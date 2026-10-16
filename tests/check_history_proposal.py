"""P2-14 check: history-aware proposal.

When a proven fix exists with a high success rate, the proposer should prefer it
directly (no LLM). Weak, unknown, or invalid prior fixes should not be preferred.
"""

from __future__ import annotations

from app.nodes.researcher import _CATALOG, _prior_proposal, propose
from app.state import new_incident


def _state_with_prior(prior: dict) -> dict:
    state = new_incident("oom", tenant_id="acme", service="svc", error_class="OOMKilled")
    state["prior_fix"] = prior
    return state


def main() -> None:
    strong = _state_with_prior(
        {
            "remediation_id": "increase_memory_limit",
            "params": {"container_name": "svc", "new_memory_limit": "2Gi"},
            "success_rate": 0.9,
            "occurrences": 3,
        }
    )
    candidate = _prior_proposal(strong)
    assert candidate is not None and candidate.remediation_id == "increase_memory_limit"
    print("prior     ->", candidate.remediation_id, candidate.params)

    update = propose(strong)
    proposal = update["proposed_remediation"]
    assert proposal.remediation_id == "increase_memory_limit"
    assert "source=history" in update["audit"][0].detail
    print("propose   ->", update["audit"][0].detail)

    weak = _state_with_prior(
        {
            "remediation_id": "increase_memory_limit",
            "params": {"container_name": "svc", "new_memory_limit": "2Gi"},
            "success_rate": 0.4,
            "occurrences": 2,
        }
    )
    assert _prior_proposal(weak) is None
    print("weak      -> not preferred (below threshold)")

    unknown = _state_with_prior(
        {"remediation_id": "totally_made_up", "params": {}, "success_rate": 0.99, "occurrences": 5}
    )
    assert _prior_proposal(unknown) is None
    print("unknown   -> not preferred (id not in catalog)")

    invalid_params = _state_with_prior(
        {
            "remediation_id": "restart_service",
            "params": {"wrong_param": "x"},
            "success_rate": 0.95,
            "occurrences": 3,
        }
    )
    assert _prior_proposal(invalid_params) is None
    print("bad params-> not preferred (catalog validation fails)")

    assert _CATALOG.get("increase_memory_limit") is not None
    print("[ok] P2-14 -- history-aware proposal working.")


if __name__ == "__main__":
    main()
