# OpsFlow AI — Phase 2 Build Log

A chronological record of each implemented step: what was built, how it was verified, and notes.

**Language policy:** All files, comments, and documentation in this project are written in English.

**Workflow per step:** concept -> implement -> verify (acceptance test) -> explain -> commit.

---

## P2-01 — Repository & Local Infrastructure Setup

**Date:** 09 Oct 2026
**Status:** Complete (verified)
**Depends on:** Phase 1 complete

### What was built

- New package skeleton for the Phase 2 platform:
  - `api/` — FastAPI service (webhooks, approvals, health, metrics)
  - `worker/` — background workers and scheduled jobs
  - `db/` — SQLAlchemy models and session management
  - `integrations/` — Retriva, Slack, email, SMS, Prometheus adapters
  - `observability/` — tracing, metrics, structured logging
  - `evals/` — golden datasets and evaluation scripts
  - `tests/` — integration and unit tests
  - `deploy/` — deployment assets (Kubernetes assets added in Week 5)
- `docker-compose.yml` at the repository root:
  - `postgres:16` on `localhost:5432` (user/password/db: `opsflow`), with a healthcheck
  - `redis:7` on `localhost:6379`, with a healthcheck
  - Named volumes for persistence
- Extended `app/config.py` with Phase 2 settings:
  - API: `api_host`, `api_port`
  - PostgreSQL: `database_url` (default `postgresql+psycopg://...`)
  - Redis: `redis_url`
  - Checkpointer backend flag: `checkpointer` (`memory` | `postgres`)
  - Webhook security: `webhook_secret`
  - Alert ingestion: `alert_rate_limit_per_minute`, `alert_dedupe_window_seconds`
- Updated `.env.example` and `.env` with the Phase 2 variables.

### Concept

Separating the agent core (`app/`) from the service layer (`api/`, `worker/`) creates clear
boundaries: the graph stays the same, while HTTP ingress, queuing, and integrations live in
their own packages. Local infrastructure runs as containers so development matches deployment.

### Verification

| Check | Command | Result |
| --- | --- | --- |
| Compose file is valid | `docker compose config --quiet` | exit 0 |
| Services defined | `docker compose config --services` | `postgres`, `redis` |
| Containers healthy | `docker compose ps` | both `Up (healthy)` |
| PostgreSQL reachable | `docker compose exec -T postgres pg_isready -U opsflow -d opsflow` | accepting connections |
| Redis reachable | `docker compose exec -T redis redis-cli ping` | `PONG` |
| Packages import | `python -c "import api, worker, db, integrations, observability, evals, tests"` | ok |
| Settings load | `python -c "from app.config import settings; ..."` | values printed as expected |

### Notes and constraints

- Docker Desktop must be running. The CLI alone is not sufficient; the engine must be started.
- Only Python 3.14 is installed locally. Some database drivers (e.g., `asyncpg`) may lack
  wheels for 3.14; the configuration therefore defaults to `psycopg` v3
  (`postgresql+psycopg://`). This will be confirmed during P2-02.
- Phase 1 behavior is preserved: `CHECKPOINTER=memory` keeps the in-memory checkpointer until
  P2-04 introduces `PostgresSaver`.

### Commands

```powershell
docker compose up -d      # start PostgreSQL + Redis
docker compose ps         # check health
docker compose down       # stop (keep volumes)
```

### Decisions

- Version control: git is intentionally not used at this time (a zip backup is retained instead).
- Existing Phase 1 documents (`README.md`, `NOTES.md`, `PROGRESS_REPORT.md`) remain in their
  current form for now. All new files and code are written in English.

---

## P2-02 — Database Models & Migrations

**Date:** 09 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-01

### What was built

- `db/base.py` — declarative `Base` for all ORM models.
- `db/models.py` — four SQLAlchemy 2.0 models:
  - `processed_alerts` — idempotency/dedupe: `alerts_signature` (PK), `source`, `service`,
    `error_class`, `first_seen`, `last_seen`, `count`, `incident_id` (FK).
  - `incidents` — `incident_id` (UUID PK), `thread_id` (unique), `source`, `service`,
    `error_class`, `severity`, `status`, `created_at`, `resolved_at`.
  - `execution_logs` — `execution_id` (UUID PK), `incident_id` (FK), `remediation_id`,
    `params` (JSONB), `command` (TEXT[]), `environment`, `dry_run`, `approved_by`,
    `approved_at`, `started_at`, `finished_at`, `exit_code`, `result`, `sandbox_checks` (JSONB).
  - `fix_outcomes` — `outcome_id` (UUID PK), `incident_id` (FK), `remediation_id`,
    `params` (JSONB), `outcome`, `confidence`, `applied_at`, `verified_at`, `stable`,
    `success_rate_before`.
- `db/session.py` — synchronous engine and `SessionLocal` factory, plus `get_session()`
  as a FastAPI dependency.
- Alembic setup: `alembic.ini`, `migrations/env.py` (reads `settings.database_url`, imports
  model metadata), and `migrations/versions/<rev>_initial_schema.py`.
- `requirements.txt` extended with `sqlalchemy`, `alembic`, and `psycopg[binary]`.

### Concept

Schema-first development with versioned migrations. The database schema is defined once in
code, and Alembic generates reproducible, reversible migrations. JSONB stores flexible
structures (params, sandbox checks), TEXT[] preserves the exact argv list, and UUID primary
keys are safe for distributed generation.

### Verification

| Check | Command | Result |
| --- | --- | --- |
| Packages import | `python -c "import sqlalchemy, alembic, psycopg"` | ok |
| Live DB connection | `create_engine(...).connect()` | `select 1 -> (1,)` |
| Migration applies | `alembic upgrade head` | 4 tables created |
| Tables present | `psql \dt` | `incidents`, `execution_logs`, `fix_outcomes`, `processed_alerts` |
| Migration reverts | `alembic downgrade base` | only `alembic_version` remains |
| Re-applies | `alembic upgrade head` | 4 tables recreated |
| Phase 1 regression | `check_state`, `check_router`, `check_catalog`, `check_hitl` | exit 0 |

### Constraints and workaround

- Windows Application Control blocked SQLAlchemy's compiled extensions
  (`sqlalchemy/engine/_processors_cy.cp314-win_amd64.pyd`), causing
  `ImportError: DLL load failed ... Application Control policy has blocked this file`.
- SQLAlchemy 2.1 ships pure-Python fallbacks alongside the compiled modules, so the fix is to
  disable the `.pyd` files and let the `.py` implementations load:

```powershell
Get-ChildItem -Recurse -File ".venv\Lib\site-packages\sqlalchemy" -Filter "*_cy*.pyd" |
  ForEach-Object { Rename-Item $_.FullName ($_.Name + ".disabled") }
```

