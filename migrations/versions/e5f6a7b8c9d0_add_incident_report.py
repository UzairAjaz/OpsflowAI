"""Add structured report fields to incidents.

Revision ID: e5f6a7b8c9d0
Revises: 7d3f9a1b2c4e
Create Date: 2026-10-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "7d3f9a1b2c4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("incidents", sa.Column("report", sa.Text(), nullable=True))
    op.add_column(
        "incidents",
        sa.Column("report_generated_at", sa.DateTime(timezone=True), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("incidents", "report_generated_at")
    op.drop_column("incidents", "report")
