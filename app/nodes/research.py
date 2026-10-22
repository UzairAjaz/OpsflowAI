from __future__ import annotations

from langgraph.types import Send

from app.config import settings
from app.state import AuditEvent, OpsFlowState, ResearchResult
from app.tools.knowledge import KnowledgeBase

_KB_SERVICE: KnowledgeBase | None = None

def set_kb_service(service: KnowledgeBase | None) -> None:
    global _KB_SERVICE
    _KB_SERVICE = service

def _kb_service() -> KnowledgeBase:
    global _KB_SERVICE
    if _KB_SERVICE is None:
        from integrations.knowledge_service import get_internal_knowledge_service

        _KB_SERVICE = get_internal_knowledge_service()
    return _KB_SERVICE

def _build_query(state: OpsFlowState) -> str:
    parts = [
        state.get("root_cause", ""),
        state.get("diagnosis", ""),
        *state.get("evidence", [])[:2],
    ]
    text = " ".join(part for part in parts if part)

    seen: set[str] = set()
    words: list[str] = []
    for word in text.split():
        key = word.lower().strip(".,:;()[]")
        if key and key not in seen:
            seen.add(key)
            words.append(word)

    return " ".join(words[:20]) or "server error"

def plan_research(state: OpsFlowState) -> dict:
    query = state.get("refined_query") or _build_query(state)
    return {"research_query": query}

def dispatch_research(state: OpsFlowState):
    return [
        Send("research_kb", state),
        Send("research_web", state),
        Send("research_history", state),
    ]

def research_kb(state: OpsFlowState) -> dict:
    query = state.get("research_query") or _build_query(state)
    try:
        response = _kb_service().retrieve(
            tenant_id=state.get("tenant_id", "default"),
            query=query,
            max_results=settings.web_max_results,
            service=state.get("service") or None,
            error_class=state.get("error_class") or None,
        )
        results = response.results
        detail = f"kb -> {len(results)} result(s) (source={response.source_used})"
    except Exception as exc:
        results = []
        detail = f"kb failed: {exc}"
    return {
        "research": results,
        "audit": [AuditEvent(actor="agent", action="research", detail=detail)],
    }

def research_web(state: OpsFlowState) -> dict:
    from app.tools.web_search import web_search

    query = state.get("research_query") or _build_query(state)
    try:
        raw = web_search.invoke({"query": query, "max_results": settings.web_max_results})
        results = [
            ResearchResult(
                source="web",
                title=item.get("title", ""),
                url=item.get("url") or None,
                snippet=item.get("snippet", ""),
                score=0.5,
            )
            for item in raw
            if item.get("snippet")
        ]
        detail = f"web -> {len(results)} result(s)"
    except Exception as exc:
        results = []
        detail = f"web failed: {exc}"
    return {
        "research": results,
        "audit": [AuditEvent(actor="agent", action="research", detail=detail)],
    }

def research_history(state: OpsFlowState) -> dict:
    service = state.get("service")
    error_class = state.get("error_class")
    if not service or not error_class:
        return {
            "research": [],
            "audit": [
                AuditEvent(
                    actor="agent",
                    action="research",
                    detail="history skipped (no service/error_class)",
                )
            ],
        }

    from db.session import SessionLocal
    from integrations.history import find_prior_fix

    try:
        with SessionLocal() as session:
            fix = find_prior_fix(
                session,
                tenant_id=state.get("tenant_id", "default"),
                service=service,
                error_class=error_class,
            )
        if fix:
            results = [
                ResearchResult(
                    source="history",
                    title=f"Past fix: {fix.remediation_id} (success rate {fix.success_rate:.0%})",
                    url=None,
                    snippet=f"{fix.occurrences} prior incident(s); params={fix.params}",
                    score=fix.success_rate,
                )
            ]
            detail = f"history -> {fix.remediation_id} rate={fix.success_rate}"
            return {
                "research": results,
                "prior_fix": fix.model_dump(mode="json"),
                "audit": [AuditEvent(actor="agent", action="research", detail=detail)],
            }

        results = []
        detail = "history -> no prior successful fix"
    except Exception as exc:
        results = []
        detail = f"history failed: {exc}"
    return {
        "research": results,
        "audit": [AuditEvent(actor="agent", action="research", detail=detail)],
    }
