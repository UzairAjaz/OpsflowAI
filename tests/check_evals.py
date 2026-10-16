"""P2-36 check: eval harness (accuracy + false-safe rate)."""

from __future__ import annotations

from evals.run_eval import run


def main() -> None:
    outcome = run()
    assert outcome["false_safe_rate"] == 0.0, outcome
    assert outcome["accuracy"] >= 0.9, outcome
    print(
        f"[ok] P2-36 -- eval accuracy={outcome['accuracy']} "
        f"false_safe_rate={outcome['false_safe_rate']} "
        f"({outcome['correct']}/{outcome['total']})"
    )


if __name__ == "__main__":
    main()
