# OpsFlow AWS Provisioning — Phase 0 / Phase 1 Foundation

These scripts provision the **real** AWS staging foundation for OpsFlow in
`ap-southeast-2`. They do not deploy application containers yet; images and ECS
services are created in Phase 3.

## What gets created

- VPC, two public subnets, two private subnets, IGW, NAT Gateway, route tables
- Security groups for ALB, API, workers, RDS, Redis, Ollama, and VPC endpoints
- VPC endpoints for SQS, Secrets Manager, CloudWatch Logs, ECR, KMS, S3
- Three SQS queues and DLQs: alerts, GitHub events, deployments
- IAM roles for ECS tasks and the CloudWatch forwarder Lambda
- CloudWatch Logs → SQS Lambda forwarder
- RDS Postgres 16 with pgvector support, private subnets
- ElastiCache Redis 7 with TLS and auth token
- ECR repositories for `opsflow/api` and `opsflow/worker`
- ECS Fargate cluster and CloudWatch log groups
- Public ALB, target group, optional ACM certificate + Route53 alias
- EventBridge rule for ECS deployment state changes → deployments SQS
- GitHub Actions OIDC roles for the OpsFlow repo and target repo
- Non-secret output file at `deploy/aws/outputs/<env>.env`

## Prerequisites

Run in **AWS CloudShell**, WSL, or Git Bash. Required tools:

```text
aws (v2), jq, openssl, python3, git
```

If you use AWS CloudShell, set `AWS_PROFILE=` (empty) in `config.env`; CloudShell
already has credentials and does not have the local `opsflow-dev` profile. If you
run from Windows Git Bash, keep `AWS_PROFILE=opsflow-dev`.

Authenticate:

```powershell
aws configure sso --profile opsflow-dev
aws sts get-caller-identity --profile opsflow-dev
```

The role must be able to create VPC, IAM, SQS, Lambda, ECS, ECR, RDS,
ElastiCache, ELB, ACM, Route53, Secrets Manager, EventBridge, and CloudWatch
resources. Prefer an admin role only during initial account setup.

If `00-preflight.sh` reports `explicitDeny` for create actions, the IAM user or
role is not authorized yet. Attach a temporary provisioning policy (or run from
an admin role) before continuing. The preflight script fails closed in that case.

## Configure

```bash
cd deploy/aws
cp config.env.example config.env
# edit config.env: AWS_PROFILE, region, target repo, domain, CIDRs
chmod +x *.sh lib/*.sh
```

Important values:

```text
AWS_REGION=ap-southeast-2
ENV=staging
TARGET_REPO=UzairAjaz/mediconnnect   # confirm exact GitHub slug
TARGET_SERVICE=mediconnect-backend
TENANT=mediconnect
MANAGER_EMAIL=uzairejaz987@gmail.com
```

For HTTPS and a real GitHub App webhook, provide:

```text
DOMAIN_NAME=opsflow.your-domain.com
HOSTED_ZONE_ID=Z...
```

Without a domain, the ALB is HTTP-only and the webhook URL uses the ALB DNS.
That is acceptable for a short staging test only.

## Run order

```bash
./00-preflight.sh
./01-network.sh
./02-sqs.sh
./03-iam.sh
./04-lambda.sh
./05-rds-redis.sh
./06-ecr-ecs.sh
./07-alb-acm-route53.sh
./08-eventbridge.sh
./09-app-secrets.sh
./10-github-oidc.sh
./10-outputs.sh
```

Each script is idempotent and stores resource IDs in
`deploy/aws/outputs/<env>.state`. Do not commit the state, outputs, or config
files.

`04-lambda.sh` runs before the target service log group exists. It will warn and
skip the subscription filter. After Phase 1 creates `/ecs/mediconnect-backend`,
rerun:

```bash
./04-lambda.sh
```

## After provisioning

1. Read `deploy/aws/outputs/staging.env`.
2. Use the secret ARNs in the ECS task definitions. Never copy secret values into
   task definition JSON.
3. Enable pgvector after the first DB connection:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
   Run this through an ECS one-off task or `psql` from inside the VPC; the RDS
   instance is private.
4. Use `GITHUB_WEBHOOK_URL` when creating the GitHub App.
5. Proceed to Phase 1: deploy the target FastAPI service to ECS Fargate and emit
   structured JSON logs with `commit_sha`.

## Cost warning

This staging foundation creates chargeable resources, including:

- NAT Gateway and public IPv4 address
- VPC interface endpoints (per AZ/hour)
- ALB
- RDS Postgres instance
- ElastiCache Redis node
- CloudWatch Logs and SQS storage

Run `99-teardown.sh` when finished:

```bash
CONFIRM_DESTROY=YES ./99-teardown.sh
```

Teardown does not delete Route53 hosted zones, ACM certificates, or the GitHub
OIDC provider, because they may be shared. Remove those manually if they are no
longer needed.

## Values you still need to confirm

- Exact GitHub repository slug (`mediconnnect` vs `mediconnect`).
- Domain name and Route53 hosted zone, or approval to use ALB DNS over HTTP.
- Whether the `opsflow-dev` role has administrator-level permissions for the
  first provisioning run.
- AWS Budget email and monthly limit.
- Confirmation that single-AZ RDS/Redis is acceptable for staging.
- GitHub App creation can be deferred until Phase 5; the OIDC role does not need
  the App.
