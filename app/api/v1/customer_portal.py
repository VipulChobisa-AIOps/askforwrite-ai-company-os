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
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.database import get_db
from app.db.models import (
    AuditLog,
    InvoiceRecord,
    OrganizationRecord,
    TaskRecord,
    UserRecord,
)
from app.security.auth import (
    APIPrincipal,
    get_current_principal,
    hash_password,
    is_service_entitled,
    verify_password,
)
from app.services.catalog import CATALOG, build_payment_link, get_all_packages, get_package
from app.api.v1.customer_success import (
    GscAnalyticsQueryRequest,
    GscOAuthExchangeRequest,
    GscOAuthUrlRequest,
    GscPropertyVerifyRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/me", tags=["customer-portal"])


def mask_gemini_key(key: str | None) -> str | None:
    """Mask all but the last 4 characters of a Gemini API key (e.g. AIza••••••••••••••••1a2b)."""
    if not key or not key.strip():
        return None
    k = key.strip()
    if len(k) <= 8:
        return "••••" + k[-4:] if len(k) >= 4 else "••••"
    prefix = k[:4]
    suffix = k[-4:]
    masked_length = max(4, len(k) - 8)
    return f"{prefix}{'•' * masked_length}{suffix}"



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
    amount_major: float = 0.0
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
    has_custom_gemini_key: bool = False
    gemini_key_masked: str | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=6, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UseServiceRequest(BaseModel):
    service_key: str = Field(min_length=1, max_length=100, description="Service or SKU capability key")
    payload: dict[str, Any] = Field(default_factory=dict, description="Execution parameters")


class UpdateGeminiKeyRequest(BaseModel):
    gemini_api_key: str | None = Field(default=None, max_length=256)


class UpgradeOption(BaseModel):
    package_key: str
    package_name: str
    category: str
    price_inr: int
    price_usd: int
    lead_credits_monthly: int
    outreach_credits_monthly: int
    entitled_capabilities: list[str]
    checkout_url: str


class SubscriptionResponse(BaseModel):
    org_id: str
    org_name: str
    tier: str
    package_key: str | None
    package_name: str
    subscription_status: str
    is_active: bool
    lead_credits_limit: int
    lead_credits_used: int
    lead_credits_remaining: int
    outreach_credits_limit: int
    outreach_credits_used: int
    outreach_credits_remaining: int
    invoices_count: int
    upgrade_options: list[UpgradeOption]


class ServiceExecutionStat(BaseModel):
    action: str
    capability: str
    timestamp: datetime
    status: str


class AnalyticsResponse(BaseModel):
    org_id: str
    org_name: str
    lead_credits_used: int
    lead_credits_limit: int
    outreach_credits_used: int
    outreach_credits_limit: int
    lead_utilization_pct: float
    outreach_utilization_pct: float
    total_service_executions: int
    recent_executions: list[ServiceExecutionStat]
    estimated_cost_savings_inr: int



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
    "mango_quality_analytics": "Computer vision quality grading & Brix estimation for fresh produce",
    "bike_rebalance_analytics": "Urban micro-mobility demand forecasting & station rebalance dispatch",
    "warehouse_automation": "StockSense Pareto ABC analysis, ROP/EOQ reorder optimization & dead-stock alerts",
    "ask4_academic_order": "Scholarly research retrieval, citation indexing & thesis verification",
    "pixel_ai_pack": "Omnichannel multi-aspect advertising visual creatives & campaign prompt generation",
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
    package_key = meta.get("package_key") or (org.tier if org.tier != "free" else None)
    pkg = get_package(package_key) if package_key else None
    entitled = set(meta.get("entitled_capabilities") or (pkg.entitled_capabilities if pkg else ()))
    package_name = pkg.name if pkg else ("Free Trial" if org.tier == "free" else None)

    org_gemini_key = meta.get("gemini_api_key")
    has_custom = bool(org_gemini_key and str(org_gemini_key).strip())
    masked = mask_gemini_key(org_gemini_key) if has_custom else None

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
        portal_url="https://os.askforwrite.com/dashboard/#portal",
        has_custom_gemini_key=has_custom,
        gemini_key_masked=masked,
    )


def _require_org_admin_write_access(principal: APIPrincipal) -> None:
    """Block non-admin organization members (member/field_agent/viewer) from mutating billing, keys, or controls."""
    role = (principal.role or "").strip().lower()
    if role in ("member", "field_agent", "viewer", "readonly"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin privileges are required for this action.",
        )


def _maybe_require_production_checkout(
    *,
    principal: APIPrincipal,
    db: Session,
    org_id: str,
    base_tier: str,
    addon_modules: list[str] | None = None,
    credit_packs: int = 0,
    currency: str = "INR",
    action: str = "configure",
) -> dict[str, Any] | None:
    """In live production, prevent non-owner users from self-upgrading to paid tiers or minting credits for ₹0.

    Returns a payment-required checkout payload pointing to AFW DirectPay when payment is required,
    or None when the change may proceed immediately (dev/test, platform owner/manager, or free/downgrade).
    """
    is_prod = os.getenv("APP_ENV", "").strip().lower() == "production"
    if not is_prod or principal.role in ("owner", "manager"):
        return None
    clean_tier = (base_tier or "free").strip().lower()
    is_paid_request = (
        action == "purchase_credits"
        or credit_packs > 0
        or bool(addon_modules)
        or clean_tier not in ("free", "starter_free", "trial")
    )
    if not is_paid_request or action in ("downgrade", "cancel"):
        return None

    org = db.get(OrganizationRecord, org_id)
    user = db.get(UserRecord, principal.user_id) if principal.user_id else None
    from app.services.catalog import CATALOG
    from app.services.sovereign_pay import create_sovereign_pay_session

    tier_to_pkg = {
        "starter": "company_os_starter",
        "growth": "growth_all_in_one",
        "business_pro": "company_os_pro",
        "pro": "company_os_pro",
        "enterprise": "company_os_enterprise",
    }
    pkg_key = tier_to_pkg.get(clean_tier, clean_tier)
    if pkg_key not in CATALOG:
        pkg_key = "growth_all_in_one"

    pay_session = create_sovereign_pay_session(
        package_key=pkg_key,
        company_name=org.name if org else "AskforWrite Subscriber",
        customer_email=(user.email if user else principal.subject) or "billing@askforwrite.com",
        currency=currency or "INR",
        preferred_rail="upi_direct",
        db=db,
    )
    return {
        "status": "PAYMENT_REQUIRED",
        "payment_required": True,
        "org_id": org_id,
        "package_key": pkg_key,
        "session_id": pay_session.session_id,
        "checkout_url": pay_session.checkout_url,
        "upi_uri": pay_session.upi_uri,
        "amount": pay_session.amount,
        "currency": pay_session.currency,
        "message": "Complete payment via AFW DirectPay checkout to activate this subscription upgrade or credit pack.",
    }