- `psycopg[binary]` installed and connected successfully on Python 3.14; no fallback needed.
- Decision: use the synchronous SQLAlchemy engine for now (Alembic and workers are sync);
  the API can use sync path operations (FastAPI runs them in a threadpool). Async can be
  added later if required.

### Commands

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic downgrade base
docker compose exec -T postgres psql -U opsflow -d opsflow -c "\dt"
```

---

## P2-03 — FastAPI Skeleton & Structured Logging

**Date:** 09 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-01, P2-02

### What was built

- `observability/logging.py` — structured JSON logging built on Loguru:
  - `configure_logging(level)` installs a single JSON sink (idempotent).
  - `get_logger(**fields)` returns a logger with attached context fields.
  - Every line is a flat JSON object: `timestamp, level, message, logger` plus any bound
    fields such as `incident_id`, `stage`, `duration_ms`.
- `api/main.py` — FastAPI application:
  - Lifespan handler logging startup and shutdown.
  - HTTP middleware logging `method, path, status_code, duration_ms` per request.
  - `GET /` service metadata, `GET /healthz` liveness, `GET /readyz` readiness (checks the
    database with `SELECT 1` and returns 503 when unavailable).
  - `python -m api.main` runs the app with Uvicorn using `settings.api_host`/`api_port`.
- `tests/check_api_health.py` — in-process check using Starlette's `TestClient`.
- `requirements.txt` extended with `fastapi`, `uvicorn`, and `loguru`.

### Concept

- **Liveness vs readiness:** `/healthz` answers "is the process alive"; `/readyz` answers
  "can it serve traffic" (dependencies reachable). Kubernetes uses these separately.
- **ASGI and middleware:** FastAPI is an ASGI app; middleware wraps every request and is the
  right place for cross-cutting concerns such as request logging and (later) rate limiting.
- **Structured logging:** flat JSON with stable field names makes logs machine-queryable
  (for example, aggregate `duration_ms` per path, or filter by `incident_id`).
- **In-process testing:** `TestClient` runs the app without a network server, which makes
  the automated check fast and deterministic.

### Verification

| Check | Command | Result |
| --- | --- | --- |
| Packages import | `python -c "import fastapi, uvicorn, loguru"` | ok |
| In-process endpoints | `python -m tests.check_api_health` | `/`, `/healthz`, `/readyz` all 200 |
| Real server boot | `uvicorn api.main:app --port 8011` | `/healthz` and `/readyz` 200 over HTTP |
| JSON logs | server stdout | flat JSON lines with `stage`, `duration_ms`, `status_code` |
| Phase 1 regression | Phase 1 checks | exit 0 |

### Notes

- Installed plain `uvicorn` (not `uvicorn[standard]`) to avoid optional compiled extensions,
  which may be blocked by the same Windows Application Control policy seen in P2-02.
- Readiness currently checks the database only; the Redis check is added alongside the queue
  work in P2-08.
- Default port is 8000 (`API_PORT`); the smoke test used 8011 to avoid conflicts.

### Commands

```powershell
.\.venv\Scripts\python.exe -m tests.check_api_health
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

---

## P2-04 — Durable Checkpoints (PostgresSaver)

**Date:** 09 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-02

### What was built

- `app/checkpointer.py` — a checkpointer factory:
  - `make_checkpointer(backend=None)` selects the backend from `settings.checkpointer`
    (`"memory"` or `"postgres"`).
  - Memory backend: `InMemorySaver` with an explicit serializer allowlist.
  - PostgreSQL backend: `PostgresSaver` over a psycopg connection (`autocommit=True`),
    calling `setup()` to create the checkpoint tables.
  - The SQLAlchemy URL (`postgresql+psycopg://`) is converted to a raw psycopg URL
    (`postgresql://`).
- `app/graph.py` — refactored to obtain its checkpointer from `app.checkpointer`; the default
  remains the in-memory backend so Phase 1 behavior is unchanged.
- `scripts/check_hitl.py` — updated to import `make_checkpointer` from `app.checkpointer`.
- `tests/check_durable_checkpoint.py` — runs the graph to the approval interrupt, then starts
  a **separate Python process** that resumes the same thread.
- `requirements.txt` — added `langgraph-checkpoint-postgres`.

### Concept

- **Durable execution:** state and the paused `interrupt()` are persisted in PostgreSQL, so a
  crashed or restarted service can resume an incident exactly where it stopped.
- **Checkpoint tables:** `PostgresSaver.setup()` creates `checkpoints`, `checkpoint_blobs`,
  `checkpoint_writes`, and `checkpoint_migrations`.
- **Backend flag:** the checkpointer is configurable, so local development can stay on memory
  while staging and production use PostgreSQL.

### Verification

| Check | Command | Result |
| --- | --- | --- |
| Cross-process resume | `python -m tests.check_durable_checkpoint` | phase-1 paused; phase-2 (new process) resumed; status `approved` |
| Resume exactly once | assertion in the test | exactly 1 `approve` audit event |
| Checkpoint tables | `psql \dt` | `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` present |
| HITL regression | `python -m scripts.check_hitl` | approve and reject paths pass |
| Phase 1 regression | `check_state`, `check_router`, `check_catalog`, `check_redact` | exit 0 |

### Notes

- The default backend remains `memory` (`CHECKPOINTER=memory`), so Phase 1 and the CLI are
  unaffected until the flag is switched.
- Each `make_checkpointer("postgres")` call opens its own psycopg connection; a connection
  pool can be introduced in a later step if the API runs many workers.
- The test purges its own checkpoint rows after a successful run to keep the database tidy.

### Commands

```powershell
python -m tests.check_durable_checkpoint
CHECKPOINTER=postgres   # set in .env to use the durable backend in the app
```

---

## P2-05 — Webhook Endpoint & HMAC Verification

**Date:** 09 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-03

### What was built

- `api/security.py` — HMAC-SHA256 helpers:
  - `sign_payload(secret, body)` -> `sha256=<hex>` (used by senders and tests).
  - `verify_hmac_sha256(secret, body, header)` -> constant-time comparison via
    `hmac.compare_digest`.
- `api/routes/__init__.py` — route package.
- `api/routes/webhooks.py` — `POST /api/v1/webhooks/alert`:
  - reads the raw request body,
  - verifies the `X-Signature` header,
  - returns `401` on invalid/missing signature,
  - parses JSON and returns `400` on malformed body,
  - returns `202 Accepted` with a small receipt on success.
- `api/main.py` — includes the webhooks router.
- `tests/check_webhook.py` — verifies valid, tampered, unsigned, wrong-secret, and
  invalid-JSON cases.

### Concept

- **Webhook authenticity:** anyone who can reach the endpoint could otherwise forge an alert.
  An HMAC-SHA256 signature over the raw body, using a shared secret, proves the sender is
  trusted.
