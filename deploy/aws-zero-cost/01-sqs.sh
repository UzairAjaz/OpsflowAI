#!/usr/bin/env bash
# Create the alerts SQS queue and DLQ. No other AWS resources.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

require_cmd jq

dlq_url="$(queue_url "$DLQ_NAME")"
if [[ -z "$dlq_url" || "$dlq_url" == "None" ]]; then
  dlq_url="$("${AWS[@]}" sqs create-queue \
    --queue-name "$DLQ_NAME" \
    --attributes '{"MessageRetentionPeriod":"1209600","SqsManagedSseEnabled":"true"}' \
    --query QueueUrl --output text)"
  log "created DLQ: $DLQ_NAME"
else
  log "DLQ exists: $DLQ_NAME"
fi
dlq_arn="$(queue_arn "$dlq_url")"

attrs="$(jq -cn --arg arn "$dlq_arn" \
  '{VisibilityTimeout:"900",MessageRetentionPeriod:"345600",ReceiveMessageWaitTimeSeconds:"20",SqsManagedSseEnabled:"true",RedrivePolicy:({deadLetterTargetArn:$arn,maxReceiveCount:"5"}|tojson)}')"

queue_url="$(queue_url "$QUEUE_NAME")"
if [[ -z "$queue_url" || "$queue_url" == "None" ]]; then
  queue_url="$("${AWS[@]}" sqs create-queue \
    --queue-name "$QUEUE_NAME" \
    --attributes "$attrs" \
    --query QueueUrl --output text)"
  log "created queue: $QUEUE_NAME"
else
  "${AWS[@]}" sqs set-queue-attributes --queue-url "$queue_url" --attributes "$attrs" >/dev/null
  log "queue exists: $QUEUE_NAME"
fi
queue_arn_value="$(queue_arn "$queue_url")"

save_state ALERT_QUEUE_URL "$queue_url"
save_state ALERT_QUEUE_ARN "$queue_arn_value"
save_state DLQ_URL "$dlq_url"
save_state DLQ_ARN "$dlq_arn"

log "queue: $queue_url"
log "dlq:   $dlq_url"
log "next:  ./02-iam.sh"
