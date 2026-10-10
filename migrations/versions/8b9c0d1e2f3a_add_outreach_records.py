"""Add outreach_records table for owner-governed email and message dispatch

Revision ID: 8b9c0d1e2f3a
Revises: 7a8b9c0d1e2f
Create Date: 2026-10-09 10:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b9c0d1e2f3a'
down_revision: Union[str, None] = '7a8b9c0d1e2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'outreach_records',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=True),
        sa.Column('lead_id', sa.String(length=36), nullable=False),
        sa.Column('task_id', sa.String(length=36), nullable=False),
        sa.Column('recipient_email', sa.String(length=250), nullable=False),
        sa.Column('recipient_name', sa.String(length=250), nullable=True),
        sa.Column('subject', sa.String(length=300), nullable=False),
        sa.Column('body_text', sa.Text(), nullable=False),
        sa.Column('channel', sa.String(length=32), nullable=False, server_default='email'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='PENDING_APPROVAL'),
        sa.Column('approval_id', sa.String(length=36), nullable=True),
        sa.Column('idempotency_key', sa.String(length=200), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_outreach_records_org_id'), 'outreach_records', ['org_id'], unique=False)
    op.create_index(op.f('ix_outreach_records_lead_id'), 'outreach_records', ['lead_id'], unique=False)
    op.create_index(op.f('ix_outreach_records_task_id'), 'outreach_records', ['task_id'], unique=False)
    op.create_index(op.f('ix_outreach_records_status'), 'outreach_records', ['status'], unique=False)
    op.create_index(op.f('ix_outreach_records_approval_id'), 'outreach_records', ['approval_id'], unique=False)
    op.create_index(op.f('ix_outreach_records_idempotency_key'), 'outreach_records', ['idempotency_key'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_outreach_records_idempotency_key'), table_name='outreach_records')
    op.drop_index(op.f('ix_outreach_records_approval_id'), table_name='outreach_records')
    op.drop_index(op.f('ix_outreach_records_status'), table_name='outreach_records')
    op.drop_index(op.f('ix_outreach_records_task_id'), table_name='outreach_records')
    op.drop_index(op.f('ix_outreach_records_lead_id'), table_name='outreach_records')
    op.drop_index(op.f('ix_outreach_records_org_id'), table_name='outreach_records')
    op.drop_table('outreach_records')
