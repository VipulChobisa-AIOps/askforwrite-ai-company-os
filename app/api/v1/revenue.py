"""Commercial Catalog and Revenue Growth API router.

Endpoints for:
- Catalog: Query modular tool subscriptions and full Company OS bundles with Razorpay & PayPal pricing
- Diagnostic: Diagnose prospect operational pain points from website signals and recommend packages
- Pitch Lead: End-to-end diagnosis and outreach draft creation with embedded one-click payment links
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.revenue_agent import (
    diagnose_lead_opportunity,
)
from app.db.database import get_db
from app.db.models import LeadRecordRow
from app.schemas.catalog import (
    CatalogListResponse,
    DiagnoseRequest,
    DiagnoseResponse,
    PackageResponse,
    PitchLeadRequest,
    PitchLeadResponse,
)
from app.security.auth import APIPrincipal, require_manager
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

    correlation_id = x_correlation_id or str(uuid.uuid4())

    try:
        draft = draft_outreach(
            db=db,
            lead_id=payload.lead_id,
            org_id=payload.org_id,
            recipient_email=payload.recipient_email,
            recipient_name=payload.recipient_name,
            custom_notes=None,
            channel="email",
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            requested_by=principal.subject,
        )

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
