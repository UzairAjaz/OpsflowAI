# OpsFlow AI — Day 1 Scope & Risk Lock

**Pilot:** MediConnect only  
**Document version:** 1.0  
**Date:** 2026-10-28  
**Owner:** Uzair Ajaz  
**Reviewer:** Naveed Bhai  
**Status:** Proposed — pending confirmation of assumptions

---

## 1. Purpose

This document freezes the scope for Day 1 of the OpsFlow AI MVP.

The immediate goal is to prove the complete workflow on **one tenant, MediConnect**:

> Alert → diagnosis → tenant-specific knowledge → proposed fix → sandbox validation → report → human approval → simulated execution → audit trail

Only after MediConnect works reliably will we configure the same flow for other tenants.

This is a **pilot-ready MVP**, not a production rollout.

---

## 2. Core Decision

**We will test with MediConnect only.**

This does **not** mean hardcoding MediConnect into the codebase. It means:

- Only MediConnect data is seeded for this phase.
- Only MediConnect rulebooks are used.
- Only MediConnect incidents are created during the demo.
- The code continues to carry `tenant_id` so other tenants can be added later.
- No multi-tenant onboarding UI, tenant switcher, or cross-tenant analytics in this phase.

---

## 3. Proposed Demo Scenario

| Item | Proposed value | Status |
|---|---|---|
| Tenant ID | `mediconnect` | Confirm |
| Tenant display name | MediConnect | Confirm |
| Service | `mediconnect-backend` | Confirm |
| Incident class | `OOMKilled` | Confirm |
| Alert source | CloudWatch-style webhook | Confirm |
| Environment | Local Docker + Ngrok | Confirm |
| LLM | `qwen2.5:3b` | Proposed |
| Knowledge source | MediConnect runbook + seeded history | Proposed |
| Sandbox | `fake` for demo; Docker optional | Proposed |
| Approval channel | CLI `approve_pending.py` + API | Confirm |
| Execution | Simulated only | Proposed |
| Report | Markdown report | Proposed |
| Audit | Incident timeline + execution log | Proposed |

### Why OOMKilled first

- It is easy to explain to stakeholders.
- The remediation is reversible: increase memory limit.
- The current catalog already supports `increase_memory_limit`.
- It gives a clear before/after story.
- It can be validated safely in a fake or Docker sandbox.

---

## 4. In Scope

### Product scope

- One tenant: MediConnect.
- One primary incident type: OOMKilled.
- One service: MediConnect backend (name to be confirmed).
- One real alert source.
- Tenant-specific RAG retrieval.
- Structured incident report.
- Human approval before execution.
- Sandbox validation.
- Audit trail.
- Demo script and fallback recording.

### Technical scope

- Keep `tenant_id` in all data paths.
- Seed MediConnect tenant data.
- Seed MediConnect runbooks.
- Seed one valid historical fix so the demo is deterministic.
- Use the existing FastAPI webhook.
- Use the existing LangGraph flow.
- Use the existing approval interrupt and signed tokens.
- Use the fake sandbox for the demo.
- Use CLI approval for reliability.
- Record the execution result and audit timeline.

### Demo scope

- 10-minute walkthrough.
- Show alert ingestion.
- Show tenant-specific knowledge.
- Show diagnosis and proposed fix.
- Show sandbox result.
- Show report.
- Show approval prompt.
- Show execution result and audit trail.

---

## 5. Out of Scope

The following are explicitly **not** part of Day 1 or the 10-day MVP:

- Multiple live tenants.
- Tenant self-service onboarding.
- Full JWT/SSO/RBAC implementation.
- Production write access.
- Real production deployment.
- High availability or disaster recovery.
- SOC2/ISO certification.
- Multi-region deployment.
- Automatic approval.
- Fully autonomous production remediation.
- Canary deployment in the main graph.
- Billing and tenant chargeback.
- Marketplace of third-party runbooks.

These belong to the production pilot or full platform phases.

---

## 6. End-to-End Workflow

```text
1. MediConnect alert arrives
   CloudWatch / webhook → OpsFlow API

2. Alert is verified and deduplicated
   HMAC signature → normalized → incident

3. Agent diagnoses
   LLM + MediConnect runbook + seeded history

4. Agent proposes a fix
   Catalog action + validated parameters

5. Sandbox validates
   Fake sandbox for demo (Docker optional)

6. Report is generated
   Diagnosis, evidence, fix, risk, rollback, confidence

7. Human approves
   CLI / API / signed link

8. Execution is simulated
   No production write access

9. Audit is recorded
   Who approved, what ran, when, result
```

---

## 7. Success Criteria

### Functional

- [ ] A MediConnect alert creates an incident.
- [ ] The agent retrieves only MediConnect knowledge.
- [ ] The proposed fix uses a valid catalog action.
- [ ] Required parameters are present.
- [ ] Sandbox validation runs.
- [ ] A structured report is generated.
- [ ] The workflow pauses for approval.
- [ ] Execution happens only after approval.
- [ ] The audit trail is complete.

### Demo

