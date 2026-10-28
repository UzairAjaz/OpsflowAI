import hashlib
import hmac
import json
import os
import time
import uuid

import requests

WEBHOOK_SECRET = os.getenv("OPSFLOW_WEBHOOK_SECRET", "dev-secret-change-me")
WEBHOOK_URL = os.getenv(
    "OPSFLOW_WEBHOOK_URL", "http://127.0.0.1:8000/api/v1/webhooks/alert"
)
DEMO_SERVICE = os.getenv("OPSFLOW_DEMO_SERVICE", "payment-api-demo")

unique_id = uuid.uuid4().hex[:8]

payload = {
    "source": "cloudwatch",
    "service": DEMO_SERVICE,
    "tenant_id": "acme",
    "error_class": "OOMKilled",
    "severity_hint": "critical",
    "raw_log": (
        f"Container {DEMO_SERVICE} killed due to memory limit exceeded. "
        f"Current usage: 2.1GB, Limit: 1Gi. Trace ID: {unique_id}"
    ),
    "event_id": f"demo-{unique_id}",
    "fingerprint": f"svc:{DEMO_SERVICE}|err:OOM|demo-{unique_id}",
}

raw_body = json.dumps(payload).encode("utf-8")
signature = hmac.new(
    WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256
).hexdigest()

headers = {
    "Content-Type": "application/json",
    "X-Signature": f"sha256={signature}",
}

print(f"Sending UNIQUE alert to {WEBHOOK_URL}...")
try:
    response = requests.post(WEBHOOK_URL, data=raw_body, headers=headers, timeout=15)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
except Exception as exc:
    print(f"Error sending alert: {exc}")
