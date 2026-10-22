from __future__ import annotations

from app.confidence import score_confidence
from app.config import settings
from app.state import AuditEvent, OpsFlowState

AUTOMATION_THRESHOLD = 80

def score(state: OpsFlowState) -> dict:
    result = score_confidence(state)
    confidence = result.score
    loops = state.get("loop_count", 0)
    status = state.get("status", "pending")

    if confidence < settings.confidence_threshold and loops >= settings.max_loops:
        status = "escalated"

    return {
        "confidence": confidence,
        "confidence_breakdown": result.breakdown,
        "manual_review": confidence < settings.confidence_threshold,
        "automation_eligible": confidence >= AUTOMATION_THRESHOLD,
        "status": status,
        "audit": [
            AuditEvent(
                actor="agent",
                action="score",
                detail=f"confidence={confidence} breakdown={result.breakdown}",
            )
        ],
    }

def route_after_scoring(state: OpsFlowState) -> str:
    if state.get("status") == "escalated":
        return "escalate"
    if state.get("confidence", 0) >= settings.confidence_threshold:
        return "accept"
    return "refine"
