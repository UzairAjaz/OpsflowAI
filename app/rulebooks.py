from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.chunking import chunk_text
from app.embeddings import embed_texts
from db.models import AuditLog, Rulebook, RulebookChunk, Tenant, User

class RulebookTenantNotFound(ValueError):
    pass

def get_rulebook(session, tenant_id: str, rulebook_id: uuid.UUID) -> Rulebook | None:
    return session.execute(
        select(Rulebook).where(
            Rulebook.tenant_id == tenant_id,
            Rulebook.rulebook_id == rulebook_id,
        )
    ).scalar_one_or_none()

def list_rulebooks(session, tenant_id: str) -> list[Rulebook]:
    return list(
        session.execute(
            select(Rulebook)
            .where(Rulebook.tenant_id == tenant_id)
            .order_by(Rulebook.title, Rulebook.version)
        )
        .scalars()
        .all()
    )

def _resolve_user_id(session, tenant_id: str, subject: str) -> uuid.UUID | None:
    user = session.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            User.email == subject,
        )
    ).scalar_one_or_none()
    return user.user_id if user else None

def _audit(
    session,
    *,
    tenant_id: str,
    action: str,
    actor: str,
    details: dict,
) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            action=action,
            actor=actor,
            details=details,
        )
    )

def _replace_chunks(session, rulebook: Rulebook) -> int:
    session.execute(
        delete(RulebookChunk).where(RulebookChunk.rulebook_id == rulebook.rulebook_id)
    )

    chunks = chunk_text(rulebook.content)
    vectors = embed_texts(chunks)

    for index, (content, vector) in enumerate(zip(chunks, vectors, strict=True)):
        session.add(
            RulebookChunk(
                rulebook_id=rulebook.rulebook_id,
                tenant_id=rulebook.tenant_id,
                chunk_index=index,
                content=content,
                embedding=vector,
                chunk_metadata={
                    "rulebook_id": str(rulebook.rulebook_id),
                    "title": rulebook.title,
                    "version": rulebook.version,
                },
            )
        )
    return len(chunks)

def replace_rulebook_chunks(session, rulebook: Rulebook) -> int:
    return _replace_chunks(session, rulebook)

def create_rulebook(
    session,
    *,
    tenant_id: str,
    title: str,
    content: str,
    tags: list[str] | None = None,
    actor: str = "system",
) -> Rulebook:
    if session.get(Tenant, tenant_id) is None:
        raise RulebookTenantNotFound(tenant_id)

    rulebook = Rulebook(
        tenant_id=tenant_id,
        title=title,
        content=content,
        tags=tags or [],
        version=1,
        created_by=_resolve_user_id(session, tenant_id, actor),
    )
    session.add(rulebook)
    session.flush()

    chunk_count = _replace_chunks(session, rulebook)
    _audit(
        session,
        tenant_id=tenant_id,
        action="rulebook.create",
        actor=actor,
        details={
            "rulebook_id": str(rulebook.rulebook_id),
            "title": rulebook.title,
            "version": rulebook.version,
            "chunks": chunk_count,
        },
    )
    return rulebook

def update_rulebook(
    session,
    rulebook: Rulebook,
    *,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    is_active: bool | None = None,
    actor: str = "system",
) -> Rulebook:
    if title is not None:
        rulebook.title = title
    if content is not None:
        rulebook.content = content
    if tags is not None:
        rulebook.tags = tags
    if is_active is not None:
        rulebook.is_active = is_active

    rulebook.version += 1
    session.flush()

    chunk_count = _replace_chunks(session, rulebook)
    _audit(
        session,
        tenant_id=rulebook.tenant_id,
        action="rulebook.update",
        actor=actor,
        details={
            "rulebook_id": str(rulebook.rulebook_id),
            "title": rulebook.title,
            "version": rulebook.version,
            "chunks": chunk_count,
        },
    )
    return rulebook

def delete_rulebook(session, rulebook: Rulebook, *, actor: str = "system") -> None:
    _audit(
        session,
        tenant_id=rulebook.tenant_id,
        action="rulebook.delete",
        actor=actor,
        details={
            "rulebook_id": str(rulebook.rulebook_id),
            "title": rulebook.title,
            "version": rulebook.version,
        },
    )
    session.delete(rulebook)

__all__ = [
    "RulebookTenantNotFound",
    "create_rulebook",
    "delete_rulebook",
    "get_rulebook",
    "list_rulebooks",
    "replace_rulebook_chunks",
    "update_rulebook",
]
