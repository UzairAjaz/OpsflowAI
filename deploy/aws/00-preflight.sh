#!/usr/bin/env bash
# Phase 0 preflight: verify tools, AWS identity, permissions, and config.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

log "OpsFlow AWS preflight"
log "profile=${AWS_PROFILE:-<default>} region=$AWS_REGION account=$ACCOUNT_ID"

require_cmd aws
require_cmd jq
require_cmd openssl
require_cmd python3
require_cmd git

if [[ ! -f "$CONFIG_FILE" ]]; then
  warn "config file not found: $CONFIG_FILE"
  warn "Copy deploy/aws/config.env.example to deploy/aws/config.env and edit it."
fi

if [[ -n "${EXPECTED_ACCOUNT_ID:-}" && "$ACCOUNT_ID" != "$EXPECTED_ACCOUNT_ID" ]]; then
  die "Expected AWS account $EXPECTED_ACCOUNT_ID but got $ACCOUNT_ID"
fi

if [[ -n "${EXPECTED_REGION:-}" && "$AWS_REGION" != "$EXPECTED_REGION" ]]; then
  die "Expected region $EXPECTED_REGION but got $AWS_REGION"
fi

identity="$("${AWS[@]}" sts get-caller-identity --output json)"
log "AWS identity:"
printf '%s\n' "$identity" | jq .

checks=(
  "ec2 describe-vpcs"
  "ec2 describe-subnets"
  "ec2 describe-security-groups"
  "ec2 describe-vpc-endpoints"
  "ec2 describe-nat-gateways"
  "sqs list-queues"
  "iam list-roles"
  "lambda list-functions"
  "ecs list-clusters"
  "rds describe-db-instances"
  "elasticache describe-cache-clusters"
  "elbv2 describe-load-balancers"
  "acm list-certificates"
  "route53 list-hosted-zones"
  "secretsmanager list-secrets"
  "events list-rules"
  "logs describe-log-groups"
)

failed=0
for check in "${checks[@]}"; do
  # shellcheck disable=SC2086
  if "${AWS[@]}" $check >/dev/null 2>&1; then
    printf '  [ok]   %s\n' "$check"
  else
    printf '  [fail] %s\n' "$check"
    failed=$((failed + 1))
  fi
done

if (( failed > 0 )); then
  warn "$failed permission check(s) failed."
  warn "Confirm the opsflow-dev role has permissions for VPC, IAM, SQS, Lambda, ECS, RDS, ElastiCache, ELB, ACM, Route53, Secrets Manager, EventBridge, and CloudWatch Logs."
fi

# Verify the principal can create the resources, not only list them.
principal_arn="$(printf '%s' "$identity" | jq -r '.Arn')"
if [[ "$principal_arn" == *":assumed-role/"* ]]; then
  principal_arn="$(printf '%s' "$principal_arn" | sed -E 's#:assumed-role/([^/]+)/.*#:role/\1#')"
fi

actions=(
  ec2:CreateVpc ec2:CreateSubnet ec2:CreateNatGateway ec2:AllocateAddress
  iam:CreateRole iam:PutRolePolicy iam:PassRole
  sqs:CreateQueue lambda:CreateFunction lambda:AddPermission
  ecs:CreateCluster rds:CreateDBInstance elasticache:CreateCacheCluster
  elasticloadbalancing:CreateLoadBalancer acm:RequestCertificate
  route53:ChangeResourceRecordSets secretsmanager:CreateSecret
  events:PutRule logs:CreateLogGroup ecr:CreateRepository
)

simulation="$("${AWS[@]}" iam simulate-principal-policy \
  --policy-source-arn "$principal_arn" \
  --action-names "${actions[@]}" \
  --query 'EvaluationResults[].{Action:EvalActionName,Decision:EvalDecision}' \
  --output json 2>/dev/null || true)"

if [[ -n "$simulation" ]]; then
  denied="$(printf '%s' "$simulation" | jq -r '.[] | select(.Decision != "allowed") | "\(.Decision): \(.Action)"')"
  if [[ -n "$denied" ]]; then
    warn "The current principal cannot create all required resources:"
    printf '%s\n' "$denied" | sed 's/^/  - /'
    die "Attach an admin/provisioning policy to $principal_arn or run the scripts with an authorized role."
  fi
  log "create-permission simulation passed"
else
  warn "Could not simulate create permissions; verify IAM manually."
fi

if [[ -z "$DOMAIN_NAME" || -z "$HOSTED_ZONE_ID" ]]; then
  warn "DOMAIN_NAME/HOSTED_ZONE_ID are empty."
  warn "ALB will be HTTP-only and GitHub App webhooks will use the ALB DNS."
  warn "For HTTPS, provide a Route53 domain and hosted zone."
fi

if [[ "$TARGET_REPO" == *"mediconnnect"* ]]; then
  warn "TARGET_REPO is '$TARGET_REPO' (three n's). Confirm this is the exact GitHub slug."
fi

printf '\n'
log "Preflight complete. Next: ./deploy/aws/01-network.sh"
