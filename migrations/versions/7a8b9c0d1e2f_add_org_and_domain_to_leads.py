"""Add org_id, domain, and unique constraint to leads

Revision ID: 7a8b9c0d1e2f
Revises: 5c7a1e890123
Create Date: 2026-10-08 16:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a8b9c0d1e2f'
down_revision: Union[str, None] = '5c7a1e890123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use batch_alter_table for compatibility with both SQLite and PostgreSQL
    with op.batch_alter_table('leads') as batch_op:
        batch_op.add_column(sa.Column('org_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('domain', sa.String(length=250), nullable=True))
        batch_op.create_index('ix_leads_org_id', ['org_id'], unique=False)
        batch_op.create_index('ix_leads_domain', ['domain'], unique=False)
        batch_op.create_unique_constraint('uq_leads_org_domain', ['org_id', 'domain'])


def downgrade() -> None:
    with op.batch_alter_table('leads') as batch_op:
        batch_op.drop_constraint('uq_leads_org_domain', type_='unique')
        batch_op.drop_index('ix_leads_domain')
        batch_op.drop_index('ix_leads_org_id')
        batch_op.drop_column('domain')
        batch_op.drop_column('org_id')
