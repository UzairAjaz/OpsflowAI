from __future__ import annotations

from typing import Protocol

import httpx
from pydantic import BaseModel

from app.config import settings

class MetricsSnapshot(BaseModel):
    error_rate: float = 0.0
    p95_ms: float = 0.0
    http_5xx: int = 0

class StageResult(BaseModel):
    percentage: int
    error_rate: float
    p95_ms: float
    promoted: bool
    reason: str = ""

class CanaryOutcome(BaseModel):
    status: str
    stages: list[StageResult]
    rollback_reason: str | None = None

class MetricsProvider(Protocol):
    def snapshot(self, *, service: str, percentage: int) -> MetricsSnapshot: ...

class StaticMetricsProvider:
    def __init__(
        self,
        error_rate: float = 0.0,
        p95_ms: float = 100.0,
        fail_at_percentage: int | None = None,
        fail_error_rate: float = 0.2,
    ) -> None:
        self._error_rate = error_rate
        self._p95_ms = p95_ms
        self._fail_at = fail_at_percentage
        self._fail_error_rate = fail_error_rate

    def snapshot(self, *, service: str, percentage: int) -> MetricsSnapshot:
        if self._fail_at is not None and percentage >= self._fail_at:
            return MetricsSnapshot(error_rate=self._fail_error_rate, p95_ms=self._p95_ms)
        return MetricsSnapshot(error_rate=self._error_rate, p95_ms=self._p95_ms)

class PrometheusMetricsProvider:
    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")

    def snapshot(self, *, service: str, percentage: int) -> MetricsSnapshot:
        error_rate = self._query(f'sum(rate(http_requests_total{{job="{service}",code=~"5.."}}[1m]))')
        p95 = self._query(f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{job="{service}"}}[5m])) by (le))')
        return MetricsSnapshot(error_rate=error_rate or 0.0, p95_ms=(p95 or 0.0) * 1000)

    def _query(self, expression: str) -> float | None:
        try:
            with httpx.Client(timeout=5) as client:
                response = client.get(f"{self._url}/api/v1/query", params={"query": expression})
                response.raise_for_status()
                data = response.json()
            result = data.get("data", {}).get("result", [])
            if not result:
                return None
            return float(result[0]["value"][1])
        except Exception:
            return None

class CanaryController(Protocol):
    name: str

    def run(
        self,
        *,
        service: str,
        steps: list[int],
        error_rate_threshold: float,
        p95_threshold_ms: int,
        metrics: MetricsProvider,
    ) -> CanaryOutcome: ...

class SimulatedCanaryController:
    name = "simulated"

    def run(
        self,
        *,
        service: str,
        steps: list[int],
        error_rate_threshold: float,
        p95_threshold_ms: int,
        metrics: MetricsProvider,
    ) -> CanaryOutcome:
        stages: list[StageResult] = []
        for percentage in steps:
            snapshot = metrics.snapshot(service=service, percentage=percentage)
            healthy = (
                snapshot.error_rate <= error_rate_threshold
                and snapshot.p95_ms <= p95_threshold_ms
            )
            reason = "healthy" if healthy else "threshold breached"
            stages.append(
                StageResult(
                    percentage=percentage,
                    error_rate=snapshot.error_rate,
                    p95_ms=snapshot.p95_ms,
                    promoted=healthy,
                    reason=reason,
                )
            )
            if not healthy:
                return CanaryOutcome(
                    status="rolled_back",
                    stages=stages,
                    rollback_reason=(
                        f"at {percentage}%: error_rate={snapshot.error_rate} "
                        f"(limit {error_rate_threshold}), p95={snapshot.p95_ms}ms "
                        f"(limit {p95_threshold_ms}ms)"
                    ),
                )
        return CanaryOutcome(status="promoted", stages=stages)

class ArgoCanaryController:

    name = "argo"

    def __init__(self, namespace: str = "default") -> None:
        self._namespace = namespace

    def run(self, *, service, steps, error_rate_threshold, p95_threshold_ms, metrics):
        import shutil
        import subprocess

        if not shutil.which("kubectl"):
            return CanaryOutcome(
                status="rolled_back",
                stages=[],
                rollback_reason="kubectl not available; cannot run Argo rollout",
            )

        return SimulatedCanaryController().run(
            service=service,
            steps=steps,
            error_rate_threshold=error_rate_threshold,
            p95_threshold_ms=p95_threshold_ms,
            metrics=metrics,
        )

_CONTROLLER_OVERRIDE: CanaryController | None = None
_METRICS_OVERRIDE: MetricsProvider | None = None

def set_canary_controller(controller: CanaryController | None) -> None:
    global _CONTROLLER_OVERRIDE
    _CONTROLLER_OVERRIDE = controller

def set_metrics_provider(provider: MetricsProvider | None) -> None:
    global _METRICS_OVERRIDE
    _METRICS_OVERRIDE = provider

def get_canary_controller() -> CanaryController:
    if _CONTROLLER_OVERRIDE is not None:
        return _CONTROLLER_OVERRIDE
    if settings.canary_backend == "argo":
        return ArgoCanaryController(namespace=settings.argo_namespace)
    return SimulatedCanaryController()

def get_metrics_provider() -> MetricsProvider:
    if _METRICS_OVERRIDE is not None:
        return _METRICS_OVERRIDE
    if settings.prometheus_url:
        return PrometheusMetricsProvider(settings.prometheus_url)
    return StaticMetricsProvider()

def parse_canary_steps() -> list[int]:
    return [int(item) for item in settings.canary_steps.split(",") if item.strip()]
