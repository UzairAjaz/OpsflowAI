#!/usr/bin/env bash
# Create VPC, public/private subnets, NAT, route tables, security groups,
# and VPC endpoints for the OpsFlow staging environment.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

log "Network provisioning in $AWS_REGION ($ACCOUNT_ID)"

AZS=($("${AWS[@]}" ec2 describe-availability-zones \
  --filters Name=state,Values=available \
  --query 'AvailabilityZones[0:2].ZoneName' --output text))
AZ1="${AZS[0]:-ap-southeast-2a}"
AZ2="${AZS[1]:-ap-southeast-2b}"
log "availability zones: $AZ1, $AZ2"

vpc_id="$("${AWS[@]}" ec2 describe-vpcs \
  --filters "Name=tag:Name,Values=$NAME_PREFIX-vpc" \
  --query 'Vpcs[0].VpcId' --output text 2>/dev/null || true)"

if [[ -z "$vpc_id" || "$vpc_id" == "None" ]]; then
  vpc_id="$("${AWS[@]}" ec2 create-vpc \
    --cidr-block "$VPC_CIDR" \
    --tag-specifications "ResourceType=vpc,Tags=$(tag_json "$NAME_PREFIX-vpc")" \
    --query 'Vpc.VpcId' --output text)"
  "${AWS[@]}" ec2 modify-vpc-attribute --vpc-id "$vpc_id" --enable-dns-hostnames
  "${AWS[@]}" ec2 modify-vpc-attribute --vpc-id "$vpc_id" --enable-dns-support
  log "created VPC: $vpc_id"
else
  log "VPC exists: $vpc_id"
fi
save_state VPC_ID "$vpc_id"

ensure_subnet() {
  local name="$1" cidr="$2" az="$3" public="$4"
  local id
  id="$("${AWS[@]}" ec2 describe-subnets \
    --filters "Name=tag:Name,Values=$name" "Name=vpc-id,Values=$vpc_id" \
    --query 'Subnets[0].SubnetId' --output text 2>/dev/null || true)"
  if [[ -z "$id" || "$id" == "None" ]]; then
    local args=(
      ec2 create-subnet
      --vpc-id "$vpc_id"
      --cidr-block "$cidr"
      --availability-zone "$az"
      --tag-specifications "ResourceType=subnet,Tags=$(tag_json "$name")"
      --query SubnetId --output text
    )
    if [[ "$public" == "true" ]]; then
      args+=(--map-public-ip-on-launch)
    fi
    id="$("${AWS[@]}" "${args[@]}")"
    log "created subnet: $name ($id)"
  else
    log "subnet exists: $name ($id)"
  fi
  printf '%s\n' "$id"
}

PUBLIC_SUBNET_1="$(ensure_subnet "$NAME_PREFIX-public-1" "$PUBLIC_SUBNET_1_CIDR" "$AZ1" true)"
PUBLIC_SUBNET_2="$(ensure_subnet "$NAME_PREFIX-public-2" "$PUBLIC_SUBNET_2_CIDR" "$AZ2" true)"
PRIVATE_SUBNET_1="$(ensure_subnet "$NAME_PREFIX-private-1" "$PRIVATE_SUBNET_1_CIDR" "$AZ1" false)"
PRIVATE_SUBNET_2="$(ensure_subnet "$NAME_PREFIX-private-2" "$PRIVATE_SUBNET_2_CIDR" "$AZ2" false)"

save_state PUBLIC_SUBNET_1 "$PUBLIC_SUBNET_1"
save_state PUBLIC_SUBNET_2 "$PUBLIC_SUBNET_2"
save_state PRIVATE_SUBNET_1 "$PRIVATE_SUBNET_1"
save_state PRIVATE_SUBNET_2 "$PRIVATE_SUBNET_2"

igw_id="$("${AWS[@]}" ec2 describe-internet-gateways \
  --filters "Name=tag:Name,Values=$NAME_PREFIX-igw" "Name=attachment.vpc-id,Values=$vpc_id" \
  --query 'InternetGateways[0].InternetGatewayId' --output text 2>/dev/null || true)"
if [[ -z "$igw_id" || "$igw_id" == "None" ]]; then
  igw_id="$("${AWS[@]}" ec2 create-internet-gateway \
    --tag-specifications "ResourceType=internet-gateway,Tags=$(tag_json "$NAME_PREFIX-igw")" \
    --query 'InternetGateway.InternetGatewayId' --output text)"
  "${AWS[@]}" ec2 attach-internet-gateway --vpc-id "$vpc_id" --internet-gateway-id "$igw_id"
  log "created internet gateway: $igw_id"
