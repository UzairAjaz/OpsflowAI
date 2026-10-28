# OpsFlow AI — Consolidated Final Implementation Plan

**Multi-Tenant Autonomous IT Remediation System**

| Field | Details |
|---|---|
| Document | OpsFlow AI — Consolidated Final Implementation Plan |
| Version | 4.0 (Consolidated) |
| Date | 2026-10-28 |
| Author | Uzair Ajaz |
| Reviewer | Naveed Bhai (Solution Architect) |
| Status | Draft for approval |
| Scope | Pilot-Ready MVP + Production Roadmap |
| Implementation status | Planning only — no code included in this document |

---

## 0. Source Inputs

This document reconciles the following inputs:

| Source | Contribution |
|---|---|
| User-provided v3.0 Final Implementation Document | 10-day plan, workflow, RAG design, demo narrative, business case |
| `PHASE_2_BUILD_PLAN.md` (repository history) | 37 build steps (P2-01…P2-37), 6-week tracks T1–T6 |
| `PHASE_2_IMPLEMENTATION_PLAN.md` (repository history) | 7-layer architecture, 6-week roadmap, OKRs, risk register |
| `NOTES.md` (repository history) | Phase 1 concept and step ledger |
| `deploy/GO_LIVE_CHECKLIST.md` | Production go-live controls |
| `docs/OPSFLOW_PRODUCTION_PLAN.md` | Production-readiness assessment and roadmap |
| Current codebase (October 2026) | Actual implemented capabilities and gaps |
| User’s final v3.0 document | Scope disclaimer, demo script, appendices |

### Key reconciliation result

The v3.0 document is correct to label the 10-day deliverable a **Pilot-Ready MVP**, but several implementation details must be aligned with the actual repository:

- The project currently uses **qwen2.5:3b**; the 7B model was removed.
- The current database does **not yet** contain `tenants`, `users`, `rulebooks`, `audit_logs`, or pgvector embeddings.
- Current RAG is adapter-based (`tenant_http`, `fake`, history, web), not pgvector.
- Current authentication is HMAC webhook signing plus tenant API keys; JWT/RBAC is planned.
- The executor is currently mock/simulated; production execution is a future deliverable.
- Canary is no longer a graph node; production canary is a deployment concern.
- Audit events exist in graph state/execution logs; a dedicated immutable `audit_logs` table is planned.

---

## 1. Executive Summary

OpsFlow AI detects incidents, diagnoses root causes using an LLM plus tenant-specific knowledge, proposes a remediation, validates it in an isolated sandbox, produces a structured report, requests human approval, and then executes or hands off the change through a controlled deployment path.

### Scope disclaimer

> The 10-day deliverable is a **Pilot-Ready MVP / Proof of Concept**, not a production-ready system.  
> Production requires a separate 8–12 week pilot with security hardening, high availability, real sandbox isolation, GitOps, canary deployment, and compliance controls.

### Roadmap

| Phase | Duration | Goal | Environment |
|---|---:|---|---|
| Phase 1 — MVP / Demo | 10 days | Validate workflow, RAG, sandbox, approval, audit | Local / Oracle Free / Ngrok |
| Phase 2 — Production Pilot | 8–12 weeks | One service, real alerts, isolated sandbox, GitOps, canary | AWS |
| Phase 3 — Full Platform | 4–6 months | Multi-tenant hardening, HA/DR, compliance, broader autonomy | Enterprise AWS |

### Corrected claims from v3.0

| v3.0 statement | Correct position |
|---|---|
| “Production-ready” | Pilot-ready MVP; production needs 8–12+ weeks |
| “$0/month” | $0 infrastructure for demo; production has real costs |
| “Llama 3.1 8B / Qwen 2.5 7B” | Current project uses `qwen2.5:3b`; 7B was removed |
| “JWT-based authentication” | Planned; current approval API uses tenant API keys |
| “pgvector RAG” | Planned; current implementation uses knowledge adapters |
| “Audit logs table” | Current audit events + execution logs; dedicated table planned |
| “Executes fixes in production” | MVP uses simulated/fake sandbox; production uses GitOps |
| “Canary node” | Canary is a deployment strategy, not a graph node |
| “98% MTTR improvement” | Target; must be measured against a baseline |
| “SOC2/ISO-ready” | Not yet; requires a compliance programme |

