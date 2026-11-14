"""Add P8 Marketplace Ecosystem tables.

Revision ID: n4c9d0e1f2a3
Revises: m3b8c9d0e1f2
Create Date: 2026-11-14 23:05:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "n4c9d0e1f2a3"
down_revision = "m3b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "p8_developer_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("developer_name", sa.String(length=160), nullable=False),
        sa.Column("contact_email", sa.String(length=160), nullable=False),
        sa.Column("legal_entity_name", sa.String(length=200), nullable=False),
        sa.Column("tax_or_gst_id", sa.String(length=64), nullable=True),
        sa.Column("kyb_status", sa.String(length=32), nullable=False),
        sa.Column("kyb_notes", sa.Text(), nullable=True),
        sa.Column("payout_account_masked", sa.String(length=64), nullable=True),
        sa.Column("verified_by", sa.String(length=120), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p8_developer_profiles_org_id", "p8_developer_profiles", ["org_id"])
    op.create_index("ix_p8_developer_profiles_contact_email", "p8_developer_profiles", ["contact_email"])
    op.create_index("ix_p8_developer_profiles_kyb_status", "p8_developer_profiles", ["kyb_status"])
    op.create_index("ix_p8_dev_kyb_status", "p8_developer_profiles", ["kyb_status", "contact_email"])

    op.create_table(
        "p8_marketplace_listings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("developer_id", sa.String(length=36), nullable=False),
        sa.Column("listing_slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("package_type", sa.String(length=48), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("requested_permissions_json", sa.JSON(), nullable=False),
        sa.Column("endpoint_url", sa.String(length=500), nullable=True),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("ecdsa_signature_hex", sa.Text(), nullable=False),
        sa.Column("signing_public_key_pem", sa.Text(), nullable=False),
        sa.Column("price_inr_monthly", sa.Integer(), nullable=False),
        sa.Column("commission_bps", sa.Integer(), nullable=False),
        sa.Column("security_review_status", sa.String(length=32), nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("published_status", sa.String(length=32), nullable=False),
        sa.Column("approved_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_slug"),
    )
    op.create_index("ix_p8_marketplace_listings_developer_id", "p8_marketplace_listings", ["developer_id"])
    op.create_index("ix_p8_marketplace_listings_listing_slug", "p8_marketplace_listings", ["listing_slug"])
    op.create_index("ix_p8_marketplace_listings_package_type", "p8_marketplace_listings", ["package_type"])
    op.create_index("ix_p8_marketplace_listings_security_review_status", "p8_marketplace_listings", ["security_review_status"])
    op.create_index("ix_p8_marketplace_listings_published_status", "p8_marketplace_listings", ["published_status"])
    op.create_index("ix_p8_list_dev_pub", "p8_marketplace_listings", ["developer_id", "published_status", "security_review_status"])

    op.create_table(
        "p8_tenant_installs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("listing_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("granted_permissions_json", sa.JSON(), nullable=False),
        sa.Column("secret_digests_json", sa.JSON(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("installed_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p8_tenant_installs_org_id", "p8_tenant_installs", ["org_id"])
    op.create_index("ix_p8_tenant_installs_listing_id", "p8_tenant_installs", ["listing_id"])
    op.create_index("ix_p8_tenant_installs_status", "p8_tenant_installs", ["status"])
    op.create_index("ix_p8_inst_org_listing", "p8_tenant_installs", ["org_id", "listing_id", "status"])

    op.create_table(
        "p8_marketplace_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("listing_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("install_id", sa.String(length=36), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("abuse_flagged", sa.Boolean(), nullable=False),
        sa.Column("abuse_reason", sa.Text(), nullable=True),
        sa.Column("moderation_status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p8_marketplace_reviews_listing_id", "p8_marketplace_reviews", ["listing_id"])
    op.create_index("ix_p8_marketplace_reviews_org_id", "p8_marketplace_reviews", ["org_id"])
    op.create_index("ix_p8_marketplace_reviews_install_id", "p8_marketplace_reviews", ["install_id"])
    op.create_index("ix_p8_marketplace_reviews_abuse_flagged", "p8_marketplace_reviews", ["abuse_flagged"])
    op.create_index("ix_p8_marketplace_reviews_moderation_status", "p8_marketplace_reviews", ["moderation_status"])
    op.create_index("ix_p8_rev_listing_mod", "p8_marketplace_reviews", ["listing_id", "moderation_status"])

    op.create_table(
        "p8_revenue_share_ledger",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("install_id", sa.String(length=36), nullable=False),
        sa.Column("listing_id", sa.String(length=36), nullable=False),
        sa.Column("developer_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("gross_amount_inr", sa.Float(), nullable=False),
        sa.Column("commission_bps", sa.Integer(), nullable=False),
        sa.Column("platform_commission_inr", sa.Float(), nullable=False),
        sa.Column("developer_payout_inr", sa.Float(), nullable=False),
        sa.Column("settlement_status", sa.String(length=24), nullable=False),
        sa.Column("evidence_status", sa.String(length=24), nullable=False),
        sa.Column("recorded_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p8_revenue_share_ledger_install_id", "p8_revenue_share_ledger", ["install_id"])
    op.create_index("ix_p8_revenue_share_ledger_listing_id", "p8_revenue_share_ledger", ["listing_id"])
    op.create_index("ix_p8_revenue_share_ledger_developer_id", "p8_revenue_share_ledger", ["developer_id"])
    op.create_index("ix_p8_revenue_share_ledger_org_id", "p8_revenue_share_ledger", ["org_id"])
    op.create_index("ix_p8_revenue_share_ledger_settlement_status", "p8_revenue_share_ledger", ["settlement_status"])
    op.create_index("ix_p8_revenue_share_ledger_evidence_status", "p8_revenue_share_ledger", ["evidence_status"])
    op.create_index("ix_p8_rev_dev_origin", "p8_revenue_share_ledger", ["developer_id", "evidence_status", "settlement_status"])


def downgrade() -> None:
    op.drop_index("ix_p8_rev_dev_origin", table_name="p8_revenue_share_ledger")
    op.drop_index("ix_p8_revenue_share_ledger_evidence_status", table_name="p8_revenue_share_ledger")
    op.drop_index("ix_p8_revenue_share_ledger_settlement_status", table_name="p8_revenue_share_ledger")
    op.drop_index("ix_p8_revenue_share_ledger_org_id", table_name="p8_revenue_share_ledger")
    op.drop_index("ix_p8_revenue_share_ledger_developer_id", table_name="p8_revenue_share_ledger")
    op.drop_index("ix_p8_revenue_share_ledger_listing_id", table_name="p8_revenue_share_ledger")
    op.drop_index("ix_p8_revenue_share_ledger_install_id", table_name="p8_revenue_share_ledger")
    op.drop_table("p8_revenue_share_ledger")

    op.drop_index("ix_p8_rev_listing_mod", table_name="p8_marketplace_reviews")
    op.drop_index("ix_p8_marketplace_reviews_moderation_status", table_name="p8_marketplace_reviews")
    op.drop_index("ix_p8_marketplace_reviews_abuse_flagged", table_name="p8_marketplace_reviews")
    op.drop_index("ix_p8_marketplace_reviews_install_id", table_name="p8_marketplace_reviews")
    op.drop_index("ix_p8_marketplace_reviews_org_id", table_name="p8_marketplace_reviews")
    op.drop_index("ix_p8_marketplace_reviews_listing_id", table_name="p8_marketplace_reviews")
    op.drop_table("p8_marketplace_reviews")

    op.drop_index("ix_p8_inst_org_listing", table_name="p8_tenant_installs")
    op.drop_index("ix_p8_tenant_installs_status", table_name="p8_tenant_installs")
    op.drop_index("ix_p8_tenant_installs_listing_id", table_name="p8_tenant_installs")
    op.drop_index("ix_p8_tenant_installs_org_id", table_name="p8_tenant_installs")
    op.drop_table("p8_tenant_installs")

    op.drop_index("ix_p8_list_dev_pub", table_name="p8_marketplace_listings")
    op.drop_index("ix_p8_marketplace_listings_published_status", table_name="p8_marketplace_listings")
    op.drop_index("ix_p8_marketplace_listings_security_review_status", table_name="p8_marketplace_listings")
    op.drop_index("ix_p8_marketplace_listings_package_type", table_name="p8_marketplace_listings")
    op.drop_index("ix_p8_marketplace_listings_listing_slug", table_name="p8_marketplace_listings")
    op.drop_index("ix_p8_marketplace_listings_developer_id", table_name="p8_marketplace_listings")
    op.drop_table("p8_marketplace_listings")

    op.drop_index("ix_p8_dev_kyb_status", table_name="p8_developer_profiles")
    op.drop_index("ix_p8_developer_profiles_kyb_status", table_name="p8_developer_profiles")
    op.drop_index("ix_p8_developer_profiles_contact_email", table_name="p8_developer_profiles")
    op.drop_index("ix_p8_developer_profiles_org_id", table_name="p8_developer_profiles")
    op.drop_table("p8_developer_profiles")
