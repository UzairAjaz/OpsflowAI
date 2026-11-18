from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from observability.logging import get_logger

log = get_logger(stage="sqs")


class SqsConsumer:
    """Long-poll an SQS queue and keep messages invisible while handling."""

    def __init__(
        self,
        *,
        queue_url: str,
        handler: Callable[[dict[str, Any]], Any],
        region: str,
        profile: str | None = None,
        wait_time_seconds: int = 20,
        visibility_timeout_seconds: int = 900,
        max_messages: int = 1,
        heartbeat_seconds: int = 120,
    ) -> None:
        self.queue_url = queue_url
        self.handler = handler
        self.wait_time_seconds = wait_time_seconds
        self.visibility_timeout_seconds = visibility_timeout_seconds
        self.max_messages = max_messages
        self.heartbeat_seconds = heartbeat_seconds
        session = boto3.Session(profile_name=profile or None, region_name=region)
        self.client = session.client("sqs")

    def run(self, *, once: bool = False) -> int:
        processed = 0
        while True:
            try:
                response = self.client.receive_message(
                    QueueUrl=self.queue_url,
                    MaxNumberOfMessages=self.max_messages,
                    WaitTimeSeconds=self.wait_time_seconds,
                    VisibilityTimeout=self.visibility_timeout_seconds,
                    AttributeNames=["ApproximateReceiveCount"],
                )
            except (BotoCoreError, ClientError):
                log.exception("SQS receive failed")
                if once:
                    return processed
                time.sleep(5)
                continue

            messages = response.get("Messages", [])
            if not messages:
                if once:
                    return processed
                continue

            for message in messages:
                self._process(message)
                processed += 1
                if once:
                    return processed

    def _process(self, message: dict[str, Any]) -> None:
        receipt = message["ReceiptHandle"]
        stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat,
            args=(receipt, stop),
            daemon=True,
        )
        heartbeat.start()
        try:
            self.handler(message)
        except Exception:
            log.bind(
                message_id=message.get("MessageId"),
                receive_count=message.get("Attributes", {}).get(
                    "ApproximateReceiveCount"
                ),
            ).exception("SQS message handler failed; leaving message for retry")
            return
        finally:
            stop.set()

        try:
            self.client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt,
            )
            log.bind(message_id=message.get("MessageId")).info("SQS message deleted")
        except (BotoCoreError, ClientError):
            log.bind(message_id=message.get("MessageId")).exception(
                "SQS delete failed; message may be redelivered"
            )

    def _heartbeat(self, receipt: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_seconds):
            try:
                self.client.change_message_visibility(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=receipt,
                    VisibilityTimeout=self.visibility_timeout_seconds,
                )
            except (BotoCoreError, ClientError):
                log.exception("SQS visibility heartbeat failed")
                return
