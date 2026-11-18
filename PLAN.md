# OpsFlow AI — Master Project Plan

**Status:** Active  
**Last updated:** 2026-11-18  
**Target region:** `eu-north-1` (Stockholm)  
**Cost ceiling:** **$0.00**  
**Primary target:** `UzairAjaz/Retriva-AI`  
**OpsFlow runtime:** Local Docker/Python, not AWS compute

---

## 1. Executive decision

OpsFlow AI is now a **zero-cost, local-first GitOps code-remediation system**.

The AWS account is active, but it is a **paid account with no 12-month free tier and no credits**. The payment card belongs to a friend. Therefore:

- No paid AWS resource may be provisioned.
- AWS is used only for the **messaging pipeline**.
- Retriva-AI and the OpsFlow bot run locally.
- Local Postgres/Redis replace RDS/ElastiCache.
- Local Ollama replaces any paid inference API.
- GitHub Actions replaces paid CI infrastructure.
- GitHub API polling replaces public webhook ingress.

The goal is to prove the full remediation loop without creating a bill.

---

## 2. Non-negotiable constraints

### Allowed AWS services

Only these may be provisioned, and only within their always-free allowances:

| Service | Purpose | Guardrail |
|---|---|---|
| CloudWatch Logs | Receive local Retriva error logs | 1-day retention, ERROR/CRITICAL only |
| AWS Lambda | Filter CloudWatch events and forward to SQS | 128 MB, 30 s timeout, reserved concurrency 1 |
| Amazon SQS | Durable alert queue + DLQ | Long polling, batch size 10, 4-day retention |

IAM users/roles are required to use those services, but no paid compute or storage services are added.

### Banned AWS services

Do **not** provision any of the following:

```text
NAT Gateway
VPC / subnets / route tables / internet gateway
VPC interface endpoints
RDS / Aurora
ElastiCache / Redis on AWS
ALB / NLB
ECS / Fargate
EC2
ECR
Secrets Manager
EventBridge
Route 53 hosted zones
ACM certificates
S3
CloudFront
API Gateway
Step Functions
Kinesis / Firehose
Any 24/7 compute or managed database
```

No service outside the allowed list may be enabled without a written cost review and explicit approval.

---

## 3. Zero-cost architecture

```text
┌──────────────────────────────── local laptop ────────────────────────────────┐
│                                                                             │
│  Retriva-AI (FastAPI + local Ollama)                                        │
│    └─ JSON logs with service/environment/commit_sha/trace_id                │
│         └─ local CloudWatch log shipper (boto3/watchtower)                  │
│                                                                             │
│  OpsFlow Bot (Python/FastAPI worker, local Docker)                          │
│    ├─ SQS long-poll consumer                                                │
│    ├─ local Postgres / SQLite incident store                                │
│    ├─ local Redis for cache/rate limits                                     │
│    ├─ local Ollama qwen2.5-coder:3b                                         │
│    ├─ GitHub App client (local private key)                                 │
│    ├─ GitHub API polling for CI/PR state                                    │
│    └─ local reports / notifications                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                    │ logs:PutLogEvents
                    ▼
┌──────────────────────────── AWS eu-north-1 ─────────────────────────────────┐
│  CloudWatch Logs  /opsflow/retriva-api                                      │
│    └─ Subscription Filter: level = ERROR or CRITICAL                        │
│         └─ Lambda: opsflow-cloudwatch-forwarder                             │
│              └─ SQS: opsflow-alerts + opsflow-alerts-dlq                    │
└─────────────────────────────────────────────────────────────────────────────┘
                    ▲
                    │ sqs:ReceiveMessage / DeleteMessage
                    │
        OpsFlow Bot on the local laptop
```

### What lives where

| Component | Location | Reason |
|---|---|---|
| Retriva-AI API | Local Docker/Python | No Fargate/EC2 budget |
| OpsFlow API/worker | Local Docker/Python | No Fargate/EC2 budget |
| Ollama models | Local CPU | No paid inference |
| Postgres/Redis | Local Docker | No RDS/ElastiCache budget |
| GitHub App / PRs | GitHub.com | Free for public repo |
| CI checks | GitHub Actions | Free for public repo |
| Alert ingestion | CloudWatch Logs + Lambda + SQS | Only allowed AWS services |
| GitHub webhooks | Replaced by GitHub API polling | Local bot has no public HTTPS endpoint |
| Post-merge verification | Local poller against CloudWatch Logs | No ALB/API Gateway/EventBridge |
| Secrets | Local `.env` + local key files | No Secrets Manager |

