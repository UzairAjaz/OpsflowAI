from __future__ import annotations

from redis import Redis
from rq import Queue

from app.config import settings

QUEUE_NAME = "incidents"
_CONNECTION: Redis | None = None

def get_connection() -> Redis:
    global _CONNECTION
    if _CONNECTION is None:
        _CONNECTION = Redis.from_url(settings.redis_url)
    return _CONNECTION

def get_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=get_connection())

def enqueue_incident(alert_signature: str, payload: dict):
    from worker.tasks import handle_new_alert

    job_id = f"incident_{alert_signature}"
    return get_queue().enqueue(
        handle_new_alert,
        alert_signature,
        payload,
        job_id=job_id,
        job_timeout=settings.worker_job_timeout_seconds,
        result_ttl=300,
        failure_ttl=300,
    )
