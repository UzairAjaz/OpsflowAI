#!/usr/bin/env bash
# Destructive teardown for the OpsFlow staging environment.
# Requires CONFIRM_DESTROY=YES. Does not delete Route53 hosted zones or ACM
# certificates that may be shared with other environments.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

if [[ "${CONFIRM_DESTROY:-}" != "YES" ]]; then
  die "Refusing to destroy resources. Re-run with CONFIRM_DESTROY=YES."
fi

log "DESTROYING $NAME_PREFIX resources in $AWS_REGION ($ACCOUNT_ID)"

# ECS
if [[ -n "${ECS_CLUSTER:-}" ]]; then
  services="$("${AWS[@]}" ecs list-services --cluster "$ECS_CLUSTER" --query 'serviceArns[]' --output text 2>/dev/null || true)"
  for service in $services; do
    "${AWS[@]}" ecs update-service --cluster "$ECS_CLUSTER" --service "$service" --desired-count 0 >/dev/null 2>&1 || true
    "${AWS[@]}" ecs delete-service --cluster "$ECS_CLUSTER" --service "$service" --force >/dev/null 2>&1 || true
  done
  "${AWS[@]}" ecs delete-cluster --cluster "$ECS_CLUSTER" >/dev/null 2>&1 || true
  log "deleted ECS cluster: $ECS_CLUSTER"
fi

# ALB / target groups
if [[ -n "${ALB_ARN:-}" ]]; then
  "${AWS[@]}" elbv2 delete-load-balancer --load-balancer-arn "$ALB_ARN" >/dev/null 2>&1 || true
  log "deleted ALB"
fi
if [[ -n "${TARGET_GROUP_ARN:-}" ]]; then
  "${AWS[@]}" elbv2 delete-target-group --target-group-arn "$TARGET_GROUP_ARN" >/dev/null 2>&1 || true
  log "deleted target group"
fi

# RDS
if [[ -n "${DB_IDENTIFIER:-}" ]]; then
  "${AWS[@]}" rds delete-db-instance \
    --db-instance-identifier "$DB_IDENTIFIER" \
    --skip-final-snapshot --delete-automated-backups >/dev/null 2>&1 || true
  "${AWS[@]}" rds wait db-instance-deleted --db-instance-identifier "$DB_IDENTIFIER" 2>/dev/null || true
  log "deleted RDS: $DB_IDENTIFIER"
fi

# ElastiCache
if [[ -n "${REDIS_CLUSTER_ID:-}" ]]; then
  "${AWS[@]}" elasticache delete-cache-cluster --cache-cluster-id "$REDIS_CLUSTER_ID" >/dev/null 2>&1 || true
  "${AWS[@]}" elasticache wait cache-cluster-deleted --cache-cluster-id "$REDIS_CLUSTER_ID" 2>/dev/null || true
  log "deleted Redis: $REDIS_CLUSTER_ID"
fi

# Lambda
if [[ -n "${LAMBDA_FUNCTION_ARN:-}" ]]; then
  "${AWS[@]}" lambda delete-function --function-name "$LAMBDA_FUNCTION_ARN" >/dev/null 2>&1 || true
  log "deleted Lambda"
fi

# SQS
for name in "$NAME_PREFIX-alerts" "$NAME_PREFIX-alerts-dlq" \
            "$NAME_PREFIX-github-events" "$NAME_PREFIX-github-events-dlq" \
            "$NAME_PREFIX-deployments" "$NAME_PREFIX-deployments-dlq"; do
  url="$(queue_url "$name")"
  if [[ -n "$url" && "$url" != "None" ]]; then
    "${AWS[@]}" sqs delete-queue --queue-url "$url" >/dev/null 2>&1 || true
  fi
done
log "deleted SQS queues"

# EventBridge
if [[ -n "${EVENTBRIDGE_RULE_NAME:-}" ]]; then
  "${AWS[@]}" events remove-targets --rule "$EVENTBRIDGE_RULE_NAME" --ids opsflow-deployments >/dev/null 2>&1 || true
  "${AWS[@]}" events delete-rule --name "$EVENTBRIDGE_RULE_NAME" >/dev/null 2>&1 || true
  log "deleted EventBridge rule"
fi

# Secrets
for secret in "$PROJECT/$ENV/database-url" "$PROJECT/$ENV/redis-url" \
              "$PROJECT/$ENV/redis-auth-token" "$PROJECT/$ENV/github-app" \
              "$PROJECT/$ENV/resend"; do
  "${AWS[@]}" secretsmanager delete-secret --secret-id "$secret" \
    --force-delete-without-recovery >/dev/null 2>&1 || true
done
log "deleted Secrets Manager secrets"

# ECR
for repo in "$PROJECT/api" "$PROJECT/worker"; do
  "${AWS[@]}" ecr delete-repository --repository-name "$repo" --force >/dev/null 2>&1 || true
done
log "deleted ECR repositories"

