"""Add code-fix branch/PR/CI state to incidents.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("stack_trace", sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("fix_status", sa.String(length=32), nullable=True))
    op.add_column("incidents", sa.Column("fix_error", sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("branch_name", sa.String(length=255), nullable=True))
    op.add_column("incidents", sa.Column("pr_number", sa.Integer(), nullable=True))
    op.add_column("incidents", sa.Column("pr_url", sa.String(length=512), nullable=True))
    op.add_column("incidents", sa.Column("pr_state", sa.String(length=32), nullable=True))
    op.add_column("incidents", sa.Column("patch_diff", sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("model_name", sa.String(length=128), nullable=True))
    op.add_column("incidents", sa.Column("ci_status", sa.String(length=32), nullable=True))


def downgrade() -> None:
    for column in (
        "ci_status",
        "model_name",
        "patch_diff",
        "pr_state",
        "pr_url",
        "pr_number",
        "branch_name",
        "fix_error",
        "fix_status",
        "stack_trace",
        "error_message",
    ):
        op.drop_column("incidents", column)
