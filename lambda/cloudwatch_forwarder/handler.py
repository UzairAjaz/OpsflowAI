"""CloudWatch Logs subscription-filter forwarder.

Decodes the gzip/base64 awslogs payload, filters real application errors, and
enqueues one compact JSON message per error to the OpsFlow alerts SQS queue.
No mock or synthetic events are generated here.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

SQS = boto3.client("sqs")
QUEUE_URL = os.environ["ALERT_QUEUE_URL"]
DEFAULT_TENANT_ID = os.environ.get("DEFAULT_TENANT_ID", "default")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "unknown")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "")
SERVICE_LOG_GROUP_MAP = json.loads(os.environ.get("SERVICE_LOG_GROUP_MAP") or "{}")

_ERROR_LEVELS = {"ERROR", "CRITICAL", "FATAL", "EXCEPTION"}
_STACK_LOCATION = re.compile(r'File "([^"]+)", line (\d+)')
_MAX_BODY_BYTES = 240_000
_MAX_STACK_CHARS = 32_000
_MAX_MESSAGE_CHARS = 4_000


def decode_cloudwatch_payload(event: dict[str, Any]) -> dict[str, Any]:
    encoded = event["awslogs"]["data"]
    compressed = base64.b64decode(encoded)
    return json.loads(gzip.decompress(compressed))


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def should_forward(record: dict[str, Any]) -> bool:
    level = str(record.get("level", "")).upper()
    status_code = _as_int(record.get("status_code"))
    message = str(record.get("message", ""))
    path = str(record.get("path", ""))

    if path in {"/health", "/healthz", "/readyz"} and status_code < 500:
        return False
    if level in _ERROR_LEVELS:
        return True
    return status_code >= 500


def _stack_location(record: dict[str, Any]) -> tuple[str, int]:
    file_path = str(record.get("file") or record.get("file_path") or "")
    line_number = _as_int(record.get("line") or record.get("line_number"))
    if file_path:
        return file_path, line_number

    stack = str(record.get("stack_trace") or record.get("traceback") or "")
    match = _STACK_LOCATION.search(stack)
    if match:
        return match.group(1), int(match.group(2))
    return "", 0


def _service_name(log_group: str) -> str:
    if SERVICE_NAME:
        return SERVICE_NAME
    if log_group in SERVICE_LOG_GROUP_MAP:
        return str(SERVICE_LOG_GROUP_MAP[log_group])
    return log_group.rsplit("/", 1)[-1]


def build_alert_message(
    record: dict[str, Any],
    payload: dict[str, Any],
    log_event: dict[str, Any],
    service: str,
) -> dict[str, Any]:
    file_path, line_number = _stack_location(record)
    error_class = str(
        record.get("error_class")
        or record.get("exception_type")
        or record.get("error")
        or ""
    )
    level = str(record.get("level", "ERROR")).upper()
    message = str(record.get("message", ""))[:_MAX_MESSAGE_CHARS]
    stack_trace = str(
        record.get("stack_trace") or record.get("traceback") or ""
    )[:_MAX_STACK_CHARS]
    commit_sha = str(
        record.get("commit_sha")
        or record.get("git_commit_sha")
        or record.get("revision")
        or ""
    ).strip()
    tenant_id = str(record.get("tenant_id") or DEFAULT_TENANT_ID)
    trace_id = str(
        record.get("trace_id")
        or record.get("request_id")
        or record.get("aws_request_id")
        or ""
    )
    timestamp_ms = _as_int(log_event.get("timestamp"))
    occurred_at = (
        datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
        if timestamp_ms
        else datetime.now(timezone.utc).isoformat()
    )
    fingerprint = f"{service}|{error_class}|{file_path}|{line_number}"
    dedupe_key = hashlib.sha256(
        json.dumps(
            {
                "service": service,
                "commit_sha": commit_sha,
                "error_class": error_class,
                "file": file_path,
                "line": line_number,
                "message": message,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    return {
        "schema_version": "1.0",
        "source": "cloudwatch",
        "tenant_id": tenant_id,
        "service": service,
        "environment": ENVIRONMENT,
        "log_group": payload.get("logGroup", ""),
        "log_stream": payload.get("logStream", ""),
        "event_id": str(log_event.get("id") or ""),
        "timestamp": occurred_at,
        "commit_sha": commit_sha,
        "level": level,
        "status_code": _as_int(record.get("status_code")),
        "error_class": error_class,
        "message": message,
        "stack_trace": stack_trace,
        "file": file_path,
        "line": line_number,
        "trace_id": trace_id,
        "fingerprint": fingerprint,
        "dedupe_key": dedupe_key,
        "analysis_only": not bool(commit_sha),
    }


def _message_attributes(message: dict[str, Any]) -> dict[str, dict[str, str]]:
    attributes = {
        "schema_version": str(message["schema_version"]),
        "tenant_id": str(message["tenant_id"]),
        "service": str(message["service"]),
        "severity": str(message["level"]),
    }
    if message["commit_sha"]:
        attributes["commit_sha"] = str(message["commit_sha"])
    return {
        key: {"DataType": "String", "StringValue": value[:256]}
        for key, value in attributes.items()
    }


def _send_batch(messages: list[dict[str, Any]]) -> int:
    sent = 0
    for start in range(0, len(messages), 10):
        batch = messages[start : start + 10]
        entries = [
            {
                "Id": str(index),
                "MessageBody": json.dumps(message),
                "MessageAttributes": _message_attributes(message),
            }
            for index, message in enumerate(batch)
        ]
        try:
            response = SQS.send_message_batch(QueueUrl=QUEUE_URL, Entries=entries)
        except ClientError as exc:
            print(f"sqs batch failed: {exc}")
            continue
        for failure in response.get("Failed", []):
            print(f"sqs message failed: {failure}")
        sent += len(response.get("Successful", []))
    return sent


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    payload = decode_cloudwatch_payload(event)
    if payload.get("messageType") == "CONTROL_MESSAGE":
        return {"forwarded": 0, "reason": "control_message"}

    log_group = str(payload.get("logGroup", ""))
    service = _service_name(log_group)
    messages: list[dict[str, Any]] = []

    for log_event in payload.get("logEvents", []):
        message_text = log_event.get("message", "")
        try:
            record = json.loads(message_text)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or not should_forward(record):
            continue

        message = build_alert_message(record, payload, log_event, service)
        body_size = len(json.dumps(message).encode("utf-8"))
        if body_size > _MAX_BODY_BYTES:
            message["stack_trace"] = message["stack_trace"][:8_000]
            message["message"] = message["message"][:1_000]
        messages.append(message)

    forwarded = _send_batch(messages)
    print(json.dumps({"forwarded": forwarded, "service": service, "log_group": log_group}))
    return {"forwarded": forwarded}
