#!/usr/bin/env bash
# Deploy the CloudWatch Logs -> SQS forwarder Lambda and optional subscription filter.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

: "${ALERTS_QUEUE_URL:?Run 02-sqs.sh first}"
: "${LAMBDA_ROLE_ARN:?Run 03-iam.sh first}"

FUNCTION_NAME="$NAME_PREFIX-cloudwatch-forwarder"
LAMBDA_DIR="$ROOT_DIR/lambda/cloudwatch_forwarder"
ZIP_FILE="$ROOT_DIR/deploy/aws/.tmp/cloudwatch_forwarder.zip"

[[ -f "$LAMBDA_DIR/handler.py" ]] || die "Missing $LAMBDA_DIR/handler.py"

(
  cd "$LAMBDA_DIR"
  rm -f "$ZIP_FILE"
  python3 -m zipfile -c "$ZIP_FILE" handler.py
)

if "${AWS[@]}" lambda get-function --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  log "updating Lambda code: $FUNCTION_NAME"
  "${AWS[@]}" lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" >/dev/null
  "${AWS[@]}" lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --timeout 30 --memory-size 512 \
    --environment "Variables={ALERT_QUEUE_URL=$ALERTS_QUEUE_URL,DEFAULT_TENANT_ID=$TENANT,ENVIRONMENT=$ENV,SERVICE_NAME=$TARGET_SERVICE}" >/dev/null
else
  log "creating Lambda: $FUNCTION_NAME"
  "${AWS[@]}" lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --handler handler.handler \
    --role "$LAMBDA_ROLE_ARN" \
    --zip-file "fileb://$ZIP_FILE" \
    --timeout 30 --memory-size 512 \
    --architectures x86_64 \
    --environment "Variables={ALERT_QUEUE_URL=$ALERTS_QUEUE_URL,DEFAULT_TENANT_ID=$TENANT,ENVIRONMENT=$ENV,SERVICE_NAME=$TARGET_SERVICE}" >/dev/null
fi

FUNCTION_ARN="$("${AWS[@]}" lambda get-function \
  --function-name "$FUNCTION_NAME" \
  --query 'Configuration.FunctionArn' --output text)"
save_state LAMBDA_FUNCTION_ARN "$FUNCTION_ARN"

"${AWS[@]}" lambda add-permission \
  --function-name "$FUNCTION_NAME" \
  --statement-id "$NAME_PREFIX-cloudwatch-logs" \
  --action lambda:InvokeFunction \
  --principal logs.amazonaws.com \
  --source-arn "arn:aws:logs:$AWS_REGION:$ACCOUNT_ID:log-group:$TARGET_LOG_GROUP:*" >/dev/null 2>&1 || true

log_group_exists="$("${AWS[@]}" logs describe-log-groups \
  --log-group-name-prefix "$TARGET_LOG_GROUP" \
  --query "logGroups[?logGroupName=='$TARGET_LOG_GROUP'].logGroupName | [0]" \
  --output text 2>/dev/null || true)"

if [[ -n "$log_group_exists" && "$log_group_exists" != "None" ]]; then
  log "attaching subscription filter to $TARGET_LOG_GROUP"
  "${AWS[@]}" logs put-subscription-filter \
    --log-group-name "$TARGET_LOG_GROUP" \
    --filter-name "$NAME_PREFIX-errors" \
    --filter-pattern '{ ($.level = "ERROR" || $.level = "CRITICAL") }' \
    --destination-arn "$FUNCTION_ARN" >/dev/null
  save_state SUBSCRIPTION_LOG_GROUP "$TARGET_LOG_GROUP"
else
  warn "Log group $TARGET_LOG_GROUP does not exist yet."
  warn "After Phase 1 creates it, rerun this script to attach the subscription filter."
fi

summary
log "Lambda ready: $FUNCTION_ARN"
log "Next: ./deploy/aws/05-rds-redis.sh"