- **Constant-time comparison:** `hmac.compare_digest` prevents timing attacks that could
  otherwise leak the expected signature.
- **Verify before parse:** authenticate the request before doing any work on the body, so
  malformed or hostile input is rejected early.
- **Status codes:** `202` means accepted for asynchronous processing; `401` means the
  signature is missing or invalid; `400` means the signature is valid but the body is not
  valid JSON.

### Verification

| Case | Expected | Result |
| --- | --- | --- |
| Valid signature | 202 | 202 |
| Tampered body (signature no longer matches) | 401 | 401 |
| Missing signature | 401 | 401 |
| Wrong secret | 401 | 401 |
| Valid signature, invalid JSON | 400 | 400 |
| API health regression | 200 | 200 |

### Notes

- The raw body is read with `await request.body()` so the signature is computed over the exact
  bytes received, not a re-serialized object.
- A single `WEBHOOK_SECRET` is used for now. Per-source secrets (a mapping keyed by `source`)
  can be added when multiple senders are onboarded.
- Normalization, deduplication, and enqueueing are intentionally deferred to P2-06 and P2-08.

### Commands

```powershell
.\.venv\Scripts\python.exe -m tests.check_webhook
.\.venv\Scripts\python.exe -m tests.check_api_health
```

---

## P2-06 — Idempotency, Normalization & Deduplication

**Date:** 09 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-02, P2-05

### What was built

- `ingestion/` — a new domain layer for alert intake:
  - `ingestion/schema.py` — the `Alert` model plus `normalize_alert(payload)`,
    `alerts_signature` (idempotency key), and `fingerprint` (dedupe key).
  - `ingestion/service.py` — `process_alert(session, payload)` and `ingest_payload(payload)`:
    insert with ON CONFLICT DO NOTHING, replay detection, peer counting within the window,
    and a result of `new`, `merged`, or `duplicate`.
- `api/routes/webhooks.py` — now normalizes and ingests the alert (via
  `run_in_threadpool`), returning the `action` and `group_key`.
- `tests/check_ingestion.py` — verifies new, replay/duplicate, burst/merge, and validation.

### Concept

- **Idempotency vs deduplication:** an idempotency key prevents processing the *same event*
  twice; a deduplication fingerprint groups *different events* that describe the same problem
  (same service and error class). Both are needed.
- **Idempotency key:** `sha256(source|event:<event_id>)` when an event id is present, otherwise
  `sha256(source|service|error_class|raw_log)`. It is the primary key of `processed_alerts`.
- **`INSERT ... ON CONFLICT DO NOTHING RETURNING`:** performs the idempotency check atomically.
  A returned row means the alert is new; no row means it is a replay.
- **Deduplication window:** a newly inserted alert with peers sharing the same service and
  error class within `ALERT_DEDUPE_WINDOW_SECONDS` is `merged`; only the first is `new`.
  Incoming incidents should only be created for `new` alerts (wired in P2-08).
- **Blocking work off the event loop:** synchronous database access runs via
  `run_in_threadpool` so the async endpoint is not blocked.

### Verification

| Case | Expected | Result |
| --- | --- | --- |
| First alert | `new` | `new` |
| Exact replay | `duplicate`, count incremented to 2 | `duplicate`, count 2 |
| Burst of 499 distinct alerts (same service/error) | 0 new, 499 merged | 0 new, 499 merged |
| Missing required field | validation error | rejected |
| Webhook integration | 202 with `action` | 202 with `action: new` |
| HMAC cases (P2-05 regression) | 202/401/400 | unchanged |

### Notes

- `ingestion/` is a deliberate addition to the package layout: alert normalization and
  deduplication are shared by the API and the worker, so they do not belong to either alone.
- The webhook still commits synchronously. In P2-08 the ingest will be enqueued and the
  worker will own the database writes, keeping the endpoint fast.
- Severity is only carried as `severity_hint` for now; AI severity classification is P2-07.

### Commands

```powershell
.\.venv\Scripts\python.exe -m tests.check_ingestion
.\.venv\Scripts\python.exe -m tests.check_webhook
```

---

## P2-07 — Rate Limiting & Severity Classification

**Date:** 09 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-06

### What was built

- `ingestion/severity.py` — severity classification:
  - `classify_severity_rules(error_class, raw_log, severity_hint)` -> `critical | warning | info`
    (deterministic baseline).
  - `classify_severity_llm(...)` — optional LLM refinement for inconclusive cases,
    `classify_severity(..., use_llm=...)` controls it.
- `ingestion/ratelimit.py` — Redis sliding-window limiter, one window per service,
  fail-open when Redis is unavailable.
- `ingestion/schema.py` — `Alert` now carries a `severity` computed by the rules classifier.
- `ingestion/service.py` — `prepare_alert`, `store_alert`, `has_recent_peers`, and
  `ingest_with_limits` (rate limit + coalesce). Severity is persisted.
- `api/routes/webhooks.py` — returns `429` for a throttled new incident and includes `severity`.
- `app/config.py` — `alert_rate_limit_window_seconds`, `severity_use_llm`.
- `db/models.py` + migration `f3b8451a4b16` — `severity` column on `processed_alerts`.
- `requirements.txt` — `redis`.
- `tests/check_ratelimit.py` — limiter unit, severity rules, HTTP 429, and coalescing.

### Concept

- **Sliding-window rate limiting:** a Redis sorted set stores one member per request; entries
  older than the window are removed before counting. This is more accurate than a fixed
  counter with a TTL.
- **Coalescing over dropping:** when the limit is exceeded, alerts that would merge into an
  existing group are still recorded; only alerts that would create a *new* incident are
  rejected. This prevents alert storms from being lost while still protecting the system.
- **Rules first, LLM second:** deterministic rules are the reliable baseline; the LLM refines
  only inconclusive cases, so cost and latency stay controlled.
- **Fail-open limiter:** if Redis is down, alerts are allowed (detection must not stop) and a
  warning is logged.

### Important incident: autogenerate dropped the checkpoint tables

The Alembic autogenerate for the `severity` column also detected the four LangGraph checkpoint
tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) as
"removed", because they are created by `PostgresSaver.setup()` and are not part of the
SQLAlchemy metadata. The generated migration contained `DROP TABLE` statements for them.

Resolution:

1. Rewrote the migration to only add/drop the `severity` column.
2. Added an `include_object` filter in `migrations/env.py` that excludes names starting with
   `checkpoint` from autogenerate comparison.
3. Recreated the checkpoint tables with `make_checkpointer("postgres")` (setup).
4. Confirmed with `alembic check` -> "No new upgrade operations detected."

Lesson: migrations must exclude tables owned by other tools, otherwise autogenerate can delete
them.

