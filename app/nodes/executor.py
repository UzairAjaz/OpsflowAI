from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select

from app.catalog import load_catalog
from app.config import settings
from app.safety.validate import build_argv, build_command, validate_proposal
from app.state import AuditEvent, ExecutionResult, OpsFlowState, Remediation
from db.models import AuditLog, ExecutionLog, Incident, Tenant
from db.session import SessionLocal
from observability.logging import get_logger

_catalog = load_catalog()

def _write_execution_log(
    state: OpsFlowState,
    *,
    remediation_id: str,
    params: dict[str, str],
    argv: list[str],
    environment: str,
    dry_run: bool,
    exit_code: int,
    result: str,
    stdout: str = "",
    stderr: str = "",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> None:
    thread_id = state.get("thread_id")
    try:
        with SessionLocal() as session:
            incident_id = None
            tenant_id = state.get("tenant_id")
            if thread_id:
                incident = session.execute(
                    select(Incident).where(Incident.thread_id == thread_id)
                ).scalar_one_or_none()
                if incident is not None:
                    incident_id = incident.incident_id
                    tenant_id = incident.tenant_id

            session.add(
                ExecutionLog(
                    incident_id=incident_id,
                    remediation_id=remediation_id,
                    params=params,
                    command=argv,
                    environment=environment,
                    dry_run=dry_run,
                    approved_by=state.get("approver"),
                    started_at=started_at,
                    finished_at=finished_at,
                    exit_code=exit_code,
                    result=result,
                    sandbox_checks=state.get("sandbox_checks"),
                )
            )

            if tenant_id and session.get(Tenant, tenant_id) is not None:
                session.add(
                    AuditLog(
                        tenant_id=tenant_id,
                        incident_id=incident_id,
                        action=(
                            "rollback"
                            if result in ("rolled_back", "rollback_failed")
                            else "execute"
                        ),
                        actor="agent",
                        details={
                            "thread_id": thread_id,
                            "remediation_id": remediation_id,
                            "command": argv,
                            "environment": environment,
                            "dry_run": dry_run,
                            "exit_code": exit_code,
                            "result": result,
                        },
                    )
                )
            session.commit()
    except Exception as exc:
        get_logger(stage="executor").warning(f"execution log write failed: {exc}")

def _simulate_execution(
    state: OpsFlowState,
    remediation: Remediation,
    argv: list[str],
    dry_run: bool,
) -> dict:
    start = time.perf_counter()
    get_logger(stage="executor", remediation_id=remediation.remediation_id).info(
        f"simulated command: {' '.join(argv)}"
    )
    time.sleep(1)
    started_at = datetime.now(timezone.utc)
    duration_ms = int((time.perf_counter() - start) * 1000)

    _write_execution_log(
        state,
        remediation_id=remediation.remediation_id,
        params=state.get("resolved_params") or remediation.params,
        argv=argv,
        environment="simulated",
        dry_run=dry_run,
        exit_code=0,
        result="simulated",
        stdout="Simulated success",
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
    )

    execution = ExecutionResult(
        remediation_id=remediation.remediation_id,
        command=argv,
        dry_run=dry_run,
        exit_code=0,
        stdout="Simulated success",
        duration_ms=duration_ms,
    )

    return {
        "execution_result": execution,
        "status": "completed",
        "audit": [
            AuditEvent(
                actor="agent",
                action="execute",
                detail=f"simulated cmd={' '.join(argv)}",
            )
        ],
    }

def _mock_dry_run(
    state: OpsFlowState,
    remediation: Remediation,
    argv: list[str],
) -> dict:
    stdout = f"[mock] would run: {' '.join(argv)}"
    _write_execution_log(
        state,
        remediation_id=remediation.remediation_id,
        params=state.get("resolved_params") or remediation.params,
        argv=argv,
        environment="dry-run",
        dry_run=True,
        exit_code=0,
        result="dry_run",
        stdout=stdout,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )

    execution = ExecutionResult(
        remediation_id=remediation.remediation_id,
        command=argv,
        dry_run=True,
        exit_code=0,
        stdout=stdout,
        duration_ms=0,
    )

    return {
        "execution_result": execution,
        "status": "completed",
        "audit": [
            AuditEvent(
                actor="agent",
                action="execute",
                detail=f"dry_run=True cmd={' '.join(argv)}",
            )
        ],
    }

def _execute_in_sandbox(
    state: OpsFlowState,
    remediation: Remediation,
    spec,
    argv: list[str],
    resolved: dict[str, str],
) -> dict:
    from integrations.sandbox import get_sandbox

    sandbox = get_sandbox()
    params = resolved or remediation.params
    rollback_argv = (
        build_argv(spec.rollback_template, resolved)
        if spec.rollback_template
        else None
    )

    start = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    fix = sandbox.run(argv, timeout=settings.sandbox_timeout_seconds)
    duration_ms = int((time.perf_counter() - start) * 1000)
    finished_at = datetime.now(timezone.utc)

    result_name = "executed" if fix.exit_code == 0 else "failed"
    _write_execution_log(
        state,
        remediation_id=remediation.remediation_id,
        params=params,
        argv=argv,
        environment=sandbox.name,
        dry_run=False,
        exit_code=fix.exit_code,
        result=result_name,
        stdout=fix.stdout,
        stderr=fix.stderr,
        started_at=started_at,
        finished_at=finished_at,
    )

    execution = ExecutionResult(
        remediation_id=remediation.remediation_id,
        command=argv,
        dry_run=False,
        exit_code=fix.exit_code,
        stdout=fix.stdout,
        stderr=fix.stderr,
        duration_ms=duration_ms,
    )

    audit = [
        AuditEvent(
            actor="agent",
            action="execute",
            detail=(
                f"{sandbox.name} exit={fix.exit_code} "
                f"cmd={' '.join(argv)}"
            ),
        )
    ]

    if fix.exit_code == 0:
        return {
            "execution_result": execution,
            "status": "completed",
            "audit": audit,
        }

    if rollback_argv:
        rollback = sandbox.run(
            rollback_argv,
            timeout=settings.sandbox_timeout_seconds,
        )
        rollback_ok = rollback.exit_code == 0
        _write_execution_log(
            state,
            remediation_id=remediation.remediation_id,
            params=params,
            argv=rollback_argv,
            environment=f"rollback:{sandbox.name}",
            dry_run=False,
            exit_code=rollback.exit_code,
            result="rolled_back" if rollback_ok else "rollback_failed",
            stdout=rollback.stdout,
            stderr=rollback.stderr,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
        audit.append(
            AuditEvent(
                actor="agent",
                action="rollback",
                detail=(
                    f"{'rolled back' if rollback_ok else 'rollback failed'} "
                    f"exit={rollback.exit_code} cmd={' '.join(rollback_argv)}"
                ),
            )
        )

    return {
        "execution_result": execution,
        "status": "failed",
        "audit": audit,
    }

def execute(state: OpsFlowState) -> dict:
    remediation = state.get("proposed_remediation")
    if remediation is None:
        return {
            "status": "failed",
            "validation_errors": ["no remediation to execute"],
            "audit": [
                AuditEvent(actor="system", action="execute", detail="no remediation to execute")
            ],
        }

    if (
        state.get("requires_approval")
        and not settings.auto_approve
        and state.get("human_approval") is not True
    ):
        return {
            "status": "failed",
            "audit": [
                AuditEvent(
                    actor="system",
                    action="execute",
                    detail="blocked: approval required but not granted",
                )
            ],
        }

    result = validate_proposal(_catalog, remediation)
    if not result.ok:
        return {
            "status": "failed",
            "validation_errors": result.errors,
            "audit": [
                AuditEvent(
                    actor="system",
                    action="execute",
                    detail="blocked invalid proposal -> " + "; ".join(result.errors),
                )
            ],
        }

    spec = _catalog.get(remediation.remediation_id)
    argv = build_command(spec, result.resolved)
    dry_run = settings.dry_run

    if spec.execution_mode == "simulated":
        return _simulate_execution(state, remediation, argv, dry_run)

    if dry_run:
        return _mock_dry_run(state, remediation, argv)

    return _execute_in_sandbox(state, remediation, spec, argv, result.resolved)
