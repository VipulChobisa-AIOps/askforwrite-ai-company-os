"""Phase 3 StockSense persistent multi-tenant SME WMS, double-entry stock ledger, FEFO picking, cycle count & 3PL billing.

Revision ID: s9h4c5d6e7f8
Revises: r8g3b4c5d6e7
Create Date: 2026-11-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "s9h4c5d6e7f8"
down_revision = "r8g3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "warehouses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False, server_default="Jaipur"),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("total_area_sqft", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("is_3pl_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "code", name="uq_warehouse_org_code"),
    )
    op.create_index("ix_warehouses_org_id", "warehouses", ["org_id"])

    op.create_table(
        "warehouse_zones",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("warehouse_id", sa.String(length=36), sa.ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("zone_type", sa.String(length=32), nullable=False, server_default="AMBIENT"),
        sa.Column("temperature_min_c", sa.Float(), nullable=True),
        sa.Column("temperature_max_c", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("warehouse_id", "code", name="uq_warehouse_zone_code"),
    )
    op.create_index("ix_warehouse_zones_org_id", "warehouse_zones", ["org_id"])
    op.create_index("ix_warehouse_zones_warehouse_id", "warehouse_zones", ["warehouse_id"])

    op.create_table(
        "warehouse_bins",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("warehouse_id", sa.String(length=36), sa.ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("zone_id", sa.String(length=36), sa.ForeignKey("warehouse_zones.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bin_code", sa.String(length=64), nullable=False),
        sa.Column("aisle", sa.String(length=32), nullable=False, server_default="A01"),
        sa.Column("rack", sa.String(length=32), nullable=False, server_default="R01"),
        sa.Column("shelf", sa.String(length=32), nullable=False, server_default="S01"),
        sa.Column("velocity_tier", sa.String(length=8), nullable=False, server_default="B"),
        sa.Column("distance_to_dispatch_m", sa.Float(), nullable=False, server_default="20.0"),
        sa.Column("max_weight_kg", sa.Float(), nullable=False, server_default="1000.0"),
        sa.Column("max_volume_cbm", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("max_pallet_slots", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("warehouse_id", "bin_code", name="uq_warehouse_bin_code"),
    )
    op.create_index("ix_warehouse_bins_org_id", "warehouse_bins", ["org_id"])
    op.create_index("ix_warehouse_bins_wh_zone", "warehouse_bins", ["warehouse_id", "zone_id"])

    op.create_table(
        "warehouse_clients",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("warehouse_id", sa.String(length=36), sa.ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_code", sa.String(length=64), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=False),
        sa.Column("contact_email", sa.String(length=250), nullable=True),
        sa.Column("gstin", sa.String(length=32), nullable=True),
        sa.Column("storage_rate_per_bin_day_inr", sa.Float(), nullable=False, server_default="35.0"),
        sa.Column("inbound_handling_rate_per_unit_inr", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("outbound_pick_rate_per_unit_inr", sa.Float(), nullable=False, server_default="3.5"),
        sa.Column("packing_rate_per_order_inr", sa.Float(), nullable=False, server_default="25.0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("warehouse_id", "client_code", name="uq_warehouse_client_code"),
    )
    op.create_index("ix_warehouse_clients_org_id", "warehouse_clients", ["org_id"])
    op.create_index("ix_warehouse_clients_warehouse_id", "warehouse_clients", ["warehouse_id"])

    op.create_table(
        "warehouse_skus",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("warehouse_id", sa.String(length=36), sa.ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(length=36), sa.ForeignKey("warehouse_clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sku_code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=250), nullable=False),
        sa.Column("barcode", sa.String(length=128), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=False, server_default="General"),
        sa.Column("required_zone_type", sa.String(length=32), nullable=False, server_default="AMBIENT"),
        sa.Column("velocity_tier", sa.String(length=8), nullable=False, server_default="B"),
        sa.Column("unit_cost_inr", sa.Float(), nullable=False, server_default="100.0"),
        sa.Column("unit_weight_kg", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("requires_expiry_tracking", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lead_time_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("reorder_point", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("eoq_qty", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("warehouse_id", "sku_code", name="uq_warehouse_sku_code"),
    )
    op.create_index("ix_warehouse_skus_org_id", "warehouse_skus", ["org_id"])
    op.create_index("ix_warehouse_skus_barcode", "warehouse_skus", ["warehouse_id", "barcode"])

    op.create_table(
        "stock_balances",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("warehouse_id", sa.String(length=36), sa.ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bin_id", sa.String(length=36), sa.ForeignKey("warehouse_bins.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", sa.String(length=36), sa.ForeignKey("warehouse_skus.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=True),
        sa.Column("batch_no", sa.String(length=80), nullable=False, server_default="DEFAULT"),
        sa.Column("expiry_date", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("qty_on_hand", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qty_reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qty_damaged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("warehouse_id", "bin_id", "sku_id", "batch_no", "expiry_date", name="uq_stock_balance_lot"),
    )
    op.create_index("ix_stock_balance_fefo", "stock_balances", ["warehouse_id", "sku_id", "expiry_date"])

    op.create_table(
        "stock_ledger_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("warehouse_id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=True),
        sa.Column("sku_id", sa.String(length=36), nullable=False),
        sa.Column("from_bin_id", sa.String(length=36), nullable=True),
        sa.Column("to_bin_id", sa.String(length=36), nullable=True),
        sa.Column("movement_type", sa.String(length=32), nullable=False),
        sa.Column("batch_no", sa.String(length=80), nullable=False, server_default="DEFAULT"),
        sa.Column("expiry_date", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(length=32), nullable=False, server_default="MANUAL"),
        sa.Column("reference_id", sa.String(length=100), nullable=True),
        sa.Column("operator_id", sa.String(length=250), nullable=False, server_default="system"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("trust_block_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stock_ledger_wh_sku_ts", "stock_ledger_entries", ["warehouse_id", "sku_id", "created_at"])
    op.create_index("ix_stock_ledger_client_ts", "stock_ledger_entries", ["client_id", "movement_type", "created_at"])

    op.create_table(
        "warehouse_grns",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("warehouse_id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=True),
        sa.Column("po_number", sa.String(length=100), nullable=False),
        sa.Column("supplier_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="RECEIVED"),
        sa.Column("lines_json", sa.JSON(), nullable=False),
        sa.Column("discrepancy_summary_json", sa.JSON(), nullable=False),
        sa.Column("qr_labels_json", sa.JSON(), nullable=False),
        sa.Column("received_by", sa.String(length=250), nullable=False, server_default="system"),
        sa.Column("trust_block_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_warehouse_grns_warehouse_id", "warehouse_grns", ["warehouse_id"])

    op.create_table(
        "warehouse_pick_waves",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("warehouse_id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=True),
        sa.Column("order_reference", sa.String(length=120), nullable=False),
        sa.Column("channel_source", sa.String(length=32), nullable=False, server_default="MANUAL"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="OPEN"),
        sa.Column("pick_lines_json", sa.JSON(), nullable=False),
        sa.Column("blocked_expired_lots_json", sa.JSON(), nullable=False),
        sa.Column("shortfalls_json", sa.JSON(), nullable=False),
        sa.Column("dispatched_by", sa.String(length=250), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trust_block_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_warehouse_pick_waves_wh_status", "warehouse_pick_waves", ["warehouse_id", "status"])

    op.create_table(
        "warehouse_cycle_counts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("warehouse_id", sa.String(length=36), nullable=False),
        sa.Column("bin_id", sa.String(length=36), nullable=False),
        sa.Column("sku_id", sa.String(length=36), nullable=False),
        sa.Column("batch_no", sa.String(length=80), nullable=False, server_default="DEFAULT"),
        sa.Column("expiry_date", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("system_qty", sa.Integer(), nullable=False),
        sa.Column("counted_qty", sa.Integer(), nullable=False),
        sa.Column("variance_qty", sa.Integer(), nullable=False),
        sa.Column("variance_value_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING_APPROVAL"),
        sa.Column("counted_by", sa.String(length=250), nullable=False),
        sa.Column("approved_by", sa.String(length=250), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("trust_block_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_warehouse_cycle_counts_wh_status", "warehouse_cycle_counts", ["warehouse_id", "status"])

    op.create_table(
        "warehouse_3pl_invoices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("warehouse_id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("invoice_number", sa.String(length=64), unique=True, nullable=False),
        sa.Column("billing_month", sa.String(length=7), nullable=False),
        sa.Column("active_bins_billed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("billing_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("inbound_units_billed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outbound_units_billed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orders_packed_billed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_charge_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("inbound_charge_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("outbound_charge_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("packing_charge_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("subtotal_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("gst_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_inr", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("line_items_json", sa.JSON(), nullable=False),
        sa.Column("audit_sha256", sa.String(length=64), nullable=False),
        sa.Column("trust_block_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_warehouse_3pl_invoices_client_month", "warehouse_3pl_invoices", ["client_id", "billing_month"])

    op.create_table(
        "inventory_uat_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=64), nullable=True),
        sa.Column("operator_id", sa.String(length=200), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("discrepancy_reported", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("inventory_uat_records")
    op.drop_table("warehouse_3pl_invoices")
    op.drop_table("warehouse_cycle_counts")
    op.drop_table("warehouse_pick_waves")
    op.drop_table("warehouse_grns")
    op.drop_table("stock_ledger_entries")
    op.drop_table("stock_balances")
    op.drop_table("warehouse_skus")
    op.drop_table("warehouse_clients")
    op.drop_table("warehouse_bins")
    op.drop_table("warehouse_zones")
    op.drop_table("warehouses")
