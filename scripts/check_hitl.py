from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.checkpointer import make_checkpointer
from app.nodes.approval import approval, route_after_approval
from app.state import OpsFlowState, Remediation, new_incident

def build_test_graph():
    builder = StateGraph(OpsFlowState)
    builder.add_node("approval", approval)
    builder.add_edge(START, "approval")
    builder.add_conditional_edges("approval", route_after_approval, {"execute": END, "reject": END})
    return builder.compile(checkpointer=make_checkpointer())

def seed(thread_id: str) -> dict:
    st = new_incident("test", thread_id)
    st["proposed_remediation"] = Remediation(
        remediation_id="increase_memory_limit",
        params={"container_name": "retriva-backend", "new_memory_limit": "2Gi"},
        rationale="test",
    )
    st["resolved_params"] = {"container_name": "retriva-backend", "new_memory_limit": "2Gi"}
    st["diagnosis"] = "OOM killed"
    st["root_cause"] = "memory limit too low"
    st["severity"] = "high"
    st["risk_level"] = "medium"
    st["requires_approval"] = True
    return st

def main() -> None:
    g = build_test_graph()

    print("=== case: APPROVE ===")
    cfg = {"configurable": {"thread_id": "hitl-approve"}}
    r = g.invoke(seed("hitl-approve"), cfg)
    assert "__interrupt__" in r, "graph pause nahi hua!"
    payload = r["__interrupt__"][0].value
    print("paused. human ko mila payload:")
    print("  remediation:", payload["remediation_id"], payload["params"])
    print("  risk:", payload["risk_level"], "reversible:", payload["reversible"])

    snap = g.get_state(cfg)
    print("  checkpoint next:", snap.next)

    r2 = g.invoke(Command(resume={"approved": True, "approver": "tester"}), cfg)
    print("resumed ->", r2["human_approval"], r2["status"], "by", r2["approver"])
    assert r2["human_approval"] is True and r2["status"] == "approved"

    print("\n=== case: REJECT ===")
    cfg2 = {"configurable": {"thread_id": "hitl-reject"}}
    r = g.invoke(seed("hitl-reject"), cfg2)
    assert "__interrupt__" in r
    r2 = g.invoke(Command(resume={"approved": False, "approver": "tester"}), cfg2)
    print("resumed ->", r2["human_approval"], r2["status"])
    assert r2["human_approval"] is False and r2["status"] == "rejected"

    print("\n[ok] Step 10 -- interrupt() + Command(resume=) working.")

if __name__ == "__main__":
    main()
