from __future__ import annotations

from app.state import ResearchResult

class FakeKnowledgeBase:
    def __init__(self, docs: dict[str, list[ResearchResult]] | None = None) -> None:
        self._docs: dict[str, list[ResearchResult]] = docs or {}

    def add(self, tenant_id: str, result: ResearchResult) -> None:
        self._docs.setdefault(tenant_id, []).append(result)

    def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        max_results: int = 5,
        service: str | None = None,
        error_class: str | None = None,
    ) -> list[ResearchResult]:
        return list(self._docs.get(tenant_id, []))[:max_results]
