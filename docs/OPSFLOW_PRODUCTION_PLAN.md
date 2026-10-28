# OpsFlow AI — Production Readiness & 10-Day MVP Plan

**Status:** Draft for review  
**Date:** 2026-10-27  
**Scope:** Planning only — no implementation in this document

---

## 1. Executive Summary

The proposed 10-day plan is a strong **demo/MVP plan**, but it is not a realistic
**production-ready** plan for one developer in 10 days.

The current plan is directionally correct:

- Detect real incidents
- Diagnose with an AI agent
- Use tenant-specific RAG
- Validate in a sandbox
- Produce a report
- Request human approval
- Execute the fix
- Keep an audit trail

The main correction is to separate three different goals:

| Goal | Realistic timeline |
|---|---|
| Working demo / MVP | 10 days |
| Production pilot for one team/service | 8–12 weeks |
| Fully production-ready multi-tenant platform | 4–6 months |

The phrase “production-ready” should not be used for the 10-day deliverable.
Use **“pilot-ready demo”** or **“MVP”** instead.

---

## 2. Assessment of the 10-Day Plan

### 2.1 What is good

- Clear end-to-end business flow.
- Sensible technology choices for a local/demo environment.
- Multi-tenant thinking from the start.
- RAG-based knowledge management.
- Human approval before execution.
- Audit trail and fix-outcome tracking.
- Structured report generation.
- Realistic recognition that the agent needs a sandbox.

### 2.2 What is risky or incorrect

| Area | Issue | Correction |
|---|---|---|
| Timeline | 10 days for “production-ready” is not credible | Label it MVP/demo; production needs 8–12+ weeks |
| Cost | “$0/month” ignores engineering time, operations, support, and free-tier limits | State “$0 infrastructure for demo”; production has real costs |
| Hosting | Oracle Cloud + AWS CloudWatch + Ngrok is a mixed architecture | Choose one target for the MVP; do not mix providers accidentally |
| LLM | Local 7B/8B models on CPU are slow and unreliable for structured output | Use local model only for demo; use Bedrock/managed LLM or GPU for production |
| Multi-tenancy | `tenant_id` filtering alone is not strong isolation | Add row-level security or schema/database isolation; test cross-tenant access |
| Auth | JWT/RBAC is planned but not fully designed | Define roles, token lifecycle, tenant resolution, and service-to-service auth |
| RAG | “Embeddings generated automatically” is not enough | Add chunking, versioning, re-indexing, metadata filters, retrieval evaluation |
| Approval | Email/Slack links without replay protection are unsafe | Signed, expiring, one-time tokens; RBAC; quorum for high risk |
| Execution | `restart_container`, `run_python_script`, etc. can be dangerous | Allowlist, least privilege, sandbox-only credentials, post-checks, rollback |
| Deployment | No GitOps/CI-CD design | Agent proposes a PR; pipeline deploys; canary + automatic rollback |
| Monitoring | CloudWatch only | Add Prometheus/Grafana or equivalent; monitor the agent itself |
| Testing | Testing only on Day 10 | Unit/integration/E2E/security tests must run throughout |
| Compliance | “SOC2/ISO-ready” from audit logs alone is not valid | Treat compliance as a separate programme |
| Business value | 98% MTTR improvement and 80% automation are unproven | Establish baseline first; measure during pilot |

---

## 3. Recommended Strategy: Two Tracks

### Track A — 10-Day MVP / Demo

Purpose: demonstrate the complete workflow to stakeholders.

Scope:

- One hosting target: local or Oracle Always Free.
- One or two tenants.
- One or two incident classes (e.g., OOM and disk full).
- Real alert ingestion from one source (CloudWatch alarm or Prometheus webhook).
- Tenant-specific rulebook retrieval.
- Sandbox execution using Docker or a fake sandbox.
- Structured report.
- Email or Slack notification.
- Signed approval link.
- Audit trail.
- Demo script and fallback plan.

Explicitly **not** included:

- Production write access
- High availability
- Full RBAC/JWT
- Compliance certification
- Multi-region deployment
- Automatic production deployment

### Track B — Production Pilot

Purpose: run safely with one real team and one low-risk service.

Timeline: 8–12 weeks.

Scope:

