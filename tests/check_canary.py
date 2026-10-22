from __future__ import annotations

from pathlib import Path

import yaml

from app.nodes.canary import run_canary
from app.state import new_incident
from integrations.argo_manifests import write_manifests
from integrations.canary import (
    SimulatedCanaryController,
    StaticMetricsProvider,
    parse_canary_steps,
    set_canary_controller,
    set_metrics_provider,
)

def _state(service: str = "checkout-api") -> dict:
    return new_incident("oom", tenant_id="acme", service=service, error_class="OOMKilled")

def main() -> None:
    steps = parse_canary_steps()
    assert steps == [10, 25, 50, 100]
    print("steps     ->", steps)

    healthy = SimulatedCanaryController().run(
        service="checkout-api",
        steps=steps,
        error_rate_threshold=0.05,
        p95_threshold_ms=500,
        metrics=StaticMetricsProvider(),
    )
    assert healthy.status == "promoted" and len(healthy.stages) == 4
    print("promote   ->", [stage.percentage for stage in healthy.stages])

    failing = SimulatedCanaryController().run(
        service="checkout-api",
        steps=steps,
        error_rate_threshold=0.05,
        p95_threshold_ms=500,
        metrics=StaticMetricsProvider(fail_at_percentage=50),
    )
    assert failing.status == "rolled_back" and failing.stages[-1].percentage == 50
    print("rollback  ->", failing.rollback_reason)

    set_canary_controller(SimulatedCanaryController())
    set_metrics_provider(StaticMetricsProvider())
    update = run_canary(_state())
    assert update["status"] == "completed" and len(update["canary_stages"]) == 4
    print("node      ->", update["audit"][0].detail)

    set_metrics_provider(StaticMetricsProvider(fail_at_percentage=25))
    update = run_canary(_state())
    assert update["status"] == "rolled_back"
    print("node      ->", update["audit"][0].detail)
    set_canary_controller(None)
    set_metrics_provider(None)

    rollout, analysis = write_manifests(
        name="canary-test", image="img:1", steps=steps, out_dir="deploy/k8s"
    )
    assert rollout["kind"] == "Rollout"
    assert rollout["spec"]["strategy"]["canary"]["steps"][0] == {"setWeight": 10}
    assert analysis["kind"] == "AnalysisTemplate"
    metric_names = [metric["name"] for metric in analysis["spec"]["metrics"]]
    assert metric_names == ["error-rate", "p95-latency"]
    for path in Path("deploy/k8s").glob("canary-test-*.yaml"):
        yaml.safe_load(path.read_text(encoding="utf-8"))
        path.unlink()
    print("manifests -> Rollout + AnalysisTemplate (error-rate, p95-latency)")

    print("[ok] P2-27..P2-29 -- canary manifests, gates, and rollback working.")

if __name__ == "__main__":
    main()