---

## 4. Deployment model

### Local deployment

Retriva-AI and OpsFlow run on the developer laptop:

```powershell
# Local dependencies
docker compose up -d postgres redis

# Local Ollama
ollama serve
ollama pull qwen2.5-coder:3b

# Local OpsFlow bot (once implemented)
.\.venv\Scripts\python.exe -m worker.consumers.alert_consumer
```

No local service is exposed publicly. The bot polls SQS; it does not need inbound ports.

### AWS deployment

Only the messaging stack is deployed:

1. CloudWatch log group `/opsflow/retriva-api` in `eu-north-1`.
2. Lambda `opsflow-cloudwatch-forwarder` outside a VPC.
3. SQS `opsflow-alerts` plus `opsflow-alerts-dlq`.
4. IAM user/role with only the required permissions.
5. CloudWatch subscription filter with an ERROR/CRITICAL pattern.

No VPC, NAT, ALB, ECS, RDS, ElastiCache, ECR, or Secrets Manager.

### Local log shipping

Retriva writes JSON logs locally. A local shipper sends only ERROR/CRITICAL
records to CloudWatch Logs using `logs:CreateLogStream` and
`logs:PutLogEvents`.

The log group has **1-day retention** to keep storage inside the free allowance.
The shipper must not send INFO/DEBUG or request bodies.

### GitHub integration without webhooks

A local bot cannot receive GitHub webhooks without a public endpoint, and no ALB
or API Gateway is allowed. Therefore:

- Poll GitHub Checks/PR APIs for CI and merge state.
- Poll SQS for alerts.
- Poll CloudWatch Logs for post-merge verification.
- Use GitHub Actions for `test` and `lint`.
- Use the GitHub App for branch/PR operations, not webhooks.

---

## 5. Credentials and IAM

### Local credentials

- AWS CLI profile `opsflow-dev` or an SSO profile.
- Permissions limited to:
  - `logs:CreateLogStream`, `logs:PutLogEvents`
  - `sqs:SendMessage` for the local test publisher
  - `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility`, `sqs:GetQueueAttributes`
- No `iam:*`, no `ec2:*`, no `rds:*`, no `ecs:*`, no `elasticache:*`.

### Lambda role

- `logs:CreateLogStream`, `logs:PutLogEvents`
- `sqs:SendMessage` to `opsflow-alerts`
- No VPC permissions, no Secrets Manager, no S3.

### GitHub App

- Local private key, stored outside Git.
- Permissions: `contents:write`, `pull_requests:write`, `checks:read`, `metadata:read`, `actions:read`.
- Bot can push branches but cannot merge.
- `.env` and key files are gitignored.

### Secrets handling

- No AWS Secrets Manager.
- Local `.env` is gitignored.
- Key files must be `chmod 600` where supported.
- Rotate any credential accidentally committed.

---

## 6. Cost guardrails

1. Any AWS spend above **$0.00** is a failure and must be investigated immediately.
2. The AWS Billing console is reviewed after each Phase 1B/2 test.
3. CloudWatch log retention is **1 day**.
4. The log shipper sends only ERROR/CRITICAL records.
5. Lambda is 128 MB, 30 s, reserved concurrency 1.
6. SQS uses long polling and batch size 10.
7. No resource outside the allowed list is created.
8. The old paid-stack scripts under `deploy/aws/` are **not** to be run as-is.
9. Any proposal to add a paid service requires explicit approval from the card owner and project owner.

---

## 7. Progress tracker