---

## 2. Current State (October 2026)

### Implemented

- FastAPI webhook with HMAC-SHA256 verification.
- Alert normalization, deduplication, rate limiting.
- LangGraph flow: intake → analyze → research → propose → critic → score → risk → sandbox → approval → executor.
- PostgreSQL persistence for incidents, alerts, execution logs, fix outcomes, checkpoints.
- Redis/RQ worker queue.
- Tenant-scoped fields on incidents and alerts.
- Knowledge adapters: tenant HTTP KB, fake KB, history, web search.
- Remediation catalog with Docker actions and simulated code actions:
  - `run_python_script`
  - `execute_ssh_command`
  - `flush_redis_cache`
- Sandbox backends: Docker, local, fake.
- Human approval via LangGraph `interrupt()` and signed tokens.
- Approval CLI (`approve_pending.py`) and API routes.
- Notification adapters: Slack, email, SMS, console.
- Markdown incident reports.
- Observability scaffolding: structured logging, metrics, tracing.
- Worker entrypoints for escalation and feedback.
- Legacy canary modules and Argo manifests, not connected to the main graph.

### Not yet production-ready

| Capability | Current state | Required work |
|---|---|---|
| Tenant/user model | `tenant_id` fields only | `tenants`, `users`, memberships, RBAC, JWT/OIDC |
| Tenant isolation | Application filtering | PostgreSQL RLS or schema-per-tenant + isolation tests |
| Rulebook CRUD | Not implemented | API, versioning, embeddings, re-indexing |
| pgvector RAG | Not implemented | pgvector schema, embedding service, tenant-filtered search |
| Dedicated audit log | Graph audit + execution logs | Immutable `audit_logs` table and retention policy |
| Production execution | Mock/simulated | Isolated sandbox, allowlist, SSM/GitOps, rollback |
| Real alert integrations | Generic webhook | CloudWatch/SNS/EventBridge, Prometheus, PagerDuty adapters |
| Queue | Redis/RQ | SQS + DLQ for production |
| Deployment | Local/Docker | IaC, CI/CD, ECS/EKS, secrets, HA |
| Testing | Integration scripts | Unit, contract, security, load, chaos suites |
| LLM | Local `qwen2.5:3b` | Bedrock/managed LLM or GPU-backed model for production |
| Observability | Local logging/metrics | CloudWatch/X-Ray/OTel/Grafana, SLOs |
| Cost controls | Not implemented | Token budgets, tenant quotas, alerts |

---

## 3. Target Architecture

### Logical flow

```text
CloudWatch / Prometheus / PagerDuty / Sentry
                    │
                    ▼
        EventBridge / Webhook API
                    │
                    ▼
        Normalize + dedupe + rate limit
                    │
                    ▼
              SQS + DLQ
                    │
                    ▼
        LangGraph Agent Workers (ECS/EKS)
          │          │            │
          ▼          ▼            ▼
       Bedrock   Aurora/      S3 evidence
         LLM     Postgres      + reports
          │
          ▼
   Isolated sandbox account / namespace
          │
          ▼
   Structured report + proposed change
          │
          ▼
   Approval: SES / Slack / Teams / PagerDuty
          │
          ▼
   GitOps PR → CI → approval → Argo/CodeDeploy
          │
          ▼
   Canary / blue-green → verify SLOs → promote/rollback
```

### AWS pilot mapping

| Layer | Recommended service |
|---|---|
| API | ECS Fargate + ALB or API Gateway |
| Workers | ECS Fargate service |
| Queue | SQS + DLQ |
| Database | Aurora PostgreSQL Multi-AZ |
| Cache | ElastiCache Redis |
| Reports/evidence | S3 |
| LLM | Bedrock |
| Embeddings | Bedrock Titan or GPU-hosted embedding model |
| Vector search | pgvector on Aurora or OpenSearch |
| Secrets | Secrets Manager + KMS |
| Observability | CloudWatch, X-Ray, OpenTelemetry, Grafana |
| Email | SES |
| Chat approvals | Slack app or Teams bot |
| Deployment | GitHub Actions + Argo CD or CodeDeploy |
| Sandbox | Separate AWS account or isolated EKS namespace |

