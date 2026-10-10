"""Pydantic schemas for multi-tenant accounts, users, and invoices."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Organization Schemas ─────────────────────────────────────────────


class OrgCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200, description="Organization name")
    slug: str | None = Field(default=None, max_length=100, description="Custom URL/unique slug (auto-generated if empty)")
    tier: str = Field(default="starter", description="Plan tier: free, starter, pro, enterprise")
    metadata: dict[str, Any] | None = Field(default=None, description="Optional metadata")


class OrgUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    tier: str | None = Field(default=None)
    lead_credits_limit: int | None = Field(default=None, ge=0)
    outreach_credits_limit: int | None = Field(default=None, ge=0)
    is_active: bool | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)


class OrgResponse(BaseModel):
    id: str
    name: str
    slug: str
    tier: str
    lead_credits_limit: int
    lead_credits_used: int
    outreach_credits_limit: int
    outreach_credits_used: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ── User Schemas ─────────────────────────────────────────────────────


class UserCreate(BaseModel):
    email: str = Field(..., description="User corporate/work email")
    full_name: str = Field(..., min_length=2, max_length=250, description="User full name")
    role: str = Field(default="member", description="Role: owner, admin, or member")
    metadata: dict[str, Any] | None = Field(default=None)


class UserResponse(BaseModel):
    id: str
    org_id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


# ── Invoice Schemas ──────────────────────────────────────────────────


class InvoiceCreate(BaseModel):
    customer_id: str = Field(..., description="Customer ID")
    subscription_id: str | None = Field(default=None, description="Subscription ID if recurring")
    provider: str = Field(default="razorpay", description="razorpay or paypal")
    provider_invoice_id: str = Field(..., description="ID from provider")
    provider_payment_id: str | None = Field(default=None, description="Payment/capture ID")
    amount: int = Field(..., gt=0, description="Amount in smallest currency unit")
    currency: str = Field(default="INR", description="Currency code")
    status: str = Field(default="paid", description="issued, paid, failed, cancelled, refunded")
    billing_period_start: str | None = Field(default=None)
    billing_period_end: str | None = Field(default=None)
    hosted_invoice_url: str | None = Field(default=None)
    pdf_url: str | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)


class InvoiceResponse(BaseModel):
    id: str
    org_id: str
    customer_id: str
    subscription_id: str | None
    provider: str
    provider_invoice_id: str
    provider_payment_id: str | None
    amount: int
    currency: str
    status: str
    billing_period_start: str | None
    billing_period_end: str | None
    hosted_invoice_url: str | None
    pdf_url: str | None
    created_at: datetime


# ── Summary Schema ───────────────────────────────────────────────────


class OrgSummaryResponse(BaseModel):
    org: OrgResponse
    members_count: int
    active_subscription: dict[str, Any] | None = None
    recent_invoices: list[InvoiceResponse] = []
