from __future__ import annotations

import time

from app.catalog import load_catalog
from app.config import settings
from app.safety.validate import build_command, validate_proposal
from app.state import AuditEvent, ExecutionResult, OpsFlowState, Remediation
from observability.logging import get_logger

_catalog = load_catalog()

def _simulate_execution(remediation: Remediation, argv: list[str], dry_run: bool) -> dict:
    start = time.perf_counter()
    get_logger(stage="executor", remediation_id=remediation.remediation_id).info(
        f"simulated command: {' '.join(argv)}"
    )
    time.sleep(1)

    execution = ExecutionResult(
        remediation_id=remediation.remediation_id,
        command=argv,
        dry_run=dry_run,
        exit_code=0,
        stdout="Simulated success",
        duration_ms=int((time.perf_counter() - start) * 1000),
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
        return _simulate_execution(remediation, argv, dry_run)

    execution = ExecutionResult(
        remediation_id=remediation.remediation_id,
        command=argv,
        dry_run=dry_run,
        exit_code=0,
        stdout=f"[mock] {'would run' if dry_run else 'ran'}: {' '.join(argv)}",
        duration_ms=0,
    )

    return {
        "execution_result": execution,
        "status": "completed",
        "audit": [
            AuditEvent(
                actor="agent",
                action="execute",
                detail=f"dry_run={dry_run} cmd={' '.join(argv)}",
            )
        ],
    }
