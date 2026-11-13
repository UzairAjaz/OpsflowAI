#!/usr/bin/env bash
# Shared helpers for OpsFlow AWS provisioning.
# Run from a bash shell (AWS CloudShell, WSL, or Git Bash).
set -euo pipefail

COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$COMMON_DIR/../../.." && pwd)"
CONFIG_FILE="${CONFIG_FILE:-$ROOT_DIR/deploy/aws/config.env}"

if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

AWS_PROFILE="${AWS_PROFILE:-opsflow-dev}"
AWS_REGION="${AWS_REGION:-ap-southeast-2}"
PROJECT="${PROJECT:-opsflow}"
ENV="${ENV:-staging}"
NAME_PREFIX="${NAME_PREFIX:-${PROJECT}-${ENV}}"
TENANT="${TENANT:-mediconnect}"
TARGET_REPO="${TARGET_REPO:-UzairAjaz/mediconnnect}"
TARGET_SERVICE="${TARGET_SERVICE:-mediconnect-backend}"
MANAGER_EMAIL="${MANAGER_EMAIL:-uzairejaz987@gmail.com}"
TARGET_LOG_GROUP="${TARGET_LOG_GROUP:-/ecs/${TARGET_SERVICE}}"
OPSFLOW_REPO="${OPSFLOW_REPO:-UzairAjaz/OpsflowAI}"

# Network defaults. Adjust before running if 10.20.0.0/16 overlaps.
VPC_CIDR="${VPC_CIDR:-10.20.0.0/16}"
PUBLIC_SUBNET_1_CIDR="${PUBLIC_SUBNET_1_CIDR:-10.20.0.0/20}"
PUBLIC_SUBNET_2_CIDR="${PUBLIC_SUBNET_2_CIDR:-10.20.16.0/20}"
PRIVATE_SUBNET_1_CIDR="${PRIVATE_SUBNET_1_CIDR:-10.20.32.0/20}"
PRIVATE_SUBNET_2_CIDR="${PRIVATE_SUBNET_2_CIDR:-10.20.48.0/20}"

# Domain is optional. If empty, ALB is HTTP-only and GitHub webhooks use the ALB DNS.
DOMAIN_NAME="${DOMAIN_NAME:-}"
HOSTED_ZONE_ID="${HOSTED_ZONE_ID:-}"

# Staging sizing defaults. Increase for production.
DB_INSTANCE_CLASS="${DB_INSTANCE_CLASS:-db.t4g.micro}"
DB_ALLOCATED_STORAGE="${DB_ALLOCATED_STORAGE:-20}"
DB_ENGINE_VERSION="${DB_ENGINE_VERSION:-16.4}"
REDIS_NODE_TYPE="${REDIS_NODE_TYPE:-cache.t4g.micro}"
REDIS_ENGINE_VERSION="${REDIS_ENGINE_VERSION:-7.1}"

OUTPUT_DIR="${OUTPUT_DIR:-$ROOT_DIR/deploy/aws/outputs}"
STATE_FILE="${STATE_FILE:-$OUTPUT_DIR/${ENV}.state}"
ENV_FILE="${ENV_FILE:-$OUTPUT_DIR/${ENV}.env}"
mkdir -p "$OUTPUT_DIR" "$ROOT_DIR/deploy/aws/.tmp"

