from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.config import settings
from app.state import (
    AuditEvent,
    Diagnosis,
    ExecutionResult,
    Remediation,
    ResearchResult,
)

ALLOWED_CHECKPOINT_TYPES = [
    AuditEvent,
    Diagnosis,
    ExecutionResult,
    Remediation,
    ResearchResult,
]

def _serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_CHECKPOINT_TYPES)

def _postgres_conn_string() -> str:

    return settings.database_url.replace("postgresql+psycopg://", "postgresql://")

def _make_memory() -> InMemorySaver:
    return InMemorySaver(serde=_serde())

def _make_postgres() -> BaseCheckpointSaver:
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    connection = psycopg.connect(_postgres_conn_string(), autocommit=True)
    saver = PostgresSaver(connection, serde=_serde())
    saver.setup()
    return saver

def make_checkpointer(backend: str | None = None) -> BaseCheckpointSaver:

    selected = backend or settings.checkpointer
    if selected == "postgres":
        return _make_postgres()
    return _make_memory()
