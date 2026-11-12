from __future__ import annotations

from sqlalchemy import delete, select

from app.config import settings
from app.nodes.report import generate_report, route_after_report
from app.reports import build_state_report
from app.state import AuditEvent, Remediation, new_incident
from db.models import AuditLog, Incident
from db.session import SessionLocal

def main() -> None:
    state = new_incident(
        "container out of memory",
        tenant_id="mediconnect",
        service="mediconnect-backend",
        error_class="OOMKilled",
    )
    state["diagnosis"] = "Container exceeded its memory limit and was OOMKilled"
    state["root_cause"] = "Memory limit is too low for current traffic"
    state["severity"] = "high"
    state["evidence"] = ["exit code 137", "OOMKilled"]
    state["proposed_remediation"] = Remediation(
        remediation_id="increase_memory_limit",
        params={"container_name": "mediconnect-backend", "new_memory_limit": "2Gi"},
        rationale="Raise memory to the proven value and restart safely.",
    )
    state["resolved_params"] = {
        "container_name": "mediconnect-backend",
        "new_memory_limit": "2Gi",
    }
    state["risk_level"] = "medium"
    state["requires_approval"] = True
    state["critic_score"] = 85
    state["confidence"] = 82
    state["confidence_breakdown"] = {"kb_match": 30.0, "critic_score": 17.0}
    state["validated"] = True
    state["sandbox_checks"] = {
        "environment": "fake",
        "checks": [
            {
                "command": ["docker", "inspect", "mediconnect-backend"],
                "exit_code": 0,
                "passed": True,
            }
        ],
        "rollback": ["docker", "update", "--memory", "512Mi", "mediconnect-backend"],
    }
    state["rollback_plan"] = [
        "docker",
        "update",
        "--memory",
        "512Mi",
        "mediconnect-backend",
    ]
    state["status"] = "validated"
    state["audit"] = [
        AuditEvent(actor="agent", action="sandbox", detail="passed in fake"),
    ]

    content = build_state_report(state)
    assert "# OpsFlow Incident Report" in content
    assert "## 1. Incident Summary" in content
    assert "## 4. Sandbox Validation" in content
    assert "increase_memory_limit" in content
    assert "mediconnect-backend" in content
    print("template    -> structured report generated")

    thread_id = state["thread_id"]
    with SessionLocal() as session:
        session.add(
            Incident(
                thread_id=thread_id,
                source="cloudwatch",
                service="mediconnect-backend",
                tenant_id="mediconnect",
                error_class="OOMKilled",
                severity="high",
                status="pending",
            )
        )
        session.commit()

    original_auto = settings.auto_approve
    try:
        settings.auto_approve = False
        assert route_after_report(state) == "approval"
        settings.auto_approve = True
        assert route_after_report(state) == "execute"
        print("routing     -> approval / execute routing works")

        update = generate_report(state)
        generated = update["report"]
        assert generated.startswith("# OpsFlow Incident Report")
        assert "increase_memory_limit" in generated
        assert update["audit"][0].action == "report"

        with SessionLocal() as session:
            incident = session.execute(
                select(Incident).where(Incident.thread_id == thread_id)
            ).scalar_one()
            assert incident.report == generated
            assert incident.report_generated_at is not None
            audit = session.execute(
                select(AuditLog).where(
                    AuditLog.tenant_id == "mediconnect",
                    AuditLog.action == "report.generate",
                    AuditLog.details["thread_id"].astext == thread_id,
                )
            ).scalars().all()
            assert audit
        print("persistence -> incident.report saved; audit row written")
    finally:
        settings.auto_approve = original_auto
        with SessionLocal() as session:
            session.execute(
                delete(AuditLog).where(
                    AuditLog.action == "report.generate",
                    AuditLog.details["thread_id"].astext == thread_id,
                )
            )
            incident = session.execute(
                select(Incident).where(Incident.thread_id == thread_id)
            ).scalar_one_or_none()
            if incident is not None:
                session.delete(incident)
            session.commit()

    print("[ok] Day 6 structured report generation works.")

if __name__ == "__main__":
    main()
