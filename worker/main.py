"""Worker entrypoint.

Runs an RQ worker for incident jobs. SimpleWorker is used because it does not
rely on fork and therefore works on Windows.

Usage:
    python -m worker.main            # long-running
    python -m worker.main --burst    # process queued jobs, then exit
"""

from __future__ import annotations

import sys

from rq import SimpleWorker

from observability.logging import configure_logging
from worker.queue import get_connection, get_queue


def main() -> None:
    configure_logging()
    burst = "--burst" in sys.argv[1:]
    worker = SimpleWorker([get_queue()], connection=get_connection())
    worker.work(burst=burst)


if __name__ == "__main__":
    main()
