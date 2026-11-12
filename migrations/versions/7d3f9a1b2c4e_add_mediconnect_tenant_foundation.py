"""Add tenant, user, rulebook, chunk, and audit tables for the MediConnect pilot.

Revision ID: 7d3f9a1b2c4e
Revises: 061f6dbf4e84
Create Date: 2026-10-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "7d3f9a1b2c4e"
down_revision: Union[str, Sequence[str], None] = "061f6dbf4e84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "settings",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "users",
        sa.Column("user_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column(
            "role",
            sa.String(length=32),
            nullable=False,
            server_default="developer",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"], unique=False)

    op.create_table(
        "rulebooks",
        sa.Column("rulebook_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by", sa.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.user_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("rulebook_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "title",
            "version",
            name="uq_rulebooks_tenant_title_version",
        ),
    )
    op.create_index("ix_rulebooks_tenant_id", "rulebooks", ["tenant_id"], unique=False)

    op.create_table(
        "rulebook_chunks",
        sa.Column("chunk_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("rulebook_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["rulebook_id"], ["rulebooks.rulebook_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
        sa.UniqueConstraint(
            "rulebook_id", "chunk_index", name="uq_rulebook_chunks_index"
        ),
    )
    op.create_index(
        "ix_rulebook_chunks_rulebook_id",
        "rulebook_chunks",
        ["rulebook_id"],
        unique=False,
    )
    op.create_index(
        "ix_rulebook_chunks_tenant_id",
        "rulebook_chunks",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_rulebook_chunks_embedding_hnsw",
        "rulebook_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "audit_logs",
        sa.Column("log_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("incident_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column(
            "details",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.incident_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("log_id"),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"], unique=False)
    op.create_index(
        "ix_audit_logs_incident_id", "audit_logs", ["incident_id"], unique=False
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)

    op.add_column(
        "fix_outcomes",
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
    )
    op.execute(
        """
        UPDATE fix_outcomes AS f
        SET tenant_id = i.tenant_id
        FROM incidents AS i
        JOIN tenants AS t ON t.tenant_id = i.tenant_id
        WHERE f.incident_id = i.incident_id
          AND f.tenant_id IS NULL
        """
    )
    op.create_index(
        "ix_fix_outcomes_tenant_id", "fix_outcomes", ["tenant_id"], unique=False
    )

def downgrade() -> None:
    op.drop_index("ix_fix_outcomes_tenant_id", table_name="fix_outcomes")
    op.drop_column("fix_outcomes", "tenant_id")

    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_incident_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index(
        "ix_rulebook_chunks_embedding_hnsw", table_name="rulebook_chunks"
    )
    op.drop_index("ix_rulebook_chunks_tenant_id", table_name="rulebook_chunks")
    op.drop_index("ix_rulebook_chunks_rulebook_id", table_name="rulebook_chunks")
    op.drop_table("rulebook_chunks")

    op.drop_index("ix_rulebooks_tenant_id", table_name="rulebooks")
    op.drop_table("rulebooks")

    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")

    op.drop_table("tenants")
