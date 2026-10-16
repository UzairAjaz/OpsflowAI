# OpsFlow AI — Phase 2 Implementation Plan

**From a Manual CLI Agent to an Automated, Closed-Loop Remediation Platform**

| Field | Detail |
| --- | --- |
| Document Owner | [Your Name], AI/ML Engineer |
| Reviewers | Engineering Manager, CTO, Platform / SRE Leads |
| Version | 1.1 — Multi-Tenant Knowledge Update |
| Date | 13 Oct 2026 |
| Status | Proposed (pending CTO approval) |
| Audience | Senior Management & Technical Leadership |
| Related Work | OpsFlow Phase 1 (10/21 steps verified) |

---

## 1. Executive Summary

OpsFlow AI today is a **working, safety-first, single-operator CLI agent**: it redacts secrets, produces an evidence-backed diagnosis, researches fixes, self-corrects through an adversarial critic, pauses for human approval on risky actions, and executes only vetted catalog commands. Phase 2 evolves it into a **fully automated, event-driven, self-healing remediation platform** that detects incidents on its own, diagnoses with tenant-aware + external knowledge, validates every fix in a sandbox, rolls it out via canary, and learns from outcomes — while keeping a human in the loop only where it matters.

**Business impact:** MTTD from ~15 min → **~0 s**, MTTR from ~2 h → **~15 min**, auto-resolution from 0% → **~70%**, and **zero** production risk from bad fixes (sandbox + canary + auto-rollback).

**At a glance**

| Dimension | Phase 1 (Today) | Phase 2 (Target) |
| --- | --- | --- |
| Trigger | Manual (user pastes logs) | Event-driven (webhooks) |
| Knowledge | Web search only | Multi-tenant KB + live connectors + web + history |
| Execution | Dry-run mock | Sandbox validation → canary rollout |
| Approval | Terminal y/n | Slack button (durable, restart-safe) |
| State | In-memory (lost on restart) | PostgreSQL (durable) |
| Observability | Basic logs | Tracing + metrics + auto reports |
| Adaptivity | Static heuristics | Learns from fix outcomes |

---

## 2. Current Architecture (Phase 1 — Baseline)

OpsFlow Phase 1 is a LangGraph state machine running locally on `qwen2.5:7b` (Ollama). The verified pipeline:

```
START → intake → analyzer → researcher ⇄ critic → risk ─┬─ safe ─────→ executor → END
                                                        ├─ await ─→ approval ─ y ─→ executor
                                                        │                    └ n ─→ END
                                                        └─ reject ─→ END
```

**Verified components**

| Component | File | Responsibility | Safety Property |
| --- | --- | --- | --- |
| Intake | `intake.py` | Regex redaction of secrets/PII before any LLM call | Defense-in-depth |
| Analyzer | `analyzer.py` | Pydantic-typed diagnosis + severity rubric | Structured, evidence-grounded |
| Research | `web_search.py` | DuckDuckGo `@tool`, citations | Untrusted data, never instructions |
| Critic | `critic.py` | Adversarial scoring, `route_after_critic` (accept/refine/escalate) | Self-correction with cap |
| Risk | `risk.py` | Catalog validation + authoritative risk | No freeform risk guessing |
| Approval | `approval.py` | LangGraph `interrupt()` + `Command(resume=...)` | Human-in-the-loop |
| Executor | `executor.py` | Catalog template → array argv (`shell=False`), dry-run | No raw shell |
| Catalog | `remediations.yaml` | Vetted actions, params, allowlists | Constrained action space |
| State | `state.py` | Typed shared state + reducers + audit | Append-only audit |

**Verified capabilities:** structured diagnosis, grounded research, self-correction loop (max 3), catalog-constrained execution, risk-based approval, append-only audit.

**Known limitations (the gap Phase 2 closes)**

