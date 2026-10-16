from __future__ import annotations

from app.catalog import load_catalog
from app.safety.validate import build_command, validate_proposal
from app.state import Remediation

def main() -> None:
    cat = load_catalog()

    print("=== catalog ids ===")
    print(cat.ids)

    print(cat.describe())

    print("\n=== valid proposal ===")
    good = Remediation(
        remediation_id="increase_memory_limit",
        params={"container_name": "retriva-backend", "new_memory_limit": "2Gi"},
        rationale="x",
    )
    r = validate_proposal(cat, good)
    print("ok:", r.ok, "resolved:", r.resolved)
    spec = cat.get("increase_memory_limit")
    print("argv:", build_command(spec, r.resolved))
    assert r.ok and build_command(spec, r.resolved) == [
        "docker", "update", "--memory", "2Gi", "retriva-backend",
    ]

    ok_enum = Remediation(remediation_id="restart_service", params={"service_name": "nginx"}, rationale="x")
    assert validate_proposal(cat, ok_enum).ok

    print("\n=== invalid proposals (all must be blocked) ===")
    bad = [
        Remediation(remediation_id="totally_made_up", params={}, rationale="x"),
        Remediation(remediation_id="increase_memory_limit", params={"container_name": "x"}, rationale="x"),
        Remediation(
            remediation_id="increase_memory_limit",
            params={"container_name": "x", "new_memory_limit": "lots"},
            rationale="x",
        ),
        Remediation(remediation_id="restart_service", params={"service_name": "hacker-svc"}, rationale="x"),
        Remediation(remediation_id="inspect_disk", params={"extra": "1"}, rationale="x"),
    ]
    for b in bad:
        res = validate_proposal(cat, b)
        print(f"[{'BLOCKED' if not res.ok else 'ALLOWED!'}] {b.remediation_id}: {res.errors}")
        assert not res.ok, f"should have been blocked: {b}"

    print("\n[ok] Step 9 -- catalog + validator working.")

if __name__ == "__main__":
    main()
