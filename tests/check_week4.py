"""P2-26 check: Week 4 integration test.

Proves the Week 4 pipeline:

    incident -> approval request notification -> external decision (Slack/email/API)
             -> resume -> completed          + escalation on timeout

Deterministic (fake notifier, injected graph): no LLM, no external services.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from langgraph.graph import END, START, StateGraph
from sqlalchemy import delete, select, text

from app.approval_service import resume_incident
from app.checkpointer import make_checkpointer
from app.nodes.approval import approval, route_after_approval
from app.state import OpsFlowState, Remediation, new_incident
from db.models import Incident
from db.session import SessionLocal, engine
from integrations.escalation import process_escalations
from integrations.notifications import FakeNotifier, dispatch_approval

SERVICE = "week4-check"


def _min_graph():
    builder = StateGraph(OpsFlowState)
    builder.add_node("approval", approval)
    builder.add_edge(START, "approval")
    builder.add_conditional_edges("approval", route_after_approval, {"execute": END, "reject": END})
    return builder.compile(checkpointer=make_checkpointer("postgres"))


def _cleanup(thread_id: str) -> None:
    with SessionLocal() as session:
        session.execute(delete(Incident).where(Incident.thread_id == thread_id))
        session.commit()
    with engine.begin() as connection:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            connection.execute(text(f"DELETE FROM {table} WHERE thread_id = :tid"), {"tid": thread_id})


def main() -> None:
    thread_id = f"week4-{uuid.uuid4().hex[:8]}"
    graph = _min_graph()
    _cleanup(thread_id)

    try:
        with SessionLocal() as session:
            session.add(
                Incident(
                    thread_id=thread_id,
                    source="cloudwatch",
                    service=SERVICE,
                    tenant_id="acme",
                    error_class="OOMKilled",
                    severity="high",
                    status="pending",
                )
            )
            session.commit()

        state = new_incident(
            "oom", thread_id=thread_id, tenant_id="acme", service=SERVICE, error_class="OOMKilled"
        )
        state["proposed_remediation"] = Remediation(
            remediation_id="increase_memory_limit",
            params={"container_name": SERVICE, "new_memory_limit": "2Gi"},
            rationale="t",
        )
        state["resolved_params"] = {"container_name": SERVICE, "new_memory_limit": "2Gi"}
        state["severity"] = "high"
        state["risk_level"] = "medium"
        state["requires_approval"] = True

        paused = graph.invoke(state, {"configurable": {"thread_id": thread_id}})
        assert "__interrupt__" in paused
        summary = paused["__interrupt__"][0].value

        with SessionLocal() as session:
            incident = session.execute(
                select(Incident).where(Incident.thread_id == thread_id)
            ).scalar_one()
            incident.status = "awaiting_approval"
            incident.approval_requested_at = datetime.now(timezone.utc)
            session.commit()

        notifier = FakeNotifier()
        dispatch_approval(summary, notifiers=[notifier])
        assert len(notifier.approvals) == 1
        assert notifier.approvals[0]["service"] == SERVICE
        print("notify    -> approval request sent to", len(notifier.approvals), "channel(s)")

        result = resume_incident(thread_id=thread_id, approved=True, approver="slack:manager", graph=graph)
        assert result["status"] == "resumed" and result["graph_status"] == "approved"
        with SessionLocal() as session:
            incident = session.execute(
                select(Incident).where(Incident.thread_id == thread_id)
            ).scalar_one()
            assert incident.status == "approved"
        print("resume    -> external decision applied; incident status = approved")

        with SessionLocal() as session:
            incident = session.execute(
                select(Incident).where(Incident.thread_id == thread_id)
            ).scalar_one()
            incident.status = "awaiting_approval"
            incident.approval_requested_at = datetime.now(timezone.utc) - timedelta(minutes=40)
            incident.escalated_level = 0
            session.commit()

        fake = FakeNotifier()
        escalated = process_escalations(notifiers=[fake])
        assert escalated and escalated[0]["level"] == 2
        print("escalate  -> level", escalated[0]["level"], "->", escalated[0]["recipient"])

        print("")
        print("[ok] P2-26 -- Week 4 exit criteria pass:")
        print("     approval request -> notification -> external decision -> resume -> escalation")
    finally:
        _cleanup(thread_id)


if __name__ == "__main__":
    main()
