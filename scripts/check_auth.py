from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete

from api.auth import create_access_token
from api.main import app
from app.config import settings
from db.models import Incident
from db.session import SessionLocal

THREAD_ID = f"auth-check-{uuid.uuid4().hex[:8]}"

def main() -> None:
    original_keys = settings.tenant_api_keys
    original_dev = settings.auth_dev_mode

    with SessionLocal() as session:
        session.add(
            Incident(
                thread_id=THREAD_ID,
                source="cloudwatch",
                service="other-tenant-service",
                tenant_id="other-tenant",
                error_class="OOMKilled",
                severity="high",
                status="pending",
            )
        )
        session.commit()

    try:
        with TestClient(app) as client:
            settings.tenant_api_keys = ""
            settings.auth_dev_mode = True

            response = client.get("/api/v1/approvals/me")
            assert response.status_code == 200, response.text
            principal = response.json()
            assert principal["tenant_id"] == "mediconnect"
            assert principal["role"] == "admin"
            print("dev auth    ->", principal)

            settings.tenant_api_keys = (
                "mediconnect:approver:approver-key,"
                "mediconnect:viewer:viewer-key"
            )

            response = client.get(
                "/api/v1/approvals/me",
                headers={"X-API-Key": "approver-key"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["role"] == "approver"
            print("api key     ->", response.json())

            response = client.get(
                f"/api/v1/approvals/{THREAD_ID}",
                headers={"X-API-Key": "approver-key"},
            )
            assert response.status_code == 404, response.text
            print("tenant wall -> other tenant hidden (404)")

            response = client.post(
                "/api/v1/approvals/does-not-exist",
                headers={"X-API-Key": "viewer-key"},
                json={"approved": True},
            )
            assert response.status_code == 403, response.text
            print("role wall   -> viewer cannot approve (403)")

            response = client.post(
                "/api/v1/approvals/does-not-exist",
                headers={"X-API-Key": "approver-key"},
                json={"approved": True},
            )
            assert response.status_code == 409, response.text
            print("no pending  -> approver gets 409")

            token = create_access_token(
                tenant_id="mediconnect",
                subject="jwt-demo",
                role="viewer",
            )
            response = client.get(
                "/api/v1/approvals/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["subject"] == "jwt-demo"
            print("jwt auth    ->", response.json())

        print("[ok] Day 3 auth + tenant isolation checks passed.")
    finally:
        settings.tenant_api_keys = original_keys
        settings.auth_dev_mode = original_dev
        with SessionLocal() as session:
            session.execute(delete(Incident).where(Incident.thread_id == THREAD_ID))
            session.commit()

if __name__ == "__main__":
    main()