For a small team, ECS Fargate is simpler than EKS. Use EKS + Argo CD only if Kubernetes is already the organisational standard.

---

## 4. Multi-Tenancy and RAG

### Target data model

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

### Isolation options

| Model | Isolation | Complexity | Use |
|---|---|---|---|
| Shared schema + `tenant_id` + RLS | Medium | Low | MVP and small SaaS |
| Schema per tenant | High | Medium | Enterprise |
| Database per tenant | Highest | High | Regulated customers |

For the MVP, use shared schema + `tenant_id` + strict application checks. For Phase 2, add PostgreSQL Row-Level Security and automated cross-tenant tests.

### RAG ingestion

1. Developer submits Markdown/JSON rulebook.
2. Validate tenant membership and permissions.
3. Chunk by heading and size.
4. Generate embeddings.
5. Store content, metadata, tenant ID, version, checksum, and embedding.
6. Re-embed on update; retain version history.
7. Soft-delete old versions.

### RAG retrieval

- Apply tenant filter in SQL, not after retrieval.
- Use cosine similarity with pgvector.
- Re-rank results.
- Include citations in the report.
- Fall back to generic knowledge only when explicitly allowed.
- Evaluate retrieval quality with a fixed question set.

---

## 5. Workflow and Safety Model

### End-to-end workflow

| Step | Action | Current state |
|---|---|---|
| 1 | Monitoring detects incident | Webhook exists; adapters planned |
| 2 | HMAC-verified alert ingestion | Implemented |
| 3 | Dedupe/rate limit and incident creation | Implemented |
| 4 | AI diagnosis + tenant RAG | Partially implemented |
| 5 | Catalog-constrained proposal | Implemented |
| 6 | Sandbox validation | Implemented with fake/Docker sandbox |
| 7 | Structured report | Implemented as Markdown |
| 8 | Notification with approval link | Partially implemented |
| 9 | Human approval | Implemented |
| 10 | Execution/audit | Mock/simulated in MVP; production GitOps planned |

### Autonomy ladder

| Level | Behaviour | When to use |
|---|---|---|
| L0 | Observe only | Initial deployment |
| L1 | Diagnose and recommend | MVP / shadow mode |
| L2 | Sandbox-validate and open PR/report | Production pilot |
| L3 | Auto-approve low-risk reversible actions | Later, with evidence |
| L4 | Fully automated narrow allowlist | Only after long stability period |

Start at L1/L2. Do not start with automatic production remediation.

### Execution rules

- Agent has no production write credentials.
- Production access is read-only.
- Sandbox runs in a separate account or isolated namespace.
- Only allowlisted actions can execute.
- Every action has a timeout, idempotency key, post-check, and rollback plan.
- High-risk actions require two approvers.
- Production changes go through GitOps/CI-CD.
- Canary and automatic rollback on SLO breach.

### Approval rules

- Signed, expiring, one-time tokens.
- RBAC: viewer, responder, approver, admin.
- Email via SES; Slack/Teams interactive buttons.
- No approval by replying “yes” to a plain email.
- Full audit of actor, time, decision, and evidence.
- Separation of duties for high-risk changes.

---

## 6. 10-Day MVP Plan

