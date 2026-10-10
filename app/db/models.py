"""Persistent task, lead, audit, and idempotency records."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class TaskRecord(Base):
    __tablename__ = "task_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    objective: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), index=True)
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
    observed_signals: Mapped[list] = mapped_column(JSON)
    sources: Mapped[list] = mapped_column(JSON)
    product_match: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fit_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    public_contact_channel: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recommended_next_step: Mapped[str] = mapped_column(String(100))
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
    requirement_id: Mapped[str] = mapped_column(String(36), index=True)
    lead_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    scope: Mapped[list] = mapped_column(JSON)
    pricing_model: Mapped[str] = mapped_column(String(100))
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


def _reject_audit_mutation(mapper, connection, target) -> None:
    raise ValueError("Audit records are append-only")


def _reject_block_mutation(mapper, connection, target) -> None:
    raise ValueError("Trust blocks are append-only and cryptographically immutable")


event.listen(AuditLog, "before_update", _reject_audit_mutation)
event.listen(AuditLog, "before_delete", _reject_audit_mutation)
event.listen(TrustBlock, "before_update", _reject_block_mutation)
event.listen(TrustBlock, "before_delete", _reject_block_mutation)