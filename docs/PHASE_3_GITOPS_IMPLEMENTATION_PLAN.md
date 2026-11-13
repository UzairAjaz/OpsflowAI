# OpsFlow AI — Phase 3: GitOps Code Remediation

**Implementation plan for real AWS + real GitHub, one Python/FastAPI service, no mocks.**

Status: execution plan  
Target: 5–10 incidents/day, max 1 concurrent code fix, p95 alert→Draft PR < 15 minutes  
Base branch: `main`  
Primary ingress: CloudWatch Logs → Subscription Filter → Lambda → SQS  
Approval: GitHub Draft PR + human review/merge; no auto-merge

---

## 0. Architectural decisions locked in

| Decision | Value |
|---|---|
| OpsFlow runtime | ECS Fargate |
| Queue | SQS primary ingress; Redis only for caching/rate limiting |
| Legacy RQ | Kept for existing infrastructure-remediation paths; not used for code fixes |
| Target service | One real Python/FastAPI service in a real GitHub repo |
| Code retrieval | GitHub Contents/Git Data API at the deployed `commit_sha` |
| LLM | Local Ollama `qwen2.5-coder:3b`, 1 concurrent fix, CPU |
| GitHub auth | GitHub App installation token, not a PAT |
| PR mode | Draft PR only; bot cannot merge |
| CI | GitHub Actions, required checks `test` and `lint` |
| Post-merge | ECS deployment event → 15-minute CloudWatch error-free window |
| Regression | Draft revert PR, human approval required |
| Multi-tenancy | `tenant_id` on every repository mapping, fix attempt, PR, CI run, deployment, verification |
| Secrets | AWS Secrets Manager in AWS; `.env` only for local dev |
| Mocks | None. Real AWS resources, real GitHub App, real staging service, real bug |

---   

## 1. Target architecture

```text
Production service (ECS Fargate)
  └─ JSON logs → CloudWatch Log Group
       └─ Subscription Filter
            └─ Lambda: decompress + filter + enrich
                 └─ SQS: opsflow-alerts-<env>
                      └─ ECS service: opsflow-alert-consumer
                           ├─ ingest incident (Postgres)
                           ├─ resolve repo mapping (tenant + service)
                           ├─ fetch code at commit_sha (GitHub App)
                           ├─ generate patch (Ollama qwen2.5-coder:3b)
                           ├─ validate patch (git apply, lint, secret scan)
                           ├─ push branch + open Draft PR
                           └─ wait for CI (LangGraph interrupt)

GitHub App webhook
  └─ ALB → FastAPI /api/v1/webhooks/github
       └─ verify X-Hub-Signature-256
            └─ SQS: opsflow-github-events-<env>
                 └─ ECS service: opsflow-github-consumer
                      ├─ check_run / check_suite / workflow_run
                      │    ├─ failed → comment + notify
                      │    └─ passed → mark PR ready + notify manager
                      └─ pull_request closed/merged → update state

ECS deployment event
  └─ EventBridge rule
       └─ SQS: opsflow-deployments-<env>
            └─ ECS service: opsflow-deployment-consumer
                 └─ create Deployment + FixVerification
                      └─ ECS service: opsflow-verification-worker
                           ├─ poll CloudWatch for 15 minutes
                           ├─ clean → incident resolved
                           └─ error recurs → Draft revert PR + notify
```

---

## 2. Environments, naming, and configuration

Use these variables in every shell session:

```bash
export AWS_REGION="us-east-1"
export ENV="staging"                 # staging first; production only after sign-off
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export PROJECT="opsflow"
export TENANT="mediconnect"          # replace with the real tenant
export SERVICE="mediconnect-backend" # replace with the real ECS service
export TARGET_REPO="your-org/your-repo"
export OPSFLOW_DOMAIN="opsflow.example.com"
```

Naming convention:

```text
Cluster:                 opsflow-<env>
API service:             opsflow-api
Alert consumer:          opsflow-alert-consumer
GitHub consumer:         opsflow-github-consumer
Deployment consumer:     opsflow-deployment-consumer
Verification worker:     opsflow-verification-worker
Ollama service:          opsflow-ollama
SQS alert queue:         opsflow-alerts-<env>
SQS alert DLQ:           opsflow-alerts-dlq-<env>
SQS GitHub queue:        opsflow-github-events-<env>
SQS deployment queue:    opsflow-deployments-<env>
CloudWatch log group:    /ecs/<service>
```

### 2.1 New settings in `app/config.py`

Add these fields to `Settings`:

```python
# AWS ingestion
aws_region: str = Field(default="us-east-1")
sqs_alert_queue_url: str = Field(default="")
sqs_github_queue_url: str = Field(default="")
sqs_deployment_queue_url: str = Field(default="")
sqs_wait_time_seconds: int = Field(default=20)
sqs_visibility_timeout_seconds: int = Field(default=900)
sqs_max_messages: int = Field(default=1)
sqs_heartbeat_seconds: int = Field(default=120)

# GitHub App
github_app_id: int = Field(default=0)
github_app_private_key: str = Field(default="")
github_webhook_secret: str = Field(default="")
github_api_url: str = Field(default="https://api.github.com")
github_bot_login: str = Field(default="opsflow-ai[bot]")
github_base_branch: str = Field(default="main")
github_max_files: int = Field(default=3)
github_max_diff_lines: int = Field(default=200)
github_denied_paths: str = Field(
    default=".github/workflows/,migrations/,alembic/,auth/,payments/,Dockerfile,.env,secrets/"
)
github_ci_timeout_minutes: int = Field(default=45)
github_reconcile_interval_seconds: int = Field(default=300)

# Code fix
code_fix_enabled: bool = Field(default=False)
code_fix_analysis_only: bool = Field(default=True)
code_fix_max_concurrent: int = Field(default=1)
code_fix_max_attempts: int = Field(default=2)
ollama_code_model: str = Field(default="qwen2.5-coder:3b")
ollama_code_num_ctx: int = Field(default=8192)
ollama_code_num_predict: int = Field(default=1200)
ollama_code_timeout_seconds: int = Field(default=600)

# Post-merge verification
post_merge_verification_minutes: int = Field(default=15)
post_merge_poll_interval_seconds: int = Field(default=60)
post_merge_error_threshold: int = Field(default=1)
```

Add the same keys to `.env.example`. Local `.env` gets real dev values; ECS gets secrets from Secrets Manager.

### 2.2 Local `.env` additions

```env
AWS_REGION=us-east-1
AWS_PROFILE=opsflow-dev
SQS_ALERT_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/opsflow-alerts-staging
SQS_GITHUB_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/opsflow-github-events-staging
SQS_DEPLOYMENT_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/opsflow-deployments-staging

GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
GITHUB_WEBHOOK_SECRET=replace-with-32-byte-random-secret
GITHUB_API_URL=https://api.github.com

OLLAMA_CODE_MODEL=qwen2.5-coder:3b
OLLAMA_BASE_URL=http://localhost:11434
CODE_FIX_ENABLED=true
CODE_FIX_ANALYSIS_ONLY=true
```

For ECS, do not put any of these secret values in task definitions. Use `secrets` with Secrets Manager ARNs.

---

## 3. Data model and state machine

### 3.1 New tables in `db/models.py`

Add these models. Use `uuid.uuid4` defaults, timezone-aware timestamps, and explicit indexes.

```python
class RepositoryMapping(Base):
    __tablename__ = "repository_mappings"
    mapping_id: UUID PK
    tenant_id: str FK tenants.tenant_id, index
    service: str(128), index
    repo_full_name: str(255)
    repo_path: str(255), default=""
    language: str(32), default="python"
    base_branch: str(64), default="main"
    log_group: str(255)
    cluster_name: str(128)
    ecs_service_name: str(128)
    required_checks: JSONB, default=["test", "lint"]
    test_command: str(512)
    lint_command: str(512)
    manager_user_id: UUID FK users.user_id, nullable
    github_installation_id: BigInteger FK github_installations.installation_id
    enabled: bool, default=True
    created_at, updated_at
    UniqueConstraint(tenant_id, service)
```

```python
class GithubInstallation(Base):
    __tablename__ = "github_installations"
    installation_id: BigInteger PK
    tenant_id: str FK tenants.tenant_id, index
    account_login: str(255)
    app_id: BigInteger
    created_at, updated_at
    UniqueConstraint(tenant_id, account_login)
```

```python
class CodeFixAttempt(Base):
    __tablename__ = "code_fix_attempts"
    attempt_id: UUID PK
    incident_id: UUID FK incidents.incident_id, index
    tenant_id: str FK tenants.tenant_id, index
    mapping_id: UUID FK repository_mappings.mapping_id
    attempt_number: int, default=1
    base_commit_sha: str(40)
    branch_name: str(255)
    status: str(32), index
    error_class: str(128)
    file_path: str(512)
    line_number: int
    model_name: str(128)
    prompt_version: str(32)
    code_context: JSONB
    patch_diff: Text
    patch_hash: str(64)
    validation_status: str(32)
    validation_errors: JSONB, default=[]
    tokens_input: int
    tokens_output: int
    created_at, updated_at
    UniqueConstraint(incident_id, attempt_number)
```

```python
class CodePullRequest(Base):
    __tablename__ = "code_pull_requests"
    pr_id: UUID PK
    attempt_id: UUID FK code_fix_attempts.attempt_id
    incident_id: UUID FK incidents.incident_id, index
    tenant_id: str FK tenants.tenant_id, index
    repo_full_name: str(255)
    pr_number: int
    pr_url: str(512)
    branch_name: str(255)
    base_branch: str(64)
    is_draft: bool, default=True
    state: str(32), default="open"
    ci_status: str(32), default="pending"
    merged_sha: str(40), nullable
    merged_by: str(255), nullable
    merged_at: datetime, nullable
    closed_at: datetime, nullable
    created_at, updated_at
    UniqueConstraint(repo_full_name, pr_number)
```

