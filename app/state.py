from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

class ResearchResult(BaseModel):

    source: Literal["kb", "web", "history"]
    title: str
    url: Optional[str] = None
    snippet: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    is_low_confidence: bool = False

class Diagnosis(BaseModel):

    diagnosis: str
    root_cause: str
    severity: Literal["low", "medium", "high", "critical"]
    evidence: list[str] = Field(default_factory=list)

class Remediation(BaseModel):

    remediation_id: str
    params: dict[str, str] = Field(default_factory=dict)
    rationale: str

class Critique(BaseModel):

    is_valid: bool
    score: int = Field(ge=0, le=100)
    counterarguments: list[str] = Field(default_factory=list)

    suggested_query: Optional[str] = None

class ExecutionResult(BaseModel):

    remediation_id: str
    command: list[str]
    dry_run: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0

class CheckResult(BaseModel):

    command: list[str]
    exit_code: int
    passed: bool
    stdout: str = ""
    stderr: str = ""

class AuditEvent(BaseModel):

    ts: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    actor: Literal["agent", "human", "system"]
    action: str
    detail: str = ""

class OpsFlowState(TypedDict, total=False):

    error_log: str
    redacted_log: str
    redactions: dict[str, int]
    thread_id: str
    tenant_id: str
    service: str
    error_class: str

    diagnosis: str
    root_cause: str
    severity: Literal["low", "medium", "high", "critical"]
    evidence: list[str]

    research: Annotated[list[ResearchResult], operator.add]
    research_query: Optional[str]
    prior_fix: dict

    proposed_remediation: Optional[Remediation]
    proposal_valid: bool
    validation_errors: list[str]
    resolved_params: dict[str, str]
    confidence: int
    confidence_breakdown: dict[str, float]
    manual_review: bool
    automation_eligible: bool

    critique: Optional[str]
    critic_score: int
    loop_count: int

    refined_query: Optional[str]

    risk_level: Literal["safe", "medium", "high"]
    requires_approval: bool
    human_approval: Optional[bool]
    approver: Optional[str]

    execution_result: Optional[ExecutionResult]
    sandbox_result: Optional[ExecutionResult]
    sandbox_checks: dict
    sandbox_attempts: int
    sandbox_feedback: Optional[str]
    rollback_plan: list[str]
    validated: bool
    canary_result: dict
    canary_stages: list[dict]
    status: Literal[
        "pending",
        "awaiting_approval",
        "approved",
        "rejected",
        "completed",
        "failed",
        "escalated",
    ]

    audit: Annotated[list[AuditEvent], operator.add]

    messages: Annotated[list[BaseMessage], add_messages]

def new_incident(
    error_log: str,
    thread_id: str | None = None,
    tenant_id: str = "default",
    service: str = "",
    error_class: str = "",
) -> OpsFlowState:

    import uuid

    return OpsFlowState(
        error_log=error_log,
        thread_id=thread_id or f"inc-{uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id,
        service=service,
        error_class=error_class,
        loop_count=0,
        confidence=0,
        critic_score=0,
        requires_approval=False,
        status="pending",
        research=[],
        audit=[],
        messages=[],
    )
