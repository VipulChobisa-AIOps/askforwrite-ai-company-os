"""add P4 growth and GTM engine tables

Revision ID: j0e5f6a7b8c9
Revises: i9d4e5f6a7b8
Create Date: 2026-11-14 21:55:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "j0e5f6a7b8c9"
down_revision: str | None = "i9d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "p4_icp_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("industry", sa.String(length=120), nullable=False),
        sa.Column("geography", sa.String(length=120), nullable=False, server_default="India"),
        sa.Column("company_size_range", sa.String(length=80), nullable=False, server_default="10-200"),
        sa.Column("buyer_personas_json", sa.JSON(), nullable=False),
        sa.Column("pain_points_json", sa.JSON(), nullable=False),
        sa.Column("value_propositions_json", sa.JSON(), nullable=False),
        sa.Column("disqualifiers_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", sa.String(length=120), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p4_icp_profiles_id", "p4_icp_profiles", ["id"])
    op.create_index("ix_p4_icp_profiles_org_id", "p4_icp_profiles", ["org_id"])
    op.create_index("ix_p4_icp_profiles_industry", "p4_icp_profiles", ["industry"])
    op.create_index("ix_p4_icp_profiles_status", "p4_icp_profiles", ["status"])
    op.create_index("ix_p4_icp_org_status", "p4_icp_profiles", ["org_id", "status"])

    op.create_table(
        "p4_market_intel_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("icp_id", sa.String(length=36), nullable=True),
        sa.Column("intel_type", sa.String(length=48), nullable=False),
        sa.Column("subject_name", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False, server_default="public_web"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_ref", sa.String(length=200), nullable=True),
        sa.Column("confidence_level", sa.String(length=48), nullable=False, server_default="OBSERVATION"),
        sa.Column("verified_facts_json", sa.JSON(), nullable=False),
        sa.Column("inferences_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p4_market_intel_records_id", "p4_market_intel_records", ["id"])
    op.create_index("ix_p4_market_intel_records_org_id", "p4_market_intel_records", ["org_id"])
    op.create_index("ix_p4_market_intel_records_icp_id", "p4_market_intel_records", ["icp_id"])
    op.create_index("ix_p4_market_intel_records_intel_type", "p4_market_intel_records", ["intel_type"])
    op.create_index("ix_p4_market_intel_records_subject_name", "p4_market_intel_records", ["subject_name"])
    op.create_index("ix_p4_market_intel_records_confidence_level", "p4_market_intel_records", ["confidence_level"])
    op.create_index("ix_p4_intel_org_type", "p4_market_intel_records", ["org_id", "intel_type"])

    op.create_table(
        "p4_growth_campaigns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("icp_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("channels_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=48), nullable=False, server_default="DRAFT"),
        sa.Column("execution_mode", sa.String(length=32), nullable=False, server_default="SIMULATION"),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("variants_json", sa.JSON(), nullable=False),
        sa.Column("budget_cap_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("spend_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("safety_report_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p4_growth_campaigns_id", "p4_growth_campaigns", ["id"])
    op.create_index("ix_p4_growth_campaigns_org_id", "p4_growth_campaigns", ["org_id"])
    op.create_index("ix_p4_growth_campaigns_icp_id", "p4_growth_campaigns", ["icp_id"])
    op.create_index("ix_p4_growth_campaigns_status", "p4_growth_campaigns", ["status"])
    op.create_index("ix_p4_growth_campaigns_execution_mode", "p4_growth_campaigns", ["execution_mode"])
    op.create_index("ix_p4_growth_campaigns_approval_id", "p4_growth_campaigns", ["approval_id"])
    op.create_index("ix_p4_campaign_org_status", "p4_growth_campaigns", ["org_id", "status"])

    op.create_table(
        "p4_pipeline_deals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("lead_id", sa.String(length=36), nullable=True),
        sa.Column("campaign_id", sa.String(length=36), nullable=True),
        sa.Column("icp_id", sa.String(length=36), nullable=True),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("contact_email", sa.String(length=200), nullable=True),
        sa.Column("stage", sa.String(length=48), nullable=False, server_default="DISCOVERED"),
        sa.Column("deal_value_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="INR"),
        sa.Column("attribution_source", sa.String(length=64), nullable=False, server_default="ORGANIC_INBOUND"),
        sa.Column("evidence_status", sa.String(length=32), nullable=False, server_default="SANDBOX"),
        sa.Column("lost_reason", sa.String(length=200), nullable=True),
        sa.Column("next_action", sa.String(length=250), nullable=True),
        sa.Column("owner_actor", sa.String(length=120), nullable=False, server_default="owner"),
        sa.Column("stage_history_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p4_pipeline_deals_id", "p4_pipeline_deals", ["id"])
    op.create_index("ix_p4_pipeline_deals_org_id", "p4_pipeline_deals", ["org_id"])
    op.create_index("ix_p4_pipeline_deals_lead_id", "p4_pipeline_deals", ["lead_id"])
    op.create_index("ix_p4_pipeline_deals_campaign_id", "p4_pipeline_deals", ["campaign_id"])
    op.create_index("ix_p4_pipeline_deals_icp_id", "p4_pipeline_deals", ["icp_id"])
    op.create_index("ix_p4_pipeline_deals_company_name", "p4_pipeline_deals", ["company_name"])
    op.create_index("ix_p4_pipeline_deals_stage", "p4_pipeline_deals", ["stage"])
    op.create_index("ix_p4_pipeline_deals_attribution_source", "p4_pipeline_deals", ["attribution_source"])
    op.create_index("ix_p4_pipeline_deals_evidence_status", "p4_pipeline_deals", ["evidence_status"])
    op.create_index("ix_p4_pipeline_deals_lost_reason", "p4_pipeline_deals", ["lost_reason"])
    op.create_index("ix_p4_deal_org_stage_origin", "p4_pipeline_deals", ["org_id", "stage", "evidence_status"])


def downgrade() -> None:
    for idx in (
        "ix_p4_deal_org_stage_origin",
        "ix_p4_pipeline_deals_lost_reason",
        "ix_p4_pipeline_deals_evidence_status",
        "ix_p4_pipeline_deals_attribution_source",
        "ix_p4_pipeline_deals_stage",
        "ix_p4_pipeline_deals_company_name",
        "ix_p4_pipeline_deals_icp_id",
        "ix_p4_pipeline_deals_campaign_id",
        "ix_p4_pipeline_deals_lead_id",
        "ix_p4_pipeline_deals_org_id",
        "ix_p4_pipeline_deals_id",
    ):
        op.drop_index(idx, table_name="p4_pipeline_deals")
    op.drop_table("p4_pipeline_deals")

    for idx in (
        "ix_p4_campaign_org_status",
        "ix_p4_growth_campaigns_approval_id",
        "ix_p4_growth_campaigns_execution_mode",
        "ix_p4_growth_campaigns_status",
        "ix_p4_growth_campaigns_icp_id",
        "ix_p4_growth_campaigns_org_id",
        "ix_p4_growth_campaigns_id",
    ):
        op.drop_index(idx, table_name="p4_growth_campaigns")
    op.drop_table("p4_growth_campaigns")

    for idx in (
        "ix_p4_intel_org_type",
        "ix_p4_market_intel_records_confidence_level",
        "ix_p4_market_intel_records_subject_name",
        "ix_p4_market_intel_records_intel_type",
        "ix_p4_market_intel_records_icp_id",
        "ix_p4_market_intel_records_org_id",
        "ix_p4_market_intel_records_id",
    ):
        op.drop_index(idx, table_name="p4_market_intel_records")
    op.drop_table("p4_market_intel_records")

    for idx in (
        "ix_p4_icp_org_status",
        "ix_p4_icp_profiles_status",
        "ix_p4_icp_profiles_industry",
        "ix_p4_icp_profiles_org_id",
        "ix_p4_icp_profiles_id",
    ):
        op.drop_index(idx, table_name="p4_icp_profiles")
    op.drop_table("p4_icp_profiles")
