from __future__ import annotations

import httpx

from app.state import ResearchResult

class TenantVectorKnowledgeBase:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        namespace_prefix: str = "tenant_",
        timeout: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._namespace_prefix = namespace_prefix
        self._timeout = timeout

    def namespace_for(self, tenant_id: str) -> str:
        return f"{self._namespace_prefix}{tenant_id}"

    def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        max_results: int = 5,
        service: str | None = None,
        error_class: str | None = None,
    ) -> list[ResearchResult]:
        payload = {
            "tenant_id": tenant_id,
            "namespace": self.namespace_for(tenant_id),
            "query": query,
            "top_k": max_results,
        }
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
