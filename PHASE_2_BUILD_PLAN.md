# OpsFlow AI — Phase 2 Build Plan

**Actionable engineering backlog derived from the Phase 2 Implementation Plan**

| Field | Detail |
| --- | --- |
| Owner | [Your Name], AI/ML Engineer |
| Source Document | `PHASE_2_IMPLEMENTATION_PLAN.md` |
| Version | 1.0 |
| Date | 09 Oct 2026 |
| Total Steps | 37 (P2-01 … P2-37) |
| Duration | 6 weeks (Weeks 1–6) |
| Audience | AI/ML + Platform engineers, Engineering Manager, CTO |

---

## 0. How to Use This Plan

- Steps are **sequential within a week** and **partially parallel across tracks** (see Section 5).
- Every step follows the same rhythm: **concept → build → test → done-when**.
- Each step must be **runnable/testable on its own** before the next begins.
- "Done when" is the acceptance test — no step is complete without it passing.
- Suggested cadence: implement one step, verify, then proceed (pair-mode: concept first).

**Legend:** `Est.` = engineer-days · `Dep.` = required prior steps · `L#` = Phase 2 layer · `W#` = week.

---

## 1. Prerequisites & Assumptions

- Phase 1 complete (10/21 verified): `intake → analyzer → researcher ⇄ critic → risk → approval → executor`.
- Paid Hosted API (Primary) + Local `qwen2.5:7b` via Ollama (Fallback); catalog + validator; `interrupt()` HITL; audit reducer.
- Available: PostgreSQL 16, Redis 7, Docker (or Kubernetes), Slack workspace, SMTP, optional Twilio.
- Assumption: production targets are Kubernetes-based (needed for Layer 5 canary).

---

## 2. Target Repository Layout

```
opsflow_ai/
├── app/                # Phase 1 agent core (state, graph, nodes, tools, catalog, safety)
├── api/                # NEW: FastAPI service (webhooks, approvals, health, metrics)
│   ├── main.py
│   ├── routes/         (webhooks.py, approvals.py, incidents.py)
│   ├── deps.py
│   └── security.py     (HMAC verification, auth)
├── worker/             # NEW: queue workers (alert processing, scheduled jobs)
│   ├── tasks.py
│   └── scheduler.py    (escalations, feedback loop)
├── db/                 # NEW: SQLAlchemy models + session
│   └── models.py
├── migrations/         # NEW: Alembic migrations
├── integrations/       # NEW: tenant_kb.py, slack.py, email.py, sms.py, prometheus.py
├── observability/      # NEW: tracing.py, metrics.py, logging.py
├── deploy/             # NEW: Dockerfile, docker-compose.yml, k8s/ (rollouts, analysis)
├── evals/              # NEW: dataset.jsonl, run_eval.py
├── tests/              # integration + unit tests
├── .env.example
├── PHASE_2_IMPLEMENTATION_PLAN.md
├── PHASE_2_BUILD_PLAN.md
└── requirements.txt
```

---

## 3. Build Tracks (Overview)

| Track | Layer | Steps | Theme |
| --- | --- | --- | --- |
| T1 | L1 | P2-01 … P2-09 | Event-driven ingestion + durable foundation |
| T2 | L2 | P2-10 … P2-15 | Multi-tenant knowledge + multi-source, high-confidence diagnosis |
| T3 | L3 | P2-16 … P2-21 | Sandboxed, auditable execution |
| T4 | L4 | P2-22 … P2-26 | Multi-channel approvals + escalation |
| T5 | L5 | P2-27 … P2-30 | Canary rollout + auto-rollback |
| T6 | L6/L7 | P2-31 … P2-37 | Observability, reporting, learning |

---

## 4. Step-by-Step Plan

### Week 1 — Foundation (T1)

#### P2-01 — Repo & local infrastructure setup
- **Build:** Split `app/` (agent core) from new `api/`, `worker/`, `db/`, `integrations/`, `observability/`, `deploy/`, `evals/`, `tests/`. Add `docker-compose.yml` (Postgres 16 + Redis 7). Extend `config.py` with DB/Redis/API settings.
- **Concept:** service boundaries, 12-factor config, local-first dev.
- **Done when:** `docker compose up` starts PG + Redis; `python -c "import api.main, worker.tasks"` succeeds.
- **Est:** 0.5d · **Dep:** —

