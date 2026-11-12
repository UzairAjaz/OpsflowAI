from __future__ import annotations

import uuid
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from api.main import app
from app.config import settings
from db.models import AuditLog, Rulebook, RulebookChunk
from db.session import SessionLocal

TENANT = "mediconnect"

def main() -> None:
    original_backend = settings.embedding_backend
    original_keys = settings.tenant_api_keys
    original_dev = settings.auth_dev_mode
    settings.embedding_backend = "fake"
    settings.tenant_api_keys = ""
    settings.auth_dev_mode = True

    title = f"MediConnect Test Rulebook {uuid.uuid4().hex[:8]}"
    rulebook_id: UUID | None = None

    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/tenants/{TENANT}/rulebooks",
                json={
                    "title": title,
                    "content": ("MediConnect OOM test content. " * 100).strip(),
                    "tags": ["oom", "test"],
                },
            )
            assert response.status_code == 201, response.text
            created = response.json()
            rulebook_id = UUID(created["rulebook_id"])
            assert created["tenant_id"] == TENANT
            assert created["version"] == 1
            print("create      ->", created["rulebook_id"], "version", created["version"])

            response = client.get(f"/api/v1/tenants/{TENANT}/rulebooks")
            assert response.status_code == 200, response.text
            assert any(item["rulebook_id"] == str(rulebook_id) for item in response.json())
            print("list        ->", len(response.json()), "rulebook(s)")

            response = client.get(
                f"/api/v1/tenants/{TENANT}/rulebooks/{rulebook_id}"
            )
            assert response.status_code == 200, response.text
            assert response.json()["title"] == title
            print("get         ->", response.json()["title"])

            response = client.put(
                f"/api/v1/tenants/{TENANT}/rulebooks/{rulebook_id}",
                json={
                    "content": ("Updated MediConnect OOM content. " * 120).strip(),
                    "tags": ["oom", "updated"],
                    "is_active": True,
                },
            )
            assert response.status_code == 200, response.text
            updated = response.json()
            assert updated["version"] == 2
            assert updated["tags"] == ["oom", "updated"]
            print("update      -> version", updated["version"])

            with SessionLocal() as session:
                chunk_count = session.execute(
                    select(func.count())
                    .select_from(RulebookChunk)
                    .where(RulebookChunk.rulebook_id == rulebook_id)
                ).scalar_one()
                assert chunk_count > 0
                chunk = session.execute(
                    select(RulebookChunk)
                    .where(RulebookChunk.rulebook_id == rulebook_id)
                    .limit(1)
                ).scalar_one()
                assert len(chunk.embedding) == settings.embedding_dimensions
            print("chunks      ->", chunk_count, "x", settings.embedding_dimensions, "dims")

            response = client.get("/api/v1/tenants/other-tenant/rulebooks")
            assert response.status_code == 404, response.text
            print("tenant wall -> other tenant hidden (404)")

            settings.tenant_api_keys = "mediconnect:viewer:view-key"
            response = client.post(
                f"/api/v1/tenants/{TENANT}/rulebooks",
                headers={"X-API-Key": "view-key"},
                json={"title": "Viewer should fail", "content": "nope"},
            )
            assert response.status_code == 403, response.text
            print("role wall   -> viewer cannot create (403)")

            settings.tenant_api_keys = ""
            settings.auth_dev_mode = True

            response = client.delete(
                f"/api/v1/tenants/{TENANT}/rulebooks/{rulebook_id}"
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "deleted"
            print("delete      ->", response.json()["status"])

            response = client.get(
                f"/api/v1/tenants/{TENANT}/rulebooks/{rulebook_id}"
            )
            assert response.status_code == 404, response.text
            print("verify      -> deleted rulebook is gone")

        print("[ok] Day 4 rulebook CRUD + embedding checks passed.")
    finally:
        settings.embedding_backend = original_backend
        settings.tenant_api_keys = original_keys
        settings.auth_dev_mode = original_dev

        if rulebook_id is not None:
            with SessionLocal() as session:
                rulebook = session.get(Rulebook, rulebook_id)
                if rulebook is not None:
                    session.delete(rulebook)
                session.execute(
                    delete(AuditLog).where(
                        AuditLog.tenant_id == TENANT,
                        AuditLog.details["rulebook_id"].astext == str(rulebook_id),
                    )
                )
                session.commit()

if __name__ == "__main__":
    main()
