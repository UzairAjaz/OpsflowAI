from __future__ import annotations

from typing import Any

from app.config import settings


class CodeFixDisabled(RuntimeError):
    """Raised when a code-fix action is attempted while the kill switch is off."""


def tenant_code_fix_enabled(tenant_settings: dict[str, Any] | None) -> bool:
    """Return True only when the tenant explicitly enables code fixes."""
    if not isinstance(tenant_settings, dict):
        return False
    code_fix = tenant_settings.get("code_fix")
    if not isinstance(code_fix, dict):
        return False
    return bool(code_fix.get("enabled", False))


def is_code_fix_enabled(tenant_settings: dict[str, Any] | None) -> bool:
    """Global kill switch AND tenant enablement must both be true."""
    return settings.code_fix_enabled and tenant_code_fix_enabled(tenant_settings)


def is_analysis_only() -> bool:
    """When true, generate reports but never create branches or PRs."""
    return settings.code_fix_analysis_only


def require_code_fix_enabled(tenant_settings: dict[str, Any] | None) -> None:
    if not is_code_fix_enabled(tenant_settings):
        raise CodeFixDisabled(
            "code fix is disabled globally or for this tenant "
            "(CODE_FIX_ENABLED / tenant.settings.code_fix.enabled)"
        )


def code_fix_status(tenant_settings: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "global_enabled": settings.code_fix_enabled,
        "tenant_enabled": tenant_code_fix_enabled(tenant_settings),
        "enabled": is_code_fix_enabled(tenant_settings),
        "analysis_only": is_analysis_only(),
    }


__all__ = [
    "CodeFixDisabled",
    "code_fix_status",
    "is_analysis_only",
    "is_code_fix_enabled",
    "require_code_fix_enabled",
    "tenant_code_fix_enabled",
]
