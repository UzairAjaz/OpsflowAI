from __future__ import annotations

from app.nodes.researcher import research
from app.state import new_incident
from app.tools.web_search import web_search

def main() -> None:

    print("=== 1) web_search tool ===")
    raw = web_search.invoke({"query": "docker container exit 137 OOM killed", "max_results": 3})
    print(f"type={type(raw).__name__} count={len(raw)}")
    for i, r in enumerate(raw, 1):
        print(f"  [{i}] {r['title']}")
        print(f"      {r['url']}")

    print("\n=== 2) researcher node ===")
    state = new_incident("Error: container exited 137")
    state["root_cause"] = "Container exceeded its memory limit and was OOM killed"
    update = research(state)
    print(f"research appended : {len(update['research'])}")
    print(f"audit detail      : {update['audit'][0].detail}")
    assert isinstance(update["research"], list)
    print("\n[ok] Step 5 -- researcher working.")

if __name__ == "__main__":
    main()
