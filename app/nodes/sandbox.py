from __future__ import annotations

import time

from sqlalchemy import select

from app.catalog import load_catalog
from app.config import settings
from app.safety.validate import build_argv, build_command, validate_proposal
from app.state import AuditEvent, CheckResult, ExecutionResult, OpsFlowState
from observability.logging import get_logger

_catalog = load_catalog()

def _write_execution_log(state, spec, argv, environment, passed, checks, rollback_argv) -> None:
    try:
        from db.models import ExecutionLog, Incident
        from db.session import SessionLocal

        with SessionLocal() as session:
            incident_id = None
            thread_id = state.get("thread_id")
            if thread_id:
                incident = session.execute(
                    select(Incident).where(Incident.thread_id == thread_id)
                ).scalar_one_or_none()
                incident_id = incident.incident_id if incident else None

            session.add(
                ExecutionLog(
                    incident_id=incident_id,
                    remediation_id=spec.id,
                    params=state.get("resolved_params") or {},
                    command=argv,
                    environment=environment,
                    dry_run=True,
                    approved_by=state.get("approver"),
                    exit_code=0 if passed else 1,
                    result="sandbox_passed" if passed else "sandbox_failed",
                    sandbox_checks={
                        "checks": [check.model_dump() for check in checks],
                        "rollback": rollback_argv,
                        "confidence": state.get("confidence"),
                    },
                )
            )
            session.commit()
    except Exception:
        pass

def run_sandbox(state: OpsFlowState) -> dict:
    remediation = state.get("proposed_remediation")
    result = validate_proposal(_catalog, remediation) if remediation else None
    if result is None or not result.ok:
        return {
            "validated": False,
            "status": "escalated",
            "sandbox_feedback": "invalid proposal",
            "audit": [
                AuditEvent(actor="agent", action="sandbox", detail="invalid proposal; escalated")
            ],
        }

    spec = _catalog.get(remediation.remediation_id)
    resolved = result.resolved
    argv = build_command(spec, resolved)
    rollback_argv = build_argv(spec.rollback_template, resolved) if spec.rollback_template else None

    if not spec.reversible and rollback_argv is None:
        return {
            "validated": False,
            "status": "escalated",
            "sandbox_feedback": "irreversible action without a rollback plan",
            "rollback_plan": [],
            "audit": [
                AuditEvent(
                    actor="agent",
                    action="sandbox",
                    detail="irreversible action without rollback plan; escalated",
                )
            ],
        }

    if spec.execution_mode == "simulated":
        start = time.perf_counter()
        get_logger(stage="sandbox", remediation_id=spec.id).info(
            f"simulated validation command: {' '.join(argv)}"
        )
        attempts = state.get("sandbox_attempts", 0) + 1
        _write_execution_log(state, spec, argv, "simulated", True, [], rollback_argv)
        execution = ExecutionResult(
            remediation_id=spec.id,
            command=argv,
            dry_run=True,
            exit_code=0,
            stdout="Simulated success",
            duration_ms=int((time.perf_counter() - start) * 1000),
        )
        return {
            "sandbox_result": execution,
            "sandbox_checks": {
                "environment": "simulated",
                "checks": [],
                "rollback": rollback_argv,
            },
            "rollback_plan": rollback_argv or [],
            "sandbox_attempts": attempts,
            "sandbox_feedback": None,
            "validated": True,
            "status": "validated",
            "audit": [
                AuditEvent(
                    actor="agent",
                    action="sandbox",
                    detail=f"simulated validation passed (attempt {attempts})",
                )
            ],
        }

    from integrations.sandbox import get_sandbox

    sandbox = get_sandbox()
    fix = sandbox.run(argv)

    checks: list[CheckResult] = []
    for template in spec.validation_commands:
        check_argv = build_argv(template, resolved)
        check = sandbox.run(check_argv)
        checks.append(
            CheckResult(
                command=check_argv,
                exit_code=check.exit_code,
                passed=check.exit_code == 0,
                stdout=check.stdout,
                stderr=check.stderr,
            )
        )

    passed = fix.exit_code == 0 and all(check.passed for check in checks)
    attempts = state.get("sandbox_attempts", 0) + 1
    _write_execution_log(state, spec, argv, sandbox.name, passed, checks, rollback_argv)

    if passed:
        execution = ExecutionResult(
            remediation_id=spec.id,
            command=argv,
            dry_run=True,
            exit_code=fix.exit_code,
            stdout=fix.stdout,
            stderr=fix.stderr,
            duration_ms=fix.duration_ms,
        )
        return {
            "sandbox_result": execution,
            "sandbox_checks": {
                "environment": sandbox.name,
                "checks": [check.model_dump() for check in checks],
                "rollback": rollback_argv,
            },
            "rollback_plan": rollback_argv or [],
            "sandbox_attempts": attempts,
            "sandbox_feedback": None,
            "validated": True,
            "status": "validated",
            "audit": [
                AuditEvent(
                    actor="agent",
                    action="sandbox",
                    detail=f"passed in {sandbox.name} (attempt {attempts})",
                )
            ],
        }

    feedback = f"sandbox validation failed in {sandbox.name}: fix exit={fix.exit_code}"
    if checks:
        feedback += "; " + "; ".join(
            f"{' '.join(check.command)} -> {check.exit_code}" for check in checks
        )

    if rollback_argv:
        sandbox.run(rollback_argv)

    exhausted = attempts >= settings.sandbox_max_attempts
    return {
        "sandbox_attempts": attempts,
        "sandbox_feedback": feedback,
        "rollback_plan": rollback_argv or [],
        "validated": False,
        "status": "escalated" if exhausted else "pending",
        "audit": [
            AuditEvent(
                actor="agent",
                action="sandbox",
                detail=feedback + ("; escalated" if exhausted else "; will retry"),
            )
        ],
    }

def route_after_sandbox(state: OpsFlowState) -> str:
    if state.get("validated"):
        if state.get("requires_approval") and not settings.auto_approve:
            return "approval"
        return "execute"
    if state.get("status") == "escalated":
        return "escalate"
    return "retry"
