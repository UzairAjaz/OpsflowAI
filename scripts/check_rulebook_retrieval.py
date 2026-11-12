from __future__ import annotations

from app.nodes.research import research_kb, set_kb_service
from app.state import new_incident
from integrations.rulebook_kb import RulebookRetriever

def main() -> None:
    retriever = RulebookRetriever()
    results = retriever.retrieve(
        tenant_id="mediconnect",
        query="OOMKilled memory limit exceeded",
        max_results=3,
    )
    assert results, "MediConnect rulebook retrieval returned no results"
    assert all(result.source == "kb" for result in results)
    assert any("MediConnect" in result.title for result in results)
    print("retriever ->", results[0].title, "| score", round(results[0].score, 3))

    other = retriever.retrieve(
        tenant_id="other-tenant",
        query="OOMKilled memory limit exceeded",
        max_results=3,
    )
    assert other == [], "cross-tenant retrieval leaked rulebooks"
    print("isolation -> other tenant returned 0 results")

    set_kb_service(None)
    state = new_incident(
        "container out of memory",
        tenant_id="mediconnect",
        service="mediconnect-backend",
        error_class="OOMKilled",
    )
    state["diagnosis"] = "Container OOMKilled after exceeding memory limit"
    state["root_cause"] = "Memory limit is too low"
    state["evidence"] = ["exit code 137"]
    state["research_query"] = "OOMKilled memory limit exceeded"

    update = research_kb(state)
    assert update["research"], "research_kb returned no results"
    assert update["research"][0].source == "kb"
    print("research_kb ->", update["research"][0].title)
    print("audit       ->", update["audit"][0].detail)
    print("[ok] Day 5 MediConnect pgvector retrieval works.")

if __name__ == "__main__":
    main()
