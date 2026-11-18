"""Seed the local Retriva tenant, manager, and repository mapping.

Run after ``alembic upgrade head``:

    .\\.venv\\Scripts\\python.exe -m scripts.seed_retriva
"""

from __future__ import annotations

import os

from sqlalchemy import select

from db.models import RepositoryMapping, Tenant, User
from db.session import SessionLocal

TENANT_ID = "retriva"
TENANT_NAME = "Retriva AI"
MANAGER_EMAIL = os.getenv("RETRIVA_MANAGER_EMAIL", "uzairejaz987@gmail.com")
REPO_FULL_NAME = os.getenv("RETRIVA_REPO", "UzairAjaz/Retriva-AI")
SERVICE = os.getenv("RETRIVA_SERVICE", "retriva-api")
LOCAL_REPO_ROOT = os.getenv(
    "RETRIVA_REPO_ROOT", r"C:\Users\RQ\Documents\Retriva-AI"
)
LOG_GROUP = os.getenv("RETRIVA_LOG_GROUP", "/opsflow/retriva-api")


def _seed_tenant(session) -> Tenant:
    tenant = session.get(Tenant, TENANT_ID)
    if tenant is None:
        tenant = Tenant(tenant_id=TENANT_ID, name=TENANT_NAME)
        session.add(tenant)
        session.flush()

    settings = dict(tenant.settings or {})
    settings["notifications"] = {
        "channels": ["console"],
        "email_to": MANAGER_EMAIL,
    }
    settings["code_fix"] = {
        "enabled": False,
        "analysis_only": True,
    }
    tenant.settings = settings
    return tenant


def _seed_manager(session) -> User:
    user = session.execute(
        select(User).where(
            User.tenant_id == TENANT_ID,
            User.email == MANAGER_EMAIL,
        )
    ).scalar_one_or_none()
    if user is None:
        user = User(
            tenant_id=TENANT_ID,
            email=MANAGER_EMAIL,
            display_name="Retriva Admin",
            role="admin",
        )
        session.add(user)
        session.flush()
    return user


def _seed_mapping(session) -> RepositoryMapping:
    mapping = session.execute(
        select(RepositoryMapping).where(
            RepositoryMapping.tenant_id == TENANT_ID,
            RepositoryMapping.service == SERVICE,
        )
    ).scalar_one_or_none()
    if mapping is None:
        mapping = RepositoryMapping(
            tenant_id=TENANT_ID,
            service=SERVICE,
            repo_full_name=REPO_FULL_NAME,
            repo_path="",
            local_repo_root=LOCAL_REPO_ROOT,
            language="python",
            base_branch="main",
            log_group=LOG_GROUP,
            enabled=True,
        )
        session.add(mapping)
    else:
        mapping.repo_full_name = REPO_FULL_NAME
        mapping.local_repo_root = LOCAL_REPO_ROOT
        mapping.language = "python"
        mapping.base_branch = "main"
        mapping.log_group = LOG_GROUP
        mapping.enabled = True
    session.flush()
    return mapping


def main() -> None:
    with SessionLocal() as session:
        _seed_tenant(session)
        _seed_manager(session)
        mapping = _seed_mapping(session)
        session.commit()
        print(
            "Retriva seed complete: "
            f"tenant={TENANT_ID}, manager={MANAGER_EMAIL}, "
            f"service={SERVICE}, repo={mapping.repo_full_name}, "
            f"local_root={mapping.local_repo_root}"
        )


if __name__ == "__main__":
    main()
