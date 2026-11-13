#!/usr/bin/env bash
# Create RDS Postgres, ElastiCache Redis, and their connection secrets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

: "${PRIVATE_SUBNET_1:?Run 01-network.sh first}"
: "${PRIVATE_SUBNET_2:?Run 01-network.sh first}"
: "${DB_SG:?Run 01-network.sh first}"
: "${REDIS_SG:?Run 01-network.sh first}"

DB_SUBNET_GROUP="$NAME_PREFIX-db-subnets"
REDIS_SUBNET_GROUP="$NAME_PREFIX-redis-subnets"
DB_IDENTIFIER="$NAME_PREFIX-postgres"
REDIS_CLUSTER_ID="$NAME_PREFIX-redis"

if ! "${AWS[@]}" rds describe-db-subnet-groups --db-subnet-group-name "$DB_SUBNET_GROUP" >/dev/null 2>&1; then
  "${AWS[@]}" rds create-db-subnet-group \
    --db-subnet-group-name "$DB_SUBNET_GROUP" \
    --db-subnet-group-description "OpsFlow $ENV private DB subnets" \
    --subnet-ids "$PRIVATE_SUBNET_1" "$PRIVATE_SUBNET_2" \
    --tags "Key=Project,Value=$PROJECT" "Key=Environment,Value=$ENV" >/dev/null
  log "created DB subnet group: $DB_SUBNET_GROUP"
else
  log "DB subnet group exists: $DB_SUBNET_GROUP"
fi

if ! "${AWS[@]}" rds describe-db-instances --db-instance-identifier "$DB_IDENTIFIER" >/dev/null 2>&1; then
  log "creating RDS instance $DB_IDENTIFIER (this can take 5-10 minutes)"
  "${AWS[@]}" rds create-db-instance \
    --db-instance-identifier "$DB_IDENTIFIER" \
    --engine postgres \
    --engine-version "$DB_ENGINE_VERSION" \
    --db-instance-class "$DB_INSTANCE_CLASS" \
    --allocated-storage "$DB_ALLOCATED_STORAGE" \
    --storage-type gp3 \
    --storage-encrypted \
    --db-name opsflow \
    --master-username opsflow \
    --manage-master-user-password \
    --no-publicly-accessible \
    --no-multi-az \
    --backup-retention-period 7 \
    --db-subnet-group-name "$DB_SUBNET_GROUP" \
    --vpc-security-group-ids "$DB_SG" \
    --no-deletion-protection \
    --tags "Key=Project,Value=$PROJECT" "Key=Environment,Value=$ENV" >/dev/null
fi

"${AWS[@]}" rds wait db-instance-available --db-instance-identifier "$DB_IDENTIFIER"
DB_ENDPOINT="$("${AWS[@]}" rds describe-db-instances \
  --db-instance-identifier "$DB_IDENTIFIER" \
  --query 'DBInstances[0].Endpoint.Address' --output text)"
DB_SECRET_ARN="$("${AWS[@]}" rds describe-db-instances \
  --db-instance-identifier "$DB_IDENTIFIER" \
  --query 'DBInstances[0].MasterUserSecret.SecretArn' --output text)"
[[ -n "$DB_ENDPOINT" && "$DB_ENDPOINT" != "None" ]] || die "RDS endpoint not available"
[[ -n "$DB_SECRET_ARN" && "$DB_SECRET_ARN" != "None" ]] || die "RDS master secret not available"

DB_PASSWORD="$("${AWS[@]}" secretsmanager get-secret-value \
  --secret-id "$DB_SECRET_ARN" --query SecretString --output text | jq -r '.password')"
DB_PASSWORD_ENCODED="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$DB_PASSWORD")"
DATABASE_URL="postgresql+psycopg://opsflow:${DB_PASSWORD_ENCODED}@${DB_ENDPOINT}:5432/opsflow"
put_secret "$PROJECT/$ENV/database-url" "$DATABASE_URL"
DB_URL_SECRET_ARN="$("${AWS[@]}" secretsmanager describe-secret \
  --secret-id "$PROJECT/$ENV/database-url" --query ARN --output text)"

