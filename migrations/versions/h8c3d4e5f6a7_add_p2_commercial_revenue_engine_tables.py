"""add_p2_commercial_revenue_engine_tables

Revision ID: h8c3d4e5f6a7
Revises: g7b2c3d4e5f6
Create Date: 2026-11-14 11:35:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "h8c3d4e5f6a7"
down_revision = "g7b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "p2_prospect_dossiers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("normalized_company_key", sa.String(length=250), nullable=False),
        sa.Column("normalized_domain", sa.String(length=250), nullable=False),
        sa.Column("business_category", sa.String(length=150), nullable=False),
        sa.Column("location", sa.String(length=250), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("public_contacts_json", sa.JSON(), nullable=False),
        sa.Column("agency_profile_json", sa.JSON(), nullable=False),
        sa.Column("research_claims_json", sa.JSON(), nullable=False),
        sa.Column("qualification_breakdown_json", sa.JSON(), nullable=False),
        sa.Column("qualification_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("research_brief_json", sa.JSON(), nullable=False),
        sa.Column("pipeline_status", sa.String(length=32), nullable=False),
        sa.Column("next_action", sa.String(length=300), nullable=True),
        sa.Column("follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovery_notes", sa.Text(), nullable=True),
        sa.Column("response_history_json", sa.JSON(), nullable=False),
        sa.Column("recommended_sku", sa.String(length=100), nullable=False),
        sa.Column("commercial_value_inr", sa.Float(), nullable=False, server_default="4999.0"),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("payment_status", sa.String(length=32), nullable=False),
        sa.Column("activation_status", sa.String(length=32), nullable=False),
        sa.Column("activated_org_id", sa.String(length=64), nullable=True),
        sa.Column("owner_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lead_id", name="uq_p2_dossier_lead_id"),
    )
    op.create_index("ix_p2_dossiers_lead", "p2_prospect_dossiers", ["lead_id"])
    op.create_index("ix_p2_dossiers_org", "p2_prospect_dossiers", ["org_id"])
    op.create_index("ix_p2_dossiers_company", "p2_prospect_dossiers", ["normalized_company_key"])
    op.create_index("ix_p2_dossiers_domain", "p2_prospect_dossiers", ["normalized_domain"])
    op.create_index("ix_p2_dossiers_pipeline", "p2_prospect_dossiers", ["pipeline_status"])
    op.create_index("ix_p2_dossiers_payment", "p2_prospect_dossiers", ["payment_status"])

    op.create_table(
        "p2_commercial_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("proposal_record_id", sa.String(length=36), nullable=True),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("sku_key", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("customer_problem", sa.Text(), nullable=False),
        sa.Column("scope_summary", sa.Text(), nullable=False),
        sa.Column("deliverables_json", sa.JSON(), nullable=False),
        sa.Column("exclusions_limitations_json", sa.JSON(), nullable=False),
        sa.Column("implementation_schedule_json", sa.JSON(), nullable=False),
        sa.Column("pricing_json", sa.JSON(), nullable=False),
        sa.Column("payment_terms_json", sa.JSON(), nullable=False),
        sa.Column("client_responsibilities_json", sa.JSON(), nullable=False),
        sa.Column("provider_responsibilities_json", sa.JSON(), nullable=False),
        sa.Column("acceptance_cancellation_terms_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("shared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shared_channel", sa.String(length=64), nullable=True),
        sa.Column("checkout_session_id", sa.String(length=100), nullable=True),
        sa.Column("checkout_url", sa.String(length=1024), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("approved_by", sa.String(length=120), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p2_proposals_lead", "p2_commercial_proposals", ["lead_id"])
    op.create_index("ix_p2_proposals_status", "p2_commercial_proposals", ["status"])
    op.create_index("ix_p2_proposals_approval", "p2_commercial_proposals", ["approval_id"])

    op.create_table(
        "p2_suppression_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("identifier_type", sa.String(length=20), nullable=False),
        sa.Column("identifier_value", sa.String(length=250), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identifier_value", name="uq_p2_suppression_identifier"),
    )
    op.create_index("ix_p2_suppression_val", "p2_suppression_entries", ["identifier_value"])

    op.create_table(
        "p2_payment_reconciliation_queue",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("lead_id", sa.String(length=36), nullable=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("checkout_reference", sa.String(length=200), nullable=False),
        sa.Column("provider_event_id", sa.String(length=200), nullable=True),
        sa.Column("expected_sku", sa.String(length=100), nullable=False),
        sa.Column("expected_amount", sa.Float(), nullable=False, server_default="4999.0"),
        sa.Column("received_amount", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("verification_state", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("activated_org_id", sa.String(length=64), nullable=True),
        sa.Column("invoice_id", sa.String(length=100), nullable=True),
        sa.Column("activation_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_event_id", name="uq_p2_recon_provider_event_id"),
    )
    op.create_index("ix_p2_recon_proposal", "p2_payment_reconciliation_queue", ["proposal_id"])
    op.create_index("ix_p2_recon_checkout", "p2_payment_reconciliation_queue", ["checkout_reference"])
    op.create_index("ix_p2_recon_state", "p2_payment_reconciliation_queue", ["verification_state"])

    op.create_table(
        "p2_customer_engagements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=True),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("invoice_id", sa.String(length=100), nullable=True),
        sa.Column("sku_key", sa.String(length=100), nullable=False),
        sa.Column("billing_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assigned_modules_json", sa.JSON(), nullable=False),
        sa.Column("entitlements_json", sa.JSON(), nullable=False),
        sa.Column("onboarding_checklist_json", sa.JSON(), nullable=False),
        sa.Column("required_client_inputs_json", sa.JSON(), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("deliverables_json", sa.JSON(), nullable=False),
        sa.Column("customer_feedback_json", sa.JSON(), nullable=True),
        sa.Column("renewal_recommendation_json", sa.JSON(), nullable=True),
        sa.Column("pilot_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pilot_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p2_engagements_org", "p2_customer_engagements", ["org_id"])
    op.create_index("ix_p2_engagements_status", "p2_customer_engagements", ["status"])

    op.create_table(
        "p2_acceptance_checklist_steps",
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("verified_by", sa.String(length=120), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("step_number"),
        sa.UniqueConstraint("step_key", name="uq_p2_acceptance_step_key"),
    )
    op.create_index("ix_p2_acceptance_status", "p2_acceptance_checklist_steps", ["verification_status"])


def downgrade() -> None:
    op.drop_index("ix_p2_acceptance_status", table_name="p2_acceptance_checklist_steps")
    op.drop_table("p2_acceptance_checklist_steps")
    op.drop_index("ix_p2_engagements_status", table_name="p2_customer_engagements")
    op.drop_index("ix_p2_engagements_org", table_name="p2_customer_engagements")
    op.drop_table("p2_customer_engagements")
    op.drop_index("ix_p2_recon_state", table_name="p2_payment_reconciliation_queue")
    op.drop_index("ix_p2_recon_checkout", table_name="p2_payment_reconciliation_queue")
    op.drop_index("ix_p2_recon_proposal", table_name="p2_payment_reconciliation_queue")
    op.drop_table("p2_payment_reconciliation_queue")
    op.drop_index("ix_p2_suppression_val", table_name="p2_suppression_entries")
    op.drop_table("p2_suppression_entries")
    op.drop_index("ix_p2_proposals_approval", table_name="p2_commercial_proposals")
    op.drop_index("ix_p2_proposals_status", table_name="p2_commercial_proposals")
    op.drop_index("ix_p2_proposals_lead", table_name="p2_commercial_proposals")
    op.drop_table("p2_commercial_proposals")
    op.drop_index("ix_p2_dossiers_payment", table_name="p2_prospect_dossiers")
    op.drop_index("ix_p2_dossiers_pipeline", table_name="p2_prospect_dossiers")
    op.drop_index("ix_p2_dossiers_domain", table_name="p2_prospect_dossiers")
    op.drop_index("ix_p2_dossiers_company", table_name="p2_prospect_dossiers")
    op.drop_index("ix_p2_dossiers_org", table_name="p2_prospect_dossiers")
    op.drop_index("ix_p2_dossiers_lead", table_name="p2_prospect_dossiers")
    op.drop_table("p2_prospect_dossiers")