| # | Phase 1 Limitation | Consequence | Addressed In |
| --- | --- | --- | --- |
| 1 | Manual trigger (paste logs) | Slow detection, human-dependent | Layer 1 |
| 2 | Web-only knowledge | Misses tenant runbooks / history | Layer 2 |
| 3 | `MemorySaver` | Approvals lost on restart | Layer 3 |
| 4 | Dry-run mock executor | No real remediation | Layer 3 |
| 5 | Terminal-only approval | Slow, single-channel | Layer 4 |
| 6 | All-or-nothing deploy | Production blast radius | Layer 5 |
| 7 | Basic logs | No tracing/metrics/reporting | Layer 6 |
| 8 | Static confidence heuristics | Doesn't improve over time | Layer 7 |

---

## 3. Phase 2 Vision & Goals

### 3.1 Vision

> An incident is detected, diagnosed, fixed, validated, and (where safe) resolved automatically — with a full audit trail — and a human is engaged only for high-risk decisions, via the channel they already use.

### 3.2 Guiding Principles

1. **Safety before autonomy** — no action reaches production without validation; irreversible actions always require human approval.
2. **Durability by default** — every incident is a resumable, persisted workflow.
3. **Grounded, not generated** — fixes come from a vetted catalog and evidence, never freeform LLM output.
4. **Tenant isolation** — a B2B SaaS product must never mix one client's data with another's.
5. **Observable end-to-end** — every stage emits traces, metrics, and structured logs.
6. **Learning system** — outcomes feed back to improve confidence and suggestions.

### 3.3 The 7 Layers

| Layer | Name | Purpose | Primary Outcome |
| --- | --- | --- | --- |
| 1 | Intelligent Detection | Ingest + filter + dedupe alerts | Zero-touch incident creation |
| 2 | Enhanced Diagnosis | Multi-tenant + external + historical knowledge | Faster, higher-confidence diagnosis |
| 3 | Safe Execution | Durable state + sandbox + rollback | Zero production risk |
| 4 | Multi-Channel Notifications | Slack/Email/SMS + escalation | 10-second approvals |
| 5 | Canary Deployment | Progressive rollout | Zero-downtime releases |
| 6 | Observability & Analytics | Tracing, metrics, reports | Full visibility |
| 7 | Learning & Improvement | Outcome feedback | Continuously smarter agent |

### 3.4 Phase 2 Objectives (OKRs)

| Objective | Key Result | Target |
| --- | --- | --- |
| Automate detection | % incidents auto-created without human | 100% |
| Accelerate resolution | MTTR | ≤ 15 min |
| Reduce toil | % incidents auto-resolved | ≥ 70% |
| Eliminate bad-fix risk | Production incidents caused by an OpsFlow fix | 0 |
| Improve approvals | Median approval time | ≤ 10 s |
| Gain visibility | % incidents fully traced | 100% |
| Protect tenants | Cross-tenant data leakage incidents | 0 |

---

## 4. Detailed Implementation Plan

### Layer 1 — Intelligent Detection (Webhook + Smart Filtering)

**Objective:** Replace manual log pasting with an event-driven ingestion pipeline that is secure, de-duplicated, and rate-limited.

**Architecture**

```
CloudWatch / Prometheus / Grafana / Datadog
        │  POST (HMAC-SHA256 signed)
        ▼
FastAPI  /api/v1/webhooks/alert
        │
        ├─ 1. Verify signature (HMAC-SHA256, constant-time compare)
        ├─ 2. Idempotency check  → processed_alerts (unique key)
        ├─ 3. Normalize to internal Alert schema
        ├─ 4. Dedupe / merge     → same service within window
        ├─ 5. Rate limit         → 50 alerts/min/service
        ├─ 6. Severity classify  → critical | warning | info (rules + LLM)
        └─ 7. Enqueue incident   → LangGraph graph.invoke (thread_id = incident_id)
```

**Technical details**