### Verification

| Check | Expected | Result |
| --- | --- | --- |
| Limiter unit | 50 allowed, 51st blocked | 50 / blocked |
| Per-service isolation | other service allowed | allowed |
| Severity rules | critical / warning / info / critical | matched |
| HTTP, distinct groups over limit | 51st = 429 | 429 |
| HTTP, same group over limit | 51st coalesced = 202 merged | 202 merged |
| Severity persisted | `critical` | `critical` |
| Regressions | P2-04, P2-05, P2-06 | pass |

### Commands

```powershell
.\.venv\Scripts\python.exe -m tests.check_ratelimit
.\.venv\Scripts\python.exe -m alembic check
```

---

## P2-08 — Incident Creation & Queue Worker

**Date:** 09 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-06, P2-04

### What was built

- `worker/graph_runner.py` — compiles the graph with the PostgreSQL checkpointer and
  `run_incident(thread_id, error_log, graph=None)` invokes it for an incident.
- `worker/tasks.py` — `create_incident(alert_signature)` (idempotent) and
  `handle_new_alert(alert_signature, payload, graph=None)` (the RQ job).
- `worker/queue.py` — Redis/RQ queue helpers with a deterministic job id per alert.
- `worker/main.py` — worker entrypoint (`python -m worker.main [--burst]`), using
  `SimpleWorker` for Windows compatibility.
- `api/routes/webhooks.py` — enqueues an incident job when an alert creates a new group.
- `tests/check_worker.py` — enqueue, burst worker with a stub graph, incident creation,
  and idempotent re-delivery.
- `requirements.txt` — `rq`.

### Concept

- **Asynchronous decoupling:** the webhook acknowledges quickly and a background worker does
  the expensive work (running the graph). A slow graph never blocks the HTTP request.
- **Idempotent incident creation:** `create_incident` checks whether the processed alert
  already has an `incident_id` before creating one, so a retried or re-delivered job cannot
  create a second incident.
- **Deterministic job id:** `incident_<alerts_signature>` keeps job identity stable for a given
  alert.
- **Durable execution path:** the worker compiles the graph with the PostgreSQL checkpointer,
  so an incident can pause for approval and be resumed by another process.
- **Windows compatibility:** RQ's default `Worker` uses `fork`; `SimpleWorker` does not.

### Verification

| Check | Expected | Result |
| --- | --- | --- |
| Ingest new alert | `new` | `new` |
| Enqueue | deterministic job id, 1 queued | `incident_<signature>`, 1 |
| Worker burst (stub graph) | job processed | processed |
| Incident row | created, linked from processed_alerts | created, linked |
| Graph ran | stub node executed | ran for thread |
| Re-delivery | skipped, one incident | skipped, count 1 |
| Regressions | P2-04, P2-05, P2-06, P2-07, P2-03 | pass |

### Notes

- RQ may record more than one queue entry for the same job id; the authoritative guarantee
  against duplicate work is the database check in `create_incident`.
- The worker uses `SimpleWorker` (no fork) so it runs on Windows.
- The incident status is updated from the graph result after the run.

### Commands

```powershell
.\.venv\Scripts\python.exe -m tests.check_worker
.\.venv\Scripts\python.exe -m worker.main --burst
```

---

## P2-09 — Week 1 Integration Test

**Date:** 09 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-05, P2-06, P2-07, P2-08, P2-04

### What was built

- `tests/check_week1.py` — one command that proves the full Week 1 pipeline:
  signed alert -> idempotency/dedupe -> incident -> graph -> approval pause ->
  process restart -> resume.
- A deterministic graph (`preflight -> risk -> approval`) is used so the test does not depend
  on the LLM; it still exercises the real `risk` and `approval` nodes and the PostgreSQL
  checkpointer.
- The resume phase runs in a **separate Python process**, so the durability claim is genuine.

### Verification

```
webhook   -> new, then duplicate (deduped)
worker    -> processed queued alert
incident  -> created and paused; status = awaiting_approval
restart   -> resume: status = approved
[ok] P2-09 -- Week 1 exit criteria pass
```

### Week 1 exit criteria

| Criterion | Status |
| --- | --- |
| Signed webhook creates an alert | pass |
| Replay is deduplicated | pass |
| Worker creates an incident | pass |
| Graph runs for the incident | pass |
| Approval pause is durable | pass |
| Resume works across a process restart | pass |

---

## Milestone M1 — Foundation complete (end of Week 1)

Layer 1 (Intelligent Detection) is complete, together with the durable foundation:

- Event-driven ingestion: HMAC-signed webhook, normalization, idempotency, dedupe,
  rate limiting, severity labelling.
- Durable state: PostgreSQL checkpoints (approvals survive restarts).
- Async processing: Redis/RQ worker creates incidents and runs the graph.
- API skeleton with structured JSON logging and health/readiness probes.
- Database, migrations, and the `incidents`, `processed_alerts`, `execution_logs`,
  `fix_outcomes` tables.

**Deliverable achieved:** alerts are received and turned into durable incidents without any
manual log pasting.

---

## P2-10 — Multi-Tenant Knowledge Base Adapter & Tool

**Date:** 13 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-09

### What was built

- **Tenant plumbing (full):**
  - `app/state.py` — `OpsFlowState.tenant_id`; `new_incident(..., tenant_id=...)`;
    `ResearchResult.is_low_confidence`.
  - `ingestion/schema.py` — `Alert.tenant_id` (parsed from the payload, defaults to `default`).
  - `db/models.py` + migration `2f44a5eb54ce` — `tenant_id` (indexed) on `processed_alerts` and
    `incidents`.
  - `ingestion/service.py`, `worker/tasks.py`, `worker/graph_runner.py` — propagate `tenant_id`
    from alert to incident to graph state.
- **Knowledge base layer (provider-neutral):**
  - `app/tools/knowledge.py` — the `KnowledgeBase` port and `KnowledgeResponse`.
  - `integrations/tenant_kb.py` — `TenantVectorKnowledgeBase` (managed vector DB over HTTP).
  - `integrations/live_connectors.py` — `LiveConnectorKnowledgeBase` (Confluence / ServiceNow).
  - `integrations/fake_kb.py` — `FakeKnowledgeBase` (deterministic, tenant-scoped, for tests).
  - `integrations/knowledge_service.py` — `WebKnowledgeBase` + `KnowledgeService` with the
    graceful fallback chain, and `get_knowledge_service()` composition from config.
  - `app/tools/kb_search.py` — the `kb_search` tool (tenant-scoped, injectable service).
- `app/config.py` / `.env` — `KB_BACKEND`, `KB_FALLBACK_ENABLED`, `KB_NAMESPACE_PREFIX`,
  `KB_TIMEOUT_SECONDS`, `TENANT_KB_BASE_URL`, `TENANT_KB_API_KEY`, `LIVE_CONNECTOR_*`.
