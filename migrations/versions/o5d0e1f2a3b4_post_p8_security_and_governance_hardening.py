"""Add TenantInvitationRecord, P7 three-control budget/state columns, execution telemetry columns, and relational FKs.

Revision ID: o5d0e1f2a3b4
Revises: n4c9d0e1f2a3
Create Date: 2026-11-15 00:46:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

revision = "o5d0e1f2a3b4"
down_revision = "n4c9d0e1f2a3"
branch_labels = None
depends_on = None


def _is_offline() -> bool:
    try:
        return bool(context.is_offline_mode())
    except Exception:
        return False


def _cleanup_nullable_p4_orphans() -> None:
    """Nullify dangling optional P4 references before enforcing PostgreSQL foreign keys."""
    if _is_offline():
        return
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE p4_market_intel_records SET icp_id = NULL "
            "WHERE icp_id IS NOT NULL AND icp_id NOT IN (SELECT id FROM p4_icp_profiles)"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE p4_growth_campaigns SET icp_id = NULL "
            "WHERE icp_id IS NOT NULL AND icp_id NOT IN (SELECT id FROM p4_icp_profiles)"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE p4_pipeline_deals SET lead_id = NULL "
            "WHERE lead_id IS NOT NULL AND lead_id NOT IN (SELECT id FROM leads)"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE p4_pipeline_deals SET campaign_id = NULL "
            "WHERE campaign_id IS NOT NULL AND campaign_id NOT IN (SELECT id FROM p4_growth_campaigns)"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE p4_pipeline_deals SET icp_id = NULL "
            "WHERE icp_id IS NOT NULL AND icp_id NOT IN (SELECT id FROM p4_icp_profiles)"
        )
    )


def upgrade() -> None:
    op.create_table(
        "tenant_invitations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=250), nullable=False),
        sa.Column("invited_role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("invited_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("invited_by_subject", sa.String(length=250), nullable=False, server_default="system"),
        sa.Column("accepted_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_tenant_invitations_org_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"], ["users.id"], name="fk_tenant_invitations_invited_by_user_id", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_tenant_invitations_token_hash"),
    )
    op.create_index("ix_tenant_invitations_org_id", "tenant_invitations", ["org_id"])
    op.create_index("ix_tenant_invitations_email", "tenant_invitations", ["email"])
    op.create_index("ix_tenant_invitations_token_hash", "tenant_invitations", ["token_hash"])
    op.create_index("ix_tenant_invitations_status", "tenant_invitations", ["status"])
    op.create_index("ix_tenant_invitations_approval_id", "tenant_invitations", ["approval_id"])
    op.create_index("ix_tenant_inv_org_email_status", "tenant_invitations", ["org_id", "email", "status"])

    with op.batch_alter_table("execution_evidence_records") as batch_op:
        batch_op.add_column(sa.Column("execution_budget_units", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("provider_cost_inr", sa.Float(), nullable=False, server_default="0.0"))
        batch_op.add_column(sa.Column("provider_tokens_total", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("provider_model", sa.String(length=100), nullable=True))

    with op.batch_alter_table("p7_delegation_plans") as batch_op:
        batch_op.add_column(sa.Column("execution_budget_limit", sa.Integer(), nullable=False, server_default="100"))
        batch_op.add_column(sa.Column("execution_budget_units_used", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("provider_cost_inr", sa.Float(), nullable=False, server_default="0.0"))
        batch_op.add_column(sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"))
        batch_op.add_column(sa.Column("node_states_json", sa.JSON(), nullable=False, server_default="{}"))

    with op.batch_alter_table("p7_autonomy_policies") as batch_op:
        batch_op.add_column(sa.Column("max_daily_execution_units", sa.Integer(), nullable=False, server_default="500"))

    _cleanup_nullable_p4_orphans()

    with op.batch_alter_table("p4_market_intel_records") as batch_op:
        batch_op.create_foreign_key(
            "fk_p4_intel_icp_id", "p4_icp_profiles", ["icp_id"], ["id"], ondelete="SET NULL"
        )

    with op.batch_alter_table("p4_growth_campaigns") as batch_op:
        batch_op.create_foreign_key(
            "fk_p4_campaigns_icp_id", "p4_icp_profiles", ["icp_id"], ["id"], ondelete="SET NULL"
        )

    with op.batch_alter_table("p4_pipeline_deals") as batch_op:
        batch_op.create_foreign_key("fk_p4_deals_lead_id", "leads", ["lead_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key(
            "fk_p4_deals_campaign_id", "p4_growth_campaigns", ["campaign_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key("fk_p4_deals_icp_id", "p4_icp_profiles", ["icp_id"], ["id"], ondelete="SET NULL")

    with op.batch_alter_table("p8_marketplace_listings") as batch_op:
        batch_op.create_foreign_key(
            "fk_p8_listings_developer_id", "p8_developer_profiles", ["developer_id"], ["id"], ondelete="RESTRICT"
        )

    with op.batch_alter_table("p8_tenant_installs") as batch_op:
        batch_op.create_foreign_key(
            "fk_p8_installs_listing_id", "p8_marketplace_listings", ["listing_id"], ["id"], ondelete="RESTRICT"
        )

    with op.batch_alter_table("p8_marketplace_reviews") as batch_op:
        batch_op.create_foreign_key(
            "fk_p8_reviews_listing_id", "p8_marketplace_listings", ["listing_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_foreign_key(
            "fk_p8_reviews_install_id", "p8_tenant_installs", ["install_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    with op.batch_alter_table("p8_marketplace_reviews") as batch_op:
        batch_op.drop_constraint("fk_p8_reviews_install_id", type_="foreignkey")
        batch_op.drop_constraint("fk_p8_reviews_listing_id", type_="foreignkey")

    with op.batch_alter_table("p8_tenant_installs") as batch_op:
        batch_op.drop_constraint("fk_p8_installs_listing_id", type_="foreignkey")

    with op.batch_alter_table("p8_marketplace_listings") as batch_op:
        batch_op.drop_constraint("fk_p8_listings_developer_id", type_="foreignkey")

    with op.batch_alter_table("p4_pipeline_deals") as batch_op:
        batch_op.drop_constraint("fk_p4_deals_icp_id", type_="foreignkey")
        batch_op.drop_constraint("fk_p4_deals_campaign_id", type_="foreignkey")
        batch_op.drop_constraint("fk_p4_deals_lead_id", type_="foreignkey")

    with op.batch_alter_table("p4_growth_campaigns") as batch_op:
        batch_op.drop_constraint("fk_p4_campaigns_icp_id", type_="foreignkey")

    with op.batch_alter_table("p4_market_intel_records") as batch_op:
        batch_op.drop_constraint("fk_p4_intel_icp_id", type_="foreignkey")

    with op.batch_alter_table("p7_autonomy_policies") as batch_op:
        batch_op.drop_column("max_daily_execution_units")

    with op.batch_alter_table("p7_delegation_plans") as batch_op:
        batch_op.drop_column("node_states_json")
        batch_op.drop_column("timeout_seconds")
        batch_op.drop_column("provider_cost_inr")
        batch_op.drop_column("execution_budget_units_used")
        batch_op.drop_column("execution_budget_limit")

    with op.batch_alter_table("execution_evidence_records") as batch_op:
        batch_op.drop_column("provider_model")
        batch_op.drop_column("provider_tokens_total")
        batch_op.drop_column("provider_cost_inr")
        batch_op.drop_column("execution_budget_units")

    op.drop_index("ix_tenant_inv_org_email_status", table_name="tenant_invitations")
    op.drop_index("ix_tenant_invitations_approval_id", table_name="tenant_invitations")
    op.drop_index("ix_tenant_invitations_status", table_name="tenant_invitations")
    op.drop_index("ix_tenant_invitations_token_hash", table_name="tenant_invitations")
    op.drop_index("ix_tenant_invitations_email", table_name="tenant_invitations")
    op.drop_index("ix_tenant_invitations_org_id", table_name="tenant_invitations")
    op.drop_table("tenant_invitations")
