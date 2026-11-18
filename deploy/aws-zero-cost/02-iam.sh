#!/usr/bin/env bash
# Create the minimal Lambda execution role for the forwarder.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

: "${ALERT_QUEUE_ARN:?Run 01-sqs.sh first}"

TMP_DIR="$ROOT_DIR/deploy/aws-zero-cost/.tmp"
mkdir -p "$TMP_DIR"
TRUST_FILE="$TMP_DIR/lambda-trust.json"

cat > "$TRUST_FILE" <<'JSON'
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

if "${AWS[@]}" iam get-role --role-name "$LAMBDA_ROLE" >/dev/null 2>&1; then
  "${AWS[@]}" iam update-assume-role-policy \
    --role-name "$LAMBDA_ROLE" \
    --policy-document "$(file_url "$TRUST_FILE")" >/dev/null
  log "role exists: $LAMBDA_ROLE"
else
  "${AWS[@]}" iam create-role \
    --role-name "$LAMBDA_ROLE" \
    --assume-role-policy-document "$(file_url "$TRUST_FILE")" >/dev/null
  log "created role: $LAMBDA_ROLE"
fi

"${AWS[@]}" iam attach-role-policy \
  --role-name "$LAMBDA_ROLE" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null

policy="$(jq -cn --arg queue "$ALERT_QUEUE_ARN" '{
  Version: "2012-10-17",
  Statement: [{
    Effect: "Allow",
    Action: ["sqs:SendMessage"],
    Resource: [$queue]
  }]
}')"
"${AWS[@]}" iam put-role-policy \
  --role-name "$LAMBDA_ROLE" \
  --policy-name "$LAMBDA_ROLE-sqs" \
  --policy-document "$policy" >/dev/null

ROLE_ARN="$("${AWS[@]}" iam get-role --role-name "$LAMBDA_ROLE" --query 'Role.Arn' --output text)"
save_state LAMBDA_ROLE_ARN "$ROLE_ARN"

log "role arn: $ROLE_ARN"
log "waiting 8s for IAM propagation"
sleep 8
log "next: ./03-lambda.sh"
