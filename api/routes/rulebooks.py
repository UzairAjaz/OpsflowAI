from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from api.auth import Principal, get_principal, require_role
from app.rulebooks import (
    RulebookTenantNotFound,
    create_rulebook,
    delete_rulebook,
    get_rulebook,
    list_rulebooks,
    update_rulebook,
)
from db.models import Tenant
from db.session import SessionLocal

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/rulebooks",
    tags=["rulebooks"],
)

class RulebookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)

class RulebookUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1)
    tags: list[str] | None = None
    is_active: bool | None = None

class RulebookSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rulebook_id: UUID
    tenant_id: str
    title: str
    tags: list[str]
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

class RulebookDetail(RulebookSummary):
    content: str

def _assert_tenant(tenant_id: str, principal: Principal) -> None:
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="tenant not found")

def _require_tenant(session, tenant_id: str) -> None:
    if session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="tenant not found")

@router.post("", response_model=RulebookDetail, status_code=status.HTTP_201_CREATED)
def create_rulebook_endpoint(
    tenant_id: str,
    body: RulebookCreate,
    principal: Principal = Depends(get_principal),
) -> RulebookDetail:
    require_role(principal, "admin")
    _assert_tenant(tenant_id, principal)

    with SessionLocal() as session:
        _require_tenant(session, tenant_id)
        try:
            rulebook = create_rulebook(
                session,
                tenant_id=tenant_id,
                title=body.title,
                content=body.content,
                tags=body.tags,
                actor=principal.subject,
            )
            session.commit()
            session.refresh(rulebook)
            return RulebookDetail.model_validate(rulebook)
        except RulebookTenantNotFound:
            raise HTTPException(status_code=404, detail="tenant not found")
        except IntegrityError:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="a rulebook with this title and version already exists",
            )
        except Exception as exc:
            session.rollback()
            raise HTTPException(
                status_code=503,
                detail=f"rulebook indexing failed: {exc}",
            )

@router.get("", response_model=list[RulebookSummary])
def list_rulebooks_endpoint(
    tenant_id: str,
    principal: Principal = Depends(get_principal),
) -> list[RulebookSummary]:
    require_role(principal, "viewer", "responder", "approver", "admin")
    _assert_tenant(tenant_id, principal)

    with SessionLocal() as session:
        _require_tenant(session, tenant_id)
        return [
            RulebookSummary.model_validate(rulebook)
            for rulebook in list_rulebooks(session, tenant_id)
        ]

@router.get("/{rulebook_id}", response_model=RulebookDetail)
def get_rulebook_endpoint(
    tenant_id: str,
    rulebook_id: UUID,
    principal: Principal = Depends(get_principal),
) -> RulebookDetail:
    require_role(principal, "viewer", "responder", "approver", "admin")
    _assert_tenant(tenant_id, principal)

    with SessionLocal() as session:
        rulebook = get_rulebook(session, tenant_id, rulebook_id)
        if rulebook is None:
            raise HTTPException(status_code=404, detail="rulebook not found")
        return RulebookDetail.model_validate(rulebook)

@router.put("/{rulebook_id}", response_model=RulebookDetail)
def update_rulebook_endpoint(
    tenant_id: str,
    rulebook_id: UUID,
    body: RulebookUpdate,
    principal: Principal = Depends(get_principal),
) -> RulebookDetail:
    require_role(principal, "admin")
    _assert_tenant(tenant_id, principal)

    with SessionLocal() as session:
        rulebook = get_rulebook(session, tenant_id, rulebook_id)
        if rulebook is None:
            raise HTTPException(status_code=404, detail="rulebook not found")
        try:
            update_rulebook(
                session,
                rulebook,
                title=body.title,
                content=body.content,
                tags=body.tags,
                is_active=body.is_active,
                actor=principal.subject,
            )
            session.commit()
            session.refresh(rulebook)
            return RulebookDetail.model_validate(rulebook)
        except IntegrityError:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="a rulebook with this title and version already exists",
            )
        except Exception as exc:
            session.rollback()
            raise HTTPException(
                status_code=503,
                detail=f"rulebook indexing failed: {exc}",
            )

@router.delete("/{rulebook_id}")
def delete_rulebook_endpoint(
    tenant_id: str,
    rulebook_id: UUID,
    principal: Principal = Depends(get_principal),
) -> dict:
    require_role(principal, "admin")
    _assert_tenant(tenant_id, principal)

    with SessionLocal() as session:
        rulebook = get_rulebook(session, tenant_id, rulebook_id)
        if rulebook is None:
            raise HTTPException(status_code=404, detail="rulebook not found")
        delete_rulebook(session, rulebook, actor=principal.subject)
        session.commit()
        return {
            "status": "deleted",
            "tenant_id": tenant_id,
            "rulebook_id": str(rulebook_id),
        }

__all__ = ["router"]