- **Endpoint:** `POST /api/v1/webhooks/alert`, async FastAPI route. Returns `202 Accepted` immediately; processing is queued (Redis/RQ or Celery).
- **Signature verification:** `X-Signature: sha256=<hex>` computed over the raw body with a per-source secret; compare with `hmac.compare_digest`. Reject with `401` on mismatch, `400` on malformed.
- **Idempotency:** `processed_alerts(alerts_signature UNIQUE, source, service, first_seen, last_seen, count, incident_id)`. A repeated signature updates `last_seen`/`count` and does **not** create a new incident.
- **Deduplication / merge:** Alerts for the same `service` + `error_class` within a configurable window (default 5 min) merge into one incident; severity is promoted to the max observed.
- **Rate limiting / throttling:** Sliding-window limiter (Redis) keyed by service; `429` on breach; excess alerts are coalesced rather than dropped.
- **Severity classification:** Deterministic rule layer first (source severity + thresholds), LLM classification as enrichment. Only `critical` triggers the full pipeline immediately; `warning`/`info` are batched.
- **Normalized Alert schema:** `{source, service, error_class, raw_log, severity_hint, fingerprint, received_at}`.

**Data model (new tables)**

```sql
processed_alerts(alerts_signature TEXT PRIMARY KEY, source TEXT, service TEXT,
                 first_seen TIMESTAMPTZ, last_seen TIMESTAMPTZ, count INT, incident_id UUID);
```

**Acceptance criteria:** signed alert creates an incident in ≤ 2 s; replayed payload creates no duplicate; burst of 500 alerts for one service is coalesced and rate-limited; unsigned/invalid callers rejected.

---

### Layer 2 — Enhanced Diagnosis (Multi-Source Intelligence)

**Objective:** Ground every diagnosis in multi-tenant knowledge + external research + historical incidents, and score confidence from evidence.

**Architecture (Map-Reduce fan-out)**

```
                 ┌─ Agent A: Multi-Tenant Knowledge Base (RAG) ─┐
diagnosis ──► Send├─ Agent B: Web search (DuckDuckGo) ──────────┤─► merge → Critic
                 └─ Agent C: Similar past incidents (Postgres) ─┘
```

**Technical details**

- **Parallel research (Map-Reduce):** LangGraph `Send` fan-out dispatches 3 research sub-agents concurrently; results are collected via an `operator.add` reducer on `research[]` (already supported in Phase 1 state). Expected ~3× faster than sequential research.
- **Agent A — Multi-Tenant Knowledge Base:** Integrate a Multi-Tenant RAG system. Support a Managed Vector DB (**namespace-isolated per client**) for standard clients, and **Live External Connectors** (Confluence / ServiceNow API) for enterprise clients requiring **zero-data-retention**. Implement a **Graceful Degradation fallback chain** (Tenant KB → Live API → Postgres History → Web Search) to ensure high availability. Every query is scoped to a `tenant_id`; tenant results are ranked above web results.
- **Agent B — External web:** Existing DuckDuckGo tool (grounded citations, untrusted-data handling preserved).
- **Agent C — Historical incidents:** Query PostgreSQL for tenant-scoped `service + error_class` matches in the last 30 days; surface the previously successful remediation.
- **Confidence scoring (rubric, 0–100):** weighted evidence — tenant KB match (highest), past-incident success rate, source agreement count, catalog match, critic score. `confidence < 70` → flag for manual review; `≥ 80` → eligible for automated path.
- **History-aware proposal:** When a prior successful fix exists for the same signature, the proposer suggests it first (with its recorded success rate).

**Reliability: Namespace Isolation and Graceful Degradation**

This architecture is reliable and scalable for two reasons:

1. **Namespace isolation.** The vector database isolates each client's data in a dedicated namespace/collection. This guarantees zero cross-tenant data leakage and allows independent per-tenant scaling.
2. **Graceful degradation (fallback chain).** If a client's specific Knowledge Base is empty or down, the agent does not crash. Retrieval falls back through a priority chain:
   1. **Managed Tenant KB** — namespace-isolated vectors for the requesting tenant.
   2. **Live External Connectors** — Confluence / ServiceNow APIs (zero-data-retention for enterprise clients).
   3. **Postgres Historical Incidents** — previously successful fixes for the same tenant and signature.
   4. **Web Search** — general knowledge, explicitly **marked as Low Confidence**.

   This ensures the agent always produces a suggestion without compromising data privacy.

