from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.config import settings
from app.nodes.executor import execute
from app.state import Remediation, new_incident
from db.models import AuditLog, ExecutionLog, Incident
from db.session import SessionLocal
from integrations.sandbox import CommandResult, FakeSandbox, set_sandbox

TENANT = "mediconnect"
SERVICE = "mediconnect-backend"

class FailingThenOkSandbox:
    name = "fake-fail-once"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, argv, *, timeout=None):
        self.calls += 1
        code = 1 if self.calls == 1 else 0
        return CommandResult(command=argv, exit_code=code, stdout="rollback ok" if code == 0 else "failed")

class ExplodingSandbox:
    name = "exploding"

    def run(self, argv, *, timeout=None):
        raise AssertionError(f"simulated action must not run: {argv}")

def _state() -> dict:
    state = new_incident(
        "container out of memory",
        tenant_id=TENANT,
        service=SERVICE,
        error_class="OOMKilled",
    )
    state["proposed_remediation"] = Remediation(
        remediation_id="increase_memory_limit",
        params={"container_name": SERVICE, "new_memory_limit": "2Gi"},
        rationale="test",
    )
    state["resolved_params"] = {
        "container_name": SERVICE,
        "new_memory_limit": "2Gi",
    }
    state["requires_approval"] = False
    state["severity"] = "high"
    state["risk_level"] = "medium"
    state["validated"] = True
    return state

def _cleanup(thread_id: str) -> None:
    with SessionLocal() as session:
        session.execute(
            delete(ExecutionLog).where(
                ExecutionLog.incident_id
                == select(Incident.incident_id)
                .where(Incident.thread_id == thread_id)
                .scalar_subquery()
            )
        )
        session.execute(
            delete(AuditLog).where(AuditLog.details["thread_id"].astext == thread_id)
        )
        incident = session.execute(
            select(Incident).where(Incident.thread_id == thread_id)
        ).scalar_one_or_none()
        if incident is not None:
            session.delete(incident)
        session.commit()

def _add_incident(thread_id: str) -> None:
    with SessionLocal() as session:
        session.add(
            Incident(
                thread_id=thread_id,
                source="cloudwatch",
                service=SERVICE,
                tenant_id=TENANT,
                error_class="OOMKilled",
                severity="high",
                status="pending",
            )
        )
        session.commit()

def main() -> None:
    original_dry_run = settings.dry_run
    thread_ids: list[str] = []

    try:
        settings.dry_run = False
        state = _state()
        thread_ids.append(state["thread_id"])
        _add_incident(state["thread_id"])
        set_sandbox(FakeSandbox(default_exit=0))
        update = execute(state)
        assert update["status"] == "completed", update
        assert update["execution_result"].exit_code == 0
        assert update["execution_result"].stdout.startswith("[fake]")
        with SessionLocal() as session:
            logs = session.execute(
                select(ExecutionLog).where(
                    ExecutionLog.incident_id
                    == select(Incident.incident_id)
                    .where(Incident.thread_id == state["thread_id"])
                    .scalar_subquery()
                )
            ).scalars().all()
        assert any(log.result == "executed" for log in logs)
        print("execute    -> sandbox success; audit log written")

        failing_state = _state()
        thread_ids.append(failing_state["thread_id"])
        _add_incident(failing_state["thread_id"])
        set_sandbox(FailingThenOkSandbox())
        failed = execute(failing_state)
        assert failed["status"] == "failed", failed
        assert failed["execution_result"].exit_code == 1
        with SessionLocal() as session:
            logs = session.execute(
                select(ExecutionLog).where(
                    ExecutionLog.incident_id
                    == select(Incident.incident_id)
                    .where(Incident.thread_id == failing_state["thread_id"])
                    .scalar_subquery()
                )
            ).scalars().all()
        results = {log.result for log in logs}
        assert {"failed", "rolled_back"}.issubset(results), results
        assert any(event.action == "rollback" for event in failed["audit"])
        print("rollback   -> failed execution rolled back and logged")

        dry_state = _state()
        thread_ids.append(dry_state["thread_id"])
        _add_incident(dry_state["thread_id"])
        settings.dry_run = True
        set_sandbox(FakeSandbox(default_exit=0))
        dry = execute(dry_state)
        assert dry["status"] == "completed"
        assert dry["execution_result"].stdout.startswith("[mock] would run")
        print("dry-run    -> no sandbox execution")

        sim_state = _state()
        sim_state["proposed_remediation"] = Remediation(
            remediation_id="run_python_script",
            params={
                "script_path": "scripts/reset_db_pool.py",
                "args": "--service mediconnect-backend",
            },
            rationale="simulated",
        )
        sim_state["resolved_params"] = {
            "script_path": "scripts/reset_db_pool.py",
            "args": "--service mediconnect-backend",
        }
        thread_ids.append(sim_state["thread_id"])
        _add_incident(sim_state["thread_id"])
        settings.dry_run = False
        set_sandbox(ExplodingSandbox())
        sim = execute(sim_state)
        assert sim["status"] == "completed"
        assert sim["execution_result"].stdout == "Simulated success"
        print("simulated  -> no external execution")

        print("[ok] Day 9 execution, rollback, and audit checks passed.")
    finally:
        settings.dry_run = original_dry_run
        set_sandbox(None)
        for thread_id in thread_ids:
            _cleanup(thread_id)

if __name__ == "__main__":
    main()
