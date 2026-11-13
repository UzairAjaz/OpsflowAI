#!/usr/bin/env bash
# Create GitHub Actions OIDC roles for deploying OpsFlow and the target service.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

: "${EXECUTION_ROLE_ARN:?Run 03-iam.sh first}"
: "${API_TASK_ROLE_ARN:?Run 03-iam.sh first}"
: "${WORKER_TASK_ROLE_ARN:?Run 03-iam.sh first}"

OIDC_URL="https://token.actions.githubusercontent.com"
OIDC_ARN="arn:aws:iam::$ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"

if ! "${AWS[@]}" iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" >/dev/null 2>&1; then
  "${AWS[@]}" iam create-open-id-connect-provider \
    --url "$OIDC_URL" \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 >/dev/null
  log "created GitHub OIDC provider"
else
  log "GitHub OIDC provider exists"
fi

ensure_oidc_role() {
  local role_name="$1" repo="$2"
  local trust_file="$ROOT_DIR/deploy/aws/.tmp/${role_name}-trust.json"
  jq -n \
    --arg provider "$OIDC_ARN" \
    --arg repo "$repo" \
    '{
      Version: "2012-10-17",
      Statement: [{
        Effect: "Allow",
        Principal: {Federated: $provider},
        Action: "sts:AssumeRoleWithWebIdentity",
        Condition: {
          StringEquals: {
            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
          },
          StringLike: {
            "token.actions.githubusercontent.com:sub": ("repo:" + $repo + ":ref:refs/heads/main")
          }
        }
      }]
    }' > "$trust_file"

  if "${AWS[@]}" iam get-role --role-name "$role_name" >/dev/null 2>&1; then
    "${AWS[@]}" iam update-assume-role-policy \
      --role-name "$role_name" --policy-document "file://$trust_file" >/dev/null
    log "OIDC role exists: $role_name"
  else
    "${AWS[@]}" iam create-role \
      --role-name "$role_name" \
      --assume-role-policy-document "file://$trust_file" >/dev/null
    log "created OIDC role: $role_name"
  fi

  "${AWS[@]}" iam get-role --role-name "$role_name" --query 'Role.Arn' --output text
}

OPSFLOW_DEPLOY_ROLE="$(ensure_oidc_role "gha-deploy-opsflow-$ENV" "$OPSFLOW_REPO")"
TARGET_DEPLOY_ROLE="$(ensure_oidc_role "gha-deploy-${TARGET_SERVICE}-$ENV" "$TARGET_REPO")"
save_state OPSFLOW_DEPLOY_ROLE_ARN "$OPSFLOW_DEPLOY_ROLE"
save_state TARGET_DEPLOY_ROLE_ARN "$TARGET_DEPLOY_ROLE"

deploy_policy="$(jq -cn \
  --arg region "$AWS_REGION" \
  --arg account "$ACCOUNT_ID" \
  --arg project "$PROJECT" \
  --arg target "$TARGET_SERVICE" \
  --arg execution "$EXECUTION_ROLE_ARN" \
  --arg api "$API_TASK_ROLE_ARN" \
  --arg worker "$WORKER_TASK_ROLE_ARN" \
  '{
    Version: "2012-10-17",
    Statement: [
      {
        Effect: "Allow",
        Action: ["ecr:GetAuthorizationToken"],
        Resource: ["*"]
      },
      {
        Effect: "Allow",
        Action: [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage"
        ],
        Resource: [
          "arn:aws:ecr:\($region):\($account):repository/\($project)/*",
          "arn:aws:ecr:\($region):\($account):repository/\($target)"
        ]
      },
      {
        Effect: "Allow",
        Action: [
          "ecs:RegisterTaskDefinition",
          "ecs:UpdateService",
          "ecs:DescribeServices",
          "ecs:DescribeTaskDefinition"
        ],
        Resource: ["*"]
      },
      {
        Effect: "Allow",
        Action: ["iam:PassRole"],
        Resource: ["*"],
        Condition: {"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}}
      },
      {
        Effect: "Allow",
        Action: ["logs:DescribeLogGroups", "logs:CreateLogGroup"],
        Resource: ["arn:aws:logs:\($region):\($account):log-group:/ecs/*"]
      }
    ]
  }')"

for role in "gha-deploy-opsflow-$ENV" "gha-deploy-${TARGET_SERVICE}-$ENV"; do
  "${AWS[@]}" iam put-role-policy \
    --role-name "$role" \
    --policy-name "$NAME_PREFIX-deploy" \
    --policy-document "$deploy_policy" >/dev/null
done

summary
log "OpsFlow deploy role: $OPSFLOW_DEPLOY_ROLE"
log "Target deploy role:  $TARGET_DEPLOY_ROLE"
log "Next: ./deploy/aws/10-outputs.sh"