**Data model (new tables)**

```sql
incidents(incident_id UUID PRIMARY KEY, thread_id TEXT, source TEXT, service TEXT,
          error_class TEXT, severity TEXT, status TEXT, created_at TIMESTAMPTZ, resolved_at TIMESTAMPTZ);
fix_outcomes(incident_id UUID, remediation_id TEXT, params JSONB, outcome TEXT,
             confidence INT, applied_at TIMESTAMPTZ, verified_at TIMESTAMPTZ,
             stable BOOLEAN, success_rate_before NUMERIC);
```

**Acceptance criteria:** 3 research sources run in parallel; tenant KB results take precedence in ranking; every proposed fix carries a rubric-derived confidence and a per-source breakdown; recurring incidents surface the last successful fix; the fallback chain is exercised when the tenant KB is empty.

---

### Layer 3 — Safe Execution (Sandbox + Durable State)

**Objective:** Persist all workflow state, validate every fix in isolation, and guarantee rollback.

**Technical details**

- **Durable checkpoints:** Replace `InMemorySaver` with **`PostgresSaver`** (`langgraph-checkpoint-postgres`) so a paused `interrupt()` (approval) survives restarts and is resumable by any API worker. Register custom state types in the checkpoint allowlist (already established in Phase 1).
- **Sandboxed execution:** Apply the catalog fix inside an **isolated environment** — Docker-in-Docker or an ephemeral Kubernetes pod — never production. Flow:
  1. Apply fix in sandbox (array argv, `shell=False`, timeout, resource limits, restricted env).
  2. Run validation: health checks, smoke tests, assertions.
  3. Pass → attach results and request "Approve for Production". Fail → return to the self-correction loop (next fix).
- **Automatic rollback:** Snapshot pre-fix state; if post-fix health checks fail, automatically revert. Rollback plan is mandatory for irreversible actions.
- **Execution audit trail:** Every attempt writes to `execution_logs` (who/what/when/where/result) — immutable and queryable.

**Data model (new tables)**

```sql
execution_logs(execution_id UUID PRIMARY KEY, incident_id UUID, remediation_id TEXT,
               params JSONB, command TEXT[], environment TEXT, dry_run BOOLEAN,
               approved_by TEXT, approved_at TIMESTAMPTZ, started_at TIMESTAMPTZ,
               finished_at TIMESTAMPTZ, exit_code INT, result TEXT, sandbox_checks JSONB);
```

**Acceptance criteria:** killing and restarting the API resumes a pending approval exactly once; no catalog fix can execute outside the sandbox; failed sandbox validation never reaches production; every execution is fully audited.

---

### Layer 4 — Multi-Channel Notifications (Slack + Email + SMS)

**Objective:** Engage approvers where they are, with fast, durable, and escalating approvals.

**Technical details**

- **Slack (primary):** When a fix passes the sandbox, post a Block Kit message with incident details and buttons `[Approve for Production] [Reject] [View Details]`. A button click hits `POST /api/v1/approvals/{thread_id}` which resumes the paused graph via `Command(resume={"approved": ..., "approver": ...})`. The graph is loaded with the **same PostgresSaver**, so the paused state is found and continued.
- **Email (backup):** SMTP with signed approve/reject links (time-limited tokens) when the approver is not on Slack.
- **SMS / PagerDuty (critical only):** If a critical incident is not approved within 15 min, notify via Twilio/PagerDuty.
- **Escalation policy:** No approval in 30 min → next-level manager → senior manager → CTO. Implemented as delayed jobs (Redis/Celery beat) keyed by `thread_id`.
- **Idempotent resume:** Approvals are recorded once; duplicate clicks are ignored.

