#!/usr/bin/env bash
# Shared helpers for the zero-cost AWS messaging stack.
set -euo pipefail

# Git Bash rewrites arguments beginning with "/" into Windows paths. AWS
# resource names such as /opsflow/retriva-api must be passed through unchanged.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$COMMON_DIR/../../.." && pwd)"
CONFIG_FILE="${CONFIG_FILE:-$ROOT_DIR/deploy/aws-zero-cost/config.env}"

if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

AWS_PROFILE="${AWS_PROFILE:-default}"
AWS_REGION="${AWS_REGION:-eu-north-1}"
EXPECTED_ACCOUNT_ID="${EXPECTED_ACCOUNT_ID:-624898490323}"
PROJECT="${PROJECT:-opsflow}"
TENANT="${TENANT:-retriva}"
SERVICE="${SERVICE:-retriva-api}"
ENVIRONMENT="${ENVIRONMENT:-local}"
LOG_GROUP="${LOG_GROUP:-/opsflow/retriva-api}"
QUEUE_NAME="${QUEUE_NAME:-opsflow-alerts}"
DLQ_NAME="${DLQ_NAME:-opsflow-alerts-dlq}"
LAMBDA_NAME="${LAMBDA_NAME:-opsflow-cloudwatch-forwarder}"
LAMBDA_ROLE="${LAMBDA_ROLE:-opsflow-lambda-forwarder}"
LAMBDA_RUNTIME="${LAMBDA_RUNTIME:-python3.12}"
LAMBDA_MEMORY="${LAMBDA_MEMORY:-128}"
LAMBDA_TIMEOUT="${LAMBDA_TIMEOUT:-30}"

OUTPUT_DIR="${OUTPUT_DIR:-$ROOT_DIR/deploy/aws-zero-cost/outputs}"
STATE_FILE="${STATE_FILE:-$OUTPUT_DIR/state.env}"
mkdir -p "$OUTPUT_DIR" "$ROOT_DIR/deploy/aws-zero-cost/.tmp"

if [[ -f "$STATE_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "$STATE_FILE"
  set +a
fi

AWS=(aws --profile "$AWS_PROFILE" --region "$AWS_REGION")
ACCOUNT_ID="${ACCOUNT_ID:-$("${AWS[@]}" sts get-caller-identity --query Account --output text)}"

log() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
warn() { printf '\n[WARN] %s\n' "$*" >&2; }
die() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command '$1' is not installed."
}

save_state() {
  local key="$1" value="$2" tmp="${STATE_FILE}.tmp"
  touch "$STATE_FILE"
  grep -v "^${key}=" "$STATE_FILE" > "$tmp" 2>/dev/null || true
  printf '%s=%q\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$STATE_FILE"
}

queue_url() {
  "${AWS[@]}" sqs get-queue-url --queue-name "$1" --query QueueUrl --output text 2>/dev/null || true
}

queue_arn() {
  "${AWS[@]}" sqs get-queue-attributes --queue-url "$1" --attribute-names QueueArn --query 'Attributes.QueueArn' --output text
}

# AWS CLI on Windows needs file://C:/... while Git Bash uses /c/...
file_url() {
  local path="$1"
  [[ "$path" == /* ]] || path="$PWD/$path"
  if command -v cygpath >/dev/null 2>&1; then
    printf 'file://%s' "$(cygpath -m "$path")"
  else
    printf 'file://%s' "$path"
  fi
}

fileb_url() {
  local path="$1"
  [[ "$path" == /* ]] || path="$PWD/$path"
  if command -v cygpath >/dev/null 2>&1; then
    printf 'fileb://%s' "$(cygpath -m "$path")"
  else
    printf 'fileb://%s' "$path"
  fi
}
