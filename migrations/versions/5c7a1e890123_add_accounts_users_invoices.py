"""Add multi-tenant organizations, users, invoices, and billing tables

Revision ID: 5c7a1e890123
Revises: 4beaadb407af
Create Date: 2026-10-08 15:52:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c7a1e890123'
down_revision: Union[str, None] = '4beaadb407af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Organizations table
    op.create_table(
        'organizations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('tier', sa.String(length=50), nullable=False),
        sa.Column('lead_credits_limit', sa.Integer(), nullable=False),
        sa.Column('lead_credits_used', sa.Integer(), nullable=False),
        sa.Column('outreach_credits_limit', sa.Integer(), nullable=False),
        sa.Column('outreach_credits_used', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_organizations_slug'), 'organizations', ['slug'], unique=True)

    # 2. Users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=250), nullable=False),
        sa.Column('full_name', sa.String(length=250), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'email', name='uq_user_org_email'),
    )
    op.create_index(op.f('ix_users_org_id'), 'users', ['org_id'], unique=False)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=False)

    # 3. Customer records
    op.create_table(
        'customer_records',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=True),
        sa.Column('email', sa.String(length=250), nullable=False),
        sa.Column('name', sa.String(length=250), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('provider_customer_id', sa.String(length=200), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_customer_id', name='uq_customer_provider_id'),
    )
    op.create_index(op.f('ix_customer_records_email'), 'customer_records', ['email'], unique=False)
    op.create_index(op.f('ix_customer_records_org_id'), 'customer_records', ['org_id'], unique=False)
    op.create_index(op.f('ix_customer_records_provider_customer_id'), 'customer_records', ['provider_customer_id'], unique=False)

    # 4. Subscription records
    op.create_table(
        'subscription_records',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=True),
        sa.Column('customer_id', sa.String(length=36), nullable=False),
        sa.Column('plan_id', sa.String(length=200), nullable=True),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('provider_subscription_id', sa.String(length=200), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('current_period_start', sa.String(length=64), nullable=True),
        sa.Column('current_period_end', sa.String(length=64), nullable=True),
        sa.Column('payment_url', sa.String(length=2048), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_subscription_id', name='uq_sub_provider_id'),
    )
    op.create_index('ix_sub_customer', 'subscription_records', ['customer_id'], unique=False)
    op.create_index('ix_sub_status', 'subscription_records', ['status'], unique=False)
    op.create_index(op.f('ix_subscription_records_org_id'), 'subscription_records', ['org_id'], unique=False)

    # 5. Webhook event records
    op.create_table(
        'webhook_event_records',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('provider_event_id', sa.String(length=200), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('raw_event_type', sa.String(length=100), nullable=False),
        sa.Column('resource_id', sa.String(length=200), nullable=False),
        sa.Column('resource_type', sa.String(length=50), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('processed', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_event_id', name='uq_webhook_provider_event'),
    )
    op.create_index(op.f('ix_webhook_event_records_event_type'), 'webhook_event_records', ['event_type'], unique=False)
    op.create_index(op.f('ix_webhook_event_records_resource_id'), 'webhook_event_records', ['resource_id'], unique=False)

    # 6. Invoice records
    op.create_table(
        'invoice_records',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('customer_id', sa.String(length=36), nullable=False),
        sa.Column('subscription_id', sa.String(length=36), nullable=True),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('provider_invoice_id', sa.String(length=200), nullable=False),
        sa.Column('provider_payment_id', sa.String(length=200), nullable=True),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('billing_period_start', sa.String(length=64), nullable=True),
        sa.Column('billing_period_end', sa.String(length=64), nullable=True),
        sa.Column('hosted_invoice_url', sa.String(length=2048), nullable=True),
        sa.Column('pdf_url', sa.String(length=2048), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_invoice_org', 'invoice_records', ['org_id'], unique=False)
    op.create_index('ix_invoice_customer', 'invoice_records', ['customer_id'], unique=False)
    op.create_index('ix_invoice_status', 'invoice_records', ['status'], unique=False)
    op.create_index(op.f('ix_invoice_records_provider_invoice_id'), 'invoice_records', ['provider_invoice_id'], unique=False)


def downgrade() -> None:
    op.drop_table('invoice_records')
    op.drop_table('webhook_event_records')
    op.drop_table('subscription_records')
    op.drop_table('customer_records')
    op.drop_table('users')
    op.drop_table('organizations')
