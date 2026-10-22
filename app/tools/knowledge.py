from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from app.state import ResearchResult

class KnowledgeResponse(BaseModel):
    results: list[ResearchResult]
    source_used: str | None = None
    fallback_used: bool = False

class KnowledgeSource(Protocol):

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

    def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        max_results: int = 5,
        service: str | None = None,
        error_class: str | None = None,
    ) -> KnowledgeResponse: ...
