"""Phase 2 FieldGuard commercialization: real Geo-OTP, travel policies, multi-day tours, manager claim review, and receipt anti-fraud columns.

Revision ID: r8g3b4c5d6e7
Revises: q7f2a3b4c5d6
Create Date: 2026-11-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "r8g3b4c5d6e7"
down_revision = "q7f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Extend conveyance_claim_records with tour linkage & honest distance method disclosure
    op.add_column(
        "conveyance_claim_records",
        sa.Column("tour_plan_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "conveyance_claim_records",
        sa.Column(
            "distance_method",
            sa.String(length=64),
            nullable=False,
            server_default="HAVERSINE_CURVATURE_ESTIMATE",
        ),
    )
    op.create_index("ix_conveyance_claim_records_tour_plan_id", "conveyance_claim_records", ["tour_plan_id"])

    # 2. Extend expense_receipt_records for cross-claim dedup, pHash, GSTIN/invoice & durable storage
    op.add_column("expense_receipt_records", sa.Column("org_id", sa.String(length=36), nullable=True))
    op.add_column("expense_receipt_records", sa.Column("perceptual_hash", sa.String(length=32), nullable=True))
    op.add_column("expense_receipt_records", sa.Column("invoice_number", sa.String(length=100), nullable=True))
    op.add_column("expense_receipt_records", sa.Column("gstin", sa.String(length=32), nullable=True))
    op.add_column("expense_receipt_records", sa.Column("ocr_confidence", sa.Float(), nullable=True))
    op.add_column("expense_receipt_records", sa.Column("ocr_provider", sa.String(length=64), nullable=True))
    op.add_column("expense_receipt_records", sa.Column("storage_uri", sa.String(length=500), nullable=True))
    op.create_index("ix_expense_receipt_records_org_id", "expense_receipt_records", ["org_id"])
    op.create_index("ix_expense_receipt_records_receipt_hash", "expense_receipt_records", ["receipt_hash"])
    op.create_index("ix_expense_receipt_records_perceptual_hash", "expense_receipt_records", ["perceptual_hash"])
    op.create_index("ix_expense_receipt_records_invoice_number", "expense_receipt_records", ["invoice_number"])
    op.create_index("ix_expense_org_hash", "expense_receipt_records", ["org_id", "receipt_hash"])
    op.create_index("ix_expense_org_phash", "expense_receipt_records", ["org_id", "perceptual_hash"])

    # 3. Server-issued time-bound single-use Geo-OTP table
    op.create_table(
        "field_visit_otps",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("client_contact", sa.String(length=250), nullable=True),
        sa.Column("delivery_channel", sa.String(length=32), nullable=False, server_default="EMAIL"),
        sa.Column("otp_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="ACTIVE"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_field_visit_otps_org_id", "field_visit_otps", ["org_id"])
    op.create_index("ix_field_visit_otps_task_id", "field_visit_otps", ["task_id"])
    op.create_index("ix_field_visit_otps_task_status", "field_visit_otps", ["task_id", "status"])

    # 4. Per-org & grade configurable Travel & Conveyance Policy table
    op.create_table(
        "field_expense_policies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("grade", sa.String(length=32), nullable=False, server_default="DEFAULT"),
        sa.Column("two_wheeler_rate_inr", sa.Float(), nullable=False, server_default="4.5"),
        sa.Column("four_wheeler_rate_inr", sa.Float(), nullable=False, server_default="10.0"),
        sa.Column("public_transit_rate_inr", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("daily_auto_approve_limit_inr", sa.Float(), nullable=False, server_default="2000.0"),
        sa.Column("max_daily_distance_km", sa.Float(), nullable=False, server_default="250.0"),
        sa.Column("tier1_da_inr", sa.Float(), nullable=False, server_default="800.0"),
        sa.Column("tier2_da_inr", sa.Float(), nullable=False, server_default="600.0"),
        sa.Column("tier3_da_inr", sa.Float(), nullable=False, server_default="450.0"),
        sa.Column("tier1_hotel_cap_inr", sa.Float(), nullable=False, server_default="3500.0"),
        sa.Column("tier2_hotel_cap_inr", sa.Float(), nullable=False, server_default="2200.0"),
        sa.Column("tier3_hotel_cap_inr", sa.Float(), nullable=False, server_default="1500.0"),
        sa.Column("fuel_max_inr_per_km", sa.Float(), nullable=False, server_default="15.0"),
        sa.Column("require_ocr_above_inr", sa.Float(), nullable=False, server_default="200.0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "grade", name="uq_field_expense_policy_org_grade"),
    )
    op.create_index("ix_field_expense_policies_org_id", "field_expense_policies", ["org_id"])

    # 5. Multi-day Outstation Tour Plans table
    op.create_table(
        "field_tour_plans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("start_date", sa.String(length=10), nullable=False),
        sa.Column("end_date", sa.String(length=10), nullable=False),
        sa.Column("cities_json", sa.JSON(), nullable=False),
        sa.Column("client_targets_json", sa.JSON(), nullable=False),
        sa.Column("estimated_budget_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("advance_requested_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("advance_approved_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="SUBMITTED"),
        sa.Column("approved_by", sa.String(length=250), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_notes", sa.Text(), nullable=True),
        sa.Column("settlement_summary_json", sa.JSON(), nullable=True),
        sa.Column("settlement_trust_block_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_field_tour_plans_org_status", "field_tour_plans", ["org_id", "status"])
    op.create_index("ix_field_tour_plans_user_id", "field_tour_plans", ["user_id"])

    # 6. Append-only Manager Conveyance Claim Review table (preserves claim immutability)
    op.create_table(
        "conveyance_claim_reviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("claimed_amount_inr", sa.Float(), nullable=False),
        sa.Column("approved_amount_inr", sa.Float(), nullable=False),
        sa.Column("reviewer_user_id", sa.String(length=64), nullable=True),
        sa.Column("reviewer_email", sa.String(length=250), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("trust_block_hash", sa.String(length=64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conveyance_claim_reviews_claim_id", "conveyance_claim_reviews", ["claim_id"])
    op.create_index("ix_conveyance_claim_reviews_org_id", "conveyance_claim_reviews", ["org_id"])


def downgrade() -> None:
    op.drop_table("conveyance_claim_reviews")
    op.drop_table("field_tour_plans")
    op.drop_table("field_expense_policies")
    op.drop_table("field_visit_otps")

    for idx_name in (
        "ix_expense_org_phash",
        "ix_expense_org_hash",
        "ix_expense_receipt_records_invoice_number",
        "ix_expense_receipt_records_perceptual_hash",
        "ix_expense_receipt_records_receipt_hash",
        "ix_expense_receipt_records_org_id",
    ):
        op.drop_index(idx_name, table_name="expense_receipt_records")

    with op.batch_alter_table("expense_receipt_records") as batch_op:
        batch_op.drop_column("storage_uri")
        batch_op.drop_column("ocr_provider")
        batch_op.drop_column("ocr_confidence")
        batch_op.drop_column("gstin")
        batch_op.drop_column("invoice_number")
        batch_op.drop_column("perceptual_hash")
        batch_op.drop_column("org_id")

    op.drop_index("ix_conveyance_claim_records_tour_plan_id", table_name="conveyance_claim_records")
    with op.batch_alter_table("conveyance_claim_records") as batch_op:
        batch_op.drop_column("distance_method")
        batch_op.drop_column("tour_plan_id")
