from __future__ import annotations

import uuid

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from sqlalchemy import delete, select

from app.checkpointer import make_checkpointer
from app.nodes.approval import approval, route_after_approval
from app.nodes.executor import execute
from app.nodes.risk import classify, route_after_risk
from app.nodes.sandbox import route_after_sandbox, run_sandbox
from app.state import AuditEvent, OpsFlowState, Remediation, new_incident
from db.models import ExecutionLog
from db.session import SessionLocal
from integrations.sandbox import FakeSandbox, set_sandbox

def _seed(state: OpsFlowState) -> dict:
    return {
        "diagnosis": "OOM killed",
        "root_cause": "memory limit too low",
        "severity": "high",
        "evidence": ["exit code 137"],
        "proposed_remediation": Remediation(
            remediation_id="increase_memory_limit",
            params={"container_name": "checkout-api", "new_memory_limit": "2Gi"},
            rationale="test",
        ),
        "critic_score": 85,
        "audit": [AuditEvent(actor="agent", action="analyze", detail="seed")],
    }

def build_graph():
    builder = StateGraph(OpsFlowState)
    builder.add_node("seed", _seed)
    builder.add_node("risk", classify)
    builder.add_node("sandbox", run_sandbox)
    builder.add_node("approval", approval)
    builder.add_node("executor", execute)
    builder.add_edge(START, "seed")
    builder.add_edge("seed", "risk")
    builder.add_conditional_edges(
        "risk",
        route_after_risk,
        {"execute": "sandbox", "await_approval": "sandbox", "reject": END},
    )
    builder.add_conditional_edges(
        "sandbox",
        route_after_sandbox,
        {"approval": "approval", "execute": "executor", "retry": END, "escalate": END},
    )
    builder.add_conditional_edges(
        "approval",
        route_after_approval,
        {"execute": "executor", "reject": END},
    )
    builder.add_edge("executor", END)
    return builder.compile(checkpointer=make_checkpointer("memory"))

def main() -> None:
    set_sandbox(FakeSandbox(default_exit=0))
    thread_id = f"week3-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    with SessionLocal() as session:
        session.execute(
            delete(ExecutionLog).where(ExecutionLog.remediation_id == "increase_memory_limit")
        )
        session.commit()

    try:
        state = new_incident(
            "container out of memory",
            thread_id=thread_id,
            tenant_id="acme",
            service="checkout-api",
            error_class="OOMKilled",
        )
        graph = build_graph()

        paused = graph.invoke(state, config)
        assert "__interrupt__" in paused, "expected approval interrupt after sandbox"
        assert paused["validated"] is True
        assert paused["rollback_plan"] == ["docker", "update", "--memory", "512Mi", "checkout-api"]
        print("sandbox   -> validated; rollback plan:", paused["rollback_plan"])

        payload = paused["__interrupt__"][0].value
        assert payload["validated"] is True
        assert payload["sandbox"]["checks"] is not None
        print("approval  -> paused; sandbox attached to approval payload")

        result = graph.invoke(Command(resume={"approved": True, "approver": "week3"}), config)
        assert result["status"] == "completed", result["status"]
        execution = result["execution_result"]
        assert execution.remediation_id == "increase_memory_limit"
        print("executor  -> production apply:", " ".join(execution.command))

        with SessionLocal() as session:
            logs = (
                session.execute(
                    select(ExecutionLog).where(
                        ExecutionLog.remediation_id == "increase_memory_limit"
                    )
                )
                .scalars()
                .all()
            )
        assert logs, "execution audit trail missing"
        print("audit     ->", len(logs), "execution log(s)")

        print("")
        print("[ok] P2-21 -- Week 3 exit criteria pass:")
        print("     proposal -> risk -> sandbox(validate+rollback) -> approval -> executor")
    finally:
        set_sandbox(None)
        with SessionLocal() as session:
            session.execute(
                delete(ExecutionLog).where(
                    ExecutionLog.remediation_id == "increase_memory_limit"
                )
            )
            session.commit()

if __name__ == "__main__":
    main()
