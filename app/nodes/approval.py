from __future__ import annotations

from langgraph.types import interrupt

from app.catalog import load_catalog
from app.state import AuditEvent, OpsFlowState

_catalog = load_catalog()

def approval(state: OpsFlowState) -> dict:
    remediation = state.get("proposed_remediation")
    spec = _catalog.get(remediation.remediation_id) if remediation else None

    payload = {
        "question": "Approve this remediation? (yes/no)",
        "thread_id": state.get("thread_id"),
        "diagnosis": state.get("diagnosis"),
        "root_cause": state.get("root_cause"),
        "severity": state.get("severity"),
        "tenant_id": state.get("tenant_id"),
        "service": state.get("service"),
        "error_class": state.get("error_class"),
        "risk_level": state.get("risk_level"),
        "reversible": spec.reversible if spec else None,
        "remediation_id": remediation.remediation_id if remediation else None,
        "params": state.get("resolved_params") or (remediation.params if remediation else {}),
        "rationale": remediation.rationale if remediation else None,
        "critic_score": state.get("critic_score"),
        "validated": state.get("validated"),
        "sandbox": state.get("sandbox_checks"),
    }

    decision = interrupt(payload)

    if isinstance(decision, dict):
        approved = bool(decision.get("approved"))
        approver = decision.get("approver")
    else:
        approved = bool(decision)
        approver = None

    return {
        "human_approval": approved,
        "approver": approver,
        "status": "approved" if approved else "rejected",
        "audit": [
            AuditEvent(
                actor="human",
                action="approve" if approved else "reject",
                detail=f"approver={approver} remediation={remediation.remediation_id if remediation else None}",
            )
        ],
    }

def route_after_approval(state: OpsFlowState) -> str:

    return "execute" if state.get("human_approval") else "reject"
