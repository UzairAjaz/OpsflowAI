from __future__ import annotations

import smtplib

from app.config import settings
from integrations.notifications import (
    EmailNotifier,
    build_slack_blocks,
    get_notifiers,
)

class FakeSMTP:
    messages: list = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        return None

    def login(self, user, password):
        return None

    def send_message(self, message):
        self.messages.append(message)

def main() -> None:
    summary = {
        "thread_id": "inc-notify-day7",
        "tenant_id": "mediconnect",
        "service": "mediconnect-backend",
        "root_cause": "Memory limit too low",
        "severity": "high",
        "risk_level": "medium",
        "remediation_id": "increase_memory_limit",
        "params": {"container_name": "mediconnect-backend", "new_memory_limit": "2Gi"},
        "validated": True,
        "confidence": 82,
        "solution": "increase_memory_limit({'container_name': 'mediconnect-backend'})",
        "question": "Do I implement it? (yes/no)",
        "report": "# OpsFlow Incident Report\n\n## Root Cause\nMemory limit too low.",
    }

    channels = [notifier.name for notifier in get_notifiers("mediconnect")]
    assert "console" in channels, channels
    if settings.smtp_host and settings.smtp_to:
        assert "email" in channels, channels
    print("routing    ->", channels)

    blocks = build_slack_blocks(summary)
    report_blocks = [
        block for block in blocks if "Incident report" in str(block.get("text", {}).get("text", ""))
    ]
    assert report_blocks
    assert blocks[-1]["type"] == "actions"
    print("slack      -> report section + approve/reject buttons")

    original_host = settings.smtp_host
    original_from = settings.smtp_from
    original_to = settings.smtp_to
    original_ssl = settings.smtp_use_ssl
    original_smtp = smtplib.SMTP
    FakeSMTP.messages = []
    settings.smtp_host = "smtp.example.local"
    settings.smtp_from = "opsflow@mediconnect.local"
    settings.smtp_to = "fallback@mediconnect.local"
    settings.smtp_use_ssl = False
    smtplib.SMTP = FakeSMTP

    try:
        notifier = EmailNotifier(
            to="developer@mediconnect.local",
            approval_base_url="http://127.0.0.1:8000",
        )
        result = notifier.send_approval_request(summary=summary)
        assert result.ok, result.detail
        assert FakeSMTP.messages, "email was not sent"
        message = FakeSMTP.messages[-1]
        body = message.get_content()
        assert message["To"] == "developer@mediconnect.local"
        assert "Incident Report" in body
        assert "api/v1/approvals/email?token=" in body
        print("email      -> tenant recipient + report + approval links")
    finally:
        settings.smtp_host = original_host
        settings.smtp_from = original_from
        settings.smtp_to = original_to
        settings.smtp_use_ssl = original_ssl
        smtplib.SMTP = original_smtp

    print("[ok] Day 7 tenant notifications work.")

if __name__ == "__main__":
    main()
