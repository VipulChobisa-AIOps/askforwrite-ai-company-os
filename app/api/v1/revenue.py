"""Commercial Catalog and Revenue Growth API router.

Endpoints for:
- Catalog: Query modular tool subscriptions and full Company OS bundles with Razorpay & PayPal pricing
- Diagnostic: Diagnose prospect operational pain points from website signals and recommend packages
- Pitch Lead: End-to-end diagnosis and outreach draft creation with embedded one-click payment links
"""

from __future__ import annotations

import logging
import uuid

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.revenue_agent import (
    diagnose_lead_opportunity,
)
from app.db.database import get_db
from app.db.models import (
    ApprovalRequest,
    InvoiceRecord,
    LeadRecordRow,
    OrganizationRecord,
    OutreachRecord,
    PreviewRecord,
    SovereignPaymentSessionRecord,
    SubscriptionRecord,
)
from app.schemas.catalog import (
    CatalogListResponse,
    DiagnoseRequest,
    DiagnoseResponse,
    PackageResponse,
    PitchLeadRequest,
    PitchLeadResponse,
)
from app.security.auth import APIPrincipal, enforce_tenant_access, require_manager
from app.services.catalog import (
    CATALOG,
    build_payment_link,
    get_all_packages,
    get_package,
)
from app.services.outreach import draft_outreach

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/revenue", tags=["revenue"])


@router.get("/catalog", response_model=CatalogListResponse)
def get_commercial_catalog() -> CatalogListResponse:
    """Retrieve full commercial pricing matrix for Modular Tools and Master Company OS bundles."""
    packages = []
    for pkg in get_all_packages():
        razorpay_url = build_payment_link(package_key=pkg.key, provider="razorpay")
        paypal_url = build_payment_link(package_key=pkg.key, provider="paypal")
        packages.append(
            PackageResponse(
                key=pkg.key,
                name=pkg.name,
                category=pkg.category,
                description=pkg.description,
                target_buyer_persona=pkg.target_buyer_persona,
                target_pain_point=pkg.target_pain_point,
                key_features=list(pkg.key_features),
                deliverables=list(pkg.deliverables),
                seo_geo_aio_capabilities=list(pkg.seo_geo_aio_capabilities),
                price_inr=pkg.price_inr,
                price_usd=pkg.price_usd,
                currency_default=pkg.currency_default,
                entitled_capabilities=list(pkg.entitled_capabilities),
                lead_credits_monthly=pkg.lead_credits_monthly,
                outreach_credits_monthly=pkg.outreach_credits_monthly,
                tier=pkg.tier,
                razorpay_checkout_url=razorpay_url,
                paypal_checkout_url=paypal_url,
            )
        )
    return CatalogListResponse(count=len(packages), packages=packages)


@router.post("/diagnose", response_model=DiagnoseResponse)
def diagnose_prospect(payload: DiagnoseRequest) -> DiagnoseResponse:
    """Diagnose prospect operational friction and recommend the optimal modular tool or master bundle."""
    diagnosis = diagnose_lead_opportunity(
        company=payload.company,
        website=payload.website,
        signals=payload.observed_signals,
        geography=payload.geography,
        industry=payload.industry,
    )
    return DiagnoseResponse(**diagnosis)


@router.post("/pitch-lead", response_model=PitchLeadResponse, status_code=status.HTTP_200_OK)
def pitch_lead_endpoint(
    payload: PitchLeadRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> PitchLeadResponse:
    """Diagnose lead pain, draft commercial proposal with Razorpay/PayPal link, and submit for Owner approval."""
    lead = db.get(LeadRecordRow, payload.lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    if principal.org_id:
        if payload.org_id:
            enforce_tenant_access(principal, payload.org_id)
        enforce_tenant_access(principal, lead.org_id or "__platform__")

    correlation_id = x_correlation_id or str(uuid.uuid4())

    try:
        draft = draft_outreach(
            db=db,
            lead_id=payload.lead_id,
            org_id=payload.org_id or principal.org_id or lead.org_id,
            recipient_email=payload.recipient_email,
            recipient_name=payload.recipient_name,
            custom_notes=None,
            channel="email",
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            requested_by=principal.subject,
        )

        target_org_id = payload.org_id or principal.org_id or lead.org_id
        if target_org_id:
            target_org = db.get(OrganizationRecord, target_org_id)
            if target_org:
                target_org.outreach_credits_used += 1
                db.commit()

        pkg_key = draft.get("package_key") or "company_os_starter"
        pkg = get_package(pkg_key) or CATALOG["company_os_starter"]

        return PitchLeadResponse(
            outreach_id=draft["outreach_id"],
            lead_id=draft["lead_id"],
            package_key=pkg.key,
            package_name=pkg.name,
            subject=draft["subject"],
            payment_link=draft.get("payment_link") or "",
            status=draft["status"],
            approval_id=draft.get("approval_id"),
            recipient_email=draft["recipient_email"],
        )
    except ValueError as exc:
        msg = str(exc)
        if "quota" in msg.lower() or "limit" in msg.lower():
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=msg) from exc
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=msg) from exc