```python
class CiRun(Base):
    __tablename__ = "ci_runs"
    ci_run_id: UUID PK
    pr_id: UUID FK code_pull_requests.pr_id, index
    provider: str(32), default="github"
    external_id: str(128)
    workflow_name: str(255)
    check_name: str(255)
    status: str(32)
    conclusion: str(32), nullable
    details_url: str(1024), nullable
    started_at, completed_at
    raw: JSONB
    UniqueConstraint(provider, external_id)
```

```python
class Deployment(Base):
    __tablename__ = "deployments"
    deployment_id: UUID PK
    incident_id: UUID FK incidents.incident_id, index
    pr_id: UUID FK code_pull_requests.pr_id
    tenant_id: str FK tenants.tenant_id, index
    repo_full_name: str(255)
    environment: str(32)
    commit_sha: str(40)
    provider: str(32), default="ecs"
    external_id: str(128)
    status: str(32)
    deployed_at: datetime
    metadata: JSONB
    UniqueConstraint(provider, external_id)
```

```python
class FixVerification(Base):
    __tablename__ = "fix_verifications"
    verification_id: UUID PK
    incident_id: UUID FK incidents.incident_id, index
    deployment_id: UUID FK deployments.deployment_id
    status: str(32), default="pending"
    started_at, deadline_at, completed_at
    error_count: int, default=0
    last_error_at: datetime, nullable
    details: JSONB
    UniqueConstraint(deployment_id)
```

```python
class GithubEvent(Base):
    __tablename__ = "github_events"
    delivery_id: str(64) PK
    event: str(64)
    action: str(64), nullable
    received_at: datetime
    processed_at: datetime, nullable
    status: str(32), default="received"
    payload_hash: str(64)
```

Add constants in `app/code_fix/statuses.py`:

```python
STATUS_RECEIVED = "received"
STATUS_REPO_UNMAPPED = "repo_unmapped"
STATUS_ANALYSIS_ONLY = "analysis_only"
STATUS_CONTEXT_FETCHED = "context_fetched"
STATUS_PATCH_GENERATED = "patch_generated"
STATUS_PATCH_INVALID = "patch_invalid"
STATUS_PR_OPENED = "pr_opened"
STATUS_CI_RUNNING = "ci_running"
STATUS_CI_FAILED = "ci_failed"
STATUS_CI_PASSED = "ci_passed"
STATUS_CI_TIMEOUT = "ci_timeout"
STATUS_AWAITING_REVIEW = "awaiting_review"
STATUS_MERGED = "merged"
STATUS_REJECTED = "rejected"
STATUS_VERIFYING = "verifying"
STATUS_VERIFIED = "verified"
STATUS_REGRESSED = "regressed"
STATUS_REVERT_OPENED = "revert_opened"
STATUS_ESCALATED = "escalated"
```

### 3.2 Migration

```bash
.\.venv\Scripts\python.exe -m alembic revision -m "add gitops code fix tables"
```

Edit the generated file in `migrations/versions/`:

- `upgrade()` creates the seven tables in dependency order: `github_installations`, `repository_mappings`, `code_fix_attempts`, `code_pull_requests`, `ci_runs`, `deployments`, `fix_verifications`, `github_events`.
- Add indexes and unique constraints exactly as above.
- `downgrade()` drops in reverse order.

Run:

```bash
.\.venv\Scripts\python.exe -m alembic upgrade head
```

---

## 4. Phase-by-phase plan

### Phase 0 — Preconditions and safety rails (1–2 days)

**Objective:** Make the real target safe to modify and prevent accidental production writes.

**Tiny tasks**

1. Create branch `feature/gitops-code-remediation` from `main`; tag baseline `pre-gitops`.
2. Run the existing test suite and record baseline:
   ```powershell
   .\.venv\Scripts\python.exe -m tests.run_all
   ```
3. Confirm the real AWS staging account, region, VPC, private subnets, NAT Gateway, RDS/ElastiCache or local equivalents, and ALB/ACM domain.
4. Confirm the real GitHub repo, organization, and permission to create/install a GitHub App.
5. Create a GitHub branch protection rule on `main`:
   - Require pull request before merging.
   - Require approvals: at least 1.
   - Require status checks: `test`, `lint`.
   - Require branches to be up to date.
   - Do not allow bypassing.
6. Add `.github/CODEOWNERS` in the target repo:
   ```text
   .github/workflows/  @your-org/platform-team
   migrations/         @your-org/backend-team
   alembic/            @your-org/backend-team
   auth/               @your-org/security-team
   payments/           @your-org/payments-team
   ```
7. Create AWS Budget with a monthly limit and alerts at 50/80/100%.
8. Add a kill switch to `.env`/ECS: `CODE_FIX_ENABLED=false`. The bot must start disabled.
9. Write `docs/ADR-001-code-remediation.md` with scope, non-goals, risk, and rollback.
10. Define acceptance criteria for the first E2E run (see Phase 12).

**Credentials/permissions**

- AWS account admin for one-time IAM/SQS/Lambda/ECS setup.
- GitHub org admin for GitHub App creation/installation and branch protection.
- Target repo write access for CI workflow changes.

**Pitfalls**

- Do not use production as the first target. Use a real staging service.
- Branch protection can block the bot later; test with a bot branch before enabling required checks.
- Do not grant the bot admin or merge rights.
- Do not put real secrets in `CODEOWNERS`, docs, or test commands.

**Exit criteria**

- Staging AWS and GitHub are confirmed.
- `main` is protected.
- Baseline tests pass.
- `CODE_FIX_ENABLED=false` is committed.

**Provisioning artifacts created for this phase**

- `deploy/aws/README.md` — run order, cost warning, prerequisites
- `deploy/aws/00-preflight.sh` — identity and permission checks
- `deploy/aws/01-network.sh` — VPC, subnets, NAT, SGs, endpoints
- `deploy/aws/02-sqs.sh` — alerts/GitHub/deployment queues + DLQs
- `deploy/aws/03-iam.sh` — ECS and Lambda roles
- `deploy/aws/04-lambda.sh` — CloudWatch forwarder + subscription filter
- `deploy/aws/05-rds-redis.sh` — RDS, ElastiCache, connection secrets
- `deploy/aws/06-ecr-ecs.sh` — ECR, ECS cluster, log groups
- `deploy/aws/07-alb-acm-route53.sh` — ALB, ACM, optional Route53
- `deploy/aws/08-eventbridge.sh` — ECS deployment event routing
- `deploy/aws/09-app-secrets.sh` — Resend and GitHub App secrets
- `deploy/aws/10-github-oidc.sh` — GitHub Actions OIDC deploy roles
- `deploy/aws/10-outputs.sh` — non-secret environment output
- `deploy/aws/99-teardown.sh` — guarded destructive teardown
- `lambda/cloudwatch_forwarder/handler.py` — real CloudWatch→SQS forwarder
- `docs/PHASE_1_TASK_1_JSON_LOGGING.md` — target-service logging task

---

### Phase 1 — Real target service, ECS deployment, structured logs, CloudWatch (3–4 days)

**Objective:** Deploy the real Python/FastAPI service to ECS Fargate with JSON logs containing `commit_sha`, and verify CloudWatch receives a real error.

**Tiny tasks**

1. In the target repo, add `observability/logging_config.py`:
   - `JsonFormatter` with fields:
     `timestamp`, `level`, `service`, `environment`, `commit_sha`, `trace_id`, `request_id`, `error_class`, `file`, `line`, `stack_trace`, `message`.
   - Configure via `logging.config.dictConfig`.
   - `get_logger(name)` helper.
2. Add middleware `observability/request_context.py`:
   - Read `X-Request-ID`; otherwise generate UUID.
   - Bind `trace_id` and `request_id` to log records.
3. Add a global exception handler that calls `logger.exception(...)` and includes `error_class`, `file`, `line`, `stack_trace`.
4. Add `GET /healthz` returning `{"status": "ok"}`.
5. Add the real safe bug endpoint, gated to staging:
   ```python
   @app.get("/debug/boom")
   def boom():
       if os.getenv("ENABLE_TEST_BUG") != "true":
           raise HTTPException(status_code=404)
       raise KeyError("intentional staging test bug")
   ```
   Enable `ENABLE_TEST_BUG=true` only in the staging task definition.
6. Add `GIT_COMMIT_SHA` and `SERVICE_NAME` environment variables to the ECS task definition. Populate `GIT_COMMIT_SHA` from `${{ github.sha }}` in CI.
7. Create ECR repository and push the image:
   ```bash
   aws ecr create-repository \
     --repository-name "$SERVICE" \
     --image-scanning-configuration scanOnPush=true \
     --encryption-configuration encryptionType=AES256
   ```
8. Create IAM roles:
   - `opsflowEcsTaskExecutionRole`: attach `AmazonECSTaskExecutionRolePolicy`; add `secretsmanager:GetSecretValue` and `kms:Decrypt` for the DB/secret ARNs.
   - `mediconnectBackendTaskRole`: minimal; CloudWatch Logs via `awslogs` uses the execution role, so no broad permissions.
9. Create the ECS cluster:
   ```bash
   aws ecs create-cluster --cluster-name "opsflow-$ENV" \
     --capacity-providers FARGATE FARGATE_SPOT
   ```
10. Create the task definition file `deploy/ecs/target-service-task.json`:
    - `networkMode: awsvpc`
    - `requiresCompatibilities: ["FARGATE"]`
    - `cpu: "1024"`, `memory: "2048"`
    - container `app` with `awslogs` to `/ecs/$SERVICE`
    - env: `ENVIRONMENT`, `SERVICE_NAME`, `GIT_COMMIT_SHA`, `ENABLE_TEST_BUG`
    - health check: `curl -f http://localhost:8000/healthz`
