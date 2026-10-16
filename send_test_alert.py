import requests
import hmac
import hashlib
import json

# Apne .env file se secret copy karein (ya jo aapne set kiya hai)
WEBHOOK_SECRET = "dev-secret-change-me" 
WEBHOOK_URL = "http://localhost:8000/api/v1/webhooks/alert"

# 1. Fake Alert Payload (Jaise Docker crash hua)
payload = {
    "source": "cloudwatch",
    "service": "payment-api",
    "error_class": "OOMKilled",
    "severity_hint": "critical",
    "raw_log": "Container payment-api-1 exited with code 137 (OOMKilled)",
    "fingerprint": "svc:payment-api|err:OOMKilled"
}

raw_body = json.dumps(payload).encode('utf-8')

# 2. HMAC Signature Generate karna
signature = hmac.new(
    WEBHOOK_SECRET.encode('utf-8'), 
    raw_body, 
    hashlib.sha256
).hexdigest()

headers = {
    "Content-Type": "application/json",
    "X-Signature": f"sha256={signature}"
}

# 3. Alert Bhejna
print("🚀 Sending fake Docker crash alert...")
response = requests.post(WEBHOOK_URL, data=raw_body, headers=headers)

print(f"✅ API Response: {response.status_code} - {response.json()}")