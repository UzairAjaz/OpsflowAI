from __future__ import annotations

from sqlalchemy import delete, select

from app.nodes.sandbox import route_after_sandbox, run_sandbox
from app.state import Remediation, new_incident
from db.models import ExecutionLog
from db.session import SessionLocal
from integrations.sandbox import DockerSandbox, FakeSandbox, set_sandbox

REMEDIATIONS = ["inspect_disk", "increase_memory_limit", "delete_volume"]

def _state(remediation_id: str, params: dict, severity: str = "high") -> dict:
    state = new_incident(
        "oom", tenant_id="acme", service="checkout-api", error_class="OOMKilled"
    )
    state["proposed_remediation"] = Remediation(
        remediation_id=remediation_id, params=params, rationale="test"
    )
    state["severity"] = severity
    return state

def _cleanup_logs() -> None:
    with SessionLocal() as session:
        session.execute(delete(ExecutionLog).where(ExecutionLog.remediation_id.in_(REMEDIATIONS)))
        session.commit()

def main() -> None:
    _cleanup_logs()

    set_sandbox(FakeSandbox(default_exit=0))
    safe = _state("inspect_disk", {})
    safe["requires_approval"] = False
    update = run_sandbox(safe)
    assert update["validated"] is True
    assert update["sandbox_result"].command == ["df", "-h"]
    assert route_after_sandbox({**safe, **update}) == "execute"
    print("pass        ->", update["audit"][0].detail)

    medium = _state(
        "increase_memory_limit", {"container_name": "checkout-api", "new_memory_limit": "2Gi"}
    )
    medium["requires_approval"] = True
    update = run_sandbox(medium)
    assert update["validated"] is True
    assert update["rollback_plan"] == ["docker", "update", "--memory", "512Mi", "checkout-api"]
    assert route_after_sandbox({**medium, **update}) == "approval"
    print("validated   ->", update["audit"][0].detail, "| rollback:", update["rollback_plan"])

    set_sandbox(FakeSandbox({"docker": 1}))
    failing = _state(
        "increase_memory_limit", {"container_name": "checkout-api", "new_memory_limit": "2Gi"}
    )
    failing["requires_approval"] = True
    first = run_sandbox(failing)
    assert first["validated"] is False and first["status"] == "pending"
    assert route_after_sandbox({**failing, **first}) == "retry"
    second = run_sandbox({**failing, **first})
    assert second["status"] == "escalated"
    assert route_after_sandbox({**failing, **first, **second}) == "escalate"
    print("fail        -> retry then escalate")

    set_sandbox(FakeSandbox(default_exit=0))
    irreversible = _state("delete_volume", {"volume_name": "data"})
    update = run_sandbox(irreversible)
    assert update["validated"] is False and update["status"] == "escalated"
    assert "rollback" in update["sandbox_feedback"]
    print("irreversible-> escalated (no rollback plan)")

    with SessionLocal() as session:
        logs = (
            session.execute(
                select(ExecutionLog).where(ExecutionLog.remediation_id.in_(REMEDIATIONS))
            )
            .scalars()
            .all()
        )
    assert logs, "no execution logs written"
    print("audit       ->", len(logs), "execution log(s)")

    set_sandbox(DockerSandbox(image="alpine:3.20", timeout=60, network=False))
    real = _state("inspect_disk", {})
    real["requires_approval"] = False
    result = run_sandbox(real)
    assert result["validated"] is True, result.get("sandbox_feedback")
    print("docker      -> real container ran df -h (exit", result["sandbox_result"].exit_code, ")")

    set_sandbox(None)
    _cleanup_logs()
    print("[ok] P2-16..P2-19 -- sandbox execution, validation, rollback, audit working.")

if __name__ == "__main__":
    main()
