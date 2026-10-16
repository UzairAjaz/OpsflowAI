from __future__ import annotations

from app.catalog import load_catalog
from app.config import settings
from app.safety.validate import validate_proposal
from app.state import AuditEvent, OpsFlowState

_catalog = load_catalog()

def classify(state: OpsFlowState) -> dict:
    remediation = state.get("proposed_remediation")

    result = validate_proposal(_catalog, remediation)

    if not result.ok:
        return {
            "proposal_valid": False,
            "validation_errors": result.errors,
            "risk_level": "high",
            "requires_approval": True,
            "status": "escalated",
            "audit": [
                AuditEvent(
                    actor="agent",
                    action="risk",
                    detail="INVALID proposal -> " + "; ".join(result.errors),
                )
            ],
        }

    spec = _catalog.get(remediation.remediation_id)
    requires_approval = spec.risk != "safe" or not spec.reversible

    status = state.get("status", "pending")
    if requires_approval and not settings.auto_approve:
        status = "awaiting_approval"

    return {
        "proposal_valid": True,
        "validation_errors": [],
        "resolved_params": result.resolved,
        "risk_level": spec.risk,
        "requires_approval": requires_approval,
        "status": status,
        "audit": [
            AuditEvent(
                actor="agent",
                action="risk",
                detail=f"{spec.risk} (reversible={spec.reversible}); "
                f"requires_approval={requires_approval}",
            )
        ],
    }

def route_after_risk(state: OpsFlowState) -> str:

    if not state.get("proposal_valid", False):
        return "reject"
    if state.get("requires_approval") and not settings.auto_approve:
        return "await_approval"
    return "execute"
