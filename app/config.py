from __future__ import annotations

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "staging", "production"] = Field(default="local")
    app_name: str = Field(default="OpsFlow AI API")
    app_version: str = Field(default="0.1.0")
    service_name: str = Field(default="opsflow-api")
    log_level: str = Field(default="INFO")

    ollama_model: str = Field(default="qwen2.5:3b")
    ollama_base_url: str = Field(default="http://localhost:11434")
    llm_temperature: float = Field(default=0.0)

    embedding_backend: Literal["ollama", "fake"] = Field(default="ollama")
    embedding_model: str = Field(default="nomic-embed-text")
    embedding_dimensions: int = Field(default=768)
    embedding_chunk_size: int = Field(default=800)
    embedding_chunk_overlap: int = Field(default=100)

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

    queue_name: str = Field(default="incidents")
    queue_result_ttl_seconds: int = Field(default=300)
    queue_failure_ttl_seconds: int = Field(default=300)
    reports_dir: str = Field(default="reports")
    deploy_k8s_dir: str = Field(default="deploy/k8s")

    webhook_secret: str = Field(default="dev-secret-change-me")
    webhook_signature_header: str = Field(default="X-Signature")

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
    tenant_kb_search_path: str = Field(default="/v1/search")
    live_connector_base_url: str = Field(default="")
    live_connector_api_key: str = Field(default="")
    live_connector_search_path: str = Field(default="/v1/search")
    rulebook_retrieval_enabled: bool = Field(default=True)

    history_preference_threshold: float = Field(default=0.7)

    sandbox_backend: Literal["docker", "local", "fake"] = Field(default="docker")
    sandbox_image: str = Field(default="alpine:3.20")
    sandbox_timeout_seconds: int = Field(default=30)
    sandbox_memory_limit: str = Field(default="256m")
    sandbox_cpus: str = Field(default="0.5")
    sandbox_network: bool = Field(default=False)
    sandbox_max_attempts: int = Field(default=2)
    default_memory_limit: str = Field(default="2Gi")

    public_base_url: str = Field(default="http://localhost:8000")
    alert_webhook_url: str = Field(default="")
    alert_webhook_path: str = Field(default="/api/v1/webhooks/alert")

    slack_webhook_url: str = Field(default="")
    slack_signing_secret: str = Field(default="")
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_use_ssl: bool = Field(default=False)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from: str = Field(default="opsflow@example.com")
    smtp_to: str = Field(default="oncall@example.com")
    twilio_account_sid: str = Field(default="")
    twilio_auth_token: str = Field(default="")
    twilio_from: str = Field(default="")
    twilio_to: str = Field(default="")
    pagerduty_routing_key: str = Field(default="")
    notification_timeout_seconds: float = Field(default=10.0)
    twilio_api_base_url: str = Field(default="https://api.twilio.com")
    approval_token_secret: str = Field(default="dev-approval-secret")
    approval_token_ttl_minutes: int = Field(default=120)

    escalation_minutes: str = Field(default="15,30,60")
    escalation_recipients: str = Field(default="manager,senior_manager,cto")

    tenant_api_keys: str = Field(default="")
    auth_dev_mode: bool = Field(default=False)
    dev_tenant_id: str = Field(default="mediconnect")
    auth_jwt_secret: str = Field(default="opsflow-dev-jwt-secret-change-me-please")
    auth_jwt_algorithm: Literal["HS256", "HS384", "HS512"] = Field(default="HS256")
    auth_token_ttl_minutes: int = Field(default=60)

    demo_tenant_id: str = Field(default="mediconnect")
    demo_tenant_name: str = Field(default="MediConnect")
    demo_service: str = Field(default="mediconnect-backend")
    demo_error_class: str = Field(default="OOMKilled")
    demo_email: str = Field(default="admin@mediconnect.local")
    demo_approver: str = Field(default="demo-cli")
    cli_approver: str = Field(default="cli-user")

    canary_backend: Literal["simulated", "argo"] = Field(default="simulated")
    canary_steps: str = Field(default="10,25,50,100")
    canary_error_rate_threshold: float = Field(default=0.05)
    canary_p95_threshold_ms: int = Field(default=500)
    prometheus_url: str = Field(default="")
    argo_namespace: str = Field(default="default")
    argo_prometheus_address: str = Field(default="http://prometheus.monitoring:9090")

    otel_enabled: bool = Field(default=False)
    otel_exporter: str = Field(default="memory")
    otel_endpoint: str = Field(default="")
    otel_service_name: str = Field(default="opsflow-ai")

    feedback_horizon_hours: int = Field(default=24)

    evals_path: str = Field(default="evals/dataset.jsonl")

    worker_job_timeout_seconds: int = Field(default=1800)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def webhook_alert_url(self) -> str:
        """Full alert webhook URL; explicit override wins over PUBLIC_BASE_URL."""
        if self.alert_webhook_url:
            return self.alert_webhook_url
        return f"{self.public_base_url.rstrip('/')}{self.alert_webhook_path}"

    @model_validator(mode="after")
    def _validate_production_settings(self):
        if self.environment != "production":
            return self

        problems: list[str] = []
        if self.auth_dev_mode:
            problems.append("AUTH_DEV_MODE must be false")
        if self.webhook_secret == "dev-secret-change-me":
            problems.append("WEBHOOK_SECRET must be changed")
        if self.approval_token_secret == "dev-approval-secret":
            problems.append("APPROVAL_TOKEN_SECRET must be changed")
        if self.auth_jwt_secret == "opsflow-dev-jwt-secret-change-me-please":
            problems.append("AUTH_JWT_SECRET must be changed")
        if "opsflow:opsflow@" in self.database_url:
            problems.append("DATABASE_URL must not use default demo credentials")
        if problems:
            raise ValueError("production configuration invalid: " + "; ".join(problems))
        return self

settings = Settings()