11. Register and deploy:
    ```bash
    aws ecs register-task-definition --cli-input-json file://deploy/ecs/target-service-task.json
    aws ecs create-service \
      --cluster "opsflow-$ENV" \
      --service-name "$SERVICE" \
      --task-definition "$SERVICE" \
      --desired-count 1 \
      --launch-type FARGATE \
      --network-configuration "awsvpcConfiguration={subnets=[$PRIVATE_SUBNET_1,$PRIVATE_SUBNET_2],securityGroups=[$APP_SG],assignPublicIp=DISABLED}" \
      --load-balancers "targetGroupArn=$TARGET_TG_ARN,containerName=app,containerPort=8000"
    ```
12. Create an ALB target group + listener (or reuse an existing ALB). Use ACM certificate and Route53 alias for the staging hostname.
13. Create the CloudWatch log group:
    ```bash
    aws logs create-log-group --log-group-name "/ecs/$SERVICE"
    aws logs put-retention-policy --log-group-name "/ecs/$SERVICE" --retention-in-days 30
    ```
14. Add the target repo GitHub Actions workflow `.github/workflows/deploy.yml`:
    - jobs: `test`, `lint`, `build`, `deploy`.
    - use GitHub OIDC to assume `arn:aws:iam::$ACCOUNT_ID:role/gha-deploy-$SERVICE`.
    - build/push to ECR with immutable tag `${{ github.sha }}`.
    - register a new task definition with `GIT_COMMIT_SHA=${{ github.sha }}`.
    - update ECS service and wait for stability: `aws ecs wait services-stable`.
15. Create the GitHub OIDC provider if absent, then create the deploy role with trust:
    ```json
    {
      "Effect": "Allow",
      "Principal": {"Federated": "arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com"},
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
        "StringLike": {"token.actions.githubusercontent.com:sub": "repo:your-org/your-repo:ref:refs/heads/main"}
      }
    }
    ```
16. Deploy. Trigger the real bug:
    ```bash
    curl -i "https://$STAGING_HOST/debug/boom"
    ```
17. Verify the CloudWatch event contains `commit_sha`:
    ```bash
    aws logs filter-log-events \
      --log-group-name "/ecs/$SERVICE" \
      --filter-pattern '{ $.level = "ERROR" }' \
      --limit 5
    ```

**Credentials/permissions**

- ECR push/pull.
- ECS task execution role with CloudWatch Logs, ECR, Secrets Manager, KMS.
- GitHub Actions OIDC deploy role: ECR push, ECS register/update/describe, `iam:PassRole`.
- ALB/ACM/Route53 for the staging hostname.

**Pitfalls**

- JSON logging can double-encode if the formatter is attached twice.
- CloudWatch `awslogs` uses the execution role, not the task role.
- Stack traces may be split across log events; the Lambda must reassemble by request/trace ID.
- If `GIT_COMMIT_SHA` is missing, the entire pipeline must fail closed to analysis-only.
- ECS deployment circuit breaker should be enabled so failed deploys roll back.
- Do not log secrets, authorization headers, or PII.

**Exit criteria**

- Real staging service runs on ECS Fargate.
- `/debug/boom` produces a real JSON ERROR log.
- Log contains `service`, `environment`, `commit_sha`, `trace_id`, `file`, `line`, `stack_trace`.

---

### Phase 2 — CloudWatch → Lambda → SQS ingestion (2–3 days)

**Objective:** Turn real CloudWatch errors into durable SQS messages without losing events.

**Tiny tasks**

1. Create the DLQ:
   ```bash
   aws sqs create-queue --queue-name "opsflow-alerts-dlq-$ENV" \
     --attributes MessageRetentionPeriod=1209600,SqsManagedSseEnabled=true
   ```
2. Create the alerts queue with redrive:
   ```bash
   aws sqs create-queue --queue-name "opsflow-alerts-$ENV" \
     --attributes '{
       "VisibilityTimeout":"900",
       "MessageRetentionPeriod":"345600",
       "ReceiveMessageWaitTimeSeconds":"20",
       "SqsManagedSseEnabled":"true",
       "RedrivePolicy":"{\"deadLetterTargetArn\":\"arn:aws:sqs:'"$AWS_REGION"':'"$ACCOUNT_ID"':opsflow-alerts-dlq-'"$ENV"'\",\"maxReceiveCount\":\"5\"}"
     }'
   ```
3. Create IAM role `opsflow-cloudwatch-forwarder-$ENV` with:
   - `logs:CreateLogStream`, `logs:PutLogEvents` on `/aws/lambda/opsflow-cloudwatch-forwarder-$ENV`.
   - `sqs:SendMessage` on the alerts queue ARN.
   - `kms:Decrypt`/`kms:GenerateDataKey` only if using a customer KMS key.
4. Create Lambda `opsflow-cloudwatch-forwarder-$ENV`:
   - Runtime Python 3.12.
   - Memory 512 MB, timeout 30 s.
   - Env: `ALERT_QUEUE_URL`, `DEFAULT_TENANT_ID`, `ENVIRONMENT`, `LOG_GROUP_SERVICE_MAP` (JSON if needed).
5. Add code under `lambda/cloudwatch_forwarder/handler.py`:
   - `handler(event, context)`
   - `decode_cloudwatch_payload(event)`
   - `should_forward(record)`
   - `build_alert_message(record, payload, log_event)`
   - `chunked(items, size)`
6. Implement decode:
   ```python
   compressed = base64.b64decode(event["awslogs"]["data"])
   payload = json.loads(gzip.decompress(compressed))
   ```
7. Implement filtering:
   - Forward `level` in `{"ERROR", "CRITICAL", "FATAL"}`.
   - Forward `status_code >= 500`.
   - Drop `4xx`, health checks, and known noise.
   - Never drop a record solely because `commit_sha` is missing; mark `analysis_only=true`.
8. Build the SQS message:
   ```json
   {
     "schema_version": "1.0",
     "source": "cloudwatch",
     "tenant_id": "mediconnect",
     "service": "mediconnect-backend",
     "environment": "staging",
     "log_group": "/ecs/mediconnect-backend",
     "log_stream": "ecs/app/abc123",
     "event_id": "1234567890",
     "timestamp": "2026-11-12T10:15:30.123Z",
     "commit_sha": "abc123...",
     "level": "ERROR",
     "status_code": 500,
     "error_class": "KeyError",
     "message": "intentional staging test bug",
     "stack_trace": "Traceback ...",
     "file": "app/main.py",
     "line": 42,
     "trace_id": "req-...",
     "fingerprint": "mediconnect-backend|KeyError|app/main.py|42",
     "analysis_only": false
   }
   ```
9. Add SQS message attributes: `tenant_id`, `service`, `severity`, `commit_sha`, `schema_version`.
10. Build and deploy:
    ```bash
    cd lambda/cloudwatch_forwarder
    zip -r function.zip handler.py
    aws lambda create-function \
      --function-name "opsflow-cloudwatch-forwarder-$ENV" \
      --runtime python3.12 \
      --handler handler.handler \
      --role "arn:aws:iam::$ACCOUNT_ID:role/opsflow-cloudwatch-forwarder-$ENV" \
      --zip-file fileb://function.zip \
      --timeout 30 --memory-size 512 \
      --environment "Variables={ALERT_QUEUE_URL=$ALERT_QUEUE_URL,ENVIRONMENT=$ENV,DEFAULT_TENANT_ID=$TENANT}"
    ```
11. Grant CloudWatch Logs invoke permission:
    ```bash
    aws lambda add-permission \
      --function-name "opsflow-cloudwatch-forwarder-$ENV" \
      --statement-id "cloudwatch-$SERVICE" \
      --action lambda:InvokeFunction \
      --principal logs.amazonaws.com \
      --source-arn "arn:aws:logs:$AWS_REGION:$ACCOUNT_ID:log-group:/ecs/$SERVICE:*"
    ```
12. Create the subscription filter:
    ```bash
    aws logs put-subscription-filter \
      --log-group-name "/ecs/$SERVICE" \
      --filter-name "opsflow-errors" \
      --filter-pattern '{ ($.level = "ERROR" || $.level = "CRITICAL") }' \
      --destination-arn "arn:aws:lambda:$AWS_REGION:$ACCOUNT_ID:function:opsflow-cloudwatch-forwarder-$ENV"
    ```
    If the console rejects the JSON pattern, use `{ $.level = "ERROR" }` and let Lambda filter `CRITICAL`/`FATAL`.
13. Create CloudWatch alarms:
    - `ApproximateNumberOfMessagesVisible > 0` for 10 minutes.
    - DLQ `ApproximateNumberOfMessagesVisible > 0`.
    - Lambda `Errors >= 1`.
14. Trigger the real staging bug and verify:
    ```bash
    curl -i "https://$STAGING_HOST/debug/boom"
    aws sqs receive-message --queue-url "$ALERT_QUEUE_URL" --max-number-of-messages 1 --wait-time-seconds 20
    ```
15. Delete the received test message after inspection; do not leave it in the queue.

**Credentials/permissions**

- Lambda execution role: SQS SendMessage, CloudWatch Logs, KMS if applicable.
- CloudWatch Logs permission to invoke the Lambda.
- SQS queue policy for Lambda (same-account identity policy is usually enough).
- SQS DLQ redrive permissions.

**Pitfalls**

- The `awslogs` payload is gzip+base64; forgetting either breaks decoding.
- SQS max message size is 256 KB; truncate `stack_trace`/`message` and keep the fingerprint.
- Duplicate CloudWatch events are normal; the consumer must dedupe by `event_id` and fingerprint.
- Subscription filters only process new events; trigger the bug after creating the filter.
- Lambda reserved concurrency can throttle; set a small reserved concurrency and alarm on throttles.
- A missing `tenant_id` must not be guessed in multi-tenant mode; send to DLQ and alert.

