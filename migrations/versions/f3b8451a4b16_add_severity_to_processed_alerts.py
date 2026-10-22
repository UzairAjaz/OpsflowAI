from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f3b8451a4b16"
down_revision: Union[str, Sequence[str], None] = "c6af597d7897"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column(
        "processed_alerts",
        sa.Column("severity", sa.String(length=16), server_default="info", nullable=False),
    )

def downgrade() -> None:
    op.drop_column("processed_alerts", "severity")
