from __future__ import annotations

import sys

from rq import SimpleWorker

from app.config import settings
from observability.logging import configure_logging
from worker.queue import get_connection, get_queue

def main() -> None:
    configure_logging(settings.log_level)
    burst = "--burst" in sys.argv[1:]
    worker = SimpleWorker([get_queue()], connection=get_connection())
    worker.work(burst=burst)

if __name__ == "__main__":
    main()
