from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '061f6dbf4e84'
down_revision: Union[str, Sequence[str], None] = '2f44a5eb54ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:

    op.add_column('incidents', sa.Column('approval_requested_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('incidents', sa.Column('escalated_level', sa.Integer(), server_default='0', nullable=False))

def downgrade() -> None:

    op.drop_column('incidents', 'escalated_level')
    op.drop_column('incidents', 'approval_requested_at')
