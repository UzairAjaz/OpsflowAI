#!/usr/bin/env bash
# Destroy only the zero-cost messaging resources.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

[[ "${CONFIRM_DESTROY:-}" == "YES" ]] || die "Re-run with CONFIRM_DESTROY=YES."

"${AWS[@]}" logs delete-subscription-filter \
  --log-group-name "$LOG_GROUP" \
  --filter-name "$LAMBDA_NAME-errors" >/dev/null 2>&1 || true

"${AWS[@]}" lambda delete-function --function-name "$LAMBDA_NAME" >/dev/null 2>&1 || true

if "${AWS[@]}" iam get-role --role-name "$LAMBDA_ROLE" >/dev/null 2>&1; then
  policies="$("${AWS[@]}" iam list-role-policies --role-name "$LAMBDA_ROLE" --query 'PolicyNames[]' --output text 2>/dev/null || true)"
  for policy in $policies; do
    "${AWS[@]}" iam delete-role-policy --role-name "$LAMBDA_ROLE" --policy-name "$policy" >/dev/null 2>&1 || true
  done
  "${AWS[@]}" iam detach-role-policy \
    --role-name "$LAMBDA_ROLE" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null 2>&1 || true
  "${AWS[@]}" iam delete-role --role-name "$LAMBDA_ROLE" >/dev/null 2>&1 || true
fi

for name in "$QUEUE_NAME" "$DLQ_NAME"; do
  url="$(queue_url "$name")"
  if [[ -n "$url" && "$url" != "None" ]]; then
    "${AWS[@]}" sqs delete-queue --queue-url "$url" >/dev/null 2>&1 || true
  fi
done

"${AWS[@]}" logs delete-log-group --log-group-name "$LOG_GROUP" >/dev/null 2>&1 || true
rm -f "$STATE_FILE"
log "zero-cost stack destroyed"
