from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.reports import build_state_report
from app.state import AuditEvent, OpsFlowState
from db.models import AuditLog, Incident, Tenant
from db.session import SessionLocal
from observability.logging import get_logger

def generate_report(state: OpsFlowState) -> dict:
    content = build_state_report(state)
    thread_id = state.get("thread_id")

    if thread_id:
        try:
            with SessionLocal() as session:
                incident = session.execute(
                    select(Incident).where(Incident.thread_id == thread_id)
                ).scalar_one_or_none()
                if incident is not None:
                    incident.report = content
                    incident.report_generated_at = datetime.now(timezone.utc)
                    if session.get(Tenant, incident.tenant_id) is not None:
                        session.add(
                            AuditLog(
                                tenant_id=incident.tenant_id,
                                incident_id=incident.incident_id,
                                action="report.generate",
                                actor="agent",
                                details={
                                    "thread_id": thread_id,
                                    "characters": len(content),
                                },
                            )
                        )
                    session.commit()
        except Exception as exc:
            get_logger(stage="report", thread_id=thread_id).warning(
                f"report persistence failed: {exc}"
            )

    return {
        "report": content,
        "audit": [
            AuditEvent(
                actor="agent",
                action="report",
                detail=f"generated structured report ({len(content)} chars)",
            )
        ],
    }

def route_after_report(state: OpsFlowState) -> str:
    if state.get("requires_approval") and not settings.auto_approve:
        return "approval"
    return "execute"

__all__ = ["generate_report", "route_after_report"]