**API surface (new)**

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/webhooks/alert` | Ingest signed alert |
| POST | `/api/v1/approvals/{thread_id}` | Resume graph from Slack/email |
| GET | `/api/v1/incidents/{id}` | Incident detail / timeline |
| GET | `/healthz`, `/readyz` | Liveness / readiness |
| GET | `/metrics` | Prometheus scrape |

**Acceptance criteria:** approval via Slack resumes the correct paused incident; approvals survive a restart of the API service; critical alerts escalate on schedule; every decision is attributed to an approver and timestamped.

---

### Layer 5 — Canary Deployment (Safe Production Rollout)

**Objective:** Roll fixes out progressively with automatic rollback on regression.

**Technical details**

- **Canary strategy:** Apply to **10%** of servers first; monitor for 15 min (error rate, p95/p99 latency, CPU/memory, HTTP 5xx). Normal → continue; abnormal → rollback.
- **Orchestration:** **Argo Rollouts** or **Flagger** on Kubernetes, with Prometheus-based analysis templates.
- **Progressive delivery:** 10% → 25% → 50% → 100%, with a monitoring window (≈10 min) at each stage and automatic promotion gates.
- **Automatic rollback:** If canary error rate > 5% (or a defined SLO breach), roll back instantly; the resulting Prometheus alert can re-enter OpsFlow via the Layer 1 webhook, closing the loop.
- **Guardrails:** Hard caps on blast radius; feature-flagged release; mandatory human approval before any irreversible 100% step.

**Acceptance criteria:** a failing canary rolls back automatically with zero user-visible impact; a healthy canary completes 10→100% unattended; every stage transition is recorded in the audit trail.

---

### Layer 6 — Observability & Analytics (Modern Monitoring)

**Objective:** Make the entire lifecycle measurable, traceable, and reportable.

**Technical details**

- **OpenTelemetry tracing:** One span per stage (alert → diagnosis → research → fix → approval → sandbox → deploy), visualized in **Jaeger** (or Zipkin). Trace/incident IDs propagated through the graph, queue, and executors.
- **Prometheus metrics** (visualized in Grafana):
  - `incident_total`, `incident_auto_resolved_total`, `incident_manual_approval_total`
  - `mttd_seconds`, `mttr_seconds`
  - `fix_success_rate`
  - `sandbox_failures_total`, `canary_rollback_total`, `approval_latency_seconds`
- **Structured JSON logging** via Loguru/structlog — every line: `timestamp, level, incident_id, stage, duration_ms, message` — ready for ELK.
- **Post-incident reports:** Auto-generated (Markdown/PDF) with timeline, root cause, fix applied, impact, and lessons learned; archived and linked to the incident record.

**Acceptance criteria:** 100% of incidents produce a trace and matching metrics; MTTR/MTTD are computed automatically; a post-incident report is generated within 60 s of resolution.

---

### Layer 7 — Learning & Improvement (AI Gets Smarter)

**Objective:** Close the loop so confidence and recommendations improve with every outcome.

**Technical details**

- **Feedback loop:** 24 h after a fix is applied, a scheduled job checks service stability and writes `fix_outcomes(stable, outcome)`. Optionally a shorter 1 h sanity check for critical services.
- **Learning from past fixes:** Successful `(service, error_class) → remediation` mappings are indexed and suggested first for recurrences, with their historical success rate.
- **Confidence calibration:** Adjust rubric weights from observed outcomes (e.g., if fixes scored 80 historically succeeded only 50% of the time, tighten the threshold / reweight sources). Track calibration error over time.
- **Continuous evaluation:** Golden incident set replayed in CI to measure correct-remediation %, avg loops, and **false-safe rate** (dangerous auto-executions) — must trend to zero.

**Acceptance criteria:** every fix has a recorded outcome; recurring incidents preferentially surface proven fixes; confidence calibration error decreases over the first quarter; false-safe rate remains 0.

---

## 5. Implementation Roadmap (Week-by-Week)

| Week | Theme | Key Tasks | Deliverable | Exit Criteria |
| --- | --- | --- | --- | --- |
| 1 | Foundation | FastAPI webhook + HMAC verification; PostgresSaver swap; idempotency keys | Webhook receives alerts; state persists across restarts | Signed alert → incident; replay deduped; restart-safe |
| 2 | Enhanced Diagnosis | Multi-tenant KB integration; Map-Reduce parallel research; confidence scoring | Tenant-aware + external knowledge; ~3× faster diagnosis | 3 sources parallel; rubric confidence emitted; tenant scoping verified |
| 3 | Safe Execution | Sandboxed Docker executor; auto-rollback; execution audit | Fixes tested in isolation; zero prod risk | No prod execution; failed sandbox loops correctly |
| 4 | Notifications | Slack interactive buttons; email backup; escalation policies | Manager approves via Slack | ≤10 s approval; survives restart; escalation fires |
| 5 | Canary Deployment | Argo Rollouts/Flagger; auto-rollback; progressive delivery | Safe rollout 10%→100% | Failed canary auto-rolls back; healthy completes |
| 6 | Observability & Analytics | OTel tracing; Prometheus + Grafana; post-incident reports | Full visibility | 100% traced; reports auto-generated |

**Milestones**

- **M1 (end Week 1):** Event-driven, durable ingestion — "no more pasting logs."
- **M2 (end Week 2):** Enhanced, grounded diagnosis — "smarter and faster, tenant-safe."
- **M3 (end Week 4):** Sandbox + Slack approvals — "safe and hands-off for the developer."
- **M4 (end Week 6):** Canary + observability — "production-grade."

---

## 6. Business Impact & KPIs

### 6.1 Before vs After

| Metric | Before (Phase 1) | After (Phase 2) |
| --- | --- | --- |
| MTTD (Mean Time To Detect) | 15 min (manual) | ~0 s (auto) |
| MTTR (Mean Time To Resolve) | 2 hours | 15 minutes |
| % Incidents Auto-Resolved | 0% | 70% |
| Production Risk from Bad Fixes | High | Zero (sandbox + canary) |
| Manager Approval Time | 10 min (terminal) | 10 sec (Slack button) |
| Developer Midnight Alerts | 100% | 10% (only critical) |
| System Observability | Basic logs | Full tracing + metrics |

### 6.2 Measurement Methodology

- **MTTD/MTTR** computed from `incidents.created_at` → `resolved_at`, exported as Prometheus histograms.
- **Auto-resolution %** = `incident_auto_resolved_total / incident_total`.
- **False-safe rate** = dangerous auto-executions / total auto-executions (target **0**).
- **Approval latency** measured at the notification → resume boundary.
- **Cross-tenant leakage** = number of incidents where a retrieval result belongs to a different tenant (target **0**).

### 6.3 Guardrails (non-negotiable)

- No production change without sandbox validation **and** (for risky/irreversible actions) human approval.
- Rollback mandatory for irreversible actions.
- Catalog is the only source of executable actions.
- Every retrieval is scoped to a single `tenant_id`; no cross-tenant reads.

---

## 7. Technical Stack & Dependencies

| Layer | Technology | Purpose |
| --- | --- | --- |
| Backend / API | **FastAPI** (async), Uvicorn | Webhooks, approvals, observability endpoints |
| State & Audit | **PostgreSQL** + `langgraph-checkpoint-postgres` | Durable state, `processed_alerts`, `execution_logs`, `fix_outcomes` |
| Queue / Cache | **Redis** (+ RQ/Celery) | Rate limiting, dedupe windows, delayed escalations, job queue |
| Orchestration | **LangGraph** | State machine, checkpointing, `Send` Map-Reduce, `interrupt()` |
| LLM Tooling | **LangChain + Paid Hosted API (Primary) with Local Ollama fallback** | Tools, structured output, hybrid inference |
| Knowledge | **Multi-Tenant Vector DB (namespace-isolated) + Live API Connectors (Confluence/ServiceNow)** | Tenant-aware retrieval |
| Monitoring | **Prometheus + Grafana**, **OpenTelemetry + Jaeger**, **Loguru** | Metrics, traces, structured JSON logs |
| Deployment | **Docker**, **Kubernetes** (Argo Rollouts / Flagger), **AWS CloudWatch** | Sandbox, canary, alert source |
| Notifications | **Slack API** (Block Kit), **SMTP**, **Twilio / PagerDuty** | Primary, backup, critical escalation |
| Security | **HMAC-SHA256**, `PostgresSaver`, Docker isolation | Anti-spoofing, durability, sandboxing, tenant isolation |

**Infrastructure requirements**

- PostgreSQL 15+ (managed/HA recommended), Redis 7+, Kubernetes cluster with Argo Rollouts.
- A multi-tenant vector store (pgvector, Pinecone, or equivalent) with per-tenant namespaces/collections.
- Container runtime with sandbox isolation (no production credentials mounted into the sandbox).
- GPU optional (local Ollama); otherwise a hosted inference endpoint for scale.

**Cost posture:** paid hosted API for dev/demo (~$10 budget); Local Ollama available as zero-cost fallback for production.

---

## 8. Risks & Mitigation Strategies

| # | Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| 1 | Webhook spoofing | Medium | High | HMAC-SHA256 verification; reject unsigned; per-source secrets; audit |
| 2 | Duplicate incidents / alert storms | High | Medium | Idempotency keys + dedupe window + rate limiting |
| 3 | LLM hallucination / unsafe fix | Medium | High | Catalog-only actions, strict validation, sandbox, human approval for risky |
| 4 | Prompt injection via logs/web | Medium | High | Untrusted-data framing; never treat content as instructions; redaction |
| 5 | Sandbox escape / privilege | Low | Critical | Ephemeral isolated pods; least privilege; no prod creds in sandbox |
| 6 | Canary regression | Medium | Medium | Prometheus gates, auto-rollback > 5% error, progressive stages |
| 7 | State migration (`MemorySaver`→Postgres) | Medium | Medium | Staged rollout; allowlist custom types; migration tests |
| 8 | Notification fatigue / missed alerts | Medium | High | Severity gating (critical only), escalation policies, quiet hours |
| 9 | Postgres/Redis outage | Low | High | HA, backups, graceful degradation; webhook returns 503 + retry |
| 10 | Latency of local LLM under load | Medium | Medium | Queue + concurrency limits; model warm pool; optional hosted fallback |
| 11 | Confidence miscalibration | Medium | Medium | Rubric scoring + outcome-based recalibration + eval harness |
| 12 | Data privacy / PII exposure | Medium | High | Redaction before LLM; data retention policy; encrypted stores |
| 13 | Multi-tenant data leakage | Low | Critical | Strict namespace/collection isolation in the Vector DB; row-level security; zero-data-retention mode for enterprise clients |
| 14 | Paid API service outage | Medium | High | Local Ollama fallback via config flag; queue-based retry |

---

## 9. Success Criteria & Definition of Done

### 9.1 Per-Layer Definition of Done

| Layer | Done When |
| --- | --- |
| 1 Detection | Signed alerts create deduped, rate-limited incidents automatically |
| 2 Diagnosis | 3 parallel sources with tenant scoping; every fix carries rubric confidence + per-source breakdown; fallback chain works |
| 3 Execution | Postgres-backed resume verified; sandbox + auto-rollback working; full audit |
| 4 Notifications | Slack approve/reject resumes the graph; escalation policy fires |
| 5 Canary | Progressive 10→100% with automatic rollback validated |
| 6 Observability | Traces, metrics, and post-incident reports generated automatically |
| 7 Learning | Outcomes recorded; proven fixes surfaced; calibration improving |

### 9.2 Program Definition of Done (Phase 2 complete)

- MTTD ≈ 0 s and MTTR ≤ 15 min measured in production.
- ≥ 70% of qualifying incidents auto-resolved.
- **0** production incidents caused by an OpsFlow-applied fix.
- **0** cross-tenant data leakage incidents.
- 100% of incidents fully traced and audited; approvals durable across restarts.
- Eval harness green in CI (correct-remediation %, false-safe rate = 0).

---

## 10. Next Steps & Immediate Actions

### 10.1 Immediate (Week 0 — this week)

| # | Action | Owner | Duration |
| --- | --- | --- | --- |
| 1 | Approve Phase 2 scope & KPIs | CTO / EM | 1 meeting |
| 2 | Provision PostgreSQL + Redis (dev/staging) | Platform | 2 days |
| 3 | Spike: `PostgresSaver` swap in a branch | AI Eng | 1 day |
| 4 | Spike: FastAPI webhook + HMAC verification | AI Eng | 1 day |
| 5 | Define the Multi-Tenant Knowledge Base interface and `tenant_id` scoping | AI Eng + Platform | 1 day |

### 10.2 Decisions Required

- Canary platform: **Argo Rollouts vs Flagger** (recommend Argo Rollouts for maturity + Prometheus analysis).
- Approval latency SLA and escalation tree (manager → senior → CTO) — confirm policy owners.
- Sandbox isolation model: **Docker-in-Docker vs ephemeral K8s pods** (recommend K8s pods for isolation + observability).
- **Inference at scale — DECIDED:** Use paid hosted API for dev/test/demo; local Ollama as fallback.
- **Multi-tenant KB — DECIDED:** Managed Vector DB for standard clients + Live API connectors for enterprise (zero-data-retention).

### 10.3 Immediate Engineering Actions

1. Create the `phase-2` branch; move `MemorySaver` → `PostgresSaver` behind a config flag.
2. Implement `POST /api/v1/webhooks/alert` with signature verification + idempotency table.
3. Stand up `Send`-based parallel research skeleton with the 3 sub-agents.
4. Add `incidents`, `execution_logs`, `fix_outcomes` migrations.
5. Wire Prometheus `/metrics` and OpenTelemetry tracing exporters.

---

## Appendix A — Reference Data Model

```sql
processed_alerts(alerts_signature PK, source, service, first_seen, last_seen, count, incident_id)
incidents(incident_id PK, thread_id, source, service, error_class, severity, status, created_at, resolved_at)
execution_logs(execution_id PK, incident_id, remediation_id, params, command[], environment,
               dry_run, approved_by, approved_at, started_at, finished_at, exit_code, result, sandbox_checks)
