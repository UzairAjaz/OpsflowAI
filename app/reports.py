from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.catalog import load_catalog
from app.config import settings
from app.safety.validate import build_command
from app.state import OpsFlowState
from db.models import ExecutionLog, FixOutcome, Incident
from db.session import SessionLocal

_catalog = load_catalog()

def _get(obj, name: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)

def build_state_report(state: OpsFlowState) -> str:
    remediation = state.get("proposed_remediation")
    params = state.get("resolved_params") or (
        remediation.params if remediation else {}
    )
    spec = _catalog.get(remediation.remediation_id) if remediation else None

    command: list[str] = []
    if spec is not None:
        try:
            command = build_command(spec, params)
        except Exception:
            command = []

    evidence = state.get("evidence") or []
    checks = state.get("sandbox_checks") or {}
    check_rows = checks.get("checks") or [] if isinstance(checks, dict) else []
    rollback = state.get("rollback_plan") or (
        checks.get("rollback") if isinstance(checks, dict) else None
    ) or []

    execution = state.get("execution_result")
    decision = state.get("human_approval")
    approval = "pending" if decision is None else ("approved" if decision else "rejected")

    lines: list[str] = [
        f"# OpsFlow Incident Report — {state.get('thread_id') or 'unknown'}",
        "",
        f"_Generated: {datetime.now(timezone.utc).isoformat()}_",
        "",
        "## 1. Incident Summary",
        f"- Tenant: {state.get('tenant_id') or 'unknown'}",
        f"- Service: {state.get('service') or 'unknown'}",
        f"- Error class: {state.get('error_class') or 'unknown'}",
        f"- Severity: {state.get('severity') or 'unknown'}",
        f"- Status: {state.get('status') or 'unknown'}",
        f"- Thread: {state.get('thread_id') or 'unknown'}",
        "",
        "## 2. Root Cause Analysis",
        f"- Diagnosis: {state.get('diagnosis') or 'n/a'}",
        f"- Root cause: {state.get('root_cause') or 'n/a'}",
        f"- Critic score: {state.get('critic_score', 'n/a')}",
        "- Evidence:",
    ]
    if evidence:
        lines.extend(f"  - {item}" for item in evidence)
    else:
        lines.append("  - (none)")

    lines.extend(
        [
            "",
            "## 3. Proposed Fix",
            f"- Action: {_get(remediation, 'remediation_id', 'n/a')}",
            f"- Parameters: {params or '(none)'}",
            f"- Command: {' '.join(command) if command else 'n/a'}",
            f"- Rationale: {_get(remediation, 'rationale', 'n/a')}",
            f"- Risk: {state.get('risk_level') or 'unknown'}",
            f"- Reversible: {spec.reversible if spec else 'unknown'}",
            f"- Requires approval: {state.get('requires_approval', False)}",
            "",
            "## 4. Sandbox Validation",
            f"- Status: {'passed' if state.get('validated') else 'not passed'}",
            f"- Environment: {checks.get('environment', 'n/a') if isinstance(checks, dict) else 'n/a'}",
        ]
    )
    if check_rows:
        lines.append("- Checks:")
        for check in check_rows:
            lines.append(
                f"  - {' '.join(_get(check, 'command', []) or [])} -> "
                f"exit {_get(check, 'exit_code', 'n/a')}"
            )
    else:
        lines.append("- Checks: (none)")
    lines.append(
        f"- Rollback plan: {' '.join(rollback) if rollback else 'n/a'}"
    )

    lines.extend(
        [
            "",
            "## 5. Confidence",
            f"- Score: {state.get('confidence', 0)} / 100",
            f"- Breakdown: {state.get('confidence_breakdown') or {}}",
            "",
            "## 6. Risk and Approval",
            f"- Risk level: {state.get('risk_level') or 'unknown'}",
            f"- Approval required: {state.get('requires_approval', False)}",
            f"- Human decision: {approval}",
            f"- Approver: {state.get('approver') or 'n/a'}",
            "",
            "## 7. Timeline",
        ]
    )
    audit = state.get("audit") or []
    if audit:
        for event in audit:
            lines.append(
                f"- {_get(event, 'ts', '')} — "
                f"{_get(event, 'actor', 'system')}/{_get(event, 'action', 'event')}: "
                f"{_get(event, 'detail', '')}"
            )
    else:
        lines.append("- (no audit events)")

    lines.extend(["", "## 8. Execution"])
    if execution is not None:
        lines.extend(
            [
                f"- Remediation: {_get(execution, 'remediation_id', 'n/a')}",
                f"- Command: {' '.join(_get(execution, 'command', []) or [])}",
                f"- Dry run: {_get(execution, 'dry_run', 'n/a')}",
                f"- Exit code: {_get(execution, 'exit_code', 'n/a')}",
                f"- Stdout: {_get(execution, 'stdout', '')}",
                f"- Stderr: {_get(execution, 'stderr', '')}",
            ]
        )
    else:
        lines.append("- Not executed yet. Waiting for approval.")

    return "\n".join(lines)



