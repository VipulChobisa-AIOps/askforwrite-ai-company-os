"""Add P6 Multi-Industry SME Packs & India SEO baseline tables.

Revision ID: l2a7b8c9d0e1
Revises: k1f6a7b8c9d0
Create Date: 2026-11-14 22:45:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "l2a7b8c9d0e1"
down_revision = "k1f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "p6_industry_packs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("pack_key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("sector", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tier_id", sa.String(length=64), nullable=False),
        sa.Column("selected_modules_json", sa.JSON(), nullable=False),
        sa.Column("catalog_service_ids_json", sa.JSON(), nullable=False),
        sa.Column("agent_ids_json", sa.JSON(), nullable=False),
        sa.Column("analytics_capabilities_json", sa.JSON(), nullable=False),
        sa.Column("kpi_definitions_json", sa.JSON(), nullable=False),
        sa.Column("default_config_json", sa.JSON(), nullable=False),
        sa.Column("monthly_price_inr", sa.Integer(), nullable=False),
        sa.Column("readiness_status", sa.String(length=32), nullable=False),
        sa.Column("verified_live_customers", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pack_key"),
    )
    op.create_index("ix_p6_industry_packs_pack_key", "p6_industry_packs", ["pack_key"])
    op.create_index("ix_p6_industry_packs_sector", "p6_industry_packs", ["sector"])
    op.create_index("ix_p6_industry_packs_tier_id", "p6_industry_packs", ["tier_id"])
    op.create_index("ix_p6_industry_packs_readiness_status", "p6_industry_packs", ["readiness_status"])
    op.create_index("ix_p6_industry_packs_is_active", "p6_industry_packs", ["is_active"])
    op.create_index("ix_p6_pack_sector_readiness", "p6_industry_packs", ["sector", "readiness_status"])

    op.create_table(
        "p6_tenant_pack_deployments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("pack_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("execution_mode", sa.String(length=24), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("last_analytics_output_json", sa.JSON(), nullable=False),
        sa.Column("readiness_label", sa.String(length=32), nullable=False),
        sa.Column("deployed_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p6_tenant_pack_deployments_org_id", "p6_tenant_pack_deployments", ["org_id"])
    op.create_index("ix_p6_tenant_pack_deployments_pack_key", "p6_tenant_pack_deployments", ["pack_key"])
    op.create_index("ix_p6_tenant_pack_deployments_status", "p6_tenant_pack_deployments", ["status"])
    op.create_index("ix_p6_dep_org_pack", "p6_tenant_pack_deployments", ["org_id", "pack_key", "status"])

    op.create_table(
        "p6_seo_baselines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("region_code", sa.String(length=16), nullable=False),
        sa.Column("city_or_cluster", sa.String(length=120), nullable=False),
        sa.Column("industry_vertical", sa.String(length=80), nullable=False),
        sa.Column("primary_catalog_sku", sa.String(length=80), nullable=False),
        sa.Column("target_keywords_json", sa.JSON(), nullable=False),
        sa.Column("localized_pages_json", sa.JSON(), nullable=False),
        sa.Column("schema_markup_json", sa.JSON(), nullable=False),
        sa.Column("baseline_status", sa.String(length=32), nullable=False),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p6_seo_baselines_org_id", "p6_seo_baselines", ["org_id"])
    op.create_index("ix_p6_seo_baselines_city_or_cluster", "p6_seo_baselines", ["city_or_cluster"])
    op.create_index("ix_p6_seo_baselines_industry_vertical", "p6_seo_baselines", ["industry_vertical"])
    op.create_index("ix_p6_seo_baselines_primary_catalog_sku", "p6_seo_baselines", ["primary_catalog_sku"])
    op.create_index("ix_p6_seo_baselines_baseline_status", "p6_seo_baselines", ["baseline_status"])
    op.create_index("ix_p6_seo_baselines_approval_id", "p6_seo_baselines", ["approval_id"])
    op.create_index("ix_p6_seo_org_vertical", "p6_seo_baselines", ["org_id", "industry_vertical"])


def downgrade() -> None:
    op.drop_index("ix_p6_seo_org_vertical", table_name="p6_seo_baselines")
    op.drop_index("ix_p6_seo_baselines_approval_id", table_name="p6_seo_baselines")
    op.drop_index("ix_p6_seo_baselines_baseline_status", table_name="p6_seo_baselines")
    op.drop_index("ix_p6_seo_baselines_primary_catalog_sku", table_name="p6_seo_baselines")
    op.drop_index("ix_p6_seo_baselines_industry_vertical", table_name="p6_seo_baselines")
    op.drop_index("ix_p6_seo_baselines_city_or_cluster", table_name="p6_seo_baselines")
    op.drop_index("ix_p6_seo_baselines_org_id", table_name="p6_seo_baselines")
    op.drop_table("p6_seo_baselines")

    op.drop_index("ix_p6_dep_org_pack", table_name="p6_tenant_pack_deployments")
    op.drop_index("ix_p6_tenant_pack_deployments_status", table_name="p6_tenant_pack_deployments")
    op.drop_index("ix_p6_tenant_pack_deployments_pack_key", table_name="p6_tenant_pack_deployments")
    op.drop_index("ix_p6_tenant_pack_deployments_org_id", table_name="p6_tenant_pack_deployments")
    op.drop_table("p6_tenant_pack_deployments")

    op.drop_index("ix_p6_pack_sector_readiness", table_name="p6_industry_packs")
    op.drop_index("ix_p6_industry_packs_is_active", table_name="p6_industry_packs")
    op.drop_index("ix_p6_industry_packs_readiness_status", table_name="p6_industry_packs")
    op.drop_index("ix_p6_industry_packs_tier_id", table_name="p6_industry_packs")
    op.drop_index("ix_p6_industry_packs_sector", table_name="p6_industry_packs")
    op.drop_index("ix_p6_industry_packs_pack_key", table_name="p6_industry_packs")
    op.drop_table("p6_industry_packs")
