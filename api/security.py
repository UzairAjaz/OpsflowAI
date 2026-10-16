"""Request security helpers.

Provides HMAC-SHA256 signing and verification for inbound webhooks. The
signature is sent in the X-Signature header as `sha256=<hex digest>`.
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_HEADER = "X-Signature"


def _digest(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def sign_payload(secret: str, body: bytes) -> str:
    """Return the `sha256=<hex>` signature for a payload (used by senders/tests)."""
    return f"sha256={_digest(secret, body)}"


def verify_hmac_sha256(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify a webhook signature in constant time."""
    if not signature_header:
        return False
    provided = signature_header.split("=", 1)[-1].strip()
    if not provided:
        return False
    return hmac.compare_digest(_digest(secret, body), provided)


def verify_slack_signature(
    signing_secret: str, timestamp: str | None, body: bytes, signature: str | None
) -> bool:
    """Verify a Slack interactive callback signature (v0 scheme)."""
    if not signing_secret:
        return True  # verification disabled in dev
    if not timestamp or not signature:
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_tenant_api_keys(raw: str) -> dict[str, str]:
    """Parse 'tenant:key,tenant2:key2' into {key: tenant}."""
    mapping: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        tenant, key = pair.split(":", 1)
        mapping[key.strip()] = tenant.strip()
    return mapping


def authenticate_api_key(raw_keys: str, api_key: str | None) -> str | None:
    """Return the tenant for an API key, or 'default' when auth is disabled."""
    mapping = parse_tenant_api_keys(raw_keys)
    if not mapping:
        return "default"
    if api_key and api_key in mapping:
        return mapping[api_key]
    return None
