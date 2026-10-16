from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.catalog import Catalog, RemediationSpec
from app.state import Remediation

_INT = re.compile(r"^-?\d+$")
_BOOL = {"true", "false"}
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

class ValidationResult(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    resolved: dict[str, str] = Field(default_factory=dict)

def validate_proposal(catalog: Catalog, remediation: Remediation | None) -> ValidationResult:
    if remediation is None:
        return ValidationResult(ok=False, errors=["no remediation proposed"], resolved={})

    spec = catalog.get(remediation.remediation_id)
    if spec is None:
        return ValidationResult(
            ok=False,
            errors=[
                f"unknown remediation id '{remediation.remediation_id}'. "
                f"allowed: {', '.join(catalog.ids)}"
            ],
            resolved={},
        )

    errors: list[str] = []
    resolved: dict[str, str] = {}
    provided = remediation.params or {}

    for key in provided:
        if key not in spec.params:
            errors.append(f"unexpected param '{key}'")

    for name, ps in spec.params.items():
        if name not in provided:
            if ps.required:
                errors.append(f"missing required param '{name}'")
            continue

        value = str(provided[name])

        if ps.type == "int" and not _INT.match(value):
            errors.append(f"param '{name}' must be an integer, got '{value}'")
        if ps.type == "bool" and value.lower() not in _BOOL:
            errors.append(f"param '{name}' must be true/false, got '{value}'")

        allowed = catalog.allowed_values(spec, name)
        if allowed is not None and value not in allowed:
            errors.append(f"param '{name}'='{value}' not allowed (allowed: {allowed})")

        if ps.pattern and not re.fullmatch(ps.pattern, value):
            errors.append(f"param '{name}'='{value}' does not match pattern {ps.pattern}")

        resolved[name] = value

    return ValidationResult(ok=not errors, errors=errors, resolved=resolved)

def build_argv(template: list[str], resolved: dict[str, str]) -> list[str]:
    def repl(match: re.Match[str]) -> str:
        return resolved[match.group(1)]

    return [_PLACEHOLDER.sub(repl, token) for token in template]

def build_command(spec: RemediationSpec, resolved: dict[str, str]) -> list[str]:
    return build_argv(spec.command_template, resolved)
