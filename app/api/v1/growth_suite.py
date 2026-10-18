"""Autonomous AI Growth & Inbound Sales Suite API Router.

Exposes endpoints for:
- Pixel AI Visual & Creative Studio asset generation
- Unified Multi-Pillar Growth Campaign (Creatives + SEO Blog + Omnichannel Social)
- 24/7 Autonomous Inbound Sales Closer (WhatsApp & Web Chat webhook/chat interface)
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.smb_search_source import audit_live_website_seo_geo
from app.db.database import get_db
from app.security.auth import APIPrincipal, require_manager
from app.services.catalog import CATALOG, build_payment_link, get_package
from app.services.growth_engine import (
    execute_unified_growth_run,
    generate_and_stage_blog,
    generate_creative_assets,
    generate_omnichannel_social_campaign,
    handle_inbound_sales_chat,
)

router = APIRouter(prefix="/v1/growth", tags=["Autonomous Growth & Sales Suite"])


class CreativeRequest(BaseModel):
    product_name: str = Field(min_length=1, max_length=200, description="Product or service name")
    target_audience: str = Field(min_length=1, max_length=300, description="Target customer persona")
    brand_voice: str = Field(default="modern, bold, premium", max_length=100)
    aspect_ratios: list[str] = Field(default_factory=lambda: ["1:1", "9:16", "16:9"])
    visual_style: str = Field(
        default="photorealistic studio lighting with minimalist glassmorphism accents",
        max_length=200,
    )


class UnifiedGrowthCampaignRequest(BaseModel):
    client_name: str = Field(min_length=1, max_length=200)
    product_or_service: str = Field(min_length=1, max_length=200)
    target_audience: str = Field(min_length=1, max_length=300)
    keywords: list[str] = Field(default_factory=lambda: ["AI Growth Engine", "Marketing Automation"])
    idempotency_key: str = Field(min_length=1, max_length=200)


class InboundCloserChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prospect_name: str = Field(min_length=1, max_length=150)
    prospect_contact: str = Field(min_length=3, max_length=150, description="Email or WhatsApp phone number")
    message: str = Field(min_length=1, max_length=2000, description="Inbound customer message")
    history: list[dict[str, str]] = Field(default_factory=list)
    currency: str = Field(default="INR", pattern="^(INR|USD)$")
    channel: str = Field(default="whatsapp", max_length=50)


class DomainAuditRequest(BaseModel):
    website_url: str = Field(min_length=3, max_length=500, description="Website URL or domain name to audit")
    company_name: str | None = Field(default=None, max_length=200, description="Optional company or brand name")
    target_audience: str | None = Field(default=None, max_length=300, description="Optional target customer persona")
    keywords: list[str] | None = Field(default=None, description="Optional target SEO / GEO keywords")
    target_keywords: list[str] | None = Field(default=None, description="Optional target SEO / GEO keywords")


@router.get("/status")
def get_growth_suite_status() -> dict[str, Any]:
    """Retrieve capabilities and live operational state of the Autonomous Growth Suite."""
    pkg = get_package("growth_all_in_one")
    return {
        "status": "OPERATIONAL",
        "package_key": "growth_all_in_one",
        "package_name": pkg.name if pkg else "AskforWrite Autonomous AI Growth & Inbound Sales Suite",
        "price_inr": pkg.price_inr if pkg else 9999,
        "price_usd": pkg.price_usd if pkg else 129,
        "pillars": {
            "creative_studio": "Pixel AI Multi-Aspect Asset Generator (afwpixelai)",
            "seo_blog_copilot": "4-Site WordPress Publishing with Schema.org JSON-LD",
            "omnichannel_marketing": "Meta, Google, and LinkedIn Ad Copy Engine",
            "inbound_sales_closer": "24/7 Autonomous WhatsApp & Web Chat Closer with Instant Checkout",
        },
        "closer_active": True,
    }


@router.post("/creative")
def generate_creative_endpoint(
    payload: CreativeRequest,
    principal: APIPrincipal = Depends(require_manager),
) -> dict[str, Any]:
    """Generate multi-format visual creative specs for the Pixel AI engine."""
    return generate_creative_assets(
        product_name=payload.product_name,
        target_audience=payload.target_audience,
        brand_voice=payload.brand_voice,
        aspect_ratios=payload.aspect_ratios,
        visual_style=payload.visual_style,
    )


@router.post("/campaign/unified")
def generate_unified_campaign_endpoint(
    payload: UnifiedGrowthCampaignRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Execute unified Growth Suite generation: Creative Visuals + SEO Blog + Omnichannel Ads + Closer setup."""
    correlation_id = x_correlation_id or str(uuid.uuid4())
    try:
        return execute_unified_growth_run(
            db=db,
            client_name=payload.client_name,
            product_or_service=payload.product_or_service,
            target_audience=payload.target_audience,
            keywords=payload.keywords,
            correlation_id=correlation_id,
            agent_id=principal.subject,
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(err)) from err


