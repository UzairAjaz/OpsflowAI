from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '2f44a5eb54ce'
down_revision: Union[str, Sequence[str], None] = 'f3b8451a4b16'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:

    op.add_column('incidents', sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False))
    op.create_index(op.f('ix_incidents_tenant_id'), 'incidents', ['tenant_id'], unique=False)
    op.add_column('processed_alerts', sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False))
    op.create_index(op.f('ix_processed_alerts_tenant_id'), 'processed_alerts', ['tenant_id'], unique=False)

def downgrade() -> None:

    op.drop_index(op.f('ix_processed_alerts_tenant_id'), table_name='processed_alerts')
    op.drop_column('processed_alerts', 'tenant_id')
    op.drop_index(op.f('ix_incidents_tenant_id'), table_name='incidents')
    op.drop_column('incidents', 'tenant_id')