| Day | Objective | Deliverables | Exit criteria |
|---|---|---|---|
| 1 | Scope and risk | One-page scope, risk matrix, demo scenario, baseline metrics | Stakeholders agree on in/out of scope |
| 2 | Database and tenancy | `tenants`, `users`, `rulebooks`, `incidents`, `audit_logs`, `fix_outcomes`; pgvector; two demo tenants | Tenant-filtered queries work; cross-tenant test fails safely |
| 3 | Auth and isolation | JWT or API-key auth, roles, tenant resolution, isolation tests | No tenant can read another tenant’s data |
| 4 | Rulebook API | CRUD, chunking, embeddings, re-index, tenant scoping | Create/update/delete/search works |
| 5 | RAG + real alert | Tenant-filtered vector search; one real alert source; normalize/dedupe | Real alert becomes tenant-scoped incident |
| 6 | Report + notification | Structured report; SES/Slack delivery; signed approval link | Developer receives report and can act |
| 7 | Approval hardening | RBAC, one-time tokens, audit, rejection path | Only authorized users can approve/reject |
| 8 | Sandbox execution | Allowlist, fake/Docker sandbox, post-checks, rollback | Approved fix runs only in sandbox; audit row written |
| 9 | Testing | Smoke, E2E, invalid token, duplicate alert, sandbox failure, isolation tests | Happy path and key failure paths pass |
| 10 | Demo deployment | Chosen free host, public URL, demo script, FAQ, fallback recording | Demo runs twice without manual repair |

### Scope cuts if a day slips

1. Slack — keep email only.
2. Second tenant — keep one tenant plus isolation test.
3. Second incident class — keep one.
4. pgvector — use keyword search, document the gap.
5. Docker sandbox — use fake sandbox and label it clearly.

Do not cut: approval, audit, tenant isolation test, report, demo fallback.

### MVP definition of done

- One real alert source creates an incident.
- Tenant-specific knowledge is retrieved with zero cross-tenant leakage.
- The agent proposes only catalog actions with validated parameters.
- Sandbox validation runs and is recorded.
- A structured report is generated.
- A signed approval link is delivered.
- Approval resumes the graph and executes only after approval.
- Audit trail contains the full timeline.
- Demo can be repeated reliably.

---

## 7. Production Pilot (8–12 Weeks)

| Weeks | Theme | Key deliverables | Exit criteria |
|---|---|---|---|
| 1–2 | Production hardening | Secrets, logging, tracing, SQS/DLQ, retries, idempotency, CI tests | App runs without local-only dependencies |
| 3–4 | AWS foundation | VPC, ECS/EKS, Aurora, ElastiCache, S3, IAM, KMS | Staging deployed entirely through IaC |
| 5–6 | Monitoring and ingestion | CloudWatch/EventBridge, Prometheus, PagerDuty adapters, DLQ | Real staging alarm creates incident |
| 7–8 | Agent and RAG | Bedrock, tenant RAG, evidence collection, confidence, checkpoints | Complete diagnosis/report for real staging incident |
| 9–10 | Sandbox and policy | Isolated account/namespace, Terraform plan, OPA/Conftest/Checkov | Fix validated without production writes |
| 11 | Approval and reporting | SES/Slack signed approvals, RBAC, audit, report storage | Engineer and manager can approve/reject audibly |
| 12 | GitOps and shadow pilot | PR workflow, canary, rollback, shadow evaluation | One real fix through pipeline; rollback tested |

### Production pilot guardrails

- Agent read-only in production.
- Sandbox credentials cannot reach production.
- GitOps only; no direct production shell.
- Canary/blue-green with automatic rollback.
- Security review before real traffic.
- On-call runbook and incident response plan.

---

## 8. Full Platform (4–6 Months)

Add:

- Multi-tenant enterprise isolation (RLS or database-per-tenant).
- SSO/OIDC and advanced RBAC.
- HA and disaster recovery.
- Multi-region or multi-AZ deployment.
- SOC2/ISO control programme.
- Cost controls and tenant chargeback.
- Advanced analytics and continuous learning.
- Broader autonomy for low-risk actions.
- Marketplace of vetted runbooks.

---

## 9. Testing and Quality

### MVP

- Unit tests for catalog, validation, confidence, approval, executor.
- Integration tests for webhook → queue → worker → approval.
- Tenant isolation tests.
- Invalid/expired approval token tests.
- Duplicate alert and rate-limit tests.
- Sandbox failure and rollback tests.
- End-to-end demo test.

### Production pilot

- Contract tests for alert sources.
- Load tests for alert bursts.
- Chaos tests: Redis down, DB failover, LLM timeout, worker crash.
- Security tests: auth bypass, tenant escape, prompt injection, SSRF.
- Replay tests with historical incidents.
- Shadow-mode accuracy evaluation.

