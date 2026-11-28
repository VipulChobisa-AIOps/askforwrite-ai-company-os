"""Pydantic schemas for Phase 3 StockSense Persistent SME Warehouse & 3PL Operations OS."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=200)
    city: str = Field(default="Jaipur", min_length=2, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    total_area_sqft: int = Field(default=10000, ge=500, le=5000000)
    is_3pl_enabled: bool = True


class WarehouseResponse(BaseModel):
    id: str
    org_id: str | None
    code: str
    name: str
    city: str
    address: str | None
    total_area_sqft: int
    is_3pl_enabled: bool
    is_active: bool
    created_at: datetime


class WarehouseZoneCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=200)
    zone_type: str = Field(default="AMBIENT", pattern="^(AMBIENT|COLD_CHAIN|HAZMAT|HIGH_VALUE|STAGING|QUARANTINE)$")
    temperature_min_c: float | None = None
    temperature_max_c: float | None = None


class WarehouseZoneResponse(BaseModel):
    id: str
    warehouse_id: str
    code: str
    name: str
    zone_type: str
    temperature_min_c: float | None
    temperature_max_c: float | None
    is_active: bool


class WarehouseBinCreate(BaseModel):
    zone_id: str = Field(min_length=1, max_length=36)
    bin_code: str = Field(min_length=2, max_length=64)
    aisle: str = Field(default="A01", max_length=32)
    rack: str = Field(default="R01", max_length=32)
    shelf: str = Field(default="S01", max_length=32)
    velocity_tier: str = Field(default="B", pattern="^(A|B|C)$")
    distance_to_dispatch_m: float = Field(default=20.0, ge=0.0, le=5000.0)
    max_weight_kg: float = Field(default=1000.0, gt=0.0)
    max_volume_cbm: float = Field(default=2.5, gt=0.0)
    max_pallet_slots: int = Field(default=2, ge=1, le=100)


class WarehouseBinResponse(BaseModel):
    id: str
    warehouse_id: str
    zone_id: str
    bin_code: str
    aisle: str
    rack: str
    shelf: str
    velocity_tier: str
    distance_to_dispatch_m: float
    max_weight_kg: float
    max_pallet_slots: int
    is_active: bool


class WarehouseClientCreate(BaseModel):
    client_code: str = Field(min_length=2, max_length=64)
    client_name: str = Field(min_length=2, max_length=200)
    contact_email: str | None = Field(default=None, max_length=250)
    gstin: str | None = Field(default=None, max_length=32)
    storage_rate_per_bin_day_inr: float = Field(default=35.0, ge=0.0)
    inbound_handling_rate_per_unit_inr: float = Field(default=2.0, ge=0.0)
    outbound_pick_rate_per_unit_inr: float = Field(default=3.5, ge=0.0)
    packing_rate_per_order_inr: float = Field(default=25.0, ge=0.0)


class WarehouseClientResponse(BaseModel):
    id: str
    warehouse_id: str
    client_code: str
    client_name: str
    contact_email: str | None
    gstin: str | None
    storage_rate_per_bin_day_inr: float
    inbound_handling_rate_per_unit_inr: float
    outbound_pick_rate_per_unit_inr: float
    packing_rate_per_order_inr: float
    is_active: bool


class WarehouseSkuCreate(BaseModel):
    sku_code: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=2, max_length=250)
    barcode: str | None = Field(default=None, max_length=128)
    category: str = Field(default="General", max_length=120)
    client_id: str | None = Field(default=None, max_length=36)
    required_zone_type: str = Field(default="AMBIENT", pattern="^(AMBIENT|COLD_CHAIN|HAZMAT|HIGH_VALUE)$")
    velocity_tier: str = Field(default="B", pattern="^(A|B|C)$")
    unit_cost_inr: float = Field(default=100.0, gt=0.0)
    unit_weight_kg: float = Field(default=0.5, ge=0.0)
    requires_expiry_tracking: bool = False
    lead_time_days: int = Field(default=7, ge=1, le=365)
    reorder_point: int = Field(default=20, ge=0)
    eoq_qty: int = Field(default=100, ge=1)


class WarehouseSkuResponse(BaseModel):
    id: str
    warehouse_id: str
    client_id: str | None
    sku_code: str
    name: str
    barcode: str | None
    category: str
    required_zone_type: str
    velocity_tier: str
    unit_cost_inr: float
    unit_weight_kg: float
    requires_expiry_tracking: bool
    reorder_point: int
    eoq_qty: int
    is_active: bool


class GrnLineInput(BaseModel):
    sku_code: str = Field(min_length=1, max_length=100)
    expected_qty: int = Field(ge=0)
    received_qty: int = Field(ge=0)
    damaged_qty: int = Field(default=0, ge=0)
    batch_no: str = Field(default="DEFAULT", max_length=80)
    expiry_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    target_bin_id: str | None = Field(default=None, max_length=36, description="Optional override; if omitted, Directed Slotting picks optimal bin")
    discrepancy_photo_base64: str | None = None


class GrnReceiveRequest(BaseModel):
    po_number: str = Field(min_length=2, max_length=100)
    supplier_name: str = Field(min_length=2, max_length=200)
    client_id: str | None = Field(default=None, max_length=36)
    lines: list[GrnLineInput] = Field(min_length=1)


class BinTransferRequest(BaseModel):
    sku_code: str = Field(min_length=1, max_length=100)
    from_bin_id: str = Field(min_length=1, max_length=36)
    to_bin_id: str = Field(min_length=1, max_length=36)
    quantity: int = Field(gt=0)
    batch_no: str = Field(default="DEFAULT", max_length=80)
    expiry_date: str = Field(default="", max_length=10)
    notes: str | None = None


class PickOrderLineInput(BaseModel):
    sku_code: str = Field(min_length=1, max_length=100)
    requested_qty: int = Field(gt=0)


class PickWaveCreateRequest(BaseModel):
    order_reference: str = Field(min_length=2, max_length=120)
    channel_source: str = Field(default="MANUAL", pattern="^(MANUAL|SHOPIFY|WOOCOMMERCE|TALLY|ZOHO)$")
    client_id: str | None = Field(default=None, max_length=36)
    lines: list[PickOrderLineInput] = Field(min_length=1)


class CycleCountSubmitRequest(BaseModel):
    bin_id: str = Field(min_length=1, max_length=36)
    sku_code: str = Field(min_length=1, max_length=100)
    batch_no: str = Field(default="DEFAULT", max_length=80)
    expiry_date: str = Field(default="", max_length=10)
    counted_qty: int = Field(ge=0)
    notes: str | None = None


class CycleCountApproveRequest(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT)$")
    notes: str | None = None


class ThreePlInvoiceGenerateRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=36)
    billing_month: str = Field(pattern=r"^\d{4}-\d{2}$")
    billing_days: int = Field(default=30, ge=1, le=31)
    gst_rate_pct: float = Field(default=18.0, ge=0.0, le=28.0)


class CsvImportRequest(BaseModel):
    csv_text: str = Field(min_length=5)
    client_id: str | None = Field(default=None, max_length=36)
    dry_run: bool = True


class ChannelOrderWebhookRequest(BaseModel):
    channel_source: str = Field(default="SHOPIFY", pattern="^(SHOPIFY|WOOCOMMERCE|TALLY|ZOHO)$")
    external_order_id: str = Field(min_length=2, max_length=120)
    client_id: str | None = Field(default=None, max_length=36)
    items: list[PickOrderLineInput] = Field(min_length=1)
