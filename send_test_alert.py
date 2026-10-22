import hashlib
import hmac
import json
import os

import requests

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "dev-secret-change-me")
WEBHOOK_URL = os.getenv(
    "OPSFLOW_WEBHOOK_URL", "http://127.0.0.1:8000/api/v1/webhooks/alert"
)
TENANT_ID = os.getenv("OPSFLOW_TENANT_ID", "acme")

payload = {
    "source": "cloudwatch",
    "service": "payment-api",
    "tenant_id": TENANT_ID,
    "error_class": "OOMKilled",
    "severity_hint": "critical",
    "raw_log": "Container payment-api-1 exited with code 137 (OOMKilled)",
    "fingerprint": "svc:payment-api|err:OOMKilled",
}

raw_body = json.dumps(payload).encode("utf-8")

signature = hmac.new(
    WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256
).hexdigest()

headers = {
    "Content-Type": "application/json",
    "X-Signature": f"sha256={signature}",
}

print(f"Sending test alert to {WEBHOOK_URL}")
response = requests.post(WEBHOOK_URL, data=raw_body, headers=headers, timeout=15)

print(f"API response: {response.status_code} - {response.json()}")
