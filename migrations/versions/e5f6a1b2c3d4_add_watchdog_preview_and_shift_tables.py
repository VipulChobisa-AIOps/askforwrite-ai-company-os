"""Add supervisor_alert_records, preview_records, and shift_records tables

Revision ID: e5f6a1b2c3d4
Revises: d4e5f6a1b2c3
Create Date: 2026-10-18 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a1b2c3d4'
down_revision: Union[str, None] = 'd4e5f6a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'supervisor_alert_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('user_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('task_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('alert_type', sa.String(length=64), nullable=False),
        sa.Column('severity', sa.String(length=32), nullable=False, server_default='HIGH'),
        sa.Column('title', sa.String(length=250), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('suggested_action', sa.Text(), nullable=True),
        sa.Column('is_acknowledged', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('acknowledged_by', sa.String(length=100), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
    )
    op.create_index('ix_alert_org_acknowledged', 'supervisor_alert_records', ['org_id', 'is_acknowledged'])
    op.create_index('ix_alert_user_severity', 'supervisor_alert_records', ['user_id', 'severity'])

    op.create_table(
        'preview_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('preview_token', sa.String(length=100), nullable=False),
        sa.Column('company_name', sa.String(length=250), nullable=False),
        sa.Column('domain', sa.String(length=250), nullable=False),
        sa.Column('recommended_package', sa.String(length=100), nullable=False),
        sa.Column('lead_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('custom_audit', sa.JSON(), nullable=False),
        sa.Column('sample_deliverable', sa.JSON(), nullable=False),
        sa.Column('benchmarks', sa.JSON(), nullable=False),
        sa.Column('payment_links', sa.JSON(), nullable=False),
        sa.Column('views_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('trust_block_hash', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_preview_token', 'preview_records', ['preview_token'], unique=True)
    op.create_index('ix_preview_domain', 'preview_records', ['domain'])

    op.create_table(
        'shift_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('shift_id', sa.String(length=100), nullable=False),
        sa.Column('shift_type', sa.String(length=64), nullable=False, server_default='full_daily_cycle'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='COMPLETED'),
        sa.Column('summary', sa.JSON(), nullable=False),
        sa.Column('trust_block_hash', sa.String(length=64), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_shift_id', 'shift_records', ['shift_id'], unique=True)
    op.create_index('ix_shift_status', 'shift_records', ['status'])


def downgrade() -> None:
    op.drop_index('ix_shift_status', table_name='shift_records')
    op.drop_index('ix_shift_id', table_name='shift_records')
    op.drop_table('shift_records')

    op.drop_index('ix_preview_domain', table_name='preview_records')
    op.drop_index('ix_preview_token', table_name='preview_records')
    op.drop_table('preview_records')

    op.drop_index('ix_alert_user_severity', table_name='supervisor_alert_records')
    op.drop_index('ix_alert_org_acknowledged', table_name='supervisor_alert_records')
    op.drop_table('supervisor_alert_records')
