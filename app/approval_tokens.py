from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from app.config import settings

def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def _b64d(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))

def sign_approval_token(
    thread_id: str,
    decision: str,
    ttl_minutes: int | None = None,
    tenant_id: str | None = None,
) -> str:
    ttl = ttl_minutes if ttl_minutes is not None else settings.approval_token_ttl_minutes
    payload = {
        "t": thread_id,
        "d": decision,
        "e": int(time.time()) + ttl * 60,
        "jti": secrets.token_urlsafe(16),
    }
    if tenant_id:
        payload["tenant"] = tenant_id
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(
        settings.approval_token_secret.encode(), raw, hashlib.sha256
    ).digest()
    return f"{_b64e(raw)}.{_b64e(signature)}"

def verify_approval_token(token: str) -> dict | None:
    try:
        raw_b64, sig_b64 = token.split(".")
        raw = _b64d(raw_b64)
        expected = hmac.new(
            settings.approval_token_secret.encode(), raw, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _b64d(sig_b64)):
            return None
        payload = json.loads(raw)
        if int(payload.get("e", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None