save_state DB_IDENTIFIER "$DB_IDENTIFIER"
save_state DB_ENDPOINT "$DB_ENDPOINT"
save_state DB_URL_SECRET_ARN "$DB_URL_SECRET_ARN"

if ! "${AWS[@]}" elasticache describe-cache-subnet-groups --cache-subnet-group-name "$REDIS_SUBNET_GROUP" >/dev/null 2>&1; then
  "${AWS[@]}" elasticache create-cache-subnet-group \
    --cache-subnet-group-name "$REDIS_SUBNET_GROUP" \
    --cache-subnet-group-description "OpsFlow $ENV private Redis subnets" \
    --subnet-ids "$PRIVATE_SUBNET_1" "$PRIVATE_SUBNET_2" >/dev/null
  log "created cache subnet group: $REDIS_SUBNET_GROUP"
else
  log "cache subnet group exists: $REDIS_SUBNET_GROUP"
fi

REDIS_AUTH_SECRET="$PROJECT/$ENV/redis-auth-token"
if "${AWS[@]}" secretsmanager describe-secret --secret-id "$REDIS_AUTH_SECRET" >/dev/null 2>&1; then
  REDIS_AUTH_TOKEN="$(get_secret "$REDIS_AUTH_SECRET")"
else
  REDIS_AUTH_TOKEN="$(openssl rand -hex 24)"
  put_secret "$REDIS_AUTH_SECRET" "$REDIS_AUTH_TOKEN"
  log "created Redis auth token secret"
fi

if ! "${AWS[@]}" elasticache describe-cache-clusters --cache-cluster-id "$REDIS_CLUSTER_ID" >/dev/null 2>&1; then
  log "creating ElastiCache cluster $REDIS_CLUSTER_ID (this can take 5-10 minutes)"
  "${AWS[@]}" elasticache create-cache-cluster \
    --cache-cluster-id "$REDIS_CLUSTER_ID" \
    --engine redis \
    --engine-version "$REDIS_ENGINE_VERSION" \
    --cache-node-type "$REDIS_NODE_TYPE" \
    --num-cache-nodes 1 \
    --cache-subnet-group-name "$REDIS_SUBNET_GROUP" \
    --security-group-ids "$REDIS_SG" \
    --transit-encryption-enabled \
    --at-rest-encryption-enabled \
    --auth-token "$REDIS_AUTH_TOKEN" \
    --tags "Key=Project,Value=$PROJECT" "Key=Environment,Value=$ENV" >/dev/null
fi

"${AWS[@]}" elasticache wait cache-cluster-available --cache-cluster-id "$REDIS_CLUSTER_ID"
REDIS_ENDPOINT="$("${AWS[@]}" elasticache describe-cache-clusters \
  --cache-cluster-id "$REDIS_CLUSTER_ID" \
  --show-cache-node-info \
  --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' --output text)"
[[ -n "$REDIS_ENDPOINT" && "$REDIS_ENDPOINT" != "None" ]] || die "Redis endpoint not available"

REDIS_URL="rediss://:${REDIS_AUTH_TOKEN}@${REDIS_ENDPOINT}:6379/0"
put_secret "$PROJECT/$ENV/redis-url" "$REDIS_URL"
REDIS_URL_SECRET_ARN="$("${AWS[@]}" secretsmanager describe-secret \
  --secret-id "$PROJECT/$ENV/redis-url" --query ARN --output text)"

save_state REDIS_CLUSTER_ID "$REDIS_CLUSTER_ID"
save_state REDIS_ENDPOINT "$REDIS_ENDPOINT"
save_state REDIS_URL_SECRET_ARN "$REDIS_URL_SECRET_ARN"

summary
log "RDS endpoint:   $DB_ENDPOINT"
log "Redis endpoint: $REDIS_ENDPOINT"
log "Secrets created: $PROJECT/$ENV/database-url, $PROJECT/$ENV/redis-url"
log "After migration, enable pgvector: CREATE EXTENSION IF NOT EXISTS vector;"
log "Next: ./deploy/aws/06-ecr-ecs.sh"
