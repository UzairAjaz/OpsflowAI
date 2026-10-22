from __future__ import annotations

import httpx

from app.state import ResearchResult

class LiveConnectorKnowledgeBase:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._api_key = api_key
        self._timeout = timeout

    def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        max_results: int = 5,
        service: str | None = None,
        error_class: str | None = None,
    ) -> list[ResearchResult]:
        if not self._base_url:
            return []

        payload = {"tenant_id": tenant_id, "query": query, "top_k": max_results}
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(f"{self._base_url}/v1/search", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        return [
            ResearchResult(
                source="kb",
                title=str(item.get("title", "")),
                url=item.get("url") or None,
                snippet=str(item.get("snippet", "")),
                score=float(item.get("score", 0.0)),
            )
            for item in data.get("results", [])
            if item.get("snippet")
        ]
