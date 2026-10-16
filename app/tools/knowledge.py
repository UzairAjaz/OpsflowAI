"""Knowledge base port (domain interface).

OpsFlow depends only on this interface. Concrete backends — a managed
multi-tenant vector store, live external connectors, a web fallback, or fakes
used in tests — live in the integrations layer and are injected at runtime, so
the agent stays provider-neutral.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from app.state import ResearchResult


class KnowledgeResponse(BaseModel):
    results: list[ResearchResult]
    source_used: str | None = None
    fallback_used: bool = False


class KnowledgeSource(Protocol):
    """A single retrieval backend (managed KB, connector, history, web)."""

    def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        max_results: int = 5,
        service: str | None = None,
        error_class: str | None = None,
    ) -> list[ResearchResult]: ...


class KnowledgeBase(Protocol):
    """A composite knowledge base that returns results plus retrieval metadata."""

    def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        max_results: int = 5,
        service: str | None = None,
        error_class: str | None = None,
    ) -> KnowledgeResponse: ...
