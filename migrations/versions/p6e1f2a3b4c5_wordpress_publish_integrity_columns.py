"""Add tenant org_id and verified WordPress publication columns to seo_draft_records (Issue #12).

Revision ID: p6e1f2a3b4c5
Revises: o5d0e1f2a3b4
Create Date: 2026-11-21 17:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "p6e1f2a3b4c5"
down_revision = "o5d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("seo_draft_records") as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("provider_post_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("canonical_url", sa.String(length=2048), nullable=True))
        batch_op.add_column(sa.Column("publish_metadata", sa.JSON(), nullable=True))
        batch_op.create_index("ix_seo_draft_records_org_id", ["org_id"])
        batch_op.create_index("ix_seo_draft_records_provider_post_id", ["provider_post_id"])


def downgrade() -> None:
    with op.batch_alter_table("seo_draft_records") as batch_op:
        batch_op.drop_index("ix_seo_draft_records_provider_post_id")
        batch_op.drop_index("ix_seo_draft_records_org_id")
        batch_op.drop_column("publish_metadata")
        batch_op.drop_column("canonical_url")
        batch_op.drop_column("provider_post_id")
        batch_op.drop_column("org_id")
