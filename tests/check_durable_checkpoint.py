"""P2-04 check: durable checkpoints with PostgresSaver.

Phase 1 runs the graph until the approval interrupt and then exits.
Phase 2 starts a brand-new Python process that resumes the same thread.
The resume must complete exactly once.

Usage:
    python -m tests.check_durable_checkpoint              # runs both phases
    python -m tests.check_durable_checkpoint start <id>    # phase 1 only
    python -m tests.check_durable_checkpoint resume <id>   # phase 2 only
"""

from __future__ import annotations

import subprocess
import sys
import time

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from sqlalchemy import text

from app.checkpointer import make_checkpointer
from app.nodes.approval import approval, route_after_approval
from app.state import OpsFlowState, Remediation, new_incident


def build_test_graph():
    builder = StateGraph(OpsFlowState)
    builder.add_node("approval", approval)
    builder.add_edge(START, "approval")
    builder.add_conditional_edges(
        "approval", route_after_approval, {"execute": END, "reject": END}
    )
    return builder.compile(checkpointer=make_checkpointer("postgres"))


def _seed(thread_id: str) -> dict:
    state = new_incident("durable checkpoint test", thread_id)
    state["proposed_remediation"] = Remediation(
        remediation_id="increase_memory_limit",
        params={"container_name": "retriva-backend", "new_memory_limit": "2Gi"},
        rationale="test",
    )
    state["resolved_params"] = {
        "container_name": "retriva-backend",
        "new_memory_limit": "2Gi",
    }
    state["diagnosis"] = "OOM killed"
    state["root_cause"] = "memory limit too low"
    state["severity"] = "high"
    state["risk_level"] = "medium"
    state["requires_approval"] = True
    return state


def phase_start(thread_id: str) -> None:
    graph = build_test_graph()
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(_seed(thread_id), config)
    assert "__interrupt__" in result, "expected the graph to pause at approval"
    print("phase-1: paused at approval; thread =", thread_id)


def phase_resume(thread_id: str) -> None:
    graph = build_test_graph()
    config = {"configurable": {"thread_id": thread_id}}

    snapshot = graph.get_state(config)
    assert snapshot.next == ("approval",), f"expected paused at approval, got {snapshot.next}"

    result = graph.invoke(
        Command(resume={"approved": True, "approver": "durable-check"}), config
    )
    assert result.get("status") == "approved", result
    approvals = [event for event in result.get("audit", []) if event.action == "approve"]
    assert len(approvals) == 1, f"expected exactly one approval, got {len(approvals)}"
    print(
        "phase-2: resumed after restart; status =",
        result["status"],
        "; approvals =",
        len(approvals),
    )


def _purge(thread_id: str) -> None:
    from db.session import engine

    try:
        with engine.begin() as connection:
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE thread_id = :tid"), {"tid": thread_id}
                )
    except Exception:
        pass


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "start":
        phase_start(args[1])
        return
    if args and args[0] == "resume":
        phase_resume(args[1])
        return

    thread_id = f"p2-04-{int(time.time())}"
    python = sys.executable

    first = subprocess.run(
        [python, "-m", "tests.check_durable_checkpoint", "start", thread_id],
        capture_output=True,
        text=True,
    )
    print(first.stdout.strip())
    if first.returncode != 0:
        print(first.stderr)
        raise SystemExit("phase start failed")

    second = subprocess.run(
        [python, "-m", "tests.check_durable_checkpoint", "resume", thread_id],
        capture_output=True,
        text=True,
    )
    print(second.stdout.strip())
    if second.returncode != 0:
        print(second.stderr)
        raise SystemExit("phase resume failed")

    _purge(thread_id)
    print("[ok] P2-04 -- durable checkpoints survive a process restart (resume exactly once).")


if __name__ == "__main__":
    main()
