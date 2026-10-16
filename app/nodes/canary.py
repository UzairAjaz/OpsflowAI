"""Canary node: progressive production rollout with automatic rollback.

After the fix is applied in production (the executor), this node rolls it out
progressively (10% -> 100%) with metric gates. If a stage breaches the error
rate or latency threshold, the rollout is abandoned and the incident is marked
`rolled_back`.
"""

from __future__ import annotations

from app.config import settings
from app.state import AuditEvent, OpsFlowState


def run_canary(state: OpsFlowState) -> dict:
    from integrations.canary import (
        get_canary_controller,
        get_metrics_provider,
        parse_canary_steps,
    )

    service = state.get("service") or "unknown"
    steps = parse_canary_steps()

    outcome = get_canary_controller().run(
        service=service,
        steps=steps,
        error_rate_threshold=settings.canary_error_rate_threshold,
        p95_threshold_ms=settings.canary_p95_threshold_ms,
        metrics=get_metrics_provider(),
    )

    stages = [stage.model_dump() for stage in outcome.stages]

    if outcome.status == "rolled_back":
        return {
            "canary_result": outcome.model_dump(),
            "canary_stages": stages,
            "status": "rolled_back",
            "rollback_plan": state.get("rollback_plan") or [],
            "audit": [
                AuditEvent(
                    actor="agent",
                    action="canary",
                    detail=f"rolled back: {outcome.rollback_reason}",
                )
            ],
        }

    return {
        "canary_result": outcome.model_dump(),
        "canary_stages": stages,
        "status": "completed",
        "audit": [
            AuditEvent(actor="agent", action="canary", detail=f"promoted through {steps}")
        ],
    }
