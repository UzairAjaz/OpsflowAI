"""P2-15 check: Week 2 integration test.

Proves the Week 2 pipeline in a single command:

    seed -> plan_research -[Send]-> (kb | web | history) -> propose -> scoring

Deterministic (fake KB, fake web, seeded history, seeded critic score): no LLM,
no network. Verifies parallel multi-source research, tenant scoping, the
history-aware proposal, and rubric confidence.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from langgraph.graph import END, START, StateGraph
from sqlalchemy import delete, select

from app.checkpointer import make_checkpointer
from app.nodes.research import (
    dispatch_research,
    plan_research,
    research_history,
    research_kb,
    research_web,
    set_kb_service,
)
from app.nodes.researcher import propose
from app.nodes.scoring import score
from app.state import AuditEvent, OpsFlowState, ResearchResult, new_incident
from db.models import FixOutcome, Incident
from db.session import SessionLocal
from integrations.fake_kb import FakeKnowledgeBase
from integrations.knowledge_service import KnowledgeService


class FakeWebTool:
    def invoke(self, payload):
        return [{"title": "Web hit", "url": "http://web", "snippet": "web snippet"}]


def _seed(state: OpsFlowState) -> dict:
    return {
        "diagnosis": "OOM killed",
        "root_cause": "memory limit too low",
        "severity": "high",
        "evidence": ["exit code 137"],
        "critic_score": 85,
        "audit": [AuditEvent(actor="agent", action="analyze", detail="seed")],
    }


def build_graph():
    builder = StateGraph(OpsFlowState)
    builder.add_node("seed", _seed)
    builder.add_node("plan_research", plan_research)
    builder.add_node("research_kb", research_kb)
    builder.add_node("research_web", research_web)
    builder.add_node("research_history", research_history)
    builder.add_node("propose", propose)
    builder.add_node("scoring", score)
    builder.add_edge(START, "seed")
    builder.add_edge("seed", "plan_research")
    builder.add_conditional_edges(
        "plan_research",
        dispatch_research,
        ["research_kb", "research_web", "research_history"],
    )
    builder.add_edge("research_kb", "propose")
    builder.add_edge("research_web", "propose")
    builder.add_edge("research_history", "propose")
    builder.add_edge("propose", "scoring")
    builder.add_edge("scoring", END)
    return builder.compile(checkpointer=make_checkpointer("memory"))


def _seed_history(tenant: str, service: str, error_class: str, success_rate: float) -> None:
    with SessionLocal() as session:
        incident = Incident(
            thread_id=f"w2-{uuid.uuid4().hex[:8]}",
            source="test",
            service=service,
            tenant_id=tenant,
            error_class=error_class,
            severity="high",
            status="completed",
        )
        session.add(incident)
        session.flush()
        stable_count = round(success_rate * 10)
        for index in range(10):
            session.add(
                FixOutcome(
                    incident_id=incident.incident_id,
                    remediation_id="increase_memory_limit",
                    params={"container_name": service, "new_memory_limit": "2Gi"},
                    outcome="success" if index < stable_count else "failure",
                    confidence=85,
                    applied_at=datetime.now(timezone.utc),
                    verified_at=datetime.now(timezone.utc),
                    stable=index < stable_count,
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


def main() -> None:
    service = f"week2-{int(time.time())}"
    thread_id = f"week2-thread-{int(time.time())}"
    _cleanup(service)

    try:
        _seed_history("acme", service, "OOMKilled", success_rate=0.9)

        kb = FakeKnowledgeBase()
        kb.add(
            "acme",
            ResearchResult(
                source="kb", title="Acme runbook", url=None, snippet="kb snippet", score=0.9
            ),
        )
        kb_service = KnowledgeService([("tenant_kb", kb)], fallback_enabled=False)
        set_kb_service(kb_service)

        import app.tools.web_search as web_module

        original_web = web_module.web_search
        web_module.web_search = FakeWebTool()
        try:
            state = new_incident(
                "container out of memory",
                thread_id=thread_id,
                tenant_id="acme",
                service=service,
                error_class="OOMKilled",
            )
            graph = build_graph()
            result = graph.invoke(state, {"configurable": {"thread_id": thread_id}})
        finally:
            web_module.web_search = original_web

        sources = sorted(item.source for item in result["research"])
        assert sources == ["history", "kb", "web"], sources
        print("research  ->", sources)

        assert result["prior_fix"]["remediation_id"] == "increase_memory_limit"
        print("prior fix ->", result["prior_fix"]["remediation_id"], result["prior_fix"]["success_rate"])

        proposal = result["proposed_remediation"]
        assert proposal.remediation_id == "increase_memory_limit"
        propose_events = [event for event in result["audit"] if event.action == "propose"]
        assert propose_events and "source=history" in propose_events[0].detail
        print("propose   ->", propose_events[0].detail)

        assert result["confidence"] == 95, result["confidence"]
        assert result["automation_eligible"] is True
        assert result["manual_review"] is False
        print("confidence->", result["confidence"], result["confidence_breakdown"])

        # tenant isolation: a different tenant gets no internal knowledge
        other = research_kb(
            {"tenant_id": "beta", "research_query": "oom", "service": service, "error_class": "OOMKilled"}
        )
        assert other["research"] == []
        print("isolation -> beta sees no acme knowledge")

        set_kb_service(None)

        print("")
        print("[ok] P2-15 -- Week 2 exit criteria pass:")
        print("     multi-tenant KB -> parallel research -> history-aware proposal -> rubric confidence")
    finally:
        set_kb_service(None)
        _cleanup(service)


if __name__ == "__main__":
    main()
