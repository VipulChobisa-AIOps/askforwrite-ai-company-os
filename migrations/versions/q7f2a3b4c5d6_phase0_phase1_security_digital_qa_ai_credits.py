"""Phase 0 & 1 hardening: persistent revoked_tokens, Digital QA protocol/report tables, and managed AI credit pool columns.

Revision ID: q7f2a3b4c5d6
Revises: p6e1f2a3b4c5
Create Date: 2026-11-28 13:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "q7f2a3b4c5d6"
down_revision = "p6e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.add_column(sa.Column("ai_credits_limit", sa.Integer(), nullable=False, server_default="150"))
        batch_op.add_column(sa.Column("ai_credits_used", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("ai_daily_spend_cap_inr", sa.Float(), nullable=False, server_default="100.0"))
        batch_op.add_column(
            sa.Column("ai_billing_mode", sa.String(length=32), nullable=False, server_default="MANAGED_CREDITS")
        )

    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(length=128), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=False, server_default="logout"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_revoked_tokens_user_id", "revoked_tokens", ["user_id"])
    op.create_index("ix_revoked_tokens_org_id", "revoked_tokens", ["org_id"])
    op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"])

    op.create_table(
        "digital_qa_protocols",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("min_score", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("min_word_count", sa.Integer(), nullable=False, server_default="800"),
        sa.Column("max_word_count", sa.Integer(), nullable=False, server_default="4500"),
        sa.Column("require_schema_ld", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("require_faq", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("require_live_llm", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("brand_voice", sa.String(length=250), nullable=False, server_default="authoritative, truthful, non-promotional"),
        sa.Column("mandatory_terms_json", sa.JSON(), nullable=True),
        sa.Column("forbidden_terms_json", sa.JSON(), nullable=True),
        sa.Column("banned_slop_phrases_json", sa.JSON(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_digital_qa_protocols_org_id", "digital_qa_protocols", ["org_id"])
    op.create_index("ix_digital_qa_protocols_is_default", "digital_qa_protocols", ["is_default"])

    op.create_table(
        "digital_qa_reports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("receipt_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("protocol_id", sa.String(length=36), nullable=True),
        sa.Column("draft_id", sa.String(length=36), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("target_url", sa.String(length=2048), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("output_origin", sa.String(length=64), nullable=False, server_default="LIVE_PROVIDER_VERIFIED"),
        sa.Column("checks_json", sa.JSON(), nullable=True),
        sa.Column("defects_json", sa.JSON(), nullable=True),
        sa.Column("flagged_claims_json", sa.JSON(), nullable=True),
        sa.Column("human_reviewer", sa.String(length=250), nullable=True),
        sa.Column("human_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("trust_block_index", sa.Integer(), nullable=True),
        sa.Column("trust_block_hash", sa.String(length=64), nullable=True),
        sa.Column("trust_signature", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_digital_qa_reports_receipt_id", "digital_qa_reports", ["receipt_id"], unique=True)
    op.create_index("ix_digital_qa_reports_org_id", "digital_qa_reports", ["org_id"])
    op.create_index("ix_digital_qa_reports_protocol_id", "digital_qa_reports", ["protocol_id"])
    op.create_index("ix_digital_qa_reports_draft_id", "digital_qa_reports", ["draft_id"])
    op.create_index("ix_digital_qa_reports_task_id", "digital_qa_reports", ["task_id"])
    op.create_index("ix_digital_qa_reports_passed", "digital_qa_reports", ["passed"])


def downgrade() -> None:
    op.drop_index("ix_digital_qa_reports_passed", table_name="digital_qa_reports")
    op.drop_index("ix_digital_qa_reports_task_id", table_name="digital_qa_reports")
    op.drop_index("ix_digital_qa_reports_draft_id", table_name="digital_qa_reports")
    op.drop_index("ix_digital_qa_reports_protocol_id", table_name="digital_qa_reports")
    op.drop_index("ix_digital_qa_reports_org_id", table_name="digital_qa_reports")
    op.drop_index("ix_digital_qa_reports_receipt_id", table_name="digital_qa_reports")
    op.drop_table("digital_qa_reports")

    op.drop_index("ix_digital_qa_protocols_is_default", table_name="digital_qa_protocols")
    op.drop_index("ix_digital_qa_protocols_org_id", table_name="digital_qa_protocols")
    op.drop_table("digital_qa_protocols")

    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_org_id", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_user_id", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")

    with op.batch_alter_table("organizations") as batch_op:
        batch_op.drop_column("ai_billing_mode")
        batch_op.drop_column("ai_daily_spend_cap_inr")
        batch_op.drop_column("ai_credits_used")
        batch_op.drop_column("ai_credits_limit")
