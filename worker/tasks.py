"""Background tasks for incident processing.

Creating an incident is idempotent: it checks whether the processed alert already
has an incident_id before creating one. This makes the job safe to retry after a
worker restart or a re-delivered job.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from db.models import Incident, ProcessedAlert
from db.session import SessionLocal
from observability.logging import get_logger
from worker.graph_runner import run_incident


def create_incident(alert_signature: str) -> tuple[str, bool]:
    """Create an incident for an alert if one does not already exist."""
    with SessionLocal() as session:
        row = session.get(ProcessedAlert, alert_signature)
        if row is None:
            return "", False
        if row.incident_id is not None:
            return str(row.incident_id), False

        incident = Incident(
            thread_id=f"inc-{uuid.uuid4().hex[:8]}",
            source=row.source,
            service=row.service,
            tenant_id=row.tenant_id,
            error_class=row.error_class or "unknown",
            severity=row.severity,
            status="pending",
        )
        session.add(incident)
        session.flush()
        row.incident_id = incident.incident_id
        session.commit()
        return str(incident.incident_id), True


def handle_new_alert(alert_signature: str, payload: dict, graph=None) -> dict:
    incident_id, created = create_incident(alert_signature)
    if not created:
        get_logger(stage="worker", incident_id=incident_id).info(
            "incident already exists; skipping"
        )
        return {"status": "skipped", "incident_id": incident_id}

    with SessionLocal() as session:
        incident = session.get(Incident, uuid.UUID(incident_id))
        thread_id = incident.thread_id
        tenant_id = incident.tenant_id
        service = incident.service
        error_class = incident.error_class or ""

    error_log = str(payload.get("raw_log") or "")
    result = run_incident(
        thread_id=thread_id,
        error_log=error_log,
        tenant_id=tenant_id,
        service=service,
        error_class=error_class,
        graph=graph,
    )

    paused = isinstance(result, dict) and "__interrupt__" in result
    graph_status = result.get("status", "processed") if isinstance(result, dict) else "processed"

    with SessionLocal() as session:
        incident = session.get(Incident, uuid.UUID(incident_id))
        if paused:
            incident.status = "awaiting_approval"
            incident.approval_requested_at = datetime.now(timezone.utc)
        else:
            incident.status = graph_status
        session.commit()

    if paused:
        summary = result["__interrupt__"][0].value
        from integrations.notifications import dispatch_approval

        dispatch_approval(summary)
        get_logger(stage="worker", incident_id=incident_id).info(
            "approval requested; notifications dispatched"
        )

    get_logger(stage="worker", incident_id=incident_id, status=graph_status).info(
        "incident processed"
    )
    return {
        "status": "awaiting_approval" if paused else "processed",
        "incident_id": incident_id,
        "graph_status": graph_status,
    }
