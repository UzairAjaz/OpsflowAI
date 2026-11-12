# Baseline Test Result — Pre-GitOps

**Date:** 2026-11-12  
**Branch:** `feature/gitops-code-remediation`  
**Baseline tag:** `pre-gitops`  
**HEAD commit:** `94c035c` — Add interactive approval workflow and production planning docs  
**Working tree:** contains uncommitted changes from the configuration and remediation work; results reflect the current working tree, not only the tagged commit.

## Command

```powershell
.\.venv\Scripts\python.exe -m tests.run_all
```

## Environment

- Python: `.venv`
- PostgreSQL: `opsflow-postgres` container, healthy on `127.0.0.1:5432`
- Redis: `opsflow-redis` container, healthy on `127.0.0.1:6379`
- Ollama: reachable on `127.0.0.1:11434`
- Alembic: `upgrade head` applied
- Seed data: 1 tenant, 1 user, 1 rulebook, 2 rulebook chunks

## Result

```text
Summary: 29/29 passed
```

All baseline checks passed:

```text
scripts.check_state
scripts.check_router
scripts.check_catalog
scripts.check_redact
scripts.check_hitl
tests.check_api_health
tests.check_webhook
tests.check_ingestion
tests.check_ratelimit
tests.check_durable_checkpoint
tests.check_worker
tests.check_week1
tests.check_kb
tests.check_history
tests.check_parallel_research
tests.check_confidence
tests.check_history_proposal
tests.check_week2
tests.check_sandbox
tests.check_week3
tests.check_approvals
tests.check_notifications
tests.check_week4
tests.check_canary
tests.check_week5
tests.check_observability
tests.check_learning
tests.check_evals
tests.check_week6
```

## Notes

- Baseline is green.
- The uncommitted working-tree changes should be committed before starting Phase 1 so the baseline tag and the executed code are identical.
- The next planned step is Phase 0, Task 3: confirm the real AWS staging account, region, VPC, private subnets, NAT Gateway, RDS/ElastiCache or local equivalents, ALB/ACM domain, and the real GitHub repository/permissions.