---

## 10. Observability and SLOs

Track:

- Alert ingestion latency.
- Queue depth and DLQ count.
- Agent latency and token cost.
- LLM error/timeout rate.
- Approval latency.
- Sandbox success rate.
- Execution success rate.
- Rollback rate.
- False-positive rate.
- MTTD and MTTR.
- Tenant-level error and cost budgets.

Example SLOs:

- 99.9% webhook availability.
- P95 alert-to-incident < 30 seconds.
- P95 report generation < 2 minutes.
- Zero cross-tenant data access.

---

## 11. Security and Compliance

- Least-privilege IAM.
- Separate production and sandbox accounts.
- No production write credentials in the agent.
- Secrets Manager and KMS.
- HMAC verification for webhooks.
- Signed, expiring, one-time approval tokens.
- RBAC and separation of duties.
- PII redaction before LLM calls.
- Prompt-injection defenses.
- Tenant isolation tests.
- Encrypted data at rest and in transit.
- Audit retention policy.
- Backup and disaster recovery.
- Compliance programme separate from engineering.

---

## 12. Deployment and Rollback

### MVP

- Local Docker Compose or a single free VM.
- Ngrok for public demo URL.
- Fake or Docker sandbox.
- Manual approval CLI/API.

### Production

```text
Agent creates PR
   → CI: tests, security, policy checks
   → Human approval
   → Argo CD / CodeDeploy
   → Canary 10% → 25% → 50% → 100%
   → SLO verification
   → Promote or automatic rollback
```

Rollback must be tested before enabling production traffic.

---

## 13. Cost Model

### MVP

- Local: $0 infrastructure, but engineering time is not free.
- Oracle Always Free: $0 infrastructure, with availability and capacity caveats.
- Ngrok free: $0, with URL and bandwidth limits.
- Gmail SMTP: free but limited deliverability.

### Production pilot

Estimate and budget for:

- Compute (ECS/EKS).
- Aurora PostgreSQL.
- ElastiCache.
- SQS/S3.
- Bedrock tokens.
- SES/Slack.
- Observability.
- Backups/DR.
- Security review.
- On-call/engineering time.

The v3.0 “$0/month” claim should be limited to the demo.

---

## 14. KPIs and Business Case

| Metric | MVP target | Production pilot target |
|---|---|---:|
| MTTR | 2–5 minutes with approval | < 2 minutes for low-risk |
| False positives | < 10% | < 5% |
| Auto-diagnosis | > 70% | > 85% |
| Approval latency | < 5 minutes | < 2 minutes |
| Engineer time saved | ~5 hours/week | ~10 hours/week |
| Tenant isolation incidents | 0 | 0 |
| Change failure rate | Measure baseline | No increase |
| Rollback rate | Measure baseline | < 5% |

All targets must be measured against a baseline, not presented as guaranteed outcomes.

---

## 15. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Wrong fix | Catalog, validation, sandbox, human approval |
| Cross-tenant leak | RLS, tenant-scoped queries, isolation tests |
| LLM hallucination | RAG citations, structured output, confidence thresholds |
| Approval bypass | Signed one-time tokens, RBAC, audit, quorum |
| Production outage | GitOps, canary, automatic rollback, blast-radius limits |
| Free-tier instability | Demo only; production on managed services |
| Queue loss | SQS + DLQ + idempotency |
| Secret leakage | Secrets Manager, redaction, least privilege |
| Prompt injection | Untrusted-data framing, separate instructions from data |
| Cost overrun | Token budgets, tenant quotas, cost alerts |
| Model quality | Evaluation harness, fallback model, human review |

---

## 16. Decisions Required

1. Hosting: local, Oracle Free, or AWS free tier for the MVP?
2. LLM: local `qwen2.5:3b` for demo, Bedrock for production?
3. Tenant isolation: shared schema + RLS or schema-per-tenant?
4. Auth: JWT/OIDC or API keys for the MVP?
5. Approval channel: email, Slack, or both?
6. Execution scope: fake sandbox, Docker sandbox, or isolated AWS sandbox?
7. Autonomy: L1/L2 only for the pilot?
8. Compliance: is SOC2/ISO required, or is auditability enough for now?
9. Success metrics: what baseline and targets will stakeholders accept?
10. Demo fallback: recorded video or secondary environment?

