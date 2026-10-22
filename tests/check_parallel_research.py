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
from app.state import OpsFlowState, ResearchResult, new_incident
from db.models import FixOutcome, Incident
from db.session import SessionLocal
from integrations.fake_kb import FakeKnowledgeBase
from integrations.knowledge_service import KnowledgeService

class FakeWebTool:
    def invoke(self, payload):
        return [{"title": "Web hit", "url": "http://web", "snippet": "web snippet"}]

def _collect(state: OpsFlowState) -> dict:
    return {}

def build_graph():
    builder = StateGraph(OpsFlowState)
    builder.add_node("plan_research", plan_research)
    builder.add_node("research_kb", research_kb)
    builder.add_node("research_web", research_web)
    builder.add_node("research_history", research_history)
    builder.add_node("collect", _collect)
    builder.add_edge(START, "plan_research")
    builder.add_conditional_edges(
        "plan_research",
        dispatch_research,
        ["research_kb", "research_web", "research_history"],
    )
    builder.add_edge("research_kb", "collect")
    builder.add_edge("research_web", "collect")
    builder.add_edge("research_history", "collect")
    builder.add_edge("collect", END)
    return builder.compile(checkpointer=make_checkpointer("memory"))

def _seed_history(tenant: str, service: str, error_class: str) -> None:
    with SessionLocal() as session:
        incident = Incident(
            thread_id=f"par-{uuid.uuid4().hex[:8]}",
            source="test",
            service=service,
            tenant_id=tenant,
            error_class=error_class,
            severity="high",
            status="completed",
        )
        session.add(incident)
        session.flush()
        session.add(
            FixOutcome(
                incident_id=incident.incident_id,
                remediation_id="increase_memory_limit",
                params={"container_name": service, "new_memory_limit": "2Gi"},
                outcome="success",
                confidence=80,
                applied_at=datetime.now(timezone.utc),
                verified_at=datetime.now(timezone.utc),
                stable=True,
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
    service = f"par-check-{int(time.time())}"
    _cleanup(service)
    thread_id = f"par-thread-{int(time.time())}"

    try:
        _seed_history("acme", service, "OOMKilled")

        kb = FakeKnowledgeBase()
        kb.add(
            "acme",
            ResearchResult(
                source="kb", title="Acme runbook", url=None, snippet="kb snippet", score=0.9
            ),
        )
        set_kb_service(KnowledgeService([("tenant_kb", kb)], fallback_enabled=False))

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
            state["diagnosis"] = "OOM killed"
            state["root_cause"] = "memory limit too low"
            state["severity"] = "high"
            state["evidence"] = ["exit code 137"]

            graph = build_graph()
            result = graph.invoke(state, {"configurable": {"thread_id": thread_id}})
        finally:
            web_module.web_search = original_web
            set_kb_service(None)

        sources = sorted(item.source for item in result["research"])
        assert sources == ["history", "kb", "web"], sources
        print("merged    ->", sources)

        assert result.get("research_query")
        print("query     ->", result["research_query"])

        research_events = [event for event in result["audit"] if event.action == "research"]
        assert len(research_events) == 3, len(research_events)
        print("agents    -> 3 research audit events")

        sends = dispatch_research({"tenant_id": "acme"})
        assert [send.node for send in sends] == [
            "research_kb",
            "research_web",
            "research_history",
        ]
        print("dispatch  ->", [send.node for send in sends])

        print("[ok] P2-12 -- parallel research (Send map-reduce) working.")
    finally:
        set_kb_service(None)
        _cleanup(service)

if __name__ == "__main__":
    main()