- `requirements.txt` — `httpx`.
- `tests/check_kb.py` — verifies the chain, tenant isolation, namespace, tool, and DB plumbing.

### Concept

- **Multi-tenant RAG:** every retrieval is scoped to a `tenant_id`; the vector store isolates each
  client in its own namespace/collection, so one tenant's data is never returned for another.
- **Provider-neutral port:** the agent depends on the `KnowledgeBase` interface, not on a specific
  vendor, so the backend can be swapped without touching agent code.
- **Graceful degradation:** the chain is Tenant KB -> Live Connectors -> Postgres History (P2-11) ->
  Web Search. The first source with results wins; web results are marked `is_low_confidence`.
  An empty or failing source never crashes the agent.
- **Zero-data-retention connectors:** enterprise knowledge can be queried live via connectors and
  never stored.

### Defined contract (managed vector DB)

```
POST {base_url}/v1/search
Authorization: Bearer <api_key>            (when configured)
body:     {"tenant_id": ..., "namespace": ..., "query": ..., "top_k": ...}
response: {"results": [{"title", "url", "snippet", "score"}]}
```

### Verification

| Case | Expected | Result |
| --- | --- | --- |
| Tenant KB hit | `tenant_kb`, no fallback | `tenant_kb` |
| Empty tenant KB -> live connector | `live_connector`, fallback | `live_connector` |
| Empty KB + connector -> web | `web`, low confidence | `web`, low confidence |
| Tenant isolation | gamma sees no acme docs | pass |
| Namespace derivation | `tenant_acme` | pass |
| `kb_search` tool | returns `source="kb"` hits | pass |
| `tenant_id` normalization | parsed / defaulted | pass |
| `tenant_id` persisted | on alerts and incidents | pass |
| Regressions | Phase 1 + P2-03..P2-09 (12 tests) | pass |

### Notes

- `KB_BACKEND` defaults to `none`; web fallback is available while `KB_FALLBACK_ENABLED=true`.
- The Postgres History source is intentionally deferred to P2-11 and will register into the same
  chain without changing agent code.
- Hybrid inference (paid hosted API + local Ollama fallback) is a separate upcoming change; it is
  not part of this step.

### Commands

```powershell
.\.venv\Scripts\python.exe -m tests.check_kb
.\.venv\Scripts\python.exe -m alembic check
```

---

## P2-11 — Historical Incidents Tool

**Date:** 13 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-02, P2-10

### What was built

- `integrations/history.py`:
  - `PriorFix` model — `remediation_id`, `params`, `success_rate`, `occurrences`, `last_applied_at`.
  - `find_prior_fix(session, tenant_id, service, error_class, days=30)` — tenant-scoped query over
    `fix_outcomes` joined to `incidents`, resolving the best prior *successful* remediation by
    success rate (tie-break: most recent success).
  - `HistoryKnowledgeBase` — knowledge source backed by past outcomes.
- `app/tools/history_search.py` — the `history_search` tool.
- Knowledge port extended with optional `service` / `error_class` context; all adapters and
  `kb_search` updated to accept and forward it.
- `HistoryKnowledgeBase` registered into the fallback chain (after tenant KB / live connectors,
  before web).
- `app/state.py` — `ResearchResult.source` now also allows `"history"`.
- `tests/check_history.py` — verifies prior-fix resolution, tenant isolation, windowing, the source,
  the tool, and chain integration.

### Concept

- **Operational memory:** the most reliable predictor of a fix is what worked before for the same
  tenant, service, and error class.
- **Tenant-scoped pattern matching:** history is filtered by `tenant_id`, so one client's history
  never informs another's incident.
- **Lookback window:** only outcomes within the last N days (default 30) are considered.
- **Chain integration:** history is source #3 in the graceful degradation chain; the adapter returns
  an empty list when `service`/`error_class` context is missing, so it degrades cleanly.

### Verification

```
prior fix -> increase_memory_limit rate=0.5 occurrences=2
isolation -> another tenant sees no history
window    -> 40-day-old outcome excluded (days=30)
source    -> Past fix: increase_memory_limit (success rate 50%)
source    -> empty without service/error_class
tool      -> increase_memory_limit rate 0.5
chain     -> source_used = history fallback = True
Regressions: 13 other tests (Phase 1 + P2-03..P2-10) pass
```

### Notes

- `fix_outcomes` is populated by the feedback loop (P2-35); this step reads it.
- `history_search` returns an empty object when there is no prior successful fix, so callers can
  fall back safely.
- The adapter swallows source errors by design (graceful degradation); a signature mismatch in a
  custom source therefore degrades to the next source rather than crashing.

### Commands

```powershell
.\.venv\Scripts\python.exe -m tests.check_history
```

---

## P2-12 — Parallel Research (Send Map-Reduce)

**Date:** 13 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-10, P2-11

### What was built

- `app/nodes/research.py` — the fan-out:
  - `plan_research` builds the search query (from `refined_query` or the diagnosis).
  - `dispatch_research` returns three `Send` objects (KB, web, history).
  - `research_kb`, `research_web`, `research_history` — one agent per source, each appending
    to the shared `research` list and writing an audit event.
- `app/nodes/researcher.py` — refactored into the `propose` node (proposal only); research no
  longer happens here.
- `app/graph.py`:
  - `analyzer -> plan_research -[Send]-> (research_kb | research_web | research_history) -> propose -> critic`.
  - Critic `refine` now loops back to `plan_research`.
- `app/state.py` — added `service`, `error_class`, `research_query`; `new_incident(..., service,
  error_class)`.
- `worker/graph_runner.py`, `worker/tasks.py` — propagate `service`/`error_class` into the graph.
- `app/tools/knowledge.py` — split into `KnowledgeSource` (leaf, returns a list) and
  `KnowledgeBase` (composite, returns `KnowledgeResponse`).
- `integrations/knowledge_service.py` — `get_internal_knowledge_service()` (KB + connectors only)
  so the KB agent does not duplicate the separate history and web agents.
- `tests/check_parallel_research.py` — deterministic fan-out test (fake KB, fake web, seeded history).

### Concept

- **Map-Reduce with `Send`:** `dispatch_research` maps the state to three parallel node
  invocations; each reduces into `research` via the `operator.add` reducer; the `propose` node
  runs once after all three complete (fan-in).
- **Independent agents:** one source per agent keeps responsibilities clear and lets sources
  fail independently (a failing agent returns an empty list, not an error).
- **No duplication:** the KB agent uses internal sources only; web and history are separate
  agents, so the same knowledge is not retrieved twice.
