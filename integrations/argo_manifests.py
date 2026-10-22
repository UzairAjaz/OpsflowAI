from __future__ import annotations

from pathlib import Path

import yaml

def build_rollout_manifest(
    *, name: str, image: str, steps: list[int], namespace: str = "default"
) -> dict:
    canary_steps: list[dict] = []
    for percentage in steps[:-1]:
        canary_steps.append({"setWeight": percentage})
        canary_steps.append({"pause": {"duration": "10m"}})
    canary_steps.append({"setWeight": steps[-1]})

    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Rollout",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "replicas": 10,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {"containers": [{"name": name, "image": image}]},
            },
            "strategy": {
                "canary": {
                    "steps": canary_steps,
                    "analysis": {
                        "templates": [{"templateName": f"{name}-analysis"}],
                    },
                }
            },
        },
    }

def build_analysis_template(
    *,
    name: str,
    namespace: str = "default",
    error_rate_threshold: float = 0.05,
    p95_threshold_ms: int = 500,
    prometheus_address: str = "http://prometheus.monitoring:9090",
) -> dict:
    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "AnalysisTemplate",
        "metadata": {"name": f"{name}-analysis", "namespace": namespace},
        "spec": {
            "metrics": [
                {
                    "name": "error-rate",
                    "interval": "1m",
                    "successCondition": f"result[0] <= {error_rate_threshold}",
                    "failureLimit": 1,
                    "provider": {
                        "prometheus": {
                            "address": prometheus_address,
                            "query": (
                                f'sum(rate(http_requests_total{{app="{name}",code=~"5.."}}[1m])) '
                                f'/ sum(rate(http_requests_total{{app="{name}"}}[1m]))'
                            ),
                        }
                    },
                },
                {
                    "name": "p95-latency",
                    "interval": "1m",
                    "successCondition": f"result[0] <= {p95_threshold_ms}",
                    "failureLimit": 1,
                    "provider": {
                        "prometheus": {
                            "address": prometheus_address,
                            "query": (
                                "histogram_quantile(0.95, "
                                f'sum(rate(http_request_duration_seconds_bucket{{app="{name}"}}[5m])) by (le))'
                            ),
                        }
                    },
                },
            ]
        },
    }

def write_manifests(
    *,
    name: str,
    image: str,
    steps: list[int],
    namespace: str = "default",
    out_dir: str = "deploy/k8s",
) -> tuple[dict, dict]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    rollout = build_rollout_manifest(name=name, image=image, steps=steps, namespace=namespace)
    analysis = build_analysis_template(name=name, namespace=namespace)

    (out / f"{name}-rollout.yaml").write_text(
        yaml.safe_dump(rollout, sort_keys=False), encoding="utf-8"
    )
    (out / f"{name}-analysis.yaml").write_text(
        yaml.safe_dump(analysis, sort_keys=False), encoding="utf-8"
    )
    return rollout, analysis