---

## 17. Demo Script and Q&A

### Opening

> “This is a pilot-ready MVP, not a production system. It detects an incident, diagnoses it with tenant-specific knowledge, validates the fix in a sandbox, generates a report, and waits for human approval before execution.”

### Live demo

1. Send an alert.
2. Show HMAC verification and incident creation.
3. Show tenant-specific RAG results.
4. Show diagnosis and proposed fix.
5. Show sandbox validation.
6. Show report and approval prompt.
7. Approve manually.
8. Show execution result and audit trail.

### Closing

> “The 10-day MVP proves the workflow. The 8–12 week pilot adds AWS isolation, GitOps, canary, rollback, security, and compliance controls.”

### Q&A

**What if the AI is wrong?**  
The agent can only choose catalog actions, parameters are validated, the fix runs in a sandbox, and a human approves.

**Does the AI have production access?**  
In the MVP, execution is simulated/fake. In production, the agent has read-only production access and changes go through GitOps.

**How is tenant data isolated?**  
Tenant ID filtering now; PostgreSQL RLS or schema-per-tenant in Phase 2, with automated isolation tests.

**What if the system crashes?**  
LangGraph checkpoints persist state in PostgreSQL; workers resume from the checkpoint.

**How do you prevent hallucination?**  
RAG citations, catalog constraints, Pydantic validation, sandbox validation, confidence thresholds, and human approval.

---

## 18. Final Recommendation

Approve the 10-day plan as a **pilot-ready MVP** with narrowed scope.

Do not claim production readiness, $0 production cost, or measured MTTR improvements before the pilot.

The safest path is:

1. **10-day MVP** — one tenant, one incident class, one real alert source, sandbox/fake execution, signed approval, report, audit, demo.
2. **8–12 week production pilot** — AWS, isolated sandbox, GitOps, canary, rollback, security review, SLOs.
3. **4–6 month production platform** — multi-tenant hardening, HA/DR, compliance, cost controls, broader autonomy.

---

## Appendix A — Ten Use Cases

| # | Service | Incident | Proposed action |
|---|---|---|---|
| 1 | payment-api | OOMKilled | `increase_memory_limit` → 2Gi |
| 2 | inventory-service | Disk full | `run_python_script` → cleanup |
| 3 | auth-service | DB pool exhausted | restart + flush Redis |
| 4 | order-service | Redis cache full | `flush_redis_cache` |
| 5 | notification-service | CrashLoopBackOff | `restart_container` |
| 6 | analytics-worker | High CPU | run cache-clear script |
| 7 | api-gateway | Nginx 502 | restart backend service |
| 8 | user-service | Stale cache | flush Redis pattern |
| 9 | billing-service | API timeout | restart + reset config |
| 10 | tenant worker | Tenant isolation issue | restart tenant-specific container |

## Appendix B — Glossary

| Term | Meaning |
|---|---|
| MTTD / MTTR | Mean time to detect / resolve |
| HITL | Human-in-the-loop |
| RAG | Retrieval-Augmented Generation |
| RLS | PostgreSQL Row-Level Security |
| GitOps | Deployment through Git-based declarative state |
| Canary | Progressive rollout to a subset of traffic |
| DLQ | Dead-letter queue |
| SLO | Service-level objective |
| RBAC | Role-based access control |
| PoC / MVP | Proof of concept / minimum viable product |

## Appendix C — Related Documents

- `docs/OPSFLOW_PRODUCTION_PLAN.md` — production-readiness assessment
- `PHASE_2_BUILD_PLAN.md` — 37-step build plan (repository history)
- `PHASE_2_IMPLEMENTATION_PLAN.md` — 7-layer Phase 2 plan (repository history)
- `deploy/GO_LIVE_CHECKLIST.md` — production go-live controls
- User-provided v3.0 Final Implementation Document
