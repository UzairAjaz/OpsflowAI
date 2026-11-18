from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CodeAlertMessage(BaseModel):
    """Contract produced by the CloudWatch -> Lambda -> SQS pipeline."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str = "1.0"
    source: str = "cloudwatch"
    tenant_id: str = "retriva"
    service: str
    environment: str = "local"
    log_group: str = ""
    log_stream: str = ""
    event_id: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    commit_sha: str = ""
    level: str = "ERROR"
    status_code: int = 0
    error_class: str = ""
    message: str = ""
    stack_trace: str = ""
    file: str = ""
    line: int = 0
    trace_id: str = ""
    request_id: str = ""
    fingerprint: str = ""
    dedupe_key: str = ""
    analysis_only: bool = False

    @model_validator(mode="after")
    def _fill_derived_fields(self) -> "CodeAlertMessage":
        if not self.fingerprint:
            self.fingerprint = (
                f"{self.service}|{self.error_class}|{self.file}|{self.line}"
            )
        if not self.dedupe_key:
            identity = "|".join(
                [
                    self.tenant_id,
                    self.service,
                    self.commit_sha,
                    self.error_class,
                    self.file,
                    str(self.line),
                    self.message,
                ]
            )
            self.dedupe_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return self

    @property
    def severity(self) -> str:
        level = self.level.upper()
        if level in {"CRITICAL", "FATAL"}:
            return "critical"
        if level in {"ERROR", "EXCEPTION"}:
            return "high"
        return "info"

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
