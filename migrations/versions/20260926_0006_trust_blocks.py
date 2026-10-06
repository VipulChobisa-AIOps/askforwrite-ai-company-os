"""Add cryptographically sealed trust blocks table.

Revision ID: 20260926_0006
Revises: 20260926_0005
Create Date: 2026-09-30 16:50:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0006"
down_revision = "20260926_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trust_blocks",
        sa.Column("index", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("capability_name", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("payload_data", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("block_hash", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sealed_by", sa.String(length=100), nullable=False),
    )
    op.create_index("ix_trust_blocks_task_id", "trust_blocks", ["task_id"])
    op.create_index("ix_trust_blocks_block_hash", "trust_blocks", ["block_hash"])


def downgrade() -> None:
    op.drop_index("ix_trust_blocks_block_hash", table_name="trust_blocks")
    op.drop_index("ix_trust_blocks_task_id", table_name="trust_blocks")
    op.drop_table("trust_blocks")
