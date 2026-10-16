"""P2-10 check: multi-tenant knowledge base and graceful fallback chain.

Verifies:
- tenant KB results are used first (no fallback),
- an empty tenant KB falls through to live connectors,
- an empty connector falls through to web search (marked low confidence),
- tenant isolation (a query never returns another tenant's documents),
- namespace derivation,
- the kb_search tool,
- tenant_id is normalized and persisted on alerts and incidents.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import delete, select

from app.state import ResearchResult
from app.tools.kb_search import kb_search, set_knowledge_base
from db.models import Incident, ProcessedAlert
from db.session import SessionLocal
from ingestion.schema import normalize_alert
from ingestion.service import ingest_payload
from integrations.fake_kb import FakeKnowledgeBase
from integrations.knowledge_service import KnowledgeService
from integrations.tenant_kb import TenantVectorKnowledgeBase
from worker.tasks import create_incident


class StubWeb:
    def retrieve(
        self, *, tenant_id: str, query: str, max_results: int = 5, service=None, error_class=None
    ):
        return [
            ResearchResult(
                source="web",
                title="Web fallback page",
                url="http://example.com",
                snippet="generic guidance",
                score=0.2,
                is_low_confidence=True,
            )
        ]


def _hit(title: str) -> ResearchResult:
    return ResearchResult(source="kb", title=title, url=None, snippet="runbook steps", score=0.9)


def build_service() -> KnowledgeService:
    tenant_kb = FakeKnowledgeBase()
    tenant_kb.add("acme", _hit("Acme OOM runbook"))
    connector = FakeKnowledgeBase()
    connector.add("beta", _hit("Beta Confluence page"))
    return KnowledgeService(
        [("tenant_kb", tenant_kb), ("live_connector", connector), ("web", StubWeb())]
    )


def main() -> None:
    service = build_service()

    acme = service.retrieve(tenant_id="acme", query="oom")
    assert acme.source_used == "tenant_kb" and not acme.fallback_used
    print("acme   ->", acme.source_used, "|", acme.results[0].title)

    beta = service.retrieve(tenant_id="beta", query="oom")
    assert beta.source_used == "live_connector" and beta.fallback_used
    print("beta   ->", beta.source_used, "|", beta.results[0].title)

    gamma = service.retrieve(tenant_id="gamma", query="oom")
    assert gamma.source_used == "web" and gamma.fallback_used
    assert gamma.results[0].is_low_confidence is True
    print("gamma  ->", gamma.source_used, "| low_confidence =", gamma.results[0].is_low_confidence)

    assert all("Acme" not in result.title for result in gamma.results)
    print("isolation -> gamma did not see acme documents")

    namespace = TenantVectorKnowledgeBase("http://kb", namespace_prefix="tenant_").namespace_for(
        "acme"
    )
    assert namespace == "tenant_acme"
    print("namespace ->", namespace)

    set_knowledge_base(service)
    try:
        hits = kb_search.invoke({"tenant_id": "acme", "query": "oom", "max_results": 5})
    finally:
        set_knowledge_base(None)
    assert isinstance(hits, list) and hits and hits[0]["source"] == "kb"
    print("kb_search ->", hits[0]["title"])

    assert normalize_alert({"source": "x", "service": "y", "tenant_id": "acme"}).tenant_id == "acme"
    assert normalize_alert({"source": "x", "service": "y"}).tenant_id == "default"
    print("alert  -> tenant_id parsed (acme) and defaulted (default)")

    svc = f"kb-check-{int(time.time())}"
    payload = {
        "source": "cloudwatch",
        "service": svc,
        "tenant_id": "acme",
        "error_class": "OOMKilled",
        "severity_hint": "critical",
        "raw_log": "container out of memory",
    }
    with SessionLocal() as session:
        session.execute(delete(ProcessedAlert).where(ProcessedAlert.service == svc))
        session.commit()
    try:
        ingested = ingest_payload(payload)
        assert ingested.alert.tenant_id == "acme"

        incident_id, created = create_incident(ingested.alert.alerts_signature)
        assert created

        with SessionLocal() as session:
            row = session.get(ProcessedAlert, ingested.alert.alerts_signature)
            incident = session.get(Incident, uuid.UUID(incident_id))
            assert row.tenant_id == "acme"
            assert incident.tenant_id == "acme"
        print("db     -> tenant_id persisted on processed_alerts and incidents")
    finally:
        with SessionLocal() as session:
            session.execute(delete(ProcessedAlert).where(ProcessedAlert.service == svc))
            incidents = (
                session.execute(select(Incident).where(Incident.service == svc)).scalars().all()
            )
            for incident in incidents:
                session.delete(incident)
            session.commit()

    print("[ok] P2-10 -- multi-tenant knowledge base + fallback chain working.")


if __name__ == "__main__":
    main()