- AWS landing zone (or a managed equivalent)
- Isolated sandbox account/namespace
- Read-only production access for the agent
- GitOps deployment
- Canary and automatic rollback
- Full approval workflow
- Security review
- SLOs and on-call runbook
- Load and chaos testing

### Track C — Production Platform

Timeline: 4–6 months.

Adds:

- Multi-tenant enterprise isolation
- HA and disaster recovery
- Full RBAC/SSO
- Cost controls and quotas
- Compliance programme
- Advanced analytics and continuous learning

---

## 4. Revised 10-Day MVP Plan

This is a realistic version of the original plan for one developer.

| Day | Objective | Deliverables | Exit criteria |
|---|---|---|---|
| 1 | Scope and risk | One-page scope, risk matrix, demo scenario, success metrics | Stakeholders agree on what is in/out |
| 2 | Database and tenancy | `tenants`, `users`, `rulebooks`, `incidents`, `audit_logs`, `fix_outcomes`; `pgvector`; seed two tenants | Tenant-filtered queries work; cross-tenant test fails safely |
| 3 | Auth and tenant isolation | JWT or API-key auth, roles, tenant resolution, isolation tests | No tenant can read another tenant’s data |
| 4 | Rulebook API and embeddings | CRUD for tenant rulebooks; chunking; embedding generation; re-index on update | Create/update/delete/search rulebooks works |
| 5 | RAG + real alert ingestion | Tenant-filtered vector search; one real alert source; normalize/dedupe | A real alert becomes a tenant-scoped incident |
| 6 | Agent + report | LangGraph integration, confidence/validation, structured report | Report contains evidence, fix, risk, rollback |
| 7 | Notifications + approval | Email/Slack delivery; signed expiring approval link; approval audit | Developer receives report and can approve/reject |
| 8 | Sandbox execution | Allowlisted actions; Docker/fake sandbox; post-checks; rollback | Approved fix runs only in sandbox; audit row written |
| 9 | Testing and failure paths | Unit smoke tests, E2E test, invalid-token test, duplicate-alert test, sandbox-failure test | Happy path and key failure paths pass |
| 10 | Deployment and rehearsal | Deploy to chosen free host; Ngrok/public URL; demo script; FAQ; fallback recording | Full demo runs twice without manual repair |

If a day slips, cut scope in this order:

1. Slack — keep email only.
2. Second tenant — keep one tenant plus isolation test.
3. Second incident class — keep one.
4. pgvector — use simple keyword search for the demo, but document the gap.
5. Docker sandbox — use fake sandbox and clearly label it.

Do not cut:

- Approval
- Audit trail
- Tenant isolation test
- Report
- Demo fallback

---

## 5. Production Roadmap

### Phase 0 — Requirements and Risk (1 week)

- Define incident classes and allowed actions.
- Define approval matrix and autonomy level.
- Define SLOs and success metrics.
- Define data retention and compliance scope.
- Choose build vs buy for LLM, RAG, monitoring, and approvals.

### Phase 1 — Production Hardening (2–3 weeks)

- Secrets Manager / environment configuration.
- Structured logging, correlation IDs, OpenTelemetry.
- Replace RQ/Redis queue with SQS + DLQ (or managed queue).
- Idempotency, retries, timeouts, rate limits.
- Alembic migrations and connection pooling.
- LLM abstraction, prompt versioning, structured-output repair.
- Unit, integration, contract, and security tests in CI.

### Phase 2 — AWS Platform (2 weeks)

Recommended pilot stack:

- ECS Fargate for API and workers (simpler than EKS for a small team).
- Application Load Balancer or API Gateway.
- Aurora PostgreSQL Multi-AZ.
- ElastiCache Redis for cache/rate limiting only.
- SQS + DLQ for jobs.
- S3 for reports and evidence.
- Secrets Manager and KMS.
- CloudWatch, X-Ray, OpenTelemetry.
- Bedrock for production LLM.
- SES for email; Slack app for interactive approvals.

Use EKS + Argo CD only if Kubernetes is already an organisational standard.

### Phase 3 — Real Monitoring and Alert Ingestion (2 weeks)

- CloudWatch alarms → EventBridge → SQS.
- Prometheus Alertmanager → webhook.
- PagerDuty/Sentry/Datadog adapters.
- Normalize alerts into one schema.
- Dedupe, group, rate-limit, and route by tenant/service.
- Dead-letter queue and replay tooling.

