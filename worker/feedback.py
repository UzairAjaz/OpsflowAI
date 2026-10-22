from __future__ import annotations

from integrations.feedback import process_feedback
from observability.logging import configure_logging, get_logger

def main() -> None:
    configure_logging()
    recorded = process_feedback()
    get_logger(stage="worker").info(f"feedback run complete; recorded={len(recorded)}")

if __name__ == "__main__":
    main()
