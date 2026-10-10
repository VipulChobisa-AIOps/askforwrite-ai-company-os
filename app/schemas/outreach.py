"""Pydantic schemas for customer outreach drafting, owner approval, and dispatch."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OutreachDraftRequest(BaseModel):
    lead_id: str = Field(min_length=1, max_length=36, description="Target lead ID")
    org_id: str | None = Field(default=None, max_length=36, description="Organization ID for credit deduction")
    recipient_email: str | None = Field(default=None, max_length=250, description="Override recipient email if not on lead")
    recipient_name: str | None = Field(default=None, max_length=250, description="Recipient contact name")
    custom_notes: str | None = Field(default=None, max_length=2000, description="Custom value proposition or context")
    channel: Literal["email", "linkedin"] = Field(default="email", description="Delivery channel")
    idempotency_key: str = Field(min_length=1, max_length=200, description="Client idempotency key")


class OutreachDraftResponse(BaseModel):
    outreach_id: str
    org_id: str | None = None
    lead_id: str
    recipient_email: str
    recipient_name: str | None = None
    subject: str
    body_text: str
    channel: str
    status: str
    approval_id: str | None = None
    payment_link: str | None = None
    package_key: str | None = None
    credits_remaining: int | None = None


class OutreachDispatchResponse(BaseModel):
    outreach_id: str
    status: str
    sent_at: str | None = None
    recipient_email: str
    receipt: dict | None = None
    lead_status: str | None = None
    credits_remaining: int | None = None


class OutreachResponse(BaseModel):
    id: str
    org_id: str | None = None
    lead_id: str
    task_id: str
    recipient_email: str
    recipient_name: str | None = None
    subject: str
    body_text: str
    channel: str
    status: str
    approval_id: str | None = None
    idempotency_key: str
    sent_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OutreachListResponse(BaseModel):
    count: int
    total: int
    records: list[OutreachResponse]
