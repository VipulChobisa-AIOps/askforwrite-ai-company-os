"""Multi-tenant Accounts and Billing API router.

Endpoints for:
- Organization management (create, list, get, update)
- Team user membership (add, list, remove)
- Invoices & billing receipts (create, list)
- Credit usage and quota verification
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
    AuditLog,
    CustomerRecord,
    InvoiceRecord,
    OrganizationRecord,
    SubscriptionRecord,
    UserRecord,
)
from app.schemas.account import (
    InvoiceCreate,
    InvoiceResponse,
    OrgCreate,
    OrgResponse,
    OrgSummaryResponse,
    OrgUpdate,
    UserCreate,
    UserResponse,
)
from app.security.auth import APIPrincipal, require_manager, require_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/accounts", tags=["accounts"])

# Tier credit allowances
TIER_QUOTAS = {
    "free": {"lead_credits": 20, "outreach_credits": 10},
    "starter": {"lead_credits": 100, "outreach_credits": 50},
    "pro": {"lead_credits": 500, "outreach_credits": 250},
    "enterprise": {"lead_credits": 5000, "outreach_credits": 2500},
}


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "org"


# ── Organization Endpoints ───────────────────────────────────────────


@router.post("/orgs", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrgCreate,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Create a new multi-tenant organization."""
    base_slug = payload.slug or _slugify(payload.name)
    slug = base_slug
    counter = 1
    while db.query(OrganizationRecord).filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    quotas = TIER_QUOTAS.get(payload.tier.lower(), TIER_QUOTAS["starter"])

    org = OrganizationRecord(
        name=payload.name,
        slug=slug,
        tier=payload.tier.lower(),
        lead_credits_limit=quotas["lead_credits"],
        lead_credits_used=0,
        outreach_credits_limit=quotas["outreach_credits"],
        outreach_credits_used=0,
        is_active=True,
        metadata_json=payload.metadata,
    )
    db.add(org)
    db.flush()

    audit = AuditLog(
        task_id=org.id,
        correlation_id=org.id,
        agent_id=principal.subject,
        capability_name="accounts",
        action="create_organization",
        input_payload={"name": payload.name, "tier": payload.tier, "slug": slug},
        output_payload={"org_id": org.id, "slug": slug},
        status="COMPLETED",
    )
    db.add(audit)
    db.commit()
    db.refresh(org)
    return org


@router.get("/orgs", response_model=list[OrgResponse])
def list_organizations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """List all registered organizations."""
    return db.query(OrganizationRecord).offset(skip).limit(limit).all()


@router.get("/orgs/{org_id}", response_model=OrgSummaryResponse)
def get_organization_summary(
    org_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Retrieve organization summary including active subscription and recent invoices."""
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail=f"Organization {org_id} not found")

    members_count = db.query(UserRecord).filter_by(org_id=org_id, is_active=True).count()

    sub = (
        db.query(SubscriptionRecord)
        .filter_by(org_id=org_id)
        .order_by(SubscriptionRecord.created_at.desc())
        .first()
    )
    sub_data = None
    if sub:
        sub_data = {
            "id": sub.id,
            "provider": sub.provider,
            "status": sub.status,
            "plan_id": sub.plan_id,
            "payment_url": sub.payment_url,
            "current_period_end": sub.current_period_end,
        }

    invoices = (
        db.query(InvoiceRecord)
        .filter_by(org_id=org_id)
        .order_by(InvoiceRecord.created_at.desc())
        .limit(10)
        .all()
    )

    return OrgSummaryResponse(
        org=OrgResponse.model_validate(org, from_attributes=True),
        members_count=members_count,
        active_subscription=sub_data,
        recent_invoices=[InvoiceResponse.model_validate(i, from_attributes=True) for i in invoices],
    )


@router.patch("/orgs/{org_id}", response_model=OrgResponse)
def update_organization(
    org_id: str,
    payload: OrgUpdate,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Update organization settings, tier, or quotas (owner authorization required)."""
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail=f"Organization {org_id} not found")

    if payload.name is not None:
        org.name = payload.name
    if payload.tier is not None:
        org.tier = payload.tier.lower()
        if org.tier in TIER_QUOTAS:
            org.lead_credits_limit = TIER_QUOTAS[org.tier]["lead_credits"]
            org.outreach_credits_limit = TIER_QUOTAS[org.tier]["outreach_credits"]
    if payload.lead_credits_limit is not None:
        org.lead_credits_limit = payload.lead_credits_limit
    if payload.outreach_credits_limit is not None:
        org.outreach_credits_limit = payload.outreach_credits_limit
    if payload.is_active is not None:
        org.is_active = payload.is_active
    if payload.metadata is not None:
        org.metadata_json = payload.metadata

    org.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(org)
    return org


