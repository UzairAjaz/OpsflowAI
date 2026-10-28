from __future__ import annotations

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_model: str = Field(default="qwen2.5:3b")
    ollama_base_url: str = Field(default="http://localhost:11434")
    llm_temperature: float = Field(default=0.0)

    max_loops: int = Field(default=3)
    confidence_threshold: int = Field(default=70)
    web_max_results: int = Field(default=5)

    dry_run: bool = Field(default=True)
    auto_approve: bool = Field(default=False)
    checkpoint_db: str = Field(default="opsflow.sqlite")

    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    database_url: str = Field(
        default="postgresql+psycopg://opsflow:opsflow@localhost:5432/opsflow"
    )

    redis_url: str = Field(default="redis://localhost:6379/0")

    checkpointer: Literal["memory", "postgres"] = Field(default="memory")

    webhook_secret: str = Field(default="dev-secret-change-me")

    alert_rate_limit_per_minute: int = Field(default=50)
    alert_rate_limit_window_seconds: int = Field(default=60)
    alert_dedupe_window_seconds: int = Field(default=300)

    severity_use_llm: bool = Field(default=False)

    kb_backend: Literal["none", "tenant_http", "fake"] = Field(default="none")
    kb_fallback_enabled: bool = Field(default=True)
    kb_namespace_prefix: str = Field(default="tenant_")
    kb_timeout_seconds: float = Field(default=5.0)
    tenant_kb_base_url: str = Field(default="http://localhost:9200")
    tenant_kb_api_key: str = Field(default="")
    live_connector_base_url: str = Field(default="")
    live_connector_api_key: str = Field(default="")

    history_preference_threshold: float = Field(default=0.7)

    sandbox_backend: Literal["docker", "local", "fake"] = Field(default="docker")
    sandbox_image: str = Field(default="alpine:3.20")
    sandbox_timeout_seconds: int = Field(default=30)
    sandbox_memory_limit: str = Field(default="256m")
    sandbox_cpus: str = Field(default="0.5")
    sandbox_network: bool = Field(default=False)
    sandbox_max_attempts: int = Field(default=2)

    public_base_url: str = Field(default="http://localhost:8000")

    slack_webhook_url: str = Field(default="")
    slack_signing_secret: str = Field(default="")
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from: str = Field(default="opsflow@example.com")
    smtp_to: str = Field(default="oncall@example.com")
    twilio_account_sid: str = Field(default="")
    twilio_auth_token: str = Field(default="")
    twilio_from: str = Field(default="")
    twilio_to: str = Field(default="")
    pagerduty_routing_key: str = Field(default="")
    approval_token_secret: str = Field(default="dev-approval-secret")
    approval_token_ttl_minutes: int = Field(default=120)

    escalation_minutes: str = Field(default="15,30,60")

    tenant_api_keys: str = Field(default="")

    canary_backend: Literal["simulated", "argo"] = Field(default="simulated")
    canary_steps: str = Field(default="10,25,50,100")
    canary_error_rate_threshold: float = Field(default=0.05)
    canary_p95_threshold_ms: int = Field(default=500)
    prometheus_url: str = Field(default="")
    argo_namespace: str = Field(default="default")

    otel_enabled: bool = Field(default=False)
    otel_exporter: str = Field(default="memory")
    otel_endpoint: str = Field(default="")

    feedback_horizon_hours: int = Field(default=24)

    evals_path: str = Field(default="evals/dataset.jsonl")

    worker_job_timeout_seconds: int = Field(default=1800)

settings = Settings()