**Exit criteria**

- A real staging error appears in SQS within 60 seconds.
- The message contains the real `commit_sha`, stack trace, file, line, and tenant.
- DLQ is empty; alarms are configured.

---

### Phase 3 — OpsFlow AWS runtime and SQS consumers (4–5 days)

**Objective:** Run the API, SQS consumers, verification worker, and Ollama on ECS Fargate using the existing codebase.

**Tiny tasks**

1. Add dependencies to `requirements.txt`:
   ```text
   boto3>=1.35
   PyGithub>=2.4
   tree-sitter>=0.23
   tree-sitter-python>=0.23
   tenacity>=9.0
   ```
2. Add `integrations/aws/__init__.py`.
3. Add `integrations/aws/sqs.py`:
   - `SqsPublisher(queue_url).send_json(body, attributes)`
   - `receive_messages`, `delete_message`, `change_visibility`
4. Add `integrations/aws/cloudwatch.py`:
   - `CloudWatchLogsClient.filter_errors(log_group, start_time, filter_pattern)`
   - pagination with `nextToken`; return normalized records.
5. Add `integrations/aws/ecs.py`:
   - `EcsClient.resolve_commit_sha(cluster, service)`
   - `describe_service`, `describe_task_definition`.
6. Add `worker/consumers/__init__.py`.
7. Add `worker/consumers/base.py`:
   ```python
   class BaseSqsConsumer:
       def __init__(self, queue_url: str, handler: Callable): ...
       def poll_forever(self): ...
       def handle_message(self, message: dict): ...
       def _heartbeat(self, receipt_handle: str): ...
       def _delete(self, receipt_handle: str): ...
       def shutdown(self): ...
   ```
   - Long poll `WaitTimeSeconds=20`.
   - `MaxNumberOfMessages=1`.
   - Heartbeat thread extends visibility every 120 s.
   - Delete only after `handler` commits DB state.
   - On unhandled exception: do not delete; let SQS redeliver; log with receipt handle.
8. Add `ingestion/code_alert_schema.py`:
   - `CodeAlertMessage` Pydantic model.
   - `normalize_code_alert(payload)`.
   - `validate_commit_sha`.
9. Add `worker/consumers/alert_consumer.py`:
   - `AlertConsumer.handle_message`: validate -> `ingest_payload` -> resolve `tenant_id`/`service` -> call `run_code_fix_incident`.
   - If `analysis_only` or missing mapping: update incident, notify, delete message.
   - If duplicate: delete message.
10. Add `worker/code_fix_runner.py`:
    - `run_code_fix_incident(incident_id, alert)`
    - Build `CodeFixState`; invoke `app/code_fix/graph.py:build_code_fix_graph()` with Postgres checkpointer.
    - Use thread ID `codefix-<incident_id>`.
11. Add `worker/consumers/github_consumer.py`:
    - `GithubEventConsumer.handle_message`.
    - `handle_check_run`, `handle_check_suite`, `handle_workflow_run`, `handle_pull_request`.
    - Idempotency via `github_events.delivery_id`.
12. Add `worker/consumers/deployment_consumer.py`:
    - `DeploymentConsumer.handle_ecs_deployment`.
    - Ignore non-completed deployments.
    - Resolve mapping by `cluster_name`/`ecs_service_name`.
    - Resolve `commit_sha` from ECS task definition.
13. Add `worker/verification_worker.py`:
    - `VerificationWorker.run_once()`
    - `verify_verification(verification_id)`
    - `evaluate_cloudwatch(...)`
14. Add `worker/reconciler.py`:
    - `reconcile_open_prs()`
    - `reconcile_deployments()`
    - Run every `GITHUB_RECONCILE_INTERVAL_SECONDS`.
15. Add `Dockerfile.api`, `Dockerfile.worker`, `Dockerfile.patch-validator`:
    - Python 3.12 slim.
    - install `git`, `curl`, `gitleaks`, `ruff`.
    - non-root user.
    - worker entrypoint: `python -m worker.consumers.alert_consumer` (override per ECS service).
16. Add `.dockerignore`.
17. Create ECR repositories:
    ```bash
    aws ecr create-repository --repository-name "opsflow/api"
    aws ecr create-repository --repository-name "opsflow/worker"
    ```
18. Create RDS Postgres in private subnets:
    ```bash
    aws rds create-db-instance \
      --db-instance-identifier "opsflow-$ENV" \
      --engine postgres --engine-version 16.4 \
      --db-instance-class db.t4g.medium \
      --allocated-storage 50 --storage-encrypted \
      --vpc-security-group-ids "$DB_SG" \
      --db-subnet-group-name "$DB_SUBNET_GROUP" \
      --backup-retention-period 7 --no-publicly-accessible \
      --manage-master-user-password
    ```
    Enable pgvector:
    ```sql
    CREATE EXTENSION IF NOT EXISTS vector;
    ```
19. Create ElastiCache Redis with encryption in transit and auth token. Store the auth token in Secrets Manager; set `REDIS_URL=rediss://...`.
20. Create VPC interface endpoints for SQS, Secrets Manager, CloudWatch Logs, ECR API/DKR, KMS; S3 gateway endpoint for ECR layers.
21. Create Secrets Manager secrets:
    ```bash
    aws secretsmanager create-secret --name "opsflow/$ENV/database-url" --secret-string "postgresql+psycopg://..."
    aws secretsmanager create-secret --name "opsflow/$ENV/github-app" --secret-string file://github-app.json
    aws secretsmanager create-secret --name "opsflow/$ENV/resend" --secret-string "{\"api_key\":\"...\"}"
    ```
22. Create ECS task definitions under `deploy/ecs/`:
    - `api-task.json`
    - `alert-consumer-task.json`
    - `github-consumer-task.json`
    - `deployment-consumer-task.json`
    - `verification-worker-task.json`
    - `ollama-task.json`
23. Each task definition:
    - `executionRoleArn` = `opsflowEcsTaskExecutionRole`.
    - `taskRoleArn` = `opsflowApiTaskRole` or `opsflowWorkerTaskRole`.
    - `secrets` from Secrets Manager for `DATABASE_URL`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`, `SMTP_PASSWORD`.
    - `awslogs` to `/ecs/opsflow-<service>`.
    - no secrets in `environment`.
24. Create the API service behind the ALB:
    ```bash
    aws ecs create-service \
      --cluster "opsflow-$ENV" \
      --service-name opsflow-api \
      --task-definition opsflow-api \
      --desired-count 2 \
      --launch-type FARGATE \
      --load-balancers "targetGroupArn=$API_TG_ARN,containerName=api,containerPort=8000" \
      --network-configuration "awsvpcConfiguration={subnets=[$PRIVATE_SUBNET_1,$PRIVATE_SUBNET_2],securityGroups=[$API_SG],assignPublicIp=DISABLED}" \
      --health-check-grace-period-seconds 30
    ```
25. Create the consumers:
    - `opsflow-alert-consumer`, desired count 1.
    - `opsflow-github-consumer`, desired count 1.
    - `opsflow-deployment-consumer`, desired count 1.
    - `opsflow-verification-worker`, desired count 1.
26. Create the Ollama service:
    - Fargate task: 4 vCPU, 8 GB; image `ollama/ollama:<pinned-version>`.
    - EFS access point for `/root/.ollama`.
    - `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=-1`.
    - Cloud Map service `ollama.opsflow.local` port 11434.
    - Init container or startup command pulls `qwen2.5-coder:3b`.
27. Create Cloud Map private DNS namespace `opsflow.local` and service `ollama`.
28. Run migrations as a one-off ECS task:
    ```bash
    aws ecs run-task --cluster "opsflow-$ENV" \
      --task-definition opsflow-worker \
      --overrides '{"containerOverrides":[{"name":"worker","command":["alembic","upgrade","head"]}]}' \
      --launch-type FARGATE --network-configuration "..."
    ```
29. Create `.github/workflows/deploy-opsflow.yml`:
    - OIDC assume `gha-deploy-opsflow-$ENV`.
    - build/push API and worker images.
    - register new task definitions.
    - update all ECS services.
    - wait for stability.
30. Local dev:
    - `docker compose up -d postgres redis`
    - set real AWS dev SQS URLs and `AWS_PROFILE=opsflow-dev`.
    - run `python -m worker.consumers.alert_consumer` locally.
    - ensure **only one** consumer is running (local or ECS) against the dev queue.

**Credentials/permissions**

- ECS task execution role: ECR pull, CloudWatch Logs, Secrets Manager, KMS.
- API task role: SQS SendMessage to the GitHub events queue.
- Worker task role: SQS Receive/Delete/ChangeVisibility, CloudWatch Logs `FilterLogEvents`, ECS `DescribeServices`/`DescribeTaskDefinition`, Secrets Manager.
- GitHub Actions OIDC deploy role: ECR push, ECS register/update/describe, `iam:PassRole`.
- RDS/ElastiCache security groups and subnet groups.
- VPC endpoints.

**Pitfalls**

- Do not use `AmazonECSFullAccess`; scope actions to the OpsFlow resources.
- SQS visibility must exceed the longest LLM call; heartbeat extends it.
- Do not run two alert consumers against the same queue; one will starve the other.
- `SimpleWorker` is not suitable for long CI waits; the SQS consumer must not block on CI.
- Ollama on Fargate is CPU-only; benchmark before committing to the 15-minute SLO.
- EFS must be mounted before the Ollama container starts.
- Secrets injected via ECS `secrets` are environment variables; never echo them.
- RDS must have pgvector; create the extension in the migration.

**Exit criteria**

- API `/healthz` is reachable through ALB.
- All four consumers are running and healthy.
- A real SQS message creates an incident in RDS.
- Ollama responds from the worker at `http://ollama.opsflow.local:11434`.

