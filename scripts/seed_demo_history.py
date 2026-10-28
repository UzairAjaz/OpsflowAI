from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from db.models import FixOutcome, Incident
from db.session import SessionLocal

TENANT_ID = "acme"

SEEDS: list[tuple[str, str, str, dict[str, str]]] = [
    (
        "payment-api",
        "OOMKilled",
        "increase_memory_limit",
        {"container_name": "payment-api", "new_memory_limit": "2Gi"},
    ),
    (
        "payment-api-demo",
        "OOMKilled",
        "increase_memory_limit",
        {"container_name": "payment-api-demo", "new_memory_limit": "2Gi"},
    ),
    (
        "payment-api-demo-2",
        "OOMKilled",
        "increase_memory_limit",
        {"container_name": "payment-api-demo-2", "new_memory_limit": "2Gi"},
    ),
    (
        "payment-api-demo-3",
        "OOMKilled",
        "increase_memory_limit",
        {"container_name": "payment-api-demo-3", "new_memory_limit": "2Gi"},
    ),
    (
        "auth-service",
        "HighCPU",
        "restart_container",
        {"container_name": "auth-service"},
    ),
    (
        "auth-service-demo",
        "HighCPU",
        "restart_container",
        {"container_name": "auth-service-demo"},
    ),
    (
        "db-master",
        "DiskSpaceFull",
        "run_python_script",
        {
            "script_path": "scripts/cleanup_disk.py",
            "args": "--older-than 30d",
        },
    ),
    (
        "db-master-demo",
        "DiskSpaceFull",
        "run_python_script",
        {
            "script_path": "scripts/cleanup_disk.py",
            "args": "--older-than 30d",
        },
    ),
]

def _already_seeded(session, service: str, error_class: str, remediation_id: str) -> bool:
    statement = (
        select(FixOutcome)
        .join(Incident, FixOutcome.incident_id == Incident.incident_id)
        .where(
            Incident.tenant_id == TENANT_ID,
            Incident.service == service,
            Incident.error_class == error_class,
            FixOutcome.remediation_id == remediation_id,
        )
    )
    return session.execute(statement).scalars().first() is not None

def main() -> None:
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        for service, error_class, remediation_id, params in SEEDS:
            if _already_seeded(session, service, error_class, remediation_id):
                print(f"skip   {service}/{error_class} (already seeded)")
                continue

            incident = Incident(
                thread_id=f"demo-seed-{uuid.uuid4().hex[:8]}",
                source="cloudwatch",
                service=service,
                tenant_id=TENANT_ID,
                error_class=error_class,
                severity="high",
                status="completed",
                resolved_at=now,
            )
            session.add(incident)
            session.flush()
            session.add(
                FixOutcome(
                    incident_id=incident.incident_id,
                    remediation_id=remediation_id,
                    params=params,
                    outcome="success",
                    confidence=90,
                    applied_at=now,
                    verified_at=now,
                    stable=True,
                )
            )
            print(f"seeded {service}/{error_class} -> {remediation_id}")

        session.commit()

if __name__ == "__main__":
    main()