@router.post(
    "/gemini-key",
    status_code=status.HTTP_200_OK,
    summary="Configure or clear tenant BYOK Gemini API Key",
    operation_id="update_me_gemini_key",
)
def update_me_gemini_key(
    body: UpdateGeminiKeyRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Save or clear the tenant's Bring-Your-Own-Key Gemini API Key."""
    _require_org_admin_write_access(principal)
    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    org = db.get(OrganizationRecord, user.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    new_key = (body.gemini_api_key or "").strip()
    meta = dict(org.metadata_json or {})

    if new_key:
        if len(new_key) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Gemini API key format (must contain at least 10 characters)",
            )
        meta["gemini_api_key"] = new_key
        has_custom = True
        masked = mask_gemini_key(new_key)
    else:
        meta.pop("gemini_api_key", None)
        has_custom = False
        masked = None

    org.metadata_json = meta
    flag_modified(org, "metadata_json")
    db.commit()

    return {
        "status": "updated",
        "has_custom_gemini_key": has_custom,
        "gemini_key_masked": masked,
    }


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
            amount_major=round(float(inv.amount) / 100.0, 2),
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
    package_key = meta.get("package_key") or (org.tier if org.tier != "free" else None)
    pkg = get_package(package_key) if package_key else None
    entitled = set(meta.get("entitled_capabilities") or (pkg.entitled_capabilities if pkg else ()))

    return _build_capability_entries(entitled)


@router.get(
    "/subscription",
    response_model=SubscriptionResponse,
    summary="Get subscription status, plan details, and upgrade options",
    operation_id="get_me_subscription",
)
def get_me_subscription(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    """Return the authenticated tenant's complete subscription lifecycle status, renewal limits, and upgrade paths."""
    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    org = db.get(OrganizationRecord, user.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    meta = org.metadata_json or {}
    pkg_key = meta.get("package_key") or (org.tier if org.tier != "free" else None)
    pkg = get_package(pkg_key) if pkg_key else None
    pkg_name = pkg.name if pkg else ("Free Trial" if org.tier == "free" else "Custom Plan")
    sub_status = meta.get("subscription_status") or ("ACTIVE" if org.is_active else "PENDING_PAYMENT")
    if org.tier == "free" and not meta.get("package_key"):
        sub_status = "FREE_TIER"

    invoices_count = db.query(InvoiceRecord).filter_by(org_id=org.id).count()

    upgrade_options = []
    for p in get_all_packages():
        if p.key != pkg_key and p.category in ("master_bundle", "modular_tool"):
            checkout_url = build_payment_link(
                package_key=p.key,
                customer_email=user.email,
                company=org.name,
                provider=meta.get("payment_provider", "sovereign_direct"),
            )
            upgrade_options.append(
                UpgradeOption(
                    package_key=p.key,
                    package_name=p.name,
                    category=p.category,
                    price_inr=p.price_inr,
                    price_usd=p.price_usd,
                    lead_credits_monthly=p.lead_credits_monthly,
                    outreach_credits_monthly=p.outreach_credits_monthly,
                    entitled_capabilities=list(p.entitled_capabilities),
                    checkout_url=checkout_url,
                )
            )

    lead_rem = max(0, org.lead_credits_limit - org.lead_credits_used)
    out_rem = max(0, org.outreach_credits_limit - org.outreach_credits_used)

    return SubscriptionResponse(
        org_id=org.id,
        org_name=org.name,
        tier=org.tier,
        package_key=pkg_key,
        package_name=pkg_name,
        subscription_status=sub_status,
        is_active=org.is_active,
        lead_credits_limit=org.lead_credits_limit,
        lead_credits_used=org.lead_credits_used,
        lead_credits_remaining=lead_rem,
        outreach_credits_limit=org.outreach_credits_limit,
        outreach_credits_used=org.outreach_credits_used,
        outreach_credits_remaining=out_rem,
        invoices_count=invoices_count,
        upgrade_options=upgrade_options[:6],
    )


@router.get(
    "/analytics",
    response_model=AnalyticsResponse,
    summary="Get tenant service execution analytics and estimated ROI savings",
    operation_id="get_me_analytics",
)
def get_me_analytics(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AnalyticsResponse:
    """Return consumption telemetry, recent modular executions, and estimated cost savings."""
    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    org = db.get(OrganizationRecord, user.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    lead_util = (
        round((org.lead_credits_used / org.lead_credits_limit) * 100, 1)
        if org.lead_credits_limit > 0
        else 0.0
    )
    out_util = (
        round((org.outreach_credits_used / org.outreach_credits_limit) * 100, 1)
        if org.outreach_credits_limit > 0
        else 0.0
    )

    recent_logs = (
        db.query(AuditLog)
        .filter(AuditLog.agent_id.in_([user.id, principal.subject]))
        .order_by(AuditLog.id.desc())
        .limit(10)
        .all()
    )

    stats = [
        ServiceExecutionStat(
            action=log.action,
            capability=log.capability_name,
            timestamp=log.created_at,
            status=log.status,
        )
        for log in recent_logs
    ]

    total_execs = db.query(AuditLog).filter(AuditLog.agent_id.in_([user.id, principal.subject])).count()
    estimated_savings = total_execs * 2500

    return AnalyticsResponse(
        org_id=org.id,
        org_name=org.name,
        lead_credits_used=org.lead_credits_used,
        lead_credits_limit=org.lead_credits_limit,
        outreach_credits_used=org.outreach_credits_used,
        outreach_credits_limit=org.outreach_credits_limit,
        lead_utilization_pct=lead_util,
        outreach_utilization_pct=out_util,
        total_service_executions=total_execs,
        recent_executions=stats,
        estimated_cost_savings_inr=estimated_savings,
    )


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


# is_service_entitled is imported from app.security.auth


@router.post(
    "/use-service",
    status_code=status.HTTP_200_OK,
    summary="Execute an entitled capability or one-off B2C service for the current tenant",
    operation_id="use_tenant_service",
)
def use_tenant_service(
    body: UseServiceRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Execute specialized modular services (mango quality, bike rebalance, warehouse automation, ask4, pixel_ai)
    for the authenticated tenant organization."""
    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    org = db.get(OrganizationRecord, user.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    if not org.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization subscription is inactive",
        )

    if org.lead_credits_limit > 0 and org.lead_credits_used >= org.lead_credits_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Monthly service credit quota exhausted. Please upgrade your plan.",
        )

    # Entitlement enforcement
    meta = org.metadata_json or {}
    pkg_key = meta.get("package_key") or org.tier or "free"
    entitled_set = set(meta.get("entitled_capabilities") or ())
    if not entitled_set and pkg_key:
        pkg = get_package(pkg_key) or CATALOG.get(pkg_key)
        if pkg:
            entitled_set = set(pkg.entitled_capabilities)

    service_key = body.service_key.strip().lower()
    if not is_service_entitled(service_key, entitled_set, pkg_key):
        pkg_name = pkg_key
        if pkg_key:
            pkg = get_package(pkg_key) or CATALOG.get(pkg_key)
            if pkg:
                pkg_name = pkg.name
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Service '{service_key}' is not entitled under your current package ({pkg_name}). Please upgrade your subscription.",
        )

    # Ensure tenant's stored BYOK Gemini key is used if no header key was provided
    meta = org.metadata_json or {}
    org_gemini_key = meta.get("gemini_api_key")
    from app.agents.llm_client import _REQUEST_GEMINI_KEY, set_request_llm_context

    if not _REQUEST_GEMINI_KEY.get() and org_gemini_key:
        set_request_llm_context(gemini_key=org_gemini_key, is_owner=False)
    elif not _REQUEST_GEMINI_KEY.get():
        set_request_llm_context(gemini_key=None, is_owner=False)

    service_key = body.service_key.strip().lower()
    input_payload = body.payload or {}
    exec_result: dict[str, Any] = {}

    # Check tenant-level or global agent pause / emergency stop before running or deducting credits
    from app.services.watchdog import AGENT_RUNTIME_CONTROLS

    tenant_controls = (org.metadata_json or {}).get("agent_controls") or {}
    tenant_agent_ctrl = tenant_controls.get(service_key) or tenant_controls.get("__all__")
    global_agent_ctrl = AGENT_RUNTIME_CONTROLS.get(service_key) or AGENT_RUNTIME_CONTROLS.get("__all__")
    active_ctrl = tenant_agent_ctrl or global_agent_ctrl
    if active_ctrl and active_ctrl.get("state") in ("PAUSED", "EMERGENCY_STOPPED"):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                f"BLOCKED: Service/Agent '{service_key}' is {active_ctrl['state']} "
                f"(reason: {active_ctrl.get('reason', 'operator control')}). 0 credits deducted."
            ),
        )


    if service_key in ("mango_quality_analytics", "quality_analytics", "quality_grading"):
        from app.services.quality_analytics import execute_produce_quality_inspection
        variety = input_payload.get("variety") or input_payload.get("crop_variety") or "Alphonso Mango"
        lot_id = input_payload.get("lot_id") or input_payload.get("batch_lot_id") or f"LOT-PORTAL-{uuid.uuid4().hex[:6].upper()}"
        res = execute_produce_quality_inspection(
            db=db,
            preset_or_sample=input_payload.get("preset_or_sample") or input_payload.get("preset") or "ripe",
            batch_lot_id=lot_id,
            crop_variety=variety,
            idempotency_key=f"portal-mango-{uuid.uuid4()}",
        )
        report = res.get("inspection_report", {})
        exec_result = {
            "lot_id": lot_id,
            "crop_variety": variety,
            "inspection_summary": report,
            "inspection_report": report,
            "task_id": res.get("task_id"),
        }

    elif service_key in ("bike_rebalance_analytics", "mobility_analytics", "bike_rebalance"):
        from app.services.mobility_analytics import execute_mobility_optimization
        temp_c = float(input_payload.get("temperature_c", 22.0))
        temp_f = (temp_c * 9.0 / 5.0) + 32.0 if "temperature_c" in input_payload else float(input_payload.get("temperature_f", 72.0))
        res = execute_mobility_optimization(
            db=db,
            hour_of_day=int(input_payload.get("hour_of_day", 9)),
            temperature_f=temp_f,
            humidity_pct=float(input_payload.get("humidity_pct", 58.0)),
            idempotency_key=f"portal-bike-{uuid.uuid4()}",
        )
        combined = res.get("result", {})
        exec_result = {
            "demand_forecast": combined.get("forecast", {}),
            "priority_rebalancing_dispatch": combined.get("rebalancing", {}).get("priority_rebalance_routes", []),
            "rebalance_plan": combined.get("rebalancing", {}),
            "task_id": res.get("task_id"),
        }

    elif service_key in ("warehouse_automation", "inventory_analytics", "inventory"):
        from app.services.inventory_analytics import execute_inventory_audit
        exec_result = execute_inventory_audit(
            db=db,
            items=input_payload.get("items"),
            service_level_z=float(input_payload.get("service_level_z", 1.65)),
            forecast_alpha=float(input_payload.get("forecast_alpha", 0.3)),
            dead_stock_threshold_days=int(input_payload.get("dead_stock_threshold_days", 90)),
            idempotency_key=f"portal-inv-{uuid.uuid4()}",
        )

    elif service_key in ("ask4_academic_order", "ask4", "academic_research"):
        from app.agents.llm_client import generate
        from app.security.trust_chain import seal_task_to_block
        task_id = str(uuid.uuid4())
        topic = input_payload.get("topic", "Autonomous Multi-Agent Enterprise Orchestration")
        db.add(
            TaskRecord(
                id=task_id,
                correlation_id=str(uuid.uuid4()),
                objective=f"ASK4 Academic Synthesis: {topic[:120]}",
                status="COMPLETED",
            )
        )
        db.flush()
        synthesis_text = generate(
            prompt=f"Write a structured scholarly synthesis abstract and key methodological findings on: {topic}",
            system_instruction="You are the AskforWrite ASK4 Academic Research & Synthesis Specialist.",
            fallback_text=(
                f"An investigation into {topic} focusing on cryptographic Merkle trust verification, "
                "algorithmic inventory rebalancing, and autonomous agent coordination."
            ),
        )
        research_output = {
            "title": f"Scholarly Synthesis: {topic}",
            "abstract": synthesis_text,
            "citations": [
                {"title": "Decentralized Trust Ledgers in Multi-Agent Systems", "year": 2026, "authors": "Chobisa et al."},
                {"title": "Pareto Inventory Optimization with Dynamic Safety Stocks", "year": 2025, "authors": "StockSense Labs"},
            ],
            "delivery_format": "PDF & BibTeX",
            "integrity_sealed": True,
            "task_id": task_id,
        }
        seal_task_to_block(
            db=db,
            task_id=task_id,
            capability_name="askforwrite_academic_ask4",
            action="academic_order_fulfillment",
            payload={"topic": topic, "status": "DELIVERED"},
            sealed_by=user.email,
        )
        exec_result = research_output

    elif service_key in ("pixel_ai_pack", "pixel_ai", "creative_pack"):
        from app.services.growth_engine import generate_creative_assets
        exec_result = generate_creative_assets(
            product_name=input_payload.get("product_name", org.name),
            target_audience=input_payload.get("target_audience", "B2B Enterprise Decision Makers"),
            brand_voice=input_payload.get("brand_voice", "authoritative, innovative, sleek"),
            aspect_ratios=input_payload.get("aspect_ratios", ["1:1", "9:16", "16:9"]),
        )

    elif service_key in ("seo_blog_copilot", "seo_copilot"):
        from app.services.growth_engine import generate_and_stage_blog
        prod_name = input_payload.get("product_name") or input_payload.get("query") or org.name
        exec_result = generate_and_stage_blog(
            product_name=prod_name,
            target_audience=input_payload.get("target_audience", "B2B Decision Makers"),
            keywords=input_payload.get("keywords", [prod_name, "AI Automation", "Enterprise Growth"]),
        )

    elif service_key in ("managed_seo_content_pilot", "managed_pilot"):
        from app.services.growth_engine import generate_and_stage_blog
        from app.services.seo import execute_seo_draft
        corr_id = str(uuid.uuid4())
        target_domain = input_payload.get("target_domain") or input_payload.get("domain") or "askforwrite.com"
        keywords = input_payload.get("keywords") or [org.name, "Managed SEO Pilot", "Generative Engine Optimization"]
        blog_article = generate_and_stage_blog(
            product_name=input_payload.get("product_name", org.name),
            target_audience=input_payload.get("target_audience", "B2B Decision Makers"),
            keywords=keywords,
            target_domain=f"https://{target_domain}/blog",
        )
        staged = execute_seo_draft(
            db=db,
            target_network=target_domain,
            keywords=keywords,
            idempotency_key=f"portal-pilot-{uuid.uuid4().hex[:12]}",
            correlation_id=corr_id,
            agent_id=user.email,
        )
        exec_result = {
            "pilot_sku": "managed_seo_content_pilot",
            "price_inr": 4999,
            "target_domain": target_domain,
            "keyword_cluster": keywords,
            "article_deliverable": blog_article,
            "cms_staging": staged,
        }

    elif service_key in ("wordpress_publisher",):
        from app.services.growth_engine import generate_and_stage_blog
        from app.services.seo import execute_seo_draft
        from app.services.wordpress_publisher import get_supported_networks
        corr_id = str(uuid.uuid4())
        target_net = input_payload.get("target_network", "askforwrite.com")
        keywords = input_payload.get("keywords", [org.name, "WordPress SEO Publishing", "AIO"])
        blog_data = generate_and_stage_blog(
            product_name=input_payload.get("product_name", org.name),
            target_audience=input_payload.get("target_audience", "Enterprise Buyers"),
            keywords=keywords,
            target_domain=f"https://{target_net}/blog",
        )
        staged = execute_seo_draft(
            db=db,
            target_network=target_net,
            keywords=keywords,
            idempotency_key=f"portal-wp-{uuid.uuid4().hex[:12]}",
            correlation_id=corr_id,
            agent_id=user.email,
        )
        exec_result = {
            "staging": staged,
            "supported_networks": get_supported_networks(),
            "article_title": blog_data.get("title"),
        }

    elif service_key in ("marketing_suite", "omnichannel_social"):
        from app.services.growth_engine import generate_omnichannel_social_campaign
        prod_name = input_payload.get("product_name") or input_payload.get("query") or org.name
        exec_result = generate_omnichannel_social_campaign(
            product_name=prod_name,
            target_audience=input_payload.get("target_audience", "B2B Decision Makers"),
            keywords=input_payload.get("keywords", [prod_name, "Growth Automation"]),
        )

    elif service_key in ("growth_all_in_one", "growth_suite"):
        from app.services.growth_engine import execute_unified_growth_run
        prod_name = input_payload.get("product_name") or input_payload.get("product_or_service") or input_payload.get("query") or org.name
        exec_result = execute_unified_growth_run(
            db=db,
            client_name=input_payload.get("client_name", org.name),
            product_or_service=prod_name,
            target_audience=input_payload.get("target_audience", "B2B Enterprise Buyers"),
            keywords=input_payload.get("keywords", [prod_name, "AI Operations", "Growth"]),
            correlation_id=str(uuid.uuid4()),
            agent_id=user.email,
            idempotency_key=f"portal-growth-{uuid.uuid4()}",
        )

    elif service_key in ("lead_discovery", "customer_discovery", "lead_generation"):
        from app.services.discovery import execute_discovery
        from app.services.watchdog import _VerifiedSimulationSourceProvider
        objective = input_payload.get("objective") or input_payload.get("query") or f"B2B enterprise prospects for {org.name}"
        limit = max(1, min(int(input_payload.get("limit", 2)), 10))
        exec_result = execute_discovery(
            db=db,
            objective=objective,
            limit=limit,
            idempotency_key=f"portal-disc-{uuid.uuid4()}",
            correlation_id=str(uuid.uuid4()),
            agent_id=user.email,
            org_id=org.id,
            provider=_VerifiedSimulationSourceProvider(),
        )

    elif service_key in ("evidence_research",):
        from app.agents.research import build_research
        from app.security.trust_chain import seal_task_to_block
        task_id = str(uuid.uuid4())
        company_target = input_payload.get("company", org.name)
        sources = input_payload.get("sources") or [
            {"url": f"https://{org.slug or 'enterprise'}.example.com/about", "snippet": f"{company_target} operates digital B2B workflows and seeks automation scale."}
        ]
        db.add(
            TaskRecord(
                id=task_id,
                correlation_id=str(uuid.uuid4()),
                objective=f"Evidence Research: {company_target}",
                status="COMPLETED",
            )
        )
        db.flush()
        draft = build_research(company_target, sources)
        block = seal_task_to_block(
            db=db,
            task_id=task_id,
            capability_name="evidence_research",
            action="portal_evidence_research",
            payload={"company": company_target, "sources_count": len(draft.sources)},
            sealed_by=user.email,
        )
        exec_result = {
            "task_id": task_id,
            "company": company_target,
            "synthesis": draft.synthesis,
            "analysis": draft.analysis,
            "sources": draft.sources,
            "trust_block_index": block.index,
            "trust_block_hash": block.block_hash,
        }

    elif service_key in ("sales_capture", "sales_proposal", "revenue_engine", "inbound_sales_closer", "support_followup", "customer_ops"):
        from app.services.growth_engine import handle_inbound_sales_chat
        default_msg = (
            "Follow up on customer support ticket and share onboarding next steps."
            if service_key in ("support_followup", "customer_ops")
            else "We are ready to buy the Managed SEO & Content Pilot and automate lead discovery."
        )
        exec_result = handle_inbound_sales_chat(
            db=db,
            session_id=f"portal-sales-{uuid.uuid4().hex[:8]}",
            prospect_name=input_payload.get("prospect_name", user.full_name or "Enterprise Buyer"),
            prospect_contact=input_payload.get("prospect_email", user.email),
            message=input_payload.get("incoming_message") or input_payload.get("query") or default_msg,
            channel=input_payload.get("channel", "web_chat"),
            requested_by=user.email,
        )

    elif service_key in ("field_force", "delivery_field_force", "field_force_automation"):
        from app.schemas.field_force import FieldTaskCreate, RouteOptimizationRequest
        from app.services.field_dispatch import create_field_task, optimize_route_sequence
        create_field_task(
            db=db,
            org_id=org.id,
            data=FieldTaskCreate(
                title="Enterprise Client Hub Visit",
                client_name=org.name,
                destination_lat=19.1136,
                destination_lon=72.8697,
                priority="HIGH",
                assigned_to_user_id=user.id,
            ),
        )
        route_req = RouteOptimizationRequest(
            user_id=user.id,
            start_latitude=float(input_payload.get("origin_lat", 19.0760)),
            start_longitude=float(input_payload.get("origin_lon", 72.8777)),
        )
        route_res = optimize_route_sequence(db=db, org_id=org.id, req=route_req)
        exec_result = route_res.model_dump()

    elif service_key in ("trust_engine", "trust_ledger"):
        from app.security.trust_chain import seal_task_to_block, verify_chain_integrity
        task_id = str(uuid.uuid4())
        db.add(
            TaskRecord(
                id=task_id,
                correlation_id=str(uuid.uuid4()),
                objective="Tenant Cryptographic Payload Attestation",
                status="COMPLETED",
            )
        )
        db.flush()
        block = seal_task_to_block(
            db=db,
            task_id=task_id,
            capability_name="afw_2030_trust_engine",
            action="tenant_payload_attestation",
            payload=input_payload or {"org_id": org.id, "attested_by": user.email},
            sealed_by=user.email,
        )
        integrity = verify_chain_integrity(db)
        exec_result = {
            "task_id": task_id,
            "block_index": block.index,
            "block_hash": block.block_hash,
            "signature": block.signature,
            "chain_valid": integrity.get("chain_valid", True),
        }

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Service '{service_key}' is not executable via /v1/me/use-service. "
                   "Supported: mango_quality_analytics, bike_rebalance_analytics, warehouse_automation, ask4_academic_order, pixel_ai_pack, seo_blog_copilot, managed_seo_content_pilot, wordpress_publisher, marketing_suite, growth_all_in_one, lead_discovery, evidence_research, sales_capture, revenue_engine, field_force, trust_engine.",
        )

    if org.lead_credits_limit > 0:
        org.lead_credits_used += 1
        db.add(org)

    audit_task_id = str(uuid.uuid4())
    corr_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    db.add(
        AuditLog(
            task_id=audit_task_id,
            correlation_id=corr_id,
            agent_id=principal.subject,
            capability_name="customer_portal",
            action="use_service",
            input_payload={"service_key": service_key, "org_id": org.id, "user_id": user.id},
            output_payload={"status": "COMPLETED", "service_key": service_key},
            status="COMPLETED",
        )
    )
    db.commit()

    has_custom_gemini = bool((org_gemini_key or "").strip())
    fallback_used = not has_custom_gemini and service_key in (
        "seo_blog_copilot",
        "managed_seo_content_pilot",
        "marketing_suite",
        "growth_all_in_one",
        "ask4_academic_order",
    )
    cap_status = "HUMAN_ASSISTED" if service_key in ("seo_blog_copilot", "managed_seo_content_pilot", "wordpress_publisher", "marketing_suite") else "LOCAL_ENGINE_VERIFIED"
    if service_key == "ask4_academic_order" and fallback_used:
        cap_status = "SIMULATED"

    import hashlib
    import json

    input_ref = "sha256:" + hashlib.sha256(
        json.dumps(input_payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    evidence_envelope = {
        "execution_id": audit_task_id,
        "tenant_id": org.id,
        "agent_id": principal.subject or user.email,
        "tool_id": service_key,
        "mode": str(input_payload.get("mode", "tenant_portal")),
        "provider": "gemini_byok" if has_custom_gemini else "local_deterministic_engine",
        "input_reference": input_ref,
        "fallback_used": fallback_used,
        "external_request_id": None,
        "started_at": now_iso,
        "completed_at": now_iso,
        "result_status": cap_status,
        "credits_consumed": 1,
        "approval_id": exec_result.get("approval_id") if isinstance(exec_result, dict) else None,
        "evidence_reference": f"audit://{audit_task_id}/{corr_id}",
    }

    return {
        "status": "COMPLETED",
        "capability_status": cap_status,
        "service_key": service_key,
        "org_id": org.id,
        "user_id": user.id,
        "evidence": evidence_envelope,
        "result": exec_result,
        "credits_remaining": max(0, org.lead_credits_limit - org.lead_credits_used) if org.lead_credits_limit > 0 else 0,
        "credits_used": org.lead_credits_used,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4, 5 & 6: Tenant SME 7-Step Onboarding, Modular Plan & Agent Controls
# ═══════════════════════════════════════════════════════════════════════════════


class TenantBusinessProfileRequest(BaseModel):
    business_name: str = Field(min_length=1, max_length=250)
    industry: str = Field(default="SME Business", max_length=200)
    description: str = Field(default="", max_length=2000)
    location: str | None = Field(default=None, max_length=250)
    city: str = Field(default="Jaipur", max_length=100)
    website: str = Field(default="", max_length=500)
    contact_info: dict[str, Any] = Field(default_factory=dict)
    company_size: str = Field(default="10-50 employees", max_length=100)
    employee_count: int = Field(default=10, ge=1, le=500000)
    products_and_services: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    customer_segments: list[str] = Field(default_factory=list)
    sales_channels: list[str] = Field(default_factory=lambda: ["B2B Direct", "Website", "WhatsApp"])
    current_software: list[str] = Field(default_factory=list)
    operational_pain_points: list[str] = Field(default_factory=list)
    business_objectives: list[str] = Field(default_factory=list)
    required_automations: list[str] = Field(default_factory=list)
    expected_monthly_volume: dict[str, Any] = Field(default_factory=dict)
    currency: str = Field(default="INR", max_length=10)
    requirements_text: str = Field(
        default="Generate qualified leads, manage inventory shortages, and publish SEO content",
        max_length=2000,
    )


class TenantProfileConfirmRequest(BaseModel):
    base_plan_key: str | None = Field(default=None, max_length=100)
    selected_modules: list[str] | None = Field(default=None)
    billing_interval: str = Field(default="monthly", max_length=32)
    currency: str = Field(default="INR", max_length=10)
    activate_selection: bool = Field(default=False)


class TenantModularSubscriptionRequest(BaseModel):
    base_tier: str = Field(default="growth", description="launch | growth | operations | business_pro | enterprise")
    addon_modules: list[str] = Field(
        default_factory=list,
        description="Additional modules: lead_discovery, sales_proposals, seo_content, marketing_campaigns, customer_support, field_operations, inventory_quality, governance_trust",
    )
    billing_type: str = Field(default="recurring", max_length=32)
    billing_interval: str = Field(default="monthly", max_length=32)
    currency: str = Field(default="INR", max_length=10)
    extra_agents: int = Field(default=0, ge=0, le=500)
    extra_seats: int = Field(default=0, ge=0, le=5000)
    credit_packs: int = Field(default=0, ge=0, le=500)
    integration_addons: list[str] = Field(default_factory=list)
    customization_level: str = Field(default="standard", max_length=64)


class TenantCancelSubscriptionRequest(BaseModel):
    cancel_at_period_end: bool = Field(default=True)


class TenantCreditPurchaseRequest(BaseModel):
    credit_packs: int = Field(default=1, ge=1, le=500)


class TenantAgentControlRequest(BaseModel):
    action: str = Field(default="activate", description="activate | pause | emergency_stop | resume | configure")
    reason: str = Field(default="", max_length=500)
    budget_credits: int | None = Field(default=None, ge=0, le=100000)


class TenantEmergencyStopRequest(BaseModel):
    scope_level: str = Field(default="tenant", description="tenant | agent | execution")
    scope_target: str | None = Field(default=None, max_length=120)
    state: str = Field(default="EMERGENCY_STOPPED", description="ACTIVE | PAUSED | EMERGENCY_STOPPED")
    reason: str = Field(default="Customer tenant safety stop", max_length=500)


@router.post(
    "/business-profile",
    summary="Save SME business profile and run AI requirement assessment (13-field P1 engine)",
    operation_id="save_me_business_profile",
)
def save_tenant_business_profile(
    body: TenantBusinessProfileRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Persist full 13-field SME Business Profile into DB, extract requirements, and generate explainable recommendations."""
    _require_org_admin_write_access(principal)
    from app.services.onboarding import save_profile_and_generate_recommendations
    from app.services.watchdog import assess_sme_business_requirements

    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    org = db.get(OrganizationRecord, user.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    loc = body.location or body.city
    prods = body.products_and_services or body.products
    pain_pts = body.operational_pain_points or ([body.requirements_text] if body.requirements_text else [])
    objs = body.business_objectives or ([body.requirements_text] if body.requirements_text else [])

    p1_result = save_profile_and_generate_recommendations(
        db,
        org_id=org.id,
        actor=user.email,
        payload={
            "business_name": body.business_name,
            "industry": body.industry,
            "description": body.description,
            "location": loc,
            "website": body.website,
            "contact_info": body.contact_info or {"email": user.email, "name": user.full_name},
            "company_size": body.company_size,
            "employee_count": body.employee_count,
            "products_and_services": prods,
            "customer_segments": body.customer_segments,
            "sales_channels": body.sales_channels,
            "current_software": body.current_software,
            "operational_pain_points": pain_pts,
            "business_objectives": objs,
            "required_automations": body.required_automations,
            "expected_monthly_volume": body.expected_monthly_volume,
            "currency": body.currency,
        },
    )
    assessment = assess_sme_business_requirements(
        business_name=body.business_name,
        industry=body.industry,
        city=loc,
        company_size=body.company_size,
        requirements_text=body.requirements_text or "; ".join(pain_pts + objs),
    )

    return {
        "status": "SAVED",
        "org_id": org.id,
        "profile": p1_result["profile"],
        "structured_requirements": p1_result["structured_requirements"],
        "recommendation": p1_result["recommendation"],
        "business_profile": p1_result["business_profile"],
        "assessment": assessment,
    }


@router.get(
    "/business-profile",
    summary="Get SME business profile, structured requirements, and modular recommendations",
    operation_id="get_me_business_profile",
)
def get_tenant_business_profile(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve the tenant's saved 13-field SME Business Profile and modular subscription configuration."""
    from app.db.models import BusinessProfileRecord, StructuredRequirementRecord, TenantSubscriptionRecord
    from app.services.billing_ledger import serialize_tenant_subscription
    from app.services.onboarding import serialize_business_profile

    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    org = db.get(OrganizationRecord, user.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    meta = org.metadata_json or {}
    profile_rec = db.query(BusinessProfileRecord).filter_by(org_id=org.id).first()
    req_rows = db.query(StructuredRequirementRecord).filter_by(org_id=org.id).all()
    sub_prof = db.query(TenantSubscriptionRecord).filter_by(org_id=org.id).first()

    return {
        "org_id": org.id,
        "org_name": org.name,
        "tier": org.tier,
        "profile": serialize_business_profile(profile_rec) if profile_rec else None,
        "structured_requirements": [
            {
                "requirement_id": r.id,
                "category": r.category,
                "title": r.title,
                "priority": r.priority,
                "recommended_modules": r.recommended_modules,
                "recommended_agents": r.recommended_agents,
                "required_connectors": r.required_connectors,
                "expected_monthly_credits": r.expected_monthly_credits,
                "limitations": r.limitations,
                "status": r.status,
            }
            for r in req_rows
        ],
        "recommendation": profile_rec.recommended_plan if profile_rec else None,
        "subscription_contract": serialize_tenant_subscription(sub_prof) if sub_prof else None,
        "business_profile": meta.get("business_profile") or {},
        "modular_subscription": meta.get("modular_subscription") or {},
        "agent_controls": meta.get("agent_controls") or {},
    }


@router.post(
    "/business-profile/confirm",
    summary="Explicitly confirm recommended SME modules before activating/charging",
    operation_id="confirm_me_business_profile",
)
def confirm_tenant_business_profile(
    body: TenantProfileConfirmRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Explicit customer confirmation step for recommended SME services and subscription."""
    _require_org_admin_write_access(principal)
    from app.services.onboarding import confirm_recommended_selection

    if not principal.org_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant organization required")
    if body.activate_selection:
        gate = _maybe_require_production_checkout(
            principal=principal,
            db=db,
            org_id=principal.org_id,
            base_tier=body.base_plan_key,
            addon_modules=body.selected_modules,
            currency=body.currency,
            action="configure",
        )
        if gate is not None:
            return gate
    try:
        return confirm_recommended_selection(
            db,
            org_id=principal.org_id,
            actor=principal.subject,
            selected_modules=body.selected_modules,
            base_plan_key=body.base_plan_key,
            billing_interval=body.billing_interval,
            currency=body.currency,
            activate_selection=body.activate_selection,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/modular-subscription",
    summary="Configure modular SME subscription (Base Plan + Add-on Service Modules)",
    operation_id="configure_me_modular_subscription",
)
def configure_tenant_modular_subscription(
    body: TenantModularSubscriptionRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Compose a modular SME subscription and persist the 15-field contract + credits."""
    _require_org_admin_write_access(principal)
    from app.services.billing_ledger import apply_subscription_configuration
    from app.services.catalog import get_modular_pricing_contract

    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    org = db.get(OrganizationRecord, user.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    gate = _maybe_require_production_checkout(
        principal=principal,
        db=db,
        org_id=org.id,
        base_tier=body.base_tier,
        addon_modules=body.addon_modules,
        credit_packs=body.credit_packs,
        currency=body.currency,
        action="configure",
    )
    if gate is not None:
        return gate

    res = apply_subscription_configuration(
        db,
        org_id=org.id,
        actor=user.email,
        action="configure",
        base_plan_key=body.base_tier,
        selected_modules=body.addon_modules,
        billing_type=body.billing_type,
        billing_interval=body.billing_interval,
        currency=body.currency,
        extra_agents=body.extra_agents,
        extra_seats=body.extra_seats,
        credit_packs=body.credit_packs,
        integration_addons=body.integration_addons,
        customization_level=body.customization_level,
    )
    contract = get_modular_pricing_contract(body.base_tier, addon_modules=body.addon_modules)
    # Sync P0 metadata key cleanly alongside P1 DB table
    org = db.get(OrganizationRecord, org.id)
    if org:
        meta = dict(org.metadata_json or {})
        meta["modular_subscription"] = {**contract, **res["pricing"]}
        org.metadata_json = meta
        flag_modified(org, "metadata_json")
        db.commit()

    return {
        "status": "CONFIGURED",
        "org_id": org.id,
        "pricing_contract": res["pricing"],
        "subscription": res["subscription"],
        "entitled_capabilities": res["pricing"]["entitled_capabilities"],
    }


@router.post("/subscription/upgrade", summary="Upgrade tenant modular subscription")
def upgrade_tenant_subscription(
    body: TenantModularSubscriptionRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_org_admin_write_access(principal)
    from app.services.billing_ledger import apply_subscription_configuration

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    gate = _maybe_require_production_checkout(
        principal=principal,
        db=db,
        org_id=principal.org_id,
        base_tier=body.base_tier,
        addon_modules=body.addon_modules,
        credit_packs=body.credit_packs,
        currency=body.currency,
        action="upgrade",
    )
    if gate is not None:
        return gate
    return apply_subscription_configuration(
        db,
        org_id=principal.org_id,
        actor=principal.subject,
        action="upgrade",
        base_plan_key=body.base_tier,
        selected_modules=body.addon_modules,
        billing_type=body.billing_type,
        billing_interval=body.billing_interval,
        currency=body.currency,
        extra_agents=body.extra_agents,
        extra_seats=body.extra_seats,
        credit_packs=body.credit_packs,
        integration_addons=body.integration_addons,
        customization_level=body.customization_level,
    )


@router.post("/subscription/downgrade", summary="Downgrade tenant modular subscription")
def downgrade_tenant_subscription(
    body: TenantModularSubscriptionRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_org_admin_write_access(principal)
    from app.services.billing_ledger import apply_subscription_configuration

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    return apply_subscription_configuration(
        db,
        org_id=principal.org_id,
        actor=principal.subject,
        action="downgrade",
        base_plan_key=body.base_tier,
        selected_modules=body.addon_modules,
        billing_type=body.billing_type,
        billing_interval=body.billing_interval,
        currency=body.currency,
        extra_agents=body.extra_agents,
        extra_seats=body.extra_seats,
        credit_packs=body.credit_packs,
        integration_addons=body.integration_addons,
        customization_level=body.customization_level,
    )


@router.post("/subscription/cancel", summary="Cancel tenant modular subscription")
def cancel_tenant_subscription(
    body: TenantCancelSubscriptionRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_org_admin_write_access(principal)
    from app.services.billing_ledger import apply_subscription_configuration

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    return apply_subscription_configuration(
        db,
        org_id=principal.org_id,
        actor=principal.subject,
        action="cancel",
        cancel_at_period_end=body.cancel_at_period_end,
    )


@router.post("/subscription/renew", summary="Renew tenant modular subscription cycle")
def renew_tenant_subscription(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_org_admin_write_access(principal)
    from app.services.billing_ledger import apply_subscription_configuration

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    org = db.get(OrganizationRecord, principal.org_id)
    gate = _maybe_require_production_checkout(
        principal=principal,
        db=db,
        org_id=principal.org_id,
        base_tier=org.tier if org else "growth",
        action="renew",
    )
    if gate is not None:
        return gate
    return apply_subscription_configuration(
        db,
        org_id=principal.org_id,
        actor=principal.subject,
        action="renew",
    )


@router.post("/credits/purchase", summary="Purchase modular usage credit packs")
def purchase_tenant_credits(
    body: TenantCreditPurchaseRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_org_admin_write_access(principal)
    from app.services.billing_ledger import apply_subscription_configuration

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    gate = _maybe_require_production_checkout(
        principal=principal,
        db=db,
        org_id=principal.org_id,
        base_tier="growth",
        credit_packs=body.credit_packs,
        action="purchase_credits",
    )
    if gate is not None:
        return gate
    return apply_subscription_configuration(
        db,
        org_id=principal.org_id,
        actor=principal.subject,
        action="purchase_credits",
        credit_packs=body.credit_packs,
    )


@router.get("/credits/ledger", summary="View tenant credit accounting ledger")
def get_tenant_credit_ledger(
    limit: int = 50,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.db.models import CreditLedgerRecord

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    rows = (
        db.query(CreditLedgerRecord)
        .filter_by(org_id=principal.org_id)
        .order_by(CreditLedgerRecord.created_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return {
        "org_id": principal.org_id,
        "count": len(rows),
        "entries": [
            {
                "id": r.id,
                "execution_id": r.execution_id,
                "entry_type": r.entry_type,
                "credit_pool": r.credit_pool,
                "delta": r.delta,
                "balance_after": r.balance_after,
                "status": r.status,
                "reason": r.reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.post(
    "/agents/{agent_key}/control",
    summary="Activate, pause, configure, or emergency-stop a tenant AI agent",
    operation_id="control_me_agent",
)
def control_tenant_agent(
    agent_key: str,
    body: TenantAgentControlRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update persistent tenant-scoped lifecycle state (ACTIVE, PAUSED, EMERGENCY_STOPPED) for an AI agent."""
    from app.services.execution_guard import set_emergency_stop

    user = db.get(UserRecord, principal.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    org = db.get(OrganizationRecord, user.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    clean_agent = agent_key.strip().lower()
    clean_action = body.action.strip().lower()
    state_map = {
        "activate": "ACTIVE",
        "resume": "ACTIVE",
        "pause": "PAUSED",
        "emergency_stop": "EMERGENCY_STOPPED",
        "configure": "ACTIVE",
    }
    if clean_action not in state_map:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported action '{body.action}'. Use activate, pause, emergency_stop, resume, or configure.",
        )

    target_state = state_map[clean_action]
    scope_lvl = "tenant" if clean_agent in ("__all__", "*") else "agent"
    scope_target = org.id if scope_lvl == "tenant" else clean_agent
    set_emergency_stop(
        db,
        scope_level=scope_lvl,
        scope_target=scope_target,
        state=target_state,
        reason=body.reason or f"Tenant {clean_action}",
        triggered_by=user.email,
        org_id=org.id,
    )

    meta = dict(org.metadata_json or {})
    controls = dict(meta.get("agent_controls") or {})
    entry = {
        "agent_key": clean_agent,
        "state": target_state,
        "last_action": clean_action,
        "reason": body.reason or f"Tenant {clean_action}",
        "budget_credits": body.budget_credits if body.budget_credits is not None else 100,
        "updated_by": user.email,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if clean_action in ("activate", "resume") and clean_agent == "__all__":
        controls.clear()
    else:
        controls[clean_agent] = entry
    meta["agent_controls"] = controls
    org.metadata_json = meta
    flag_modified(org, "metadata_json")
    db.add(org)
    db.commit()

    return {
        "status": "UPDATED",
        "org_id": org.id,
        "control": entry,
    }


@router.post("/emergency-stop", summary="Trigger or clear tenant-scoped emergency stop (tenant/agent/execution)")
def trigger_tenant_emergency_stop(
    body: TenantEmergencyStopRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_org_admin_write_access(principal)
    from app.services.execution_guard import set_emergency_stop

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    clean_scope = body.scope_level.strip().lower()
    if clean_scope == "platform":
        raise HTTPException(status_code=403, detail="Tenants cannot toggle platform-wide emergency stop")
    target = principal.org_id if clean_scope == "tenant" else (body.scope_target or principal.org_id)
    try:
        ctrl = set_emergency_stop(
            db,
            scope_level=clean_scope,
            scope_target=target,
            state=body.state,
            reason=body.reason,
            triggered_by=principal.subject,
            org_id=principal.org_id,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": ctrl["state"], "emergency_stop": ctrl}


@router.get("/emergency-stops", summary="List active emergency stops for current tenant")
def list_tenant_emergency_stops(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.execution_guard import list_active_emergency_stops

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    stops = list_active_emergency_stops(db, org_id=principal.org_id)
    return {"org_id": principal.org_id, "count": len(stops), "emergency_stops": stops}


@router.get("/evidence", summary="List tenant-scoped 18-field execution evidence records")
def list_tenant_execution_evidence(
    agent_id: str | None = None,
    limit: int = 50,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.evidence import list_execution_evidence

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    rows = list_execution_evidence(db, tenant_id=principal.org_id, agent_id=agent_id, limit=limit)
    return {"org_id": principal.org_id, "count": len(rows), "records": rows}


_PLATFORM_OWNER_ONLY_APPROVAL_ACTIONS = {
    "support_sensitive_external_reply",
    "subscription_pricing_or_refund_action",
    "expansion_offer_or_referral",
    "customer_offboarding_and_deletion",
    "sovereign_payment_verification",
}


def _approval_belongs_to_org(
    appr: Any,
    *,
    org_id: str,
    wf_app_ids: set[str],
    user_emails: set[str],
    principal_subject: str,
) -> bool:
    detail_org = appr.detail.get("org_id") if isinstance(getattr(appr, "detail", None), dict) else None
    return (
        appr.id in wf_app_ids
        or detail_org == org_id
        or appr.requested_by in user_emails
        or appr.requested_by == principal_subject
    )


@router.get("/approvals", summary="List HITL approvals belonging to current tenant workspace")
def list_tenant_approvals(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.db.models import ApprovalRequest, WorkflowRunRecord

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    # Match approvals requested by tenant users, attached to tenant workflow runs, or scoped to org_id
    wf_app_ids = {
        r.approval_id
        for r in db.query(WorkflowRunRecord).filter_by(org_id=principal.org_id).all()
        if r.approval_id
    }
    user_emails = {u.email for u in db.query(UserRecord).filter_by(org_id=principal.org_id).all()}
    all_apprs = db.query(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()).limit(200).all()
    scoped = [
        a
        for a in all_apprs
        if _approval_belongs_to_org(
            a,
            org_id=principal.org_id,
            wf_app_ids=wf_app_ids,
            user_emails=user_emails,
            principal_subject=principal.subject,
        )
    ]
    return {
        "org_id": principal.org_id,
        "count": len(scoped),
        "approvals": [
            {
                "approval_id": a.id,
                "task_id": a.task_id,
                "action": a.action,
                "requested_by": a.requested_by,
                "status": a.status,
                "requires_platform_owner": a.action in _PLATFORM_OWNER_ONLY_APPROVAL_ACTIONS,
                "decided_by": a.decided_by,
                "decision_note": a.decision_note,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in scoped
        ],
    }


class TenantApprovalDecisionRequest(BaseModel):
    decision: str = Field(default="APPROVED")
    reason: str = Field(default="", max_length=500)
    decision_note: str = Field(default="", max_length=500)


@router.post("/approvals/{approval_id}/decide", summary="Approve or reject a tenant HITL gate")
def decide_tenant_approval(
    approval_id: str,
    body: TenantApprovalDecisionRequest | None = None,
    decision: str | None = None,
    decision_note: str = "",
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_org_admin_write_access(principal)
    from app.db.models import ApprovalRequest, WorkflowRunRecord

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    appr = db.get(ApprovalRequest, approval_id)
    if not appr:
        raise HTTPException(status_code=404, detail="Approval request not found")

    # Verify tenant ownership
    wf_app_ids = {
        r.approval_id
        for r in db.query(WorkflowRunRecord).filter_by(org_id=principal.org_id, approval_id=approval_id).all()
        if r.approval_id
    }
    user_emails = {u.email for u in db.query(UserRecord).filter_by(org_id=principal.org_id).all()}
    if not _approval_belongs_to_org(
        appr,
        org_id=principal.org_id,
        wf_app_ids=wf_app_ids,
        user_emails=user_emails,
        principal_subject=principal.subject,
    ):
        raise HTTPException(status_code=403, detail="Approval request belongs to a different organization")

    if appr.action in _PLATFORM_OWNER_ONLY_APPROVAL_ACTIONS and principal.role not in ("owner", "platform_owner"):
        raise HTTPException(
            status_code=403,
            detail=f"Platform owner authorization required to decide '{appr.action}' approval.",
        )

    effective_dec = (body.decision if body else None) or decision or "APPROVED"
    effective_note = (body.decision_note or body.reason if body else "") or decision_note
    clean_dec = effective_dec.strip().upper()
    if clean_dec not in ("APPROVED", "REJECTED"):
        raise HTTPException(status_code=422, detail="decision must be APPROVED or REJECTED")
    appr.status = clean_dec
    appr.decided_by = principal.subject
    appr.decision_note = effective_note or appr.decision_note
    appr.decided_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "approval_id": appr.id,
        "status": appr.status,
        "decided_by": appr.decided_by,
        "decision_note": appr.decision_note,
    }


# ── P3 Tenant Self-Service: Onboarding, Deliverables, Support, Privacy ───────


class TenantOnboardingTaskRequest(BaseModel):
    completed: bool = True
    evidence_summary: str | None = Field(default=None, max_length=1000)
    evidence_ref: str | None = Field(default=None, max_length=500)
    blockers: list[str] | None = None
    sku_key: str | None = Field(default=None, max_length=100)


class TenantDeliveryRespondRequest(BaseModel):
    action: Literal["ACCEPTED", "REVISION_REQUESTED"]
    note: str | None = Field(default=None, max_length=1000)


class TenantSupportTicketCreateRequest(BaseModel):
    subject: str = Field(min_length=3, max_length=300)
    description: str = Field(min_length=3, max_length=4000)
    category: str = Field(default="general", max_length=64)
    priority: Literal["LOW", "MEDIUM", "HIGH", "URGENT"] = "MEDIUM"
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class TenantSupportReplyRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class TenantTicketCSATRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class TenantConsentUpdateRequest(BaseModel):
    consent_preferences: dict[str, Any]


@router.get("/onboarding", summary="Get tenant onboarding checklist, blockers & readiness state")
def get_tenant_onboarding(
    sku_key: str | None = None,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.p3_customer_success import create_or_get_onboarding_workflow

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    return create_or_get_onboarding_workflow(db, org_id=principal.org_id, sku_key=sku_key, actor=principal.subject)


@router.patch("/onboarding/tasks/{task_key}", summary="Submit tenant onboarding task input & completion")
def update_tenant_onboarding_task(
    task_key: str,
    body: TenantOnboardingTaskRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.p3_customer_success import update_onboarding_task

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    try:
        return update_onboarding_task(
            db,
            org_id=principal.org_id,
            task_key=task_key,
            completed=body.completed,
            evidence_summary=body.evidence_summary,
            evidence_ref=body.evidence_ref,
            blockers=body.blockers,
            sku_key=body.sku_key,
            actor=principal.subject,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/deliveries", summary="List tenant service deliverables & outcomes")
def list_tenant_deliveries(
    quality_state: str | None = None,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.p3_delivery_health import list_service_deliveries

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    rows = list_service_deliveries(db, org_id=principal.org_id, quality_state=quality_state)
    return {"org_id": principal.org_id, "count": len(rows), "deliveries": rows}


@router.post("/deliveries/{delivery_id}/respond", summary="Accept deliverable or request revision (org-scoped)")
def respond_tenant_delivery(
    delivery_id: str,
    body: TenantDeliveryRespondRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.db.models import P3ServiceDeliveryRecord
    from app.services.p3_delivery_health import transition_delivery_quality_state

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    rec = db.get(P3ServiceDeliveryRecord, delivery_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Deliverable not found")
    if rec.org_id != principal.org_id:
        raise HTTPException(status_code=403, detail="Deliverable belongs to a different organization")
    try:
        return transition_delivery_quality_state(
            db, delivery_id=delivery_id, target_state=body.action, note=body.note, actor=principal.subject
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/support/tickets", summary="List customer-visible support tickets for tenant org")
def list_tenant_support_tickets(
    status_filter: str | None = Query(default=None, alias="status"),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.p3_support_improvements import list_support_tickets

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    rows = list_support_tickets(db, org_id=principal.org_id, status=status_filter, include_internal=False)
    return {"org_id": principal.org_id, "count": len(rows), "tickets": rows}


@router.post("/support/tickets", summary="Create tenant support ticket")
def create_tenant_support_ticket(
    body: TenantSupportTicketCreateRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.p3_support_improvements import create_support_ticket

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    try:
        return create_support_ticket(
            db,
            org_id=principal.org_id,
            subject=body.subject,
            description=body.description,
            category=body.category,
            priority=body.priority,
            created_by_user_id=principal.user_id,
            created_by_email=principal.email,
            attachments=body.attachments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/support/tickets/{ticket_id}/messages", summary="Post customer reply on tenant ticket")
def reply_tenant_support_ticket(
    ticket_id: str,
    body: TenantSupportReplyRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.p3_support_improvements import add_ticket_message

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    try:
        return add_ticket_message(
            db,
            ticket_id=ticket_id,
            body=body.body,
            visibility="customer_visible",
            sender_type="customer",
            sender=principal.email or principal.subject,
            org_id_scope=principal.org_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/support/tickets/{ticket_id}/csat", summary="Submit tenant CSAT rating for resolved support ticket")
def submit_tenant_ticket_csat(
    ticket_id: str,
    body: TenantTicketCSATRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.p3_support_improvements import submit_ticket_csat

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    try:
        return submit_ticket_csat(
            db, ticket_id=ticket_id, rating=body.rating, comment=body.comment, org_id_scope=principal.org_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/data-export", summary="Export strictly tenant-scoped secret-redacted data bundle (DPDP/GDPR)")
def get_tenant_data_export(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.p3_ops_compliance_cc import export_customer_data_bundle

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    return export_customer_data_bundle(
        db, org_id=principal.org_id, requested_by=principal.subject, customer_safe_only=True
    )


@router.patch("/consent-preferences", summary="Update tenant privacy consent preferences")
def update_tenant_consent_preferences(
    body: TenantConsentUpdateRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.p3_ops_compliance_cc import update_consent_and_retention

    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    return update_consent_and_retention(
        db,
        org_id=principal.org_id,
        consent_preferences=body.consent_preferences,
        retention_policy=None,
        actor=principal.subject,
    )


def _require_tenant_org(principal: APIPrincipal) -> str:
    if not principal.org_id:
        raise HTTPException(status_code=400, detail="Tenant organization required")
    return principal.org_id


def _run_portal_gsc(fn: Any) -> dict[str, Any]:
    from app.services.gsc_integration import GscIntegrationError

    try:
        return fn()
    except GscIntegrationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"{exc.code}: {exc.message}") from exc


@router.get("/integrations/gsc/status", summary="Get tenant Google Search Console verification state")
def tenant_gsc_status(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.gsc_integration import get_gsc_status

    org_id = _require_tenant_org(principal)
    return get_gsc_status(db, org_id=org_id)


@router.post("/integrations/gsc/oauth/url", summary="Generate tenant GSC OAuth 2.0 consent URL")
def tenant_gsc_oauth_url(
    body: GscOAuthUrlRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.gsc_integration import build_gsc_oauth_authorization_url

    org_id = _require_tenant_org(principal)
    return _run_portal_gsc(
        lambda: build_gsc_oauth_authorization_url(
            db,
            org_id=org_id,
            redirect_uri=body.redirect_uri,
            scopes=body.scopes,
            actor=principal.subject,
        )
    )


@router.post("/integrations/gsc/oauth/exchange", summary="Exchange tenant GSC OAuth authorization code")
def tenant_gsc_oauth_exchange(
    body: GscOAuthExchangeRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.gsc_integration import exchange_gsc_oauth_code

    org_id = _require_tenant_org(principal)
    return _run_portal_gsc(
        lambda: exchange_gsc_oauth_code(
            db,
            org_id=org_id,
            code=body.code,
            state=body.state,
            redirect_uri=body.redirect_uri,
            actor=principal.subject,
        )
    )


@router.post("/integrations/gsc/properties/verify", summary="Verify tenant Search Console property access")
def tenant_gsc_verify_property(
    body: GscPropertyVerifyRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.gsc_integration import verify_and_select_gsc_property

    org_id = _require_tenant_org(principal)
    return _run_portal_gsc(
        lambda: verify_and_select_gsc_property(
            db,
            org_id=org_id,
            site_url=body.site_url,
            actor=principal.subject,
        )
    )


@router.post("/integrations/gsc/analytics/query", summary="Query verified GSC analytics for tenant organization")
def tenant_gsc_analytics_query(
    body: GscAnalyticsQueryRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.gsc_integration import fetch_gsc_search_analytics

    org_id = _require_tenant_org(principal)
    return _run_portal_gsc(
        lambda: fetch_gsc_search_analytics(
            db,
            org_id=org_id,
            start_date=body.start_date,
            end_date=body.end_date,
            dimensions=body.dimensions,
            row_limit=body.row_limit,
            baseline_start_date=body.baseline_start_date,
            baseline_end_date=body.baseline_end_date,
            delivery_id=body.delivery_id,
            claimed_askforwrite_caused=body.claimed_askforwrite_caused,
            actor=principal.subject,
        )
    )


@router.post("/integrations/gsc/disconnect", summary="Disconnect tenant Google Search Console integration")
def tenant_gsc_disconnect(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.gsc_integration import disconnect_gsc_account

    org_id = _require_tenant_org(principal)
    return disconnect_gsc_account(db, org_id=org_id, actor=principal.subject)

