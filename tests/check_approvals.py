"""P2-22 check: approval service + resume endpoint.

- signed approval tokens (email links) verify and expire,
- a paused incident resumes exactly once via the approval service,
- the HTTP approval endpoint enforces auth and reports no-pending.
"""

from __future__ import annotations

import time
import uuid

from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text

from api.main import app
from app.approval_service import is_pending, resume_incident
from app.approval_tokens import sign_approval_token, verify_approval_token
from app.checkpointer import make_checkpointer
from app.config import settings
from app.nodes.approval import approval, route_after_approval
from app.state import OpsFlowState, Remediation, new_incident
from db.session import engine


def _min_graph():
    builder = StateGraph(OpsFlowState)
    builder.add_node("approval", approval)
    builder.add_edge(START, "approval")
    builder.add_conditional_edges("approval", route_after_approval, {"execute": END, "reject": END})
    return builder.compile(checkpointer=make_checkpointer("postgres"))


def _paused_thread(graph, thread_id: str):
    state = new_incident(
        "oom", thread_id=thread_id, tenant_id="acme", service="checkout-api", error_class="OOMKilled"
    )
    state["proposed_remediation"] = Remediation(
        remediation_id="increase_memory_limit",
        params={"container_name": "checkout-api", "new_memory_limit": "2Gi"},
        rationale="t",
    )
    state["resolved_params"] = {"container_name": "checkout-api", "new_memory_limit": "2Gi"}
    state["severity"] = "high"
    state["risk_level"] = "medium"
    state["requires_approval"] = True
    result = graph.invoke(state, {"configurable": {"thread_id": thread_id}})
    assert "__interrupt__" in result


def _purge(thread_id: str) -> None:
    with engine.begin() as connection:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            connection.execute(text(f"DELETE FROM {table} WHERE thread_id = :tid"), {"tid": thread_id})


def main() -> None:
    token = sign_approval_token("inc-1", "approve")
    payload = verify_approval_token(token)
    assert payload and payload["t"] == "inc-1" and payload["d"] == "approve"
    expired = sign_approval_token("inc-1", "approve", ttl_minutes=-1)
    assert verify_approval_token(expired) is None
    print("token     -> sign/verify/expire ok")

    thread_id = f"appr-{uuid.uuid4().hex[:8]}"
    graph = _min_graph()
    try:
        _paused_thread(graph, thread_id)
        assert is_pending(thread_id=thread_id, graph=graph) is True

        result = resume_incident(thread_id=thread_id, approved=True, approver="api", graph=graph)
        assert result["status"] == "resumed" and result["graph_status"] == "approved"
        print("resume    ->", result["graph_status"])

        again = resume_incident(thread_id=thread_id, approved=True, approver="api", graph=graph)
        assert again["status"] == "no_pending"
        print("idempotent-> second resume returns", again["status"])
    finally:
        _purge(thread_id)

    with TestClient(app) as client:
        unknown = client.post("/api/v1/approvals/does-not-exist", json={"approved": True})
        assert unknown.status_code == 409, unknown.text
        print("endpoint  -> unknown thread:", unknown.status_code)

        original = settings.tenant_api_keys
        settings.tenant_api_keys = "acme:secret-key"
        try:
            unauthorized = client.post("/api/v1/approvals/x", json={"approved": True})
            assert unauthorized.status_code == 401, unauthorized.text
            print("auth      -> missing key:", unauthorized.status_code)
        finally:
            settings.tenant_api_keys = original

    print("[ok] P2-22 -- approval service and resume endpoint working.")


if __name__ == "__main__":
    main()
