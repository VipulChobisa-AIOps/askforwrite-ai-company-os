"""Customer Self-Service Portal API router.

Provides tenant-scoped, JWT-authenticated endpoints for:
- GET /v1/me          — current user profile + org details + credit balance
- GET /v1/me/usage    — monthly credit consumption breakdown
- GET /v1/me/billing  — invoice history for the tenant org
- GET /v1/me/capabilities — list of entitled capabilities for the tenant tier
- POST /v1/me/change-password — self-service password change

These endpoints are accessed via the Bearer token issued by POST /v1/auth/login.
No API-Key role is needed; the JWT itself carries user_id, org_id, and role.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
    AuditLog,
    InvoiceRecord,
    OrganizationRecord,
    UserRecord,
)
from app.security.auth import (
    APIPrincipal,
    get_current_principal,
    hash_password,
    verify_password,
)
from app.services.catalog import CATALOG, get_package

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/me", tags=["customer-portal"])


# ── Response Schemas ──────────────────────────────────────────────────────────


class CreditUsageSummary(BaseModel):
    """Credit balance and consumption for a billing period."""

    lead_credits_limit: int
    lead_credits_used: int
    lead_credits_remaining: int
    lead_utilization_pct: float

    outreach_credits_limit: int
    outreach_credits_used: int
    outreach_credits_remaining: int
    outreach_utilization_pct: float


class InvoiceSummary(BaseModel):
    """Condensed invoice record for customer billing history."""

    invoice_id: str
    amount: int
    currency: str
    status: str
    provider: str
    created_at: datetime


class CapabilityEntry(BaseModel):
    """A single entitled capability for the tenant's plan."""

    capability: str
    description: str


class MeResponse(BaseModel):
    """Full customer profile response."""

    user_id: str
    email: str
    full_name: str
    role: str
    org_id: str
    org_name: str
    org_slug: str
    tier: str
    package_name: str | None
    is_active: bool
    credits: CreditUsageSummary
    capabilities: list[CapabilityEntry]
    portal_url: str


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=6, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# ── Capability descriptions ───────────────────────────────────────────────────

_CAPABILITY_DESCRIPTIONS: dict[str, str] = {
    "lead_discovery": "AI-powered offline lead scoring and prospect discovery",
    "evidence_research": "Evidence synthesis and competitive intelligence on prospects",
    "sales_capture": "Sales conversation requirement capture and proposal drafting",
    "proposal_delivery": "Field force delivery of approved proposals",
    "manager_orchestration": "Full multi-agent Manager → Discovery → Research → Outreach pipeline",
    "outreach_dispatch": "HITL-gated email outreach drafting and dispatch",
    "revenue_engine": "AI pitch generation with embedded Razorpay/PayPal payment links",
    "field_attendance": "Geofenced attendance tracking with anti-spoofing",
    "field_visit_verification": "Client visit proof-of-execution (photo, voice, OTP)",
    "field_dispatch": "Task assignment and intelligent route sequencing",
    "field_conveyance": "Mileage reimbursement and expense verification",
    "seo_copilot": "AI-generated SEO blog post and keyword strategy drafts",
    "marketing_suite": "Ad copy, campaign brief, and social post generation",
    "trust_ledger": "Cryptographic ECDSA trust chain and audit ledger access",
    "payment_processing": "Razorpay and PayPal subscription management",
    "multi_tenant_accounts": "Organization and team user management",
}


def _build_capability_entries(entitled: set[str]) -> list[CapabilityEntry]:
    return [
        CapabilityEntry(
            capability=cap,
            description=_CAPABILITY_DESCRIPTIONS.get(cap, cap.replace("_", " ").title()),
        )
        for cap in sorted(entitled)
    ]


