from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from db.models import AuditLog, Incident, ProcessedAlert, RepositoryMapping, Tenant
from ingestion.code_alert_schema import CodeAlertMessage
from observability.logging import get_logger

log = get_logger(stage="ingestion.code")


@dataclass
class CodeIngestResult:
    incident_id: uuid.UUID
    thread_id: str
    duplicate: bool
    analysis_only: bool
    file_path: str
    repository_mapping_id: uuid.UUID | None


def normalize_repo_path(file_path: str, repo_root: str | None, repo_path: str = "") -> str:
    """Convert a local absolute path into a repository-relative path."""
    if not file_path:
        return ""

    normalized = file_path.replace("\\", "/")
    if not os.path.isabs(file_path):
        prefix = repo_path.strip("/").replace("\\", "/")
        if prefix:
            normalized = f"{prefix}/{normalized.lstrip('/')}"
        return normalized.lstrip("/")

    if repo_root:
        root = repo_root.replace("\\", "/").rstrip("/")
        candidate = normalized
        if os.name == "nt":
            candidate = os.path.normpath(file_path)
            root = os.path.normpath(repo_root)
        try:
            relative = os.path.relpath(candidate, root)
        except ValueError:
            relative = normalized
        if not relative.startswith(".."):
            normalized = relative.replace("\\", "/")
        else:
            normalized = os.path.basename(normalized)
    else:
        normalized = os.path.basename(normalized)

    prefix = repo_path.strip("/").replace("\\", "/")
    if prefix:
        normalized = f"{prefix}/{normalized.lstrip('/')}"
    return normalized.lstrip("/")


def resolve_repository_mapping(
    session: Session, tenant_id: str, service: str
) -> RepositoryMapping | None:
    return session.execute(
        select(RepositoryMapping).where(
            RepositoryMapping.tenant_id == tenant_id,
            RepositoryMapping.service == service,
            RepositoryMapping.enabled.is_(True),
        )
    ).scalar_one_or_none()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def ingest_code_alert(session: Session, alert: CodeAlertMessage) -> CodeIngestResult:
    mapping = resolve_repository_mapping(session, alert.tenant_id, alert.service)
    normalized_file = normalize_repo_path(
        alert.file,
        mapping.local_repo_root if mapping else None,
        mapping.repo_path if mapping else "",
    )

    analysis_only = (
        alert.analysis_only
        or not settings.code_fix_enabled
        or settings.code_fix_analysis_only
        or mapping is None
        or not alert.commit_sha
    )
    status = "analysis_only" if analysis_only else "pending"
    occurred_at = _aware(alert.timestamp)

    existing = session.get(ProcessedAlert, alert.dedupe_key)
    duplicate = existing is not None
    if existing is None:
        existing = ProcessedAlert(
            alerts_signature=alert.dedupe_key,
            source=alert.source,
            service=alert.service,
            tenant_id=alert.tenant_id,
            error_class=alert.error_class or None,
            severity=alert.severity,
            first_seen=occurred_at,
            last_seen=occurred_at,
            count=1,
        )
        session.add(existing)
        session.flush()
    else:
        existing.last_seen = occurred_at
        existing.count = (existing.count or 1) + 1

    incident = None
    if existing.incident_id:
        incident = session.get(Incident, existing.incident_id)

    if incident is None:
        incident = Incident(
            thread_id=f"inc-{uuid.uuid4().hex[:8]}",
            source=alert.source,
            service=alert.service,
            tenant_id=alert.tenant_id,
            error_class=alert.error_class or None,
            error_message=alert.message or None,
            stack_trace=alert.stack_trace or None,
            severity=alert.severity,
            status=status,
            environment=alert.environment,
            commit_sha=alert.commit_sha or None,
            log_group=alert.log_group or None,
            log_stream=alert.log_stream or None,
            trace_id=alert.trace_id or None,
            request_id=alert.request_id or None,
            file_path=normalized_file or None,
            line_number=alert.line or None,
            analysis_only=analysis_only,
            error_fingerprint=alert.fingerprint,
            dedupe_key=alert.dedupe_key,
            repository_mapping_id=mapping.mapping_id if mapping else None,
        )
        session.add(incident)
        session.flush()
        existing.incident_id = incident.incident_id

        if session.get(Tenant, alert.tenant_id) is not None:
            session.add(
                AuditLog(
                    tenant_id=alert.tenant_id,
                    incident_id=incident.incident_id,
                    action="code_alert.received",
                    actor="system",
                    details={
                        "dedupe_key": alert.dedupe_key,
                        "commit_sha": alert.commit_sha,
                        "file": normalized_file,
                        "line": alert.line,
                        "analysis_only": analysis_only,
                        "mapping_found": mapping is not None,
                        "environment": alert.environment,
                    },
                )
            )

    session.commit()
    log.bind(
        tenant_id=alert.tenant_id,
        service=alert.service,
        incident_id=str(incident.incident_id),
        thread_id=incident.thread_id,
        duplicate=duplicate,
        analysis_only=analysis_only,
    ).info("code alert ingested")
    return CodeIngestResult(
        incident_id=incident.incident_id,
        thread_id=incident.thread_id,
        duplicate=duplicate,
        analysis_only=analysis_only,
        file_path=normalized_file,
        repository_mapping_id=mapping.mapping_id if mapping else None,
    )


def ingest_code_alert_payload(payload: dict) -> CodeIngestResult:
    alert = CodeAlertMessage.model_validate(payload)
    from db.session import SessionLocal

    with SessionLocal() as session:
        return ingest_code_alert(session, alert)
