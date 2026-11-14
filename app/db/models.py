"""Persistent task, lead, audit, and idempotency records."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, synonym

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
    lead_credits_quota = synonym("lead_credits_limit")
    outreach_credits_quota = synonym("outreach_credits_limit")
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


class PreviewRecord(Base):
    """Trojan Horse Proof-First Public Preview entity."""
    __tablename__ = "preview_records"
    __table_args__ = (
        Index("ix_preview_token", "preview_token", unique=True),
        Index("ix_preview_domain", "domain"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    preview_token: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(250))
    domain: Mapped[str] = mapped_column(String(250), index=True)
    recommended_package: Mapped[str] = mapped_column(String(100))
    lead_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    custom_audit: Mapped[dict] = mapped_column(JSON)
    sample_deliverable: Mapped[dict] = mapped_column(JSON)
    benchmarks: Mapped[dict] = mapped_column(JSON)
    payment_links: Mapped[dict] = mapped_column(JSON)
    views_count: Mapped[int] = mapped_column(Integer, default=0)
    trust_block_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ShiftRecord(Base):
    """Autonomous shift execution log and digest record."""
    __tablename__ = "shift_records"
    __table_args__ = (
        Index("ix_shift_id", "shift_id", unique=True),
        Index("ix_shift_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shift_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    shift_type: Mapped[str] = mapped_column(String(64), default="full_daily_cycle")
    status: Mapped[str] = mapped_column(String(32), default="COMPLETED")
    summary: Mapped[dict] = mapped_column(JSON)
    trust_block_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SovereignPaymentSessionRecord(Base):
    """Durable first-party sovereign checkout session surviving restarts and multi-worker routing."""
    __tablename__ = "sovereign_payment_sessions"
    __table_args__ = (
        Index("ix_sovereign_session_status", "status"),
        Index("ix_sovereign_session_email", "customer_email"),
    )

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    package_key: Mapped[str] = mapped_column(String(100), index=True)
    package_name: Mapped[str] = mapped_column(String(250))
    company_name: Mapped[str] = mapped_column(String(250))
    customer_email: Mapped[str] = mapped_column(String(250), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    amount: Mapped[float] = mapped_column(Float)
    preferred_rail: Mapped[str] = mapped_column(String(32), default="upi_direct")
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    upi_uri: Mapped[str] = mapped_column(Text)
    upi_qr_svg: Mapped[str] = mapped_column(Text)
    usdc_payload: Mapped[dict] = mapped_column(JSON)
    bank_wire_invoice: Mapped[dict] = mapped_column(JSON)
    checkout_url: Mapped[str] = mapped_column(String(500))
    verification_proof: Mapped[str | None] = mapped_column(String(250), nullable=True)
    verified_rail: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trust_block_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trust_block_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

# Model aliases for supervisory and watchdog frameworks
ApprovalRequestRecord = ApprovalRequest
FieldTelemetryRecord = FieldAttendanceRecord


# ── P1: Modular SME AI Workforce & Execution Evidence Models ─────────────────


class BusinessProfileRecord(Base):
    """Persisted 13-field SME Business Onboarding Profile and confirmation state."""

    __tablename__ = "business_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    business_name: Mapped[str] = mapped_column(String(250), nullable=False)
    industry: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    location: Mapped[str] = mapped_column(String(250), default="", nullable=False)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contact_info: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    company_size: Mapped[str] = mapped_column(String(64), default="small", nullable=False)
    employee_count: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    products_and_services: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    customer_segments: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    sales_channels: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    current_software: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    operational_pain_points: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    business_objectives: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    required_automations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    expected_monthly_volume: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    recommended_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    selection_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class StructuredRequirementRecord(Base):
    """Structured operational requirements extracted from SME onboarding."""

    __tablename__ = "structured_requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    profile_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="MEDIUM", nullable=False)
    recommended_modules: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    recommended_agents: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    required_connectors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    expected_monthly_credits: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    limitations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="RECOMMENDED", index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class TenantSubscriptionRecord(Base):
    """Canonical modular subscription contract for a tenant organization."""

    __tablename__ = "tenant_subscription_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    internal_sku: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    billing_type: Mapped[str] = mapped_column(String(32), default="recurring", nullable=False)
    billing_interval: Mapped[str] = mapped_column(String(32), default="monthly", nullable=False)
    base_price: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    provider_plan_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    included_modules: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    selected_modules: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    entitled_agents: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    agent_execution_limit: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    included_credits: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    credit_costs: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    seat_limit: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    setup_fee: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    support_level: Mapped[str] = mapped_column(String(64), default="email_standard", nullable=False)
    customization_allowance: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    renewal_policy: Mapped[str] = mapped_column(String(64), default="auto_renew", nullable=False)
    extra_agents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extra_seats: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    credit_packs_purchased: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    integration_addons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    total_recurring_price: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_setup_price: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True, nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class TenantAgentConfigRecord(Base):
    """Per-tenant AI agent activation, configuration, tool allowlist, and execution limit."""

    __tablename__ = "tenant_agent_configs"
    __table_args__ = (
        UniqueConstraint("org_id", "agent_id", name="uq_tenant_agent_config"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DEACTIVATED", index=True, nullable=False)
    model_override: Mapped[str | None] = mapped_column(String(120), nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(32), default="SIMULATION", nullable=False)
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_allowlist: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    execution_limits: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    activated_by: Mapped[str | None] = mapped_column(String(250), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class ConnectorStateRecord(Base):
    """Persistent verification, capability, and masked configuration state per connector."""

    __tablename__ = "connector_states"
    __table_args__ = (
        UniqueConstraint("org_id", "connector_id", name="uq_org_connector_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), default="__platform__", index=True, nullable=False)
    connector_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    service_category: Mapped[str] = mapped_column(String(100), nullable=False)
    authentication_type: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), default="SIMULATION", nullable=False)
    connection_status: Mapped[str] = mapped_column(String(32), default="UNVERIFIED", nullable=False)
    capability_state: Mapped[str] = mapped_column(String(32), default="SIMULATED", nullable=False)
    config_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class WorkflowDefinitionRecord(Base):
    """Persisted multi-step SME automation workflow template/definition."""

    __tablename__ = "workflow_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    schedule_cron: Mapped[str | None] = mapped_column(String(100), nullable=True)
    max_credits_budget: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    execution_mode_default: Mapped[str] = mapped_column(String(32), default="SIMULATION", nullable=False)
    steps_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[str] = mapped_column(String(250), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class WorkflowRunRecord(Base):
    """Persisted workflow execution instance following the strict 8-state FSM."""

    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), index=True, nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(32), default="SIMULATION", index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True, nullable=False)
    current_step_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    credits_budget: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    credits_consumed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approval_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    step_results_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    output_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_by: Mapped[str] = mapped_column(String(250), default="system", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class ExecutionEvidenceRecord(Base):
    """Durable 18-field execution evidence ledger with output-origin verification."""

    __tablename__ = "execution_evidence_records"

    execution_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    agent_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    connector_id: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    input_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    output_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approval_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    credits_consumed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    output_origin: Mapped[str] = mapped_column(String(64), default="SIMULATED_SYNTHETIC", nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CreditLedgerRecord(Base):
    """Atomic, tenant-scoped, idempotent credit reserve/debit/refund ledger."""

    __tablename__ = "credit_ledger_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    execution_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    credit_pool: Mapped[str] = mapped_column(String(64), default="lead_credits", nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="COMMITTED", nullable=False)
    reason: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    created_by: Mapped[str] = mapped_column(String(250), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class EmergencyStopRecord(Base):
    """Persistent 4-level emergency stop and pause governance state."""

    __tablename__ = "emergency_stop_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scope_level: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    scope_target: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="EMERGENCY_STOPPED", index=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(250), default="system", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P2ProspectDossierRecord(Base):
    """P2 Prospect Intelligence, 6-criterion Qualification Breakdown, Brief, & 12-stage Sales Pipeline."""

    __tablename__ = "p2_prospect_dossiers"
    __table_args__ = (
        UniqueConstraint("lead_id", name="uq_p2_dossier_lead_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    normalized_company_key: Mapped[str] = mapped_column(String(250), index=True, nullable=False)
    normalized_domain: Mapped[str] = mapped_column(String(250), index=True, nullable=False)
    business_category: Mapped[str] = mapped_column(
        String(150), default="Digital Marketing & SEO Agency", nullable=False
    )
    location: Mapped[str] = mapped_column(String(250), default="India", nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), default="manual_owner_curation", nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    public_contacts_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    agency_profile_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    research_claims_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    qualification_breakdown_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    qualification_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    research_brief_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    pipeline_status: Mapped[str] = mapped_column(String(32), default="NEW", index=True, nullable=False)
    next_action: Mapped[str | None] = mapped_column(String(300), nullable=True)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovery_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_history_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    recommended_sku: Mapped[str] = mapped_column(String(100), default="managed_seo_content_pilot", nullable=False)
    commercial_value_inr: Mapped[float] = mapped_column(Float, default=4999.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    payment_status: Mapped[str] = mapped_column(String(32), default="NOT_INITIATED", index=True, nullable=False)
    activation_status: Mapped[str] = mapped_column(String(32), default="NOT_ACTIVATED", index=True, nullable=False)
    activated_org_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P2CommercialProposalRecord(Base):
    """P2 Structured Multi-Clause Commercial Proposal gated by Owner HITL approval."""

    __tablename__ = "p2_commercial_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    proposal_record_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    lead_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    sku_key: Mapped[str] = mapped_column(String(100), default="managed_seo_content_pilot", nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    customer_problem: Mapped[str] = mapped_column(Text, nullable=False)
    scope_summary: Mapped[str] = mapped_column(Text, nullable=False)
    deliverables_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    exclusions_limitations_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    implementation_schedule_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    pricing_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    payment_terms_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    client_responsibilities_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    provider_responsibilities_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    acceptance_cancellation_terms_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="AWAITING_OWNER_APPROVAL", index=True, nullable=False)
    approval_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shared_channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkout_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), default="system", nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P2SuppressionEntryRecord(Base):
    """Persistent DB-backed suppression and opt-out registry."""

    __tablename__ = "p2_suppression_entries"
    __table_args__ = (
        UniqueConstraint("identifier_value", name="uq_p2_suppression_identifier"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    identifier_type: Mapped[str] = mapped_column(String(20), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(250), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), default="Opt-out requested", nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="unsubscribe_endpoint", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class P2PaymentReconciliationRecord(Base):
    """Payment-to-activation reconciliation queue & settlement audit state."""

    __tablename__ = "p2_payment_reconciliation_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    proposal_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    lead_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    checkout_reference: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    expected_sku: Mapped[str] = mapped_column(String(100), default="managed_seo_content_pilot", nullable=False)
    expected_amount: Mapped[float] = mapped_column(Float, default=4999.0, nullable=False)
    received_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    verification_state: Mapped[str] = mapped_column(
        String(32), default="CHECKOUT_CREATED", index=True, nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_org_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    activation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P2CustomerEngagementRecord(Base):
    """Post-payment customer activation, onboarding checklist, workflow delivery, feedback & renewal."""

    __tablename__ = "p2_customer_engagements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    lead_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    proposal_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sku_key: Mapped[str] = mapped_column(String(100), default="managed_seo_content_pilot", nullable=False)
    billing_type: Mapped[str] = mapped_column(String(64), default="managed_pilot_14d", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="ONBOARDING_PENDING_INPUTS", index=True, nullable=False
    )
    assigned_modules_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    entitlements_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    onboarding_checklist_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    required_client_inputs_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    workflow_run_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    deliverables_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    customer_feedback_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    renewal_recommendation_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pilot_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pilot_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P2AcceptanceStepRecord(Base):
    """Owner-executable 12-step real-world pilot verification tracker."""

    __tablename__ = "p2_acceptance_checklist_steps"

    step_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), default="NOT_TESTED", index=True, nullable=False)
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P3CustomerAccountRecord(Base):
    """P3 Customer Success 360 account profile linked cleanly to OrganizationRecord."""

    __tablename__ = "p3_customer_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    primary_contact_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    primary_contact_email: Mapped[str | None] = mapped_column(String(250), nullable=True)
    primary_contact_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    human_owner: Mapped[str] = mapped_column(String(200), default="owner", nullable=False)
    assigned_agents_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    acquisition_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lead_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(String(32), default="LEAD", index=True, nullable=False)
    business_goals_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    expected_outcomes_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    onboarding_progress_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    activation_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    renewal_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_customer_engagement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_preferences_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    retention_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    health_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P3OnboardingWorkflowRecord(Base):
    """Service/product-configurable onboarding workflow with task ownership, blockers, & readiness gates."""

    __tablename__ = "p3_onboarding_workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    sku_key: Mapped[str] = mapped_column(String(100), default="managed_seo_content_pilot", index=True, nullable=False)
    template_key: Mapped[str] = mapped_column(String(100), default="india_seo_agency_pilot", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="IN_PROGRESS", index=True, nullable=False)
    tasks_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    readiness_criteria_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    blockers_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    training_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    activation_confirmed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    activation_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P3ServiceDeliveryRecord(Base):
    """Customer service delivery lifecycle, quality state machine, evidence, and separated outputs/outcomes."""

    __tablename__ = "p3_service_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    p2_engagement_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    sku_key: Mapped[str] = mapped_column(String(100), default="managed_seo_content_pilot", nullable=False)
    service_id: Mapped[str] = mapped_column(String(100), default="seo_blog_copilot", nullable=False)
    workflow_run_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    original_requirement: Mapped[str] = mapped_column(Text, default="", nullable=False)
    approved_scope_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    assigned_owner: Mapped[str] = mapped_column(String(200), default="owner", nullable=False)
    assigned_agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_data_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    source_evidence_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    execution_history_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    approval_checkpoints_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    output_artifacts_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    quality_checks_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    quality_state: Mapped[str] = mapped_column(String(32), default="NOT_STARTED", index=True, nullable=False)
    output_metrics_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    outcome_metrics_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    revision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P3SupportTicketRecord(Base):
    """Organization-scoped customer support ticketing, AI triage, escalation, SLA & CSAT feedback."""

    __tablename__ = "p3_support_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_number: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by_email: Mapped[str | None] = mapped_column(String(250), nullable=True)
    category: Mapped[str] = mapped_column(String(64), default="general", nullable=False)
    priority: Mapped[str] = mapped_column(String(24), default="MEDIUM", index=True, nullable=False)
    assigned_owner: Mapped[str] = mapped_column(String(200), default="support_team", nullable=False)
    assigned_agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    attachments_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    internal_notes_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    messages_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    ai_triage_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    csat_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    csat_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P3SubscriptionEventRecord(Base):
    """Idempotent subscription state machine, grace period, manual-proof flag & renewal history log."""

    __tablename__ = "p3_subscription_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    subscription_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    subscription_state: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    billing_category: Mapped[str] = mapped_column(String(48), default="RECURRING_SUBSCRIPTION", nullable=False)
    is_provider_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="internal", nullable=False)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    internal_sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    billing_interval: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    renewal_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor: Mapped[str] = mapped_column(String(200), default="system", nullable=False)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class P3GrowthOpportunityRecord(Base):
    """Evidence-backed catalog upsell, seat expansion, managed extension & HITL-gated referral engine."""

    __tablename__ = "p3_growth_opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    recommended_sku_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    business_justification: Mapped[str] = mapped_column(Text, default="", nullable=False)
    supporting_evidence_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    catalog_price_inr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    catalog_price_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="IDENTIFIED", index=True, nullable=False)
    approval_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    referral_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    referred_company: Mapped[str | None] = mapped_column(String(250), nullable=True)
    owner_authorized_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P3UnitEconomicsEntryRecord(Base):
    """Per-customer and per-service cost ledger explicitly labeled ACTUAL, ALLOCATED, or ESTIMATED."""

    __tablename__ = "p3_unit_economics_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    service_id: Mapped[str] = mapped_column(String(100), default="general", index=True, nullable=False)
    delivery_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    workflow_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost_category: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    cost_type_label: Mapped[str] = mapped_column(String(24), default="ESTIMATED", index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), default="internal", nullable=False)
    tokens_input: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_inr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[str] = mapped_column(String(200), default="system", nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class P3CustomerCostBudgetRecord(Base):
    """Configurable per-organization monthly spend caps and owner exception approvals."""

    __tablename__ = "p3_customer_cost_budgets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    monthly_cost_limit_inr: Mapped[float] = mapped_column(Float, default=2000.0, nullable=False)
    alert_threshold_pct: Mapped[float] = mapped_column(Float, default=80.0, nullable=False)
    hard_cap_enforced: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    exception_approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exception_limit_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    exception_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[str] = mapped_column(String(200), default="owner", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P3ImprovementItemRecord(Base):
    """Evidence-driven product & service improvement loop prioritized without autonomous code changes."""

    __tablename__ = "p3_improvement_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cluster_key: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    source_category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    problem_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    customer_impact: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    frequency_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    business_value: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    dev_effort: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(24), default="MEDIUM", nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    source_refs_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True, nullable=False)
    requires_release_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P3ComplianceRequestRecord(Base):
    """GDPR/DPDP customer data export, retention enforcement, legal hold, deletion & offboarding."""

    __tablename__ = "p3_compliance_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    request_type: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="REQUESTED", index=True, nullable=False)
    approval_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    export_manifest_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    offboarding_checklist_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P3OperationalIncidentRecord(Base):
    """Multi-tenant operational incident, dead-letter job recovery, DB performance & backup drills."""

    __tablename__ = "p3_operational_incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    incident_type: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(24), default="MEDIUM", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True, nullable=False)
    resource_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    retry_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class P3AcceptanceStepRecord(Base):
    """Owner-executable 12-step real-world Customer Success acceptance tracker."""

    __tablename__ = "p3_acceptance_steps"

    step_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), default="NOT_TESTED", index=True, nullable=False)
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class P4IcpProfileRecord(Base):
    """P4 Ideal Customer Profile (ICP) definition scoped by tenant or platform GTM workspace."""

    __tablename__ = "p4_icp_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    geography: Mapped[str] = mapped_column(String(120), nullable=False, default="India")
    company_size_range: Mapped[str] = mapped_column(String(80), nullable=False, default="10-200")
    buyer_personas_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    pain_points_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    value_propositions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    disqualifiers_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p4_icp_org_status", "org_id", "status"),
    )


class P4MarketIntelRecord(Base):
    """P4 provenance-backed market, competitor, and keyword gap intelligence."""

    __tablename__ = "p4_market_intel_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    icp_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    intel_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    subject_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, default="public_web")
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(48), nullable=False, default="OBSERVATION", index=True)
    verified_facts_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    inferences_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        Index("ix_p4_intel_org_type", "org_id", "intel_type"),
    )


class P4GrowthCampaignRecord(Base):
    """P4 multi-channel repeatable GTM campaign with HITL approval gating and safety audit."""

    __tablename__ = "p4_growth_campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    icp_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    channels_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(48), nullable=False, default="DRAFT", index=True)
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="SIMULATION", index=True)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    variants_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    budget_cap_inr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    spend_inr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    safety_report_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p4_campaign_org_status", "org_id", "status"),
    )


class P4PipelineDealRecord(Base):
    """P4 structured sales pipeline stage, attribution, and lost-reason tracking (ACTUAL vs SANDBOX)."""

    __tablename__ = "p4_pipeline_deals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    lead_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    icp_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stage: Mapped[str] = mapped_column(String(48), nullable=False, default="DISCOVERED", index=True)
    deal_value_inr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    attribution_source: Mapped[str] = mapped_column(String(64), nullable=False, default="ORGANIC_INBOUND", index=True)
    evidence_status: Mapped[str] = mapped_column(String(32), nullable=False, default="SANDBOX", index=True)
    lost_reason: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    next_action: Mapped[str | None] = mapped_column(String(250), nullable=True)
    owner_actor: Mapped[str] = mapped_column(String(120), nullable=False, default="owner")
    stage_history_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_p4_deal_org_stage_origin", "org_id", "stage", "evidence_status"),
    )


class P5TenantTemplateRecord(Base):
    """P5 catalog-bound multi-tenant industry and workflow provisioning template."""

    __tablename__ = "p5_tenant_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    template_key: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    industry: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    tier_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    selected_modules_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    catalog_service_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    default_agent_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    connector_requirements_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    policy_defaults_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    monthly_price_inr: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    evidence_status: Mapped[str] = mapped_column(String(32), nullable=False, default="CATALOG_GROUNDED")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p5_tpl_industry_active", "industry", "is_active"),
    )


class P5ProvisioningRunRecord(Base):
    """P5 idempotent 9-state tenant provisioning state machine execution and retry record."""

    __tablename__ = "p5_provisioning_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True, index=True, nullable=False)
    template_key: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    state: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="REQUESTED")
    completed_steps_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    failed_step: Mapped[str | None] = mapped_column(String(48), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    config_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="SIMULATION")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p5_prov_org_state", "org_id", "state"),
    )


class P5TenantPolicyRecord(Base):
    """P5 per-tenant rate limit, quota, credit budget, and SLA enforcement policy."""

    __tablename__ = "p5_tenant_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    tier_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    daily_agent_runs_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    monthly_credit_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    storage_quota_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=1024)
    sla_target_uptime_pct: Mapped[float] = mapped_column(Float, nullable=False, default=99.5)
    sla_response_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=240)
    auto_throttle_on_breach: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    custom_limits_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class P5UsageQuotaEventRecord(Base):
    """P5 tenant-scoped runtime quota/rate evaluation and throttle audit record."""

    __tablename__ = "p5_usage_quota_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    metric_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    observed_value: Mapped[float] = mapped_column(Float, nullable=False)
    limit_value: Mapped[float] = mapped_column(Float, nullable=False)
    breached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    action_taken: Mapped[str] = mapped_column(String(32), nullable=False, default="ALLOWED")
    details_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    recorded_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        Index("ix_p5_usage_org_metric", "org_id", "metric_type", "breached"),
    )


class P5OperationalIncidentRecord(Base):
    """P5 multi-tenant SLA/quota/provisioning incident lifecycle tracker."""

    __tablename__ = "p5_operational_incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), index=True, nullable=False, default="SEV3_MEDIUM")
    category: Mapped[str] = mapped_column(String(48), index=True, nullable=False, default="SLA_DEGRADATION")
    status: Mapped[str] = mapped_column(String(24), index=True, nullable=False, default="OPEN")
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    mitigation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reported_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    assigned_to: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p5_incident_org_status", "org_id", "status", "severity"),
    )


class P6IndustryPackRecord(Base):
    """P6 configuration-driven SME industry pack bound to real catalog modules and vertical analytics."""

    __tablename__ = "p6_industry_packs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pack_key: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sector: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tier_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    selected_modules_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    catalog_service_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    agent_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    analytics_capabilities_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    kpi_definitions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    default_config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    monthly_price_inr: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    readiness_status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="SANDBOX")
    verified_live_customers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p6_pack_sector_readiness", "sector", "readiness_status"),
    )


class P6TenantPackDeploymentRecord(Base):
    """P6 tenant deployment of an industry pack plus vertical analytics simulation/diagnostics state."""

    __tablename__ = "p6_tenant_pack_deployments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    pack_key: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="CONFIGURED")
    execution_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="SIMULATION")
    configuration_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_analytics_output_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    readiness_label: Mapped[str] = mapped_column(String(32), nullable=False, default="SANDBOX")
    deployed_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p6_dep_org_pack", "org_id", "pack_key", "status"),
    )


class P6SeoBaselineRecord(Base):
    """P6 India agency / local SME SEO baseline grounded strictly in real catalog SKUs."""

    __tablename__ = "p6_seo_baselines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    region_code: Mapped[str] = mapped_column(String(16), nullable=False, default="IN")
    city_or_cluster: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    industry_vertical: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    primary_catalog_sku: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    target_keywords_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    localized_pages_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    schema_markup_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    baseline_status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="SANDBOX_DRAFT")
    approval_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p6_seo_org_vertical", "org_id", "industry_vertical"),
    )


class P7DelegationPlanRecord(Base):
    """P7 multi-agent delegation DAG with cycle, depth, and credit budget enforcement."""

    __tablename__ = "p7_delegation_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    nodes_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    computed_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    credit_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    credits_consumed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="PLANNED")
    execution_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="SIMULATION")
    execution_results_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    approval_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p7_dag_org_status", "org_id", "status"),
    )


class P7TenantMemoryRecord(Base):
    """P7 tenant-isolated persistent agent memory with provenance, TTL, and DPDP purge support."""

    __tablename__ = "p7_tenant_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    namespace: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    memory_key: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False, default="USER_CONFIG")
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, index=True, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p7_mem_org_ns", "org_id", "namespace", "is_deleted"),
    )


class P7AutonomyPolicyRecord(Base):
    """P7 5-level governed agent autonomy policy (LEVEL_0..LEVEL_4 only; HITL enforced)."""

    __tablename__ = "p7_autonomy_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    agent_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    autonomy_level: Mapped[str] = mapped_column(String(48), index=True, nullable=False, default="LEVEL_2_APPROVAL_GATED")
    requires_hitl_for_external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_daily_budget_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_paused: Mapped[bool] = mapped_column(Boolean, index=True, nullable=False, default=False)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_eval_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.75)
    approval_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    updated_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p7_autonomy_org_agent", "org_id", "agent_id", "is_paused"),
    )


class P7AgentEvalRunRecord(Base):
    """P7 continuous agent evaluation record that triggers automatic pause on threshold breach."""

    __tablename__ = "p7_agent_eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    agent_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    eval_suite_name: Mapped[str] = mapped_column(String(120), nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    safety_score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.75)
    passed: Mapped[bool] = mapped_column(Boolean, index=True, nullable=False, default=True)
    auto_paused_triggered: Mapped[bool] = mapped_column(Boolean, index=True, nullable=False, default=False)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        Index("ix_p7_eval_org_agent", "org_id", "agent_id", "passed"),
    )


class P8DeveloperProfileRecord(Base):
    """P8 third-party marketplace developer entity with KYB verification gating."""

    __tablename__ = "p8_developer_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    developer_name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    legal_entity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tax_or_gst_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kyb_status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="PENDING")
    kyb_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    payout_account_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p8_dev_kyb_status", "kyb_status", "contact_email"),
    )


class P8MarketplaceListingRecord(Base):
    """P8 signed third-party agent/connector marketplace package listing."""

    __tablename__ = "p8_marketplace_listings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    developer_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    listing_slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    package_type: Mapped[str] = mapped_column(String(48), index=True, nullable=False, default="AGENT_PLUGIN")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    requested_permissions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    endpoint_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ecdsa_signature_hex: Mapped[str] = mapped_column(Text, nullable=False)
    signing_public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    price_inr_monthly: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    commission_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=1500)
    security_review_status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="PENDING_REVIEW")
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="DRAFT")
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p8_list_dev_pub", "developer_id", "published_status", "security_review_status"),
    )


class P8TenantInstallRecord(Base):
    """P8 tenant-isolated installation of a marketplace package with credential redaction."""

    __tablename__ = "p8_tenant_installs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    listing_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), index=True, nullable=False, default="ACTIVE")
    granted_permissions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    secret_digests_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    installed_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p8_inst_org_listing", "org_id", "listing_id", "status"),
    )


class P8MarketplaceReviewRecord(Base):
    """P8 verified-installer marketplace review and abuse moderation record."""

    __tablename__ = "p8_marketplace_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    listing_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    install_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    abuse_flagged: Mapped[bool] = mapped_column(Boolean, index=True, nullable=False, default=False)
    abuse_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    moderation_status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="PUBLISHED")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_p8_rev_listing_mod", "listing_id", "moderation_status"),
    )


class P8RevenueShareLedgerRecord(Base):
    """P8 marketplace commission and developer payout ledger separating ACTUAL vs SANDBOX origin."""

    __tablename__ = "p8_revenue_share_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    install_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    listing_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    developer_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    gross_amount_inr: Mapped[float] = mapped_column(Float, nullable=False)
    commission_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_commission_inr: Mapped[float] = mapped_column(Float, nullable=False)
    developer_payout_inr: Mapped[float] = mapped_column(Float, nullable=False)
    settlement_status: Mapped[str] = mapped_column(String(24), index=True, nullable=False, default="ACCRUED")
    evidence_status: Mapped[str] = mapped_column(String(24), index=True, nullable=False, default="SANDBOX")
    recorded_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        Index("ix_p8_rev_dev_origin", "developer_id", "evidence_status", "settlement_status"),
    )
