# OpsFlow AI

**Zero-cost, local-first GitOps code remediation.**

OpsFlow AI ingests real application errors, resolves the deployed commit, asks a
local coding model for a minimal patch, validates it, and opens a Draft Pull
Request for human review. Retriva-AI is the first target service.

The current architecture is deliberately constrained to **$0.00 AWS spend**.
Only the messaging pipeline runs on AWS; the application, worker, database,
cache, and LLM run locally.

**Master plan:** [`PLAN.md`](./PLAN.md)

---

## Current status

| Phase | Status | Notes |
|---|---|---|
| **Phase 0** — Git safety, CODEOWNERS, kill switch | ✅ COMPLETE | Branch protection, CODEOWNERS, baseline tag, kill switch |
| **Phase 1A** — Retriva-AI observability, JSON logging, `/debug/boom` | ✅ COMPLETE & MERGED | PR [#1](https://github.com/UzairAjaz/Retriva-AI/pull/1); CI `test` + `lint` passed |
| **Phase 1B** — AWS deployment | ✅ COMPLETE | Zero-cost stack in `eu-north-1`; real CloudWatch → Lambda → SQS message verified |
| **Phase 2** — OpsFlow Bot Core | ⏳ PENDING | Will run locally, consuming from real AWS SQS |
| **Phase 3 & Beyond** — validation, CI polling, verification, revert | ⏳ PENDING | Local-first; no paid AWS compute |

---

## What runs where

| Component | Location | Notes |
|---|---|---|
| Retriva-AI FastAPI service | Local Docker/Python | No ECS/Fargate |
| OpsFlow API/worker | Local Docker/Python | No ECS/Fargate |
| Ollama (`qwen2.5-coder:3b`) | Local CPU | No paid inference |
| Postgres / SQLite | Local Docker / local file | No RDS |
| Redis | Local Docker | No ElastiCache |
| Alert ingestion | AWS `eu-north-1` | CloudWatch Logs → Lambda → SQS |
| GitHub App / Draft PRs | GitHub.com | Public repo; free GitHub Actions |
| CI status | GitHub API polling | No public webhook endpoint |
| Post-merge verification | Local CloudWatch polling | No ALB/API Gateway/EventBridge |
| Secrets | Local `.env` + local key files | No Secrets Manager |

### Allowed AWS services

```text
CloudWatch Logs   (1-day retention, ERROR/CRITICAL only)
AWS Lambda        (128 MB, 30 s, reserved concurrency 1)
Amazon SQS        (alerts queue + DLQ, long polling)
```

### Banned AWS services

```text
NAT Gateway, VPC, VPC endpoints, RDS, ElastiCache, ALB/NLB,
ECS/Fargate, EC2, ECR, Secrets Manager, EventBridge, Route 53,
ACM, S3, CloudFront, API Gateway, Step Functions,
Kinesis/Firehose, any 24/7 compute or managed database
```

No service outside the allowed list may be enabled without a written cost review
and explicit approval from the card owner.

---

## Architecture

```text
Local laptop
  Retriva-AI (FastAPI + local Ollama)
    └─ JSON logs
         └─ local CloudWatch log shipper
              │
              ▼
AWS eu-north-1
  CloudWatch Logs /opsflow/retriva-api
    └─ Subscription Filter (ERROR/CRITICAL)
         └─ Lambda: opsflow-cloudwatch-forwarder
              └─ SQS: opsflow-alerts + DLQ
                   │
                   ▼
Local laptop
  OpsFlow Bot
    ├─ SQS long-poll consumer
    ├─ local SQLite/Postgres incident store
    ├─ local Redis cache/rate limiting
    ├─ local Ollama qwen2.5-coder:3b
    ├─ GitHub App → branch + Draft PR
    ├─ GitHub API polling for CI/merge
    ├─ CloudWatch polling for post-merge verification
    └─ local reports and notifications
```

Key architectural changes from the original plan:

- **No ECS/Fargate.** OpsFlow and Retriva run locally.
- **No RDS/ElastiCache.** Use local Docker services.
- **No ALB/API Gateway.** The local bot polls SQS and GitHub instead of receiving webhooks.
- **No Secrets Manager.** Use local `.env` and local GitHub App key files.
- **No NAT/VPC.** Lambda runs outside a VPC and calls SQS directly.
- **No paid AWS services.** Only CloudWatch Logs, Lambda, and SQS.

---

## Quick start

### Prerequisites

- Python 3.12+
- Docker Desktop
- Ollama
- AWS CLI configured with a least-privilege profile
- GitHub CLI authenticated

### Local dependencies

```powershell
docker compose up -d postgres redis

ollama serve
ollama pull qwen2.5-coder:3b
```

### OpsFlow setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Run the local API/worker once Phase 2 is implemented:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m worker.consumers.alert_consumer
```

### Retriva target service

```powershell
git clone https://github.com/UzairAjaz/Retriva-AI.git C:\Users\RQ\Documents\Retriva-AI
cd C:\Users\RQ\Documents\Retriva-AI
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Set `ENABLE_TEST_BUG=true` only for the local staging test.

---

## Repository layout

```text
api/                    FastAPI API
app/                    LangGraph, remediation catalog, config, safety
worker/                 Local workers and SQS consumers
integrations/           AWS, GitHub, notifications, storage
ingestion/              Alert schemas and normalization
db/                     SQLAlchemy models and sessions
migrations/             Alembic migrations
deploy/aws/             Legacy paid-stack scripts; do not run as-is
docs/                   Configuration, runbooks, and phase plans
tests/                  Verification scripts
PLAN.md                 Master plan and zero-cost architecture
```

---

## Documentation

- [`PLAN.md`](./PLAN.md) — master plan, architecture, and phase tracker
- [`docs/CONFIGURATION_GUIDE.md`](./docs/CONFIGURATION_GUIDE.md) — environment configuration
- [`docs/PHASE_1_TASK_1_JSON_LOGGING.md`](./docs/PHASE_1_TASK_1_JSON_LOGGING.md) — Retriva logging task
- [`docs/BASELINE_TEST_RESULT.md`](./docs/BASELINE_TEST_RESULT.md) — pre-GitOps baseline

---

## Legacy note

The original infrastructure-remediation agent under `app/`, `api/`, and
`worker/` remains in the repository, but it is not the critical path for the
zero-cost GitOps rollout. The old `docs/PHASE_3_GITOPS_IMPLEMENTATION_PLAN.md`
describes an ECS/RDS/ALB architecture that is superseded by `PLAN.md`.
