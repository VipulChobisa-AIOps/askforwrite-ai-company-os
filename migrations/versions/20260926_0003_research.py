"""Add persisted Research Agent outputs."""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0003"
down_revision = "20260926_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("synthesis", sa.Text(), nullable=False),
        sa.Column("analysis", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "lead_id", "idempotency_key",
            name="uq_research_lead_idempotency_key",
        ),
    )
    op.create_index("ix_research_records_lead_id", "research_records", ["lead_id"])
    op.create_index("ix_research_records_task_id", "research_records", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_research_records_task_id", table_name="research_records")
    op.drop_index("ix_research_records_lead_id", table_name="research_records")
    op.drop_table("research_records")