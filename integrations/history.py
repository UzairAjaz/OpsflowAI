from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.state import ResearchResult
from db.models import FixOutcome, Incident

class PriorFix(BaseModel):
    remediation_id: str
    params: dict[str, str] = Field(default_factory=dict)
    success_rate: float
    occurrences: int
    last_applied_at: datetime | None = None

def find_prior_fix(
    session: Session,
    *,
    tenant_id: str,
    service: str,
    error_class: str,
    days: int = 30,
) -> PriorFix | None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    statement = (
        select(FixOutcome)
        .join(Incident, FixOutcome.incident_id == Incident.incident_id)
        .where(
            Incident.tenant_id == tenant_id,
            Incident.service == service,
            Incident.error_class == error_class,
            FixOutcome.applied_at >= cutoff,
        )
    )
    outcomes = session.execute(statement).scalars().all()
    if not outcomes:
        return None

    stats: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "success": 0, "last_success": None, "params": {}}
    )
    for outcome in outcomes:
        entry = stats[outcome.remediation_id]
        entry["total"] += 1
        if outcome.stable:
            entry["success"] += 1
            timestamp = outcome.verified_at or outcome.applied_at
            if entry["last_success"] is None or (
                timestamp is not None and timestamp > entry["last_success"]
            ):
                entry["last_success"] = timestamp
                entry["params"] = outcome.params or {}

    candidates = [(rid, s) for rid, s in stats.items() if s["success"] > 0]
    if not candidates:
        return None

    epoch = datetime.min.replace(tzinfo=timezone.utc)
    candidates.sort(
        key=lambda item: (
            item[1]["success"] / item[1]["total"],
            item[1]["last_success"] or epoch,
        ),
        reverse=True,
    )
    remediation_id, best = candidates[0]
    return PriorFix(
        remediation_id=remediation_id,
        params=best["params"],
        success_rate=round(best["success"] / best["total"], 3),
        occurrences=best["total"],
        last_applied_at=best["last_success"],
    )

class HistoryKnowledgeBase:

    def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        max_results: int = 5,
        service: str | None = None,
        error_class: str | None = None,
    ) -> list[ResearchResult]:
        if not service or not error_class:
            return []

        from db.session import SessionLocal

        with SessionLocal() as session:
            fix = find_prior_fix(
                session,
                tenant_id=tenant_id,
                service=service,
                error_class=error_class,
            )
        if fix is None:
            return []

        return [
            ResearchResult(
                source="history",
                title=f"Past fix: {fix.remediation_id} (success rate {fix.success_rate:.0%})",
                url=None,
                snippet=(
                    f"{fix.occurrences} prior incident(s); params={fix.params}; "
                    f"success rate {fix.success_rate:.0%}"
                ),
                score=fix.success_rate,
            )
        ]
