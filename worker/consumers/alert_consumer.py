from __future__ import annotations

import argparse
import json

from app.config import settings
from db.session import SessionLocal
from ingestion.code_alert_schema import CodeAlertMessage
from ingestion.code_alerts import ingest_code_alert
from observability.logging import get_logger
from worker.consumers.base import SqsConsumer

log = get_logger(stage="consumer.alert")


def handle_message(message: dict) -> None:
    payload = json.loads(message["Body"])
    alert = CodeAlertMessage.model_validate(payload)

    with SessionLocal() as session:
        result = ingest_code_alert(session, alert)

    if not settings.code_fix_enabled:
        log.bind(
            tenant_id=alert.tenant_id,
            service=alert.service,
            thread_id=result.thread_id,
        ).info("code fix disabled; incident stored analysis-only")
    elif not result.analysis_only:
        from app.code_fix.runner import run_code_fix

        fix_result = run_code_fix(result.incident_id)
        log.bind(
            tenant_id=alert.tenant_id,
            service=alert.service,
            thread_id=result.thread_id,
            fix_status=fix_result.get("status"),
        ).info("code fix run completed")

    log.bind(
        tenant_id=alert.tenant_id,
        service=alert.service,
        incident_id=str(result.incident_id),
        thread_id=result.thread_id,
        duplicate=result.duplicate,
        analysis_only=result.analysis_only,
        file_path=result.file_path,
    ).info("code alert processed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Consume OpsFlow alerts from SQS")
    parser.add_argument("--once", action="store_true", help="Process one poll and exit")
    args = parser.parse_args()

    if not settings.sqs_alert_queue_url:
        raise SystemExit("SQS_ALERT_QUEUE_URL is not configured")

    log.bind(
        queue_url=settings.sqs_alert_queue_url,
        region=settings.aws_region,
        code_fix_enabled=settings.code_fix_enabled,
        analysis_only=settings.code_fix_analysis_only,
    ).info("starting alert consumer")

    consumer = SqsConsumer(
        queue_url=settings.sqs_alert_queue_url,
        handler=handle_message,
        region=settings.aws_region,
        profile=settings.aws_profile,
        wait_time_seconds=settings.sqs_wait_time_seconds,
        visibility_timeout_seconds=settings.sqs_visibility_timeout_seconds,
        max_messages=settings.sqs_max_messages,
        heartbeat_seconds=settings.sqs_heartbeat_seconds,
    )
    processed = consumer.run(once=args.once)
    print(f"processed {processed} SQS message(s)")


if __name__ == "__main__":
    main()
