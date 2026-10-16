"""Alert ingestion webhook.

Receives alerts from monitoring systems (CloudWatch, Prometheus, Grafana,
Datadog). Every request must carry a valid HMAC-SHA256 signature. Valid alerts
are normalized, severity-labelled, rate-limited, and de-duplicated. When an
alert creates a new group, an incident-processing job is enqueued.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from api.security import SIGNATURE_HEADER, verify_hmac_sha256
from app.config import settings
from ingestion.schema import AlertValidationError
from ingestion.service import ingest_with_limits
from observability.logging import get_logger
from worker.queue import enqueue_incident

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post("/alert", status_code=202)
async def receive_alert(request: Request) -> dict:
    body = await request.body()
    signature = request.headers.get(SIGNATURE_HEADER)

    if not verify_hmac_sha256(settings.webhook_secret, body, signature):
        get_logger(stage="webhook").warning("rejected alert: invalid signature")
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    try:
        outcome = await run_in_threadpool(ingest_with_limits, payload)
    except AlertValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if outcome.rate_limited or outcome.result is None:
        raise HTTPException(status_code=429, detail="rate limit exceeded")

    result = outcome.result

    if result.action == "new":
        try:
            await run_in_threadpool(enqueue_incident, result.alert.alerts_signature, payload)
        except Exception:
            get_logger(stage="webhook").exception("failed to enqueue incident job")

    get_logger(
        stage="webhook",
        source=result.alert.source,
        action=result.action,
        severity=result.alert.severity,
    ).info("alert ingested")

    return {
        "status": "accepted",
        "action": result.action,
        "severity": result.alert.severity,
        "source": result.alert.source,
        "service": result.alert.service,
        "group_key": result.group_key,
    }
