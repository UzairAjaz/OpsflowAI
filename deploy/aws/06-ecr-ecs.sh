#!/usr/bin/env bash
# Create ECR repositories, the ECS Fargate cluster, and CloudWatch log groups.
# ECS services are created in Phase 3 after images exist.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

CLUSTER_NAME="$NAME_PREFIX"
LIFECYCLE_POLICY='{"rules":[{"rulePriority":1,"description":"Keep last 10 images","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}'

ensure_ecr_repo() {
  local name="$1"
  if "${AWS[@]}" ecr describe-repositories --repository-names "$name" >/dev/null 2>&1; then
    log "ECR repo exists: $name"
  else
    "${AWS[@]}" ecr create-repository \
      --repository-name "$name" \
      --image-scanning-configuration scanOnPush=true \
      --encryption-configuration encryptionType=AES256 >/dev/null
    log "created ECR repo: $name"
  fi
  "${AWS[@]}" ecr put-lifecycle-policy \
    --repository-name "$name" \
    --lifecycle-policy-text "$LIFECYCLE_POLICY" >/dev/null
  "${AWS[@]}" ecr describe-repositories \
    --repository-names "$name" \
    --query 'repositories[0].repositoryUri' --output text
}

API_ECR_URI="$(ensure_ecr_repo "$PROJECT/api")"
WORKER_ECR_URI="$(ensure_ecr_repo "$PROJECT/worker")"
save_state API_ECR_URI "$API_ECR_URI"
save_state WORKER_ECR_URI "$WORKER_ECR_URI"

if "${AWS[@]}" ecs describe-clusters --clusters "$CLUSTER_NAME" \
  --query 'clusters[?status==`ACTIVE`].clusterName | [0]' --output text 2>/dev/null | grep -q .; then
  log "ECS cluster exists: $CLUSTER_NAME"
else
  "${AWS[@]}" ecs create-cluster \
    --cluster-name "$CLUSTER_NAME" \
    --capacity-providers FARGATE FARGATE_SPOT \
    --settings name=containerInsights,value=enabled >/dev/null
  log "created ECS cluster: $CLUSTER_NAME"
fi
save_state ECS_CLUSTER "$CLUSTER_NAME"

for log_group in \
  "/ecs/opsflow-api" \
  "/ecs/opsflow-alert-consumer" \
  "/ecs/opsflow-github-consumer" \
  "/ecs/opsflow-deployment-consumer" \
  "/ecs/opsflow-verification-worker" \
  "/ecs/opsflow-ollama" \
  "/ecs/$TARGET_SERVICE"; do
  if "${AWS[@]}" logs describe-log-groups --log-group-name-prefix "$log_group" \
    --query "logGroups[?logGroupName=='$log_group'].logGroupName | [0]" --output text | grep -q .; then
    log "log group exists: $log_group"
  else
    "${AWS[@]}" logs create-log-group --log-group-name "$log_group" >/dev/null
    "${AWS[@]}" logs put-retention-policy --log-group-name "$log_group" --retention-in-days 30 >/dev/null
    log "created log group: $log_group"
  fi
done

summary
log "ECR API:    $API_ECR_URI"
log "ECR worker: $WORKER_ECR_URI"
log "Next: ./deploy/aws/07-alb-acm-route53.sh"