def generate_incident_report(thread_id: str) -> str:
    with SessionLocal() as session:
        incident = session.execute(
            select(Incident).where(Incident.thread_id == thread_id)
        ).scalar_one_or_none()
        if incident is None:
            raise ValueError(f"incident not found: {thread_id}")
        logs = (
            session.execute(
                select(ExecutionLog)
                .where(ExecutionLog.incident_id == incident.incident_id)
                .order_by(ExecutionLog.started_at)
            )
            .scalars()
            .all()
        )
        outcomes = (
            session.execute(
                select(FixOutcome).where(FixOutcome.incident_id == incident.incident_id)
            )
            .scalars()
            .all()
        )

    lines = [
        f"# Incident Report — {thread_id}",
        "",
        "## Summary",
        f"- Tenant: {incident.tenant_id}",
        f"- Service: {incident.service}",
        f"- Error class: {incident.error_class}",
        f"- Severity: {incident.severity}",
        f"- Status: {incident.status}",
        f"- Created: {incident.created_at}",
        f"- Approval requested: {incident.approval_requested_at}",
        f"- Escalated level: {incident.escalated_level}",
        "",
        "## Timeline",
        f"- detected: {incident.created_at}",
    ]
    if incident.approval_requested_at:
        lines.append(f"- approval requested: {incident.approval_requested_at}")
    lines.append(f"- resolved: {incident.resolved_at or 'n/a'}")
    for log in logs:
        lines.append(
            f"- execution ({log.environment}): {' '.join(log.command or [])} -> {log.result}"
        )

    lines.extend(["", "## Root cause / fix"])
    if logs:
        latest = logs[-1]
        lines.append(f"- Remediation: {latest.remediation_id}")
        lines.append(f"- Command: {' '.join(latest.command or [])}")
        lines.append(f"- Rollback plan: {(latest.sandbox_checks or {}).get('rollback')}")
    else:
        lines.append("- No execution recorded.")

    lines.extend(["", "## Outcome"])
    if outcomes:
        for outcome in outcomes:
            lines.append(
                f"- {outcome.remediation_id}: outcome={outcome.outcome}, "
                f"stable={outcome.stable}, confidence={outcome.confidence}"
            )
    else:
        lines.append("- Pending verification.")

    lines.extend(
        [
            "",
            "## Lessons learned",
            "- [ ] Note what prevented or mitigated this incident.",
            "- [ ] Update the runbook / catalog if needed.",
        ]
    )
    return "\n".join(lines)

def write_report(thread_id: str, out_dir: str | None = None) -> str:
    content = generate_incident_report(thread_id)
    out = Path(out_dir or settings.reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{thread_id}.md"
    path.write_text(content, encoding="utf-8")
    return str(path)