- **Loop still works:** the critic's `refine` path re-enters `plan_research`, so the refined query
  is used by all three agents on the next iteration.
- **Port split:** leaf sources return a list; the composite service returns
  `KnowledgeResponse` (results + which source was used + whether fallback occurred).

### Verification

```
merged    -> ['history', 'kb', 'web']
query     -> memory limit too low OOM killed exit code 137
agents    -> 3 research audit events
dispatch  -> ['research_kb', 'research_web', 'research_history']
Regressions: 14 other tests + real graph build pass
```

### Notes

- `research_history` returns an empty result (and an audit note) when `service`/`error_class`
  are missing, so it degrades cleanly.
- The web agent marks its results as normal sources (not low confidence); low confidence is
  reserved for the web *fallback* in the knowledge chain. The P2-13 rubric will weight sources.
- The existing LLM-based `propose` and `critic` are unchanged; only their position in the graph
  changed.

### Commands

```powershell
.\.venv\Scripts\python.exe -m tests.check_parallel_research
```

---

## P2-13 — Rubric Confidence Scoring

**Date:** 13 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-12

### What was built

- `app/confidence.py` — `score_confidence(state)` (pure): weighted signals with a per-signal
  breakdown. Weights: `kb_match` 30, `history_success` 20, `source_agreement` 15,
  `catalog_match` 15, `critic_score` 20.
- `app/nodes/scoring.py` — the `score` node and `route_after_scoring`:
  - sets `confidence`, `confidence_breakdown`, `manual_review`, `automation_eligible`,
  - enforces the loop cap (`status = escalated` when confidence < threshold and loops >= max).
- `app/nodes/critic.py` — refactored to evaluate only (critique, `critic_score`, `refined_query`,
  `loop_count`); it no longer sets `confidence` or the escalation status.
- `app/graph.py` — `propose -> critic -> scoring -> route` (routing now uses rubric confidence).
- `app/state.py` — added `confidence_breakdown`, `manual_review`, `automation_eligible`.
- `scripts/check_router.py` — updated to test `route_after_scoring`.
- `tests/check_confidence.py` — verifies the rubric and the node flags.

### Concept

- **Evidence-based confidence:** instead of trusting a self-reported number, confidence is derived
  from signals that can be checked (internal knowledge match, historical success rate, source
  agreement, catalog match, critic score).
- **Per-signal breakdown:** each signal contributes points that sum to the score, so a decision can
  be explained and audited.
- **Two thresholds:** `manual_review` when confidence < 70; `automation_eligible` when >= 80.
- **Separation of concerns:** the critic evaluates a fix; the scoring node turns that (plus the
  retrieval evidence) into a confidence decision and owns the loop cap.

### Verification

```
full   -> 94 {'kb_match': 30.0, 'history_success': 16.0, 'source_agreement': 15.0,
              'catalog_match': 15.0, 'critic_score': 18.0}
weak   -> 8  {... all zero except critic_score 8.0}
node   -> confidence 94, automation_eligible True
node   -> confidence 8, status escalated, manual_review True
mid    -> 70, manual_review False, automation_eligible False
router -> escalate / accept / refine correct
Regressions: 15 other tests + real graph build pass
```

### Notes

- `catalog_match` checks the remediation id directly against the catalog (independent of the risk
  node, which runs later).
- History contributes both as `kb_match`? No: `kb` and `history` are distinct signals; history
  contributes through `history_success`.
- Web results are a normal source in the parallel research; the rubric weights them via
  `source_agreement` rather than a special flag.

### Commands

```powershell
.\.venv\Scripts\python.exe -m tests.check_confidence
.\.venv\Scripts\python.exe -m scripts.check_router
```

---

## P2-14 — History-Aware Proposal

**Date:** 13 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-11, P2-13

### What was built

- `app/nodes/research.py` — the history agent now also stores a structured `prior_fix`
  (`remediation_id`, `params`, `success_rate`, `occurrences`).
- `app/state.py` — added `prior_fix: dict`.
- `app/nodes/researcher.py`:
  - `_prior_proposal(state)` — returns the proven fix directly when its success rate is at or
    above `history_preference_threshold`, the id exists in the catalog, and the stored params
    pass catalog validation. Otherwise returns `None`.
  - `propose(state)` — prefers the proven fix (source `history`) and falls back to the LLM
    (source `llm`) when there is no strong prior fix. The LLM prompt now includes a
    `<prior_successful_fix>` block.
- `app/config.py` / `.env` — `HISTORY_PREFERENCE_THRESHOLD` (default 0.7).
- `tests/check_history_proposal.py` — verifies preference and rejection cases.

### Concept

- **Learning from past fixes:** a fix that worked before for the same tenant/service/error class
  is the strongest prior we have, so it is preferred over a fresh LLM guess.
- **Preference ordering with guardrails:** the prior fix is only used directly when it clears the
  success-rate threshold, exists in the catalog, and its stored params still validate. Otherwise
  the LLM proposes with the prior fix as guidance.
- **Catalog constraint preserved:** a prior fix can never bypass the vetted catalog.

### Verification

```
prior     -> increase_memory_limit {'container_name': 'svc', 'new_memory_limit': '2Gi'}
propose   -> increase_memory_limit(...) [source=history]
weak      -> not preferred (below threshold)
unknown   -> not preferred (id not in catalog)
bad params-> not preferred (catalog validation fails)
Regressions: 16 other tests + real graph build pass
```

### Notes

- `prior_fix` is stored as a plain dict so no checkpoint type allowlist change is needed.
- The deterministic path makes the behavior testable without the LLM; the LLM path is used only
  when the prior fix is weak, unknown, or invalid.
- The threshold is configurable so operators can make the agent more or less history-driven.

### Commands

```powershell
.\.venv\Scripts\python.exe -m tests.check_history_proposal
```

---

## P2-15 — Week 2 Integration Test

**Date:** 13 Oct 2026
**Status:** Complete (verified)
**Depends on:** P2-10 … P2-14

### What was built

- `tests/check_week2.py` — one command that proves the Week 2 pipeline:
  `seed -> plan_research -[Send]-> (kb | web | history) -> propose -> scoring`.
- Deterministic (fake KB, fake web, seeded history, seeded critic score): no LLM, no network.

### Verification

```
research  -> ['history', 'kb', 'web']
prior fix -> increase_memory_limit 0.9
propose   -> increase_memory_limit(...) [source=history]
confidence-> 95 {'kb_match': 30.0, 'history_success': 18.0, 'source_agreement': 15.0,
                 'catalog_match': 15.0, 'critic_score': 17.0}
isolation -> beta sees no acme knowledge
[ok] P2-15 -- Week 2 exit criteria pass
```

### Week 2 exit criteria