@router.get("/funnel", status_code=status.HTTP_200_OK)
def get_revenue_funnel(
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve the unified 14-stage CEO commercial acquisition and revenue funnel (Finding 9)."""
    lead_q = db.query(LeadRecordRow)
    outreach_q = db.query(OutreachRecord)
    invoice_q = db.query(InvoiceRecord)
    sub_q = db.query(SubscriptionRecord)

    if principal.org_id:
        lead_q = lead_q.filter(LeadRecordRow.org_id == principal.org_id)
        outreach_q = outreach_q.filter(OutreachRecord.org_id == principal.org_id)
        invoice_q = invoice_q.filter(InvoiceRecord.org_id == principal.org_id)
        sub_q = sub_q.filter(SubscriptionRecord.org_id == principal.org_id)

    leads = lead_q.all()
    leads_discovered = len(leads)

    # Verified prospects: leads whose email is not a generic contact@domain fallback
    verified_prospects = sum(
        1
        for ld in leads
        if ld.public_contact_channel
        and ld.domain
        and ld.public_contact_channel.lower().strip() != f"contact@{ld.domain.lower().strip()}"
    )

    previews_all = db.query(PreviewRecord).all()
    previews_generated = len(previews_all)
    previews_viewed = sum(1 for p in previews_all if (p.views_count or 0) > 0)

    outreach_all = outreach_q.all()
    proposals_issued = len(outreach_all)
    outreach_delivered = sum(1 for o in outreach_all if o.status in ("DELIVERED", "SENT"))
    replies_received = sum(1 for o in outreach_all if o.status == "REPLIED")

    approvals_approved = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.action == "external_sales_outreach", ApprovalRequest.status == "APPROVED")
        .count()
    )

    qualified_opportunities = sum(1 for ld in leads if (ld.fit_score or 0.0) >= 0.75 and not ld.do_not_contact)

    checkouts_all = db.query(SovereignPaymentSessionRecord).all()
    checkout_initiated = len(checkouts_all)

    invoices_paid = [inv for inv in invoice_q.all() if inv.status == "paid"]
    payments_completed = len(invoices_paid)

    subs_all = sub_q.all()
    active_subscriptions = sum(1 for s in subs_all if s.status == "active")
    churned_subscriptions = sum(1 for s in subs_all if s.status == "cancelled")

    mrr_inr = 0
    for s in subs_all:
        if s.status == "active":
            pkg = get_package(s.plan_id)
            if pkg:
                mrr_inr += pkg.price_inr

    # Build persistent prospect-level stage tracking (linked by lead_id / domain)
    preview_by_lead = {p.lead_id: p for p in previews_all if p.lead_id}
    preview_by_domain = {p.domain: p for p in previews_all if p.domain}
    outreach_by_lead = {o.lead_id: o for o in outreach_all if o.lead_id}
    paid_emails = {
        (inv.metadata_json or {}).get("customer_email", "").lower()
        for inv in invoices_paid
        if isinstance(inv.metadata_json, dict)
    }

    prospect_journey = []
    for ld in leads[:25]:
        prv = preview_by_lead.get(ld.id) or preview_by_domain.get(ld.domain)
        out = outreach_by_lead.get(ld.id)
        is_paid = (ld.public_contact_channel or "").lower() in paid_emails

        if is_paid:
            stage = "PAID_CUSTOMER"
        elif out and out.status in ("DELIVERED", "SENT"):
            stage = "OUTREACH_DELIVERED"
        elif out:
            stage = "PROPOSAL_ISSUED"
        elif prv and (prv.views_count or 0) > 0:
            stage = "PREVIEW_VIEWED"
        elif prv:
            stage = "PREVIEW_GENERATED"
        else:
            stage = "DISCOVERED"

        prospect_journey.append({
            "lead_id": ld.id,
            "company": ld.company,
            "domain": ld.domain,
            "contact": ld.public_contact_channel,
            "stage": stage,
            "preview_views": prv.views_count if prv else 0,
            "outreach_status": out.status if out else None,
            "paid": is_paid,
        })

    return {
        "status": "OK",
        "kpis": {
            "leads_discovered": leads_discovered,
            "verified_prospects": verified_prospects,
            "qualified_opportunities": qualified_opportunities,
            "previews_generated": previews_generated,
            "preview_views": previews_viewed,
            "proposals_issued": proposals_issued,
            "outreach_approved": approvals_approved,
            "outreach_delivered": outreach_delivered,
            "replies_received": replies_received,
            "checkout_initiated": checkout_initiated,
            "payments_completed": payments_completed,
            "active_subscriptions": active_subscriptions,
            "mrr_inr": mrr_inr,
            "churn_count": churned_subscriptions,
        },
        "conversion_rates": {
            "verification_rate": round(verified_prospects / max(1, leads_discovered), 4),
            "preview_engagement_rate": round(previews_viewed / max(1, previews_generated), 4),
            "outreach_delivery_rate": round(outreach_delivered / max(1, proposals_issued), 4),
            "checkout_to_paid_rate": round(payments_completed / max(1, checkout_initiated), 4),
        },
        "prospect_funnel": prospect_journey,
    }
