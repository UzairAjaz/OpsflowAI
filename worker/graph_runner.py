from __future__ import annotations

from app.checkpointer import make_checkpointer
from app.graph import build_graph
from app.state import new_incident

_GRAPH = None

def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph(make_checkpointer("postgres"))
    return _GRAPH

def run_incident(
    *,
    thread_id: str,
    error_log: str,
    tenant_id: str = "default",
    service: str = "",
    error_class: str = "",
    graph=None,
) -> dict:
    compiled = graph if graph is not None else get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    return compiled.invoke(
        new_incident(
            error_log,
            thread_id,
            tenant_id=tenant_id,
            service=service,
            error_class=error_class,
        ),
        config,
    )
