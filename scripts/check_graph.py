from __future__ import annotations

from app.graph import graph
from app.state import new_incident

def main() -> None:
    thread_id = "inc-demo-checkpoint"
    config = {"configurable": {"thread_id": thread_id}}

    print("=== Run 1 ===")
    r1 = graph.invoke(
        new_incident("Error: disk usage on /dev/sda1 is 100% (no space left)", thread_id),
        config,
    )
    print("diagnosis :", r1.get("diagnosis"))
    print("severity  :", r1.get("severity"))
    print("audit len :", len(r1["audit"]))

    print("\n=== Run 2 (same thread_id, naya log) ===")
    r2 = graph.invoke({"error_log": "FATAL: sorry, too many clients already (postgres)"}, config)
    print("diagnosis :", r2.get("diagnosis"))
    print("severity  :", r2.get("severity"))
    print("audit len :", len(r2["audit"]), "<- 2 hua? matlab purana audit yaad raha")

    for i, ev in enumerate(r2["audit"]):
        print(f"  audit[{i}] {ev.actor}/{ev.action}: {ev.detail}")

    snapshot = graph.get_state(config)
    print("\ncheckpoint next node:", snapshot.next or "(done)")

    assert len(r2["audit"]) == 2, "Checkpointer ne purana audit yaad nahi rakha!"
    print("\n[ok] Step 4 -- graph + checkpointer working.")

if __name__ == "__main__":
    main()
