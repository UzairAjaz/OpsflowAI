from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from fastapi import Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.config import settings
from db.models import Incident
from db.session import SessionLocal

Role = Literal["viewer", "responder", "approver", "admin"]
ROLES: tuple[Role, ...] = ("viewer", "responder", "approver", "admin")

class Principal(BaseModel):
    tenant_id: str
    subject: str
    role: Role

def _dev_principal() -> Principal:
    return Principal(
        tenant_id=settings.dev_tenant_id,
        subject="dev-admin",
        role="admin",
    )

def _parse_api_keys(raw: str) -> dict[str, Principal]:
    principals: dict[str, Principal] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue

        parts = pair.split(":")
        if len(parts) == 2:
            tenant_id, key = parts
            role: Role = "approver"
        elif len(parts) >= 3:
            tenant_id, role_value, *key_parts = parts
            key = ":".join(key_parts)
            role = role_value.strip().lower()  # type: ignore[assignment]
            if role not in ROLES:
                role = "viewer"
        else:
            continue

        tenant_id = tenant_id.strip()
        key = key.strip()
        if tenant_id and key:
            principals[key] = Principal(
                tenant_id=tenant_id,
                subject=f"api-key:{tenant_id}",
                role=role,
            )
    return principals

def _principal_from_api_key(api_key: str) -> Principal | None:
    return _parse_api_keys(settings.tenant_api_keys).get(api_key)

def _principal_from_authorization(authorization: str) -> Principal:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="invalid authorization header")

    try:
        payload = jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid or expired token")

    tenant_id = str(payload.get("tenant_id") or payload.get("tenant") or "").strip()
    subject = str(payload.get("sub") or "jwt-user")
    role = str(payload.get("role") or "viewer").lower()
    if not tenant_id or role not in ROLES:
        raise HTTPException(status_code=401, detail="invalid token claims")

    return Principal(tenant_id=tenant_id, subject=subject, role=role)

def create_access_token(
    *,
    tenant_id: str,
    subject: str,
    role: Role = "approver",
    ttl_minutes: int | None = None,
) -> str:
    if role not in ROLES:
        raise ValueError(f"invalid role: {role}")

    ttl = ttl_minutes if ttl_minutes is not None else settings.auth_token_ttl_minutes
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "tenant_id": tenant_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
    }
    return jwt.encode(
        payload,
        settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
    )

def get_principal(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Principal:
    if authorization:
        return _principal_from_authorization(authorization)

    if x_api_key:
        principal = _principal_from_api_key(x_api_key)
        if principal is None:
            raise HTTPException(status_code=401, detail="invalid API key")
        return principal

    if settings.auth_dev_mode and not settings.tenant_api_keys:
        return _dev_principal()

    raise HTTPException(status_code=401, detail="missing credentials")

def require_role(principal: Principal, *allowed: Role) -> None:
    if principal.role not in allowed:
        raise HTTPException(status_code=403, detail="insufficient permissions")

def ensure_incident_tenant(thread_id: str, tenant_id: str) -> None:
    with SessionLocal() as session:
        incident = session.execute(
            select(Incident).where(Incident.thread_id == thread_id)
        ).scalar_one_or_none()

    if incident is not None and incident.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="incident not found")

__all__ = [
    "Principal",
    "Role",
    "ROLES",
    "create_access_token",
    "ensure_incident_tenant",
    "get_principal",
    "require_role",
]
