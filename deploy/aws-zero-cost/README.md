# Zero-Cost AWS Messaging Stack (eu-north-1)

Only these resources are created:

```text
CloudWatch Logs  /opsflow/retriva-api   (1-day retention)
Lambda           opsflow-cloudwatch-forwarder (128 MB, 30 s)
SQS              opsflow-alerts + opsflow-alerts-dlq
IAM role         opsflow-lambda-forwarder
```

No VPC, NAT, RDS, ElastiCache, ALB, ECS, ECR, S3, Secrets Manager, EventBridge,
Route53, or ACM.

## Prerequisites

```bash
aws --version
aws sts get-caller-identity --profile default --region eu-north-1
```

The account must be `624898490323` and the region `eu-north-1`.

## Run

```bash
cd deploy/aws-zero-cost
cp config.env.example config.env
chmod +x *.sh lib/*.sh
./00-preflight.sh
./01-sqs.sh
./02-iam.sh
./03-lambda.sh
```

## Test with local Retriva

Start Retriva with the local shipper enabled:

```powershell
$env:AWS_REGION="eu-north-1"
$env:CLOUDWATCH_ENABLED="true"
$env:CLOUDWATCH_LOG_GROUP="/opsflow/retriva-api"
$env:CLOUDWATCH_LOG_STREAM="retriva-api-local"
$env:SERVICE_NAME="retriva-api"
$env:ENVIRONMENT="local"
$env:GIT_COMMIT_SHA="<retriva-sha>"
$env:ENABLE_TEST_BUG="true"
uvicorn api_server:app --host 127.0.0.1 --port 8000 --lifespan off
```

Then:

```powershell
curl.exe -i http://127.0.0.1:8000/debug/boom
```

Wait a few seconds and receive the real SQS message:

```bash
aws sqs receive-message \
  --profile default \
  --region eu-north-1 \
  --queue-url "$(aws sqs get-queue-url --profile default --region eu-north-1 --queue-name opsflow-alerts --query QueueUrl --output text)" \
  --max-number-of-messages 1 \
  --wait-time-seconds 20
```

## Cost guardrails

- CloudWatch Logs: 1-day retention, ERROR/CRITICAL only.
- Lambda: 128 MB, 30 s, no reserved concurrency.
- SQS: long polling, 4-day retention, DLQ.
- No paid monitoring, no secrets manager, no VPC.

## Teardown

```bash
CONFIRM_DESTROY=YES ./99-teardown.sh
```
