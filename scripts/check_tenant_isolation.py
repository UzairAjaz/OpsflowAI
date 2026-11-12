from __future__ import annotations

from sqlalchemy import delete, select

from db.models import Rulebook, Tenant
from db.session import SessionLocal

MEDICONNECT = "mediconnect"
TEMP_TENANT = "isolation-check"
TEMP_TITLE = "ISOLATION_SECRET_RULEBOOK"

def _cleanup(session) -> None:
    session.execute(delete(Rulebook).where(Rulebook.tenant_id == TEMP_TENANT))
    session.execute(delete(Tenant).where(Tenant.tenant_id == TEMP_TENANT))

def main() -> None:
    with SessionLocal() as session:
        mediconnect = session.get(Tenant, MEDICONNECT)
        if mediconnect is None:
            raise SystemExit("MediConnect tenant is not seeded. Run scripts.seed_mediconnect first.")

        _cleanup(session)
        session.add(Tenant(tenant_id=TEMP_TENANT, name="Isolation Check"))
        session.flush()
        session.add(
            Rulebook(
                tenant_id=TEMP_TENANT,
                title=TEMP_TITLE,
                content="This rule must never appear in a MediConnect query.",
                tags=["isolation"],
            )
        )
        session.commit()

    try:
        with SessionLocal() as session:
            mediconnect_rules = (
                session.execute(
                    select(Rulebook).where(Rulebook.tenant_id == MEDICONNECT)
                )
                .scalars()
                .all()
            )
            assert all(rule.tenant_id == MEDICONNECT for rule in mediconnect_rules)
            assert not any(rule.title == TEMP_TITLE for rule in mediconnect_rules)

            temp_rules = (
                session.execute(
                    select(Rulebook).where(Rulebook.tenant_id == TEMP_TENANT)
                )
                .scalars()
                .all()
            )
            assert len(temp_rules) == 1
            assert temp_rules[0].title == TEMP_TITLE

        print("[ok] MediConnect queries cannot see the isolation-check tenant.")
    finally:
        with SessionLocal() as session:
            _cleanup(session)
            session.commit()

if __name__ == "__main__":
    main()