---

### Phase 4 — Repository mapping, tenancy, and admin operations (2–3 days)

**Objective:** Resolve a real service to a real repo, base branch, installation, log group, and manager.

**Tiny tasks**

1. Add `app/code_fix/repository_mapping.py`:
   - `get_mapping(session, tenant_id, service) -> RepositoryMapping | None`
   - `resolve_repo_path(mapping) -> str`
   - `resolve_manager_email(session, mapping) -> str | None`
   - `require_mapping(...)` raises `RepoMappingMissing`.
2. Add `app/code_fix/tenancy.py`:
   - `ensure_tenant_enabled(tenant_id)`
   - `ensure_repo_allowed(tenant_id, repo_full_name)`
   - `ensure_installation_belongs_to_tenant(...)`.
3. Add `scripts/register_github_installation.py`:
   - args: `--tenant`, `--installation-id`, `--account-login`, `--app-id`.
   - insert/update `github_installations`.
4. Add `scripts/register_repo_mapping.py`:
   - args: `--tenant`, `--service`, `--repo`, `--repo-path`, `--base-branch`, `--log-group`, `--cluster`, `--ecs-service`, `--required-checks`, `--manager-email`.
   - insert/update `repository_mappings`.
5. Add `Tenant.settings["code_fix"]` fields:
   ```json
   {
     "enabled": true,
     "analysis_only": true,
     "max_concurrent": 1,
     "allowed_repos": ["your-org/your-repo"]
   }
   ```
6. Add `app/code_fix/policy.py`:
   - `is_path_allowed(path)`
   - `is_repo_allowed(tenant_id, repo)`
   - `is_tenant_enabled(tenant_id)`.
7. Register the real mapping:
   ```bash
   .\.venv\Scripts\python.exe -m scripts.register_github_installation \
     --tenant "$TENANT" --installation-id "$INSTALLATION_ID" \
     --account-login "$GITHUB_ORG" --app-id "$GITHUB_APP_ID"
   .\.venv\Scripts\python.exe -m scripts.register_repo_mapping \
     --tenant "$TENANT" --service "$SERVICE" --repo "$TARGET_REPO" \
     --base-branch main --log-group "/ecs/$SERVICE" \
     --cluster "opsflow-$ENV" --ecs-service "$SERVICE" \
     --required-checks test,lint \
     --manager-email "manager@your-company.com"
   ```
8. Add admin API endpoints (optional, authenticated):
   - `GET /api/v1/admin/repository-mappings`
   - `POST /api/v1/admin/repository-mappings`
   - `GET /api/v1/admin/installations`
   Use existing auth/role checks; `admin` only.
9. Add tests that verify tenant isolation: a mapping from tenant A cannot be read by tenant B.

**Credentials/permissions**

- DB write access for migrations/seeding.
- GitHub organization owner to confirm installation ID.
- Existing admin JWT/API key for admin endpoints.

**Pitfalls**

- Service names must be unique per tenant; enforce `(tenant_id, service)`.
- Do not guess a repo when mapping is missing; mark `repo_unmapped` and notify.
- A GitHub installation can cover multiple repos; verify `repo_full_name` is in the installation.
- Manager email must be tenant-scoped; never fall back to a global address in multi-tenant mode.

**Exit criteria**

- A real alert resolves to the real repo, branch, log group, manager, and installation.
- Missing mapping produces `repo_unmapped`, not a wrong PR.

---

### Phase 5 — GitHub App, installation tokens, and webhook ingress (2–3 days)

**Objective:** Authenticate as a GitHub App and receive real GitHub webhooks securely.

**Tiny tasks**

1. In GitHub.com → Organization settings → Developer settings → GitHub Apps → New GitHub App:
   - Name: `opsflow-ai-bot`.
   - Homepage: `https://$OPSFLOW_DOMAIN`.
   - Webhook URL: `https://$OPSFLOW_DOMAIN/api/v1/webhooks/github`.
   - Webhook secret: generate 32+ random bytes; store in Secrets Manager.
   - Permissions:
     - Repository: `Actions: Read`, `Checks: Read`, `Contents: Write`, `Issues: Write` (only if labels), `Metadata: Read`, `Pull requests: Write`.
     - Organization: `Members: Read` only if requesting team reviewers.
     - Do **not** grant `Administration`, `Secrets`, or `Workflows: Write`.
   - Subscribe to events: `Check run`, `Check suite`, `Workflow run`, `Pull request`.
   - Install on selected repositories only: the real target repo.
2. Generate a private key. Store it as a Secrets Manager JSON secret:
   ```bash
   aws secretsmanager create-secret \
     --name "opsflow/$ENV/github-app" \
     --secret-string '{"app_id":"123456","private_key":"-----BEGIN RSA PRIVATE KEY-----\n...","webhook_secret":"..."}'
   ```
3. Add `api/security.py:verify_github_signature(secret, body, signature_header)`:
   - Parse `sha256=...`.
   - `hmac.new(secret, body, hashlib.sha256)`.
   - `hmac.compare_digest`.
4. Add `api/routes/github_webhooks.py`:
   ```python
   @router.post("/github", status_code=202)
   async def receive_github_webhook(request: Request):
       body = await request.body()
       signature = request.headers.get("X-Hub-Signature-256")
       if not verify_github_signature(settings.github_webhook_secret, body, signature):
           raise HTTPException(401)
       event = request.headers.get("X-GitHub-Event", "")
       delivery = request.headers.get("X-GitHub-Delivery", "")
       if event == "ping":
           return {"status": "pong"}
       # insert github_events(delivery_id) idempotently
       # publish to sqs_github_queue_url
       return {"status": "accepted"}
   ```
5. Register the router in `api/main.py`.
6. Add `integrations/github_service.py`:
   ```python
   class GitHubAppClient:
       def __init__(self, app_id: int, private_key: str, api_url: str): ...
       def get_installation_token(self, installation_id: int) -> str: ...
       def get_repo(self, installation_id: int, repo_full_name: str): ...
       def get_file_at_sha(self, repo, path: str, sha: str) -> str: ...
       def get_tree(self, repo, sha: str) -> list[dict]: ...
       def create_branch(self, repo, branch: str, sha: str) -> None: ...
       def commit_files(self, repo, branch: str, files: list[FileChange], message: str) -> str: ...
       def open_draft_pr(self, repo, title: str, body: str, head: str, base: str) -> PullRequest: ...
       def mark_ready_for_review(self, repo, pr_number: int) -> None: ...
       def comment_on_pr(self, repo, pr_number: int, body: str) -> None: ...
       def get_check_runs(self, repo, ref: str) -> list[dict]: ...
       def open_revert_pr(self, repo, merge_sha: str, original_pr: int, reason: str): ...
   ```
7. Use `GithubIntegration` and `Auth.Token` from PyGithub. Cache tokens with expiry; refresh 5 minutes before expiry.
8. Add `integrations/aws/sqs.py` publisher; API publishes GitHub events to `sqs_github_queue_url`.
9. Add a real verification script `scripts/verify_github_app.py`:
   - load app ID/private key/installation ID from env.
   - list installation repositories.
   - fetch a known file at `main` SHA.
   - print repo and SHA; no mock.
10. Configure ALB/ACM/Route53 for `https://$OPSFLOW_DOMAIN` and point the GitHub App webhook at it.
11. Add WAF/rate limit for `/api/v1/webhooks/github` if available; at minimum SQS buffering and signature verification.

**Credentials/permissions**

- GitHub App private key (Secrets Manager).
- GitHub App permissions above.
- Webhook secret.
- API task role `sqs:SendMessage` to the GitHub events queue.
- Public TLS certificate for the webhook URL.

**Pitfalls**

- Signature must be computed over the **raw request body**, not parsed JSON.
- GitHub retries; enforce `X-GitHub-Delivery` idempotency.
- Installation tokens expire after 1 hour; cache and refresh.
- Private key newlines break in env vars; use Secrets Manager JSON and decode carefully.
- The bot cannot merge; branch protection must enforce that.
- Do not subscribe to events you do not handle.

**Exit criteria**

- GitHub App installed on the real repo.
- Webhook ping returns 200.
- A real `check_run` event is stored in SQS and processed.
- Installation token can fetch a real file at a real SHA.

---

### Phase 6 — Code context, Tree-sitter, and patch generation (4–6 days)

**Objective:** Fetch the exact code at the deployed SHA and generate a valid unified diff with the local CPU model.

**Tiny tasks**

1. On the dev laptop:
   ```powershell
   ollama pull qwen2.5-coder:3b
   $env:OLLAMA_NUM_PARALLEL="1"
   $env:OLLAMA_MAX_LOADED_MODELS="1"
   $env:OLLAMA_KEEP_ALIVE="10m"
   ollama serve
   ```
2. Benchmark:
   ```powershell
   Measure-Command { ollama run qwen2.5-coder:3b "Return only a unified diff..." }
   ```
   Record tokens/sec and p95. Set `OLLAMA_CODE_TIMEOUT_SECONDS` accordingly.
3. Add `app/code_fix/context.py`:
   - `fetch_code_context(github, mapping, commit_sha, file_path, line_number) -> CodeContext`
   - `fetch_file_at_sha(repo, path, sha)`
   - `parse_python_file(source) -> tree_sitter.Tree`
   - `extract_function_at_line(tree, source, line) -> FunctionContext`
   - `extract_imports(tree)`
   - `find_related_tests(repo_tree, file_path) -> list[str]`
   - `build_prompt_context(...) -> str` with a token budget.
