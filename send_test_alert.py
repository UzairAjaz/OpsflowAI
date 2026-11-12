"""Send a signed test alert through the configured OpsFlow webhook.

All values come from the central ``settings`` object (app/config.py + .env).
Override the destination for local testing with ``ALERT_WEBHOOK_URL`` or
``PUBLIC_BASE_URL`` in .env / the process environment.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import uuid

import requests

from app.config import settings

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

WEBHOOK_SECRET = settings.webhook_secret
WEBHOOK_URL = settings.webhook_alert_url
DEMO_SERVICE = settings.demo_service
DEMO_TENANT = settings.demo_tenant_id
DEMO_ERROR = settings.demo_error_class
SIGNATURE_HEADER = settings.webhook_signature_header

# Unique ID so deduplication does not block repeated demo alerts.
unique_id = uuid.uuid4().hex[:8]

payload = {
  "source": "cloudwatch",
  "service": "mediconnect-backend",
  "tenant_id": "mediconnect",
  "error_class": "DBConnectionPoolExhausted",
  "severity_hint": "high",
  "raw_log": "PostgreSQL connection pool for mediconnect-backend is exhausted. Max connections reached (100/100).",
  "event_id": "demo-db-004",
  "fingerprint": "svc:mediconnect-backend|err:DBPOOL|demo-004"
}

raw_body = json.dumps(payload).encode("utf-8")

signature = hmac.new(
    WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256
).hexdigest()

headers = {
    "Content-Type": "application/json",
    SIGNATURE_HEADER: f"sha256={signature}",
}

print(f"🚀 Sending UNIQUE alert to {WEBHOOK_URL}...")
print(f"📦 Payload Fingerprint: {payload['fingerprint']}")

try:
    response = requests.post(WEBHOOK_URL, data=raw_body, headers=headers, timeout=15)
    print(f"✅ Status: {response.status_code}")
    print(f"📩 Response: {response.json()}")
    print(
        "\n👉 Check the worker terminal and the configured notification "
        f"channels (email={settings.smtp_to or 'not set'})."
    )
except requests.exceptions.ConnectionError:
    print("❌ Error: Could not connect. Is the API running and ALERT_WEBHOOK_URL correct?")
except Exception as exc:
    print(f"❌ Error sending alert: {exc}")
