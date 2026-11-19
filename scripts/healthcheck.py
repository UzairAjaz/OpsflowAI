"""Phase 3 connectivity healthcheck: Postgres, SQS, Ollama, GitHub App."""

from __future__ import annotations

import sys

import boto3
import httpx
from sqlalchemy import text

from app.config import settings
from db.session import engine
from integrations.github_app import GitHubAppClient


def check_postgres() -> str:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return "ok"


def check_sqs() -> str:
    if not settings.sqs_alert_queue_url:
        raise RuntimeError("SQS_ALERT_QUEUE_URL is empty")
    session = boto3.Session(
        profile_name=settings.aws_profile or None,
        region_name=settings.aws_region,
    )
    client = session.client("sqs")
    response = client.get_queue_attributes(
        QueueUrl=settings.sqs_alert_queue_url,
        AttributeNames=["QueueArn", "ApproximateNumberOfMessages"],
    )
    attrs = response["Attributes"]
    return f"ok (messages={attrs.get('ApproximateNumberOfMessages', '?')})"


def check_ollama() -> str:
    response = httpx.get(
        f"{settings.ollama_base_url.rstrip('/')}/api/tags",
        timeout=10,
    )
    response.raise_for_status()
    names = [item.get("name", "") for item in response.json().get("models", [])]
    if not any(name.startswith(settings.ollama_code_model) for name in names):
        raise RuntimeError(f"model {settings.ollama_code_model} not installed")
    return f"ok ({settings.ollama_code_model})"


def check_github() -> str:
    client = GitHubAppClient(
        app_id=settings.github_app_id,
        installation_id=settings.github_installation_id,
        private_key_path=settings.github_app_private_key_path,
        repo=settings.github_repo,
        base_branch=settings.github_base_branch,
        api_url=settings.github_api_url,
    )
    commit = client.get_commit(settings.github_base_branch)
    return f"ok ({settings.github_repo} @ {commit['sha'][:12]})"


def check_gmail() -> str:
    if not settings.smtp_email or not settings.smtp_app_password:
        return "warning (SMTP_EMAIL/SMTP_APP_PASSWORD not configured)"
    return "configured"


def main() -> None:
    checks = [
        ("Postgres", check_postgres),
        ("SQS", check_sqs),
        ("Ollama", check_ollama),
        ("GitHub App", check_github),
        ("Gmail SMTP", check_gmail),
    ]
    failed = False
    for name, check in checks:
        try:
            result = check()
            print(f"[PASS] {name}: {result}")
            if name == "Gmail SMTP" and result.startswith("warning"):
                print("       Set SMTP_EMAIL and SMTP_APP_PASSWORD to test real email.")
        except Exception as exc:
            failed = True
            print(f"[FAIL] {name}: {exc}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