| Phase | Status | Notes |
|---|---|---|
| **Phase 0** — Git safety, CODEOWNERS, kill switch | ✅ COMPLETE | Branch protection, CODEOWNERS, baseline tag, kill switch |
| **Phase 1A** — Retriva-AI observability, JSON logging, `/debug/boom` | ✅ COMPLETE & MERGED | PR #1 merged; CI `test` + `lint` passed |
| **Phase 1B** — AWS deployment | ✅ COMPLETE | Minimal zero-cost stack in `eu-north-1`; real `/debug/boom` → CloudWatch → Lambda → SQS verified |
| **Phase 2A** — SQS ingestion and local state | ✅ COMPLETE | Local consumer, Postgres incident store, Retriva mapping, kill switch; real message verified |
| **Phase 2B** — Code-fix vertical slice | ⏳ PENDING | GitHub App, code fetch, Ollama patch, validation, Draft PR, CI polling |
| **Phase 3 & Beyond** — verification, revert, hardening | ⏳ PENDING | Local-first; no paid AWS compute |

### Phase 1B scope — minimal zero-cost AWS messaging stack

- [x] Set AWS region to `eu-north-1`.
- [x] Confirm the IAM principal can create only CloudWatch Logs, Lambda, and SQS.
- [x] Create `/opsflow/retriva-api` log group with 1-day retention.
- [x] Create `opsflow-alerts` and `opsflow-alerts-dlq`.
- [x] Create Lambda `opsflow-cloudwatch-forwarder` (128 MB, 30 s).
- [x] Grant Lambda `sqs:SendMessage`.
- [x] Add the CloudWatch subscription filter for ERROR/CRITICAL.
- [x] Add a local Retriva Watchtower shipper to CloudWatch.
- [x] Run Retriva locally with `ENABLE_TEST_BUG=true`.
- [x] Trigger `/debug/boom` and verify one real SQS message.
- [ ] Manual AWS Billing review confirms $0.00.

**Verified result:** the real SQS message contained `tenant=retriva`,
`service=retriva-api`, `environment=local`, `commit=c736b10`,
`error_class=KeyError`, `file=api_server.py`, `line=534`,
`request_id` and `trace_id` populated, and `analysis_only=false`.

### Phase 2A scope — SQS ingestion and local state

- [x] SQS long-poll consumer (`worker/consumers/alert_consumer.py`).
- [x] Local Postgres incident store.
- [x] Tenant and repository mapping for `retriva`.
- [x] Windows path normalization to repo-relative paths.
- [x] Kill switch respected: incidents stored `analysis_only` while `CODE_FIX_ENABLED=false`.
- [x] Idempotent duplicate handling via `dedupe_key`.

**Verified result:** a real `/debug/boom` message was consumed from SQS,
saved as incident `ae1ee382-7d84-4b16-92d1-052ffef0977c`, normalized to
`api_server.py:534`, and a second delivery reused the same incident with
`processed_alerts.count=2`.

### Phase 2B scope — code-fix vertical slice

- [ ] Local GitHub App authentication.
- [ ] Code fetch at `commit_sha`.
- [ ] Local Ollama `qwen2.5-coder:3b`.
- [ ] Patch generation and local validation.
- [ ] Draft PR creation.
- [ ] CI status polling via GitHub API.
- [ ] Local reports and notifications.

### Phase 3+ scope

- Patch policy and secret scanning.
- Full CI polling and merge tracking.
- Post-merge CloudWatch verification.
- Draft revert PR flow.
- Evaluation, hardening, and runbooks.

---

## 8. Acceptance criteria for the zero-cost architecture

- A real Retriva exception reaches SQS through CloudWatch + Lambda.
- The message contains the real `commit_sha`, service, tenant, file, line, and stack trace.
- The local OpsFlow bot consumes the message without AWS compute.
- The bot can open a Draft PR via the GitHub App.
- CI `test` and `lint` pass.
- Post-merge verification runs locally against CloudWatch Logs.
- AWS Billing remains **$0.00**.
- No banned service exists in the account.

---

## 9. Superseded documents

`docs/PHASE_3_GITOPS_IMPLEMENTATION_PLAN.md` was written for an ECS/RDS/ALB
architecture. It is **superseded by this plan** for AWS deployment and must not
be used to provision infrastructure without rewriting its cost model.

`deploy/aws/` contains scripts for the old paid stack. Do not run the network,
RDS, ElastiCache, ECS, ALB, EventBridge, Secrets Manager, or teardown scripts in
zero-cost mode.