### Phase 4 — Agent Runtime and Knowledge (2–3 weeks)

- LangGraph workers consuming SQS.
- Bedrock model with guardrails.
- Tenant-scoped RAG with pgvector or OpenSearch.
- Evidence collection from logs, metrics, traces, deployments.
- Risk classification and confidence calibration.
- Checkpoint persistence in Aurora.
- Prompt-injection and PII defenses.

### Phase 5 — Isolated Sandbox and Policy (2–3 weeks)

- Separate AWS account or isolated EKS namespace.
- No production write credentials in the agent.
- Read-only production access.
- Terraform plan / Kubernetes manifest generation.
- Policy-as-code: OPA, Conftest, Checkov.
- Block privileged containers, host mounts, public buckets, broad IAM.
- Sandbox evidence and logs retained.

### Phase 6 — Reporting and Approval (1–2 weeks)

- Structured report with evidence, root cause, fix, blast radius, risk,
  rollback, sandbox results, confidence, and cost.
- SES email with signed, expiring, one-time approval links.
- Slack/Teams interactive approval.
- RBAC and approval quorum.
- Immutable audit trail.

### Phase 7 — GitOps Deployment (2–3 weeks)

- Agent creates a branch/PR, not a production command.
- CI runs tests, security scans, and policy checks.
- Human approval.
- Argo CD or CodeDeploy applies the change.
- Canary/blue-green rollout.
- SLO verification and automatic rollback.

### Phase 8 — Shadow Pilot (2–4 weeks)

- Agent diagnoses and proposes; humans act.
- Compare with actual fixes.
- Measure false positives, accuracy, and approval latency.
- Tune prompts, retrieval, and thresholds.

### Phase 9 — Limited Production (2–3 weeks)

- One service, one incident class, one approval group.
- Expand only after stable metrics.

---

## 6. Multi-Tenancy Design

### Recommended MVP model

Shared database, shared schema, `tenant_id` on every row, enforced by:

- Application-level tenant resolution
- PostgreSQL Row-Level Security (RLS) where possible
- Automated cross-tenant tests
- Tenant-scoped vector search filters

### Production options

| Model | Isolation | Complexity | Recommendation |
|---|---|---|---|
| Shared schema + `tenant_id` + RLS | Medium | Low | MVP and small SaaS |
| Schema per tenant | High | Medium | Enterprise |
| Database per tenant | Highest | High | Regulated customers |

Never rely only on the agent prompt to enforce tenancy.

### Required tables

- `tenants`
- `users`
- `memberships` / roles
- `rulebooks`
- `rulebook_chunks` / embeddings
- `alerts`
- `incidents`
- `approvals`
- `execution_logs`
- `audit_logs`
- `fix_outcomes`
- `checkpoints`

---

## 7. RAG Design

- Chunk rulebooks by heading and size.
- Store `tenant_id`, document version, source, and checksum.
- Re-embed on update; soft-delete old versions.
- Use pgvector with HNSW or IVFFlat.
- Apply tenant filter in SQL, not after retrieval.
- Re-rank results before sending to the LLM.
- Keep citations in the report.
- Evaluate retrieval quality with a fixed question/answer set.
- Fallback to generic runbooks only when explicitly allowed.

---

## 8. Execution and Safety Model

### Autonomy ladder

| Level | Behaviour |
|---|---|
| L0 | Observe only |
| L1 | Diagnose and recommend |
| L2 | Sandbox-validate and open a PR/report |
| L3 | Auto-approve low-risk reversible actions after policy checks |
| L4 | Fully automated remediation for a narrow allowlist |

Start at L1/L2. Do not start at L4.

### Execution rules

- Agent has no production write credentials.
- Production access is read-only.
- Sandbox is a separate account/namespace.
- Only allowlisted actions are executable.
- Every action has a timeout, idempotency key, and post-check.
- Every action has a rollback plan or is blocked.
- High-risk actions require two approvers.
- Production changes go through GitOps/CI-CD.
- Canary and automatic rollback on SLO breach.

### Approval rules

- Signed, expiring, one-time tokens.
- RBAC: viewer, responder, approver, admin.
- Email via SES, Slack/Teams interactive buttons.
- No approval by replying “yes” to a plain email.
- Full audit of who approved what and when.
- Separation of duties for high-risk changes.

