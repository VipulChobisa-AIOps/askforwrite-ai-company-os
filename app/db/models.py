"""Persistent task, lead, audit, and idempotency records."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class TaskRecord(Base):
    __tablename__ = "task_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    objective: Mapped[str] = mapped_column(String(500))
    status: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class LeadRecordRow(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("org_id", "domain", name="uq_leads_org_domain"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(250), nullable=True, index=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    company: Mapped[str] = mapped_column(String(250))
    website: Mapped[str] = mapped_column(String(2048))
    industry: Mapped[str] = mapped_column(String(250))
    geography: Mapped[str] = mapped_column(String(250))
    observed_signals: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    product_match: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    public_contact_channel: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recommended_next_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    do_not_contact: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(32), index=True)
    last_checked: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    capability_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    input_payload: Mapped[dict] = mapped_column(JSON)
    output_payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("capability_name", "idempotency_key", name="uq_idempotency_capability_key"),
        Index("ix_idempotency_task_id", "task_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    capability_name: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str] = mapped_column(String(36))
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_approval_idempotency_key"),
        Index("ix_approval_task_status", "task_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    lead_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    proposal_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    requested_by: Mapped[str] = mapped_column(String(100))
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationRecord(Base):
    __tablename__ = "conversation_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id: Mapped[str] = mapped_column(String(36), index=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    channel: Mapped[str] = mapped_column(String(32))
    notes: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class RequirementRecord(Base):
    __tablename__ = "requirement_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    customer_company: Mapped[str] = mapped_column(String(250))
    stated_needs: Mapped[list] = mapped_column(JSON)
    has_budget_signal: Mapped[bool] = mapped_column()
    has_timeline: Mapped[bool] = mapped_column()
    constraints: Mapped[list] = mapped_column(JSON)
    product_match: Mapped[str | None] = mapped_column(String(100), nullable=True)
    priority: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ProposalRecord(Base):
    __tablename__ = "proposal_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    requirement_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    lead_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    scope: Mapped[list] = mapped_column(JSON, nullable=True, default=list)
    pricing_model: Mapped[str | None] = mapped_column(String(100), nullable=True, default="")
    status: Mapped[str] = mapped_column(String(32))
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeliveryRecord(Base):
    __tablename__ = "delivery_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    proposal_id: Mapped[str] = mapped_column(String(36), index=True)
    customer_company: Mapped[str] = mapped_column(String(250))
    summary: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ResearchRecord(Base):
    __tablename__ = "research_records"
    __table_args__ = (
        UniqueConstraint("lead_id", "idempotency_key", name="uq_research_lead_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id: Mapped[str] = mapped_column(String(36), index=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    source_hash: Mapped[str] = mapped_column(String(64))
    synthesis: Mapped[str] = mapped_column(Text)
    analysis: Mapped[dict] = mapped_column(JSON)
    sources: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class TrustBlock(Base):
    __tablename__ = "trust_blocks"

    index: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    capability_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    payload_data: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    block_hash: Mapped[str] = mapped_column(String(64), index=True)
    signature: Mapped[str] = mapped_column(Text)
    public_key: Mapped[str] = mapped_column(Text)
    sealed_by: Mapped[str] = mapped_column(String(100))


class OrderRecord(Base):
    __tablename__ = "order_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id: Mapped[str] = mapped_column(String(100), index=True, unique=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10))
    customer_email: Mapped[str] = mapped_column(String(250))
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class SeoDraftRecord(Base):
    __tablename__ = "seo_draft_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    target_network: Mapped[str] = mapped_column(String(100))
    keywords: Mapped[list] = mapped_column(JSON)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketingCampaignRecord(Base):
    __tablename__ = "marketing_campaign_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    campaign_type: Mapped[str] = mapped_column(String(100))
    target_audience: Mapped[str] = mapped_column(String(250))
    ad_copy: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrganizationRecord(Base):
    """Multi-tenant organization entity."""
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    tier: Mapped[str] = mapped_column(String(50), default="free")  # "free" | "starter" | "pro" | "enterprise"
    lead_credits_limit: Mapped[int] = mapped_column(Integer, default=50)
    lead_credits_used: Mapped[int] = mapped_column(Integer, default=0)
    outreach_credits_limit: Mapped[int] = mapped_column(Integer, default=20)
    outreach_credits_used: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class UserRecord(Base):
    """Team user belonging to an organization."""
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_user_org_email"),
        Index("ix_users_org", "org_id"),
        Index("ix_users_email", "email"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36))
    email: Mapped[str] = mapped_column(String(250))
    full_name: Mapped[str] = mapped_column(String(250))
    role: Mapped[str] = mapped_column(String(32), default="member")  # "owner" | "admin" | "member" | "customer"
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class InvoiceRecord(Base):
    """Invoice / receipt record for billing transactions."""
    __tablename__ = "invoice_records"
    __table_args__ = (
        Index("ix_invoice_org", "org_id"),
        Index("ix_invoice_customer", "customer_id"),
        Index("ix_invoice_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36))
    customer_id: Mapped[str] = mapped_column(String(36))
    subscription_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32))  # "razorpay" | "paypal"
    provider_invoice_id: Mapped[str] = mapped_column(String(200), index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    amount: Mapped[int] = mapped_column(Integer)  # in paise / cents
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    status: Mapped[str] = mapped_column(String(32))  # "issued" | "paid" | "failed" | "cancelled" | "refunded"
    billing_period_start: Mapped[str | None] = mapped_column(String(64), nullable=True)
    billing_period_end: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hosted_invoice_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class CustomerRecord(Base):
    """Payment customer synced from Razorpay / PayPal."""
    __tablename__ = "customer_records"
    __table_args__ = (
        UniqueConstraint("provider", "provider_customer_id", name="uq_customer_provider_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(250), index=True)
    name: Mapped[str] = mapped_column(String(250))
    provider: Mapped[str] = mapped_column(String(32))  # "razorpay" | "paypal"
    provider_customer_id: Mapped[str] = mapped_column(String(200), index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class SubscriptionRecord(Base):
    """Subscription synced from Razorpay / PayPal."""
    __tablename__ = "subscription_records"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subscription_id", name="uq_sub_provider_id"),
        Index("ix_sub_customer", "customer_id"),
        Index("ix_sub_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(36), index=True)
    plan_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider: Mapped[str] = mapped_column(String(32))  # "razorpay" | "paypal"
    provider_subscription_id: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(32))
    current_period_start: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_period_end: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class WebhookEventRecord(Base):
    """Persisted payment webhook events for audit trail."""
    __tablename__ = "webhook_event_records"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_webhook_provider_event"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider: Mapped[str] = mapped_column(String(32))
    provider_event_id: Mapped[str] = mapped_column(String(200), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    raw_event_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str] = mapped_column(String(200), index=True)
    resource_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON)
    processed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class OutreachRecord(Base):
    """Owner-governed customer outreach message entity."""
    __tablename__ = "outreach_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    lead_id: Mapped[str] = mapped_column(String(36), index=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    recipient_email: Mapped[str] = mapped_column(String(250))
    recipient_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    subject: Mapped[str] = mapped_column(String(300))
    body_text: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(32), default="email")
    status: Mapped[str] = mapped_column(String(32), index=True, default="PENDING_APPROVAL")
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class GeofenceDefinition(Base):
    """Geofence site/hub definition for zero-trust presence verification."""
    __tablename__ = "geofence_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    radius_meters: Mapped[float] = mapped_column(Float, default=150.0)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class FieldAttendanceRecord(Base):
    """Zero-trust cryptographically sealed attendance log with anti-spoofing flags."""
    __tablename__ = "field_attendance_records"
    __table_args__ = (
        Index("ix_attendance_user_ts", "user_id", "timestamp"),
        Index("ix_attendance_org_ts", "org_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(32))  # "CHECK_IN" | "CHECK_OUT" | "HEARTBEAT"
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    accuracy_meters: Mapped[float] = mapped_column(Float)
    altitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    device_fingerprint: Mapped[str] = mapped_column(String(128))
    is_mock_location_detected: Mapped[bool] = mapped_column(default=False)
    wifi_bssid_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cell_tower_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    geofence_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32))  # "VERIFIED" | "SPOOF_REJECTED" | "OUT_OF_BOUNDS"
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    trust_block_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class FieldTaskRecord(Base):
    """Field service assignment, client visit, or delivery task."""
    __tablename__ = "field_task_records"
    __table_args__ = (
        Index("ix_field_task_org_status", "org_id", "status"),
        Index("ix_field_task_assigned_status", "assigned_to_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    assigned_to_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_name: Mapped[str] = mapped_column(String(200))
    destination_lat: Mapped[float] = mapped_column(Float)
    destination_lon: Mapped[float] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String(32), default="NORMAL")  # "URGENT" | "HIGH" | "NORMAL" | "LOW"
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)  # "PENDING" | "ASSIGNED" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED"
    route_sequence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ClientVisitRecord(Base):
    """Multimodal proof-of-execution, geo-verification, and voice debrief record."""
    __tablename__ = "client_visit_records"
    __table_args__ = (
        Index("ix_visit_org_client", "org_id", "client_name"),
        Index("ix_visit_user_completed", "user_id", "completed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    client_name: Mapped[str] = mapped_column(String(200))
    visit_lat: Mapped[float] = mapped_column(Float)
    visit_lon: Mapped[float] = mapped_column(Float)
    distance_from_site_meters: Mapped[float] = mapped_column(Float)
    geo_otp_verified: Mapped[bool] = mapped_column(default=False)
    photo_evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    photo_verification_status: Mapped[str] = mapped_column(String(32), default="VERIFIED")  # "VERIFIED" | "REJECTED" | "FLAGGED"
    photo_analysis_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    voice_audio_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    crm_debrief_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trust_block_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ConveyanceClaimRecord(Base):
    """Fraud-proof distance calculation, mileage reimbursement, and policy settlement record."""
    __tablename__ = "conveyance_claim_records"
    __table_args__ = (
        Index("ix_conveyance_user_date", "user_id", "claim_date"),
        Index("ix_conveyance_org_status", "org_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_date: Mapped[str] = mapped_column(String(10), index=True)  # "YYYY-MM-DD"
    transport_mode: Mapped[str] = mapped_column(String(32), default="TWO_WHEELER")  # "TWO_WHEELER" | "FOUR_WHEELER" | "PUBLIC_TRANSIT"
    raw_gps_distance_km: Mapped[float] = mapped_column(Float)
    verified_road_distance_km: Mapped[float] = mapped_column(Float)
    jitter_filtered_km: Mapped[float] = mapped_column(Float)
    rate_per_km: Mapped[float] = mapped_column(Float)
    total_conveyance_amount: Mapped[float] = mapped_column(Float)
    total_expenses_amount: Mapped[float] = mapped_column(Float, default=0.0)
    grand_total_amount: Mapped[float] = mapped_column(Float)
    receipt_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="AUTO_APPROVED", index=True)  # "AUTO_APPROVED" | "FLAGGED_FOR_REVIEW" | "REJECTED" | "MANUALLY_APPROVED"
    discrepancy_flags: Mapped[list] = mapped_column(JSON, default=list)
    trust_block_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ExpenseReceiptRecord(Base):
    """Itemized receipt verified via OCR and cross-matched against shift route."""
    __tablename__ = "expense_receipt_records"
    __table_args__ = (
        Index("ix_expense_claim_id", "claim_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    claim_id: Mapped[str] = mapped_column(String(36), index=True)
    category: Mapped[str] = mapped_column(String(32))  # "FUEL" | "TOLL" | "PARKING" | "MEAL" | "OTHER"
    amount: Mapped[float] = mapped_column(Float)
    merchant_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    receipt_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(String(64))
    ocr_extracted_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_verified: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class SupervisorAlertRecord(Base):
    """Proactive real-time operational alerts generated by the 24/7 AI Supervisor Co-Pilot."""
    __tablename__ = "supervisor_alert_records"
    __table_args__ = (
        Index("ix_alert_org_acknowledged", "org_id", "is_acknowledged"),
        Index("ix_alert_user_severity", "user_id", "severity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    alert_type: Mapped[str] = mapped_column(String(64))  # "STALLED_AGENT" | "SLA_BREACH_RISK" | "GEOFENCE_BREACH" | "SPOOF_ATTEMPT"
    severity: Mapped[str] = mapped_column(String(32), default="HIGH")  # "CRITICAL" | "HIGH" | "MEDIUM" | "INFO"
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_acknowledged: Mapped[bool] = mapped_column(default=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


def _reject_audit_mutation(mapper, connection, target) -> None:
    raise ValueError("Audit records are append-only")


def _reject_block_mutation(mapper, connection, target) -> None:
    raise ValueError("Trust blocks are append-only and cryptographically immutable")


def _reject_attendance_mutation(mapper, connection, target) -> None:
    raise ValueError("Attendance records are append-only and cryptographically immutable")


def _reject_visit_mutation(mapper, connection, target) -> None:
    raise ValueError("Client visit records are append-only and cryptographically immutable")


def _reject_claim_mutation(mapper, connection, target) -> None:
    raise ValueError("Conveyance claims are append-only and cryptographically immutable")


event.listen(AuditLog, "before_update", _reject_audit_mutation)
event.listen(AuditLog, "before_delete", _reject_audit_mutation)
event.listen(TrustBlock, "before_update", _reject_block_mutation)
event.listen(TrustBlock, "before_delete", _reject_block_mutation)
event.listen(FieldAttendanceRecord, "before_update", _reject_attendance_mutation)
event.listen(FieldAttendanceRecord, "before_delete", _reject_attendance_mutation)
event.listen(ClientVisitRecord, "before_update", _reject_visit_mutation)
event.listen(ClientVisitRecord, "before_delete", _reject_visit_mutation)
event.listen(ConveyanceClaimRecord, "before_update", _reject_claim_mutation)
event.listen(ConveyanceClaimRecord, "before_delete", _reject_claim_mutation)