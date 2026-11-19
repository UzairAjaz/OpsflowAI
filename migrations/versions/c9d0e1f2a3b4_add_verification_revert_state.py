"""Add post-merge verification and revert PR state.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("fix_commit_sha", sa.String(length=40), nullable=True))
    op.add_column(
        "incidents", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("incidents", sa.Column("merge_commit_sha", sa.String(length=40), nullable=True))
    op.add_column(
        "incidents", sa.Column("verification_status", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "incidents",
        sa.Column("verification_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column("verification_deadline", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("incidents", sa.Column("revert_pr_number", sa.Integer(), nullable=True))
    op.add_column("incidents", sa.Column("revert_pr_url", sa.String(length=512), nullable=True))
    op.add_column("incidents", sa.Column("revert_status", sa.String(length=32), nullable=True))


def downgrade() -> None:
    for column in (
        "revert_status",
        "revert_pr_url",
        "revert_pr_number",
        "verification_deadline",
        "verification_started_at",
        "verification_status",
        "merge_commit_sha",
        "merged_at",
        "fix_commit_sha",
    ):
        op.drop_column("incidents", column)
