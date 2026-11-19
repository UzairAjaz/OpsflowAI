from __future__ import annotations

import argparse
import time

from app.config import settings
from app.verification.service import verify_pending
from observability.logging import get_logger

log = get_logger(stage="verification.worker")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify merged OpsFlow PRs")
    parser.add_argument("--once", action="store_true", help="Run one verification pass")
    args = parser.parse_args()

    while True:
        results = verify_pending()
        for result in results:
            print(result)
        if args.once:
            return
        time.sleep(settings.verification_poll_interval_seconds)


if __name__ == "__main__":
    main()
