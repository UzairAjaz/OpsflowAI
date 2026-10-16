"""history_search tool: find the last successful fix for a recurring signature.

Complements kb_search by surfacing operational memory: what fixed this tenant's
same service + error class before, and how reliably.
"""

from __future__ import annotations

from langchain_core.tools import tool

from db.session import SessionLocal
from integrations.history import find_prior_fix


@tool(
    "history_search",
    description=(
        "Look up the last successful remediation for the same tenant, service, and "
        "error_class within the last N days. Returns an empty object when there is no "
        "prior successful fix."
    ),
)
def history_search(
    tenant_id: str, service: str, error_class: str, days: int = 30
) -> dict:
    with SessionLocal() as session:
        fix = find_prior_fix(
            session,
            tenant_id=tenant_id,
            service=service,
            error_class=error_class,
            days=days,
        )
    return fix.model_dump(mode="json") if fix else {}
