#!/usr/bin/env bash
# Create the three SQS queues + DLQs used by OpsFlow.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

log "SQS provisioning in $AWS_REGION"

alerts_url="$(ensure_queue "$NAME_PREFIX-alerts" "$NAME_PREFIX-alerts-dlq")"
alerts_arn="$(queue_arn "$alerts_url")"
save_state ALERTS_QUEUE_URL "$alerts_url"
save_state ALERTS_QUEUE_ARN "$alerts_arn"

github_url="$(ensure_queue "$NAME_PREFIX-github-events" "$NAME_PREFIX-github-events-dlq")"
github_arn="$(queue_arn "$github_url")"
save_state GITHUB_EVENTS_QUEUE_URL "$github_url"
save_state GITHUB_EVENTS_QUEUE_ARN "$github_arn"

deployments_url="$(ensure_queue "$NAME_PREFIX-deployments" "$NAME_PREFIX-deployments-dlq")"
deployments_arn="$(queue_arn "$deployments_url")"
save_state DEPLOYMENTS_QUEUE_URL "$deployments_url"
save_state DEPLOYMENTS_QUEUE_ARN "$deployments_arn"

summary
log "SQS queues:"
log "  alerts:      $alerts_url"
log "  github:      $github_url"
log "  deployments: $deployments_url"
log "Next: ./deploy/aws/03-iam.sh"
