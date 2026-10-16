"""Structured JSON logging for OpsFlow AI Phase 2.

Every log line is emitted as a single JSON object with a stable set of fields
so it can be ingested by an ELK stack. Required fields:

    timestamp, level, message, logger

Additional context (for example incident_id, stage, duration_ms) is attached
with `get_logger(...)` and appears as top-level JSON fields.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from loguru import logger


def _json_sink(message: Any) -> None:
    """Write a single log record as a flat JSON object."""
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
    """Configure Loguru to emit structured JSON. Safe to call more than once."""
    logger.remove()
    logger.add(_json_sink, level=level, backtrace=False, diagnose=False)


def get_logger(**fields: Any):
    """Return a logger with structured context fields attached."""
    return logger.bind(**fields)


__all__ = ["configure_logging", "get_logger", "logger"]
