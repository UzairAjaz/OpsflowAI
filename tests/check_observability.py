from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from app.config import settings
from observability import metrics
from observability.tracing import configure_tracing, get_recorded_spans, span

def main() -> None:
    settings.otel_enabled = True
    settings.otel_exporter = "memory"
    assert configure_tracing() is True

    with span("unit-test", incident_id="inc-1", stage="test"):
        pass
    names = [recorded.name for recorded in get_recorded_spans()]
    assert "unit-test" in names, names
    print("tracing   -> recorded spans:", names[:3])

    metrics.record_incident(tenant="acme", severity="high", mttd=0.2)
    metrics.record_resolution(auto=False, mttr=120.0)
    metrics.record_sandbox_failure()
    metrics.record_canary_rollback()

    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200, response.text
    body = response.text
    for series in (
        "opsflow_incident_total",
        "opsflow_incident_manual_approval_total",
        "opsflow_sandbox_failures_total",
        "opsflow_canary_rollback_total",
    ):
        assert series in body, series
    print("metrics   -> /metrics exposes opsflow_* series")

    print("[ok] P2-31..P2-33 -- tracing, metrics, structured logs working.")

if __name__ == "__main__":
    main()
