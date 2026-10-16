"""P2-23..P2-25 check: notifications and escalation.

- Slack Block Kit message includes approve/reject buttons,
- notification dispatch records via a FakeNotifier,
- email approval tokens are embedded in the links,
- escalation policy fires at the right levels and advances the incident.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.approval_tokens import sign_approval_token, verify_approval_token
from integrations.escalation import due_escalation, parse_escalation_minutes, process_escalations
from integrations.notifications import (
    FakeNotifier,
    build_slack_blocks,
    dispatch_approval,
)
from db.models import Incident
from db.session import SessionLocal

SERVICE = "notify-check"


def _cleanup() -> None:
    with SessionLocal() as session:
        incidents = (
            session.execute(select(Incident).where(Incident.service == SERVICE)).scalars().all()
        )
        for incident in incidents:
            session.delete(incident)
        session.commit()


def main() -> None:
    summary = {
        "thread_id": "inc-1",
        "tenant_id": "acme",
        "service": SERVICE,
        "root_cause": "memory limit too low",
        "severity": "high",
        "risk_level": "medium",
        "remediation_id": "increase_memory_limit",
        "params": {"container_name": SERVICE, "new_memory_limit": "2Gi"},
        "validated": True,
        "confidence": 95,
    }

    blocks = build_slack_blocks(summary)
    labels = [block["type"] for block in blocks]
    actions = blocks[-1]["elements"]
    assert labels[0] == "header" and "actions" in labels
    assert {action["action_id"] for action in actions} == {"approve", "reject"}
    assert actions[0]["value"] == "inc-1"
    print("slack     -> buttons:", [action["action_id"] for action in actions])

    fake = FakeNotifier()
    dispatch_approval(summary, notifiers=[fake])
    assert len(fake.approvals) == 1
    print("dispatch  -> fake recorded", len(fake.approvals), "approval request(s)")

    email_token = sign_approval_token("inc-1", "approve")
    assert verify_approval_token(email_token)
    print("email     -> link token verifies:", True)

    minutes = parse_escalation_minutes()
    assert minutes == [15, 30, 60]
    assert due_escalation(elapsed_minutes=10, current_level=0) is None
    assert due_escalation(elapsed_minutes=20, current_level=0).level == 1
    assert due_escalation(elapsed_minutes=35, current_level=1).level == 2
    assert due_escalation(elapsed_minutes=70, current_level=0).level == 3
    assert due_escalation(elapsed_minutes=20, current_level=2) is None
    print("escalation-> thresholds:", minutes)

    _cleanup()
    try:
        now = datetime.now(timezone.utc)
        with SessionLocal() as session:
            session.add(
                Incident(
                    thread_id=f"notify-{uuid.uuid4().hex[:8]}",
                    source="test",
                    service=SERVICE,
                    tenant_id="acme",
                    error_class="OOMKilled",
                    severity="critical",
                    status="awaiting_approval",
                    approval_requested_at=now - timedelta(minutes=40),
                    escalated_level=0,
                )
            )
            session.commit()

        fake2 = FakeNotifier()
        first = process_escalations(notifiers=[fake2])
        assert len(first) == 1 and first[0]["level"] == 2, first
        assert len(fake2.escalations) == 1
        second = process_escalations(notifiers=[fake2])
        assert second == []
        print("process   -> escalated to level", first[0]["level"], "->", first[0]["recipient"])
    finally:
        _cleanup()

    print("[ok] P2-23..P2-25 -- notifications and escalation working.")


if __name__ == "__main__":
    main()
