from __future__ import annotations

from app.safety.redact import redact
from app.state import AuditEvent, OpsFlowState

def intake(state: OpsFlowState) -> dict:
    raw = state.get("error_log", "")
    redacted, counts = redact(raw)

    total = sum(counts.values())
    detail = f"redacted {total} item(s): {counts}" if total else "no secrets/PII found"

    return {
        "redacted_log": redacted,
        "redactions": counts,
        "status": "pending",
        "audit": [AuditEvent(actor="system", action="intake", detail=detail)],
    }