#### P2-02 — Database models & migrations
- **Build:** SQLAlchemy models + Alembic migrations for `processed_alerts`, `incidents`, `execution_logs`, `fix_outcomes` (schemas in Implementation Plan, Appendix A).
- **Concept:** schema-first, versioned migrations, JSONB for params/checks.
- **Done when:** `alembic upgrade head` and `downgrade` run cleanly; all 4 tables exist.
- **Est:** 1d · **Dep:** P2-01

#### P2-03 — FastAPI skeleton + structured logging
- **Build:** `api/main.py` with `/healthz`, `/readyz`; Loguru/structlog JSON logs: `timestamp, level, incident_id, stage, duration_ms, message`.
- **Concept:** structured logging, liveness/readiness probes.
- **Done when:** app boots; `/healthz` → 200; emitted logs parse as JSON.
- **Est:** 0.5d · **Dep:** P2-01

#### P2-04 — Durable checkpoints (PostgresSaver)
- **Build:** Swap `InMemorySaver` → `PostgresSaver` behind `CHECKPOINTER=postgres|memory`; register custom state types in the checkpoint allowlist; manage setup/connection lifecycle.
- **Concept:** durable execution, resumable workflows, checkpoint stores.
- **Done when:** pause at `approval`, restart the API process, resume the same incident **exactly once**.
- **Est:** 1d · **Dep:** P2-02

#### P2-05 — Webhook endpoint + HMAC verification
- **Build:** `POST /api/v1/webhooks/alert`; read raw body; verify `X-Signature` via `hmac.compare_digest` with per-source secrets; return 202 / 401 / 400.
- **Concept:** webhook authenticity, constant-time comparison, anti-spoofing.
- **Done when:** valid signature → 202; tampered/unsigned → 401; malformed → 400.
- **Est:** 1d · **Dep:** P2-03

#### P2-06 — Idempotency, normalization, dedupe
- **Build:** Insert into `processed_alerts` (unique alerts_signature); normalize to Alert schema; merge same `service + error_class` within a 5-min window; promote severity to max.
- **Concept:** idempotency keys, deduplication windows, alert storms.
- **Done when:** replayed payload creates no new incident; a 500-alert burst for one service merges into one.
- **Est:** 1d · **Dep:** P2-05

#### P2-07 — Rate limiting + severity classification
- **Build:** Redis sliding-window limiter (50/min/service); rules-first severity classifier + LLM enrichment; `critical` triggers immediately, `warning`/`info` batched.
- **Concept:** backpressure/throttling, rules-as-guardrails before ML.
- **Done when:** 51st alert/min is throttled/coalesced; each alert is severity-labelled and stored.
- **Est:** 1d · **Dep:** P2-06

#### P2-08 — Incident creation + queue worker
- **Build:** background worker (RQ/Celery) consumes queued alerts, writes an `incidents` row, and invokes the LangGraph app with `thread_id = incident_id` using the Postgres checkpointer.
- **Concept:** async decoupling (webhook fast-ack), worker idempotency, queue retries.
- **Done when:** an alert produces an incident row + a graph run; worker restart does not duplicate work.
- **Est:** 1d · **Dep:** P2-04, P2-07

#### P2-09 — Week 1 integration test (exit criteria)
- **Build:** one script proving signed alert → dedupe → incident → graph → pause at approval → process restart → resume.
- **Done when:** all Week 1 exit criteria pass in a single command.
- **Est:** 0.5d · **Dep:** P2-08

---

### Week 2 — Enhanced Diagnosis (T2)

#### P2-10 — Multi-Tenant Knowledge Base Adapter & Tool
- **Build:** Build an HTTP client/adapter for the Multi-Tenant RAG system. Support tenant-isolated namespaces for managed KB and live API connectors for external enterprise KBs. Implement the kb_search tool with a graceful fallback chain.
- **Concept:** Multi-tenant RAG, namespace isolation, graceful degradation, zero-data-retention connectors.
- **Done when:** a query correctly scopes to a specific `tenant_id` namespace, returns ranked runbook hits with citations, and gracefully falls back to web/history if the tenant KB is empty.
- **Est:** 1.5d · **Dep:** P2-09

#### P2-11 — Historical incidents tool
- **Build:** Postgres query for same `service + error_class` in the last 30 days; return the prior successful remediation + its success rate.
- **Concept:** operational memory, pattern matching, closed-loop history.
- **Done when:** a recurring signature surfaces the last successful fix.
- **Est:** 1d · **Dep:** P2-02

