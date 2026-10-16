"""Step 6 check: routing after rubric scoring (conditional edge).

Chalao:
    python -m scripts.check_router

`route_after_scoring` is a pure function (state -> next node name), so it can be
tested without the LLM. Routing is based on the rubric confidence, and the loop
cap is enforced by the scoring node (status = escalated).
"""

from __future__ import annotations

from app.config import settings
from app.nodes.scoring import route_after_scoring


def main() -> None:
    cases: list[tuple[dict, str]] = [
        ({"status": "escalated", "confidence": 99, "loop_count": 3}, "escalate"),
        ({"status": "pending", "confidence": 90, "loop_count": 1}, "accept"),
        ({"status": "pending", "confidence": 40, "loop_count": 1}, "refine"),
    ]

    print(f"threshold = {settings.confidence_threshold} (config se)\n")
    for state, expected in cases:
        got = route_after_scoring(state)
        mark = "ok " if got == expected else "FAIL"
        print(
            f"[{mark}] confidence={state['confidence']:>3} loops={state['loop_count']} "
            f"status={state['status']:<9} -> {got:<8} (expected {expected})"
        )
        assert got == expected, f"router wrong: {got} != {expected}"

    print("\n[ok] P2-13 -- router routes on rubric confidence.")


if __name__ == "__main__":
    main()
