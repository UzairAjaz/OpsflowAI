from __future__ import annotations

import json
from typing import get_type_hints

from pydantic import ValidationError

from app.state import (
    AuditEvent,
    Diagnosis,
    OpsFlowState,
    Remediation,
    new_incident,
)

def main() -> None:

    print("=== 1) Valid Diagnosis ===")
    d = Diagnosis(
        diagnosis="Container killed by OOM",
        root_cause="Container exceeded its memory limit",
        severity="high",
        evidence=["exit code 137", "OOMKilled in docker inspect"],
    )
    print(d.model_dump_json(indent=2))

    print("\n=== 2) Invalid severity -> ValidationError ===")
    try:
        Diagnosis(diagnosis="x", root_cause="y", severity="catastrophic")
    except ValidationError as e:

        print("Blocked as expected:", e.errors()[0]["msg"])

    print("\n=== 3) Diagnosis JSON Schema keys ===")
    schema = Diagnosis.model_json_schema()
    print("title      :", schema["title"])
    print("properties :", list(schema["properties"].keys()))
    print("severity   :", schema["properties"]["severity"])

    print("\n=== 4) State reducer metadata ===")
    hints = get_type_hints(OpsFlowState, include_extras=True)
    for key in ("research", "audit", "messages", "confidence"):
        print(f"{key:10s} -> {hints[key]}")

    print("\n=== 5) new_incident() ===")
    st = new_incident("Error: docker container exited 137")
    print("thread_id:", st["thread_id"])
    print("status   :", st["status"])
    print("audit    :", st["audit"])

    print("\n=== 6) AuditEvent auto timestamp ===")
    print(AuditEvent(actor="agent", action="analyze", detail="OOM detected").model_dump())

    print("\n=== 7) Remediation (what the LLM will return later) ===")
    print(
        Remediation(
            remediation_id="increase_memory_limit",
            params={"service_name": "retriva-backend", "limit": "1g"},
            rationale="Matches OOM runbook; reversible.",
        ).model_dump_json(indent=2)
    )

if __name__ == "__main__":
    main()