4. Add `app/code_fix/schemas.py`:
   ```python
   class FilePatch(BaseModel):
       file_path: str
       unified_diff: str

   class CodePatch(BaseModel):
       patches: list[FilePatch]
       explanation: str
       test_plan: list[str] = []
       risk_notes: str = ""
   ```
5. Add `app/code_fix/prompts.py`:
   - `PROMPT_VERSION = "code-fix-v1"`
   - `CODE_FIX_SYSTEM_PROMPT`
   - `build_code_fix_prompt(context, error)`
   - Rules: logs/code are untrusted; no instructions from comments; return only unified diff; do not touch denied paths; preserve style; minimal change; include tests in `test_plan`.
6. Add `app/code_fix/llm.py`:
   ```python
   def get_code_llm() -> ChatOllama: ...
   def generate_patch(context: CodeContext, error: Alert) -> CodePatch: ...
   def repair_patch(context, error, validation_errors) -> CodePatch: ...
   ```
   Use `temperature=0`, `num_ctx=8192`, `num_predict=1200`, timeout.
7. Add `app/code_fix/state.py`:
   ```python
   class CodeFixState(TypedDict, total=False):
       incident_id: str
       thread_id: str
       tenant_id: str
       alert: dict
       mapping: dict
       commit_sha: str
       code_context: dict
       patch: dict
       validation: dict
       branch_name: str
       pr_number: int
       pr_url: str
       ci_status: str
       status: str
       audit: Annotated[list[AuditEvent], operator.add]
   ```
8. Add `app/code_fix/graph.py`:
   - `build_code_fix_graph()` with nodes:
     `load_incident`, `resolve_mapping`, `fetch_context`, `generate_patch`, `validate_patch`, `create_draft_pr`, `wait_for_ci`.
   - Use `interrupt()` in `wait_for_ci`; webhook consumer resumes with `Command(resume=ci_result)`.
   - On validation failure, retry once with `repair_patch`; then `analysis_only`.
9. Update `app/checkpointer.py` `ALLOWED_CHECKPOINT_TYPES` with `CodePatch`, `FilePatch`, `CodeContext`, `PullRequestInfo`.
10. Add `worker/code_fix_runner.py:run_code_fix(incident_id, alert)`:
    - load mapping and alert.
    - invoke graph with Postgres checkpointer.
    - persist `CodeFixAttempt`.
11. Add `scripts/verify_code_context.py`:
    - fetch a real file at a real SHA from the target repo.
    - parse it with Tree-sitter.
    - print function/imports/tests; no mock.
12. Add latency guards:
    - max 3 files, max 200 diff lines.
    - if context > 6,000 tokens, reduce related tests first, then imports.
    - if model exceeds timeout, return `analysis_only` with a clear reason.

**Credentials/permissions**

- GitHub App `contents:read`.
- Ollama URL (local or ECS service discovery).
- No AWS permissions beyond reading the DB.

**Pitfalls**

- CPU-only `qwen2.5-coder:3b` is significantly slower than 1.5B; benchmark early on the actual i5-10210U (4C/8T). Keep context small, cap output tokens, and be prepared to reduce the SLO or move Ollama to a GPU/EC2 host if p95 exceeds 15 minutes.
- Models often wrap diffs in Markdown fences; strip fences and validate schema.
- Hallucinated file paths must be rejected before applying.
- Tree-sitter node positions are 0-based; convert to 1-based carefully.
- Do not send entire repository files; send the function plus imports/tests.
- If the model returns multiple unrelated hunks, reject.

**Exit criteria**

- A real alert at a real SHA produces a `CodePatch` with the correct file path.
- The diff applies cleanly to the real code.
- p95 generation time is measured and within the 15-minute SLO.

---

### Phase 7 — Patch validation sandbox and policy gates (3–4 days)

**Objective:** Reject unsafe or invalid patches before any GitHub write.

**Tiny tasks**

1. Add `app/code_fix/validation.py`:
   - `validate_patch(mapping, commit_sha, patch) -> ValidationResult`
   - `check_path_policy(path, mapping)`
   - `check_diff_limits(patch)`
   - `prepare_workspace(repo, commit_sha, files)`
   - `apply_check(workspace, patch)`
   - `lint_check(workspace, changed_files)`
   - `secret_scan(workspace)`
2. Policy:
   - Allowed extensions: `.py`.
   - Max files: `GITHUB_MAX_FILES=3`.
   - Max changed lines: `GITHUB_MAX_DIFF_LINES=200`.
   - Denied paths: `.github/workflows/`, `migrations/`, `alembic/`, `auth/`, `payments/`, `Dockerfile`, `.env`, `secrets/`, lockfiles.
   - Reject binary, symlink, generated, vendored files.
3. Workspace:
   - Fetch base files at `commit_sha` via GitHub API into a temp directory.
   - `git init`, `git add`, `git commit` baseline.
   - `git apply --check patch.diff`.
   - `git apply patch.diff`.
4. Static checks:
   - `python -m compileall -q <changed_files>`.
   - `ruff check <changed_files>` if configured.
   - `gitleaks detect --no-git --source <workspace> --redact`.
   - `git diff --check` for whitespace errors.
5. Do **not** execute target repo tests locally. Full tests run in GitHub Actions to avoid untrusted code execution on the worker.
6. On failure:
   - feed validation errors to `repair_patch` once.
   - if still invalid, set `patch_invalid`, notify, no branch/PR.
7. Add `Dockerfile.patch-validator` only if you later need a containerized validator. For now, run static checks in the worker image with no AWS credentials and a read-only workspace.
8. Add a real validation drill:
   - generate a patch that touches `.github/workflows/ci.yml`; assert it is rejected.
   - generate a patch with a hardcoded secret; assert `gitleaks` rejects it.
9. Persist `CodeFixAttempt.validation_status`, `validation_errors`, `patch_hash`.
10. Audit: `patch.generated`, `patch.validation_failed`, `patch.validated` with hashes/model/prompt version.

**Credentials/permissions**

- GitHub App `contents:read`.
- No write permissions in this phase.
- No AWS secrets in the validation workspace.

**Pitfalls**

- `git apply` is context-sensitive; CRLF/line-ending differences can cause false failures.
- `gitleaks` may flag test fixtures; use allowlist only for known test paths, not broad ignores.
- Do not run `pytest` locally on untrusted patches; a malicious patch could exfiltrate secrets.
- Path denylist must be enforced after normalization; reject `..` and absolute paths.
- A patch that only changes tests is suspicious; reject or escalate.

**Exit criteria**

- Invalid diffs, denied paths, secrets, and oversized patches never reach GitHub.
- Valid patches apply cleanly and pass static checks.
- Validation failures produce a clear incident status and notification.

---

### Phase 8 — Branch, commit, and Draft PR creation (2 days)

**Objective:** Publish the validated patch as a Draft PR with a professional, auditable description.

**Tiny tasks**

1. Add `app/code_fix/pr.py`:
   - `build_branch_name(incident_id, attempt)` → `opsflow/fix-<short>-<attempt>`.
   - `build_pr_title(alert, patch)`.
   - `build_pr_body(alert, patch, validation, mapping)`.
   - `create_draft_pr(...)`.
2. PR body includes:
   - Incident ID and link.
   - Service, environment, commit SHA.
   - Root cause and evidence summary.
   - Proposed fix and risk notes.
   - Validation results.
   - Required checks and rollback plan.
   - Model, prompt version, patch hash.
   - “AI-generated; human review required.”
3. Use GitHub Git Data API:
   - `create_git_blob` per changed file.
   - `create_git_tree` with base tree.
   - `create_git_commit`.
   - `create_ref` for the branch.
   - `create_pull` with `draft=True`, base `main`.
4. Add labels `opsflow`, `ai-generated`, `code-fix` only if the App has `issues:write`.
5. Request reviewers from `CODEOWNERS`/team mapping; do not request the bot.
6. Persist `CodePullRequest` and update incident status `pr_opened`; audit `pr.created`.
7. Idempotency:
   - unique `(repo_full_name, branch_name)`.
   - if branch or PR exists for the incident, return it; do not create a second.
8. Add `scripts/verify_draft_pr.py`:
   - create a real draft PR on the staging repo from a real validated patch.
   - print PR URL; close it after verification if desired.
9. Add comment on PR with CI expectations.

**Credentials/permissions**

- GitHub App `contents:write`, `pull_requests:write`, `metadata:read`.
- `issues:write` only if using labels.
- Branch protection allows the bot to push `opsflow/*`, not `main`.

**Pitfalls**

- Draft PR creation fails if the head branch does not exist; create the ref first.
- GitHub App commits must have a valid author/committer; use the app bot identity.
- Do not force-push; create a new attempt branch if needed.
- PR body must not include raw logs, secrets, or PII.
- If labels are not permitted, skip labels rather than failing the entire PR.

**Exit criteria**

- A real Draft PR is created against `main` with the validated diff.
- The bot cannot merge; branch protection is verified.
- PR URL is stored and emailed to the manager.

---

### Phase 9 — Async CI webhooks, required checks, and notifications (2–3 days)

**Objective:** React to real GitHub Actions results without blocking a worker.

**Tiny tasks**

1. In `worker/consumers/github_consumer.py`:
   - `handle_check_run(event)`.
   - `handle_check_suite(event)`.
   - `handle_workflow_run(event)`.
   - `handle_pull_request(event)`.
2. Match the event to `CodePullRequest` by repo + PR number + head SHA.
3. Upsert `CiRun` with `external_id`, check name, status, conclusion, details URL.
4. Add `app/code_fix/ci.py`:
   - `required_checks(mapping) -> list[str]`.
   - `aggregate_ci_status(pr, runs) -> "pending"|"passed"|"failed"`.
   - Only `success` counts as pass; `neutral`/`skipped` do not unless explicitly configured.
