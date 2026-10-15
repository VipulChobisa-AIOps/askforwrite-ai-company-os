"""Add conveyance_claim_records and expense_receipt_records tables

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-10-11 23:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a1b2c3'
down_revision: Union[str, None] = 'c3d4e5f6a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conveyance_claim_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=36), nullable=True, index=True),
        sa.Column('user_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('claim_date', sa.String(length=10), nullable=False, index=True),
        sa.Column('transport_mode', sa.String(length=32), nullable=False, server_default='TWO_WHEELER'),
        sa.Column('raw_gps_distance_km', sa.Float(), nullable=False),
        sa.Column('verified_road_distance_km', sa.Float(), nullable=False),
        sa.Column('jitter_filtered_km', sa.Float(), nullable=False),
        sa.Column('rate_per_km', sa.Float(), nullable=False),
        sa.Column('total_conveyance_amount', sa.Float(), nullable=False),
        sa.Column('total_expenses_amount', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('grand_total_amount', sa.Float(), nullable=False),
        sa.Column('receipt_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='AUTO_APPROVED'),
        sa.Column('discrepancy_flags', sa.JSON(), nullable=True),
        sa.Column('trust_block_hash', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
    )
    op.create_index('ix_conveyance_user_date', 'conveyance_claim_records', ['user_id', 'claim_date'])
    op.create_index('ix_conveyance_org_status', 'conveyance_claim_records', ['org_id', 'status'])

    op.create_table(
        'expense_receipt_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('claim_id', sa.String(length=36), nullable=False, index=True),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('merchant_name', sa.String(length=200), nullable=True),
        sa.Column('receipt_date', sa.String(length=10), nullable=True),
        sa.Column('receipt_hash', sa.String(length=64), nullable=False),
        sa.Column('ocr_extracted_data', sa.JSON(), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_expense_claim_id', 'expense_receipt_records', ['claim_id'])


def downgrade() -> None:
    op.drop_index('ix_expense_claim_id', table_name='expense_receipt_records')
    op.drop_table('expense_receipt_records')
    op.drop_index('ix_conveyance_org_status', table_name='conveyance_claim_records')
    op.drop_index('ix_conveyance_user_date', table_name='conveyance_claim_records')
    op.drop_table('conveyance_claim_records')