# VPC endpoints
if [[ -n "${VPC_ID:-}" ]]; then
  endpoints="$("${AWS[@]}" ec2 describe-vpc-endpoints \
    --filters "Name=vpc-id,Values=$VPC_ID" \
    --query 'VpcEndpoints[].VpcEndpointId' --output text 2>/dev/null || true)"
  for endpoint in $endpoints; do
    "${AWS[@]}" ec2 delete-vpc-endpoints --vpc-endpoint-ids "$endpoint" >/dev/null 2>&1 || true
  done
  log "deleted VPC endpoints"
fi

# NAT / EIP / IGW
if [[ -n "${NAT_GATEWAY_ID:-}" ]]; then
  "${AWS[@]}" ec2 delete-nat-gateway --nat-gateway-id "$NAT_GATEWAY_ID" >/dev/null 2>&1 || true
  "${AWS[@]}" ec2 wait nat-gateway-deleted --nat-gateway-ids "$NAT_GATEWAY_ID" 2>/dev/null || true
  log "deleted NAT gateway"
fi
if [[ -n "${NAT_EIP_ALLOCATION_ID:-}" ]]; then
  "${AWS[@]}" ec2 release-address --allocation-id "$NAT_EIP_ALLOCATION_ID" >/dev/null 2>&1 || true
  log "released EIP"
fi
if [[ -n "${IGW_ID:-}" && -n "${VPC_ID:-}" ]]; then
  "${AWS[@]}" ec2 detach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID" >/dev/null 2>&1 || true
  "${AWS[@]}" ec2 delete-internet-gateway --internet-gateway-id "$IGW_ID" >/dev/null 2>&1 || true
  log "deleted internet gateway"
fi

# Subnets / route tables / security groups
if [[ -n "${VPC_ID:-}" ]]; then
  for subnet in "${PRIVATE_SUBNET_1:-}" "${PRIVATE_SUBNET_2:-}" "${PUBLIC_SUBNET_1:-}" "${PUBLIC_SUBNET_2:-}"; do
    [[ -n "$subnet" ]] && "${AWS[@]}" ec2 delete-subnet --subnet-id "$subnet" >/dev/null 2>&1 || true
  done
  for rt in "${PRIVATE_ROUTE_TABLE:-}" "${PUBLIC_ROUTE_TABLE:-}"; do
    [[ -n "$rt" ]] && "${AWS[@]}" ec2 delete-route-table --route-table-id "$rt" >/dev/null 2>&1 || true
  done
  for sg in "${ALB_SG:-}" "${API_SG:-}" "${WORKER_SG:-}" "${DB_SG:-}" "${REDIS_SG:-}" "${OLLAMA_SG:-}" "${ENDPOINTS_SG:-}"; do
    [[ -n "$sg" ]] && "${AWS[@]}" ec2 delete-security-group --group-id "$sg" >/dev/null 2>&1 || true
  done
  "${AWS[@]}" ec2 delete-vpc --vpc-id "$VPC_ID" >/dev/null 2>&1 || true
  log "deleted VPC and network resources"
fi

# IAM roles (best-effort; policies must be detached first)
for role in "gha-deploy-opsflow-$ENV" "gha-deploy-${TARGET_SERVICE}-$ENV" \
            "$NAME_PREFIX-lambda-forwarder" "$NAME_PREFIX-worker-task" \
            "$NAME_PREFIX-api-task" "$NAME_PREFIX-ecs-task-execution"; do
  if "${AWS[@]}" iam get-role --role-name "$role" >/dev/null 2>&1; then
    policies="$("${AWS[@]}" iam list-attached-role-policies --role-name "$role" --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null || true)"
    for policy in $policies; do
      "${AWS[@]}" iam detach-role-policy --role-name "$role" --policy-arn "$policy" >/dev/null 2>&1 || true
    done
    inline="$("${AWS[@]}" iam list-role-policies --role-name "$role" --query 'PolicyNames[]' --output text 2>/dev/null || true)"
    for policy in $inline; do
      "${AWS[@]}" iam delete-role-policy --role-name "$role" --policy-name "$policy" >/dev/null 2>&1 || true
    done
    "${AWS[@]}" iam delete-role --role-name "$role" >/dev/null 2>&1 || true
  fi
done
log "deleted IAM roles"

# Log groups
for log_group in "/ecs/opsflow-api" "/ecs/opsflow-alert-consumer" \
                 "/ecs/opsflow-github-consumer" "/ecs/opsflow-deployment-consumer" \
                 "/ecs/opsflow-verification-worker" "/ecs/opsflow-ollama" \
                 "/ecs/$TARGET_SERVICE" "/aws/lambda/$NAME_PREFIX-cloudwatch-forwarder"; do
  "${AWS[@]}" logs delete-log-group --log-group-name "$log_group" >/dev/null 2>&1 || true
done

rm -f "$STATE_FILE" "$ENV_FILE"
log "Teardown complete."
