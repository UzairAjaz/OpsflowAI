#!/usr/bin/env bash
# Create or update the monthly AWS Budget with 50/80/100 percent alerts.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

BUDGET_NAME="${BUDGET_NAME:-${NAME_PREFIX}-monthly}"
BUDGET_LIMIT_USD="${BUDGET_LIMIT_USD:-100}"
BUDGET_EMAIL="${BUDGET_EMAIL:-$MANAGER_EMAIL}"

require_cmd jq
[[ -n "$BUDGET_EMAIL" ]] || die "BUDGET_EMAIL (or MANAGER_EMAIL) is required."
[[ "$BUDGET_LIMIT_USD" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "BUDGET_LIMIT_USD must be a number."

TMP_DIR="$ROOT_DIR/deploy/aws/.tmp"
mkdir -p "$TMP_DIR"
BUDGET_FILE="$TMP_DIR/budget.json"
NOTIFICATIONS_FILE="$TMP_DIR/budget-notifications.json"

jq -n \
  --arg name "$BUDGET_NAME" \
  --arg amount "$BUDGET_LIMIT_USD" \
  '{
    BudgetName: $name,
    BudgetLimit: {Amount: $amount, Unit: "USD"},
    TimeUnit: "MONTHLY",
    BudgetType: "COST"
  }' > "$BUDGET_FILE"

jq -n \
  --arg email "$BUDGET_EMAIL" \
  '[50, 80, 100] | map({
    Notification: {
      NotificationType: "ACTUAL",
      ComparisonOperator: "GREATER_THAN",
      Threshold: .,
      ThresholdType: "PERCENTAGE"
    },
    Subscribers: [{SubscriptionType: "EMAIL", Address: $email}]
  })' > "$NOTIFICATIONS_FILE"

if "${AWS[@]}" budgets describe-budget \
  --account-id "$ACCOUNT_ID" \
  --budget-name "$BUDGET_NAME" >/dev/null 2>&1; then
  log "budget exists: $BUDGET_NAME; updating amount to \$$BUDGET_LIMIT_USD"
  "${AWS[@]}" budgets update-budget \
    --account-id "$ACCOUNT_ID" \
    --new-budget "$(file_url "$BUDGET_FILE")" >/dev/null
else
  log "creating budget: $BUDGET_NAME (\$$BUDGET_LIMIT_USD/month)"
  "${AWS[@]}" budgets create-budget \
    --account-id "$ACCOUNT_ID" \
    --budget "$(file_url "$BUDGET_FILE")" \
    --notifications-with-subscribers "$(file_url "$NOTIFICATIONS_FILE")" >/dev/null
fi

save_state BUDGET_NAME "$BUDGET_NAME"
save_state BUDGET_LIMIT_USD "$BUDGET_LIMIT_USD"
save_state BUDGET_EMAIL "$BUDGET_EMAIL"

summary
log "budget: $BUDGET_NAME"
log "limit:  \$$BUDGET_LIMIT_USD/month"
log "alerts: 50%, 80%, 100% -> $BUDGET_EMAIL"
