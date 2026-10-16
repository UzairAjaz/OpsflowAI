"""P2-07 check: rate limiting and severity classification.

Verifies:
- the sliding-window limiter allows 50 per service per window and blocks the 51st,
- limits are isolated per service,
- severity rules classify critical / warning / info,
- the endpoint returns 429 for a 51st new incident but coalesces same-group alerts,
- the classified severity is persisted.
"""

from __future__ import annotations

import json
import time

import redis
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from api.main import app
from api.security import sign_payload
from app.config import settings
from db.models import ProcessedAlert
from db.session import SessionLocal
from ingestion.ratelimit import get_rate_limiter
from ingestion.severity import classify_severity_rules
from worker.queue import get_queue


def _redis() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _post(client: TestClient, payload: dict, secret: str):
    body = json.dumps(payload).encode("utf-8")
    return client.post(
        "/api/v1/webhooks/alert",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature": sign_payload(secret, body),
        },
    )


def _clear(service: str) -> None:
    _redis().delete(f"ratelimit:alerts:{service}")
    with SessionLocal() as session:
        session.execute(delete(ProcessedAlert).where(ProcessedAlert.service == service))
        session.commit()


def main() -> None:
    limiter = get_rate_limiter()
    client_redis = _redis()

    service = f"rl-unit-{int(time.time())}"
    client_redis.delete(f"ratelimit:alerts:{service}")
    allowed = sum(1 for _ in range(50) if limiter.allow(service))
    blocked = limiter.allow(service)
    print(f"limiter   -> allowed={allowed} 51st_allowed={blocked}")
    assert allowed == 50 and blocked is False

    other = f"rl-unit-other-{int(time.time())}"
    client_redis.delete(f"ratelimit:alerts:{other}")
    assert limiter.allow(other) is True
    print("limiter   -> per-service isolation ok")
    client_redis.delete(f"ratelimit:alerts:{service}", f"ratelimit:alerts:{other}")

    cases = [
        ({"error_class": "OOMKilled", "raw_log": "container out of memory", "severity_hint": "info"}, "critical"),
        ({"error_class": "LatencyHigh", "raw_log": "p99 slow and degraded", "severity_hint": "info"}, "warning"),
        ({"error_class": "Heartbeat", "raw_log": "routine health ping", "severity_hint": "info"}, "info"),
        ({"error_class": "Whatever", "raw_log": "nothing notable", "severity_hint": "critical"}, "critical"),
    ]
    for kwargs, expected in cases:
        got = classify_severity_rules(**kwargs).level
        print(f"severity  -> {kwargs['error_class']:<12} = {got}")
        assert got == expected, (kwargs, got, expected)

    service_a = f"rl-http-a-{int(time.time())}"
    _clear(service_a)
    statuses_a = []
    with TestClient(app) as client:
        for index in range(51):
            response = _post(
                client,
                {
                    "source": "prometheus",
                    "service": service_a,
                    "error_class": f"err-{index}",
                    "raw_log": f"oom event {index}",
                    "severity_hint": "info",
                },
                settings.webhook_secret,
            )
            statuses_a.append(response.status_code)
    print(
        f"http new  -> first50_202={all(s == 202 for s in statuses_a[:50])} 51st={statuses_a[50]}"
    )
    assert all(s == 202 for s in statuses_a[:50])
    assert statuses_a[50] == 429

    service_b = f"rl-http-b-{int(time.time())}"
    _clear(service_b)
    statuses_b = []
    actions_b = []
    with TestClient(app) as client:
        for index in range(51):
            response = _post(
                client,
                {
                    "source": "prometheus",
                    "service": service_b,
                    "error_class": "OOMKilled",
                    "raw_log": f"oom event {index}",
                    "severity_hint": "info",
                },
                settings.webhook_secret,
            )
            statuses_b.append(response.status_code)
            actions_b.append(response.json().get("action") if response.status_code == 202 else "429")
    print(f"http merge-> 51st_status={statuses_b[50]} action={actions_b[50]}")
    assert statuses_b[50] == 202 and actions_b[50] == "merged"

    with SessionLocal() as session:
        row = session.execute(
            select(ProcessedAlert).where(ProcessedAlert.service == service_a).limit(1)
        ).scalar_one()
    print("stored    -> severity =", row.severity)
    assert row.severity == "critical"

    _clear(service_a)
    _clear(service_b)
    get_queue().empty()
    print("[ok] P2-07 -- rate limiting and severity classification working.")


if __name__ == "__main__":
    main()