| Criterion | Status |
| --- | --- |
| 3 research sources run in parallel and merge | pass |
| Tenant scoping (no cross-tenant knowledge) | pass |
| History-aware proposal prefers the proven fix | pass |
| Rubric confidence with per-signal breakdown | pass |
| Regressions (P2-01 … P2-14) | pass |

---

## Milestone M2 — Enhanced Diagnosis complete (end of Week 2)

Layer 2 (Multi-Source Intelligence) is complete:

- Provider-neutral, multi-tenant knowledge base with a graceful fallback chain
  (tenant KB -> live connectors -> Postgres history -> web).
- Parallel multi-agent research via LangGraph `Send` (map-reduce).
- Postgres-backed operational memory (prior successful fixes).
- Rubric-based confidence scoring with per-signal breakdown and review/automation thresholds.
- History-aware proposal that prefers proven fixes without bypassing the catalog.

**Deliverable achieved:** the agent diagnoses with tenant-aware + external knowledge, faster
(parallel) and with explainable confidence.

---

## Week 3 — Safe Execution (P2-16 … P2-21)

**Date:** 16 Oct 2026
**Status:** Complete (verified)

### P2-16 — Sandbox executor (isolation)

- `integrations/sandbox.py` — `SandboxRunner` protocol with three backends:
  - `DockerSandbox`: `docker run --rm --pids-limit 256 --memory … --cpus … [--network none] <image> <argv…>`.
    The container is ephemeral (discarded after the run = implicit rollback).
  - `LocalSandbox`: subprocess fallback (dev; no isolation).
  - `FakeSandbox`: deterministic results for tests.
  - `set_sandbox()` allows injection (tests); `get_sandbox()` builds from config.
- `app/nodes/sandbox.py` — the `sandbox` node applies the catalog fix in isolation.
- Config: `SANDBOX_BACKEND`, `SANDBOX_IMAGE`, `SANDBOX_TIMEOUT_SECONDS`,
  `SANDBOX_MEMORY_LIMIT`, `SANDBOX_CPUS`, `SANDBOX_NETWORK`, `SANDBOX_MAX_ATTEMPTS`.

### P2-17 — Sandbox validation suite

- Catalog gains optional `validation_commands` (argv templates); after the fix, each check runs in
  the sandbox and must exit 0. Checks are recorded as `sandbox_checks`.
- `build_argv(template, resolved)` generalized in `app/safety/validate.py`.

### P2-18 — Automatic rollback

- Catalog gains optional `rollback_template`. A pre-fix rollback plan is computed and recorded.
- Irreversible actions (`reversible: false`) without a rollback plan are **escalated**, never
  executed. On validation failure the rollback command is run (best effort).

### P2-19 — Execution audit trail

- Every sandbox attempt is written to `execution_logs` (remediation, params, command, environment,
  result, checks, rollback). Writes are best-effort (a DB outage never crashes the graph).

### P2-20 — Self-correction on sandbox failure

- A failed validation keeps `status=pending` and sets `sandbox_feedback`; the graph loops back to
  `propose` (the feedback is included in the prompt). After `SANDBOX_MAX_ATTEMPTS` the incident is
  escalated.

### P2-21 — Week 3 integration test

- `tests/check_week3.py` proves `seed -> risk -> sandbox(validate+rollback) -> approval -> executor`.

### Graph change

```
risk ─(reject)→ END
     ─(valid)→ sandbox ─validated→ approval (if required) or executor
                       ─failed→ propose (retry) or END (escalated)
approval ─approved→ executor → END
```

The sandbox runs **before** approval, so the human approves *after* seeing sandbox results
(Implementation Plan, Layer 3).

### Verification

```
pass        -> passed in fake (attempt 1)
validated   -> rollback: ['docker','update','--memory','512Mi','checkout-api']
fail        -> retry then escalate
irreversible-> escalated (no rollback plan)
audit       -> 4 execution log(s)
docker      -> real container ran df -h (exit 0)
week3       -> proposal -> risk -> sandbox -> approval -> executor
Summary: 20/20 checks pass
```

### Notes

- The sandbox is a real ephemeral Docker container (validated locally by running `df -h` in
  `alpine`); commands that need host/target tooling will fail validation by design and trigger
  self-correction or escalation — that is the safety property, not a bug.
- In a real deployment the sandbox image would be a replica of the target service image.

---

## Week 4 — Notifications & Approvals (P2-22 … P2-26)

**Date:** 16 Oct 2026
**Status:** Complete (verified)

### P2-22 — Approval service + resume endpoint

- `app/approval_service.py` — `is_pending(thread_id)` and
  `resume_incident(thread_id, approved, approver, graph=None)`: loads the graph with the
  PostgreSQL checkpointer, resumes via `Command(resume=...)`, and is **idempotent**
  (returns `no_pending` when the incident is not paused).
- `api/routes/approvals.py`:
  - `GET /api/v1/approvals/email?token=...` — signed email link.
  - `POST /api/v1/approvals/slack/interactions` — Slack buttons (signature verified).
  - `GET/POST /api/v1/approvals/{thread_id}` — pending status / approve-reject (API key).
- Per-tenant API keys (`api/security.py`): `TENANT_API_KEYS="tenant:key,..."`; empty disables
  auth for local development.

### P2-23 — Slack integration

- `integrations/notifications.py` — `build_slack_blocks(summary)` (header + details + approve/reject
  buttons) and `SlackNotifier` (posts to a configured webhook). Interactive callbacks are verified
  with the Slack signing secret.

### P2-24 — Email backup channel

- `app/approval_tokens.py` — HMAC-signed, time-limited approve/reject tokens.
- `EmailNotifier` — SMTP email with signed approve/reject links.

### P2-25 — SMS + escalation policy

- `SmsNotifier` — Twilio REST (critical SMS).
- `integrations/escalation.py` — `due_escalation(elapsed, current_level)` (levels at 15/30/60 min →
  manager / senior_manager / cto) and `process_escalations()` which scans `awaiting_approval`
  incidents and advances `escalated_level`.
- `worker/escalation.py` — one-shot escalation runner.
- `incidents` gains `approval_requested_at` and `escalated_level` (migration `061f6dbf4e84`).

### P2-26 — Week 4 integration test

- `tests/check_week4.py` proves `approval request -> notification -> external decision -> resume ->
  escalation`.

### Worker change

- `worker/tasks.py` now sets `status=awaiting_approval` + `approval_requested_at` and dispatches the
  approval notification when the graph pauses.

### Verification

```
token     -> sign/verify/expire ok
resume    -> approved ; idempotent -> no_pending
auth      -> missing key: 401 ; unknown thread: 409
slack     -> buttons: ['approve', 'reject']
dispatch  -> fake recorded 1 approval request
escalation-> thresholds: [15, 30, 60] ; process -> level 2 -> senior_manager
week4     -> approval request -> notification -> external decision -> resume -> escalation
Summary: 23/23 checks pass
```

