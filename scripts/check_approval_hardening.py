from __future__ import annotations

import uuid
from types import SimpleNamespace

from sqlalchemy import delete, select

from app.approval_service import resume_incident
from app.approval_store import consume_approval_token
from app.approval_tokens import sign_approval_token, verify_approval_token
from db.models import ApprovalTokenUse, AuditLog, Incident
from db.session import SessionLocal

THREAD_ID = f"appr-hard-{uuid.uuid4().hex[:8]}"

class StubGraph:
    def get_state(self, config):
        return SimpleNamespace(next=("approval",))

    def invoke(self, command, config):
        return {"status": "completed"}

def main() -> None:
    token_one = sign_approval_token(
        THREAD_ID, "approve", tenant_id="mediconnect"
    )
    payload = verify_approval_token(token_one)
    assert payload is not None
    assert payload["t"] == THREAD_ID
    assert payload["d"] == "approve"
    assert payload["tenant"] == "mediconnect"
    assert payload["jti"]
    print("token       -> signed with tenant + unique id")

    token_two = sign_approval_token(
        THREAD_ID, "approve", tenant_id="mediconnect"
    )
    assert verify_approval_token(token_two)["jti"] != payload["jti"]
    print("uniqueness  -> two tokens have different ids")

    with SessionLocal() as session:
        session.add(
            Incident(
                thread_id=THREAD_ID,
                source="cloudwatch",
                service="mediconnect-backend",
                tenant_id="mediconnect",
                error_class="OOMKilled",
                severity="high",
                status="awaiting_approval",
            )
        )
        session.commit()

    try:
        used = consume_approval_token(
            token_id=payload["jti"],
            thread_id=THREAD_ID,
            tenant_id=payload["tenant"],
            decision=payload["d"],
            used_by="email",
        )
        assert used is True
        replay = consume_approval_token(
            token_id=payload["jti"],
            thread_id=THREAD_ID,
            tenant_id=payload["tenant"],
            decision=payload["d"],
            used_by="email",
        )
        assert replay is False
        print("replay      -> first use accepted, second rejected")

        result = resume_incident(
            thread_id=THREAD_ID,
            approved=True,
            approver="day8-test",
            graph=StubGraph(),
        )
        assert result["status"] == "resumed"
        assert result["graph_status"] == "completed"

        with SessionLocal() as session:
            incident = session.execute(
                select(Incident).where(Incident.thread_id == THREAD_ID)
            ).scalar_one()
            assert incident.status == "approved"
            audit = session.execute(
                select(AuditLog).where(
                    AuditLog.tenant_id == "mediconnect",
                    AuditLog.action == "approval.approve",
                    AuditLog.details["thread_id"].astext == THREAD_ID,
                )
            ).scalars().all()
            assert audit
        print("audit       -> approval decision recorded")

        print("[ok] Day 8 approval hardening works.")
    finally:
        with SessionLocal() as session:
            session.execute(
                delete(ApprovalTokenUse).where(
                    ApprovalTokenUse.thread_id == THREAD_ID
                )
            )
            session.execute(
                delete(AuditLog).where(
                    AuditLog.details["thread_id"].astext == THREAD_ID
                )
            )
            incident = session.execute(
                select(Incident).where(Incident.thread_id == THREAD_ID)
            ).scalar_one_or_none()
            if incident is not None:
                session.delete(incident)
            session.commit()

if __name__ == "__main__":
    main()
