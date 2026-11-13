# Phase 1, Task 1 — Structured JSON Logging and `/debug/boom`

Target repo: `UzairAjaz/mediconnnect`  
Target service: `mediconnect-backend`  
Environment: staging  
Goal: emit real CloudWatch JSON logs containing the deployed `commit_sha`, then
produce one safe, real error that the OpsFlow pipeline can ingest.

## 1. Files to add in the target repo

```text
observability/__init__.py
observability/logging_config.py
observability/request_context.py
```

Modify the FastAPI entrypoint (usually `app/main.py`):

```text
configure_logging() at import/startup
add RequestContextMiddleware
add a global exception handler
add GET /debug/boom behind ENABLE_TEST_BUG
```

## 2. Environment variables

Add to the target service `.env.example` and ECS task definition:

```env
SERVICE_NAME=mediconnect-backend
ENVIRONMENT=staging
GIT_COMMIT_SHA=replace-at-deploy-time
ENABLE_TEST_BUG=false
LOG_LEVEL=INFO
```

`GIT_COMMIT_SHA` must be set by the deployment workflow:

```yaml
GIT_COMMIT_SHA=${{ github.sha }}
```

Use `ENABLE_TEST_BUG=true` only in the staging task definition.

## 3. Log schema

Every application log line must be one JSON object:

```json
{
  "timestamp": "2026-11-13T10:15:30.123456+00:00",
  "level": "ERROR",
  "message": "intentional staging test bug",
  "logger": "app.main",
  "service": "mediconnect-backend",
  "environment": "staging",
  "commit_sha": "abc123...",
  "trace_id": "req-...",
  "request_id": "req-...",
  "error_class": "KeyError",
  "file": "app/main.py",
  "line": 42,
  "stack_trace": "Traceback (most recent call last): ..."
}
```

No secrets, authorization headers, cookies, or customer PII in logs.

## 4. `observability/logging_config.py`

```python
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from observability.request_context import request_id_var, trace_id_var


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "service": os.getenv("SERVICE_NAME", "unknown"),
            "environment": os.getenv("ENVIRONMENT", "unknown"),
            "commit_sha": os.getenv("GIT_COMMIT_SHA", ""),
            "trace_id": trace_id_var.get(),
            "request_id": request_id_var.get(),
            "error_class": getattr(record, "error_class", ""),
            "file": getattr(record, "file_path", ""),
            "line": getattr(record, "line_number", 0),
        }

        if record.exc_info:
            exc_type, exc_value, tb = record.exc_info
            payload["error_class"] = exc_type.__name__
            payload["stack_trace"] = self.formatException(record.exc_info)
            extracted = __import__("traceback").extract_tb(tb)
            if extracted:
                payload["file"] = extracted[-1].filename
                payload["line"] = extracted[-1].lineno

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
```

## 5. `observability/request_context.py`

```python
from __future__ import annotations

import contextvars
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        trace_id = request.headers.get("X-Trace-ID") or request_id
        request_id_var.set(request_id)
        trace_id_var.set(trace_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        return response
```

## 6. FastAPI entrypoint changes

```python
import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from observability.logging_config import configure_logging
from observability.request_context import RequestContextMiddleware

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception(request, exc: Exception):
    logger.error(
        "unhandled exception",
        exc_info=exc,
        extra={"error_class": type(exc).__name__},
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/debug/boom")
def debug_boom():
    if os.getenv("ENABLE_TEST_BUG") != "true":
        raise HTTPException(status_code=404)
    raise KeyError("intentional staging test bug")
```

Ensure the real exception handler is registered before the ASGI server starts and
that uvicorn does not add a second non-JSON handler for application logs.

## 7. Deployment changes

1. Build and push the image with the real commit SHA.
2. Update the ECS task definition:
   ```json
   {
     "name": "GIT_COMMIT_SHA",
     "value": "<github-sha>"
   }
   ```
3. Set `ENABLE_TEST_BUG=true` in staging only.
4. Confirm the ECS `awslogs` driver writes to `/ecs/mediconnect-backend`.
5. Deploy and wait for ECS service stability.

## 8. Validation

Local:

```powershell
$env:SERVICE_NAME="mediconnect-backend"
$env:ENVIRONMENT="staging"
$env:GIT_COMMIT_SHA="local-test"
$env:ENABLE_TEST_BUG="true"
uvicorn app.main:app --host 127.0.0.1 --port 8000
curl -i http://127.0.0.1:8000/debug/boom
```

The log must be one JSON line with `error_class=KeyError`, `file`, `line`,
`commit_sha`, `trace_id`, and `stack_trace`.

Staging:

```bash
curl -i "https://<staging-host>/debug/boom"
aws logs filter-log-events \
  --log-group-name /ecs/mediconnect-backend \
  --filter-pattern '{ $.level = "ERROR" }' \
  --limit 5
```

Then verify the real ingestion path:

```bash
aws sqs receive-message \
  --queue-url "$ALERTS_QUEUE_URL" \
  --max-number-of-messages 1 \
  --wait-time-seconds 20
```

The SQS body must contain the same `commit_sha`, `service`, `error_class`, file,
line, and stack trace.

## 9. Pitfalls

- **Double-encoded JSON:** attach exactly one JSON formatter to the root logger.
- **No `commit_sha`:** the pipeline must mark the alert `analysis_only`; never
  fetch code from `main` as a substitute.
- **Stack trace split across CloudWatch events:** the Lambda reassembles fields
  from the JSON record; do not split `stack_trace` across separate log calls.
- **Uvicorn access logs:** keep them separate or format them as JSON; they are
  not the application error records.
- **Secrets/PII:** redact before logging; never log headers or request bodies.
- **Test bug in production:** `ENABLE_TEST_BUG` must be false outside staging.
- **Missing subscription filter:** rerun `deploy/aws/04-lambda.sh` after the log
  group exists.
