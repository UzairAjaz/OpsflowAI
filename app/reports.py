from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from db.models import ExecutionLog, FixOutcome, Incident
from db.session import SessionLocal

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

def write_report(thread_id: str, out_dir: str = "reports") -> str:
    content = generate_incident_report(thread_id)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{thread_id}.md"
    path.write_text(content, encoding="utf-8")
    return str(path)
