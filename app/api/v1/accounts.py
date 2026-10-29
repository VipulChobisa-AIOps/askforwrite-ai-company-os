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
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
    AuditLog,
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
from app.security.auth import (
    APIPrincipal,
    enforce_tenant_access,
    require_manager,
    require_owner,
)

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
    """List registered organizations (scoped to tenant if principal is org-bound)."""
    query = db.query(OrganizationRecord)
    if principal.org_id:
        query = query.filter(OrganizationRecord.id == principal.org_id)
    return query.offset(skip).limit(limit).all()


@router.get("/orgs/{org_id}", response_model=OrgSummaryResponse)
def get_organization_summary(
    org_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Retrieve organization summary including active subscription and recent invoices."""
    enforce_tenant_access(principal, org_id)

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
    enforce_tenant_access(principal, org_id)

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
    enforce_tenant_access(principal, org_id)

    role_clean = payload.role.lower().strip()
    if role_clean in {"owner", "manager"} and principal.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform owners can assign owner or manager roles",
        )

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
        role=role_clean,
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
    enforce_tenant_access(principal, org_id)

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
    enforce_tenant_access(principal, org_id)

    user = db.query(UserRecord).filter_by(org_id=org_id, id=user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found in org {org_id}")

    db.delete(user)
    db.commit()


# ── Invoice Endpoints ────────────────────────────────────────────────


@router.post("/orgs/{org_id}/invoices", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
def record_invoice(
    org_id: str,
    payload: InvoiceCreate,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Record an invoice or payment receipt for an organization."""
    enforce_tenant_access(principal, org_id)

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
    enforce_tenant_access(principal, org_id)

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
    enforce_tenant_access(principal, org_id)

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


# ── Payment Authorization vs. Bank Settlement Reconciliation ─────────


class ReconcileSettlementRequest(BaseModel):
    settlement_reference: str = Field(..., min_length=4, max_length=120, description="Bank UTR / NEFT / Razorpay / PayPal settlement payout ID")
    settlement_status: str = Field(
        default="SETTLED",
        description="ELIGIBLE_FOR_SETTLEMENT, SETTLEMENT_INITIATED, SETTLED, REFUND_INITIATED, REFUND_COMPLETED",
    )
    bank_account_masked: str = Field(default="6940XXXXXX26", max_length=64)
    notes: str | None = Field(default=None, max_length=500)


@router.get("/reconciliation")
def get_payment_settlement_reconciliation(
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    """Return separated payment lifecycle states: checkout created, payment captured, eligible for settlement, settled to bank, and refunded."""
    import os
    from app.db.models import SovereignPaymentSessionRecord

    inv_query = db.query(InvoiceRecord)
    if principal.org_id:
        inv_query = inv_query.filter(InvoiceRecord.org_id == principal.org_id)
    invoices = inv_query.order_by(InvoiceRecord.created_at.desc()).all()

    sess_query = db.query(SovereignPaymentSessionRecord)
    sessions = sess_query.all() if not principal.org_id else []

    checkout_created_count = sum(1 for s in sessions if s.status == "PENDING")
    awaiting_owner_confirmation_count = sum(1 for s in sessions if s.status == "AWAITING_OWNER_CONFIRMATION")

    captured_paid_count = 0
    settled_to_bank_count = 0
    unsettled_captured_count = 0
    refunded_count = 0
    failed_count = 0

    total_captured_inr_paise = 0
    total_settled_inr_paise = 0
    total_unsettled_inr_paise = 0
    total_captured_usd_cents = 0
    total_settled_usd_cents = 0

    for inv in invoices:
        meta = inv.metadata_json or {}
        s_status = meta.get("settlement_status", "ELIGIBLE_FOR_SETTLEMENT")
        if inv.status == "paid":
            captured_paid_count += 1
            if inv.currency == "INR":
                total_captured_inr_paise += inv.amount
            elif inv.currency == "USD":
                total_captured_usd_cents += inv.amount

            if s_status == "SETTLED":
                settled_to_bank_count += 1
                if inv.currency == "INR":
                    total_settled_inr_paise += inv.amount
                elif inv.currency == "USD":
                    total_settled_usd_cents += inv.amount
            else:
                unsettled_captured_count += 1
                if inv.currency == "INR":
                    total_unsettled_inr_paise += inv.amount
        elif inv.status == "refunded":
            refunded_count += 1
        elif inv.status == "failed":
            failed_count += 1

    raw_bank = os.getenv("AFW_BANK_ACCOUNT_NUMBER", "6940XXXXXX26")
    masked_bank = f"{raw_bank[:4]}XXXXXX{raw_bank[-2:]}" if len(raw_bank) >= 8 and "X" not in raw_bank else raw_bank

    return {
        "merchant_destination": {
            "beneficiary_entity": os.getenv("AFW_BANK_BENEFICIARY", "ASKFORWRITE / Vipul Kumar Chobisa"),
            "bank_name": os.getenv("AFW_BANK_NAME", "ICICI Bank Ltd"),
            "bank_account_masked": masked_bank,
            "ifsc_code": os.getenv("AFW_BANK_IFSC", "ICIC0006940"),
            "upi_vpa": os.getenv("AFW_MERCHANT_UPI_VPA", "ask4write@icici"),
            "evm_wallet": os.getenv("AFW_MERCHANT_EVM_WALLET", "0x811db32e3802eD9a75F7bbd24f6C3C03216346a2"),
        },
        "lifecycle_counts": {
            "checkout_created_pending": checkout_created_count,
            "payment_initiated_awaiting_verification": awaiting_owner_confirmation_count,
            "payment_captured_confirmed": captured_paid_count,
            "payment_eligible_for_settlement_unsettled": unsettled_captured_count,
            "funds_settled_to_merchant_bank": settled_to_bank_count,
            "refunded": refunded_count,
            "failed": failed_count,
        },
        "financial_totals": {
            "captured_inr": round(total_captured_inr_paise / 100.0, 2),
            "settled_to_bank_inr": round(total_settled_inr_paise / 100.0, 2),
            "unsettled_captured_inr": round(total_unsettled_inr_paise / 100.0, 2),
            "captured_usd": round(total_captured_usd_cents / 100.0, 2),
            "settled_to_bank_usd": round(total_settled_usd_cents / 100.0, 2),
        },
    }


@router.post("/invoices/{invoice_id}/reconcile-settlement")
def reconcile_invoice_settlement(
    invoice_id: str,
    payload: ReconcileSettlementRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    """Owner-only endpoint to record verified bank statement / payout settlement against a captured InvoiceRecord."""
    import uuid
    from sqlalchemy.orm.attributes import flag_modified
    from app.security.trust_chain import seal_task_to_block

    inv = db.get(InvoiceRecord, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found")

    meta = dict(inv.metadata_json or {})
    meta["settlement_status"] = payload.settlement_status.upper()
    meta["settlement_reference"] = payload.settlement_reference.strip()
    meta["bank_account_masked"] = payload.bank_account_masked
    meta["reconciled_by"] = principal.subject
    meta["reconciled_at"] = datetime.now(UTC).isoformat()
    if payload.notes:
        meta["settlement_notes"] = payload.notes

    if payload.settlement_status.upper() in ("REFUND_INITIATED", "REFUND_COMPLETED"):
        inv.status = "refunded"

    inv.metadata_json = meta
    flag_modified(inv, "metadata_json")
    db.flush()

    task_id = str(uuid.uuid4())
    block = seal_task_to_block(
        db=db,
        task_id=task_id,
        capability_name="payment_settlement_reconciliation",
        action="reconcile_bank_settlement",
        payload={
            "invoice_id": inv.id,
            "org_id": inv.org_id,
            "amount": inv.amount,
            "currency": inv.currency,
            "settlement_status": meta["settlement_status"],
            "settlement_reference": meta["settlement_reference"],
            "bank_account_masked": payload.bank_account_masked,
        },
        sealed_by=principal.subject,
        commit=True,
    )

    return {
        "status": "RECONCILED",
        "invoice_id": inv.id,
        "invoice_status": inv.status,
        "settlement_status": meta["settlement_status"],
        "settlement_reference": meta["settlement_reference"],
        "bank_account_masked": payload.bank_account_masked,
        "trust_block_hash": block.block_hash,
    }
