from __future__ import annotations

from ingestion.code_alert_schema import CodeAlertMessage
from ingestion.code_alerts import normalize_repo_path


def main() -> None:
    windows_path = r"C:\Users\RQ\Documents\Retriva-AI\api_server.py"
    normalized = normalize_repo_path(
        windows_path,
        r"C:\Users\RQ\Documents\Retriva-AI",
    )
    assert normalized == "api_server.py", normalized
    print("path      ->", normalized)

    already_relative = normalize_repo_path(
        "app/main.py",
        r"C:\Users\RQ\Documents\Retriva-AI",
    )
    assert already_relative == "app/main.py", already_relative
    print("relative  ->", already_relative)

    alert = CodeAlertMessage(
        service="retriva-api",
        tenant_id="retriva",
        error_class="KeyError",
        message="boom",
        file=windows_path,
        line=534,
        commit_sha="c736b10",
    )
    assert len(alert.dedupe_key) == 64
    assert alert.severity == "high"
    print("dedupe    ->", alert.dedupe_key[:12], "...")
    print("[ok] Phase 2A alert normalization working.")


if __name__ == "__main__":
    main()
