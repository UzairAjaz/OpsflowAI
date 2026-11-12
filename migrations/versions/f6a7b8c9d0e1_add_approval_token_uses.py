"""Add one-time approval token use tracking.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "approval_token_uses",
        sa.Column("token_id", sa.String(length=64), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("used_by", sa.String(length=255), nullable=False),
        sa.Column(
            "used_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("token_id"),
    )
    op.create_index(
        "ix_approval_token_uses_thread_id",
        "approval_token_uses",
        ["thread_id"],
        unique=False,
    )
    op.create_index(
        "ix_approval_token_uses_tenant_id",
        "approval_token_uses",
        ["tenant_id"],
        unique=False,
    )

def downgrade() -> None:
    op.drop_index("ix_approval_token_uses_tenant_id", table_name="approval_token_uses")
    op.drop_index("ix_approval_token_uses_thread_id", table_name="approval_token_uses")
    op.drop_table("approval_token_uses")