---

## 9. Testing Strategy

### MVP

- Unit tests for catalog, validation, confidence, approval, executor.
- Integration tests for webhook → queue → worker → approval.
- Tenant isolation tests.
- Invalid/expired approval token tests.
- Duplicate alert and rate-limit tests.
- Sandbox failure and rollback tests.
- One end-to-end demo test.

### Production pilot

- Contract tests for alert sources.
- Load tests for alert bursts.
- Chaos tests: Redis down, DB failover, LLM timeout, worker crash.
- Security tests: auth bypass, tenant escape, prompt injection, SSRF.
- Replay tests with historical incidents.
- Shadow-mode accuracy evaluation.

---

## 10. Observability and SLOs

Monitor the platform and the agent:

- Alert ingestion latency
- Queue depth and DLQ count
- Agent latency and token cost
- LLM error/timeout rate
- Approval latency
- Sandbox success rate
- Execution success rate
- Rollback rate
- False-positive rate
- MTTD and MTTR
- Tenant-level error and cost budgets

Define SLOs before the pilot. Example:

- 99.9% webhook availability
- P95 alert-to-incident < 30 seconds
- P95 report generation < 2 minutes
- Zero cross-tenant data access

---

## 11. Cost Reality

The “$0/month” claim is valid only for a local/demo setup.

Free-tier caveats:

- Oracle Always Free capacity is not guaranteed and can be reclaimed.
- Ngrok free has limits and changing URLs.
- Gmail SMTP has sending limits and deliverability issues.
- CloudWatch free tier is limited.
- Local LLM inference costs engineering time and latency.

Production costs include:

- Compute (ECS/EKS)
- Managed Postgres
- Redis/ElastiCache
- SQS/S3
- Bedrock tokens
- SES/Slack
- Observability
- Backups/DR
- Security review
- On-call/engineering time

Document a monthly cost estimate before the pilot.

---

## 12. Key Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Agent suggests dangerous fix | Allowlist, sandbox, policy checks, human approval |
| Cross-tenant leak | RLS, tenant-scoped queries, automated isolation tests |
| LLM hallucination | RAG citations, structured output validation, confidence thresholds |
| Approval bypass | Signed one-time tokens, RBAC, audit, quorum |
| Production outage from fix | GitOps, canary, automatic rollback, blast-radius limits |
| Free-tier instability | Treat as demo only; production on paid/managed services |
| Queue loss | SQS + DLQ + idempotency |
| Secret leakage | Secrets Manager, redaction, least privilege |
| Prompt injection | Treat logs/rulebooks as untrusted, separate instructions from data |
| Cost overrun | Token budgets, per-tenant quotas, alerts |

---

## 13. Decisions Required Before Day 1

1. **Hosting:** local demo, Oracle Always Free, or AWS free tier?
2. **LLM:** local Ollama only for demo, or Bedrock for production?
3. **Tenant isolation:** shared schema + RLS or schema-per-tenant?
4. **Auth:** JWT/OIDC or API keys for the MVP?
5. **Approval channel:** email only, Slack only, or both?
6. **Execution scope:** fake sandbox, Docker sandbox, or isolated AWS sandbox?
7. **Autonomy:** L1/L2 only for the pilot?
8. **Compliance:** is SOC2/ISO actually required, or is auditability enough for now?
9. **Success metrics:** what baseline and target values will stakeholders accept?
10. **Demo fallback:** recorded video or secondary environment?

---

## 14. Final Recommendation

Proceed with the 10-day plan **only as an MVP/demo**, with narrowed scope and
explicitly non-production execution.

Do not claim:

- “Production-ready in 10 days”
- “$0/month production”
- “80% automated resolution” before measurement
- “SOC2/ISO-ready” without a compliance programme

The safest path is:

1. **10-day MVP** — one tenant, one incident class, one real alert source,
   sandbox/fake execution, signed approval, report, audit, demo.
2. **8–12 week production pilot** — AWS, isolated sandbox, GitOps, canary,
   rollback, security review, SLOs.
3. **4–6 month production platform** — multi-tenant hardening, HA/DR,
   compliance, cost controls, broader automation.

This gives stakeholders a working demo quickly without overstating production
readiness or exposing production systems to unsafe automation.
