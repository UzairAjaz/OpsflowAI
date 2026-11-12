from __future__ import annotations

import argparse
import json
import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from api.main import app
from api.security import sign_payload
from app.config import settings
from db.models import AuditLog, ExecutionLog, FixOutcome, Incident, ProcessedAlert
from db.session import SessionLocal, engine
from ingestion.schema import normalize_alert
from integrations.sandbox import FakeSandbox, set_sandbox
from worker.graph_runner import get_graph
from worker.queue import get_queue
from worker.tasks import handle_new_alert

TENANT = settings.demo_tenant_id
SERVICE = settings.demo_service
ERROR_CLASS = settings.demo_error_class

def _cleanup(thread_id: str | None, signature: str | None) -> None:
    if signature:
        with SessionLocal() as session:
            session.execute(
                delete(ProcessedAlert).where(
                    ProcessedAlert.alerts_signature == signature
                )
            )
            session.commit()

    if thread_id:
        with SessionLocal() as session:
            incident = session.execute(
                select(Incident).where(Incident.thread_id == thread_id)
            ).scalar_one_or_none()
            if incident is not None:
                session.execute(
                    delete(ExecutionLog).where(
                        ExecutionLog.incident_id == incident.incident_id
                    )
                )
                session.execute(
                    delete(AuditLog).where(
                        AuditLog.incident_id == incident.incident_id
                    )
                )
                session.execute(
                    delete(FixOutcome).where(
                        FixOutcome.incident_id == incident.incident_id
                    )
                )
                session.delete(incident)
            session.commit()

    if thread_id:
        with engine.begin() as connection:
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE thread_id = :tid"),
                    {"tid": thread_id},
                )

def _run_once(run_number: int) -> None:
    run_id = uuid.uuid4().hex[:8]
    payload = {
        "source": "cloudwatch",
        "service": SERVICE,
        "tenant_id": TENANT,
        "error_class": ERROR_CLASS,
        "severity_hint": "critical",
        "raw_log": (
            f"Container {SERVICE} exited with code 137 (OOMKilled). "
            f"MediConnect demo run {run_number}, trace {run_id}."
        ),
        "event_id": f"day10-{run_number}-{run_id}",
    }
    signature = normalize_alert(payload).alerts_signature
    thread_id: str | None = None

    try:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            settings.webhook_signature_header: sign_payload(
                settings.webhook_secret, body
            ),
        }

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/webhooks/alert",
                content=body,
                headers=headers,
            )
        assert response.status_code == 202, response.text
        accepted = response.json()
        assert accepted["action"] == "new", accepted
        print(f"run {run_number}: webhook accepted ({accepted['action']})")

        get_queue().empty()

        graph = get_graph()
        started = time.perf_counter()
        worker_result = handle_new_alert(signature, payload, graph=graph)
        assert worker_result["status"] == "awaiting_approval", worker_result

        with SessionLocal() as session:
            incident = session.get(Incident, uuid.UUID(worker_result["incident_id"]))
            assert incident is not None
            thread_id = incident.thread_id
            assert incident.status == "awaiting_approval"
            assert incident.report
            report_text = incident.report

        snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
        assert snapshot.next == ("approval",)
        assert "OpsFlow Incident Report" in report_text
        print(
            f"run {run_number}: paused for approval in "
            f"{time.perf_counter() - started:.1f}s; report saved"
        )

        from app.approval_service import resume_incident

        approval_started = time.perf_counter()
        approved = resume_incident(
            thread_id=thread_id,
            approved=True,
            approver="day10-e2e",
            graph=graph,
        )
        assert approved["status"] == "resumed", approved
        assert approved["graph_status"] == "completed", approved

        completed = graph.get_state({"configurable": {"thread_id": thread_id}})
        assert completed.values.get("status") == "completed"
        execution = completed.values.get("execution_result")
        assert execution is not None and execution.exit_code == 0

        with SessionLocal() as session:
            incident = session.execute(
                select(Incident).where(Incident.thread_id == thread_id)
            ).scalar_one()
            logs = session.execute(
                select(ExecutionLog).where(
                    ExecutionLog.incident_id == incident.incident_id
                )
            ).scalars().all()
            audit = session.execute(
                select(AuditLog).where(
                    AuditLog.incident_id == incident.incident_id
                )
            ).scalars().all()

        results = {log.result for log in logs}
        actions = {entry.action for entry in audit}
        assert "executed" in results, results
        assert {"report.generate", "approval.approve", "execute"}.issubset(actions), actions
        print(
            f"run {run_number}: approved + executed in "
            f"{time.perf_counter() - approval_started:.1f}s; "
            f"logs={sorted(results)} audit={sorted(actions)}"
        )
    finally:
        set_sandbox(None)
        _cleanup(thread_id, signature)

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MediConnect end-to-end demo")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    original_dry_run = settings.dry_run
    original_auto = settings.auto_approve
    original_threshold = settings.confidence_threshold
    original_loops = settings.max_loops
    original_sandbox = settings.sandbox_backend

    try:
        settings.dry_run = False
        settings.auto_approve = False
        settings.confidence_threshold = 0
        settings.max_loops = 1
        settings.sandbox_backend = "fake"
        set_sandbox(FakeSandbox(default_exit=0))

        for run_number in range(1, args.runs + 1):
            _run_once(run_number)
            print("")

        print(f"[ok] {args.runs} MediConnect end-to-end run(s) passed.")
    finally:
        settings.dry_run = original_dry_run
        settings.auto_approve = original_auto
        settings.confidence_threshold = original_threshold
        settings.max_loops = original_loops
        settings.sandbox_backend = original_sandbox
        set_sandbox(None)

if __name__ == "__main__":
    main()
