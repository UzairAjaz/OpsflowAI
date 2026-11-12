from __future__ import annotations

from app.config import settings
from app.nodes.scoring import route_after_scoring

def main() -> None:
    cases: list[tuple[dict, str]] = [
        ({"status": "escalated", "confidence": 99, "loop_count": 3}, "escalate"),
        ({"status": "pending", "confidence": 90, "loop_count": 1}, "accept"),
        ({"status": "pending", "confidence": 40, "loop_count": 1}, "refine"),
    ]

    original_threshold = settings.confidence_threshold
    settings.confidence_threshold = 70
    try:
        print(f"threshold = {settings.confidence_threshold} (pinned for test)\n")
        for state, expected in cases:
            got = route_after_scoring(state)
            mark = "ok " if got == expected else "FAIL"
            print(
                f"[{mark}] confidence={state['confidence']:>3} loops={state['loop_count']} "
                f"status={state['status']:<9} -> {got:<8} (expected {expected})"
            )
            assert got == expected, f"router wrong: {got} != {expected}"
    finally:
        settings.confidence_threshold = original_threshold

    print("\n[ok] P2-13 -- router routes on rubric confidence.")

if __name__ == "__main__":
    main()