# ── Team User Endpoints ───────────────────────────────────────────────


@router.post("/orgs/{org_id}/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def add_user_to_org(
    org_id: str,
    payload: UserCreate,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Add a new member to an organization."""
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail=f"Organization {org_id} not found")

    existing = db.query(UserRecord).filter_by(org_id=org_id, email=payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"User with email '{payload.email}' already exists in this org")

    user = UserRecord(
        org_id=org_id,
        email=payload.email.lower().strip(),
        full_name=payload.full_name.strip(),
        role=payload.role.lower(),
        is_active=True,
        metadata_json=payload.metadata,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/orgs/{org_id}/users", response_model=list[UserResponse])
def list_org_users(
    org_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """List active members of an organization."""
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail=f"Organization {org_id} not found")

    return db.query(UserRecord).filter_by(org_id=org_id).all()


@router.delete("/orgs/{org_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_org_user(
    org_id: str,
    user_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Deactivate/remove an organization member."""
    user = db.query(UserRecord).filter_by(org_id=org_id, id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found in org {org_id}")

    db.delete(user)
    db.commit()
    return None


# ── Invoice Endpoints ────────────────────────────────────────────────


@router.post("/orgs/{org_id}/invoices", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
def record_invoice(
    org_id: str,
    payload: InvoiceCreate,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Record an invoice or payment receipt for an organization."""
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail=f"Organization {org_id} not found")

    invoice = InvoiceRecord(
        org_id=org_id,
        customer_id=payload.customer_id,
        subscription_id=payload.subscription_id,
        provider=payload.provider.lower(),
        provider_invoice_id=payload.provider_invoice_id,
        provider_payment_id=payload.provider_payment_id,
        amount=payload.amount,
        currency=payload.currency.upper(),
        status=payload.status.lower(),
        billing_period_start=payload.billing_period_start,
        billing_period_end=payload.billing_period_end,
        hosted_invoice_url=payload.hosted_invoice_url,
        pdf_url=payload.pdf_url,
        metadata_json=payload.metadata,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


@router.get("/orgs/{org_id}/invoices", response_model=list[InvoiceResponse])
def list_org_invoices(
    org_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """List billing invoices for an organization."""
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail=f"Organization {org_id} not found")

    return (
        db.query(InvoiceRecord)
        .filter_by(org_id=org_id)
        .order_by(InvoiceRecord.created_at.desc())
        .all()
    )


# ── Quota & Feature Gating Verification ──────────────────────────────


class ConsumeCreditsRequest(BaseModel):
    credit_type: str = Field(..., description="'lead' or 'outreach'")
    amount: int = Field(default=1, gt=0, description="Number of credits to consume")


class ConsumeCreditsResponse(BaseModel):
    org_id: str
    credit_type: str
    consumed: int
    credits_remaining: int
    allowed: bool


@router.post("/orgs/{org_id}/consume-credits", response_model=ConsumeCreditsResponse)
def consume_org_credits(
    org_id: str,
    payload: ConsumeCreditsRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Verify and consume monthly feature credits for an organization.

    Enforces plan limits on discovery and outreach.
    """
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail=f"Organization {org_id} not found")

    if not org.is_active:
        raise HTTPException(status_code=403, detail="Organization account is inactive or suspended")

    ctype = payload.credit_type.lower()
    if ctype == "lead":
        limit = org.lead_credits_limit
        used = org.lead_credits_used
        if used + payload.amount > limit:
            raise HTTPException(
                status_code=402,
                detail=f"Lead credit quota exceeded ({used}/{limit} used). Upgrade plan for more credits.",
            )
        org.lead_credits_used += payload.amount
        remaining = limit - org.lead_credits_used
    elif ctype == "outreach":
        limit = org.outreach_credits_limit
        used = org.outreach_credits_used
        if used + payload.amount > limit:
            raise HTTPException(
                status_code=402,
                detail=f"Outreach credit quota exceeded ({used}/{limit} used). Upgrade plan for more credits.",
            )
        org.outreach_credits_used += payload.amount
        remaining = limit - org.outreach_credits_used
    else:
        raise HTTPException(status_code=400, detail="Invalid credit_type. Must be 'lead' or 'outreach'")

    db.commit()
    return ConsumeCreditsResponse(
        org_id=org_id,
        credit_type=ctype,
        consumed=payload.amount,
        credits_remaining=remaining,
        allowed=True,
    )
