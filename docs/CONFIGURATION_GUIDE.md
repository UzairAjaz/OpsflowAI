# OpsFlow AI — Centralized Configuration Guide

## Single source of truth

All runtime configuration is defined in:

- `app/config.py` — typed Pydantic `Settings`
- `.env` — local values (not committed)
- `.env.example` — canonical variable list and safe local defaults

Application modules must import the shared object:

```python
from app.config import settings
```

Do not hardcode service URLs, credentials, queue names, model names, report
paths, or environment-specific values inside nodes, routes, workers, or
integrations.

---

## Environment profiles

Set the profile in `.env`:

```env
ENVIRONMENT=local
```

Allowed values:

- `local`
- `staging`
- `production`

The `production` profile is guarded. It refuses to start if:

- `AUTH_DEV_MODE=true`
- `WEBHOOK_SECRET` is still the development secret
- `APPROVAL_TOKEN_SECRET` is still the development secret
- `DATABASE_URL` still contains the demo `opsflow:opsflow` credentials

This prevents accidentally running a demo configuration in production.

---

## Variable groups

### Runtime

```env
ENVIRONMENT=local
APP_NAME=OpsFlow AI API
APP_VERSION=0.1.0
SERVICE_NAME=opsflow-api
LOG_LEVEL=INFO
API_HOST=0.0.0.0
API_PORT=8000
```

### LLM and embeddings

```env
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_BASE_URL=http://localhost:11434
EMBEDDING_BACKEND=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
EMBEDDING_CHUNK_SIZE=800
EMBEDDING_CHUNK_OVERLAP=100
```

### Database, Redis, and queue

```env
DATABASE_URL=postgresql+psycopg://opsflow:opsflow@localhost:5432/opsflow
POSTGRES_USER=opsflow
POSTGRES_PASSWORD=opsflow
POSTGRES_DB=opsflow
POSTGRES_PORT=5432
REDIS_URL=redis://localhost:6379/0
REDIS_PORT=6379
CHECKPOINTER=memory
QUEUE_NAME=incidents
QUEUE_RESULT_TTL_SECONDS=300
QUEUE_FAILURE_TTL_SECONDS=300
```

`POSTGRES_*` and `REDIS_PORT` are consumed by `docker-compose.yml`, which
interpolates them from the same `.env` file. Keep them consistent with
`DATABASE_URL` and `REDIS_URL`.

### API security

```env
WEBHOOK_SECRET=dev-secret-change-me
WEBHOOK_SIGNATURE_HEADER=X-Signature
AUTH_DEV_MODE=true
DEV_TENANT_ID=mediconnect
AUTH_JWT_SECRET=opsflow-dev-jwt-secret-change-me-please
AUTH_JWT_ALGORITHM=HS256
AUTH_TOKEN_TTL_MINUTES=60
TENANT_API_KEYS=
```

### Knowledge and RAG

```env
KB_BACKEND=none
KB_FALLBACK_ENABLED=true
RULEBOOK_RETRIEVAL_ENABLED=true
KB_NAMESPACE_PREFIX=tenant_
KB_TIMEOUT_SECONDS=5
TENANT_KB_BASE_URL=http://localhost:9200
TENANT_KB_API_KEY=
TENANT_KB_SEARCH_PATH=/v1/search
LIVE_CONNECTOR_BASE_URL=
LIVE_CONNECTOR_API_KEY=
LIVE_CONNECTOR_SEARCH_PATH=/v1/search
HISTORY_PREFERENCE_THRESHOLD=0.7
```

### Sandbox and execution

```env
DRY_RUN=true
SANDBOX_BACKEND=docker
SANDBOX_IMAGE=alpine:3.20
SANDBOX_TIMEOUT_SECONDS=30
SANDBOX_MEMORY_LIMIT=256m
SANDBOX_CPUS=0.5
SANDBOX_NETWORK=false
SANDBOX_MAX_ATTEMPTS=2
DEFAULT_MEMORY_LIMIT=2Gi
```

### Notifications and approvals

