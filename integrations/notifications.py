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
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "OpsFlow: approval required"},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
    ]

    report = summary.get("report")
    if report:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Incident report:*\n{str(report)[:2500]}",
                },
            }
        )

    blocks.append(
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
        }
    )
    return blocks

class ConsoleNotifier:
    name = "console"

    def send_approval_request(self, *, summary: dict) -> NotificationResult:
        print(
            f"[notify:console] approval required for {summary.get('thread_id')} "
            f"({summary.get('service')})"
        )
        print(
            f"[notify:console] proposed solution: {summary.get('solution')} "
            f"| rationale: {summary.get('rationale')}"
        )
        print(
            f"[notify:console] {summary.get('question', 'Do I implement it? (yes/no)')} "
            "Run: python approve_pending.py --wait"
        )
        report = summary.get("report")
        if report:
            print(f"[notify:console] incident report ready ({len(str(report))} chars)")
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
            with httpx.Client(timeout=settings.notification_timeout_seconds) as client:
                response = client.post(self._url, json={"blocks": build_slack_blocks(summary)})
                response.raise_for_status()
            return NotificationResult(channel=self.name, ok=True, detail="sent")
        except Exception as exc:
            return NotificationResult(channel=self.name, ok=False, detail=str(exc))

    def send_escalation(self, *, level: int, recipient: str, summary: dict) -> NotificationResult:
        return self.send_approval_request(summary=summary)

class EmailNotifier:
    name = "email"

    def __init__(
        self,
        to: str | None = None,
        approval_base_url: str | None = None,
    ) -> None:
        self._to = to or settings.smtp_to
        self._approval_base_url = (approval_base_url or settings.public_base_url).rstrip("/")

    def send_approval_request(self, *, summary: dict) -> NotificationResult:
        if not settings.smtp_host:
            return NotificationResult(channel=self.name, ok=False, detail="smtp not configured")
        thread_id = str(summary.get("thread_id"))
        base = self._approval_base_url
        approve = sign_approval_token(
            thread_id, "approve", tenant_id=summary.get("tenant_id")
        )
        reject = sign_approval_token(
            thread_id, "reject", tenant_id=summary.get("tenant_id")
        )
        body = (
            f"Approval required for {thread_id} ({summary.get('service')}).\n\n"
            f"Proposed fix: {summary.get('solution')}\n"
            f"Risk: {summary.get('risk_level')}\n"
            f"Sandbox: {'passed' if summary.get('validated') else 'not run'}\n\n"
            f"Approve: {base}/api/v1/approvals/email?token={approve}\n"
            f"Reject:  {base}/api/v1/approvals/email?token={reject}\n"
        )
        if summary.get("report"):
            body += "\n--- Incident Report ---\n" + str(summary["report"])
        try:
            import smtplib
            from email.message import EmailMessage

            message = EmailMessage()
            message["Subject"] = f"[OpsFlow] Approval required: {thread_id}"
            message["From"] = settings.smtp_from
            message["To"] = self._to
            message.set_content(body)

            if settings.smtp_use_ssl:
                smtp_client = smtplib.SMTP_SSL(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.notification_timeout_seconds,
                )
            else:
                smtp_client = smtplib.SMTP(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.notification_timeout_seconds,
                )

            with smtp_client as smtp:
                if not settings.smtp_use_ssl and settings.smtp_user:
                    smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
            return NotificationResult(channel=self.name, ok=True, detail="sent")
        except Exception as exc:
            return NotificationResult(channel=self.name, ok=False, detail=str(exc))

    def send_escalation(self, *, level: int, recipient: str, summary: dict) -> NotificationResult:
        return self.send_approval_request(summary=summary)

class SmsNotifier:
    name = "sms"

    def __init__(self, to: str | None = None) -> None:
        self._to = to or settings.twilio_to

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
            and self._to
        ):
            return NotificationResult(channel=self.name, ok=False, detail="twilio not configured")
        url = (
            f"{settings.twilio_api_base_url.rstrip('/')}/2010-04-01/Accounts/"
            f"{settings.twilio_account_sid}/Messages.json"
        )
        try:
            with httpx.Client(timeout=settings.notification_timeout_seconds) as client:
                response = client.post(
                    url,
                    data={
                        "From": settings.twilio_from,
                        "To": self._to,
                        "Body": text,
                    },
                    auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                )
                response.raise_for_status()
            return NotificationResult(channel=self.name, ok=True, detail="sent")
        except Exception as exc:
            return NotificationResult(channel=self.name, ok=False, detail=str(exc))

_OVERRIDE: list[Notifier] | None = None

def _tenant_notification_config(tenant_id: str | None) -> dict:
    if not tenant_id:
        return {}

    try:
        from db.models import Tenant
        from db.session import SessionLocal

        with SessionLocal() as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None or not isinstance(tenant.settings, dict):
                return {}
            config = dict(tenant.settings)
            nested = config.get("notifications")
            if isinstance(nested, dict):
                config.update(nested)
            channels = config.get("channels") or config.get("notification_channels") or []
            if isinstance(channels, str):
                channels = [item.strip() for item in channels.split(",") if item.strip()]
            config["channels"] = [str(item).lower() for item in channels]
            return config
    except Exception:
        return {}

def set_notifiers(notifiers: list[Notifier] | None) -> None:
    global _OVERRIDE
    _OVERRIDE = notifiers

def get_notifiers(tenant_id: str | None = None) -> list[Notifier]:
    if _OVERRIDE is not None:
        return _OVERRIDE

    config = _tenant_notification_config(tenant_id)
    channels = config.get("channels") or []

    notifiers: list[Notifier] = []
    for channel in channels:
        if channel == "console":
            notifiers.append(ConsoleNotifier())
        elif channel == "slack":
            notifiers.append(SlackNotifier(config.get("slack_webhook_url")))
        elif channel == "email":
            notifiers.append(
                EmailNotifier(
                    to=config.get("email_to"),
                    approval_base_url=config.get("approval_base_url"),
                )
            )
        elif channel == "sms":
            notifiers.append(SmsNotifier(config.get("sms_to")))

    if notifiers:
        return notifiers

    return [SlackNotifier(), EmailNotifier(), SmsNotifier(), ConsoleNotifier()]

def dispatch_approval(summary: dict, notifiers: list[Notifier] | None = None) -> list[NotificationResult]:
    channels = (
        notifiers
        if notifiers is not None
        else get_notifiers(summary.get("tenant_id"))
    )
    return [channel.send_approval_request(summary=summary) for channel in channels]

def dispatch_escalation(
    level: int, recipient: str, summary: dict, notifiers: list[Notifier] | None = None
) -> list[NotificationResult]:
    channels = (
        notifiers
        if notifiers is not None
        else get_notifiers(summary.get("tenant_id"))
    )
    return [channel.send_escalation(level=level, recipient=recipient, summary=summary) for channel in channels]
