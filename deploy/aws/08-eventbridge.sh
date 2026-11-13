#!/usr/bin/env bash
# Route ECS deployment state changes to the OpsFlow deployments SQS queue.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

: "${DEPLOYMENTS_QUEUE_URL:?Run 02-sqs.sh first}"
: "${DEPLOYMENTS_QUEUE_ARN:?Run 02-sqs.sh first}"

RULE_NAME="$NAME_PREFIX-ecs-deployments"
RULE_ARN="arn:aws:events:$AWS_REGION:$ACCOUNT_ID:rule/$RULE_NAME"

policy="$(jq -cn \
  --arg queue "$DEPLOYMENTS_QUEUE_ARN" \
  --arg rule "$RULE_ARN" \
  '{
    Version: "2012-10-17",
    Statement: [
      {
        Effect: "Allow",
        Principal: {"Service": "events.amazonaws.com"},
        Action: "sqs:SendMessage",
        Resource: $queue,
        Condition: {"ArnEquals": {"aws:SourceArn": $rule}}
      }
    ]
  }')"
attrs="$(jq -cn --arg policy "$policy" '{Policy:$policy}')"
"${AWS[@]}" sqs set-queue-attributes \
  --queue-url "$DEPLOYMENTS_QUEUE_URL" \
  --attributes "$attrs" >/dev/null

"${AWS[@]}" events put-rule \
  --name "$RULE_NAME" \
  --event-pattern '{"source":["aws.ecs"],"detail-type":["ECS Deployment State Change"]}' \
  --state ENABLED >/dev/null

"${AWS[@]}" events put-targets \
  --rule "$RULE_NAME" \
  --targets "[{\"Id\":\"opsflow-deployments\",\"Arn\":\"$DEPLOYMENTS_QUEUE_ARN\"}]" >/dev/null

save_state EVENTBRIDGE_RULE_NAME "$RULE_NAME"
save_state EVENTBRIDGE_RULE_ARN "$RULE_ARN"

summary
log "EventBridge rule: $RULE_ARN -> $DEPLOYMENTS_QUEUE_ARN"
log "Next: ./deploy/aws/09-app-secrets.sh"
