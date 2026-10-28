from __future__ import annotations

import sys
import time

from sqlalchemy import select

from app.approval_service import resume_incident
from app.catalog import load_catalog
from app.safety.validate import build_command
from db.models import Incident
from db.session import SessionLocal
from worker.graph_runner import get_graph

_catalog = load_catalog()

def _latest_pending() -> str | None:
    with SessionLocal() as session:
        incident = session.execute(
            select(Incident)
            .where(Incident.status == "awaiting_approval")
            .order_by(Incident.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return incident.thread_id if incident else None

def _wait_for_pending(timeout_seconds: int = 180) -> str | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        thread_id = _latest_pending()
        if thread_id:
            return thread_id
        time.sleep(2)
    return None

def _show_solution(thread_id: str):
    graph = get_graph()
    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    if snapshot.next != ("approval",):
        print(f"No pending approval for {thread_id}.")
        return None

    values = snapshot.values
    remediation = values.get("proposed_remediation")
    spec = _catalog.get(remediation.remediation_id) if remediation else None
    params = values.get("resolved_params") or (remediation.params if remediation else {})

    print("\n" + "=" * 64)
    print("APPROVAL REQUIRED")
    print("=" * 64)
    print(f"Incident     : {thread_id}")
    print(f"Service      : {values.get('service')}")
    print(f"Diagnosis    : {values.get('diagnosis')}")
    print(f"Root cause   : {values.get('root_cause')}")
    print("")
    print("Proposed solution:")
    if remediation:
        print(f"  Action     : {remediation.remediation_id}")
        print(f"  Parameters : {params}")
        if spec:
            argv = build_command(spec, params)
            print(f"  Command    : {' '.join(argv)}")
        print(f"  Rationale  : {remediation.rationale}")
    print(
        f"  Risk       : {values.get('risk_level')} "
        f"(reversible={spec.reversible if spec else 'unknown'})"
    )
    print(f"  Sandbox    : {'passed' if values.get('validated') else 'not run'}")

    try:
        answer = input("\nDo I implement it? (yes/no): ").strip().lower()
    except EOFError:
        answer = "no"
    return graph, answer.startswith("y")

def main() -> None:
    args = sys.argv[1:]
    wait = "--wait" in args
    thread_id = next((arg for arg in args if not arg.startswith("-")), None)

    if thread_id is None:
        thread_id = _latest_pending()
    if thread_id is None and wait:
        print("Waiting for an incident to reach approval...")
        thread_id = _wait_for_pending()
    if thread_id is None:
        print("No pending approval found.")
        return

    choice = _show_solution(thread_id)
    if choice is None:
        return
    graph, approved = choice

    result = resume_incident(
        thread_id=thread_id,
        approved=approved,
        approver="demo-cli",
        graph=graph,
    )
    print(f"\nDecision: {'APPROVED' if approved else 'REJECTED'}")
    print(f"Graph status: {result.get('graph_status')}")
    if approved:
        snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
        execution = snapshot.values.get("execution_result")
        if execution:
            print(f"Execution: {execution.stdout}")

if __name__ == "__main__":
    main()
