from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

CATALOG_PATH = Path(__file__).resolve().parent / "remediations.yaml"

class ParamSpec(BaseModel):
    type: Literal["string", "int", "bool"] = "string"
    required: bool = True
    enum: list[str] | None = None
    enum_from: str | None = None
    pattern: str | None = None

class RemediationSpec(BaseModel):
    id: str
    description: str
    risk: Literal["safe", "medium", "high"]
    reversible: bool
    command_template: list[str]
    params: dict[str, ParamSpec] = Field(default_factory=dict)
    validation_commands: list[list[str]] = Field(default_factory=list)
    rollback_template: list[str] | None = None

class Catalog(BaseModel):
    allowlists: dict[str, list[str]] = Field(default_factory=dict)
    remediations: list[RemediationSpec] = Field(default_factory=list)

    def get(self, remediation_id: str) -> RemediationSpec | None:
        for spec in self.remediations:
            if spec.id == remediation_id:
                return spec
        return None

    @property
    def ids(self) -> list[str]:
        return [s.id for s in self.remediations]

    def allowed_values(self, spec: RemediationSpec, param: str) -> list[str] | None:

        ps = spec.params.get(param)
        if ps is None:
            return None
        if ps.enum is not None:
            return ps.enum
        if ps.enum_from is not None:
            return self.allowlists.get(ps.enum_from)
        return None

    def describe(self) -> str:

        lines: list[str] = []
        for s in self.remediations:
            params = ", ".join(s.params.keys()) or "(none)"
            lines.append(
                f"- {s.id}: {s.description} "
                f"[risk={s.risk}, reversible={s.reversible}, params: {params}]"
            )
        return "\n".join(lines)

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

def _validate_catalog(catalog: Catalog) -> None:

    seen: set[str] = set()
    for spec in catalog.remediations:
        if spec.id in seen:
            raise ValueError(f"duplicate remediation id: {spec.id}")
        seen.add(spec.id)

        placeholders: set[str] = set()
        for token in spec.command_template:
            placeholders.update(_PLACEHOLDER.findall(token))
        for check in spec.validation_commands:
            for token in check:
                placeholders.update(_PLACEHOLDER.findall(token))
        if spec.rollback_template:
            for token in spec.rollback_template:
                placeholders.update(_PLACEHOLDER.findall(token))
        declared = set(spec.params.keys())

        unknown = placeholders - declared
        if unknown:
            raise ValueError(f"{spec.id}: template uses undeclared param(s): {unknown}")

        for name, ps in spec.params.items():
            if ps.enum_from and ps.enum_from not in catalog.allowlists:
                raise ValueError(f"{spec.id}.{name}: enum_from '{ps.enum_from}' not in allowlists")
            if ps.required and name not in placeholders:
                raise ValueError(f"{spec.id}.{name}: required but not used in command_template")

@lru_cache
def load_catalog(path: str | None = None) -> Catalog:
    p = Path(path) if path else CATALOG_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    catalog = Catalog.model_validate(data)
    _validate_catalog(catalog)
    return catalog
