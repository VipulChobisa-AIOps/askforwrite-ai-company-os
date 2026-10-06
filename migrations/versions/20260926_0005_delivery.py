"""Add verifiable capability delivery records."""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0005"
down_revision = "20260926_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("customer_company", sa.String(length=250), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_delivery_records_task_id", "delivery_records", ["task_id"])
    op.create_index("ix_delivery_records_proposal_id", "delivery_records", ["proposal_id"])


def downgrade() -> None:
    op.drop_index("ix_delivery_records_proposal_id", table_name="delivery_records")
    op.drop_index("ix_delivery_records_task_id", table_name="delivery_records")
    op.drop_table("delivery_records")