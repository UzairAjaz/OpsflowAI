from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select

from app.config import settings
from db.models import Incident
from db.session import SessionLocal
from integrations.notifications import dispatch_escalation
from observability.logging import get_logger

ESCALATION_RECIPIENTS = ["manager", "senior_manager", "cto"]

def parse_escalation_minutes() -> list[int]:
    values = [int(item) for item in settings.escalation_minutes.split(",") if item.strip()]
    return sorted(values)

class EscalationAction(BaseModel):
    level: int
    due_minutes: int
    recipient: str

def due_escalation(*, elapsed_minutes: float, current_level: int) -> EscalationAction | None:
    thresholds = parse_escalation_minutes()
    due_level = 0
    for index, threshold in enumerate(thresholds, start=1):
        if elapsed_minutes >= threshold:
            due_level = index

    if due_level == 0 or due_level <= current_level:
        return None

    recipient = ESCALATION_RECIPIENTS[min(due_level - 1, len(ESCALATION_RECIPIENTS) - 1)]
    return EscalationAction(
        level=due_level, due_minutes=thresholds[due_level - 1], recipient=recipient
    )

def process_escalations(now: datetime | None = None, notifiers=None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    escalated: list[dict] = []

    with SessionLocal() as session:
        incidents = (
            session.execute(
                select(Incident).where(Incident.status == "awaiting_approval")
            )
            .scalars()
            .all()
        )
        for incident in incidents:
            if incident.approval_requested_at is None:
                continue
            elapsed = (now - incident.approval_requested_at).total_seconds() / 60.0
            action = due_escalation(
                elapsed_minutes=elapsed, current_level=incident.escalated_level
            )
            if action is None:
                continue

            summary = {
                "thread_id": incident.thread_id,
                "tenant_id": incident.tenant_id,
                "service": incident.service,
                "severity": incident.severity,
            }
            dispatch_escalation(action.level, action.recipient, summary, notifiers=notifiers)
            incident.escalated_level = action.level
            escalated.append(
                {
                    "thread_id": incident.thread_id,
                    "level": action.level,
                    "recipient": action.recipient,
                }
            )
        session.commit()

    if escalated:
        get_logger(stage="escalation").info(f"escalated {len(escalated)} incident(s)")
    return escalated
