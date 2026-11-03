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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

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
from app.services.catalog import CATALOG, build_payment_link, get_all_packages, get_package

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
        portal_url="https://os.askforwrite.com/portal",
        has_custom_gemini_key=has_custom,
        gemini_key_masked=masked,
    )


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


def is_service_entitled(service_key: str, entitled_caps: set[str], pkg_key: str | None = None) -> bool:
    """Validate whether the tenant's purchased plan includes the requested modular service."""
    if pkg_key == "all_access" or "all_access" in entitled_caps:
        return True
    
    capability_mapping = {
        "mango_quality_analytics": {"produce_quality_cv", "quality_analytics", "all_access"},
        "quality_analytics": {"produce_quality_cv", "quality_analytics", "all_access"},
        "quality_grading": {"produce_quality_cv", "quality_analytics", "all_access"},
        "bike_rebalance_analytics": {"bike_mobility_ai", "mobility_analytics", "all_access"},
        "mobility_analytics": {"bike_mobility_ai", "mobility_analytics", "all_access"},
        "bike_rebalance": {"bike_mobility_ai", "mobility_analytics", "all_access"},
        "warehouse_automation": {"warehouse_stocksense", "inventory_analytics", "all_access"},
        "inventory_analytics": {"warehouse_stocksense", "inventory_analytics", "all_access"},
        "inventory": {"warehouse_stocksense", "inventory_analytics", "all_access"},
        "ask4_academic_order": {"ask4_custom_development", "academic_research", "all_access"},
        "ask4": {"ask4_custom_development", "academic_research", "all_access"},
        "academic_research": {"ask4_custom_development", "academic_research", "all_access"},
        "pixel_ai_pack": {"pixel_ai_creative_studio", "all_access"},
        "pixel_ai": {"pixel_ai_creative_studio", "all_access"},
        "creative_pack": {"pixel_ai_creative_studio", "all_access"},
        "seo_blog_copilot": {"seo_content_automation", "all_access"},
        "seo_copilot": {"seo_content_automation", "all_access"},
        "marketing_suite": {"marketing_campaign_suite", "all_access"},
        "omnichannel_social": {"marketing_campaign_suite", "all_access"},
        "growth_all_in_one": {"growth_all_in_one", "seo_content_automation", "marketing_campaign_suite", "pixel_ai_creative_studio", "inbound_sales_closer", "all_access"},
        "growth_suite": {"growth_all_in_one", "seo_content_automation", "marketing_campaign_suite", "pixel_ai_creative_studio", "inbound_sales_closer", "all_access"},
        "trust_engine": {"trust_ledger_audit", "all_access"},
        "trust_ledger": {"trust_ledger_audit", "all_access"},
    }
    
    clean_key = service_key.strip().lower()
    required = capability_mapping.get(clean_key, {clean_key})
    # If the tenant holds growth_all_in_one or company_os master bundles, they get all core modular services
    if pkg_key in ("growth_all_in_one", "company_os_starter", "company_os_pro", "company_os_enterprise", "starter", "pro", "enterprise"):
        return True
    return bool(required & entitled_caps) or clean_key in entitled_caps


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


    if service_key in ("mango_quality_analytics", "quality_analytics", "quality_grading"):
        from app.services.quality_analytics import execute_produce_quality_inspection
        variety = input_payload.get("variety", "Alphonso Mango")
        lot_id = input_payload.get("lot_id") or input_payload.get("batch_lot_id") or f"LOT-PORTAL-{uuid.uuid4().hex[:6].upper()}"
        res = execute_produce_quality_inspection(
            db=db,
            preset_or_sample=input_payload.get("preset", "ripe"),
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
        exec_result = generate_and_stage_blog(
            product_name=input_payload.get("product_name", org.name),
            target_audience=input_payload.get("target_audience", "B2B Decision Makers"),
            keywords=input_payload.get("keywords", [org.name, "AI Automation", "Enterprise Growth"]),
        )

    elif service_key in ("marketing_suite", "omnichannel_social"):
        from app.services.growth_engine import generate_omnichannel_social_campaign
        exec_result = generate_omnichannel_social_campaign(
            product_name=input_payload.get("product_name", org.name),
            target_audience=input_payload.get("target_audience", "B2B Decision Makers"),
            keywords=input_payload.get("keywords", [org.name, "Growth Automation"]),
        )

    elif service_key in ("growth_all_in_one", "growth_suite"):
        from app.services.growth_engine import execute_unified_growth_run
        prod_name = input_payload.get("product_name") or input_payload.get("product_or_service") or org.name
        exec_result = execute_unified_growth_run(
            db=db,
            client_name=input_payload.get("client_name", org.name),
            product_or_service=prod_name,
            target_audience=input_payload.get("target_audience", "B2B Enterprise Buyers"),
            keywords=input_payload.get("keywords", [org.name, "AI Operations", "Growth"]),
            correlation_id=str(uuid.uuid4()),
            agent_id=user.email,
            idempotency_key=f"portal-growth-{uuid.uuid4()}",
        )

    elif service_key in ("trust_engine", "trust_ledger"):
        from app.security.trust_chain import seal_task_to_block, verify_chain_integrity
        task_id = str(uuid.uuid4())
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
            "block_index": block.index,
            "block_hash": block.block_hash,
            "signature": block.signature,
            "chain_valid": integrity.get("chain_valid", True),
        }

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Service '{service_key}' is not executable via /v1/me/use-service. "
                   "Supported: mango_quality_analytics, bike_rebalance_analytics, warehouse_automation, ask4_academic_order, pixel_ai_pack, seo_blog_copilot, marketing_suite, growth_all_in_one, trust_engine.",
        )

    if org.lead_credits_limit > 0:
        org.lead_credits_used += 1
        db.add(org)

    audit_task_id = str(uuid.uuid4())
    db.add(
        AuditLog(
            task_id=audit_task_id,
            correlation_id=str(uuid.uuid4()),
            agent_id=principal.subject,
            capability_name="customer_portal",
            action="use_service",
            input_payload={"service_key": service_key, "org_id": org.id, "user_id": user.id},
            output_payload={"status": "COMPLETED", "service_key": service_key},
            status="COMPLETED",
        )
    )
    db.commit()

    return {
        "status": "COMPLETED",
        "service_key": service_key,
        "org_id": org.id,
        "user_id": user.id,
        "result": exec_result,
        "credits_remaining": max(0, org.lead_credits_limit - org.lead_credits_used) if org.lead_credits_limit > 0 else 0,
        "credits_used": org.lead_credits_used,
    }
