"""Pydantic schemas for AskforWrite Autonomous Field Force Engine."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GeofenceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200, description="Name of the hub or client site")
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    radius_meters: float = Field(default=150.0, ge=10.0, le=50000.0, description="Geofence boundary radius")
    address: str | None = Field(default=None, max_length=500)


class GeofenceResponse(BaseModel):
    id: str
    org_id: str | None
    name: str
    latitude: float
    longitude: float
    radius_meters: float
    address: str | None
    is_active: bool
    created_at: datetime


class AttendanceCheckInRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    accuracy_meters: float = Field(default=10.0, ge=0.0, description="GPS sensor accuracy radius")
    altitude: float | None = Field(default=None)
    device_fingerprint: str = Field(min_length=8, max_length=128, description="Hardware/device unique hash")
    is_mock_provider: bool = Field(default=False, description="OS-level Mock Location / Fake GPS flag")
    wifi_bssid_hash: str | None = Field(default=None, max_length=64, description="SHA256 hash of connected Wi-Fi BSSID")
    cell_tower_id: str | None = Field(default=None, max_length=64, description="Cellular tower LAC/CID identifier")
    geofence_id: str | None = Field(default=None, max_length=36, description="Target assigned geofence if required")
    idempotency_key: str = Field(min_length=8, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AttendanceCheckOutRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    accuracy_meters: float = Field(default=10.0, ge=0.0)
    device_fingerprint: str = Field(min_length=8, max_length=128)
    is_mock_provider: bool = Field(default=False)
    idempotency_key: str = Field(min_length=8, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AttendanceRecordResponse(BaseModel):
    id: str
    org_id: str | None
    user_id: str
    event_type: str
    latitude: float
    longitude: float
    accuracy_meters: float
    status: str  # "VERIFIED", "SPOOF_REJECTED", "OUT_OF_BOUNDS"
    is_mock_location_detected: bool
    geofence_id: str | None
    trust_block_hash: str | None
    timestamp: datetime
    verification_notes: str | None


# ── Field Task & Autonomous Dispatch Schemas ──────────────────────────


class FieldTaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=250)
    description: str | None = Field(default=None)
    client_name: str = Field(min_length=2, max_length=200)
    destination_lat: float = Field(ge=-90.0, le=90.0)
    destination_lon: float = Field(ge=-180.0, le=180.0)
    priority: str = Field(default="NORMAL", pattern="^(URGENT|HIGH|NORMAL|LOW)$")
    assigned_to_user_id: str | None = Field(default=None, max_length=36)
    due_at: datetime | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FieldTaskAssign(BaseModel):
    assigned_to_user_id: str = Field(min_length=1, max_length=36)


class FieldTaskResponse(BaseModel):
    id: str
    org_id: str | None
    assigned_to_user_id: str | None
    title: str
    description: str | None
    client_name: str
    destination_lat: float
    destination_lon: float
    priority: str
    status: str
    route_sequence_index: int | None
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


# ── Dynamic Route Optimizer Schemas ───────────────────────────────────


class RouteOptimizationRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    start_latitude: float = Field(ge=-90.0, le=90.0, description="Current live GPS or hub latitude")
    start_longitude: float = Field(ge=-180.0, le=180.0, description="Current live GPS or hub longitude")
    task_ids: list[str] | None = Field(default=None, description="Optional subset of tasks; if omitted, all pending tasks assigned to user are optimized")


class OptimizedStop(BaseModel):
    sequence_index: int
    task_id: str
    title: str
    client_name: str
    destination_lat: float
    destination_lon: float
    priority: str
    leg_distance_km: float
    cumulative_distance_km: float
    estimated_leg_minutes: float


class RouteOptimizationResponse(BaseModel):
    user_id: str
    optimized_stops: list[OptimizedStop]
    total_stops: int
    total_distance_km: float
    estimated_total_minutes: float
    estimated_fuel_savings_percent: float
    summary: str


# ── Multimodal Proof-of-Execution & Visit Debrief Schemas ──────────────


class ClientVisitVerifyRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=36)
    user_id: str = Field(min_length=1, max_length=36)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    accuracy_meters: float = Field(default=10.0, ge=0.0)
    geo_otp_code: str | None = Field(default=None, max_length=10, description="Optional client verification OTP")
    photo_evidence_base64_or_url: str | None = Field(default=None, description="Base64 or URL of captured photo")
    expected_photo_tags: list[str] | None = Field(default=None, description="Tags expected to verify (e.g. shelf, storefront)")
    notes: str | None = Field(default=None)


class VoiceDebriefRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=36)
    user_id: str = Field(min_length=1, max_length=36)
    raw_audio_transcript_or_base64: str = Field(min_length=5, description="Spoken voice transcript or audio data")


class StructuredCrmDebrief(BaseModel):
    meeting_summary: str
    client_sentiment: str  # "POSITIVE" | "NEUTRAL" | "CONCERNED"
    follow_up_action: str
    next_follow_up_date: str | None
    orders_booked: list[dict[str, Any]]
    competitor_mentions: list[str]


class ClientVisitResponse(BaseModel):
    id: str
    task_id: str
    org_id: str | None
    user_id: str
    client_name: str
    visit_lat: float
    visit_lon: float
    distance_from_site_meters: float
    geo_otp_verified: bool
    photo_evidence_hash: str | None
    photo_verification_status: str
    photo_analysis_json: dict[str, Any] | None = None
    crm_debrief_json: dict[str, Any] | None = None
    trust_block_hash: str | None = None
    completed_at: datetime


# ── Fraud-Proof Conveyance & Expense Schemas ───────────────────────────


class GpsBreadcrumb(BaseModel):
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    timestamp: datetime
    speed_kmh: float | None = Field(default=None, ge=0.0)


class ConveyanceCalculateRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    claim_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")
    transport_mode: str = Field(default="TWO_WHEELER", pattern="^(TWO_WHEELER|FOUR_WHEELER|PUBLIC_TRANSIT)$")
    gps_breadcrumbs: list[GpsBreadcrumb] = Field(min_length=2, description="Chronological GPS route points")


class ExpenseReceiptItem(BaseModel):
    category: str = Field(pattern="^(FUEL|TOLL|PARKING|MEAL|OTHER)$")
    amount: float = Field(gt=0.0)
    merchant_name: str | None = Field(default=None, max_length=200)
    receipt_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    receipt_base64_or_hash: str = Field(min_length=8)


class ConveyanceClaimSubmitRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    claim_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    transport_mode: str = Field(default="TWO_WHEELER", pattern="^(TWO_WHEELER|FOUR_WHEELER|PUBLIC_TRANSIT)$")
    gps_breadcrumbs: list[GpsBreadcrumb] = Field(min_length=2)
    receipts: list[ExpenseReceiptItem] | None = Field(default=None)
    notes: str | None = Field(default=None)


class ConveyanceClaimResponse(BaseModel):
    id: str
    org_id: str | None
    user_id: str
    claim_date: str
    transport_mode: str
    raw_gps_distance_km: float
    verified_road_distance_km: float
    jitter_filtered_km: float
    rate_per_km: float
    total_conveyance_amount: float
    total_expenses_amount: float
    grand_total_amount: float
    receipt_count: int
    status: str  # "AUTO_APPROVED" | "FLAGGED_FOR_REVIEW" | "REJECTED" | "MANUALLY_APPROVED"
    discrepancy_flags: list[str]
    trust_block_hash: str | None
    created_at: datetime