else
  log "internet gateway exists: $igw_id"
fi
save_state IGW_ID "$igw_id"

ensure_route_table() {
  local name="$1" vpc="$2"
  local rt
  rt="$("${AWS[@]}" ec2 describe-route-tables \
    --filters "Name=tag:Name,Values=$name" "Name=vpc-id,Values=$vpc" \
    --query 'RouteTables[0].RouteTableId' --output text 2>/dev/null || true)"
  if [[ -z "$rt" || "$rt" == "None" ]]; then
    rt="$("${AWS[@]}" ec2 create-route-table \
      --vpc-id "$vpc" \
      --tag-specifications "ResourceType=route-table,Tags=$(tag_json "$name")" \
      --query 'RouteTable.RouteTableId' --output text)"
    log "created route table: $name ($rt)"
  else
    log "route table exists: $name ($rt)"
  fi
  printf '%s\n' "$rt"
}

PUBLIC_RT="$(ensure_route_table "$NAME_PREFIX-public-rt" "$vpc_id")"
PRIVATE_RT="$(ensure_route_table "$NAME_PREFIX-private-rt" "$vpc_id")"
save_state PUBLIC_ROUTE_TABLE "$PUBLIC_RT"
save_state PRIVATE_ROUTE_TABLE "$PRIVATE_RT"

"${AWS[@]}" ec2 create-route --route-table-id "$PUBLIC_RT" --destination-cidr-block 0.0.0.0/0 --gateway-id "$igw_id" >/dev/null 2>&1 || true
for subnet in "$PUBLIC_SUBNET_1" "$PUBLIC_SUBNET_2"; do
  "${AWS[@]}" ec2 associate-route-table --route-table-id "$PUBLIC_RT" --subnet-id "$subnet" >/dev/null 2>&1 || true
done

nat_eip="$("${AWS[@]}" ec2 describe-addresses \
  --filters "Name=tag:Name,Values=$NAME_PREFIX-nat-eip" \
  --query 'Addresses[0].AllocationId' --output text 2>/dev/null || true)"
if [[ -z "$nat_eip" || "$nat_eip" == "None" ]]; then
  nat_eip="$("${AWS[@]}" ec2 allocate-address \
    --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=$(tag_json "$NAME_PREFIX-nat-eip")" \
    --query AllocationId --output text)"
  log "allocated EIP: $nat_eip"
else
  log "EIP exists: $nat_eip"
fi
save_state NAT_EIP_ALLOCATION_ID "$nat_eip"

nat_id="$("${AWS[@]}" ec2 describe-nat-gateways \
  --filter "Name=tag:Name,Values=$NAME_PREFIX-nat" "Name=vpc-id,Values=$vpc_id" \
  --query 'NatGateways[0].NatGatewayId' --output text 2>/dev/null || true)"
if [[ -z "$nat_id" || "$nat_id" == "None" ]]; then
  nat_id="$("${AWS[@]}" ec2 create-nat-gateway \
    --subnet-id "$PUBLIC_SUBNET_1" \
    --allocation-id "$nat_eip" \
    --tag-specifications "ResourceType=natgateway,Tags=$(tag_json "$NAME_PREFIX-nat")" \
    --query 'NatGateway.NatGatewayId' --output text)"
  log "waiting for NAT gateway $nat_id"
  "${AWS[@]}" ec2 wait nat-gateway-available --nat-gateway-ids "$nat_id"
  log "NAT gateway available: $nat_id"
else
  log "NAT gateway exists: $nat_id"
fi
save_state NAT_GATEWAY_ID "$nat_id"

"${AWS[@]}" ec2 create-route --route-table-id "$PRIVATE_RT" --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$nat_id" >/dev/null 2>&1 || true
for subnet in "$PRIVATE_SUBNET_1" "$PRIVATE_SUBNET_2"; do
  "${AWS[@]}" ec2 associate-route-table --route-table-id "$PRIVATE_RT" --subnet-id "$subnet" >/dev/null 2>&1 || true
done

ALB_SG="$(ensure_sg "$NAME_PREFIX-alb-sg" "OpsFlow ALB" "$vpc_id")"
API_SG="$(ensure_sg "$NAME_PREFIX-api-sg" "OpsFlow API" "$vpc_id")"
WORKER_SG="$(ensure_sg "$NAME_PREFIX-worker-sg" "OpsFlow workers" "$vpc_id")"
DB_SG="$(ensure_sg "$NAME_PREFIX-db-sg" "OpsFlow RDS" "$vpc_id")"
REDIS_SG="$(ensure_sg "$NAME_PREFIX-redis-sg" "OpsFlow Redis" "$vpc_id")"
OLLAMA_SG="$(ensure_sg "$NAME_PREFIX-ollama-sg" "OpsFlow Ollama" "$vpc_id")"
ENDPOINTS_SG="$(ensure_sg "$NAME_PREFIX-endpoints-sg" "OpsFlow VPC endpoints" "$vpc_id")"

