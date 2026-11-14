"""Add P1 modular SME workforce, registry, workflow, credit ledger, emergency stop, and execution evidence tables.

Revision ID: g7b2c3d4e5f6
Revises: f6a1b2c3d4e5
Create Date: 2026-11-13 21:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g7b2c3d4e5f6'
down_revision: Union[str, None] = 'f6a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'business_profiles',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('business_name', sa.String(length=250), nullable=False),
        sa.Column('industry', sa.String(length=150), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('location', sa.String(length=250), nullable=False, server_default=''),
        sa.Column('website', sa.String(length=500), nullable=True),
        sa.Column('contact_info', sa.JSON(), nullable=False),
        sa.Column('company_size', sa.String(length=64), nullable=False, server_default='small'),
        sa.Column('employee_count', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('products_and_services', sa.JSON(), nullable=False),
        sa.Column('customer_segments', sa.JSON(), nullable=False),
        sa.Column('sales_channels', sa.JSON(), nullable=False),
        sa.Column('current_software', sa.JSON(), nullable=False),
        sa.Column('operational_pain_points', sa.JSON(), nullable=False),
        sa.Column('business_objectives', sa.JSON(), nullable=False),
        sa.Column('required_automations', sa.JSON(), nullable=False),
        sa.Column('expected_monthly_volume', sa.JSON(), nullable=False),
        sa.Column('recommended_plan', sa.JSON(), nullable=True),
        sa.Column('selection_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.String(length=32), nullable=False, server_default='1.0.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('org_id', name='uq_business_profile_org_id'),
    )
    op.create_index('ix_business_profiles_org_id', 'business_profiles', ['org_id'])

    op.create_table(
        'structured_requirements',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('profile_id', sa.String(length=36), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.Column('title', sa.String(length=250), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('priority', sa.String(length=32), nullable=False, server_default='MEDIUM'),
        sa.Column('recommended_modules', sa.JSON(), nullable=False),
        sa.Column('recommended_agents', sa.JSON(), nullable=False),
        sa.Column('required_connectors', sa.JSON(), nullable=False),
        sa.Column('expected_monthly_credits', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('limitations', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='RECOMMENDED'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_structured_requirements_org_id', 'structured_requirements', ['org_id'])
    op.create_index('ix_structured_requirements_profile_id', 'structured_requirements', ['profile_id'])

    op.create_table(
        'tenant_subscription_profiles',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('internal_sku', sa.String(length=100), nullable=False),
        sa.Column('billing_type', sa.String(length=32), nullable=False, server_default='recurring'),
        sa.Column('billing_interval', sa.String(length=32), nullable=False, server_default='monthly'),
        sa.Column('base_price', sa.JSON(), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False, server_default='INR'),
        sa.Column('provider_plan_id', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('included_modules', sa.JSON(), nullable=False),
        sa.Column('selected_modules', sa.JSON(), nullable=False),
        sa.Column('entitled_agents', sa.JSON(), nullable=False),
        sa.Column('agent_execution_limit', sa.Integer(), nullable=False, server_default='200'),
        sa.Column('included_credits', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('credit_costs', sa.JSON(), nullable=False),
        sa.Column('seat_limit', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('setup_fee', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('support_level', sa.String(length=64), nullable=False, server_default='email_standard'),
        sa.Column('customization_allowance', sa.JSON(), nullable=False),
        sa.Column('renewal_policy', sa.String(length=64), nullable=False, server_default='auto_renew'),
        sa.Column('extra_agents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('extra_seats', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('credit_packs_purchased', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('integration_addons', sa.JSON(), nullable=False),
        sa.Column('total_recurring_price', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_setup_price', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='active'),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.String(length=32), nullable=False, server_default='1.0.0'),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('org_id', name='uq_tenant_sub_profile_org_id'),
    )
    op.create_index('ix_tenant_sub_profile_org_id', 'tenant_subscription_profiles', ['org_id'])
    op.create_index('ix_tenant_sub_profile_sku', 'tenant_subscription_profiles', ['internal_sku'])

    op.create_table(
        'tenant_agent_configs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=64), nullable=False),
        sa.Column('agent_id', sa.String(length=100), nullable=False),
        sa.Column('version', sa.String(length=32), nullable=False, server_default='1.0.0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='DEACTIVATED'),
        sa.Column('model_override', sa.String(length=120), nullable=True),
        sa.Column('execution_mode', sa.String(length=32), nullable=False, server_default='SIMULATION'),
        sa.Column('custom_instructions', sa.Text(), nullable=True),
        sa.Column('tool_allowlist', sa.JSON(), nullable=False),
        sa.Column('execution_limits', sa.JSON(), nullable=False),
        sa.Column('config_json', sa.JSON(), nullable=True),
        sa.Column('activated_by', sa.String(length=250), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('org_id', 'agent_id', name='uq_tenant_agent_config'),
    )
    op.create_index('ix_tenant_agent_configs_org_agent', 'tenant_agent_configs', ['org_id', 'agent_id'])

    op.create_table(
        'connector_states',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=64), nullable=False, server_default='__platform__'),
        sa.Column('connector_id', sa.String(length=100), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('service_category', sa.String(length=100), nullable=False),
        sa.Column('authentication_type', sa.String(length=64), nullable=False),
        sa.Column('environment', sa.String(length=32), nullable=False, server_default='SIMULATION'),
        sa.Column('connection_status', sa.String(length=32), nullable=False, server_default='UNVERIFIED'),
        sa.Column('capability_state', sa.String(length=32), nullable=False, server_default='SIMULATED'),
        sa.Column('config_summary', sa.JSON(), nullable=False),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('version', sa.String(length=32), nullable=False, server_default='1.0.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('org_id', 'connector_id', name='uq_org_connector_state'),
    )
    op.create_index('ix_connector_states_org_conn', 'connector_states', ['org_id', 'connector_id'])

    op.create_table(
        'workflow_definitions',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=64), nullable=False),
        sa.Column('workflow_key', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=250), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('version', sa.String(length=32), nullable=False, server_default='1.0.0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('trigger_type', sa.String(length=32), nullable=False, server_default='manual'),
        sa.Column('schedule_cron', sa.String(length=100), nullable=True),
        sa.Column('max_credits_budget', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='120'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('execution_mode_default', sa.String(length=32), nullable=False, server_default='SIMULATION'),
        sa.Column('steps_json', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(length=250), nullable=False, server_default='system'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_workflow_definitions_org', 'workflow_definitions', ['org_id'])

    op.create_table(
        'workflow_runs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('workflow_id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=64), nullable=False),
        sa.Column('idempotency_key', sa.String(length=200), nullable=True),
        sa.Column('execution_mode', sa.String(length=32), nullable=False, server_default='SIMULATION'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='DRAFT'),
        sa.Column('current_step_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_steps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('credits_budget', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('credits_consumed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('approval_id', sa.String(length=64), nullable=True),
        sa.Column('input_payload', sa.JSON(), nullable=False),
        sa.Column('step_results_json', sa.JSON(), nullable=False),
        sa.Column('output_summary', sa.JSON(), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_by', sa.String(length=250), nullable=False, server_default='system'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_workflow_runs_org_status', 'workflow_runs', ['org_id', 'status'])
    op.create_index('ix_workflow_runs_idempotency', 'workflow_runs', ['idempotency_key'])

    op.create_table(
        'execution_evidence_records',
        sa.Column('execution_id', sa.String(length=64), primary_key=True),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('workflow_id', sa.String(length=64), nullable=True),
        sa.Column('agent_id', sa.String(length=100), nullable=False),
        sa.Column('connector_id', sa.String(length=100), nullable=True),
        sa.Column('execution_mode', sa.String(length=32), nullable=False),
        sa.Column('input_reference', sa.String(length=500), nullable=False),
        sa.Column('output_reference', sa.String(length=500), nullable=False),
        sa.Column('provider_request_id', sa.String(length=200), nullable=True),
        sa.Column('fallback_used', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('approval_id', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('credits_consumed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('evidence_reference', sa.String(length=500), nullable=False),
        sa.Column('version', sa.String(length=32), nullable=False, server_default='1.0.0'),
        sa.Column('output_origin', sa.String(length=64), nullable=False, server_default='SIMULATED_SYNTHETIC'),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
    )
    op.create_index('ix_exec_evidence_tenant_status', 'execution_evidence_records', ['tenant_id', 'status'])
    op.create_index('ix_exec_evidence_agent_mode', 'execution_evidence_records', ['agent_id', 'execution_mode'])

    op.create_table(
        'credit_ledger_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=64), nullable=False),
        sa.Column('execution_id', sa.String(length=64), nullable=True),
        sa.Column('idempotency_key', sa.String(length=200), nullable=False),
        sa.Column('entry_type', sa.String(length=32), nullable=False),
        sa.Column('credit_pool', sa.String(length=64), nullable=False, server_default='lead_credits'),
        sa.Column('delta', sa.Integer(), nullable=False),
        sa.Column('balance_after', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='COMMITTED'),
        sa.Column('reason', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('created_by', sa.String(length=250), nullable=False, server_default='system'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('idempotency_key', name='uq_credit_ledger_idempotency_key'),
    )
    op.create_index('ix_credit_ledger_org_id', 'credit_ledger_records', ['org_id'])

    op.create_table(
        'emergency_stop_records',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('scope_level', sa.String(length=32), nullable=False),
        sa.Column('scope_target', sa.String(length=120), nullable=False),
        sa.Column('org_id', sa.String(length=64), nullable=True),
        sa.Column('state', sa.String(length=32), nullable=False, server_default='EMERGENCY_STOPPED'),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('triggered_by', sa.String(length=250), nullable=False, server_default='system'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_emergency_stop_scope', 'emergency_stop_records', ['scope_level', 'scope_target', 'is_active'])


def downgrade() -> None:
    op.drop_index('ix_emergency_stop_scope', table_name='emergency_stop_records')
    op.drop_table('emergency_stop_records')
    op.drop_index('ix_credit_ledger_org_id', table_name='credit_ledger_records')
    op.drop_table('credit_ledger_records')
    op.drop_index('ix_exec_evidence_agent_mode', table_name='execution_evidence_records')
    op.drop_index('ix_exec_evidence_tenant_status', table_name='execution_evidence_records')
    op.drop_table('execution_evidence_records')
    op.drop_index('ix_workflow_runs_idempotency', table_name='workflow_runs')
    op.drop_index('ix_workflow_runs_org_status', table_name='workflow_runs')
    op.drop_table('workflow_runs')
    op.drop_index('ix_workflow_definitions_org', table_name='workflow_definitions')
    op.drop_table('workflow_definitions')
    op.drop_index('ix_connector_states_org_conn', table_name='connector_states')
    op.drop_table('connector_states')
    op.drop_index('ix_tenant_agent_configs_org_agent', table_name='tenant_agent_configs')
    op.drop_table('tenant_agent_configs')
    op.drop_index('ix_tenant_sub_profile_sku', table_name='tenant_subscription_profiles')
    op.drop_index('ix_tenant_sub_profile_org_id', table_name='tenant_subscription_profiles')
    op.drop_table('tenant_subscription_profiles')
    op.drop_index('ix_structured_requirements_profile_id', table_name='structured_requirements')
    op.drop_index('ix_structured_requirements_org_id', table_name='structured_requirements')
    op.drop_table('structured_requirements')
    op.drop_index('ix_business_profiles_org_id', table_name='business_profiles')
    op.drop_table('business_profiles')

