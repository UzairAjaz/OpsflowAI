from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.checkpointer import make_checkpointer
from app.nodes.canary import run_canary
from app.nodes.executor import execute
from app.state import OpsFlowState, Remediation, new_incident
from integrations.canary import (
    SimulatedCanaryController,
    StaticMetricsProvider,
    set_canary_controller,
    set_metrics_provider,
)

def _seed(state: OpsFlowState) -> dict:
    return {
        "diagnosis": "OOM killed",
        "root_cause": "memory limit too low",
        "severity": "high",
        "proposed_remediation": Remediation(
            remediation_id="increase_memory_limit",
            params={"container_name": "checkout-api", "new_memory_limit": "2Gi"},
            rationale="test",
        ),
        "resolved_params": {"container_name": "checkout-api", "new_memory_limit": "2Gi"},
        "requires_approval": False,
    }

def build_graph():
    builder = StateGraph(OpsFlowState)
    builder.add_node("seed", _seed)
    builder.add_node("executor", execute)
    builder.add_node("canary", run_canary)
    builder.add_edge(START, "seed")
    builder.add_edge("seed", "executor")
    builder.add_edge("executor", "canary")
    builder.add_edge("canary", END)
    return builder.compile(checkpointer=make_checkpointer("memory"))

def main() -> None:
    graph = build_graph()
    set_canary_controller(SimulatedCanaryController())

    try:
        set_metrics_provider(StaticMetricsProvider())
        state = new_incident(
            "oom", tenant_id="acme", service="checkout-api", error_class="OOMKilled"
        )
        promoted = graph.invoke(state, {"configurable": {"thread_id": "w5-ok"}})
        assert promoted["status"] == "completed"
        assert promoted["canary_result"]["status"] == "promoted"
        assert promoted["execution_result"].remediation_id == "increase_memory_limit"
        print(
            "promote   -> applied; canary promoted through",
            [stage["percentage"] for stage in promoted["canary_stages"]],
        )

        set_metrics_provider(StaticMetricsProvider(fail_at_percentage=50))
        state = new_incident(
            "oom", tenant_id="acme", service="checkout-api", error_class="OOMKilled"
        )
        rolled = graph.invoke(state, {"configurable": {"thread_id": "w5-bad"}})
        assert rolled["status"] == "rolled_back"
        print("rollback  ->", rolled["canary_result"]["rollback_reason"])

        print("")
        print("[ok] P2-30 -- Week 5 exit criteria pass:")
        print("     executor -> canary 10->100% -> promote or auto-rollback")
    finally:
        set_canary_controller(None)
        set_metrics_provider(None)

if __name__ == "__main__":
    main()