def _credit_usage(org: OrganizationRecord) -> CreditUsageSummary:
    lead_limit = org.lead_credits_limit or 0
    lead_used = org.lead_credits_used or 0
    lead_remaining = max(0, lead_limit - lead_used)
    lead_pct = round((lead_used / lead_limit * 100) if lead_limit > 0 else 0.0, 1)

    out_limit = org.outreach_credits_limit or 0
    out_used = org.outreach_credits_used or 0
    out_remaining = max(0, out_limit - out_used)
    out_pct = round((out_used / out_limit * 100) if out_limit > 0 else 0.0, 1)

    return CreditUsageSummary(
        lead_credits_limit=lead_limit,
        lead_credits_used=lead_used,
        lead_credits_remaining=lead_remaining,
        lead_utilization_pct=lead_pct,
        outreach_credits_limit=out_limit,
        outreach_credits_used=out_used,
        outreach_credits_remaining=out_remaining,
        outreach_utilization_pct=out_pct,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=MeResponse,
    summary="Get current user profile, org details, and credit balance",
    operation_id="get_me",
)
def get_me(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> MeResponse:
    """Return the authenticated user's full profile including org info, credit balance, and entitled capabilities."""
    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    org = db.get(OrganizationRecord, user.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    meta = org.metadata_json or {}
    package_key = meta.get("package_key", "company_os_starter")
    pkg = get_package(package_key) or CATALOG.get("company_os_starter")
    entitled = pkg.entitled_capabilities if pkg else set()
    package_name = pkg.name if pkg else None

    return MeResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name or "",
        role=user.role,
        org_id=org.id,
        org_name=org.name,
        org_slug=org.slug or "",
        tier=org.tier,
        package_name=package_name,
        is_active=user.is_active,
        credits=_credit_usage(org),
        capabilities=_build_capability_entries(entitled),
        portal_url="https://os.askforwrite.com/portal",
    )


@router.get(
    "/usage",
    response_model=CreditUsageSummary,
    summary="Get monthly credit usage and remaining balance",
    operation_id="get_me_usage",
)
def get_me_usage(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> CreditUsageSummary:
    """Returns current billing-period credit consumption for the authenticated user's organization."""
    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    org = db.get(OrganizationRecord, user.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    return _credit_usage(org)


@router.get(
    "/billing",
    response_model=list[InvoiceSummary],
    summary="Get invoice and billing history for the tenant organization",
    operation_id="get_me_billing",
)
def get_me_billing(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> list[InvoiceSummary]:
    """Returns all invoice records for the authenticated user's organization, newest first."""
    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    invoices = (
        db.query(InvoiceRecord)
        .filter(InvoiceRecord.org_id == user.org_id)
        .order_by(InvoiceRecord.created_at.desc())
        .limit(50)
        .all()
    )

    return [
        InvoiceSummary(
            invoice_id=inv.id,
            amount=inv.amount,
            currency=inv.currency,
            status=inv.status,
            provider=inv.provider,
            created_at=inv.created_at,
        )
        for inv in invoices
    ]


@router.get(
    "/capabilities",
    response_model=list[CapabilityEntry],
    summary="List entitled capabilities for the current tenant plan",
    operation_id="get_me_capabilities",
)
def get_me_capabilities(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> list[CapabilityEntry]:
    """Returns all capabilities the tenant organization is entitled to under their current plan."""
    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    org = db.get(OrganizationRecord, user.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    meta = org.metadata_json or {}
    package_key = meta.get("package_key", "company_os_starter")
    pkg = get_package(package_key) or CATALOG.get("company_os_starter")
    entitled = pkg.entitled_capabilities if pkg else set()

    return _build_capability_entries(entitled)


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Self-service password change for authenticated users",
    operation_id="change_my_password",
)
def change_my_password(
    payload: PasswordChangeRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Allow an authenticated user to change their own password after verifying the current one."""
    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not user.password_hash or not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    user.password_hash = hash_password(payload.new_password)

    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id=principal.subject,
            capability_name="customer_portal",
            action="password_changed",
            input_payload={"user_id": user.id},
            output_payload={"status": "success"},
            status="COMPLETED",
        )
    )
    db.commit()

    logger.info("Password changed successfully for user %s", user.id)
    return {"status": "password_updated", "message": "Your password has been changed successfully."}