authorize_sg_ingress "$ALB_SG" tcp 80 0.0.0.0/0
authorize_sg_ingress "$ALB_SG" tcp 443 0.0.0.0/0
authorize_sg_ingress_sg "$API_SG" tcp 8000 "$ALB_SG"
authorize_sg_ingress_sg "$DB_SG" tcp 5432 "$API_SG"
authorize_sg_ingress_sg "$DB_SG" tcp 5432 "$WORKER_SG"
authorize_sg_ingress_sg "$REDIS_SG" tcp 6379 "$API_SG"
authorize_sg_ingress_sg "$REDIS_SG" tcp 6379 "$WORKER_SG"
authorize_sg_ingress_sg "$OLLAMA_SG" tcp 11434 "$WORKER_SG"
authorize_sg_ingress "$ENDPOINTS_SG" tcp 443 "$VPC_CIDR"

save_state ALB_SG "$ALB_SG"
save_state API_SG "$API_SG"
save_state WORKER_SG "$WORKER_SG"
save_state DB_SG "$DB_SG"
save_state REDIS_SG "$REDIS_SG"
save_state OLLAMA_SG "$OLLAMA_SG"
save_state ENDPOINTS_SG "$ENDPOINTS_SG"

ensure_interface_endpoint() {
  local name="$1" service="$2"
  local id
  id="$("${AWS[@]}" ec2 describe-vpc-endpoints \
    --filters "Name=vpc-id,Values=$vpc_id" "Name=service-name,Values=$service" "Name=vpc-endpoint-type,Values=Interface" \
    --query 'VpcEndpoints[0].VpcEndpointId' --output text 2>/dev/null || true)"
  if [[ -z "$id" || "$id" == "None" ]]; then
    id="$("${AWS[@]}" ec2 create-vpc-endpoint \
      --vpc-id "$vpc_id" \
      --vpc-endpoint-type Interface \
      --service-name "$service" \
      --subnet-ids "$PRIVATE_SUBNET_1" "$PRIVATE_SUBNET_2" \
      --security-group-ids "$ENDPOINTS_SG" \
      --private-dns-enabled \
      --tag-specifications "ResourceType=vpc-endpoint,Tags=$(tag_json "$name")" \
      --query 'VpcEndpoint.VpcEndpointId' --output text)"
    log "created endpoint: $name ($id)"
  else
    log "endpoint exists: $name ($id)"
  fi
}

ensure_interface_endpoint "$NAME_PREFIX-endpoint-sqs" "com.amazonaws.$AWS_REGION.sqs"
ensure_interface_endpoint "$NAME_PREFIX-endpoint-secrets" "com.amazonaws.$AWS_REGION.secretsmanager"
ensure_interface_endpoint "$NAME_PREFIX-endpoint-logs" "com.amazonaws.$AWS_REGION.logs"
ensure_interface_endpoint "$NAME_PREFIX-endpoint-ecr-api" "com.amazonaws.$AWS_REGION.ecr.api"
ensure_interface_endpoint "$NAME_PREFIX-endpoint-ecr-dkr" "com.amazonaws.$AWS_REGION.ecr.dkr"
ensure_interface_endpoint "$NAME_PREFIX-endpoint-kms" "com.amazonaws.$AWS_REGION.kms"

s3_endpoint="$("${AWS[@]}" ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=$vpc_id" "Name=service-name,Values=com.amazonaws.$AWS_REGION.s3" "Name=vpc-endpoint-type,Values=Gateway" \
  --query 'VpcEndpoints[0].VpcEndpointId' --output text 2>/dev/null || true)"
if [[ -z "$s3_endpoint" || "$s3_endpoint" == "None" ]]; then
  "${AWS[@]}" ec2 create-vpc-endpoint \
    --vpc-id "$vpc_id" \
    --vpc-endpoint-type Gateway \
    --service-name "com.amazonaws.$AWS_REGION.s3" \
    --route-table-ids "$PRIVATE_RT" \
    --tag-specifications "ResourceType=vpc-endpoint,Tags=$(tag_json "$NAME_PREFIX-endpoint-s3")" >/dev/null
  log "created S3 gateway endpoint"
else
  log "S3 gateway endpoint exists: $s3_endpoint"
fi

summary
log "Network provisioning complete."
log "Next: ./deploy/aws/02-sqs.sh"
