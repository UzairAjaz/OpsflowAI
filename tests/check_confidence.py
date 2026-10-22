from __future__ import annotations

from app.confidence import WEIGHTS, score_confidence
from app.config import settings
from app.nodes.scoring import route_after_scoring, score
from app.state import Remediation, ResearchResult, new_incident

def _full_state() -> dict:
    state = new_incident("x")
    state["research"] = [
        ResearchResult(source="kb", title="kb", snippet="s", score=0.9),
        ResearchResult(source="web", title="web", snippet="s", score=0.5),
        ResearchResult(source="history", title="history", snippet="s", score=0.8),
    ]
    state["proposed_remediation"] = Remediation(
        remediation_id="increase_memory_limit", params={}, rationale="x"
    )
    state["critic_score"] = 90
    return state

def main() -> None:
    full = score_confidence(_full_state())
    print("full   ->", full.score, full.breakdown)
    assert full.score == 94, full.score
    assert set(full.breakdown) == set(WEIGHTS)
    assert abs(sum(full.breakdown.values()) - full.score) < 1.5

    weak_state = new_incident("x")
    weak_state["critic_score"] = 40
    weak = score_confidence(weak_state)
    print("weak   ->", weak.score, weak.breakdown)
    assert weak.score == 8, weak.score

    full_state = _full_state()
    full_update = score(full_state)
    assert full_update["confidence"] == 94
    assert full_update["automation_eligible"] is True
    assert full_update["manual_review"] is False
    assert route_after_scoring({**full_state, **full_update}) == "accept"
    print(
        "node   -> confidence",
        full_update["confidence"],
        "automation_eligible",
        full_update["automation_eligible"],
    )

    low_state = new_incident("x")
    low_state["critic_score"] = 40
    low_state["loop_count"] = settings.max_loops
    low_update = score(low_state)
    assert low_update["manual_review"] is True
    assert low_update["status"] == "escalated"
    assert route_after_scoring({**low_state, **low_update}) == "escalate"
    print(
        "node   -> confidence",
        low_update["confidence"],
        "status",
        low_update["status"],
        "manual_review",
        low_update["manual_review"],
    )

    mid_state = new_incident("x")
    mid_state["research"] = [
        ResearchResult(source="kb", title="kb", snippet="s", score=0.9),
        ResearchResult(source="web", title="web", snippet="s", score=0.5),
    ]
    mid_state["proposed_remediation"] = Remediation(
        remediation_id="increase_memory_limit", params={}, rationale="x"
    )
    mid_state["critic_score"] = 75
    mid_update = score(mid_state)
    assert mid_update["confidence"] == 70, mid_update["confidence"]
    assert mid_update["manual_review"] is False
    assert mid_update["automation_eligible"] is False
    print(
        "mid    ->",
        mid_update["confidence"],
        "manual_review",
        mid_update["manual_review"],
        "automation_eligible",
        mid_update["automation_eligible"],
    )

    print("[ok] P2-13 -- rubric confidence scoring working.")

if __name__ == "__main__":
    main()