5. On all required checks passed:
   - `GitHubAppClient.mark_ready_for_review`.
   - update `CodePullRequest.state="ready"`, `ci_status="passed"`.
   - update incident `awaiting_review`.
   - notify manager via `integrations/notifications.py:send_pr_ready`.
   - audit `ci.passed`, `pr.ready`.
6. On any required check failed:
   - comment on PR with failing check names and details URLs.
   - update incident `ci_failed`.
   - notify manager.
   - keep the PR in Draft; do not close automatically.
7. On timeout:
   - `worker/reconciler.py` scans PRs in `ci_running` older than `GITHUB_CI_TIMEOUT_MINUTES`.
   - mark `ci_timeout`, notify, keep Draft.
8. Add notification functions/templates:
   - `send_pr_ready`
   - `send_ci_failed`
   - `send_review_reminder`
   - `send_analysis_only`
   Use existing Resend/Slack modules and tenant manager mapping.
9. Verify branch protection requires exactly `test` and `lint`; confirm names from a real PR check run.
10. Trigger a real CI failure and a real CI pass; verify both state transitions.

**Credentials/permissions**

- GitHub App `checks:read`, `actions:read`, `pull_requests:write`.
- Webhook secret.
- SQS GitHub events queue.
- SMTP/Resend/Slack credentials.

**Pitfalls**

- `check_run` events fire multiple times; upsert by external ID.
- Stale check runs from previous commits must be ignored by head SHA.
- Matrix jobs may be named `test (3.12)`; match the exact required names.
- `workflow_run` and `check_run` can duplicate; dedupe.
- Do not mark ready on a skipped check.
- GitHub webhook retries can arrive out of order; reconcile from the GitHub API if needed.

**Exit criteria**

- Passing CI marks the PR ready and emails the manager.
- Failing CI comments and notifies; PR remains Draft.
- CI timeout is detected without a blocked worker.

---

### Phase 10 — Merge webhook, ECS deployment events, verification, and revert (4–5 days)

**Objective:** Verify the fix in production after deployment; open a Draft revert PR if the error recurs.

**Tiny tasks**

1. `handle_pull_request` merged:
   - update `CodePullRequest.merged_sha`, `merged_by`, `merged_at`.
   - incident status `merged`.
   - audit `pr.merged`.
2. `handle_pull_request` closed unmerged:
   - incident `rejected`; audit `pr.rejected`; notify.
3. Create EventBridge rule:
   ```bash
   aws events put-rule \
     --name "opsflow-ecs-deployments-$ENV" \
     --event-pattern '{"source":["aws.ecs"],"detail-type":["ECS Deployment State Change"]}'
   ```
4. Create deployment SQS queue and DLQ; add queue policy allowing `events.amazonaws.com` to send messages from the rule.
5. Add EventBridge target:
   ```bash
   aws events put-targets \
     --rule "opsflow-ecs-deployments-$ENV" \
     --targets '[{"Id":"opsflow-deployments","Arn":"arn:aws:sqs:'"$AWS_REGION"':'"$ACCOUNT_ID"':opsflow-deployments-'"$ENV"'"}]'
   ```
6. `DeploymentConsumer.handle_ecs_deployment`:
   - ignore non-completed/in-progress events.
   - match `detail.clusterArn`/`detail.service` or resources to `RepositoryMapping`.
   - resolve `commit_sha` from the ECS task definition env `GIT_COMMIT_SHA`.
   - find merged `CodePullRequest` with that SHA.
   - create `Deployment` and `FixVerification` with deadline `now + 15 min`.
   - incident status `verifying`.
7. Add `worker/verification_worker.py`:
   - loop every 60 s.
   - select `FixVerification.status in ("pending","verifying")`.
   - call `CloudWatchLogsClient.filter_errors(log_group, start_time, pattern)`.
   - pattern:
     ```text
     { $.service = "<service>" && $.commit_sha = "<sha>" && $.level = "ERROR" }
     ```
   - count matches; if `count >= POST_MERGE_ERROR_THRESHOLD`, mark regression.
   - if `now >= deadline` and no matches, mark verified.
   - on CloudWatch API error, retry; after deadline mark `inconclusive` and notify.
8. On verified:
   - `FixVerification.status="verified"`.
   - `Incident.status="verified"`, `resolved_at=now`.
   - audit `verification.passed`.
   - notify manager.
9. On regression:
   - `FixVerification.status="regressed"`.
   - `Incident.status="regressed"`.
   - `GitHubAppClient.open_revert_pr(...)`.
   - audit `verification.failed`, `revert.created`.
   - notify manager with evidence and revert PR URL.
10. Revert implementation:
    - clone the repo at `main`.
    - `git revert --no-commit <merge_sha>`.
    - if merge commit, use `git revert -m 1 <merge_sha>`; detect parents.
    - commit, push branch `opsflow/revert-<pr_number>`.
    - open Draft PR with reason, evidence, original PR link.
    - if conflict: do not force; create a comment/issue and notify.
11. Add `worker/reconciler.py:reconcile_deployments()`:
    - if no EventBridge event after 10 minutes, poll ECS `describe_services` for a new deployment.
    - if steady state and new task definition, create verification.
12. Add `docs/runbooks/GITOPS.md` for deployment event debugging, CloudWatch query, revert conflicts.

**Credentials/permissions**

- EventBridge role: SQS SendMessage to deployment queue.
- Deployment consumer task role: SQS Receive/Delete/ChangeVisibility, ECS Describe, CloudWatch Logs FilterLogEvents.
- GitHub App: `contents:write`, `pull_requests:write`.
- SQS queue policy for EventBridge.

**Pitfalls**

- ECS emits multiple deployment events; ignore in-progress and duplicate deployment IDs.
- The event may not include the commit SHA; resolve it from the task definition.
- A deployment can take longer than 15 minutes; start the window at deployment completion, not merge.
- CloudWatch Logs are eventually consistent; add a 2-minute grace before declaring clean.
- Unrelated errors can trigger a false revert; match the original fingerprint and require the configured threshold.
- Revert conflicts must escalate, never force-push.
- Do not auto-merge the revert.

**Exit criteria**

- A real merged PR produces a real ECS deployment event.
- OpsFlow verifies a clean 15-minute window and marks the incident resolved.
- Reintroducing the real error produces a Draft revert PR and a regression notification.

---

### Phase 11 — Security, observability, cost, and operations (2–3 days)

**Objective:** Make the system safe and operable before production use.

**Tiny tasks**

1. Write `docs/THREAT_MODEL.md`:
   - prompt injection via logs/code
   - malicious code changes
   - secret exfiltration via CI
   - GitHub token leakage
   - cross-tenant repo access
   - webhook spoofing/replay
   - SQS poison messages
   - model hallucination
   - supply-chain compromise
2. Reuse `app/safety/redact.py` before sending logs/code to Ollama; add secret scanning before prompts.
3. Ensure CI:
   - `permissions: contents: read` for test/lint jobs.
   - no repository secrets in PR workflows.
   - `pull_request`, not `pull_request_target`.
   - actions pinned by commit SHA.
   - `CODEOWNERS` protects workflows.
4. Ensure branch protection:
   - bot cannot merge.
   - required reviews and checks.
   - no force-push to `main`.
5. IAM:
   - no wildcard `*` actions/resources except where unavoidable; document exceptions.
   - separate API/worker roles.
   - no long-lived AWS keys in GitHub; OIDC only.
6. Observability:
   - add spans: `webhook.received`, `sqs.publish`, `consumer.alert`, `github.fetch`, `llm.generate`, `patch.validate`, `pr.create`, `ci.event`, `deployment.event`, `verification.poll`, `revert.create`.
   - metrics: `opsflow_code_fix_total`, `opsflow_code_fix_duration_seconds`, `opsflow_patch_validation_failed_total`, `opsflow_pr_created_total`, `opsflow_ci_passed_total`, `opsflow_ci_failed_total`, `opsflow_verification_failed_total`, `opsflow_llm_tokens_total`.
   - CloudWatch alarms: DLQ depth, Lambda errors, SQS age, ECS task failures, GitHub 429, LLM timeout.
7. Cost controls:
   - max 1 concurrent fix.
   - max 3 files / 200 lines.
   - CloudWatch retention 30 days.
   - GitHub Actions minutes budget.
   - daily LLM token budget.
   - `CODE_FIX_ENABLED=false` kill switch.
8. Runbooks:
   - DLQ replay.
   - GitHub App key rotation.
   - Ollama unavailable.
   - SQS backlog.
   - bad PR / revert.
   - secret leak response.
9. Audit:
   - prompt hash, model, diff hash, validation, PR, CI, merge, deployment, verification.
   - actor `agent`/`human`; tenant/repo/incident IDs.

**Credentials/permissions**

- Security review approval.
- Secrets Manager rotation.
- CloudTrail/GuardDuty optional for enterprise.

**Pitfalls**

- Don’t let the LLM call tools or execute shell commands.
- Don’t log prompts containing PII/secrets.
- Don’t give the bot `workflows:write`.
- Don’t let the bot bypass branch protection.
- Don’t ignore DLQ alarms.

**Exit criteria**

- Threat model reviewed.
- All alarms and dashboards live.
- Kill switch tested.
- Runbooks complete.

---

### Phase 12 — Real end-to-end validation and rollout (3–5 days)

**Objective:** Prove the complete flow on real infrastructure and roll out safely.

**Tiny tasks**

1. Deploy the real staging service with `ENABLE_TEST_BUG=true`.
2. Trigger `/debug/boom`; confirm:
   - CloudWatch log
   - Lambda decode
   - SQS message
   - alert consumer incident
   - repo mapping
   - code fetch at exact SHA
   - patch generation
   - validation
   - Draft PR
   - CI `test` + `lint`
   - PR ready + manager email
