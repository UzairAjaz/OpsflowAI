from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from db.models import ApprovalTokenUse
from db.session import SessionLocal

def consume_approval_token(
    *,
    token_id: str,
    thread_id: str,
    tenant_id: str | None,
    decision: str,
    used_by: str,
) -> bool:
    with SessionLocal() as session:
        if session.get(ApprovalTokenUse, token_id) is not None:
            return False

        session.add(
            ApprovalTokenUse(
                token_id=token_id,
                thread_id=thread_id,
                tenant_id=tenant_id or "default",
                decision=decision,
                used_by=used_by,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return False
    return True

__all__ = ["consume_approval_token"]
