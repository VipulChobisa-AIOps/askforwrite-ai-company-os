"""Add sovereign_payment_sessions table for durable checkout persistence

Revision ID: f6a1b2c3d4e5
Revises: e5f6a1b2c3d4
Create Date: 2026-10-21 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a1b2c3d4e5'
down_revision: Union[str, None] = 'e5f6a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sovereign_payment_sessions',
        sa.Column('session_id', sa.String(length=64), primary_key=True),
        sa.Column('package_key', sa.String(length=100), nullable=False, index=True),
        sa.Column('package_name', sa.String(length=250), nullable=False),
        sa.Column('company_name', sa.String(length=250), nullable=False),
        sa.Column('customer_email', sa.String(length=250), nullable=False, index=True),
        sa.Column('customer_name', sa.String(length=250), nullable=True),
        sa.Column('customer_phone', sa.String(length=50), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=False, server_default='INR'),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('preferred_rail', sa.String(length=32), nullable=False, server_default='upi_direct'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='PENDING', index=True),
        sa.Column('upi_uri', sa.Text(), nullable=False),
        sa.Column('upi_qr_svg', sa.Text(), nullable=False),
        sa.Column('usdc_payload', sa.JSON(), nullable=False),
        sa.Column('bank_wire_invoice', sa.JSON(), nullable=False),
        sa.Column('checkout_url', sa.String(length=500), nullable=False),
        sa.Column('verification_proof', sa.String(length=250), nullable=True),
        sa.Column('verified_rail', sa.String(length=32), nullable=True),
        sa.Column('trust_block_hash', sa.String(length=64), nullable=True),
        sa.Column('trust_block_index', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
    )
    op.create_index('ix_sovereign_session_status', 'sovereign_payment_sessions', ['status'])
    op.create_index('ix_sovereign_session_email', 'sovereign_payment_sessions', ['customer_email'])


def downgrade() -> None:
    op.drop_index('ix_sovereign_session_email', table_name='sovereign_payment_sessions')
    op.drop_index('ix_sovereign_session_status', table_name='sovereign_payment_sessions')
    op.drop_table('sovereign_payment_sessions')
