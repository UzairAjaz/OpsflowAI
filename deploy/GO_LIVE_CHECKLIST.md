# OpsFlow AI — Go-Live Checklist

Use this before enabling OpsFlow on production traffic. Check items as they are completed.

## Infrastructure
- [ ] PostgreSQL 15+ provisioned (HA + backups) and `alembic upgrade head` applied
- [ ] Redis 7+ provisioned (persistence enabled for the queue)
- [ ] `docker compose up -d` (or managed equivalents) healthy
- [ ] Secrets loaded via environment (no secrets in the repo)
- [ ] `WEBHOOK_SECRET` and `APPROVAL_TOKEN_SECRET` set to strong random values
- [ ] `TENANT_API_KEYS` configured per tenant (auth enabled)

## Detection (Layer 1)
- [ ] Monitoring sources (CloudWatch/Prometheus/Grafana/Datadog) configured to POST
      `/api/v1/webhooks/alert` with an HMAC-SHA256 `X-Signature`
- [ ] Rate limit and dedupe window tuned (`ALERT_RATE_LIMIT_PER_MINUTE`,
      `ALERT_DEDUPE_WINDOW_SECONDS`)
- [ ] Severity classification reviewed (`SEVERITY_USE_LLM` as desired)

## Diagnosis (Layer 2)
- [ ] Knowledge base configured (`KB_BACKEND`, `TENANT_KB_BASE_URL`, `TENANT_KB_API_KEY`)
- [ ] Per-tenant namespace isolation verified (no cross-tenant reads)
- [ ] History lookup verified; `HISTORY_PREFERENCE_THRESHOLD` set
- [ ] Confidence thresholds reviewed (`CONFIDENCE_THRESHOLD`)

## Safe Execution (Layer 3)
- [ ] Sandbox image equals the target service image (`SANDBOX_IMAGE`)
- [ ] `SANDBOX_NETWORK=false` unless the fix requires egress
- [ ] Rollback templates present for all reversible actions; irreversible actions have a plan
- [ ] `DRY_RUN` decision made (start `true`)

## Notifications (Layer 4)
- [ ] Slack app + signing secret + interactivity URL configured (`SLACK_WEBHOOK_URL`,
      `SLACK_SIGNING_SECRET`)
- [ ] SMTP backup channel configured (optional)
- [ ] SMS/PagerDuty configured for critical incidents (optional)
- [ ] Escalation tree owners confirmed (`ESCALATION_MINUTES`)
- [ ] Escalation job scheduled (`python -m worker.escalation`)

## Canary (Layer 5)
- [ ] `CANARY_BACKEND` set (`argo` in production)
- [ ] Argo Rollouts installed; `deploy/k8s/*-rollout.yaml` and `*-analysis.yaml` applied
- [ ] Prometheus reachable (`PROMETHEUS_URL`); thresholds reviewed
  (`CANARY_ERROR_RATE_THRESHOLD`, `CANARY_P95_THRESHOLD_MS`)

## Observability (Layer 6)
- [ ] `OTEL_ENABLED=true` with `OTEL_EXPORTER=otlp` and `OTEL_ENDPOINT` (Jaeger/collector)
- [ ] Prometheus scraping `/metrics`; Grafana dashboards imported
- [ ] Logs shipped to the ELK stack (JSON, correlated by `incident_id`)

## Learning (Layer 7)
- [ ] Feedback job scheduled (`python -m worker.feedback`)
- [ ] Eval harness green in CI (`python -m evals.run_eval`; false-safe rate = 0)
- [ ] Calibration reviewed (`app/calibration.py`) and thresholds adjusted

## Verification
- [ ] `python -m tests.run_all` → all checks pass
- [ ] `python -m alembic check` → no new upgrade operations
- [ ] One end-to-end drill: alert → diagnose → sandbox → approval → canary → report

## Rollback / rollback of the rollout itself
- [ ] Rollback plan defined for every irreversible action
- [ ] Canary auto-rollback verified on a staging rollout
- [ ] A rollback alert loops back through the Layer 1 webhook
