"""add_p3_customer_success_growth_engine_tables

Revision ID: i9d4e5f6a7b8
Revises: h8c3d4e5f6a7
Create Date: 2026-11-14 13:36:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "i9d4e5f6a7b8"
down_revision = "h8c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "p3_customer_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("primary_contact_user_id", sa.String(length=36), nullable=True),
        sa.Column("primary_contact_email", sa.String(length=250), nullable=True),
        sa.Column("primary_contact_name", sa.String(length=250), nullable=True),
        sa.Column("human_owner", sa.String(length=200), nullable=False),
        sa.Column("assigned_agents_json", sa.JSON(), nullable=False),
        sa.Column("acquisition_source", sa.String(length=120), nullable=True),
        sa.Column("lead_id", sa.String(length=36), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=32), nullable=False),
        sa.Column("business_goals_json", sa.JSON(), nullable=False),
        sa.Column("expected_outcomes_json", sa.JSON(), nullable=False),
        sa.Column("onboarding_progress_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("activation_ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("renewal_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_customer_engagement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_preferences_json", sa.JSON(), nullable=False),
        sa.Column("retention_policy_json", sa.JSON(), nullable=False),
        sa.Column("health_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id"),
    )
    op.create_index("ix_p3_customer_accounts_org_id", "p3_customer_accounts", ["org_id"])
    op.create_index("ix_p3_customer_accounts_lead_id", "p3_customer_accounts", ["lead_id"])
    op.create_index("ix_p3_customer_accounts_lifecycle_state", "p3_customer_accounts", ["lifecycle_state"])

    op.create_table(
        "p3_onboarding_workflows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("sku_key", sa.String(length=100), nullable=False),
        sa.Column("template_key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tasks_json", sa.JSON(), nullable=False),
        sa.Column("readiness_criteria_json", sa.JSON(), nullable=False),
        sa.Column("blockers_json", sa.JSON(), nullable=False),
        sa.Column("training_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("progress_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("activation_confirmed_by", sa.String(length=200), nullable=True),
        sa.Column("activation_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p3_onboarding_workflows_org_id", "p3_onboarding_workflows", ["org_id"])
    op.create_index("ix_p3_onboarding_workflows_sku_key", "p3_onboarding_workflows", ["sku_key"])
    op.create_index("ix_p3_onboarding_workflows_status", "p3_onboarding_workflows", ["status"])

    op.create_table(
        "p3_service_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("p2_engagement_id", sa.String(length=36), nullable=True),
        sa.Column("sku_key", sa.String(length=100), nullable=False),
        sa.Column("service_id", sa.String(length=100), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("original_requirement", sa.Text(), nullable=False),
        sa.Column("approved_scope_json", sa.JSON(), nullable=False),
        sa.Column("assigned_owner", sa.String(length=200), nullable=False),
        sa.Column("assigned_agent_id", sa.String(length=100), nullable=True),
        sa.Column("input_data_json", sa.JSON(), nullable=False),
        sa.Column("source_evidence_json", sa.JSON(), nullable=False),
        sa.Column("execution_history_json", sa.JSON(), nullable=False),
        sa.Column("approval_checkpoints_json", sa.JSON(), nullable=False),
        sa.Column("output_artifacts_json", sa.JSON(), nullable=False),
        sa.Column("quality_checks_json", sa.JSON(), nullable=False),
        sa.Column("quality_state", sa.String(length=32), nullable=False),
        sa.Column("output_metrics_json", sa.JSON(), nullable=False),
        sa.Column("outcome_metrics_json", sa.JSON(), nullable=False),
        sa.Column("revision_notes", sa.Text(), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p3_service_deliveries_org_id", "p3_service_deliveries", ["org_id"])
    op.create_index("ix_p3_service_deliveries_p2_engagement_id", "p3_service_deliveries", ["p2_engagement_id"])
    op.create_index("ix_p3_service_deliveries_workflow_run_id", "p3_service_deliveries", ["workflow_run_id"])
    op.create_index("ix_p3_service_deliveries_quality_state", "p3_service_deliveries", ["quality_state"])

    op.create_table(
        "p3_support_tickets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ticket_number", sa.String(length=40), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_email", sa.String(length=250), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=24), nullable=False),
        sa.Column("assigned_owner", sa.String(length=200), nullable=False),
        sa.Column("assigned_agent_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("attachments_json", sa.JSON(), nullable=False),
        sa.Column("internal_notes_json", sa.JSON(), nullable=False),
        sa.Column("messages_json", sa.JSON(), nullable=False),
        sa.Column("ai_triage_json", sa.JSON(), nullable=True),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_seconds", sa.Integer(), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalation_reason", sa.Text(), nullable=True),
        sa.Column("csat_rating", sa.Integer(), nullable=True),
        sa.Column("csat_comment", sa.Text(), nullable=True),
        sa.Column("feedback_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticket_number"),
    )
    op.create_index("ix_p3_support_tickets_ticket_number", "p3_support_tickets", ["ticket_number"])
    op.create_index("ix_p3_support_tickets_org_id", "p3_support_tickets", ["org_id"])
    op.create_index("ix_p3_support_tickets_priority", "p3_support_tickets", ["priority"])
    op.create_index("ix_p3_support_tickets_status", "p3_support_tickets", ["status"])

    op.create_table(
        "p3_subscription_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("subscription_state", sa.String(length=32), nullable=False),
        sa.Column("billing_category", sa.String(length=48), nullable=False),
        sa.Column("is_provider_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_subscription_id", sa.String(length=200), nullable=True),
        sa.Column("internal_sku", sa.String(length=100), nullable=True),
        sa.Column("billing_interval", sa.String(length=32), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("renewal_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_p3_subscription_events_org_id", "p3_subscription_events", ["org_id"])
    op.create_index("ix_p3_subscription_events_subscription_id", "p3_subscription_events", ["subscription_id"])
    op.create_index("ix_p3_subscription_events_idempotency_key", "p3_subscription_events", ["idempotency_key"])
    op.create_index("ix_p3_subscription_events_event_type", "p3_subscription_events", ["event_type"])
    op.create_index("ix_p3_subscription_events_subscription_state", "p3_subscription_events", ["subscription_state"])

    op.create_table(
        "p3_growth_opportunities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("opportunity_type", sa.String(length=48), nullable=False),
        sa.Column("recommended_sku_key", sa.String(length=100), nullable=True),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("business_justification", sa.Text(), nullable=False),
        sa.Column("supporting_evidence_json", sa.JSON(), nullable=False),
        sa.Column("catalog_price_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("catalog_price_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("referral_code", sa.String(length=64), nullable=True),
        sa.Column("referred_company", sa.String(length=250), nullable=True),
        sa.Column("owner_authorized_by", sa.String(length=200), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p3_growth_opportunities_org_id", "p3_growth_opportunities", ["org_id"])
    op.create_index("ix_p3_growth_opportunities_opportunity_type", "p3_growth_opportunities", ["opportunity_type"])
    op.create_index("ix_p3_growth_opportunities_status", "p3_growth_opportunities", ["status"])
    op.create_index("ix_p3_growth_opportunities_approval_id", "p3_growth_opportunities", ["approval_id"])

    op.create_table(
        "p3_unit_economics_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("service_id", sa.String(length=100), nullable=False),
        sa.Column("delivery_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("execution_id", sa.String(length=64), nullable=True),
        sa.Column("cost_category", sa.String(length=48), nullable=False),
        sa.Column("cost_type_label", sa.String(length=24), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("amount_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("amount_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.String(length=200), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p3_unit_economics_entries_org_id", "p3_unit_economics_entries", ["org_id"])
    op.create_index("ix_p3_unit_economics_entries_service_id", "p3_unit_economics_entries", ["service_id"])
    op.create_index("ix_p3_unit_economics_entries_delivery_id", "p3_unit_economics_entries", ["delivery_id"])
    op.create_index("ix_p3_unit_economics_entries_cost_category", "p3_unit_economics_entries", ["cost_category"])
    op.create_index("ix_p3_unit_economics_entries_cost_type_label", "p3_unit_economics_entries", ["cost_type_label"])

    op.create_table(
        "p3_customer_cost_budgets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("monthly_cost_limit_inr", sa.Float(), nullable=False, server_default="2000.0"),
        sa.Column("alert_threshold_pct", sa.Float(), nullable=False, server_default="80.0"),
        sa.Column("hard_cap_enforced", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("exception_approval_id", sa.String(length=64), nullable=True),
        sa.Column("exception_limit_inr", sa.Float(), nullable=True),
        sa.Column("exception_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id"),
    )
    op.create_index("ix_p3_customer_cost_budgets_org_id", "p3_customer_cost_budgets", ["org_id"])

    op.create_table(
        "p3_improvement_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cluster_key", sa.String(length=120), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("source_category", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("problem_summary", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("customer_impact", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("frequency_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("business_value", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("dev_effort", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("risk_level", sa.String(length=24), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requires_release_approval", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_key"),
    )
    op.create_index("ix_p3_improvement_items_cluster_key", "p3_improvement_items", ["cluster_key"])
    op.create_index("ix_p3_improvement_items_org_id", "p3_improvement_items", ["org_id"])
    op.create_index("ix_p3_improvement_items_status", "p3_improvement_items", ["status"])

    op.create_table(
        "p3_compliance_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("request_type", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("export_manifest_json", sa.JSON(), nullable=True),
        sa.Column("offboarding_checklist_json", sa.JSON(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p3_compliance_requests_org_id", "p3_compliance_requests", ["org_id"])
    op.create_index("ix_p3_compliance_requests_request_type", "p3_compliance_requests", ["request_type"])
    op.create_index("ix_p3_compliance_requests_status", "p3_compliance_requests", ["status"])
    op.create_index("ix_p3_compliance_requests_approval_id", "p3_compliance_requests", ["approval_id"])

    op.create_table(
        "p3_operational_incidents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("incident_type", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resource_ref", sa.String(length=200), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("retry_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p3_operational_incidents_org_id", "p3_operational_incidents", ["org_id"])
    op.create_index("ix_p3_operational_incidents_incident_type", "p3_operational_incidents", ["incident_type"])
    op.create_index("ix_p3_operational_incidents_status", "p3_operational_incidents", ["status"])

    op.create_table(
        "p3_acceptance_steps",
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
        sa.UniqueConstraint("step_key"),
    )
    op.create_index("ix_p3_acceptance_steps_verification_status", "p3_acceptance_steps", ["verification_status"])


def downgrade() -> None:
    op.drop_index("ix_p3_acceptance_steps_verification_status", table_name="p3_acceptance_steps")
    op.drop_table("p3_acceptance_steps")

    op.drop_index("ix_p3_operational_incidents_status", table_name="p3_operational_incidents")
    op.drop_index("ix_p3_operational_incidents_incident_type", table_name="p3_operational_incidents")
    op.drop_index("ix_p3_operational_incidents_org_id", table_name="p3_operational_incidents")
    op.drop_table("p3_operational_incidents")

    op.drop_index("ix_p3_compliance_requests_approval_id", table_name="p3_compliance_requests")
    op.drop_index("ix_p3_compliance_requests_status", table_name="p3_compliance_requests")
    op.drop_index("ix_p3_compliance_requests_request_type", table_name="p3_compliance_requests")
    op.drop_index("ix_p3_compliance_requests_org_id", table_name="p3_compliance_requests")
    op.drop_table("p3_compliance_requests")

    op.drop_index("ix_p3_improvement_items_status", table_name="p3_improvement_items")
    op.drop_index("ix_p3_improvement_items_org_id", table_name="p3_improvement_items")
    op.drop_index("ix_p3_improvement_items_cluster_key", table_name="p3_improvement_items")
    op.drop_table("p3_improvement_items")

    op.drop_index("ix_p3_customer_cost_budgets_org_id", table_name="p3_customer_cost_budgets")
    op.drop_table("p3_customer_cost_budgets")

    op.drop_index("ix_p3_unit_economics_entries_cost_type_label", table_name="p3_unit_economics_entries")
    op.drop_index("ix_p3_unit_economics_entries_cost_category", table_name="p3_unit_economics_entries")
    op.drop_index("ix_p3_unit_economics_entries_delivery_id", table_name="p3_unit_economics_entries")
    op.drop_index("ix_p3_unit_economics_entries_service_id", table_name="p3_unit_economics_entries")
    op.drop_index("ix_p3_unit_economics_entries_org_id", table_name="p3_unit_economics_entries")
    op.drop_table("p3_unit_economics_entries")

    op.drop_index("ix_p3_growth_opportunities_approval_id", table_name="p3_growth_opportunities")
    op.drop_index("ix_p3_growth_opportunities_status", table_name="p3_growth_opportunities")
    op.drop_index("ix_p3_growth_opportunities_opportunity_type", table_name="p3_growth_opportunities")
    op.drop_index("ix_p3_growth_opportunities_org_id", table_name="p3_growth_opportunities")
    op.drop_table("p3_growth_opportunities")

    op.drop_index("ix_p3_subscription_events_subscription_state", table_name="p3_subscription_events")
    op.drop_index("ix_p3_subscription_events_event_type", table_name="p3_subscription_events")
    op.drop_index("ix_p3_subscription_events_idempotency_key", table_name="p3_subscription_events")
    op.drop_index("ix_p3_subscription_events_subscription_id", table_name="p3_subscription_events")
    op.drop_index("ix_p3_subscription_events_org_id", table_name="p3_subscription_events")
    op.drop_table("p3_subscription_events")

    op.drop_index("ix_p3_support_tickets_status", table_name="p3_support_tickets")
    op.drop_index("ix_p3_support_tickets_priority", table_name="p3_support_tickets")
    op.drop_index("ix_p3_support_tickets_org_id", table_name="p3_support_tickets")
    op.drop_index("ix_p3_support_tickets_ticket_number", table_name="p3_support_tickets")
    op.drop_table("p3_support_tickets")

    op.drop_index("ix_p3_service_deliveries_quality_state", table_name="p3_service_deliveries")
    op.drop_index("ix_p3_service_deliveries_workflow_run_id", table_name="p3_service_deliveries")
    op.drop_index("ix_p3_service_deliveries_p2_engagement_id", table_name="p3_service_deliveries")
    op.drop_index("ix_p3_service_deliveries_org_id", table_name="p3_service_deliveries")
    op.drop_table("p3_service_deliveries")

    op.drop_index("ix_p3_onboarding_workflows_status", table_name="p3_onboarding_workflows")
    op.drop_index("ix_p3_onboarding_workflows_sku_key", table_name="p3_onboarding_workflows")
    op.drop_index("ix_p3_onboarding_workflows_org_id", table_name="p3_onboarding_workflows")
    op.drop_table("p3_onboarding_workflows")

    op.drop_index("ix_p3_customer_accounts_lifecycle_state", table_name="p3_customer_accounts")
    op.drop_index("ix_p3_customer_accounts_lead_id", table_name="p3_customer_accounts")
    op.drop_index("ix_p3_customer_accounts_org_id", table_name="p3_customer_accounts")
    op.drop_table("p3_customer_accounts")