fix_outcomes(incident_id, remediation_id, params, outcome, confidence, applied_at, verified_at, stable, success_rate_before)
```

## Appendix B — Alert Payload Contract (example)

```json
{
  "source": "cloudwatch",
  "service": "checkout-api",
  "error_class": "OOMKilled",
  "severity_hint": "critical",
  "raw_log": "container exited with code 137 ...",
  "fingerprint": "svc:checkout-api|err:OOMKilled",
  "received_at": "2026-10-08T12:00:00Z",
  "tenant_id": "tenant-123"
}
```

## Appendix C — Glossary

| Term | Meaning |
| --- | --- |
| MTTD / MTTR | Mean Time To Detect / Resolve |
| HITL | Human-in-the-loop |
| RAG | Retrieval-Augmented Generation |
| BM25 | Lexical ranking function used in hybrid retrieval |
| Namespace isolation | Per-tenant separation of vector data to prevent cross-tenant reads |
| Zero-data-retention | Connector mode where client knowledge is queried live and never stored |
| Canary | Progressive rollout to a small subset before full release |
| Map-Reduce (Send) | LangGraph fan-out/fan-in parallel pattern |

---

*Prepared by [Your Name], AI/ML Engineer · OpsFlow AI Phase 2 · 13 Oct 2026*
