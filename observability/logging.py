from __future__ import annotations

import json
import sys
from typing import Any

from loguru import logger

def _json_sink(message: Any) -> None:

    record = message.record
    payload: dict[str, Any] = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "message": record["message"],
        "logger": record["name"],
    }
    payload.update(record["extra"])
    if record["exception"] is not None:
        payload["exception"] = str(record["exception"])
    sys.stdout.write(json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()

def configure_logging(level: str = "INFO") -> None:

    logger.remove()
    logger.add(_json_sink, level=level, backtrace=False, diagnose=False)

def get_logger(**fields: Any):

    return logger.bind(**fields)

__all__ = ["configure_logging", "get_logger", "logger"]
