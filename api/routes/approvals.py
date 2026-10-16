"""Approval endpoints: resume a paused incident from an external channel.

- `GET  /email?token=...`       — signed email link
- `POST /slack/interactions`    — Slack interactive buttons (signature verified)
- `GET  /{thread_id}`           — pending status (API key)
- `POST /{thread_id}`           — approve/reject (API key)
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from api.security import authenticate_api_key, verify_slack_signature
from app.approval_service import is_pending, resume_incident
from app.approval_tokens import verify_approval_token
from app.config import settings

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


class ApprovalDecision(BaseModel):
    approved: bool
    approver: str = "api"


@router.get("/email")
async def email_decision(token: str) -> dict:
    payload = verify_approval_token(token)
    if not payload:
        raise HTTPException(status_code=400, detail="invalid or expired token")
    result = await run_in_threadpool(
        resume_incident,
        thread_id=payload["t"],
        approved=payload["d"] == "approve",
        approver="email",
    )
    if result["status"] == "no_pending":
        raise HTTPException(status_code=409, detail="no pending approval")
    return result


@router.post("/slack/interactions")
async def slack_interactions(request: Request) -> dict:
    body = await request.body()
    if not verify_slack_signature(
        settings.slack_signing_secret,
        request.headers.get("X-Slack-Request-Timestamp"),
        body,
        request.headers.get("X-Slack-Signature"),
    ):
        raise HTTPException(status_code=401, detail="invalid slack signature")

    form = parse_qs(body.decode("utf-8"))
    payload = json.loads(form.get("payload", ["{}"])[0])
    actions = payload.get("actions") or []
    if not actions:
        raise HTTPException(status_code=400, detail="no action in payload")

    action = actions[0]
    thread_id = action.get("value")
    if not thread_id:
        raise HTTPException(status_code=400, detail="missing thread id")

    result = await run_in_threadpool(
        resume_incident,
        thread_id=thread_id,
        approved=action.get("action_id") == "approve",
        approver=(payload.get("user") or {}).get("name", "slack"),
    )
    return result


@router.get("/{thread_id}")
async def pending(thread_id: str, x_api_key: str | None = Header(default=None)) -> dict:
    if authenticate_api_key(settings.tenant_api_keys, x_api_key) is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return {
        "thread_id": thread_id,
        "pending": await run_in_threadpool(is_pending, thread_id=thread_id),
    }


@router.post("/{thread_id}")
async def decide(
    thread_id: str,
    body: ApprovalDecision,
    x_api_key: str | None = Header(default=None),
) -> dict:
    if authenticate_api_key(settings.tenant_api_keys, x_api_key) is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    result = await run_in_threadpool(
        resume_incident, thread_id=thread_id, approved=body.approved, approver=body.approver
    )
    if result["status"] == "no_pending":
        raise HTTPException(status_code=409, detail="no pending approval")
    return result
