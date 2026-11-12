from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.rulebooks import replace_rulebook_chunks
from db.models import FixOutcome, Incident, Rulebook, Tenant, User
from db.session import SessionLocal

TENANT_ID = settings.demo_tenant_id
TENANT_NAME = settings.demo_tenant_name
SERVICE = settings.demo_service
ERROR_CLASS = settings.demo_error_class

OOM_RUNBOOK = f"""# {TENANT_NAME} Backend OOMKilled Runbook

## When to use
Use this runbook when the `{SERVICE}` container exits with code 137
or Kubernetes reports `{ERROR_CLASS}`.

## Symptoms
- Container restart count increases
- Exit code 137
- Memory usage near the configured limit
- Authentication or API requests time out during restart

## Diagnosis
1. Confirm the container exit reason.
2. Compare current memory usage with the configured limit.
3. Check recent deploys for memory growth.
4. Check for memory leaks or large report-generation jobs.

## Safe remediation
1. Raise the container memory limit in small steps, for example 2Gi.
2. Restart the container.
3. Verify the health endpoint and error rate after restart.

## Rollback
Revert the memory limit to the previous value if the service becomes unstable.

## Risk
Medium. The action is reversible.
"""

def _seed_tenant(session) -> Tenant:
    tenant = session.get(Tenant, TENANT_ID)
    if tenant is None:
        tenant = Tenant(tenant_id=TENANT_ID, name=TENANT_NAME)
        session.add(tenant)
        session.flush()

    channels = ["console"]
    if settings.smtp_host and settings.smtp_to:
        channels.append("email")
    if settings.slack_webhook_url:
        channels.append("slack")

    tenant_settings = dict(tenant.settings or {})
    tenant_settings["notifications"] = {
        "channels": channels,
        "email_to": settings.smtp_to or settings.demo_email,
    }
    tenant_settings["approval_base_url"] = settings.public_base_url
    tenant.settings = tenant_settings
    return tenant

def _seed_user(session) -> User:
    user = session.execute(
        select(User).where(
            User.tenant_id == TENANT_ID,
            User.email == settings.demo_email,
        )
    ).scalar_one_or_none()
    if user is None:
        user = User(
            tenant_id=TENANT_ID,
            email=settings.demo_email,
            display_name="MediConnect Admin",
            role="admin",
        )
        session.add(user)
        session.flush()
    return user

def _seed_rulebook(session, user: User) -> Rulebook:
    rulebook = session.execute(
        select(Rulebook).where(
            Rulebook.tenant_id == TENANT_ID,
            Rulebook.title == "MediConnect Backend OOMKilled Runbook",
            Rulebook.version == 1,
        )
    ).scalar_one_or_none()
    if rulebook is None:
        rulebook = Rulebook(
            tenant_id=TENANT_ID,
            title="MediConnect Backend OOMKilled Runbook",
            content=OOM_RUNBOOK,
            tags=["oom", "memory", "mediconnect-backend"],
            version=1,
            created_by=user.user_id,
        )
        session.add(rulebook)
        session.flush()
    return rulebook

def _seed_history(session) -> None:
    existing = session.execute(
        select(FixOutcome)
        .join(Incident, FixOutcome.incident_id == Incident.incident_id)
        .where(
            Incident.tenant_id == TENANT_ID,
            Incident.service == SERVICE,
            Incident.error_class == ERROR_CLASS,
            FixOutcome.remediation_id == "increase_memory_limit",
        )
    ).scalars().first()
    if existing is not None:
        return

    now = datetime.now(timezone.utc)
    incident = Incident(
        thread_id=f"mediconnect-seed-{uuid.uuid4().hex[:8]}",
        source="cloudwatch",
        service=SERVICE,
        tenant_id=TENANT_ID,
        error_class=ERROR_CLASS,
        severity="high",
        status="completed",
        resolved_at=now,
    )
    session.add(incident)
    session.flush()
    session.add(
        FixOutcome(
            incident_id=incident.incident_id,
            tenant_id=TENANT_ID,
            remediation_id="increase_memory_limit",
            params={"container_name": SERVICE, "new_memory_limit": "2Gi"},
            outcome="success",
            confidence=90,
            applied_at=now,
            verified_at=now,
            stable=True,
        )
    )

def main() -> None:
    with SessionLocal() as session:
        _seed_tenant(session)
        user = _seed_user(session)
        rulebook = _seed_rulebook(session, user)
        chunk_count = replace_rulebook_chunks(session, rulebook)
        _seed_history(session)
        session.commit()
    print(
        f"MediConnect seed complete: tenant={TENANT_ID}, "
        f"service={SERVICE}, chunks={chunk_count}"
    )

if __name__ == "__main__":
    main()
