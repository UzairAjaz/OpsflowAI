from __future__ import annotations

from app.code_fix.kill_switch import (
    CodeFixDisabled,
    code_fix_status,
    is_analysis_only,
    is_code_fix_enabled,
    require_code_fix_enabled,
)
from app.config import settings


def main() -> None:
    original_enabled = settings.code_fix_enabled
    original_analysis = settings.code_fix_analysis_only
    tenant_on = {"code_fix": {"enabled": True}}

    try:
        settings.code_fix_enabled = False
        settings.code_fix_analysis_only = True

        assert is_code_fix_enabled(tenant_on) is False
        try:
            require_code_fix_enabled(tenant_on)
        except CodeFixDisabled:
            pass
        else:
            raise AssertionError("global kill switch did not block the fix")
        print("global off -> blocked")

        settings.code_fix_enabled = True
        assert is_code_fix_enabled(tenant_on) is True
        assert is_code_fix_enabled({"code_fix": {"enabled": False}}) is False
        assert is_code_fix_enabled(None) is False
        assert is_analysis_only() is True
        require_code_fix_enabled(tenant_on)

        status = code_fix_status(tenant_on)
        assert status["global_enabled"] is True
        assert status["tenant_enabled"] is True
        assert status["enabled"] is True
        assert status["analysis_only"] is True
        print("tenant on + analysis_only -> allowed (report only)")

        print("[ok] code-fix kill switch and tenant gate working.")
    finally:
        settings.code_fix_enabled = original_enabled
        settings.code_fix_analysis_only = original_analysis


if __name__ == "__main__":
    main()