- [ ] Full workflow runs in under 2 minutes after approval.
- [ ] Three consecutive demo runs succeed.
- [ ] No manual database edits are needed during the demo.
- [ ] A fallback recording exists.
- [ ] The demo can be explained in simple business language.

### Safety

- [ ] No production write credentials are used.
- [ ] No real SSH, Redis, or database command is executed.
- [ ] Irreversible actions are blocked or require escalation.
- [ ] Approval cannot be bypassed.
- [ ] MediConnect data is not mixed with other tenants.

---

## 8. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| LLM omits required parameters | Fix rejected, demo fails | Seed valid history; strict validation; fallback |
| LLM chooses an irreversible action | Escalation | Catalog risk rules; block irreversible actions without rollback |
| Duplicate alerts | No new incident | Unique event ID; dedupe window explained |
| Fake sandbox gives false confidence | Misleading demo | Label as simulated; Docker sandbox in next phase |
| Approval bypass | Unsafe execution | Signed token; executor approval guard |
| Wrong diagnosis | Bad fix | RAG + evidence + human approval |
| Prompt injection in logs | Unsafe behavior | Treat logs as untrusted; redaction |
| Cross-tenant leakage | Data breach | Single tenant now; tenant_id retained; isolation tests later |
| Model latency | Demo delay | 3B model; seeded history; pre-warm model |
| Free-tier/network failure | Demo outage | Local fallback; Ngrok backup; recorded demo |
| Data loss | Lost audit | PostgreSQL persistence; backups in production |
| Scope creep | Missed demo date | This document is the scope lock |

---

## 9. Approval Matrix

| Action risk | Example | Approval |
|---|---|---|
| Safe / read-only | inspect disk | Auto |
| Medium / reversible | increase memory limit | One approver |
| High / irreversible | delete volume | Two approvers or block |
| Production write | any real change | Not allowed in MVP |

### Demo approvers

- **Implementer:** Uzair Ajaz
- **Reviewer / stakeholder:** Naveed Bhai
- **Default CLI approver:** `demo-cli`

---

## 10. Data Plan

### Tenant

- `tenant_id`: `mediconnect`
- Display name: MediConnect

### Rulebook

Add a MediConnect OOM runbook:

- When to use
- Symptoms
- Diagnosis steps
- Fix steps
- Rollback
- Risk level

### Historical fix

Seed one successful fix:

```text
service:        mediconnect-backend
error_class:    OOMKilled
remediation:    increase_memory_limit
params:         container_name=mediconnect-backend,
                new_memory_limit=2Gi
outcome:        success
```

This makes the demo deterministic and avoids relying on the small model to invent parameters.

### Other tenants

No other tenant data is seeded for this phase.

---

## 11. Expansion Plan After MediConnect

Once MediConnect is stable:

1. Add a `tenants` table and tenant onboarding.
2. Add `users`, memberships, and RBAC.
3. Add tenant-specific rulebook CRUD.
4. Add PostgreSQL RLS or schema-per-tenant.
5. Add automated cross-tenant isolation tests.
6. Seed a second tenant.
7. Add tenant-specific notification routing.
8. Add per-tenant quotas and cost tracking.

The code should keep using `tenant_id` from Day 1 so this expansion does not require a rewrite.

---

## 12. Day 1 Exit Checklist

- [ ] Tenant ID confirmed as `mediconnect`
- [ ] MediConnect service name confirmed
- [ ] First incident class confirmed
- [ ] Alert source confirmed
- [ ] Approval channel confirmed
- [ ] Hosting target confirmed
- [ ] Risk matrix reviewed
- [ ] Demo scenario frozen
- [ ] No out-of-scope feature added
- [ ] Reviewer sign-off

---

## 13. Clarifications Needed

Please confirm or correct:

1. **MediConnect service name**  
   Is it `mediconnect-backend`, or something else?

2. **First incident type**  
   Should we start with `OOMKilled`, or do you want disk full or high CPU first?

3. **Alert source**  
   Will the alert come from CloudWatch, Prometheus, or a generic webhook for the demo?

4. **Approval channel**  
   Do you want CLI approval, email approval, Slack approval, or a combination?

5. **Hosting**  
   Should the demo run locally with Ngrok, on Oracle Always Free, or on AWS free tier?

6. **Demo approver**  
   Who should approve in the live demo — you, Naveed Bhai, or both?

---

## 14. Sign-Off

| Role | Name | Decision | Date |
|---|---|---|---|
| Implementer | Uzair Ajaz | Pending | |
| Reviewer | Naveed Bhai | Pending | |
| Product owner | TBD | Pending | |

---

## 15. Simple Explanation

We are not trying to support every company on Day 1.

We are proving one complete story with **MediConnect**:

> “A MediConnect production alert comes in. OpsFlow reads MediConnect’s own runbook, finds the right fix, tests it safely, writes a report, asks a human for approval, and only then runs the fix.”

Once this works reliably, we repeat the same pattern for other tenants.

This keeps the demo focused, reduces risk, and gives us a reusable foundation for the full multi-tenant platform.
