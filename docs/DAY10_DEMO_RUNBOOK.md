# OpsFlow AI — Day 10 Demo Runbook

**Audience:** Naveed Bhai / project owner  
**Scope:** MediConnect pilot-ready MVP  
**Goal:** Demonstrate one complete incident from alert to approved fix and audit

---

## 1. Demo Story

> “A MediConnect backend container runs out of memory. OpsFlow receives the alert,
> reads MediConnect’s own runbook, proposes the proven fix, validates it in a
> sandbox, generates a report, asks a human for approval, executes the approved
> action, and writes the full audit trail.”

---

## 2. Preflight — 2 Minutes

Open PowerShell in:

```powershell
cd C:\Users\RQ\Documents\opsflow_AI
```

Start infrastructure and apply migrations:

```powershell
docker compose up -d
.\.venv\Scripts\alembic.exe upgrade head
```

Seed MediConnect:

```powershell
.\.venv\Scripts\python.exe -m scripts.seed_mediconnect
```

Expected:

```text
MediConnect seed complete: tenant=mediconnect, service=mediconnect-backend, chunks=2
```

---

## 3. Terminal 1 — API

```powershell
cd C:\Users\RQ\Documents\opsflow_AI
$env:SANDBOX_BACKEND="fake"
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

If port `8000` is already in use:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
```

Expected:

```text
status
------
ok
```

---

## 4. Terminal 2 — Worker

```powershell
cd C:\Users\RQ\Documents\opsflow_AI

$env:DRY_RUN="false"
$env:AUTO_APPROVE="false"
$env:CONFIDENCE_THRESHOLD="0"
$env:MAX_LOOPS="1"
$env:SANDBOX_BACKEND="fake"
$env:OLLAMA_MODEL="qwen2.5:3b"

.\.venv\Scripts\python.exe -m worker.main
```

Leave the worker running.

`DRY_RUN=false` with `SANDBOX_BACKEND=fake` lets us show an execution log
without touching a real production server.

---

## 5. Terminal 3 — Send Alert and Approve

### Send the MediConnect alert

```powershell
cd C:\Users\RQ\Documents\opsflow_AI
$env:OPSFLOW_DEMO_SERVICE="mediconnect-backend"
.\.venv\Scripts\python.exe send_test_alert.py
```

Expected:

```text
Status: 202
Response: {'action': 'new', 'service': 'mediconnect-backend', ...}
```

### Wait for approval

```powershell
.\.venv\Scripts\python.exe approve_pending.py --wait
```

After about **30–40 seconds**, it shows:

```text
================================================================
APPROVAL REQUIRED
================================================================
Incident     : inc-xxxxxxxx
Service      : mediconnect-backend
Diagnosis    : ...
Root cause   : ...

Proposed solution:
  Action     : increase_memory_limit
  Parameters : {'container_name': 'mediconnect-backend', 'new_memory_limit': '2Gi'}
  Command    : docker update --memory 2Gi mediconnect-backend
  Rationale  : Proven fix: 1 prior incident(s), success rate 100%.
  Risk       : medium (reversible=True)
  Sandbox    : passed

Do I implement it? (yes/no):
```

Type:

```text
yes
```

Expected:

```text
Decision: APPROVED
Graph status: completed
Execution: [fake] docker update --memory 2Gi mediconnect-backend
```

---

## 6. Verify the Result

Incident and report:

```powershell
docker exec opsflow-postgres psql -U opsflow -d opsflow -c "select thread_id, service, status, report is not null as has_report from incidents order by created_at desc limit 1;"
```

Execution log:

```powershell
docker exec opsflow-postgres psql -U opsflow -d opsflow -c "select remediation_id, environment, exit_code, result from execution_logs order by started_at desc limit 5;"
```

Expected:

```text
increase_memory_limit | fake | 0 | executed
increase_memory_limit | fake | 0 | sandbox_passed
```

Audit trail:

```powershell
docker exec opsflow-postgres psql -U opsflow -d opsflow -c "select action, actor, details from audit_logs order by created_at desc limit 10;"
```

Expected actions:

```text
report.generate
approval.approve
execute
```

---

## 7. What to Say During the Demo

### During alert ingestion

> “The webhook verifies the HMAC signature, extracts the tenant and service,
> deduplicates the alert, and creates a MediConnect incident.”

### During diagnosis

> “The agent uses MediConnect’s own OOM runbook from pgvector, not generic
> internet advice. Historical fixes are also searched, scoped to the same tenant.”

### During the proposal

> “The fix is not free-form. It must come from the vetted remediation catalog,
> and the required parameters are validated with Pydantic.”

### During sandbox

> “The fix is validated in an isolated sandbox before any human sees it.”

### During the report

> “The approver sees the root cause, evidence, exact command, risk, rollback plan,
> confidence, and timeline. This is saved on the incident.”

### During approval

> “OpsFlow pauses the LangGraph execution with `interrupt()`. Nothing executes
> until a human approves.”

### During execution

> “After approval, the executor runs the approved action through the sandbox and
> writes an execution log and audit entry.”

### Closing

> “This is a pilot-ready MVP, not production. The production pilot adds an
> isolated AWS account, GitOps, canary rollout, automatic rollback, SSO/RBAC, and
> real monitoring integrations.”

---

## 8. Measured End-to-End Results

Three consecutive MediConnect runs passed:

| Run | Alert → Approval | Approval → Execution | Result |
|---|---:|---:|---|
| 1 | 32.3 s | 0.3 s | completed |
| 2 | 33.9 s | 0.3 s | completed |
| 3 | 37.0 s | 0.3 s | completed |

Automated verification:

```powershell
.\.venv\Scripts\python.exe -m scripts.check_end_to_end_mediconnect --runs 3
```

This test validates:

- Signed webhook acceptance
- Incident creation
- MediConnect edge retrieval
- Report persistence
- Approval pause
- Resume and execution
- `execution_logs` rows
- `audit_logs` rows

---

## 9. Fallback Plan

If Ollama or the network is slow during the live demo:

1. Use the already-verified automated run:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.check_end_to_end_mediconnect --runs 1
   ```

2. Show the recorded three-run results from Section 8.

3. Show the database rows from a previous completed run if available.

Do not debug the model during the demo.

---

## 10. FAQ

**What if the AI suggests a wrong fix?**  
The action must come from the catalog, parameters are validated, sandbox validation
runs, and a human approves.

**Does the AI have production access?**  
In this MVP, execution uses a fake/Docker sandbox. Production uses read-only
access and GitOps with canary and rollback.

**How is tenant data isolated?**  
Every retrieval and API operation is filtered by `tenant_id`; MediConnect cannot
see another tenant’s rulebooks or incidents.

**What if the process crashes?**  
LangGraph checkpoints persist state in PostgreSQL, so approval can resume.

**How do you prevent hallucination?**  
Tenant RAG citations, catalog constraints, Pydantic validation, sandbox checks,
confidence scoring, and human approval.

**What is the cost?**  
The MVP runs on free/local tools. Production costs are covered separately in the
production plan.

---

## 11. Demo Checklist

- [ ] Docker/Postgres/Redis running
- [ ] Migrations applied
- [ ] MediConnect seeded
- [ ] API healthy
- [ ] Worker running
- [ ] `DRY_RUN=false`
- [ ] `SANDBOX_BACKEND=fake`
- [ ] `AUTO_APPROVE=false`
- [ ] Terminal 3 ready
- [ ] Fallback test command ready