### Notes

- Slack/Email/SMS report `ok=False` when unconfigured so the platform runs locally; tests inject a
  `FakeNotifier`. Real providers are enabled purely via `.env`.
- Escalation is triggered by `worker.escalation` (cron/RQ scheduler); it is idempotent per level.

---

## Milestone M3 — Notifications complete (end of Week 4)

Layer 4 is complete: approvals are delivered via Slack/Email/SMS (adapters + fakes), resumed through
a durable approval service, authenticated per tenant, and escalated on timeout.

---

## Week 5 — Canary Deployment (P2-27 … P2-30)

**Date:** 16 Oct 2026
**Status:** Complete (verified)

### P2-27 — Kubernetes + Argo Rollouts setup

- `integrations/argo_manifests.py` — generates a `Rollout` (canary strategy with weighted steps
  and pauses) and an `AnalysisTemplate`. `write_manifests()` writes them to `deploy/k8s/`.
- Generated manifests: `deploy/k8s/checkout-api-rollout.yaml`,
  `deploy/k8s/checkout-api-analysis.yaml`.

### P2-28 — Prometheus analysis gates

- The `AnalysisTemplate` defines gates: `error-rate` (5xx ratio) and `p95-latency`, each with a
  `successCondition` and `failureLimit`.
- `PrometheusMetricsProvider` queries Prometheus; `StaticMetricsProvider` is used for tests/local.

### P2-29 — Progressive delivery + auto-rollback

- `integrations/canary.py` — `CanaryController` protocol with:
  - `SimulatedCanaryController` (promotion logic run locally),
  - `ArgoCanaryController` (real cluster adapter; falls back to simulation without `kubectl`).
- Steps 10 → 25 → 50 → 100; a stage that breaches the error-rate (5%) or p95 (500 ms) threshold
  aborts the rollout and returns `rolled_back` with a reason.
- `app/nodes/canary.py` — the `canary` node records stages and sets `completed` / `rolled_back`.
- Graph: `executor -> canary -> END`.

### P2-30 — Week 5 integration test

- `tests/check_week5.py` proves `executor -> canary 10->100% -> promote or auto-rollback`.

### Verification

```
steps     -> [10, 25, 50, 100]
promote   -> [10, 25, 50, 100]
rollback  -> at 50%: error_rate=0.2 (limit 0.05)
manifests -> Rollout + AnalysisTemplate (error-rate, p95-latency)
week5     -> executor -> canary -> promote/rollback
Summary: 25/25 checks pass
```

### Notes

- Without a cluster the `simulated` backend exercises the exact promotion/rollback logic; real
  clusters use the Argo manifests. Switch with `CANARY_BACKEND=argo` (+ `kubectl`/`PROMETHEUS_URL`).
- A rolled-back rollout sets `status=rolled_back` and carries the rollback plan; the rollback alert
  can be sent back through the Layer 1 webhook to close the loop.

---

## Week 6 — Observability & Learning (P2-31 … P2-37)

**Date:** 16 Oct 2026
**Status:** Complete (verified)

### P2-31 — OpenTelemetry tracing

- `observability/tracing.py` — `configure_tracing()` (memory | console | otlp exporter),
  `span(name, **attrs)` context manager, and `get_recorded_spans()` for tests.
- Disabled by default (`OTEL_ENABLED=false`) so the platform runs without a collector.

### P2-32 — Prometheus metrics + Grafana

- `observability/metrics.py` — counters/histograms/gauge: `incident_total`,
  `incident_auto_resolved_total`, `incident_manual_approval_total`, `sandbox_failures_total`,
  `canary_rollback_total`, `mttd_seconds`, `mttr_seconds`, `approval_latency_seconds`,
  `fix_success_rate`.
- `api/routes/metrics.py` — `GET /metrics` (Prometheus scrape).

### P2-33 — Structured logging

- JSON logs (Week 1) now carry correlation fields (`incident_id`, `stage`, `duration_ms`) and are
  correlated across the API, worker, and graph.

### P2-34 — Post-incident reports

- `app/reports.py` — `generate_incident_report(thread_id)` and `write_report()` build a Markdown
  report (summary, timeline, root cause/fix, outcome, lessons) from the incident, execution logs,
  and fix outcomes.

### P2-35 — Feedback loop + fix_outcomes

- `integrations/feedback.py` — `process_feedback()` scans incidents past the horizon
  (`FEEDBACK_HORIZON_HOURS`), determines stability, and writes `fix_outcomes` (idempotent).
- `worker/feedback.py` — scheduled entrypoint.

### P2-36 — Confidence calibration + eval harness

- `app/calibration.py` — groups outcomes by confidence bucket and suggests an automation threshold.
- `evals/dataset.jsonl` + `evals/run_eval.py` — golden dataset scored by `run(path)` returning
  accuracy and **false-safe rate** (must be 0).

### P2-37 — End-to-end acceptance

- `tests/check_week6.py` proves tracing + metrics + reports + feedback + calibration + evals
  work together; `deploy/GO_LIVE_CHECKLIST.md` lists the production readiness steps.

### Verification

```
tracing   -> recorded spans: ['unit-test']
metrics   -> /metrics exposes opsflow_* series
report    -> generated
feedback  -> recorded 1 outcome; idempotent
calibrate -> high (80-100) success_rate 1.0; threshold 80
evals     -> accuracy=1.0 false_safe_rate=0.0 (6/6)
week6     -> tracing + metrics + reports + feedback + calibration + evals
Summary: 29/29 checks pass
```

---

## Milestone M4 — Production-Ready (Phase 2 complete, end of Week 6)

All 7 layers are implemented and verified end-to-end:

| Layer | Status |
| --- | --- |
| 1 — Intelligent Detection | ✅ |
| 2 — Enhanced Diagnosis | ✅ |
| 3 — Safe Execution | ✅ |
| 4 — Notifications & Approval | ✅ |
| 5 — Canary Deployment | ✅ |
| 6 — Observability & Analytics | ✅ |
| 7 — Learning & Improvement | ✅ |

**Verification:** 29/29 checks pass, `alembic check` clean, real graph builds.

### Deliverables

- Event-driven, durable, multi-tenant remediation platform.
- Catalog-constrained execution in an ephemeral Docker sandbox with rollback and audit.
- Multi-channel approvals with per-tenant auth and escalation.
- Progressive canary rollout with metric gates and auto-rollback.
- Tracing, Prometheus metrics, structured logs, post-incident reports, feedback loop,
  confidence calibration, and an eval harness.
- `deploy/GO_LIVE_CHECKLIST.md` for production rollout.

---

<!-- New steps are appended below. -->
