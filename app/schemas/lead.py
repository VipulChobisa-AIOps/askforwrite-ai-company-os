"""Pydantic schemas for multi-tenant lead discovery, enrichment, and lifecycle management."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class LeadDiscoverRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=500, description="Discovery target objective or industry search criteria")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum candidate leads to discover")
    idempotency_key: str = Field(min_length=1, max_length=200, description="Client idempotency key")
    org_id: str | None = Field(default=None, max_length=36, description="Organization ID for credit deduction and deduplication")
    live_source: bool = Field(default=False, description="Whether to perform live web enrichment rather than synthetic fixtures")


class LeadEnrichRequest(BaseModel):
    website: str = Field(min_length=3, max_length=2048, description="Target website URL or domain name to scrape and enrich")
    org_id: str | None = Field(default=None, max_length=36, description="Organization ID to associate enriched lead with")


class LeadUpdateRequest(BaseModel):
    status: Literal[
        "DISCOVERED",
        "QUALIFIED",
        "CONTACTED",
        "MEETING_SCHEDULED",
        "PROPOSAL_SENT",
        "CONVERTED",
        "LOST",
        "DO_NOT_CONTACT",
    ] | None = None
    recommended_next_step: str | None = Field(default=None, max_length=100)
    public_contact_channel: str | None = Field(default=None, max_length=500)
    do_not_contact: bool | None = None


class LeadImportItem(BaseModel):
    company: str = Field(min_length=1, max_length=250)
    website: str = Field(min_length=3, max_length=2048)
    industry: str = Field(default="Technology & Services", max_length=250)
    geography: str = Field(default="Global", max_length=250)
    public_contact_channel: str | None = Field(default=None, max_length=500)
    signals: list[str] = Field(default_factory=list)


class LeadImportRequest(BaseModel):
    org_id: str = Field(min_length=1, max_length=36)
    leads: list[LeadImportItem] = Field(min_length=1, max_length=100)


class LeadResponse(BaseModel):
    id: str
    org_id: str | None = None
    domain: str | None = None
    company: str
    website: str
    industry: str
    geography: str
    observed_signals: list[str]
    sources: list[dict]
    product_match: str | None = None
    fit_score: float
    confidence: float
    public_contact_channel: str | None = None
    recommended_next_step: str
    do_not_contact: bool
    status: str
    last_checked: datetime

    model_config = ConfigDict(from_attributes=True)


class LeadListResponse(BaseModel):
    count: int
    total: int
    leads: list[LeadResponse]
    credits_remaining: int | None = None
