from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

class DemoState(TypedDict):
    last_only: str
    collected: Annotated[list[str], operator.add]

def node_a(state: DemoState) -> dict:
    print(f"[node_a] input last_only={state.get('last_only')!r}")
    return {"last_only": "A", "collected": ["from_A"]}

def node_b(state: DemoState) -> dict:
    print(f"[node_b] input last_only={state.get('last_only')!r}")
    return {"last_only": "B", "collected": ["from_B"]}

def main() -> None:
    builder = StateGraph(DemoState)
    builder.add_node("a", node_a)
    builder.add_node("b", node_b)
    builder.add_edge(START, "a")
    builder.add_edge("a", "b")
    builder.add_edge("b", END)
    graph = builder.compile()

    result = graph.invoke({"last_only": "(start)", "collected": []})
    print("\nfinal state:", result)
    print("\n=> last_only =", repr(result["last_only"]), "(B ne A ko overwrite kiya)")
    print("=> collected =", result["collected"], "(dono append hue)")

if __name__ == "__main__":
    main()