3. Merge the Draft PR; confirm:
   - `pull_request` merged webhook
   - new ECS deployment
   - EventBridge deployment event
   - 15-minute CloudWatch clean window
   - incident `verified`
4. Regression drill:
   - deploy a real commit that reintroduces the bug (staging only).
   - confirm verification detects the error and opens a Draft revert PR.
   - human approves/merges the revert; confirm the system does not auto-merge.
5. Failure drills:
   - remove the repo mapping → `repo_unmapped`.
   - omit `commit_sha` → analysis-only, no PR.
   - revoke GitHub App permission → retry, then DLQ/alarm.
   - stop Ollama → timeout, analysis-only.
   - make CI fail → comment + notify, Draft remains.
   - force a GitHub 429 → backoff and retry.
   - send a malformed SQS message → DLQ, alarm.
   - inject a prompt-injection line into a real log → model ignores it; patch remains scoped.
6. Performance:
   - measure alert→Draft PR p95 for 5–10 incidents/day.
   - if p95 > 15 min, reduce context to 4k, max 2 files, 120 diff lines, or increase Fargate CPU.
7. Rollout:
   - Week 1: `CODE_FIX_ANALYSIS_ONLY=true`; produce reports only.
   - Week 2: Draft PRs for one repo, one service.
   - Week 3: Draft PRs for all allowlisted repos.
   - Never enable auto-merge.
8. Acceptance criteria:
   - 100% patches pass local validation.
   - 0 duplicate PRs.
   - 100% PRs have incident link, evidence, validation, rollback.
   - 95% verification completes within 20 minutes of deployment.
   - 0 secrets in prompts/PRs/logs.
   - p95 alert→Draft PR < 15 minutes.
9. Update `README.md`, `docs/CONFIGURATION_GUIDE.md`, and `docs/runbooks/GITOPS.md`.

**Credentials/permissions**

- Staging and production deploy roles.
- Manager email/notification test account.
- No new permissions.

**Pitfalls**

- Do not run the first E2E against production.
- Do not leave `ENABLE_TEST_BUG=true` in production.
- Do not enable Draft PR creation before validation/policy gates are proven.
- Do not treat a merged PR as resolved; wait for deployment verification.
- Do not ignore `inconclusive` verification; escalate to a human.

**Exit criteria**

- Full real E2E passed.
- Regression and revert drills passed.
- Kill switch and rollback tested.
- Sign-off from engineering/security.

---

## 5. Failure handling matrix

| Failure | Detection | Action | Incident status |
|---|---|---|---|
| Missing `commit_sha` | Alert schema / ECS fallback | Analysis-only report; no branch/PR; notify | `analysis_only` |
| No repo mapping | DB lookup | Notify; no PR; audit | `repo_unmapped` |
| GitHub 401/403 | API response | Refresh token; retry; escalate | `escalated` |
| GitHub 429 | API response | Exponential backoff + jitter; retry | `retrying` |
| Ollama timeout | HTTP timeout | Retry once with smaller context; then analysis-only | `analysis_only` |
| Invalid patch | `git apply`/lint/secret scan | Repair once; then reject | `patch_invalid` |
| Denied path | Policy check | Reject; notify | `patch_invalid` |
| CI failure | `check_run` failed | Comment + notify; keep Draft | `ci_failed` |
| CI timeout | Reconciler | Notify; keep Draft | `ci_timeout` |
| Duplicate webhook | `github_events.delivery_id` | Ignore; return 200 | unchanged |
| SQS poison message | Receive count > 5 | DLQ + alarm | unchanged |
| Deployment event missing | Reconciler | Poll ECS; start verification | `verifying` |
| CloudWatch API error | Exception | Retry; after deadline mark inconclusive | `inconclusive` |
| Error recurs | CloudWatch query | Draft revert PR; notify | `regressed` |
| Revert conflict | git apply/revert | Comment/issue; notify; no force-push | `escalated` |
| Secret found | gitleaks | Reject patch; notify security | `patch_invalid` |
| Cross-tenant access | Policy check | Reject; security alert | `escalated` |

---

## 6. Security controls

- **Least privilege:** separate ECS task roles for API, alert consumer, GitHub consumer, deployment consumer, verification worker.
- **No long-lived AWS keys:** GitHub Actions uses OIDC; local dev uses AWS SSO/profile.
- **GitHub App:** installation tokens, no PAT; no `workflows:write`; no admin; no merge.
- **Branch protection:** required reviews, required checks, no bypass, no force-push to `main`.
- **CODEOWNERS:** protects workflows, migrations, auth, payments.
- **Prompt injection:** logs and code are untrusted; model returns structured diff only; no tool execution; path denylist.
- **Secret scanning:** `gitleaks` before PR; GitHub secret scanning; no secrets in prompts.
- **CI hardening:** `pull_request` not `pull_request_target`; minimal `GITHUB_TOKEN`; no repository secrets in PR workflows; pin actions by SHA.
- **Network:** private subnets, no public RDS/Redis/Ollama, VPC endpoints, security groups.
- **Data:** redact PII/secrets; CloudWatch retention 30 days; audit logs retained per policy.
- **Kill switch:** `CODE_FIX_ENABLED=false` global; per-tenant disable; revoke GitHub App installation as last resort.
- **Audit:** every state transition with tenant, repo, incident, PR, commit SHA, model, prompt version, diff hash.

---

## 7. Observability, SLOs, and cost

**SLOs**

- 99% of CloudWatch errors reach SQS within 60 seconds.
- p95 alert→Draft PR < 15 minutes.
- 100% of PRs pass local static validation.
- 0 duplicate PRs per incident.
- 95% of deployments verified within 20 minutes.
- 0 secrets in prompts, PRs, or logs.

**Metrics**

```text
opsflow_code_fix_total{status,tenant,repo}
opsflow_code_fix_duration_seconds{stage}
opsflow_patch_validation_failed_total{reason}
opsflow_pr_created_total{repo}
opsflow_ci_passed_total{repo}
opsflow_ci_failed_total{repo}
opsflow_verification_failed_total{repo}
opsflow_llm_tokens_total{model}
opsflow_sqs_dlq_depth{queue}
```

**Alarms**

- SQS DLQ depth > 0.
- SQS oldest message age > 10 minutes.
- Lambda errors >= 1.
- ECS service running count < desired.
- GitHub 429 rate > threshold.
- Ollama timeout rate > 5%.
- Verification `inconclusive` > 0.

**Cost controls**

- Max 1 concurrent code fix.
- Max 3 files / 200 diff lines per patch.
- CloudWatch retention 30 days.
- Daily token budget and GitHub Actions minutes budget.
- Fargate right-sizing; review CPU/memory monthly.
- Optional: switch Ollama to GPU EC2 only if p95 SLO is missed.

---

## 8. Realistic timeline

| Phase | Duration | Dependency |
|---|---|---|
| 0. Preconditions | 1–2 days | AWS/GitHub access |
| 1. Target service + logs | 3–4 days | Phase 0 |
| 2. CloudWatch → Lambda → SQS | 2–3 days | Phase 1 |
| 3. OpsFlow runtime + consumers | 4–5 days | Phase 2 |
| 4. Repo mapping + tenancy | 2–3 days | Phase 3 |
| 5. GitHub App + webhook | 2–3 days | Phase 3 |
| 6. Context + patch generation | 4–6 days | Phases 4, 5 |
| 7. Validation + policy | 3–4 days | Phase 6 |
| 8. Draft PR | 2 days | Phase 7 |
| 9. CI webhooks + notifications | 2–3 days | Phase 8 |
| 10. Deployment verification + revert | 4–5 days | Phase 9 |
| 11. Security/observability | 2–3 days | Phase 10 |
| 12. E2E + rollout | 3–5 days | Phase 11 |

**Total: ~34–45 working days for one engineer.**  
A 7-day demo is only realistic if Phases 10–12 and hardening are deferred; it would not be production-grade.

---

## 9. First files to create

```text
lambda/cloudwatch_forwarder/handler.py
lambda/cloudwatch_forwarder/requirements.txt
lambda/cloudwatch_forwarder/build.sh

integrations/aws/__init__.py
integrations/aws/sqs.py
integrations/aws/cloudwatch.py
integrations/aws/ecs.py
integrations/github_service.py

ingestion/code_alert_schema.py

worker/consumers/__init__.py
worker/consumers/base.py
worker/consumers/alert_consumer.py
worker/consumers/github_consumer.py
worker/consumers/deployment_consumer.py
worker/verification_worker.py
worker/reconciler.py
worker/code_fix_runner.py

app/code_fix/__init__.py
app/code_fix/statuses.py
app/code_fix/schemas.py
app/code_fix/state.py
app/code_fix/policy.py
app/code_fix/repository_mapping.py
app/code_fix/context.py
app/code_fix/prompts.py
app/code_fix/llm.py
app/code_fix/validation.py
app/code_fix/pr.py
app/code_fix/ci.py
app/code_fix/graph.py
app/code_fix/verification.py

api/routes/github_webhooks.py

scripts/register_github_installation.py
scripts/register_repo_mapping.py
scripts/verify_github_app.py
scripts/verify_code_context.py
scripts/verify_draft_pr.py
scripts/verify_aws_ingestion.py

deploy/ecs/api-task.json
deploy/ecs/alert-consumer-task.json
deploy/ecs/github-consumer-task.json
deploy/ecs/deployment-consumer-task.json
deploy/ecs/verification-worker-task.json
deploy/ecs/ollama-task.json
deploy/aws/01-sqs.sh
deploy/aws/02-lambda.sh
deploy/aws/03-ecs.sh
deploy/aws/04-eventbridge.sh

Dockerfile.api
Dockerfile.worker
Dockerfile.patch-validator
.dockerignore

docs/ADR-001-code-remediation.md
docs/THREAT_MODEL.md
docs/runbooks/GITOPS.md
```
