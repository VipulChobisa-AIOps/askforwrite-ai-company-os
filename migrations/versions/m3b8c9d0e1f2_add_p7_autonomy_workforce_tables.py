"""Add P7 Controlled Autonomous Workforce tables.

Revision ID: m3b8c9d0e1f2
Revises: l2a7b8c9d0e1
Create Date: 2026-11-14 22:55:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m3b8c9d0e1f2"
down_revision = "l2a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "p7_delegation_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("nodes_json", sa.JSON(), nullable=False),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("computed_depth", sa.Integer(), nullable=False),
        sa.Column("credit_budget", sa.Integer(), nullable=False),
        sa.Column("credits_consumed", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("execution_mode", sa.String(length=24), nullable=False),
        sa.Column("execution_results_json", sa.JSON(), nullable=False),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p7_delegation_plans_org_id", "p7_delegation_plans", ["org_id"])
    op.create_index("ix_p7_delegation_plans_status", "p7_delegation_plans", ["status"])
    op.create_index("ix_p7_delegation_plans_approval_id", "p7_delegation_plans", ["approval_id"])
    op.create_index("ix_p7_dag_org_status", "p7_delegation_plans", ["org_id", "status"])

    op.create_table(
        "p7_tenant_memories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("namespace", sa.String(length=80), nullable=False),
        sa.Column("memory_key", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=48), nullable=False),
        sa.Column("source_ref", sa.String(length=200), nullable=True),
        sa.Column("ttl_seconds", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p7_tenant_memories_org_id", "p7_tenant_memories", ["org_id"])
    op.create_index("ix_p7_tenant_memories_namespace", "p7_tenant_memories", ["namespace"])
    op.create_index("ix_p7_tenant_memories_memory_key", "p7_tenant_memories", ["memory_key"])
    op.create_index("ix_p7_tenant_memories_expires_at", "p7_tenant_memories", ["expires_at"])
    op.create_index("ix_p7_tenant_memories_is_deleted", "p7_tenant_memories", ["is_deleted"])
    op.create_index("ix_p7_mem_org_ns", "p7_tenant_memories", ["org_id", "namespace", "is_deleted"])

    op.create_table(
        "p7_autonomy_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("agent_id", sa.String(length=100), nullable=False),
        sa.Column("autonomy_level", sa.String(length=48), nullable=False),
        sa.Column("requires_hitl_for_external", sa.Boolean(), nullable=False),
        sa.Column("max_daily_budget_credits", sa.Integer(), nullable=False),
        sa.Column("is_paused", sa.Boolean(), nullable=False),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        sa.Column("min_eval_threshold", sa.Float(), nullable=False),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p7_autonomy_policies_org_id", "p7_autonomy_policies", ["org_id"])
    op.create_index("ix_p7_autonomy_policies_agent_id", "p7_autonomy_policies", ["agent_id"])
    op.create_index("ix_p7_autonomy_policies_autonomy_level", "p7_autonomy_policies", ["autonomy_level"])
    op.create_index("ix_p7_autonomy_policies_is_paused", "p7_autonomy_policies", ["is_paused"])
    op.create_index("ix_p7_autonomy_policies_approval_id", "p7_autonomy_policies", ["approval_id"])
    op.create_index("ix_p7_autonomy_org_agent", "p7_autonomy_policies", ["org_id", "agent_id", "is_paused"])

    op.create_table(
        "p7_agent_eval_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("agent_id", sa.String(length=100), nullable=False),
        sa.Column("eval_suite_name", sa.String(length=120), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("safety_score", sa.Float(), nullable=False),
        sa.Column("threshold_score", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("auto_paused_triggered", sa.Boolean(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("evaluated_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_p7_agent_eval_runs_org_id", "p7_agent_eval_runs", ["org_id"])
    op.create_index("ix_p7_agent_eval_runs_agent_id", "p7_agent_eval_runs", ["agent_id"])
    op.create_index("ix_p7_agent_eval_runs_passed", "p7_agent_eval_runs", ["passed"])
    op.create_index("ix_p7_agent_eval_runs_auto_paused_triggered", "p7_agent_eval_runs", ["auto_paused_triggered"])
    op.create_index("ix_p7_eval_org_agent", "p7_agent_eval_runs", ["org_id", "agent_id", "passed"])


def downgrade() -> None:
    op.drop_index("ix_p7_eval_org_agent", table_name="p7_agent_eval_runs")
    op.drop_index("ix_p7_agent_eval_runs_auto_paused_triggered", table_name="p7_agent_eval_runs")
    op.drop_index("ix_p7_agent_eval_runs_passed", table_name="p7_agent_eval_runs")
    op.drop_index("ix_p7_agent_eval_runs_agent_id", table_name="p7_agent_eval_runs")
    op.drop_index("ix_p7_agent_eval_runs_org_id", table_name="p7_agent_eval_runs")
    op.drop_table("p7_agent_eval_runs")

    op.drop_index("ix_p7_autonomy_org_agent", table_name="p7_autonomy_policies")
    op.drop_index("ix_p7_autonomy_policies_approval_id", table_name="p7_autonomy_policies")
    op.drop_index("ix_p7_autonomy_policies_is_paused", table_name="p7_autonomy_policies")
    op.drop_index("ix_p7_autonomy_policies_autonomy_level", table_name="p7_autonomy_policies")
    op.drop_index("ix_p7_autonomy_policies_agent_id", table_name="p7_autonomy_policies")
    op.drop_index("ix_p7_autonomy_policies_org_id", table_name="p7_autonomy_policies")
    op.drop_table("p7_autonomy_policies")

    op.drop_index("ix_p7_mem_org_ns", table_name="p7_tenant_memories")
    op.drop_index("ix_p7_tenant_memories_is_deleted", table_name="p7_tenant_memories")
    op.drop_index("ix_p7_tenant_memories_expires_at", table_name="p7_tenant_memories")
    op.drop_index("ix_p7_tenant_memories_memory_key", table_name="p7_tenant_memories")
    op.drop_index("ix_p7_tenant_memories_namespace", table_name="p7_tenant_memories")
    op.drop_index("ix_p7_tenant_memories_org_id", table_name="p7_tenant_memories")
    op.drop_table("p7_tenant_memories")

    op.drop_index("ix_p7_dag_org_status", table_name="p7_delegation_plans")
    op.drop_index("ix_p7_delegation_plans_approval_id", table_name="p7_delegation_plans")
    op.drop_index("ix_p7_delegation_plans_status", table_name="p7_delegation_plans")
    op.drop_index("ix_p7_delegation_plans_org_id", table_name="p7_delegation_plans")
    op.drop_table("p7_delegation_plans")
