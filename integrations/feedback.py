from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from db.models import ExecutionLog, FixOutcome, Incident
from db.session import SessionLocal

SUCCESS_STATUSES = ("completed", "approved")
OBSERVED_STATUSES = ("completed", "approved", "rolled_back")

def process_feedback(*, now: datetime | None = None, horizon_hours: int | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    horizon = horizon_hours if horizon_hours is not None else settings.feedback_horizon_hours
    cutoff = now - timedelta(hours=horizon)
    recorded: list[dict] = []

    with SessionLocal() as session:
        incidents = (
            session.execute(
                select(Incident).where(
                    Incident.status.in_(OBSERVED_STATUSES),
                    Incident.created_at <= cutoff,
                )
            )
            .scalars()
            .all()
        )

        for incident in incidents:
            existing = session.execute(
                select(FixOutcome).where(FixOutcome.incident_id == incident.incident_id)
            ).scalar_one_or_none()
            if existing is not None:
                continue

            logs = (
                session.execute(
                    select(ExecutionLog).where(ExecutionLog.incident_id == incident.incident_id)
                )
                .scalars()
                .all()
            )
            latest = logs[-1] if logs else None
            stable = incident.status in SUCCESS_STATUSES
            outcome = "success" if stable else "failure"

            session.add(
                FixOutcome(
                    incident_id=incident.incident_id,
                    remediation_id=(latest.remediation_id if latest else "unknown"),
                    params=(latest.params if latest else {}),
                    outcome=outcome,
                    confidence=((latest.sandbox_checks or {}).get("confidence") if latest else None),
                    applied_at=incident.created_at,
                    verified_at=now,
                    stable=stable,
                )
            )
            recorded.append(
                {"thread_id": incident.thread_id, "outcome": outcome, "stable": stable}
            )

        session.commit()

    return recorded