if [[ -f "$STATE_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "$STATE_FILE"
  set +a
fi

AWS_BIN="${AWS_BIN:-aws}"
AWS_ARGS=(--region "$AWS_REGION")
if [[ -n "${AWS_PROFILE:-}" ]]; then
  AWS_ARGS+=(--profile "$AWS_PROFILE")
fi
AWS=("$AWS_BIN" "${AWS_ARGS[@]}")
ACCOUNT_ID="${ACCOUNT_ID:-$("${AWS[@]}" sts get-caller-identity --query Account --output text)}"

log()  { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
warn() { printf '\n[WARN] %s\n' "$*" >&2; }
die()  { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command '$1' is not installed."
}

save_state() {
  local key="$1" value="$2"
  local tmp="${STATE_FILE}.tmp"
  touch "$STATE_FILE"
  grep -v "^${key}=" "$STATE_FILE" > "$tmp" 2>/dev/null || true
  printf '%s=%q\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$STATE_FILE"
}

tag_json() {
  local name="$1"
  jq -cn \
    --arg name "$name" \
    --arg project "$PROJECT" \
    --arg env "$ENV" \
    '[{Key:"Name",Value:$name},{Key:"Project",Value:$project},{Key:"Environment",Value:$env},{Key:"ManagedBy",Value:"opsflow"}]'
}

put_secret() {
  local name="$1" value="$2"
  local tmp
  tmp="$(mktemp)"
  chmod 600 "$tmp"
  printf '%s' "$value" > "$tmp"
  if "${AWS[@]}" secretsmanager describe-secret --secret-id "$name" >/dev/null 2>&1; then
    "${AWS[@]}" secretsmanager put-secret-value --secret-id "$name" --secret-string "file://$tmp" >/dev/null
  else
    "${AWS[@]}" secretsmanager create-secret --name "$name" --secret-string "file://$tmp" >/dev/null
  fi
  rm -f "$tmp"
}

get_secret() {
  local name="$1"
  "${AWS[@]}" secretsmanager get-secret-value --secret-id "$name" --query SecretString --output text
}

queue_url() {
  "${AWS[@]}" sqs get-queue-url --queue-name "$1" --query QueueUrl --output text 2>/dev/null || true
}

queue_arn() {
  local url="$1"
  "${AWS[@]}" sqs get-queue-attributes --queue-url "$url" --attribute-names QueueArn --query 'Attributes.QueueArn' --output text
}

ensure_queue() {
  local name="$1" dlq_name="$2"
  local dlq_url dlq_arn attrs url arn

  dlq_url="$(queue_url "$dlq_name")"
  if [[ -z "$dlq_url" || "$dlq_url" == "None" ]]; then
    dlq_url="$("${AWS[@]}" sqs create-queue \
      --queue-name "$dlq_name" \
      --attributes '{"MessageRetentionPeriod":"1209600","SqsManagedSseEnabled":"true"}' \
      --query QueueUrl --output text)"
    log "created DLQ: $dlq_name"
  else
    log "DLQ exists: $dlq_name"
  fi
  dlq_arn="$(queue_arn "$dlq_url")"

  attrs="$(jq -cn --arg arn "$dlq_arn" \
    '{VisibilityTimeout:"900",MessageRetentionPeriod:"345600",ReceiveMessageWaitTimeSeconds:"20",SqsManagedSseEnabled:"true",RedrivePolicy:({deadLetterTargetArn:$arn,maxReceiveCount:"5"}|tojson)}')"

  url="$(queue_url "$name")"
  if [[ -z "$url" || "$url" == "None" ]]; then
    url="$("${AWS[@]}" sqs create-queue \
      --queue-name "$name" \
      --attributes "$attrs" \
      --query QueueUrl --output text)"
    log "created queue: $name"
  else
    "${AWS[@]}" sqs set-queue-attributes --queue-url "$url" --attributes "$attrs" >/dev/null
    log "queue exists: $name"
  fi
  arn="$(queue_arn "$url")"
  save_state "${name//-/_}_URL" "$url"
  save_state "${name//-/_}_ARN" "$arn"
  printf '%s\n' "$url"
}

ensure_sg() {
  local name="$1" description="$2" vpc_id="$3"
  local sg_id
  sg_id="$("${AWS[@]}" ec2 describe-security-groups \
    --filters "Name=group-name,Values=$name" "Name=vpc-id,Values=$vpc_id" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"
  if [[ -z "$sg_id" || "$sg_id" == "None" ]]; then
    sg_id="$("${AWS[@]}" ec2 create-security-group \
      --group-name "$name" --description "$description" --vpc-id "$vpc_id" \
      --query GroupId --output text)"
    "${AWS[@]}" ec2 create-tags --resources "$sg_id" --tags "$(tag_json "$name")"
    log "created security group: $name ($sg_id)"
  else
    log "security group exists: $name ($sg_id)"
  fi
  printf '%s\n' "$sg_id"
}

authorize_sg_ingress() {
  local sg_id="$1" protocol="$2" port="$3" source="$4"
  "${AWS[@]}" ec2 authorize-security-group-ingress \
    --group-id "$sg_id" --protocol "$protocol" --port "$port" --cidr "$source" >/dev/null 2>&1 || true
}

authorize_sg_ingress_sg() {
  local sg_id="$1" protocol="$2" port="$3" source_sg="$4"
  "${AWS[@]}" ec2 authorize-security-group-ingress \
    --group-id "$sg_id" --protocol "$protocol" --port "$port" --source-group "$source_sg" >/dev/null 2>&1 || true
}

summary() {
  log "state file: $STATE_FILE"
  log "outputs:    $ENV_FILE"
}
