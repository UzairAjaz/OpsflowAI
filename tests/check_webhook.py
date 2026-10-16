"""P2-05 check: webhook HMAC verification.

Exercises POST /api/v1/webhooks/alert with a valid signature, a tampered body,
a missing signature, and invalid JSON (valid signature).
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from api.main import app
from api.security import sign_payload
from app.config import settings
from worker.queue import get_queue

ALERT = {
    "source": "cloudwatch",
    "service": "retriva-backend",
    "error_class": "OOMKilled",
    "severity_hint": "critical",
    "raw_log": "container exited with code 137",
}


def main() -> None:
    body = json.dumps(ALERT).encode("utf-8")
    secret = settings.webhook_secret
    headers = {"Content-Type": "application/json", "X-Signature": sign_payload(secret, body)}

    with TestClient(app) as client:
        ok = client.post("/api/v1/webhooks/alert", content=body, headers=headers)
        assert ok.status_code == 202, ok.text
        print("valid signature     ->", ok.status_code, ok.json())

        tampered_body = json.dumps({**ALERT, "service": "other"}).encode("utf-8")
        bad = client.post("/api/v1/webhooks/alert", content=tampered_body, headers=headers)
        assert bad.status_code == 401, bad.text
        print("tampered body       ->", bad.status_code)

        unsigned = client.post("/api/v1/webhooks/alert", content=body)
        assert unsigned.status_code == 401, unsigned.text
        print("missing signature   ->", unsigned.status_code)

        wrong_secret = {
            "Content-Type": "application/json",
            "X-Signature": sign_payload("wrong-secret", body),
        }
        wrong = client.post("/api/v1/webhooks/alert", content=body, headers=wrong_secret)
        assert wrong.status_code == 401, wrong.text
        print("wrong secret        ->", wrong.status_code)

        bad_json = b"{not-json"
        bad_json_headers = {
            "Content-Type": "application/json",
            "X-Signature": sign_payload(secret, bad_json),
        }
        malformed = client.post(
            "/api/v1/webhooks/alert", content=bad_json, headers=bad_json_headers
        )
        assert malformed.status_code == 400, malformed.text
        print("invalid JSON        ->", malformed.status_code)

    get_queue().empty()
    print("[ok] P2-05 -- webhook accepts signed alerts and rejects tampered/unsigned ones.")


if __name__ == "__main__":
    main()
