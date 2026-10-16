"""OpsFlow AI HTTP API (Phase 2 skeleton).

Exposes liveness and readiness endpoints plus request logging. Alert webhooks,
approval callbacks, and metrics are added in later steps.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from api.routes.approvals import router as approvals_router
from api.routes.metrics import router as metrics_router
from api.routes.webhooks import router as webhooks_router
from app.config import settings
from db.session import engine
from observability.logging import configure_logging, get_logger

configure_logging()

log = get_logger(stage="api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("OpsFlow API starting")
    yield
    log.info("OpsFlow API stopped")


app = FastAPI(title="OpsFlow AI API", version="0.1.0", lifespan=lifespan)

app.include_router(webhooks_router)
app.include_router(approvals_router)
app.include_router(metrics_router)


@app.middleware("http")
async def request_logging_middleware(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    get_logger(
        stage="http",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    ).info("request completed")
    return response


@app.get("/")
def root() -> dict:
    return {"service": "opsflow-api", "version": app.version, "docs": "/docs"}


@app.get("/healthz")
def healthz() -> dict:
    """Liveness probe: the process is running."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict:
    """Readiness probe: dependencies (database) are reachable."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        get_logger(stage="readiness").exception("database not ready")
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready", "database": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host=settings.api_host, port=settings.api_port)
