from __future__ import annotations

import json
from pathlib import Path

from app.catalog import load_catalog

DATASET = Path(__file__).resolve().parent / "dataset.jsonl"

KEYWORD_MAP: dict[str, str] = {
    "oom": "increase_memory_limit",
    "out of memory": "increase_memory_limit",
    "137": "increase_memory_limit",
    "memory limit": "increase_memory_limit",
    "high memory": "increase_memory_limit",
    "no space": "inspect_disk",
    "disk": "inspect_disk",
    "connection refused": "restart_container",
    "crash": "restart_container",
    "exited": "restart_container",
}

def stub_propose(case: dict) -> str | None:
    text = f"{case.get('error_class', '')} {case.get('error_log', '')}".lower()
    for keyword, remediation_id in KEYWORD_MAP.items():
        if keyword in text:
            return remediation_id
    return None

def run(path: Path | None = None, verbose: bool = False) -> dict:
    catalog = load_catalog()
    dataset = path or DATASET
    cases = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    total = len(cases)
    correct = 0
    false_safe = 0
    results = []

    for case in cases:
        proposed = stub_propose(case)
        expected = case["expected_remediation_id"]
        is_correct = proposed == expected
        correct += int(is_correct)

        expected_spec = catalog.get(expected)
        proposed_spec = catalog.get(proposed) if proposed else None
        is_false_safe = bool(
            proposed_spec
            and expected_spec
            and proposed_spec.risk == "safe"
            and expected_spec.risk != "safe"
        )
        false_safe += int(is_false_safe)

        results.append(
            {
                "error_class": case.get("error_class"),
                "expected": expected,
                "proposed": proposed,
                "correct": is_correct,
                "false_safe": is_false_safe,
            }
        )
        if verbose:
            status = "OK" if is_correct else "MISS"
            print(f"[{status}] expected={expected:<22} proposed={proposed}")

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3) if total else 0.0,
        "false_safe": false_safe,
        "false_safe_rate": round(false_safe / total, 3) if total else 0.0,
        "results": results,
    }

def main() -> None:
    outcome = run(verbose=True)
    print(
        f"\naccuracy={outcome['accuracy']} false_safe_rate={outcome['false_safe_rate']} "
        f"({outcome['correct']}/{outcome['total']})"
    )
    if outcome["false_safe_rate"] > 0:
        raise SystemExit("false-safe proposals detected")
    print("[ok] eval harness complete")

if __name__ == "__main__":
    main()
