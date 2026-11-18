# Legacy AWS Paid-Stack Scripts — DO NOT RUN

> **ZERO-COST MODE — updated 2026-11-18**
>
> The AWS account is a **paid account with a strict $0.00 ceiling**.
>
> These scripts were written for the original paid architecture:
>
> ```text
> VPC, NAT Gateway, RDS, ElastiCache, ECS/Fargate, ECR,
> ALB, ACM, Route53, Secrets Manager, EventBridge
> ```
>
> Those resources are now **banned**. Do not run any script in this directory
> until it has been rewritten for zero-cost mode.

## Allowed AWS services

Only these services may be provisioned, in `eu-north-1`:

```text
CloudWatch Logs   (1-day retention, ERROR/CRITICAL only)
AWS Lambda        (128 MB, 30 s, reserved concurrency 1)
Amazon SQS        (alerts queue + DLQ, long polling)
```

## Current architecture

- Retriva-AI runs locally with Docker/Python.
- OpsFlow runs locally with Docker/Python.
- Local Postgres/SQLite replaces RDS.
- Local Redis replaces ElastiCache.
- Local Ollama replaces paid inference.
- GitHub API polling replaces webhooks.
- AWS only handles CloudWatch Logs → Lambda → SQS.

Authoritative plan:

[`../../PLAN.md`](../../PLAN.md)

## Script status

| Script | Status |
|---|---|
| `00-preflight.sh` | Read-only; may be adapted |
| `01-network.sh` | **BANNED** — creates VPC/NAT |
| `02-sqs.sh` | May be reused after updating region/names |
| `03-iam.sh` | **Do not run as-is** — creates ECS roles |
| `04-lambda.sh` | May be reused after updating region/names |
| `05-rds-redis.sh` | **BANNED** — RDS/ElastiCache |
| `06-ecr-ecs.sh` | **BANNED** — ECR/ECS |
| `07-alb-acm-route53.sh` | **BANNED** — ALB/ACM/Route53 |
| `08-eventbridge.sh` | **BANNED** — EventBridge |
| `09-app-secrets.sh` | **BANNED** — Secrets Manager |
| `10-github-oidc.sh` | **BANNED** — creates ECR/ECS deploy role |
| `10-outputs.sh` | Legacy; will reference banned resources |
| `11-budget.sh` | Legacy paid-stack guardrail |
| `99-teardown.sh` | **BANNED** until rewritten |

The zero-cost messaging stack needs a new, smaller script set.
