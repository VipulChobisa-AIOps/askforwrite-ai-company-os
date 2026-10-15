"""Pydantic schemas for product catalog, pricing packages, and diagnostic pitches."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PackageResponse(BaseModel):
    key: str
    name: str
    category: Literal["modular_tool", "master_bundle"]
    description: str
    target_buyer_persona: str = ""
    target_pain_point: str
    key_features: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    seo_geo_aio_capabilities: list[str] = Field(default_factory=list)
    price_inr: int
    price_usd: int
    currency_default: str
    entitled_capabilities: list[str]
    lead_credits_monthly: int
    outreach_credits_monthly: int
    tier: str
    razorpay_checkout_url: str
    paypal_checkout_url: str


class CatalogListResponse(BaseModel):
    count: int
    packages: list[PackageResponse]


class DiagnoseRequest(BaseModel):
    company: str = Field(min_length=1, max_length=250)
    website: str = Field(min_length=3, max_length=2048)
    industry: str = Field(default="Technology & Services", max_length=250)
    geography: str = Field(default="India", max_length=250)
    observed_signals: list[str] = Field(default_factory=list)


class DiagnoseResponse(BaseModel):
    company: str
    target_buyer_persona: str | None = None
    identified_pain_point: str
    recommended_package_key: str
    package_name: str
    category: str
    reasoning: str
    currency: str
    price: int
    payment_link: str
    provider: str
    key_features: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    seo_geo_aio_capabilities: list[str] = Field(default_factory=list)


class PitchLeadRequest(BaseModel):
    lead_id: str = Field(min_length=1, max_length=36)
    org_id: str | None = Field(default=None, max_length=36)
    package_key: str | None = Field(default=None, description="Optional override of recommended package")
    recipient_email: str | None = Field(default=None, max_length=250)
    recipient_name: str | None = Field(default=None, max_length=250)
    provider: Literal["razorpay", "paypal"] = Field(default="razorpay")
    idempotency_key: str = Field(min_length=1, max_length=200)


class PitchLeadResponse(BaseModel):
    outreach_id: str
    lead_id: str
    package_key: str
    package_name: str
    subject: str
    payment_link: str
    status: str
    approval_id: str | None = None
    recipient_email: str
