#!/usr/bin/env bash
# Store optional third-party secrets in AWS Secrets Manager.
# This script never invents credentials; it skips anything not provided.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

if [[ -n "${RESEND_API_KEY:-}" ]]; then
  payload="$(jq -cn --arg key "$RESEND_API_KEY" '{api_key:$key}')"
  put_secret "$PROJECT/$ENV/resend" "$payload"
  RESEND_SECRET_ARN="$("${AWS[@]}" secretsmanager describe-secret \
    --secret-id "$PROJECT/$ENV/resend" --query ARN --output text)"
  save_state RESEND_SECRET_ARN "$RESEND_SECRET_ARN"
  log "stored Resend secret: $PROJECT/$ENV/resend"
else
  warn "RESEND_API_KEY is not set; skipping Resend secret."
fi

if [[ -n "${GITHUB_APP_ID:-}" && -n "${GITHUB_APP_PRIVATE_KEY_FILE:-}" && -n "${GITHUB_WEBHOOK_SECRET:-}" ]]; then
  [[ -f "$GITHUB_APP_PRIVATE_KEY_FILE" ]] || die "GitHub private key file not found: $GITHUB_APP_PRIVATE_KEY_FILE"
  payload="$(jq -cn \
    --arg app_id "$GITHUB_APP_ID" \
    --rawfile private_key "$GITHUB_APP_PRIVATE_KEY_FILE" \
    --arg webhook_secret "$GITHUB_WEBHOOK_SECRET" \
    '{app_id:$app_id,private_key:$private_key,webhook_secret:$webhook_secret}')"
  put_secret "$PROJECT/$ENV/github-app" "$payload"
  GITHUB_SECRET_ARN="$("${AWS[@]}" secretsmanager describe-secret \
    --secret-id "$PROJECT/$ENV/github-app" --query ARN --output text)"
  save_state GITHUB_APP_SECRET_ARN "$GITHUB_SECRET_ARN"
  log "stored GitHub App secret: $PROJECT/$ENV/github-app"
else
  warn "GitHub App credentials not provided; skipping $PROJECT/$ENV/github-app."
  warn "Set GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_FILE, and GITHUB_WEBHOOK_SECRET, then rerun."
fi

summary
log "Next: ./deploy/aws/10-outputs.sh"
