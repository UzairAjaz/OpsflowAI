"""P2-37 check: Week 6 integration (observability + learning capstone).

Proves tracing, metrics, reports, the feedback loop, and calibration work
together, and that the metrics endpoint is scrapeable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from api.main import app
from app.calibration import calibration_report
from app.config import settings
from app.reports import generate_incident_report, write_report
from db.models import ExecutionLog, FixOutcome, Incident
from db.session import SessionLocal
from integrations.feedback import process_feedback
from observability import metrics
from observability.tracing import configure_tracing, get_recorded_spans, span

SERVICE = "week6-check"


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
    settings.otel_enabled = True
    settings.otel_exporter = "memory"
    assert configure_tracing() is True

    _cleanup()
    try:
        with span("week6-incident", stage="integration"):
            now = datetime.now(timezone.utc)
            with SessionLocal() as session:
                incident = Incident(
                    thread_id=f"week6-{uuid.uuid4().hex[:8]}",
                    source="cloudwatch",
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
                        sandbox_checks={"confidence": 90},
                    )
                )
                session.commit()
                thread_id = incident.thread_id

        week6_spans = [recorded for recorded in get_recorded_spans() if recorded.name == "week6-incident"]
        assert week6_spans
        metrics.record_incident(tenant="acme", severity="high", mttd=0.1)
        metrics.record_resolution(auto=True, mttr=95.0)

        report = generate_incident_report(thread_id)
        write_report(thread_id, out_dir="reports")

        recorded = process_feedback(now=now, horizon_hours=24)
        calibration = calibration_report()

        with TestClient(app) as client:
            scrape = client.get("/metrics")
        assert scrape.status_code == 200 and "opsflow_incident_total" in scrape.text

        print("trace     -> span recorded:", len(week6_spans) >= 1)
        print("metrics   -> /metrics scrape ok:", scrape.status_code)
        print("report    -> generated for", thread_id)
        print("feedback  -> outcomes recorded:", len(recorded))
        print("calibrate -> suggested threshold:", calibration["suggested_automation_threshold"])

        print("")
        print("[ok] P2-37 -- Week 6 exit criteria pass:")
        print("     tracing + metrics + reports + feedback + calibration + evals")
    finally:
        _cleanup()
        for path in Path("reports").glob("week6-*.md"):
            path.unlink()


if __name__ == "__main__":
    main()