#### P2-12 — Parallel research (Send Map-Reduce)
- **Build:** replace the sequential researcher with a `Send` fan-out to 3 sub-agents (KB, web, history); merge with the existing `operator.add` reducer; fan-in to the critic.
- **Concept:** LangGraph Map-Reduce (`Send`), fan-out/fan-in, reducer accumulation.
- **Done when:** all 3 sources appear merged in state; wall-clock ~3× faster than sequential.
- **Est:** 2d · **Dep:** P2-10, P2-11

#### P2-13 — Rubric confidence scoring
- **Build:** weighted module → 0–100 from KB match, source agreement, history success rate, catalog match, critic score; persist a per-source breakdown.
- **Concept:** evidence-based confidence vs self-reported scores.
- **Done when:** every fix has a confidence + breakdown; `< 70` is flagged for manual review.
- **Est:** 1.5d · **Dep:** P2-12

#### P2-14 — History-aware proposal
- **Build:** proposer suggests the proven fix first for recurring issues (with its success rate), while staying catalog-constrained.
- **Concept:** learning from past fixes, preference ordering.
- **Done when:** a recurrence prefers the previously successful remediation.
- **Est:** 1d · **Dep:** P2-11, P2-13

#### P2-15 — Week 2 integration test (exit criteria)
- **Build:** end-to-end diagnosis with 3 sources + rubric confidence + history-aware proposal.
- **Done when:** all Week 2 exit criteria pass.
- **Est:** 0.5d · **Dep:** P2-14

---

### Week 3 — Safe Execution (T3)

#### P2-16 — Sandbox executor (isolation)
- **Build:** runner abstraction applying the catalog fix in an ephemeral Docker/K8s pod; argv + `shell=False`, timeout, resource limits, restricted env; **no production credentials**.
- **Concept:** blast-radius isolation, least privilege, ephemeral environments.
- **Done when:** a fix executes only inside the sandbox; production is untouched.
- **Est:** 2d · **Dep:** P2-09

#### P2-17 — Sandbox validation suite
- **Build:** health checks + smoke tests + assertions after the fix; capture results as `sandbox_checks` JSON.
- **Concept:** verification gates, test-as-a-barrier.
- **Done when:** pass/fail is recorded; a failing validation blocks promotion.
- **Est:** 1.5d · **Dep:** P2-16

#### P2-18 — Automatic rollback
- **Build:** pre-fix snapshot; on validation failure auto-revert; enforce a mandatory rollback plan for irreversible actions.
- **Concept:** idempotent revert, safety invariants.
- **Done when:** a failed validation reverts the sandbox cleanly.
- **Est:** 1.5d · **Dep:** P2-17

#### P2-19 — Execution audit trail
- **Build:** write `execution_logs` (who/what/when/where/result); append-only; queryable by incident.
- **Concept:** immutable audit, compliance-ready records.
- **Done when:** every execution attempt is audited end-to-end.
- **Est:** 1d · **Dep:** P2-16

#### P2-20 — Self-correction on sandbox failure
- **Build:** a failed sandbox result loops back to the proposer with failure feedback (reuse the critic loop + cap).
- **Concept:** feedback into the decision, bounded retries.
- **Done when:** a failed fix triggers the next candidate automatically.
- **Est:** 1d · **Dep:** P2-18

#### P2-21 — Week 3 integration test (exit criteria)
- **Build:** proposal → approval → sandbox → validate → "approve for production"; audit verified.
- **Done when:** all Week 3 exit criteria pass.
- **Est:** 0.5d · **Dep:** P2-20

---

### Week 4 — Notifications (T4)

#### P2-22 — Approval service + resume endpoint
- **Build:** `POST /api/v1/approvals/{thread_id}` loads the graph with the Postgres checkpointer and calls `Command(resume={approved, approver})`; idempotent.
- **Concept:** resuming a paused graph from an external channel.
- **Done when:** an API call resumes the correct paused incident exactly once.
- **Est:** 1d · **Dep:** P2-04

#### P2-23 — Slack integration
- **Build:** Slack app posting a Block Kit message (incident, root cause, fix, sandbox result) with `[Approve for Production] [Reject] [View Details]`; verify Slack interactive payload signatures; call the resume endpoint.
- **Concept:** interactive approvals, signed callbacks.
- **Done when:** a button click resumes the correct incident.
- **Est:** 2d · **Dep:** P2-22

#### P2-24 — Email backup channel
- **Build:** SMTP with signed, time-limited approve/reject links for approvers not on Slack.
- **Concept:** fallback channels, signed tokens.
- **Done when:** an email link approves/rejects the incident.
- **Est:** 1d · **Dep:** P2-22

