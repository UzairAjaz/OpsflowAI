"""P2-08 check: incident creation and queue worker.

Verifies:
- a new alert can be enqueued exactly once (deterministic job id),
- a worker (burst mode) processes the job and creates an incident,
- the graph runs for the incident,
- re-delivering the job does not create a second incident.
"""

from __future__ import annotations

import time

from langgraph.graph import END, START, StateGraph
from rq import SimpleWorker
from sqlalchemy import delete, func, select, text

from app.checkpointer import make_checkpointer
from app.state import OpsFlowState
from db.models import Incident, ProcessedAlert
from db.session import SessionLocal, engine
from ingestion.service import ingest_payload
from worker.graph_runner import run_incident  # noqa: F401  (kept for clarity)
from worker.queue import enqueue_incident, get_connection, get_queue

STUB_RUNS: list[str] = []


def _stub_node(state: OpsFlowState) -> dict:
    STUB_RUNS.append(str(state.get("thread_id")))
    return {"status": "completed"}


def build_stub_graph():
    builder = StateGraph(OpsFlowState)
    builder.add_node("stub", _stub_node)
    builder.add_edge(START, "stub")
    builder.add_edge("stub", END)
    return builder.compile(checkpointer=make_checkpointer("memory"))


def _cleanup(service: str) -> None:
    get_queue().empty()
    with SessionLocal() as session:
        incidents = (
            session.execute(select(Incident).where(Incident.service == service))
            .scalars()
            .all()
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
                        text(f"DELETE FROM {table} WHERE thread_id = :tid"),
                        {"tid": thread_id},
                    )


def main() -> None:
    service = f"worker-check-{int(time.time())}"
    payload = {
        "source": "cloudwatch",
        "service": service,
        "error_class": "OOMKilled",
        "severity_hint": "critical",
        "raw_log": "container exited with code 137 (OOM)",
    }

    _cleanup(service)
    try:
        ingested = ingest_payload(payload)
        assert ingested.action == "new", ingested.action
        signature = ingested.alert.alerts_signature
        print("ingest    -> action =", ingested.action)

        job = enqueue_incident(signature, payload)
        queue = get_queue()
        print(f"enqueue   -> job_id={job.id} queue_count={queue.count}")
        assert job.id == f"incident_{signature}"
        assert queue.count == 1

        import worker.graph_runner as graph_runner

        graph_runner.get_graph = lambda: build_stub_graph()

        worker = SimpleWorker([queue], connection=get_connection())
        worker.work(burst=True)
        print("worker    -> burst finished")

        with SessionLocal() as session:
            row = session.get(ProcessedAlert, signature)
            assert row is not None and row.incident_id is not None
            incident = session.get(Incident, row.incident_id)
            assert incident is not None and incident.service == service
            print("incident  -> created", str(incident.incident_id), "status =", incident.status)

        assert STUB_RUNS, "the graph did not run for the incident"
        print("graph     -> ran for thread", STUB_RUNS[-1])

        from worker.tasks import handle_new_alert

        again = handle_new_alert(signature, payload, graph=None)
        assert again["status"] == "skipped", again
        print("redeliver ->", again["status"])

        with SessionLocal() as session:
            count = session.execute(
                select(func.count()).select_from(Incident).where(Incident.service == service)
            ).scalar_one()
        assert count == 1, count
        print("idempotent-> incident count =", count)

        print("[ok] P2-08 -- incident creation and queue worker working.")
    finally:
        _cleanup(service)


if __name__ == "__main__":
    main()
