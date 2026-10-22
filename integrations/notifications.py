from __future__ import annotations

from typing import Protocol

import httpx
from pydantic import BaseModel

from app.approval_tokens import sign_approval_token
from app.config import settings

class NotificationResult(BaseModel):
    channel: str
    ok: bool
    detail: str = ""

class Notifier(Protocol):
    name: str

    def send_approval_request(self, *, summary: dict) -> NotificationResult: ...

    def send_escalation(
        self, *, level: int, recipient: str, summary: dict
    ) -> NotificationResult: ...

def build_slack_blocks(summary: dict) -> list[dict]:
    thread_id = summary.get("thread_id")
    text = "\n".join(
        [
            f"*Incident:* `{thread_id}`  ({summary.get('tenant_id')} / {summary.get('service')})",
            f"*Root cause:* {summary.get('root_cause')}",
            f"*Severity:* {summary.get('severity')}    *Risk:* {summary.get('risk_level')}",
            f"*Fix:* `{summary.get('remediation_id')}` params={summary.get('params')}",
            f"*Sandbox:* {'passed' if summary.get('validated') else 'not run'}"
            f"    *Confidence:* {summary.get('confidence')}",
        ]
    )
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "OpsFlow: approval required"},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve for production"},
                    "style": "primary",
                    "action_id": "approve",
                    "value": thread_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "action_id": "reject",
                    "value": thread_id,
                },
            ],
        },
    ]

class ConsoleNotifier:
    name = "console"

    def send_approval_request(self, *, summary: dict) -> NotificationResult:
        print(
            f"[notify:console] approval required for {summary.get('thread_id')} "
            f"({summary.get('service')}): {summary.get('remediation_id')}"
        )
        return NotificationResult(channel=self.name, ok=True, detail="printed to console")

    def send_escalation(self, *, level: int, recipient: str, summary: dict) -> NotificationResult:
        print(
            f"[notify:console] escalation L{level} -> {recipient} "
            f"for {summary.get('thread_id')}"
        )
        return NotificationResult(channel=self.name, ok=True, detail="printed to console")

class FakeNotifier:
    name = "fake"

    def __init__(self) -> None:
        self.approvals: list[dict] = []
        self.escalations: list[dict] = []

    def send_approval_request(self, *, summary: dict) -> NotificationResult:
        self.approvals.append(summary)
        return NotificationResult(channel=self.name, ok=True, detail="recorded")

    def send_escalation(self, *, level: int, recipient: str, summary: dict) -> NotificationResult:
        self.escalations.append({"level": level, "recipient": recipient, "summary": summary})
        return NotificationResult(channel=self.name, ok=True, detail="recorded")

class SlackNotifier:
    name = "slack"

    def __init__(self, webhook_url: str | None = None) -> None:
        self._url = webhook_url if webhook_url is not None else settings.slack_webhook_url

    def send_approval_request(self, *, summary: dict) -> NotificationResult:
        if not self._url:
            return NotificationResult(channel=self.name, ok=False, detail="slack not configured")
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(self._url, json={"blocks": build_slack_blocks(summary)})
                response.raise_for_status()
            return NotificationResult(channel=self.name, ok=True, detail="sent")
        except Exception as exc:
            return NotificationResult(channel=self.name, ok=False, detail=str(exc))

    def send_escalation(self, *, level: int, recipient: str, summary: dict) -> NotificationResult:
        return self.send_approval_request(summary=summary)

class EmailNotifier:
    name = "email"

    def send_approval_request(self, *, summary: dict) -> NotificationResult:
        if not settings.smtp_host:
            return NotificationResult(channel=self.name, ok=False, detail="smtp not configured")
        thread_id = str(summary.get("thread_id"))
        base = settings.public_base_url.rstrip("/")
        approve = sign_approval_token(thread_id, "approve")
        reject = sign_approval_token(thread_id, "reject")
        body = (
            f"Approval required for {thread_id} ({summary.get('service')}).\n\n"
            f"Approve: {base}/api/v1/approvals/email?token={approve}\n"
            f"Reject:  {base}/api/v1/approvals/email?token={reject}\n"
        )
        try:
            import smtplib
            from email.message import EmailMessage

            message = EmailMessage()
            message["Subject"] = f"[OpsFlow] Approval required: {thread_id}"
            message["From"] = settings.smtp_from
            message["To"] = settings.smtp_to
            message.set_content(body)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                if settings.smtp_user:
                    smtp.starttls()
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
            return NotificationResult(channel=self.name, ok=True, detail="sent")
        except Exception as exc:
            return NotificationResult(channel=self.name, ok=False, detail=str(exc))

    def send_escalation(self, *, level: int, recipient: str, summary: dict) -> NotificationResult:
        return self.send_approval_request(summary=summary)

class SmsNotifier:
    name = "sms"

    def send_approval_request(self, *, summary: dict) -> NotificationResult:
        return self._send(
            f"OpsFlow approval required: {summary.get('thread_id')} ({summary.get('severity')})"
        )

    def send_escalation(self, *, level: int, recipient: str, summary: dict) -> NotificationResult:
        return self._send(
            f"OpsFlow escalation L{level} -> {recipient}: {summary.get('thread_id')}"
        )

    def _send(self, text: str) -> NotificationResult:
        if not (
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_from
            and settings.twilio_to
        ):
            return NotificationResult(channel=self.name, ok=False, detail="twilio not configured")
        url = (
            "https://api.twilio.com/2010-04-01/Accounts/"
            f"{settings.twilio_account_sid}/Messages.json"
        )
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    url,
                    data={
                        "From": settings.twilio_from,
                        "To": settings.twilio_to,
                        "Body": text,
                    },
                    auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                )
                response.raise_for_status()
            return NotificationResult(channel=self.name, ok=True, detail="sent")
        except Exception as exc:
            return NotificationResult(channel=self.name, ok=False, detail=str(exc))

_OVERRIDE: list[Notifier] | None = None

def set_notifiers(notifiers: list[Notifier] | None) -> None:
    global _OVERRIDE
    _OVERRIDE = notifiers

def get_notifiers() -> list[Notifier]:
    if _OVERRIDE is not None:
        return _OVERRIDE
    return [SlackNotifier(), EmailNotifier(), SmsNotifier(), ConsoleNotifier()]

def dispatch_approval(summary: dict, notifiers: list[Notifier] | None = None) -> list[NotificationResult]:
    channels = notifiers if notifiers is not None else get_notifiers()
    return [channel.send_approval_request(summary=summary) for channel in channels]

def dispatch_escalation(
    level: int, recipient: str, summary: dict, notifiers: list[Notifier] | None = None
) -> list[NotificationResult]:
    channels = notifiers if notifiers is not None else get_notifiers()
    return [channel.send_escalation(level=level, recipient=recipient, summary=summary) for channel in channels]