```env
PUBLIC_BASE_URL=http://localhost:8000
ALERT_WEBHOOK_URL=
ALERT_WEBHOOK_PATH=/api/v1/webhooks/alert
SLACK_WEBHOOK_URL=
SLACK_SIGNING_SECRET=
SMTP_HOST=
SMTP_PORT=587
SMTP_USE_SSL=false
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=opsflow@example.com
SMTP_TO=oncall@example.com
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM=
TWILIO_TO=
TWILIO_API_BASE_URL=https://api.twilio.com
PAGERDUTY_ROUTING_KEY=
NOTIFICATION_TIMEOUT_SECONDS=10
APPROVAL_TOKEN_SECRET=dev-approval-secret
APPROVAL_TOKEN_TTL_MINUTES=120
ESCALATION_MINUTES=15,30,60
ESCALATION_RECIPIENTS=manager,senior_manager,cto
```

### Demo values

```env
DEMO_TENANT_ID=mediconnect
DEMO_TENANT_NAME=MediConnect
DEMO_SERVICE=mediconnect-backend
DEMO_ERROR_CLASS=OOMKilled
DEMO_EMAIL=admin@mediconnect.local
DEMO_APPROVER=demo-cli
CLI_APPROVER=cli-user
```

### Canary and Argo

```env
CANARY_BACKEND=simulated
CANARY_STEPS=10,25,50,100
CANARY_ERROR_RATE_THRESHOLD=0.05
CANARY_P95_THRESHOLD_MS=500
PROMETHEUS_URL=
ARGO_NAMESPACE=default
ARGO_PROMETHEUS_ADDRESS=http://prometheus.monitoring:9090
DEPLOY_K8S_DIR=deploy/k8s
```

### Observability and reports

```env
OTEL_ENABLED=false
OTEL_EXPORTER=memory
OTEL_ENDPOINT=
OTEL_SERVICE_NAME=opsflow-ai
FEEDBACK_HORIZON_HOURS=24
EVALS_PATH=evals/dataset.jsonl
REPORTS_DIR=reports
WORKER_JOB_TIMEOUT_SECONDS=1800
```

---

## Environment switching

### Local

```env
ENVIRONMENT=local
AUTH_DEV_MODE=true
DRY_RUN=true
CHECKPOINTER=memory
ALERT_WEBHOOK_URL=http://127.0.0.1:8000/api/v1/webhooks/alert
```

### Staging

```env
ENVIRONMENT=staging
AUTH_DEV_MODE=false
DRY_RUN=false
CHECKPOINTER=postgres
DATABASE_URL=postgresql+psycopg://user:pass@staging-db:5432/opsflow
REDIS_URL=redis://staging-redis:6379/0
```

### Production

```env
ENVIRONMENT=production
AUTH_DEV_MODE=false
DRY_RUN=false
CHECKPOINTER=postgres
DATABASE_URL=postgresql+psycopg://user:strong-password@prod-db:5432/opsflow
REDIS_URL=rediss://prod-redis:6379/0
WEBHOOK_SECRET=replace-with-a-long-random-secret
APPROVAL_TOKEN_SECRET=replace-with-a-long-random-secret
AUTH_JWT_SECRET=replace-with-a-long-random-secret
```

For production, also configure:

- Strong `TENANT_API_KEYS`
- SMTP/Slack/Twilio credentials
- `PUBLIC_BASE_URL` with the real HTTPS domain
- `PROMETHEUS_URL` and `ARGO_PROMETHEUS_ADDRESS`
- `OTEL_ENABLED=true` if using tracing

---

## Adding a new setting

1. Add a typed field to `app/config.py`.
2. Add the variable to `.env.example`.
3. Add the local value to `.env`.
4. Reference `settings.<field>` from application code.
5. Add a test if the setting changes behavior.

Never read arbitrary environment variables directly in application modules.
Use `settings` so validation, defaults, and production guards remain centralized.

---

## Secret handling

- `.env` is ignored by Git.
- Never commit real credentials.
- In production, prefer a secrets manager (AWS Secrets Manager, Vault, etc.)
  to inject environment variables.
- Rotate the webhook, approval, and JWT secrets regularly.
- Do not place secrets in logs, reports, or agent prompts.
