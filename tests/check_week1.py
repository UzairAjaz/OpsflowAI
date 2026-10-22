from __future__ import annotations

import json
import subprocess
import sys
import time

from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from rq import SimpleWorker
from sqlalchemy import delete, select, text

from api.main import app
from api.security import sign_payload
from app.checkpointer import make_checkpointer
from app.config import settings
from app.nodes.approval import approval, route_after_approval
from app.nodes.risk import classify, route_after_risk
from app.state import AuditEvent, OpsFlowState, Remediation
from db.models import Incident, ProcessedAlert
from db.session import SessionLocal, engine
from worker.queue import get_connection, get_queue

def _preflight(state: OpsFlowState) -> dict:
    return {
        "diagnosis": "OOM killed",
        "root_cause": "memory limit too low",
        "severity": "high",
        "evidence": ["exit code 137", "OOMKilled"],
        "proposed_remediation": Remediation(
            remediation_id="increase_memory_limit",
            params={"container_name": "retriva-backend", "new_memory_limit": "2Gi"},
            rationale="integration test",
        ),
        "critic_score": 85,
        "confidence": 85,
        "audit": [AuditEvent(actor="agent", action="analyze", detail="preflight")],
    }

def build_week1_graph():
    builder = StateGraph(OpsFlowState)
    builder.add_node("preflight", _preflight)
    builder.add_node("risk", classify)
    builder.add_node("approval", approval)
    builder.add_edge(START, "preflight")
    builder.add_edge("preflight", "risk")
    builder.add_conditional_edges(
        "risk",
        route_after_risk,
        {"execute": END, "await_approval": "approval", "reject": END},
    )
    builder.add_conditional_edges(
        "approval",
        route_after_approval,
        {"execute": END, "reject": END},
    )
    return builder.compile(checkpointer=make_checkpointer("postgres"))

def _resume(thread_id: str) -> None:
    graph = build_week1_graph()
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    if snapshot.next != ("approval",):
        print("not paused at approval:", snapshot.next)
        sys.exit(1)
    result = graph.invoke(
        Command(resume={"approved": True, "approver": "week1-integration"}), config
    )
    print("resume: status =", result.get("status"))
    if result.get("status") not in ("approved", "completed"):
        sys.exit(1)

def _cleanup(service: str) -> None:
    get_queue().empty()
    with SessionLocal() as session:
        incidents = (
            session.execute(select(Incident).where(Incident.service == service)).scalars().all()
        )
        thread_ids = [incident.thread_id for incident in incidents]
        session.execute(delete(ProcessedAlert).where(ProcessedAlert.service == service))
        for incident in incidents:
            session.delete(incident)
        session.commit()

    if thread_ids:
        with engine.begin() as connection:
            for thread_id in thread_ids:
                for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                    connection.execute(
                        text(f"DELETE FROM {table} WHERE thread_id = :tid"), {"tid": thread_id}
                    )

def _post(client: TestClient, payload: dict):
    body = json.dumps(payload).encode("utf-8")
    return client.post(
        "/api/v1/webhooks/alert",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature": sign_payload(settings.webhook_secret, body),
        },
    )

def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "resume":
        _resume(args[1])
        return

    service = f"week1-{int(time.time())}"
    payload = {
        "source": "cloudwatch",
        "service": service,
        "error_class": "OOMKilled",
        "severity_hint": "critical",
        "raw_log": "container exited with code 137 (OOM Killed)",
    }

    _cleanup(service)
    try:
        with TestClient(app) as client:
            first = _post(client, payload)
            replay = _post(client, payload)
        assert first.status_code == 202 and first.json()["action"] == "new", first.text
        assert replay.status_code == 202 and replay.json()["action"] == "duplicate", replay.text
        print("webhook   -> new, then duplicate (deduped)")

        import worker.graph_runner as graph_runner

        graph_runner.get_graph = build_week1_graph

        worker = SimpleWorker([get_queue()], connection=get_connection())
        worker.work(burst=True)
        print("worker    -> processed queued alert")

        with SessionLocal() as session:
            row = session.execute(
                select(ProcessedAlert).where(ProcessedAlert.service == service)
            ).scalars().first()
            assert row is not None and row.incident_id is not None
            incident = session.get(Incident, row.incident_id)
            thread_id = incident.thread_id
            assert incident.status == "awaiting_approval", incident.status
        print("incident  -> created and paused; status =", incident.status)

        resumed = subprocess.run(
            [sys.executable, "-m", "tests.check_week1", "resume", thread_id],
            capture_output=True,
            text=True,
        )
        print("restart   ->", resumed.stdout.strip())
        if resumed.returncode != 0:
            print(resumed.stderr)
            raise SystemExit("resume phase failed")
        assert "approved" in resumed.stdout

        print("")
        print("[ok] P2-09 -- Week 1 exit criteria pass:")
        print("     signed alert -> dedupe -> incident -> graph -> approval pause -> resume")
    finally:
        _cleanup(service)

if __name__ == "__main__":
    main()
