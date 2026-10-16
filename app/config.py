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

    # LLM / Ollama
    ollama_model: str = Field(default="llama3.2")
    ollama_base_url: str = Field(default="http://localhost:11434")
    llm_temperature: float = Field(default=0.0)

    # Graph tuning
    max_loops: int = Field(default=3)
    confidence_threshold: int = Field(default=70)
    web_max_results: int = Field(default=5)

    # Execution and safety
    dry_run: bool = Field(default=True)
    auto_approve: bool = Field(default=False)
    checkpoint_db: str = Field(default="opsflow.sqlite")

    # Phase 2: API service
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    # Phase 2: PostgreSQL (durable state and audit)
    database_url: str = Field(
        default="postgresql+psycopg://opsflow:opsflow@localhost:5432/opsflow"
    )

    # Phase 2: Redis (queue, rate limiting, caching)
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Phase 2: Checkpointer backend.
    # "memory" preserves Phase 1 behavior; "postgres" enables durable checkpoints.
    checkpointer: Literal["memory", "postgres"] = Field(default="memory")

    # Phase 2: Webhook security
    webhook_secret: str = Field(default="dev-secret-change-me")

    # Phase 2: Alert ingestion
    alert_rate_limit_per_minute: int = Field(default=50)
    alert_rate_limit_window_seconds: int = Field(default=60)
    alert_dedupe_window_seconds: int = Field(default=300)

    # Phase 2: Severity classification (rules always run; LLM refines when enabled)
    severity_use_llm: bool = Field(default=False)

    # Phase 2: Knowledge base (multi-tenant RAG)
    kb_backend: Literal["none", "tenant_http", "fake"] = Field(default="none")
    kb_fallback_enabled: bool = Field(default=True)
    kb_namespace_prefix: str = Field(default="tenant_")
    kb_timeout_seconds: float = Field(default=5.0)
    tenant_kb_base_url: str = Field(default="http://localhost:9200")
    tenant_kb_api_key: str = Field(default="")
    live_connector_base_url: str = Field(default="")
    live_connector_api_key: str = Field(default="")

    # Phase 2: History-aware proposal (prefer a proven fix above this success rate)
    history_preference_threshold: float = Field(default=0.7)

    # Phase 2: Sandbox execution (safe apply + validation)
    sandbox_backend: Literal["docker", "local", "fake"] = Field(default="docker")
    sandbox_image: str = Field(default="alpine:3.20")
    sandbox_timeout_seconds: int = Field(default=30)
    sandbox_memory_limit: str = Field(default="256m")
    sandbox_cpus: str = Field(default="0.5")
    sandbox_network: bool = Field(default=False)
    sandbox_max_attempts: int = Field(default=2)

    # Phase 2: Public base URL (for approval links)
    public_base_url: str = Field(default="http://localhost:8000")

    # Phase 2: Notifications
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

    # Phase 2: Escalation (minutes after the approval request)
    escalation_minutes: str = Field(default="15,30,60")

    # Phase 2: Per-tenant API keys ("tenant:key,tenant2:key2"; empty disables auth)
    tenant_api_keys: str = Field(default="")

    # Phase 2: Canary deployment
    canary_backend: Literal["simulated", "argo"] = Field(default="simulated")
    canary_steps: str = Field(default="10,25,50,100")
    canary_error_rate_threshold: float = Field(default=0.05)
    canary_p95_threshold_ms: int = Field(default=500)
    prometheus_url: str = Field(default="")
    argo_namespace: str = Field(default="default")

    # Phase 2: Observability
    otel_enabled: bool = Field(default=False)
    otel_exporter: str = Field(default="memory")
    otel_endpoint: str = Field(default="")

    # Phase 2: Learning
    feedback_horizon_hours: int = Field(default=24)

    # Phase 2: Evals
    evals_path: str = Field(default="evals/dataset.jsonl")


settings = Settings()
