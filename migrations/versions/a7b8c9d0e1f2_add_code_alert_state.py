"""Add code-alert incident state and repository mappings.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repository_mappings",
        sa.Column("mapping_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("service", sa.String(length=128), nullable=False),
        sa.Column("repo_full_name", sa.String(length=255), nullable=False),
        sa.Column("repo_path", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("local_repo_root", sa.String(length=512), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=False, server_default="python"),
        sa.Column("base_branch", sa.String(length=64), nullable=False, server_default="main"),
        sa.Column("log_group", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("mapping_id"),
        sa.UniqueConstraint(
            "tenant_id", "service", name="uq_repository_mappings_tenant_service"
        ),
    )
    op.create_index(
        "ix_repository_mappings_tenant_id", "repository_mappings", ["tenant_id"]
    )
    op.create_index(
        "ix_repository_mappings_service", "repository_mappings", ["service"]
    )

    op.add_column("incidents", sa.Column("environment", sa.String(length=32), nullable=True))
    op.add_column("incidents", sa.Column("commit_sha", sa.String(length=40), nullable=True))
    op.add_column("incidents", sa.Column("log_group", sa.String(length=255), nullable=True))
    op.add_column("incidents", sa.Column("log_stream", sa.String(length=255), nullable=True))
    op.add_column("incidents", sa.Column("trace_id", sa.String(length=128), nullable=True))
    op.add_column("incidents", sa.Column("request_id", sa.String(length=128), nullable=True))
    op.add_column("incidents", sa.Column("file_path", sa.String(length=512), nullable=True))
    op.add_column("incidents", sa.Column("line_number", sa.Integer(), nullable=True))
    op.add_column(
        "incidents",
        sa.Column(
            "analysis_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("incidents", sa.Column("error_fingerprint", sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("dedupe_key", sa.String(length=64), nullable=True))
    op.add_column(
        "incidents", sa.Column("repository_mapping_id", sa.UUID(as_uuid=True), nullable=True)
    )
    op.create_index("ix_incidents_dedupe_key", "incidents", ["dedupe_key"])
    op.create_foreign_key(
        "incidents_repository_mapping_id_fkey",
        "incidents",
        "repository_mappings",
        ["repository_mapping_id"],
        ["mapping_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "incidents_repository_mapping_id_fkey", "incidents", type_="foreignkey"
    )
    op.drop_index("ix_incidents_dedupe_key", table_name="incidents")
    for column in (
        "repository_mapping_id",
        "dedupe_key",
        "error_fingerprint",
        "analysis_only",
        "line_number",
        "file_path",
        "request_id",
        "trace_id",
        "log_stream",
        "log_group",
        "commit_sha",
        "environment",
    ):
        op.drop_column("incidents", column)
    op.drop_index("ix_repository_mappings_service", table_name="repository_mappings")
    op.drop_index("ix_repository_mappings_tenant_id", table_name="repository_mappings")
    op.drop_table("repository_mappings")
