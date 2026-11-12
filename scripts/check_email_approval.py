from __future__ import annotations

import time
import uuid

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from api.main import app
from app.approval_tokens import sign_approval_token
from app.config import settings
from db.models import ApprovalTokenUse, AuditLog, Incident
from db.session import SessionLocal

TENANT = "mediconnect"
SERVICE = "mediconnect-backend"
THREADS: list[str] = []

def _create_incident(thread_id: str, tenant_id: str = TENANT) -> None:
    THREADS.append(thread_id)
    with SessionLocal() as session:
        session.add(
            Incident(
                thread_id=thread_id,
                source="cloudwatch",
                service=SERVICE,
                tenant_id=tenant_id,
                error_class="OOMKilled",
                severity="high",
                status="awaiting_approval",
            )
        )
        session.commit()

def _cleanup() -> None:
    with SessionLocal() as session:
        session.execute(
            delete(ApprovalTokenUse).where(ApprovalTokenUse.thread_id.in_(THREADS))
        )
        session.execute(
            delete(AuditLog).where(
                AuditLog.details["thread_id"].astext.in_(THREADS)
            )
        )
        for thread_id in THREADS:
            incident = session.execute(
                select(Incident).where(Incident.thread_id == thread_id)
            ).scalar_one_or_none()
            if incident is not None:
                session.delete(incident)
        session.commit()

def _jwt(thread_id: str, decision: str, tenant_id: str = TENANT) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "t": thread_id,
            "d": decision,
            "e": now + 600,
            "jti": f"jwt-{uuid.uuid4().hex[:12]}",
            "tenant": tenant_id,
        },
        settings.approval_token_secret,
        algorithm="HS256",
    )

def main() -> None:
    hmac_thread = f"email-hmac-{uuid.uuid4().hex[:8]}"
    jwt_thread = f"email-jwt-{uuid.uuid4().hex[:8]}"
    tenant_thread = f"email-tenant-{uuid.uuid4().hex[:8]}"

    _create_incident(hmac_thread)
    _create_incident(jwt_thread)
    _create_incident(tenant_thread, tenant_id="other-tenant")

    try:
        with TestClient(app) as client:
            token = sign_approval_token(
                hmac_thread, "approve", tenant_id=TENANT
            )
            response = client.get("/api/v1/approvals/email", params={"token": token})
            assert response.status_code == 200, response.text
            assert "text/html" in response.headers["content-type"]
            assert "Remediation approved" in response.text
            print("hmac token  -> HTML success page")

            response = client.get(
                "/api/v1/approvals/email",
                params={"token": _jwt(jwt_thread, "reject")},
            )
            assert response.status_code == 200, response.text
            assert "Rejected" in response.text
            print("jwt token   -> HTML success page")

            response = client.get(
                "/api/v1/approvals/email",
                params={"token": "not-a-valid-token"},
            )
            assert response.status_code == 400, response.text
            assert "text/html" in response.headers["content-type"]
            print("invalid     -> HTML error page")

            wrong_tenant = sign_approval_token(
                tenant_thread, "approve", tenant_id=TENANT
            )
            response = client.get(
                "/api/v1/approvals/email",
                params={"token": wrong_tenant},
            )
            assert response.status_code == 404, response.text
            assert "text/html" in response.headers["content-type"]
            print("tenant wall -> HTML 404")

        with SessionLocal() as session:
            hmac_incident = session.execute(
                select(Incident).where(Incident.thread_id == hmac_thread)
            ).scalar_one()
            jwt_incident = session.execute(
                select(Incident).where(Incident.thread_id == jwt_thread)
            ).scalar_one()
            assert hmac_incident.status == "approved"
            assert jwt_incident.status == "rejected"

            audits = session.execute(
                select(AuditLog).where(
                    AuditLog.details["thread_id"].astext.in_(
                        [hmac_thread, jwt_thread]
                    )
                )
            ).scalars().all()
            actions = {entry.action for entry in audits}
            assert {"approval.approve", "approval.reject"}.issubset(actions)

        print("database    -> status + audit rows updated")
        print("[ok] email approval HTML endpoint works.")
    finally:
        _cleanup()

if __name__ == "__main__":
    main()
