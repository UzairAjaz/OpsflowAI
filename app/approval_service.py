from __future__ import annotations

from langgraph.types import Command

from db.models import Incident
from db.session import SessionLocal
from observability.logging import get_logger

def _default_graph():
    from worker.graph_runner import get_graph

    return get_graph()

def is_pending(*, thread_id: str, graph=None) -> bool:
    compiled = graph if graph is not None else _default_graph()
    snapshot = compiled.get_state({"configurable": {"thread_id": thread_id}})
    return snapshot.next == ("approval",)

def resume_incident(*, thread_id: str, approved: bool, approver: str, graph=None) -> dict:
    compiled = graph if graph is not None else _default_graph()
    config = {"configurable": {"thread_id": thread_id}}

    snapshot = compiled.get_state(config)
    if snapshot.next != ("approval",):
        return {"status": "no_pending", "thread_id": thread_id}

    result = compiled.invoke(
        Command(resume={"approved": approved, "approver": approver}), config
    )

    try:
        from sqlalchemy import select

        with SessionLocal() as session:
            incident = session.execute(
                select(Incident).where(Incident.thread_id == thread_id)
            ).scalar_one_or_none()
            if incident is not None:
                incident.status = "approved" if approved else "rejected"
                session.commit()
    except Exception:
        pass

    get_logger(stage="approval", thread_id=thread_id).info(
        f"{'approved' if approved else 'rejected'} by {approver}"
    )
    return {
        "status": "resumed",
        "thread_id": thread_id,
        "approved": approved,
        "approver": approver,
        "graph_status": result.get("status") if isinstance(result, dict) else None,
    }
