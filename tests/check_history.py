from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.state import ResearchResult
from app.tools.history_search import history_search
from db.models import FixOutcome, Incident
from db.session import SessionLocal
from integrations.fake_kb import FakeKnowledgeBase
from integrations.history import HistoryKnowledgeBase, find_prior_fix
from integrations.knowledge_service import KnowledgeService

def _seed(
    tenant: str,
    service: str,
    error_class: str,
    remediation_id: str,
    stable_values: list[bool],
    applied_at: datetime | None = None,
) -> None:
    applied_at = applied_at or datetime.now(timezone.utc)
    with SessionLocal() as session:
        incident = Incident(
            thread_id=f"hist-{uuid.uuid4().hex[:8]}",
            source="test",
            service=service,
            tenant_id=tenant,
            error_class=error_class,
            severity="high",
            status="completed",
        )
        session.add(incident)
        session.flush()
        for stable in stable_values:
            session.add(
                FixOutcome(
                    incident_id=incident.incident_id,
                    remediation_id=remediation_id,
                    params={"container_name": service, "new_memory_limit": "2Gi"},
                    outcome="success" if stable else "failure",
                    confidence=80,
                    applied_at=applied_at,
                    verified_at=applied_at,
                    stable=stable,
                    success_rate_before=0.5,
                )
            )
        session.commit()

def _cleanup(service: str) -> None:
    with SessionLocal() as session:
        incidents = (
            session.execute(select(Incident).where(Incident.service == service)).scalars().all()
        )
        ids = [incident.incident_id for incident in incidents]
        if ids:
            session.execute(delete(FixOutcome).where(FixOutcome.incident_id.in_(ids)))
        for incident in incidents:
            session.delete(incident)
        session.commit()

class StubWeb:
    def retrieve(self, *, tenant_id, query, max_results=5, service=None, error_class=None):
        return [
            ResearchResult(
                source="web", title="web", url=None, snippet="s", score=0.2, is_low_confidence=True
            )
        ]

def main() -> None:
    service = f"hist-check-{int(time.time())}"
    other = f"hist-other-{int(time.time())}"
    old = f"hist-old-{int(time.time())}"
    for name in (service, other, old):
        _cleanup(name)

    try:
        _seed("acme", service, "OOMKilled", "increase_memory_limit", [True, False])
        with SessionLocal() as session:
            fix = find_prior_fix(
                session, tenant_id="acme", service=service, error_class="OOMKilled"
            )
        assert fix is not None and fix.remediation_id == "increase_memory_limit"
        assert fix.occurrences == 2 and fix.success_rate == 0.5
        print(
            f"prior fix -> {fix.remediation_id} rate={fix.success_rate} occurrences={fix.occurrences}"
        )

        with SessionLocal() as session:
            none = find_prior_fix(
                session, tenant_id="beta", service=service, error_class="OOMKilled"
            )
        assert none is None
        print("isolation -> another tenant sees no history")

        _seed(
            "acme",
            old,
            "OOMKilled",
            "restart_container",
            [True],
            applied_at=datetime.now(timezone.utc) - timedelta(days=40),
        )
        with SessionLocal() as session:
            expired = find_prior_fix(
                session, tenant_id="acme", service=old, error_class="OOMKilled", days=30
            )
        assert expired is None
        print("window    -> 40-day-old outcome excluded (days=30)")

        source = HistoryKnowledgeBase()
        hits = source.retrieve(
            tenant_id="acme", query="oom", service=service, error_class="OOMKilled"
        )
        assert hits and hits[0].source == "history"
        print("source    ->", hits[0].title)
        assert source.retrieve(tenant_id="acme", query="oom") == []
        print("source    -> empty without service/error_class")

        result = history_search.invoke(
            {"tenant_id": "acme", "service": service, "error_class": "OOMKilled", "days": 30}
        )
        assert result and result["remediation_id"] == "increase_memory_limit"
        print("tool      ->", result["remediation_id"], "rate", result["success_rate"])

        empty = FakeKnowledgeBase()
        chain = KnowledgeService(
            [
                ("tenant_kb", empty),
                ("live_connector", empty),
                ("history", source),
                ("web", StubWeb()),
            ]
        )
        response = chain.retrieve(
            tenant_id="acme", query="oom", service=service, error_class="OOMKilled"
        )
        assert response.source_used == "history" and response.fallback_used
        print("chain     -> source_used =", response.source_used, "fallback =", response.fallback_used)

        print("[ok] P2-11 -- historical incidents tool working.")
    finally:
        for name in (service, other, old):
            _cleanup(name)

if __name__ == "__main__":
    main()
