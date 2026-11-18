#!/usr/bin/env bash
# Deploy the CloudWatch -> SQS Lambda and subscription filter.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

: "${ALERT_QUEUE_URL:?Run 01-sqs.sh first}"
: "${LAMBDA_ROLE_ARN:?Run 02-iam.sh first}"

LAMBDA_DIR="$ROOT_DIR/lambda/cloudwatch_forwarder"
ZIP_FILE="$ROOT_DIR/deploy/aws-zero-cost/.tmp/cloudwatch_forwarder.zip"

require_cmd python3
[[ -f "$LAMBDA_DIR/handler.py" ]] || die "Missing $LAMBDA_DIR/handler.py"

# Create log group first so the subscription filter can be attached.
if "${AWS[@]}" logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" \
  --query "logGroups[?logGroupName=='$LOG_GROUP'].logGroupName | [0]" --output text | grep -q .; then
  log "log group exists: $LOG_GROUP"
else
  "${AWS[@]}" logs create-log-group --log-group-name "$LOG_GROUP" >/dev/null
  log "created log group: $LOG_GROUP"
fi
"${AWS[@]}" logs put-retention-policy --log-group-name "$LOG_GROUP" --retention-in-days 1 >/dev/null

ZIP_ARG="$ZIP_FILE"
if command -v cygpath >/dev/null 2>&1; then
  ZIP_ARG="$(cygpath -m "$ZIP_FILE")"
fi
(
  cd "$LAMBDA_DIR"
  rm -f "$ZIP_FILE"
  python3 -m zipfile -c "$ZIP_ARG" handler.py
)

if "${AWS[@]}" lambda get-function --function-name "$LAMBDA_NAME" >/dev/null 2>&1; then
  log "updating Lambda: $LAMBDA_NAME"
  "${AWS[@]}" lambda update-function-code \
    --function-name "$LAMBDA_NAME" \
    --zip-file "$(fileb_url "$ZIP_FILE")" >/dev/null
  "${AWS[@]}" lambda update-function-configuration \
    --function-name "$LAMBDA_NAME" \
    --runtime "$LAMBDA_RUNTIME" \
    --timeout "$LAMBDA_TIMEOUT" \
    --memory-size "$LAMBDA_MEMORY" \
    --environment "Variables={ALERT_QUEUE_URL=$ALERT_QUEUE_URL,DEFAULT_TENANT_ID=$TENANT,ENVIRONMENT=$ENVIRONMENT,SERVICE_NAME=$SERVICE}" >/dev/null
else
  log "creating Lambda: $LAMBDA_NAME"
  "${AWS[@]}" lambda create-function \
    --function-name "$LAMBDA_NAME" \
    --runtime "$LAMBDA_RUNTIME" \
    --handler handler.handler \
    --role "$LAMBDA_ROLE_ARN" \
    --zip-file "$(fileb_url "$ZIP_FILE")" \
    --timeout "$LAMBDA_TIMEOUT" \
    --memory-size "$LAMBDA_MEMORY" \
    --architectures x86_64 \
    --environment "Variables={ALERT_QUEUE_URL=$ALERT_QUEUE_URL,DEFAULT_TENANT_ID=$TENANT,ENVIRONMENT=$ENVIRONMENT,SERVICE_NAME=$SERVICE}" >/dev/null
fi

FUNCTION_ARN="$("${AWS[@]}" lambda get-function --function-name "$LAMBDA_NAME" --query 'Configuration.FunctionArn' --output text)"
save_state LAMBDA_FUNCTION_ARN "$FUNCTION_ARN"

"${AWS[@]}" lambda add-permission \
  --function-name "$LAMBDA_NAME" \
  --statement-id "$LAMBDA_NAME-cloudwatch-logs" \
  --action lambda:InvokeFunction \
  --principal logs.amazonaws.com \
  --source-arn "arn:aws:logs:$AWS_REGION:$ACCOUNT_ID:log-group:$LOG_GROUP:*" >/dev/null 2>&1 || true

"${AWS[@]}" logs put-subscription-filter \
  --log-group-name "$LOG_GROUP" \
  --filter-name "$LAMBDA_NAME-errors" \
  --filter-pattern '{ ($.level = "ERROR" || $.level = "CRITICAL") }' \
  --destination-arn "$FUNCTION_ARN" >/dev/null

save_state LOG_GROUP "$LOG_GROUP"
log "Lambda: $FUNCTION_ARN"
log "subscription filter attached to: $LOG_GROUP"
log "next: local Retriva test"
