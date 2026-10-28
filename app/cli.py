from __future__ import annotations

import sys

from langgraph.types import Command

from app.graph import graph
from app.state import new_incident

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

def _ask_approval(payload: dict) -> dict:

    print("\n" + "=" * 62)
    print("⚠️  APPROVAL REQUIRED")
    print("=" * 62)
    print(f"  Diagnosis  : {payload.get('diagnosis')}")
    print(f"  Root cause : {payload.get('root_cause')}")
    print(f"  Severity   : {payload.get('severity')}")
    print("")
    print("  Proposed solution:")
    print(f"    Action     : {payload.get('remediation_id')}")
    print(f"    Parameters : {payload.get('params')}")
    print(f"    Rationale  : {payload.get('rationale')}")
    print(
        f"    Risk       : {payload.get('risk_level')} "
        f"(reversible={payload.get('reversible')})"
    )
    print(f"    Sandbox    : {'passed' if payload.get('validated') else 'not run'}")
    print(f"    Critic     : {payload.get('critic_score')}")

    try:
        ans = input("\nDo I implement it? (yes/no): ").strip().lower()
    except EOFError:
        ans = "no"
    return {"approved": ans.startswith("y"), "approver": "cli-user"}

def run(error_log: str, thread_id: str | None = None) -> dict:

    state = new_incident(error_log, thread_id=thread_id)

    config = {"configurable": {"thread_id": state["thread_id"]}}
    print(f"\n🤖 [Intake]    thread_id = {state['thread_id']}")

    result = graph.invoke(state, config)

    while "__interrupt__" in result:
        interrupt_obj = result["__interrupt__"][0]
        decision = _ask_approval(interrupt_obj.value)

        result = graph.invoke(Command(resume=decision), config)

    redactions = result.get("redactions") or {}
    if redactions:
        print(f"[Intake]    redacted: {redactions}")
    else:
        print("[Intake]    no secrets/PII found")

    print(f"[Analyzer]  Diagnosis : {result.get('diagnosis')}")
    print(f"[Analyzer]  Root cause: {result.get('root_cause')}")
    print(f"[Analyzer]  Severity  : {result.get('severity')}")
    for i, ev in enumerate(result.get("evidence", [])):
        print(f"   evidence[{i}]        : {ev}")

    research_results = result.get("research", [])
    print(f"\n[Researcher] {len(research_results)} source(s) mile:")
    for i, r in enumerate(research_results, start=1):
        print(f"   [{i}] {r.title}\n       {r.url}")

    rem = result.get("proposed_remediation")
    if rem:
        print(f"\n [Proposal] {rem.remediation_id}({rem.params})")
        print(f"    rationale: {rem.rationale}")

    print(
        f"\n [Critic]   score={result.get('critic_score')} "
        f"loops={result.get('loop_count')} valid={result.get('proposal_valid')}"
    )
    print(f"    critique: {result.get('critique')}")

    print(
        f"\n[Risk]     level={result.get('risk_level')} "
        f"requires_approval={result.get('requires_approval')}"
    )

    if result.get("human_approval") is not None:
        verdict = "APPROVED" if result["human_approval"] else "REJECTED"
        print(f"[Human]     {verdict} by {result.get('approver')}")

    ex = result.get("execution_result")
    if ex:
        print(f"\n[Executor]  {ex.remediation_id} (dry_run={ex.dry_run}, exit={ex.exit_code})")
        print(f"    cmd: {' '.join(ex.command)}")
        print(f"    {ex.stdout}")

    if result.get("status") == "rejected":
        print("\n❌[Approval] Rejected -> No execution occur.")
    if result.get("status") == "escalated":
        print("\n⚠️  [Escalate] MAX_LOOPS tak confidence nahi mila -> manual review.")

    print("\n📜 [Audit trail]")
    for i, ev in enumerate(result.get("audit", []), start=1):
        print(f"   {i:>2}. {ev.actor}/{ev.action}: {ev.detail}")

    snapshot = graph.get_state(config)
    print(f"\n💾 [Checkpoint] saved keys: {sorted(snapshot.values.keys())}")
    print(f"💾 [Checkpoint] next node : {snapshot.next or '(done)'}")

    return result

def main() -> None:
    if len(sys.argv) > 1:
        error_log = " ".join(sys.argv[1:])
    else:
        print("no argument given:")
        lines: list[str] = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if not line.strip():
                break
            lines.append(line)
        error_log = "\n".join(lines)

    if not error_log.strip():
        print("Empty error log -- kuch diya hi nahi.")
        raise SystemExit(1)

    run(error_log)

if __name__ == "__main__":
    main()
