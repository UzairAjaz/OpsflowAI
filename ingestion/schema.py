from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from ingestion.severity import classify_severity_rules

SEVERITY_HINTS = {"critical", "warning", "info"}

class AlertValidationError(ValueError):
    pass

class Alert(BaseModel):
    source: str
    service: str
    tenant_id: str
    error_class: str
    severity_hint: str
    severity: str
    raw_log: str
    event_id: str | None
    fingerprint: str
    alerts_signature: str
    received_at: datetime

def _required(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AlertValidationError(f"missing or invalid '{key}'")
    return value.strip()

def normalize_alert(payload: dict[str, Any]) -> Alert:
    source = _required(payload, "source")
    service = _required(payload, "service")
    tenant_id = str(payload.get("tenant_id") or "default").strip() or "default"
    error_class = str(payload.get("error_class") or "unknown").strip()
    raw_log = str(payload.get("raw_log") or "")

    event_id = payload.get("event_id")
    event_id = str(event_id).strip() if event_id else None

    severity_hint = str(payload.get("severity_hint") or "info").lower().strip()
    if severity_hint not in SEVERITY_HINTS:
        severity_hint = "info"

    if event_id:
        identity = f"{source}|event:{event_id}"
    else:
        identity = f"{source}|{service}|{error_class}|{raw_log}"
    alerts_signature = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    fingerprint = f"svc:{service}|err:{error_class}"

    severity = classify_severity_rules(
        error_class=error_class, raw_log=raw_log, severity_hint=severity_hint
    ).level

    return Alert(
        source=source,
        service=service,
        tenant_id=tenant_id,
        error_class=error_class,
        severity_hint=severity_hint,
        severity=severity,
        raw_log=raw_log,
        event_id=event_id,
        fingerprint=fingerprint,
        alerts_signature=alerts_signature,
        received_at=datetime.now(timezone.utc),
    )
