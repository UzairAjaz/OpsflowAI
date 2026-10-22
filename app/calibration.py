from __future__ import annotations

from sqlalchemy import select

from db.models import FixOutcome
from db.session import SessionLocal

BUCKETS = ("low (0-59)", "medium (60-79)", "high (80-100)")

def _bucket(confidence: int) -> str:
    if confidence < 60:
        return BUCKETS[0]
    if confidence < 80:
        return BUCKETS[1]
    return BUCKETS[2]

def calibration_report() -> dict:
    with SessionLocal() as session:
        outcomes = session.execute(select(FixOutcome)).scalars().all()

    counts: dict[str, list[int]] = {name: [0, 0] for name in BUCKETS}
    for outcome in outcomes:
        if outcome.confidence is None:
            continue
        entry = counts[_bucket(int(outcome.confidence))]
        entry[0] += 1
        if outcome.stable:
            entry[1] += 1

    report = {
        name: {
            "total": total,
            "success": success,
            "success_rate": (round(success / total, 3) if total else None),
        }
        for name, (total, success) in counts.items()
    }

    high = report["high (80-100)"]
    suggested_threshold = 80
    if high["total"] and high["success_rate"] is not None and high["success_rate"] < 0.8:
        suggested_threshold = 85

    return {"buckets": report, "suggested_automation_threshold": suggested_threshold}
