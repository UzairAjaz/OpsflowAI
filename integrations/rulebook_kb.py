from __future__ import annotations

from sqlalchemy import select

from app.embeddings import embed_query
from app.state import ResearchResult
from db.models import Rulebook, RulebookChunk
from db.session import SessionLocal

class RulebookRetriever:
    name = "pgvector"

    def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        max_results: int = 5,
        service: str | None = None,
        error_class: str | None = None,
    ) -> list[ResearchResult]:
        query_vector = embed_query(query)

        distance = RulebookChunk.embedding.cosine_distance(query_vector)

        with SessionLocal() as session:
            rows = (
                session.execute(
                    select(RulebookChunk, Rulebook, distance)
                    .join(
                        Rulebook,
                        RulebookChunk.rulebook_id == Rulebook.rulebook_id,
                    )
                    .where(
                        RulebookChunk.tenant_id == tenant_id,
                        Rulebook.tenant_id == tenant_id,
                        Rulebook.is_active.is_(True),
                        RulebookChunk.embedding.is_not(None),
                    )
                    .order_by(distance)
                    .limit(max(1, max_results) * 4)
                )
                .all()
            )

        results: list[ResearchResult] = []
        seen_rulebooks: set[str] = set()

        for chunk, rulebook, distance_value in rows:
            rulebook_key = str(rulebook.rulebook_id)
            if rulebook_key in seen_rulebooks:
                continue
            seen_rulebooks.add(rulebook_key)

            score = max(0.0, min(1.0, 1.0 - float(distance_value)))

            results.append(
                ResearchResult(
                    source="kb",
                    title=rulebook.title,
                    url=None,
                    snippet=chunk.content[:500],
                    score=score,
                )
            )
            if len(results) >= max_results:
                break

        return results

__all__ = ["RulebookRetriever"]
