#!/usr/bin/env bash
# Create the public ALB, optional ACM certificate, and optional Route53 alias.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

: "${PUBLIC_SUBNET_1:?Run 01-network.sh first}"
: "${PUBLIC_SUBNET_2:?Run 01-network.sh first}"
: "${ALB_SG:?Run 01-network.sh first}"

ALB_NAME="$NAME_PREFIX-alb"
TG_NAME="$NAME_PREFIX-api-tg"
CERT_ARN=""

log "ALB/ACM/Route53 provisioning"

if [[ -n "$DOMAIN_NAME" ]]; then
  CERT_ARN="$("${AWS[@]}" acm list-certificates \
    --query "CertificateSummaryList[?DomainName=='$DOMAIN_NAME'].CertificateArn | [0]" \
    --output text 2>/dev/null || true)"
  if [[ -z "$CERT_ARN" || "$CERT_ARN" == "None" ]]; then
    CERT_ARN="$("${AWS[@]}" acm request-certificate \
      --domain-name "$DOMAIN_NAME" \
      --validation-method DNS \
      --query CertificateArn --output text)"
    log "requested ACM certificate: $CERT_ARN"
  else
    log "ACM certificate exists: $CERT_ARN"
  fi

  if [[ -n "$HOSTED_ZONE_ID" ]]; then
    validation_name="$("${AWS[@]}" acm describe-certificate --certificate-arn "$CERT_ARN" \
      --query 'Certificate.DomainValidationOptions[0].ResourceRecord.Name' --output text)"
    validation_value="$("${AWS[@]}" acm describe-certificate --certificate-arn "$CERT_ARN" \
      --query 'Certificate.DomainValidationOptions[0].ResourceRecord.Value' --output text)"
    if [[ -n "$validation_name" && "$validation_name" != "None" ]]; then
      change_batch="$(jq -cn \
        --arg name "$validation_name" \
        --arg value "$validation_value" \
        '{Comment:"OpsFlow ACM validation",Changes:[{Action:"UPSERT",ResourceRecordSet:{Name:$name,Type:"CNAME",TTL:300,ResourceRecords:[{Value:$value}]}}]}')"
      tmp="$ROOT_DIR/deploy/aws/.tmp/acm-validation.json"
      printf '%s' "$change_batch" > "$tmp"
      "${AWS[@]}" route53 change-resource-record-sets \
        --hosted-zone-id "$HOSTED_ZONE_ID" \
        --change-batch "file://$tmp" >/dev/null
      log "created ACM DNS validation record: $validation_name"
    fi

    log "waiting for ACM certificate validation (up to 15 minutes)"
    for _ in $(seq 1 60); do
      status="$("${AWS[@]}" acm describe-certificate --certificate-arn "$CERT_ARN" \
        --query 'Certificate.Status' --output text)"
      [[ "$status" == "ISSUED" ]] && break
      sleep 15
    done
    status="$("${AWS[@]}" acm describe-certificate --certificate-arn "$CERT_ARN" \
      --query 'Certificate.Status' --output text)"
    if [[ "$status" != "ISSUED" ]]; then
      warn "ACM certificate is $status; ALB will be HTTP-only until validation completes."
      CERT_ARN=""
    fi
  else
    warn "DOMAIN_NAME is set but HOSTED_ZONE_ID is empty; ACM validation must be completed manually."
    "${AWS[@]}" acm describe-certificate --certificate-arn "$CERT_ARN" \
      --query 'Certificate.DomainValidationOptions[0].ResourceRecord' --output table
    CERT_ARN=""
  fi
fi

ALB_ARN="$("${AWS[@]}" elbv2 describe-load-balancers --names "$ALB_NAME" \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || true)"
if [[ -z "$ALB_ARN" || "$ALB_ARN" == "None" ]]; then
  ALB_ARN="$("${AWS[@]}" elbv2 create-load-balancer \
    --name "$ALB_NAME" \
    --subnets "$PUBLIC_SUBNET_1" "$PUBLIC_SUBNET_2" \
    --security-groups "$ALB_SG" \
    --scheme internet-facing \
    --type application \
    --ip-address-type ipv4 \
    --tags "Key=Project,Value=$PROJECT" "Key=Environment,Value=$ENV" \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text)"
  log "created ALB: $ALB_ARN"
else
  log "ALB exists: $ALB_ARN"
fi

