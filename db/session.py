"""Database engine and session management.

The URL comes from settings.database_url, which uses the psycopg v3 driver
(postgresql+psycopg). Alembic and background workers use the synchronous engine.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine: Engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
