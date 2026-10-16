"""P2-34..P2-36 check: post-incident reports, feedback loop, calibration."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select

from app.calibration import calibration_report
from app.reports import generate_incident_report, write_report
from db.models import ExecutionLog, FixOutcome, Incident
from db.session import SessionLocal
from integrations.feedback import process_feedback

SERVICE = "learning-check"


def _cleanup() -> None:
    with SessionLocal() as session:
        incidents = (
            session.execute(select(Incident).where(Incident.service == SERVICE)).scalars().all()
        )
        ids = [incident.incident_id for incident in incidents]
        if ids:
            session.execute(delete(ExecutionLog).where(ExecutionLog.incident_id.in_(ids)))
            session.execute(delete(FixOutcome).where(FixOutcome.incident_id.in_(ids)))
        for incident in incidents:
            session.delete(incident)
        session.commit()


def main() -> None:
    _cleanup()
    try:
        now = datetime.now(timezone.utc)
        with SessionLocal() as session:
            incident = Incident(
                thread_id=f"learn-{uuid.uuid4().hex[:8]}",
                source="test",
                service=SERVICE,
                tenant_id="acme",
                error_class="OOMKilled",
                severity="high",
                status="approved",
                created_at=now - timedelta(hours=30),
            )
            session.add(incident)
            session.flush()
            session.add(
                ExecutionLog(
                    incident_id=incident.incident_id,
                    remediation_id="increase_memory_limit",
                    params={"container_name": SERVICE, "new_memory_limit": "2Gi"},
                    command=["docker", "update", "--memory", "2Gi", SERVICE],
                    environment="sandbox",
                    dry_run=True,
                    result="sandbox_passed",
                    sandbox_checks={"confidence": 90, "rollback": ["docker", "update", "--memory", "512Mi", SERVICE]},
                )
            )
            session.commit()
            thread_id = incident.thread_id

        report = generate_incident_report(thread_id)
        assert "Incident Report" in report and "Timeline" in report
        assert "increase_memory_limit" in report
        path = write_report(thread_id, out_dir="reports")
        assert Path(path).exists()
        print("report    ->", path)

        recorded = process_feedback(now=now, horizon_hours=24)
        assert any(item["thread_id"] == thread_id for item in recorded)
        again = process_feedback(now=now, horizon_hours=24)
        assert all(item["thread_id"] != thread_id for item in again)
        print("feedback  -> recorded", len(recorded), "outcome(s); idempotent")

        report_data = calibration_report()
        assert report_data["buckets"]["high (80-100)"]["total"] >= 1
        print(
            "calibrate ->",
            report_data["buckets"]["high (80-100)"],
            "suggested threshold:",
            report_data["suggested_automation_threshold"],
        )

        print("[ok] P2-34..P2-36 -- reports, feedback, calibration working.")
    finally:
        _cleanup()
        for path in Path("reports").glob("learn-*.md"):
            path.unlink()


if __name__ == "__main__":
    main()