TG_ARN="$("${AWS[@]}" elbv2 describe-target-groups --names "$TG_NAME" \
  --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || true)"
if [[ -z "$TG_ARN" || "$TG_ARN" == "None" ]]; then
  TG_ARN="$("${AWS[@]}" elbv2 create-target-group \
    --name "$TG_NAME" \
    --protocol HTTP --port 8000 \
    --vpc-id "$VPC_ID" \
    --target-type ip \
    --health-check-path /healthz \
    --health-check-interval-seconds 30 \
    --health-check-timeout-seconds 5 \
    --healthy-threshold-count 2 \
    --unhealthy-threshold-count 3 \
    --matcher HttpCode=200 \
    --query 'TargetGroups[0].TargetGroupArn' --output text)"
  log "created target group: $TG_ARN"
else
  log "target group exists: $TG_ARN"
fi

listener_ports="$("${AWS[@]}" elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" \
  --query 'Listeners[].Port' --output text 2>/dev/null || true)"

if [[ -n "$CERT_ARN" ]]; then
  if ! grep -qw 443 <<< "$listener_ports"; then
    "${AWS[@]}" elbv2 create-listener \
      --load-balancer-arn "$ALB_ARN" \
      --protocol HTTPS --port 443 \
      --certificates "CertificateArn=$CERT_ARN" \
      --default-actions "[{\"Type\":\"forward\",\"TargetGroupArn\":\"$TG_ARN\"}]" >/dev/null
    log "created HTTPS listener"
  fi
  if ! grep -qw 80 <<< "$listener_ports"; then
    "${AWS[@]}" elbv2 create-listener \
      --load-balancer-arn "$ALB_ARN" \
      --protocol HTTP --port 80 \
      --default-actions '[{"Type":"redirect","RedirectConfig":{"Protocol":"HTTPS","Port":"443","StatusCode":"HTTP_301"}}]' >/dev/null
    log "created HTTP->HTTPS redirect"
  fi
else
  if ! grep -qw 80 <<< "$listener_ports"; then
    "${AWS[@]}" elbv2 create-listener \
      --load-balancer-arn "$ALB_ARN" \
      --protocol HTTP --port 80 \
      --default-actions "[{\"Type\":\"forward\",\"TargetGroupArn\":\"$TG_ARN\"}]" >/dev/null
    log "created HTTP listener (staging only)"
  fi
fi

ALB_DNS="$("${AWS[@]}" elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" \
  --query 'LoadBalancers[0].DNSName' --output text)"
ALB_ZONE="$("${AWS[@]}" elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" \
  --query 'LoadBalancers[0].CanonicalHostedZoneId' --output text)"

if [[ -n "$DOMAIN_NAME" && -n "$HOSTED_ZONE_ID" && -n "$CERT_ARN" ]]; then
  change_batch="$(jq -cn \
    --arg name "$DOMAIN_NAME" \
    --arg dns "$ALB_DNS" \
    --arg zone "$ALB_ZONE" \
    '{Comment:"OpsFlow ALB alias",Changes:[{Action:"UPSERT",ResourceRecordSet:{Name:$name,Type:"A",AliasTarget:{HostedZoneId:$zone,DNSName:("dualstack."+$dns),EvaluateTargetHealth:false}}}]}')"
  tmp="$ROOT_DIR/deploy/aws/.tmp/alb-alias.json"
  printf '%s' "$change_batch" > "$tmp"
  "${AWS[@]}" route53 change-resource-record-sets \
    --hosted-zone-id "$HOSTED_ZONE_ID" \
    --change-batch "file://$tmp" >/dev/null
  API_BASE_URL="https://$DOMAIN_NAME"
  log "created Route53 alias: $DOMAIN_NAME"
else
  API_BASE_URL="http://$ALB_DNS"
  if [[ -z "$DOMAIN_NAME" ]]; then
    warn "No domain configured; using ALB DNS over HTTP for staging."
  fi
fi

save_state ALB_ARN "$ALB_ARN"
save_state ALB_DNS "$ALB_DNS"
save_state TARGET_GROUP_ARN "$TG_ARN"
save_state API_BASE_URL "$API_BASE_URL"
if [[ -n "$CERT_ARN" ]]; then
  save_state ACM_CERT_ARN "$CERT_ARN"
fi

summary
log "ALB DNS:       $ALB_DNS"
log "API base URL:  $API_BASE_URL"
log "Next: ./deploy/aws/08-eventbridge.sh"