@router.post("/sales-closer/chat")
@router.post("/inbound-closer/chat")
def inbound_closer_chat_endpoint(
    payload: InboundCloserChatRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """24/7 Conversational AI Inbound Sales Closer.

    Receives prospect inquiries (from WhatsApp webhook or Web Chat), diagnoses customer needs,
    handles objections, and delivers instant Razorpay/PayPal checkout links.
    """
    return handle_inbound_sales_chat(
        db=db,
        session_id=payload.session_id,
        prospect_name=payload.prospect_name,
        prospect_contact=payload.prospect_contact,
        message=payload.message,
        history=payload.history,
        currency=payload.currency,
        channel=payload.channel,
    )


@router.post("/audit-domain")
def audit_domain_endpoint(
    payload: DomainAuditRequest,
) -> dict[str, Any]:
    """Inspect live website SEO/GEO gaps & deliver tailored 2026 growth prescription with instant checkout."""
    raw_url = payload.website_url.strip()
    if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
        audit_url = f"https://{raw_url}"
    else:
        audit_url = raw_url

    clean_domain = re.sub(r"^https?://", "", audit_url).split("/")[0].lower()
    clean_domain = re.sub(r"^www\.", "", clean_domain)
    comp_name = payload.company_name or clean_domain.split(".")[0].capitalize()
    audience = payload.target_audience or f"Customers and partners of {comp_name}"
    kws = payload.target_keywords or payload.keywords or [f"{comp_name} services", "commercial growth automation"]

    audit_result = audit_live_website_seo_geo(website_url=audit_url)

    blog_prescription = generate_and_stage_blog(
        product_name=comp_name,
        target_audience=audience,
        keywords=kws,
        target_domain=f"https://{clean_domain}/blog",
    )

    social_prescription = generate_omnichannel_social_campaign(
        product_name=comp_name,
        target_audience=audience,
        keywords=kws,
    )

    pkg = get_package("growth_all_in_one") or CATALOG.get("growth_all_in_one")
    checkout_inr = build_payment_link(package_key="growth_all_in_one", company=comp_name, provider="razorpay")
    checkout_usd = build_payment_link(package_key="growth_all_in_one", company=comp_name, provider="paypal")
    checkout_directpay = build_payment_link(package_key="growth_all_in_one", company=comp_name, provider="afw_directpay")

    return {
        "status": "COMPLETED",
        "website_url": audit_url,
        "domain": clean_domain,
        "company_name": comp_name,
        "seo_geo_audit": audit_result,
        "package": {
            "key": "growth_all_in_one",
            "name": pkg.name if pkg else "AskforWrite Autonomous AI Growth Suite",
            "price_inr": pkg.price_inr if pkg else 9999,
            "price_usd": pkg.price_usd if pkg else 129,
        },
        "checkout_links": {
            "razorpay_inr": checkout_inr,
            "paypal_usd": checkout_usd,
            "afw_directpay": checkout_directpay,
        },
        "growth_prescription": {
            "gap_score": audit_result.get("seo_geo_gap_score", 0),
            "seo_geo_blog": blog_prescription,
            "omnichannel_social": social_prescription,
            "recommended_actions": [
                "Deploy Schema.org @graph entity payload to index in Google AI Overviews",
                "Host /llms.txt manifest for SearchGPT and Perplexity citation ingestion",
                "Activate 24/7 WhatsApp Closer to respond to prospects within 3 seconds",
                "Run 30s viral Instagram Reels & 5-slide LinkedIn carousel campaigns",
            ],
        },
    }
