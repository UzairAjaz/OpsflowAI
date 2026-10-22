from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from db.models import ProcessedAlert
from db.session import SessionLocal
from ingestion.ratelimit import get_rate_limiter
from ingestion.schema import Alert, normalize_alert
from ingestion.severity import classify_severity_llm
from observability.logging import get_logger

class IngestResult(BaseModel):
    action: str
    alert: Alert
    group_key: str

class IngestOutcome(BaseModel):
    rate_limited: bool
    result: IngestResult | None

def prepare_alert(payload: dict) -> Alert:
    alert = normalize_alert(payload)
    if settings.severity_use_llm and alert.severity == "info":
        try:
            alert.severity = classify_severity_llm(
                error_class=alert.error_class,
                raw_log=alert.raw_log,
                severity_hint=alert.severity_hint,
            ).level
        except Exception:
            pass
    return alert

def _insert_alert(session: Session, alert: Alert) -> bool:
    statement = (
        pg_insert(ProcessedAlert)
        .values(
            alerts_signature=alert.alerts_signature,
            source=alert.source,
            service=alert.service,
            tenant_id=alert.tenant_id,
            error_class=alert.error_class,
            severity=alert.severity,
            first_seen=alert.received_at,
            last_seen=alert.received_at,
            count=1,
        )
        .on_conflict_do_nothing(index_elements=["alerts_signature"])
        .returning(ProcessedAlert.alerts_signature)
    )
    return session.execute(statement).fetchone() is not None

def _bump_alert(session: Session, alert: Alert) -> None:
    session.execute(
        update(ProcessedAlert)
        .where(ProcessedAlert.alerts_signature == alert.alerts_signature)
        .values(last_seen=alert.received_at, count=ProcessedAlert.count + 1)
    )

def _count_peers(session: Session, alert: Alert) -> int:
    cutoff = alert.received_at - timedelta(seconds=settings.alert_dedupe_window_seconds)
    statement = (
        select(func.count())
        .select_from(ProcessedAlert)
        .where(
            ProcessedAlert.service == alert.service,
            ProcessedAlert.error_class == alert.error_class,
            ProcessedAlert.alerts_signature != alert.alerts_signature,
            ProcessedAlert.last_seen >= cutoff,
        )
    )
    return int(session.execute(statement).scalar_one())

def has_recent_peers(session: Session, alert: Alert) -> bool:
    cutoff = alert.received_at - timedelta(seconds=settings.alert_dedupe_window_seconds)
    statement = (
        select(func.count())
        .select_from(ProcessedAlert)
        .where(
            ProcessedAlert.service == alert.service,
            ProcessedAlert.error_class == alert.error_class,
            ProcessedAlert.last_seen >= cutoff,
        )
    )
    return int(session.execute(statement).scalar_one()) > 0

def store_alert(session: Session, alert: Alert) -> IngestResult:
    if not _insert_alert(session, alert):
        _bump_alert(session, alert)
        session.commit()
        return IngestResult(action="duplicate", alert=alert, group_key=alert.fingerprint)

    session.flush()
    peers = _count_peers(session, alert)
    session.commit()
    action = "merged" if peers > 0 else "new"
    return IngestResult(action=action, alert=alert, group_key=alert.fingerprint)

def process_alert(session: Session, payload: dict) -> IngestResult:
    return store_alert(session, prepare_alert(payload))

def ingest_payload(payload: dict) -> IngestResult:

    with SessionLocal() as session:
        return process_alert(session, payload)

def ingest_with_limits(payload: dict) -> IngestOutcome:
    alert = prepare_alert(payload)
    limiter = get_rate_limiter()

    if not limiter.allow(alert.service):
        with SessionLocal() as session:
            merging = has_recent_peers(session, alert)
        if not merging:
            get_logger(stage="ingestion", service=alert.service).warning(
                "rate limited; new incident rejected"
            )
            return IngestOutcome(rate_limited=True, result=None)

    with SessionLocal() as session:
        result = store_alert(session, alert)
    return IngestOutcome(rate_limited=False, result=result)
