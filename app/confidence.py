from __future__ import annotations

from pydantic import BaseModel

from app.catalog import load_catalog
from app.state import OpsFlowState

_CATALOG = load_catalog()

WEIGHTS: dict[str, int] = {
    "kb_match": 30,
    "history_success": 20,
    "source_agreement": 15,
    "catalog_match": 15,
    "critic_score": 20,
}

class ConfidenceResult(BaseModel):
    score: int
    breakdown: dict[str, float]

def score_confidence(state: OpsFlowState) -> ConfidenceResult:
    research = state.get("research", [])
    sources = {result.source for result in research}

    kb_match = 1.0 if "kb" in sources else 0.0

    history_scores = [result.score for result in research if result.source == "history"]
    history_success = max(history_scores) if history_scores else 0.0

    source_agreement = min(len(sources) / 3.0, 1.0)

    remediation = state.get("proposed_remediation")
    catalog_match = 1.0 if remediation and remediation.remediation_id in _CATALOG.ids else 0.0

    critic_score = max(0.0, min(1.0, state.get("critic_score", 0) / 100.0))

    signals = {
        "kb_match": kb_match,
        "history_success": history_success,
        "source_agreement": source_agreement,
        "catalog_match": catalog_match,
        "critic_score": critic_score,
    }
    breakdown = {name: round(WEIGHTS[name] * value, 2) for name, value in signals.items()}
    score = max(0, min(100, int(round(sum(breakdown.values())))))
    return ConfidenceResult(score=score, breakdown=breakdown)
