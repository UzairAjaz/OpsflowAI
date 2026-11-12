from __future__ import annotations

import hashlib
import html
import json
import time
from urllib.parse import parse_qs

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from api.auth import Principal, ensure_incident_tenant, get_principal, require_role
from api.security import verify_slack_signature
from app.approval_service import is_pending, resume_incident
from app.approval_store import consume_approval_token
from app.approval_tokens import verify_approval_token
from app.config import settings
from db.models import AuditLog, Incident, Tenant
from db.session import SessionLocal

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])

class ApprovalDecision(BaseModel):
    approved: bool
    approver: str = "api"

def _html_page(
    *,
    title: str,
    heading: str,
    message: str,
    tone: str = "success",
    details: dict | None = None,
) -> HTMLResponse:
    color = "#166534" if tone == "success" else "#991b1b"
    background = "#f0fdf4" if tone == "success" else "#fef2f2"
    rows = ""
    if details:
        rows = "".join(
            f"<div class='row'><span>{html.escape(str(key))}</span>"
            f"<strong>{html.escape(str(value))}</strong></div>"
            for key, value in details.items()
        )

    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #0f172a;
    }}
    .card {{
      width: min(560px, calc(100% - 32px));
      background: white;
      border: 1px solid #e2e8f0;
      border-radius: 16px;
      box-shadow: 0 20px 45px rgba(15, 23, 42, 0.08);
      overflow: hidden;
    }}
    .banner {{
      padding: 28px 32px;
      background: {background};
      border-bottom: 1px solid #e2e8f0;
    }}
    .banner h1 {{ margin: 0; color: {color}; font-size: 24px; }}
    .content {{ padding: 28px 32px; }}
    p {{ line-height: 1.6; margin: 0 0 18px; }}
    .row {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      padding: 11px 0;
      border-top: 1px solid #f1f5f9;
      font-size: 14px;
    }}
    .row span {{ color: #64748b; }}
    .row strong {{ text-align: right; }}
    .footer {{ margin-top: 24px; color: #94a3b8; font-size: 12px; }}
  </style>
</head>
<body>
  <main class="card">
    <section class="banner"><h1>{html.escape(heading)}</h1></section>
    <section class="content">
      <p>{html.escape(message)}</p>
      {rows}
      <div class="footer">OpsFlow AI · Human-in-the-loop approval</div>
    </section>
  </main>
</body>
</html>"""
    return HTMLResponse(content=body, status_code=200 if tone == "success" else 400)

def _error_page(message: str, status_code: int = 400) -> HTMLResponse:
    response = _html_page(
        title="OpsFlow approval error",
        heading="Approval could not be completed",
        message=message,
        tone="error",
    )
    response.status_code = status_code
    return response

def _decode_email_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token,
            settings.approval_token_secret,
            algorithms=["HS256"],
        )
        expiry = payload.get("e") or payload.get("exp")
        if expiry is not None and int(expiry) < int(time.time()):
            return None
        return payload
    except (jwt.PyJWTError, TypeError, ValueError):
        pass

    return verify_approval_token(token)

def _claims(payload: dict) -> tuple[str, str, str | None, str] | None:
    thread_id = str(
        payload.get("t")
        or payload.get("thread_id")
        or payload.get("incident_id")
        or ""
    ).strip()
    decision = str(payload.get("d") or payload.get("decision") or "").strip().lower()
    tenant_id = payload.get("tenant") or payload.get("tenant_id")
    tenant_id = str(tenant_id).strip() if tenant_id else None

    if not thread_id or decision not in {"approve", "reject"}:
        return None

    token_id = str(payload.get("jti") or "").strip()
    if not token_id:
        token_id = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:40]

    return thread_id, decision, tenant_id, token_id

def _get_incident(thread_id: str) -> Incident | None:
    with SessionLocal() as session:
        return session.execute(
            select(Incident).where(Incident.thread_id == thread_id)
        ).scalar_one_or_none()

def _mark_decision_direct(
    thread_id: str,
    *,
    approved: bool,
    approver: str,
) -> str | None:
    with SessionLocal() as session:
        incident = session.execute(
            select(Incident).where(Incident.thread_id == thread_id)
        ).scalar_one_or_none()
        if incident is None:
            return None

        incident.status = "approved" if approved else "rejected"
        if session.get(Tenant, incident.tenant_id) is not None:
            session.add(
                AuditLog(
                    tenant_id=incident.tenant_id,
                    incident_id=incident.incident_id,
                    action="approval.approve" if approved else "approval.reject",
                    actor=approver,
                    details={
                        "thread_id": thread_id,
                        "approved": approved,
                        "approver": approver,
                        "source": "email",
                    },
                )
            )
        session.commit()
        return incident.status

@router.get("/email", response_class=HTMLResponse)
def email_decision(token: str) -> HTMLResponse:
    payload = _decode_email_token(token)
    if not payload:
        return _error_page("This approval link is invalid or has expired.", 400)

    claims = _claims(payload)
    if claims is None:
        return _error_page("This approval link is missing required claims.", 400)

    thread_id, decision, tenant_id, token_id = claims
    approved = decision == "approve"
    approver = "email"

    incident = _get_incident(thread_id)
    if incident is None:
        return _error_page("The incident for this approval link was not found.", 404)

    if tenant_id and incident.tenant_id != tenant_id:
        return _error_page("This approval link does not belong to this tenant.", 404)

    if incident.status in {"approved", "rejected"}:
        return _html_page(
            title="OpsFlow approval already processed",
            heading="Approval already processed",
            message="This incident has already received a decision. No further action was taken.",
            details={
                "Incident": thread_id,
                "Tenant": incident.tenant_id,
                "Current status": incident.status,
            },
        )

    try:
        pending = is_pending(thread_id=thread_id)
    except Exception:
        pending = False

    if pending:
        used = consume_approval_token(
            token_id=token_id,
            thread_id=thread_id,
            tenant_id=tenant_id or incident.tenant_id,
            decision=decision,
            used_by=approver,
        )
        if not used:
            return _error_page(
                "This approval link has already been used.",
                409,
            )

        try:
            result = resume_incident(
                thread_id=thread_id,
                approved=approved,
                approver=approver,
            )
        except Exception:
            return _error_page(
                "The approval was received, but the workflow could not be resumed.",
                500,
            )

        if result.get("status") == "no_pending":
            _mark_decision_direct(thread_id, approved=approved, approver=approver)
    else:
        _mark_decision_direct(thread_id, approved=approved, approver=approver)

    return _html_page(
        title="OpsFlow approval recorded",
        heading="Remediation approved" if approved else "Remediation rejected",
        message=(
            "Your decision has been recorded successfully. "
            "You can close this window."
        ),
        details={
            "Incident": thread_id,
            "Tenant": incident.tenant_id,
            "Decision": "Approved" if approved else "Rejected",
            "Actor": approver,
        },
    )

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

    tenant_id = payload.get("tenant_id") or action.get("tenant_id")
    if tenant_id:
        ensure_incident_tenant(thread_id, str(tenant_id))

    result = await run_in_threadpool(
        resume_incident,
        thread_id=thread_id,
        approved=action.get("action_id") == "approve",
        approver=(payload.get("user") or {}).get("name", "slack"),
    )
    return result

@router.get("/me")
async def me(principal: Principal = Depends(get_principal)) -> dict:
    require_role(principal, "viewer", "responder", "approver", "admin")
    return principal.model_dump()

@router.get("/{thread_id}")
async def pending(
    thread_id: str,
    principal: Principal = Depends(get_principal),
) -> dict:
    require_role(principal, "viewer", "responder", "approver", "admin")
    ensure_incident_tenant(thread_id, principal.tenant_id)
    return {
        "thread_id": thread_id,
        "pending": await run_in_threadpool(is_pending, thread_id=thread_id),
    }

@router.post("/{thread_id}")
async def decide(
    thread_id: str,
    body: ApprovalDecision,
    principal: Principal = Depends(get_principal),
) -> dict:
    require_role(principal, "approver", "admin")
    ensure_incident_tenant(thread_id, principal.tenant_id)
    result = await run_in_threadpool(
        resume_incident, thread_id=thread_id, approved=body.approved, approver=body.approver
    )
    if result["status"] == "no_pending":
        raise HTTPException(status_code=409, detail="no pending approval")
    return result
