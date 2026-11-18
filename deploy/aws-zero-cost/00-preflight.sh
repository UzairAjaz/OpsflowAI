#!/usr/bin/env bash
# Read-only preflight for the zero-cost messaging stack.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

require_cmd aws
require_cmd jq
require_cmd python3

log "Zero-cost preflight: account=$ACCOUNT_ID region=$AWS_REGION profile=$AWS_PROFILE"

if [[ "$ACCOUNT_ID" != "$EXPECTED_ACCOUNT_ID" ]]; then
  die "Expected account $EXPECTED_ACCOUNT_ID but got $ACCOUNT_ID"
fi

identity="$("${AWS[@]}" sts get-caller-identity --output json)"
printf '%s\n' "$identity" | jq .

actions=(
  logs:CreateLogGroup logs:PutRetentionPolicy logs:PutSubscriptionFilter
  logs:CreateLogStream logs:PutLogEvents
  sqs:CreateQueue sqs:GetQueueAttributes sqs:SetQueueAttributes
  sqs:ReceiveMessage sqs:DeleteMessage sqs:ChangeMessageVisibility
  lambda:CreateFunction lambda:GetFunction lambda:UpdateFunctionCode lambda:AddPermission
  iam:CreateRole iam:GetRole iam:AttachRolePolicy iam:PutRolePolicy iam:PassRole
)

simulation="$("${AWS[@]}" iam simulate-principal-policy \
  --policy-source-arn "$(printf '%s' "$identity" | jq -r '.Arn')" \
  --action-names "${actions[@]}" \
  --query 'EvaluationResults[].{Action:EvalActionName,Decision:EvalDecision}' \
  --output json 2>/dev/null || true)"

if [[ -n "$simulation" ]]; then
  denied="$(printf '%s' "$simulation" | jq -r '.[] | select(.Decision != "allowed") | "\(.Decision): \(.Action)"')"
  if [[ -n "$denied" ]]; then
    warn "Missing permissions:"
    printf '%s\n' "$denied" | sed 's/^/  - /'
    die "Fix IAM permissions before provisioning."
  fi
  log "create-permission simulation passed"
else
  warn "Could not simulate permissions; verify IAM manually."
fi

log "Existing resources:"
"${AWS[@]}" logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" \
  --query 'logGroups[].logGroupName' --output text 2>/dev/null || true
"${AWS[@]}" sqs list-queues --queue-name-prefix "$QUEUE_NAME" \
  --query 'QueueUrls[]' --output text 2>/dev/null || true
"${AWS[@]}" lambda list-functions \
  --query "Functions[?FunctionName=='$LAMBDA_NAME'].FunctionName" --output text 2>/dev/null || true

log "Preflight complete. Next: ./01-sqs.sh"
