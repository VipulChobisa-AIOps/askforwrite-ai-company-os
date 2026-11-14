"""Add P5 Productization & Multi-Customer Scale tables.

Revision ID: k1f6a7b8c9d0
Revises: j0e5f6a7b8c9
Create Date: 2026-11-14 22:25:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "k1f6a7b8c9d0"
down_revision = "j0e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "p5_tenant_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("template_key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("industry", sa.String(length=80), nullable=False),
        sa.Column("tier_id", sa.String(length=64), nullable=False),
        sa.Column("selected_modules_json", sa.JSON(), nullable=False),
        sa.Column("catalog_service_ids_json", sa.JSON(), nullable=False),
        sa.Column("default_agent_ids_json", sa.JSON(), nullable=False),
        sa.Column("connector_requirements_json", sa.JSON(), nullable=False),
        sa.Column("policy_defaults_json", sa.JSON(), nullable=False),
        sa.Column("monthly_price_inr", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("evidence_status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_key"),
    )
    op.create_index("ix_p5_tenant_templates_template_key", "p5_tenant_templates", ["template_key"])
    op.create_index("ix_p5_tenant_templates_industry", "p5_tenant_templates", ["industry"])
    op.create_index("ix_p5_tenant_templates_tier_id", "p5_tenant_templates", ["tier_id"])
    op.create_index("ix_p5_tenant_templates_is_active", "p5_tenant_templates", ["is_active"])
    op.create_index("ix_p5_tpl_industry_active", "p5_tenant_templates", ["industry", "is_active"])

    op.create_table(
        "p5_provisioning_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("template_key", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("completed_steps_json", sa.JSON(), nullable=False),
        sa.Column("failed_step", sa.String(length=48), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("config_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("execution_mode", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_p5_provisioning_runs_org_id", "p5_provisioning_runs", ["org_id"])
    op.create_index("ix_p5_provisioning_runs_idempotency_key", "p5_provisioning_runs", ["idempotency_key"])
    op.create_index("ix_p5_provisioning_runs_template_key", "p5_provisioning_runs", ["template_key"])
    op.create_index("ix_p5_provisioning_runs_state", "p5_provisioning_runs", ["state"])
    op.create_index("ix_p5_prov_org_state", "p5_provisioning_runs", ["org_id", "state"])

    op.create_table(
        "p5_tenant_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("tier_id", sa.String(length=64), nullable=False),
        sa.Column("rate_limit_rpm", sa.Integer(), nullable=False),
        sa.Column("daily_agent_runs_cap", sa.Integer(), nullable=False),
        sa.Column("monthly_credit_budget", sa.Integer(), nullable=False),
        sa.Column("storage_quota_mb", sa.Integer(), nullable=False),
        sa.Column("sla_target_uptime_pct", sa.Float(), nullable=False),
        sa.Column("sla_response_minutes", sa.Integer(), nullable=False),
        sa.Column("auto_throttle_on_breach", sa.Boolean(), nullable=False),
        sa.Column("custom_limits_json", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id"),
    )
    op.create_index("ix_p5_tenant_policies_org_id", "p5_tenant_policies", ["org_id"])
    op.create_index("ix_p5_tenant_policies_tier_id", "p5_tenant_policies", ["tier_id"])

    op.create_table(
        "p5_usage_quota_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("metric_type", sa.String(length=64), nullable=False),
        sa.Column("observed_value", sa.Float(), nullable=False),
        sa.Column("limit_value", sa.Float(), nullable=False),
        sa.Column("breached", sa.Boolean(), nullable=False),
        sa.Column("action_taken", sa.String(length=32), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("recorded_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p5_usage_quota_events_org_id", "p5_usage_quota_events", ["org_id"])
    op.create_index("ix_p5_usage_quota_events_metric_type", "p5_usage_quota_events", ["metric_type"])
    op.create_index("ix_p5_usage_quota_events_breached", "p5_usage_quota_events", ["breached"])
    op.create_index("ix_p5_usage_org_metric", "p5_usage_quota_events", ["org_id", "metric_type", "breached"])

    op.create_table(
        "p5_operational_incidents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("mitigation_notes", sa.Text(), nullable=True),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reported_by", sa.String(length=120), nullable=False),
        sa.Column("assigned_to", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p5_operational_incidents_org_id", "p5_operational_incidents", ["org_id"])
    op.create_index("ix_p5_operational_incidents_severity", "p5_operational_incidents", ["severity"])
    op.create_index("ix_p5_operational_incidents_category", "p5_operational_incidents", ["category"])
    op.create_index("ix_p5_operational_incidents_status", "p5_operational_incidents", ["status"])
    op.create_index("ix_p5_incident_org_status", "p5_operational_incidents", ["org_id", "status", "severity"])


def downgrade() -> None:
    op.drop_index("ix_p5_incident_org_status", table_name="p5_operational_incidents")
    op.drop_index("ix_p5_operational_incidents_status", table_name="p5_operational_incidents")
    op.drop_index("ix_p5_operational_incidents_category", table_name="p5_operational_incidents")
    op.drop_index("ix_p5_operational_incidents_severity", table_name="p5_operational_incidents")
    op.drop_index("ix_p5_operational_incidents_org_id", table_name="p5_operational_incidents")
    op.drop_table("p5_operational_incidents")

    op.drop_index("ix_p5_usage_org_metric", table_name="p5_usage_quota_events")
    op.drop_index("ix_p5_usage_quota_events_breached", table_name="p5_usage_quota_events")
    op.drop_index("ix_p5_usage_quota_events_metric_type", table_name="p5_usage_quota_events")
    op.drop_index("ix_p5_usage_quota_events_org_id", table_name="p5_usage_quota_events")
    op.drop_table("p5_usage_quota_events")

    op.drop_index("ix_p5_tenant_policies_tier_id", table_name="p5_tenant_policies")
    op.drop_index("ix_p5_tenant_policies_org_id", table_name="p5_tenant_policies")
    op.drop_table("p5_tenant_policies")

    op.drop_index("ix_p5_prov_org_state", table_name="p5_provisioning_runs")
    op.drop_index("ix_p5_provisioning_runs_state", table_name="p5_provisioning_runs")
    op.drop_index("ix_p5_provisioning_runs_template_key", table_name="p5_provisioning_runs")
    op.drop_index("ix_p5_provisioning_runs_idempotency_key", table_name="p5_provisioning_runs")
    op.drop_index("ix_p5_provisioning_runs_org_id", table_name="p5_provisioning_runs")
    op.drop_table("p5_provisioning_runs")

    op.drop_index("ix_p5_tpl_industry_active", table_name="p5_tenant_templates")
    op.drop_index("ix_p5_tenant_templates_is_active", table_name="p5_tenant_templates")
    op.drop_index("ix_p5_tenant_templates_tier_id", table_name="p5_tenant_templates")
    op.drop_index("ix_p5_tenant_templates_industry", table_name="p5_tenant_templates")
    op.drop_index("ix_p5_tenant_templates_template_key", table_name="p5_tenant_templates")
    op.drop_table("p5_tenant_templates")
