"""Prometheus metrics.

Counters and histograms track the platform's key indicators (incidents,
auto-resolution, approvals, sandbox failures, canary rollbacks, MTTD/MTTR,
fix success rate, approval latency). Exposed at `/metrics`.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

incident_total = Counter(
    "opsflow_incident_total", "Total incidents created", ["tenant", "severity"]
)
incident_auto_resolved_total = Counter(
    "opsflow_incident_auto_resolved_total", "Incidents resolved without human approval"
)
incident_manual_approval_total = Counter(
    "opsflow_incident_manual_approval_total", "Incidents that required human approval"
)
sandbox_failures_total = Counter(
    "opsflow_sandbox_failures_total", "Sandbox validation failures"
)
canary_rollback_total = Counter("opsflow_canary_rollback_total", "Canary rollbacks")

mttd_seconds = Histogram("opsflow_mttd_seconds", "Mean time to detect (seconds)")
mttr_seconds = Histogram("opsflow_mttr_seconds", "Mean time to resolve (seconds)")
approval_latency_seconds = Histogram(
    "opsflow_approval_latency_seconds", "Approval latency (seconds)"
)
fix_success_rate = Gauge("opsflow_fix_success_rate", "Rolling fix success rate (0-1)")


def record_incident(*, tenant: str, severity: str, mttd: float = 0.0) -> None:
    incident_total.labels(tenant=tenant, severity=severity).inc()
    if mttd:
        mttd_seconds.observe(mttd)


def record_resolution(*, auto: bool, mttr: float = 0.0) -> None:
    if auto:
        incident_auto_resolved_total.inc()
    else:
        incident_manual_approval_total.inc()
    if mttr:
        mttr_seconds.observe(mttr)


def record_sandbox_failure() -> None:
    sandbox_failures_total.inc()


def record_canary_rollback() -> None:
    canary_rollback_total.inc()
