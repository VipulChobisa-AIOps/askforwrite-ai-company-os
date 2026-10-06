"""Create task, lead, audit, and idempotency tables."""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("objective", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_records_correlation_id", "task_records", ["correlation_id"])
    op.create_index("ix_task_records_status", "task_records", ["status"])

    op.create_table(
        "leads",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("company", sa.String(length=250), nullable=False),
        sa.Column("website", sa.String(length=2048), nullable=False),
        sa.Column("industry", sa.String(length=250), nullable=False),
        sa.Column("geography", sa.String(length=250), nullable=False),
        sa.Column("observed_signals", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("product_match", sa.String(length=100), nullable=True),
        sa.Column("fit_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("public_contact_channel", sa.String(length=500), nullable=True),
        sa.Column("recommended_next_step", sa.String(length=100), nullable=False),
        sa.Column("do_not_contact", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_checked", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_leads_task_id", "leads", ["task_id"])
    op.create_index("ix_leads_status", "leads", ["status"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=100), nullable=True),
        sa.Column("capability_name", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_task_id", "audit_logs", ["task_id"])
    op.create_index("ix_audit_logs_correlation_id", "audit_logs", ["correlation_id"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("capability_name", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "capability_name", "idempotency_key",
            name="uq_idempotency_capability_key",
        ),
    )
    op.create_index("ix_idempotency_task_id", "idempotency_records", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_task_id", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_audit_logs_correlation_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_task_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_leads_status", table_name="leads")
    op.drop_index("ix_leads_task_id", table_name="leads")
    op.drop_table("leads")
    op.drop_index("ix_task_records_status", table_name="task_records")
    op.drop_index("ix_task_records_correlation_id", table_name="task_records")
    op.drop_table("task_records")