"""Run all OpsFlow checks and print a summary.

Usage:
    python -m tests.run_all

Runs every Phase 1, Week 1, and Week 2 check in sequence and prints a PASS/FAIL
summary. Exits non-zero if any check fails.
"""

from __future__ import annotations

import subprocess
import sys
import time

TESTS = [
    "scripts.check_state",
    "scripts.check_router",
    "scripts.check_catalog",
    "scripts.check_redact",
    "scripts.check_hitl",
    "tests.check_api_health",
    "tests.check_webhook",
    "tests.check_ingestion",
    "tests.check_ratelimit",
    "tests.check_durable_checkpoint",
    "tests.check_worker",
    "tests.check_week1",
    "tests.check_kb",
    "tests.check_history",
    "tests.check_parallel_research",
    "tests.check_confidence",
    "tests.check_history_proposal",
    "tests.check_week2",
    "tests.check_sandbox",
    "tests.check_week3",
    "tests.check_approvals",
    "tests.check_notifications",
    "tests.check_week4",
    "tests.check_canary",
    "tests.check_week5",
    "tests.check_observability",
    "tests.check_learning",
    "tests.check_evals",
    "tests.check_week6",
]


def main() -> None:
    results: list[tuple[str, bool, float]] = []

    for module in TESTS:
        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, "-m", module], capture_output=True, text=True
        )
        duration = time.perf_counter() - start
        ok = proc.returncode == 0
        results.append((module, ok, duration))
        print(f"[{'PASS' if ok else 'FAIL'}] {module} ({duration:.1f}s)")
        if not ok:
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-8:]
            for line in tail:
                print("        " + line)

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("")
    print(f"Summary: {passed}/{total} passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
