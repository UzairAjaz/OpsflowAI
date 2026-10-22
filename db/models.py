from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

class ProcessedAlert(Base):

    __tablename__ = "processed_alerts"

    alerts_signature: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    service: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="default", index=True
    )
    error_class: Mapped[str | None] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(16), nullable=False, server_default="info")
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.incident_id"), nullable=True
    )

class Incident(Base):

    __tablename__ = "incidents"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    service: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="default", index=True
    )
    error_class: Mapped[str | None] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    approval_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_level: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_incidents_service_error_class", "service", "error_class"),
        Index("ix_incidents_status", "status"),
    )

class ExecutionLog(Base):

    __tablename__ = "execution_logs"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.incident_id"), nullable=True
    )
    remediation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    command: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    environment: Mapped[str] = mapped_column(String(32), nullable=False, default="sandbox")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str | None] = mapped_column(String(32))
    sandbox_checks: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_execution_logs_incident_id", "incident_id"),)

class FixOutcome(Base):

    __tablename__ = "fix_outcomes"

    outcome_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.incident_id"), nullable=True
    )
    remediation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    confidence: Mapped[int | None] = mapped_column(Integer)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stable: Mapped[bool | None] = mapped_column(Boolean)
    success_rate_before: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        Index("ix_fix_outcomes_incident_id", "incident_id"),
        Index("ix_fix_outcomes_remediation_id", "remediation_id"),
    )
