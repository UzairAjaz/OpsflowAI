"""Knowledge service: multi-tenant retrieval with a graceful fallback chain.

Priority order:
    1. Managed Tenant KB (namespace-isolated vectors)
    2. Live External Connectors (Confluence / ServiceNow)
    3. Web Search (marked Low Confidence)

The first source that returns results wins. If an earlier source is empty or
errors, retrieval degrades gracefully instead of failing. Web results are marked
`is_low_confidence` so downstream confidence scoring can account for them.
"""

from __future__ import annotations

from app.config import settings
from app.state import ResearchResult
from app.tools.knowledge import KnowledgeBase, KnowledgeResponse


class WebKnowledgeBase:
    """Web fallback built on the existing DuckDuckGo tool; results are low confidence."""

    def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        max_results: int = 5,
        service: str | None = None,
        error_class: str | None = None,
    ) -> list[ResearchResult]:
        from app.tools.web_search import web_search

        raw = web_search.invoke({"query": query, "max_results": max_results})
        return [
            ResearchResult(
                source="web",
                title=item.get("title", ""),
                url=item.get("url") or None,
                snippet=item.get("snippet", ""),
                score=0.2,
                is_low_confidence=True,
            )
            for item in raw
            if item.get("snippet")
        ]


class KnowledgeService:
    def __init__(
        self,
        sources: list[tuple[str, KnowledgeBase]],
        fallback_enabled: bool = True,
    ) -> None:
        self._sources = sources
        self._fallback_enabled = fallback_enabled

    def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        max_results: int = 5,
        service: str | None = None,
        error_class: str | None = None,
    ) -> KnowledgeResponse:
        tried = 0
        for name, source in self._sources:
            if tried > 0 and not self._fallback_enabled:
                break
            try:
                results = source.retrieve(
                    tenant_id=tenant_id,
                    query=query,
                    max_results=max_results,
                    service=service,
                    error_class=error_class,
                )
            except Exception:
                results = []
            if results:
                return KnowledgeResponse(
                    results=results, source_used=name, fallback_used=tried > 0
                )
            tried += 1
        return KnowledgeResponse(results=[], source_used=None, fallback_used=False)


def _kb_sources() -> list[tuple[str, KnowledgeBase]]:
    sources: list[tuple[str, KnowledgeBase]] = []

    if settings.kb_backend == "tenant_http":
        from integrations.tenant_kb import TenantVectorKnowledgeBase

        sources.append(
            (
                "tenant_kb",
                TenantVectorKnowledgeBase(
                    base_url=settings.tenant_kb_base_url,
                    api_key=settings.tenant_kb_api_key,
                    namespace_prefix=settings.kb_namespace_prefix,
                    timeout=settings.kb_timeout_seconds,
                ),
            )
        )
        if settings.live_connector_base_url:
            from integrations.live_connectors import LiveConnectorKnowledgeBase

            sources.append(
                (
                    "live_connector",
                    LiveConnectorKnowledgeBase(
                        base_url=settings.live_connector_base_url,
                        api_key=settings.live_connector_api_key,
                        timeout=settings.kb_timeout_seconds,
                    ),
                )
            )
    elif settings.kb_backend == "fake":
        from integrations.fake_kb import FakeKnowledgeBase

        sources.append(("fake", FakeKnowledgeBase()))

    return sources


def get_internal_knowledge_service() -> KnowledgeService:
    """Managed knowledge sources only (tenant KB + live connectors).

    Used by the parallel KB research agent so it does not duplicate the separate
    history and web agents.
    """
    return KnowledgeService(_kb_sources(), fallback_enabled=True)


def get_knowledge_service() -> KnowledgeService:
    """Full fallback chain: KB -> connectors -> history -> web."""
    sources = _kb_sources()

    from integrations.history import HistoryKnowledgeBase

    sources.append(("history", HistoryKnowledgeBase()))

    if settings.kb_fallback_enabled:
        sources.append(("web", WebKnowledgeBase()))

    return KnowledgeService(sources, fallback_enabled=settings.kb_fallback_enabled)
