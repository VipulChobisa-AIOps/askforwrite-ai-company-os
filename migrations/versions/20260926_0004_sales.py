"""Add requirement capture and proposal records."""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0004"
down_revision = "20260926_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "approval_requests",
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
    )
    op.create_index("ix_approval_requests_proposal_id", "approval_requests", ["proposal_id"])

    op.create_table(
        "conversation_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversation_logs_lead_id", "conversation_logs", ["lead_id"])
    op.create_index("ix_conversation_logs_task_id", "conversation_logs", ["task_id"])

    op.create_table(
        "requirement_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("customer_company", sa.String(length=250), nullable=False),
        sa.Column("stated_needs", sa.JSON(), nullable=False),
        sa.Column("has_budget_signal", sa.Boolean(), nullable=False),
        sa.Column("has_timeline", sa.Boolean(), nullable=False),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("product_match", sa.String(length=100), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_requirement_records_lead_id", "requirement_records", ["lead_id"])
    op.create_index("ix_requirement_records_conversation_id", "requirement_records", ["conversation_id"])
    op.create_index("ix_requirement_records_task_id", "requirement_records", ["task_id"])

    op.create_table(
        "proposal_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("pricing_model", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_proposal_records_task_id", "proposal_records", ["task_id"])
    op.create_index("ix_proposal_records_requirement_id", "proposal_records", ["requirement_id"])
    op.create_index("ix_proposal_records_lead_id", "proposal_records", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_proposal_records_lead_id", table_name="proposal_records")
    op.drop_index("ix_proposal_records_requirement_id", table_name="proposal_records")
    op.drop_index("ix_proposal_records_task_id", table_name="proposal_records")
    op.drop_table("proposal_records")
    op.drop_index("ix_requirement_records_task_id", table_name="requirement_records")
    op.drop_index("ix_requirement_records_conversation_id", table_name="requirement_records")
    op.drop_index("ix_requirement_records_lead_id", table_name="requirement_records")
    op.drop_table("requirement_records")
    op.drop_index("ix_conversation_logs_task_id", table_name="conversation_logs")
    op.drop_index("ix_conversation_logs_lead_id", table_name="conversation_logs")
    op.drop_table("conversation_logs")
    op.drop_index("ix_approval_requests_proposal_id", table_name="approval_requests")
    op.drop_column("approval_requests", "proposal_id")