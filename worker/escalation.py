from __future__ import annotations

from integrations.escalation import process_escalations
from observability.logging import configure_logging, get_logger

def main() -> None:
    configure_logging()
    escalated = process_escalations()
    get_logger(stage="worker").info(f"escalation run complete; escalated={len(escalated)}")

if __name__ == "__main__":
    main()
