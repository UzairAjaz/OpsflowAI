#!/usr/bin/env bash
# Create least-privilege IAM roles for ECS tasks and the CloudWatch forwarder.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

: "${ALERTS_QUEUE_ARN:?Run 02-sqs.sh first}"
: "${GITHUB_EVENTS_QUEUE_ARN:?Run 02-sqs.sh first}"
: "${DEPLOYMENTS_QUEUE_ARN:?Run 02-sqs.sh first}"

TMP_DIR="$ROOT_DIR/deploy/aws/.tmp"
mkdir -p "$TMP_DIR"

ensure_role() {
  local name="$1" trust_file="$2"
  if "${AWS[@]}" iam get-role --role-name "$name" >/dev/null 2>&1; then
    "${AWS[@]}" iam update-assume-role-policy \
      --role-name "$name" --policy-document "file://$trust_file" >/dev/null
    log "role exists: $name"
  else
    "${AWS[@]}" iam create-role \
      --role-name "$name" --assume-role-policy-document "file://$trust_file" >/dev/null
    log "created role: $name"
  fi
  "${AWS[@]}" iam get-role --role-name "$name" --query 'Role.Arn' --output text
}

ecs_trust="$TMP_DIR/ecs-tasks-trust.json"
lambda_trust="$TMP_DIR/lambda-trust.json"
cat > "$ecs_trust" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON
cat > "$lambda_trust" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON

execution_role="$(ensure_role "$NAME_PREFIX-ecs-task-execution" "$ecs_trust")"
api_role="$(ensure_role "$NAME_PREFIX-api-task" "$ecs_trust")"
worker_role="$(ensure_role "$NAME_PREFIX-worker-task" "$ecs_trust")"
lambda_role="$(ensure_role "$NAME_PREFIX-lambda-forwarder" "$lambda_trust")"

save_state EXECUTION_ROLE_ARN "$execution_role"
save_state API_TASK_ROLE_ARN "$api_role"
save_state WORKER_TASK_ROLE_ARN "$worker_role"
save_state LAMBDA_ROLE_ARN "$lambda_role"

"${AWS[@]}" iam attach-role-policy \
  --role-name "$NAME_PREFIX-ecs-task-execution" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy >/dev/null

# Execution role: read only the app's secrets and decrypt with account KMS keys.
execution_policy="$(jq -cn \
  --arg region "$AWS_REGION" \
  --arg account "$ACCOUNT_ID" \
  --arg prefix "$PROJECT/$ENV" \
  '{
    Version: "2012-10-17",
    Statement: [
      {
        Effect: "Allow",
        Action: ["secretsmanager:GetSecretValue"],
        Resource: ["arn:aws:secretsmanager:\($region):\($account):secret:\($prefix)/*"]
      },
      {
        Effect: "Allow",
        Action: ["kms:Decrypt"],
        Resource: ["arn:aws:kms:\($region):\($account):key/*"]
      }
    ]
  }')"
"${AWS[@]}" iam put-role-policy \
  --role-name "$NAME_PREFIX-ecs-task-execution" \
  --policy-name "$NAME_PREFIX-execution-secrets" \
  --policy-document "$execution_policy" >/dev/null

# API role: publish GitHub events to SQS and write its own logs.
api_policy="$(jq -cn \
  --arg region "$AWS_REGION" \
  --arg account "$ACCOUNT_ID" \
  --arg prefix "$NAME_PREFIX" \
  --arg queue "$GITHUB_EVENTS_QUEUE_ARN" \
  '{
    Version: "2012-10-17",
    Statement: [
      {
        Effect: "Allow",
        Action: ["sqs:SendMessage"],
        Resource: [$queue]
      },
      {
        Effect: "Allow",
        Action: ["logs:CreateLogStream", "logs:PutLogEvents"],
        Resource: ["arn:aws:logs:\($region):\($account):log-group:/ecs/opsflow-api:*"]
      }
    ]
  }')"
"${AWS[@]}" iam put-role-policy \
  --role-name "$NAME_PREFIX-api-task" \
  --policy-name "$NAME_PREFIX-api-sqs" \
  --policy-document "$api_policy" >/dev/null

# Worker role: consume queues, read CloudWatch, inspect ECS, read app secrets.
worker_policy="$(jq -cn \
  --arg region "$AWS_REGION" \
  --arg account "$ACCOUNT_ID" \
  --arg prefix "$NAME_PREFIX" \
  --arg alerts "$ALERTS_QUEUE_ARN" \
  --arg github "$GITHUB_EVENTS_QUEUE_ARN" \
  --arg deployments "$DEPLOYMENTS_QUEUE_ARN" \
  '{
    Version: "2012-10-17",
    Statement: [
      {
        Effect: "Allow",
        Action: [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:GetQueueAttributes"
        ],
        Resource: [$alerts, $github, $deployments]
      },
      {
        Effect: "Allow",
        Action: ["logs:CreateLogStream", "logs:PutLogEvents"],
        Resource: ["arn:aws:logs:\($region):\($account):log-group:/ecs/opsflow-*:*"]
      },
      {
        Effect: "Allow",
        Action: ["logs:FilterLogEvents"],
        Resource: ["arn:aws:logs:\($region):\($account):log-group:/ecs/*"]
      },
      {
        Effect: "Allow",
        Action: ["ecs:DescribeServices", "ecs:DescribeTaskDefinition"],
        Resource: ["*"]
      },
      {
        Effect: "Allow",
        Action: ["secretsmanager:GetSecretValue"],
        Resource: ["arn:aws:secretsmanager:\($region):\($account):secret:\($prefix)/*"]
      },
      {
        Effect: "Allow",
        Action: ["kms:Decrypt"],
        Resource: ["arn:aws:kms:\($region):\($account):key/*"]
      }
    ]
  }')"
"${AWS[@]}" iam put-role-policy \
  --role-name "$NAME_PREFIX-worker-task" \
  --policy-name "$NAME_PREFIX-worker-queues" \
  --policy-document "$worker_policy" >/dev/null

# Lambda role: send to the alerts queue and write its own logs.
lambda_policy="$(jq -cn \
  --arg region "$AWS_REGION" \
  --arg account "$ACCOUNT_ID" \
  --arg prefix "$NAME_PREFIX" \
  --arg queue "$ALERTS_QUEUE_ARN" \
  '{
    Version: "2012-10-17",
    Statement: [
      {
        Effect: "Allow",
        Action: ["sqs:SendMessage"],
        Resource: [$queue]
      },
      {
        Effect: "Allow",
        Action: ["logs:CreateLogStream", "logs:PutLogEvents"],
        Resource: ["arn:aws:logs:\($region):\($account):log-group:/aws/lambda/\($prefix)-cloudwatch-forwarder:*"]
      }
    ]
  }')"
"${AWS[@]}" iam put-role-policy \
  --role-name "$NAME_PREFIX-lambda-forwarder" \
  --policy-name "$NAME_PREFIX-lambda-forwarder" \
  --policy-document "$lambda_policy" >/dev/null

log "IAM roles are ready. Waiting for IAM propagation..."
sleep 8

summary
log "Next: ./deploy/aws/04-lambda.sh"
