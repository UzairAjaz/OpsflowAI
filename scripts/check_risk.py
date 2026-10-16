from __future__ import annotations

from app.nodes.risk import classify, route_after_risk
from app.state import Remediation, new_incident

def run(remediation: Remediation, severity: str = "high") -> dict:
    st = new_incident("test")
    st["proposed_remediation"] = remediation
    st["severity"] = severity
    update = classify(st)
    return {**st, **update}

def main() -> None:

    s = run(Remediation(remediation_id="inspect_disk", params={}, rationale="x"))
    print(f"inspect_disk         -> risk={s['risk_level']:<6} approval={s['requires_approval']} route={route_after_risk(s)}")
    assert s["risk_level"] == "safe" and not s["requires_approval"]
    assert route_after_risk(s) == "execute"

    s = run(
        Remediation(
            remediation_id="increase_memory_limit",
            params={"container_name": "retriva-backend", "new_memory_limit": "2Gi"},
            rationale="x",
        )
    )
    print(f"increase_memory_limit-> risk={s['risk_level']:<6} approval={s['requires_approval']} route={route_after_risk(s)}")
    assert s["risk_level"] == "medium" and s["requires_approval"]
    assert route_after_risk(s) == "await_approval"

    s = run(Remediation(remediation_id="delete_volume", params={"volume_name": "data"}, rationale="x"))
    print(f"delete_volume        -> risk={s['risk_level']:<6} approval={s['requires_approval']} route={route_after_risk(s)}")
    assert s["risk_level"] == "high" and s["requires_approval"]

    s = run(Remediation(remediation_id="totally_made_up", params={}, rationale="x"))
    print(f"totally_made_up      -> valid={s['proposal_valid']} status={s['status']} route={route_after_risk(s)}")
    assert s["proposal_valid"] is False and s["status"] == "escalated"
    assert route_after_risk(s) == "reject"

    print("\n[ok] Step 9 -- catalog-driven risk + routing working.")

if __name__ == "__main__":
    main()