#### P2-25 — SMS/PagerDuty + escalation policy
- **Build:** critical-only SMS at 15 min; escalation scheduler (30 min → manager → senior → CTO) via delayed jobs.
- **Concept:** on-call escalation, SLA timers.
- **Done when:** an unapproved critical incident escalates on schedule.
- **Est:** 1.5d · **Dep:** P2-23

#### P2-26 — Week 4 integration test (exit criteria)
- **Build:** approve via Slack, reject via email, escalate a critical incident.
- **Done when:** all Week 4 exit criteria pass.
- **Est:** 0.5d · **Dep:** P2-25

---

### Week 5 — Canary Deployment (T5)

#### P2-27 — Kubernetes + Argo Rollouts setup
- **Build:** cluster manifests; install Argo Rollouts; author a `Rollout` CRD for the target service.
- **Concept:** progressive delivery primitives.
- **Done when:** the Rollout CRD applies and defines canary steps.
- **Est:** 2d · **Dep:** P2-21

#### P2-28 — Prometheus analysis gates
- **Build:** `AnalysisTemplate` on error rate, p95/p99 latency, HTTP 5xx, CPU/memory; gates at each step.
- **Concept:** metric-driven promotion gates.
- **Done when:** an unhealthy canary fails the gate automatically.
- **Est:** 1.5d · **Dep:** P2-27

#### P2-29 — Progressive delivery + auto-rollback
- **Build:** orchestrate 10→25→50→100% with monitoring windows; auto-rollback if error rate > 5%; route the rollback alert back through the webhook.
- **Concept:** blast-radius control, closed-loop rollback.
- **Done when:** a failing canary auto-rolls back; a healthy canary completes unattended.
- **Est:** 2d · **Dep:** P2-28

#### P2-30 — Week 5 integration test (exit criteria)
- **Build:** kind/minikube tests for both healthy and failing rollouts.
- **Done when:** all Week 5 exit criteria pass.
- **Est:** 1d · **Dep:** P2-29

---

### Week 6 — Observability, Reporting & Learning (T6)

#### P2-31 — OpenTelemetry tracing
- **Build:** instrument graph, queue, and executors; propagate `incident_id`/trace context; export to Jaeger.
- **Concept:** distributed tracing, span-per-stage.
- **Done when:** one incident produces a single trace covering all stages.
- **Est:** 2d · **Dep:** P2-30

#### P2-32 — Prometheus metrics + Grafana dashboards
- **Build:** emit counters/histograms: `incident_total`, `incident_auto_resolved_total`, `incident_manual_approval_total`, `mttd_seconds`, `mttr_seconds`, `fix_success_rate`, `sandbox_failures_total`, `canary_rollback_total`, `approval_latency_seconds`; build dashboards.
- **Concept:** SLO/observability instrumentation.
- **Done when:** dashboards show live KPI values.
- **Est:** 1.5d · **Dep:** P2-31

#### P2-33 — Structured logging pipeline
- **Build:** JSON logs correlated by `incident_id`, ELK-ready; consistent fields across services.
- **Concept:** observability via logs, correlation IDs.
- **Done when:** logs parse and are queryable by incident.
- **Est:** 1d · **Dep:** P2-03

#### P2-34 — Post-incident report generator
- **Build:** auto-generate Markdown/PDF with timeline, root cause, fix applied, impact, lessons learned; link to the incident.
- **Concept:** automated retrospectives, knowledge capture.
- **Done when:** a report is generated ≤ 60 s after resolution.
- **Est:** 1.5d · **Dep:** P2-19, P2-32

#### P2-35 — Feedback loop + fix_outcomes
- **Build:** T+24h (and T+1h for critical) stability check; write `fix_outcomes`; mark stable/unstable.
- **Concept:** closed-loop learning, delayed verification.
- **Done when:** outcomes are recorded automatically for every applied fix.
- **Est:** 1d · **Dep:** P2-19

#### P2-36 — Confidence calibration + eval harness in CI
- **Build:** recalibrate rubric weights from outcomes; golden incident set replayed in CI; gate on correct-remediation % and **false-safe rate = 0**.
- **Concept:** continuous evaluation, calibration error.
- **Done when:** CI eval is green and calibration error trends down.
- **Est:** 2d · **Dep:** P2-35

#### P2-37 — End-to-end acceptance + go-live
- **Build:** full drill (alert → diagnosis → sandbox → Slack approval → canary → report); operational runbook; go-live checklist.
- **Concept:** production readiness, operational handover.
- **Done when:** the Phase 2 Definition of Done (Section 8) is fully met.
- **Est:** 1.5d · **Dep:** P2-36

---

## 5. Dependency & Sequencing Notes

- **Critical path:** P2-01 → P2-02 → P2-04 → P2-08 → P2-12 → P2-16 → P2-22 → P2-27 → P2-31 → P2-37.
- **Parallelizable early:** P2-10/P2-11 (integrations) can proceed once P2-02 lands, in parallel with P2-05…P2-08.
- **Parallelizable mid:** P2-16…P2-21 (sandbox) and P2-22…P2-26 (notifications) can run as two workstreams.
- **Hard prerequisites:** P2-04 (durable state) before any approval/resume work; P2-27 (K8s) before canary; P2-31/P2-32 before P2-34.
- **Estimated total:** ~47 engineer-days; achievable in 6 weeks with 2 engineers (or 1 engineer + AI-assisted development).

---

## 6. Requirements Traceability Matrix

| Phase 2 Requirement | Step(s) |
| --- | --- |
| FastAPI webhook endpoint | P2-05 |
| HMAC-SHA256 signature verification | P2-05, P2-23 |
| Idempotency keys (`processed_alerts`) | P2-06 |
| Alert dedupe / merge | P2-06 |
| Rate limiting (50/min/service) | P2-07 |
| AI severity classification | P2-07 |
| Multi-Tenant Internal Knowledge Base (RAG) | P2-10 |
| Parallel multi-agent research (Map-Reduce) | P2-12 |
| Confidence scoring (rubric) | P2-13 |
| Historical pattern matching | P2-11, P2-14 |
| `PostgresSaver` durable checkpoints | P2-04 |
| Sandboxed execution | P2-16 |
| Sandbox validation tests | P2-17 |
| Automatic rollback (sandbox) | P2-18 |
| Execution audit trail (`execution_logs`) | P2-19 |
| Slack interactive approvals | P2-23 |
| Email backup channel | P2-24 |
| SMS / PagerDuty (critical) | P2-25 |
| Escalation policies | P2-25 |
| Canary rollout (Argo/Flagger) | P2-27, P2-29 |
| Automatic canary rollback | P2-29 |
| Progressive delivery 10→100% | P2-29 |
| OpenTelemetry tracing | P2-31 |
| Prometheus metrics + Grafana | P2-32 |
| Structured JSON logging (ELK) | P2-33 |
| Post-incident auto reports | P2-34 |
| Feedback loop (`fix_outcomes`) | P2-35 |
| Learning from past fixes | P2-14, P2-35 |
| Confidence calibration | P2-36 |
| Eval harness (false-safe = 0) | P2-36 |

---

## 7. Cross-Cutting Concerns

- **Security:** HMAC on all inbound webhooks (P2-05), signed Slack callbacks (P2-23), sandbox with no prod credentials (P2-16), redaction retained from Phase 1.
- **Testing:** each step ships its own acceptance test; weekly integration gates at P2-09, P2-15, P2-21, P2-26, P2-30, P2-37.
- **Configuration:** all new settings in `config.py` + `.env.example` (DB, Redis, Slack, SMTP, Twilio, checkpointer flag, HMAC secrets).
- **Backward compatibility:** Phase 1 CLI remains functional; new features behind flags so local demo still works.
- **CI/CD:** lint + unit + integration + eval (P2-36) on every change.

---

## 8. Definition of Done

**Per step:** builds; acceptance test passes; no regression in Phase 1 tests; config documented; logged/traced where applicable.

**Per week:** the week's integration test passes; deliverable demoed; exit criteria signed off.

**Program (Phase 2 complete):**
- MTTD ≈ 0 s and MTTR ≤ 15 min measured in production.
- ≥ 70% of qualifying incidents auto-resolved.
- 0 production incidents caused by an OpsFlow-applied fix.
- 100% of incidents fully traced and audited; approvals durable across restarts.
- Eval harness green in CI (false-safe rate = 0).

---

## 9. Immediate Next Action

**Start P2-01** (repo & local infrastructure setup), then P2-02 (DB models/migrations) and P2-03 (FastAPI skeleton).

**Decisions needed first:**
1. Canary platform: Argo Rollouts vs Flagger → *recommend Argo Rollouts*.
2. Sandbox isolation: Docker-in-Docker vs ephemeral K8s pods → *recommend K8s pods*.
3. Inference at scale — **DECIDED**: paid hosted API for dev/demo, local Ollama as fallback.
4. Approval SLA + escalation tree owners → *confirm policy*.

---

*Prepared by [Your Name], AI/ML Engineer · OpsFlow AI Phase 2 Build Plan · 09 Oct 2026*
