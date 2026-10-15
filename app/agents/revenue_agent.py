"""Company OS Revenue & Commercial Growth Agent.

Specialist agent that analyzes prospect companies, diagnoses operational pain points,
matches them to either a Modular Tool or Master Company OS bundle, and generates
personalized sales proposals with embedded Razorpay (INR) or PayPal (USD) payment links.

Includes:
- Deep SEO, GEO (Generative Engine Optimization), and AIO (AI Optimization) alignment
- Automatic target buyer persona identification
- Concrete operational deliverables and multi-tier subscription choices
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from app.services.catalog import (
    CATALOG,
    build_payment_link,
    get_package,
)

logger = logging.getLogger(__name__)


# Signal keywords for deterministic diagnosis matching
KEYWORDS_MAP: dict[str, tuple[str, ...]] = {
    "seo_blog_copilot": (
        "seo", "blog", "content", "wordpress", "publishing", "ranking",
        "organic traffic", "writer", "article", "geo", "aio", "generative engine",
        "chatgpt", "perplexity", "meta description", "schema", "json-ld",
        "topical authority", "search engine",
    ),
    "marketing_suite": (
        "marketing", "ads", "advertising", "campaign", "social media",
        "copywriting", "creative", "lead gen", "facebook ads", "google ads",
        "pixelbot", "omnichannel", "ad copy", "agency retainer",
    ),
    "field_operations_automation": (
        "field", "attendance", "supervisor", "gps", "tracking", "geofence",
        "workforce", "sales rep", "dispatch", "store manager", "fleet",
        "route optimization", "logistics", "delivery", "drivers", "proxy attendance", "conveyance",
    ),
    "trust_engine": (
        "compliance", "audit", "security", "blockchain", "merkle",
        "cryptographic", "tamper", "verification", "soc2", "hipaa",
        "ecdsa", "fintech", "regulated", "non-repudiation",
    ),
    "growth_all_in_one": (
        "pixel ai", "image modification", "photos", "videos", "reels",
        "instagram", "creatives", "creative studio", "all-in-one", "all in one",
        "solo founder", "growth suite", "closer", "sales closer", "whatsapp sales",
        "inbound sales", "inbound closer", "marketing agency", "agency replacement",
        "full funnel", "growth engine",
    ),
}


def diagnose_lead_opportunity(
    company: str,
    website: str,
    signals: list[str],
    geography: str = "India",
    industry: str = "Technology & Services",
) -> dict[str, object]:
    """Diagnose the prospect's operational bottleneck, identify buyer persona, and select commercial package."""
    text_corpus = (" ".join(signals) + " " + industry + " " + company).lower()

    # Determine optimal payment provider based on geography (use word boundary to avoid substring collisions)
    is_india = bool(
        re.search(
            r"\b(india|in|ind|delhi|bangalore|bengaluru|mumbai|hyderabad|pune|chennai|kolkata|noida|gurgaon|gurugram|gujarat|rajasthan|karnataka|maharashtra)\b",
            geography,
            re.IGNORECASE,
        )
    )
    provider: Literal["razorpay", "paypal"] = "razorpay" if is_india else "paypal"

    # Score each modular tool against observed signals
    best_modular_key: str | None = None
    best_modular_score = 0

    # Map scoring keys back to catalog keys
    _SCORING_TO_CATALOG: dict[str, str] = {
        "seo_blog_copilot": "seo_blog_copilot",
        "marketing_suite": "marketing_suite",
        "field_operations_automation": "field_force",
        "trust_engine": "trust_engine",
        "growth_all_in_one": "growth_all_in_one",
    }

    for pkg_key, keywords in KEYWORDS_MAP.items():
        score = sum(1 for kw in keywords if kw in text_corpus)
        if score > best_modular_score:
            best_modular_score = score
            best_modular_key = _SCORING_TO_CATALOG.get(pkg_key, pkg_key)

    # Decision logic:
    if best_modular_score >= 2 and best_modular_key:
        package = CATALOG[best_modular_key]
        reasoning = (
            f"Prospect matches target persona '{package.target_buyer_persona}' "
            f"with specific operational friction aligned with {package.name} (signal match score: {best_modular_score})."
        )
    elif best_modular_score == 1 and best_modular_key:
        package = CATALOG[best_modular_key]
        reasoning = (
            f"Initial entry offer via {package.name} for '{package.target_buyer_persona}' "
            f"to solve immediate friction before expanding to Full OS."
        )
    else:
        # Default to Full Company OS Starter bundle for holistic transformation
        package = CATALOG["company_os_starter"]
        reasoning = (
            "General operational transformation candidate suited for the complete multi-agent Company OS platform."
        )

    # Build the live checkout link
    payment_link = build_payment_link(
        package_key=package.key,
        company=company,
        provider=provider,
    )

    price = package.price_inr if provider == "razorpay" else package.price_usd
    currency = "INR" if provider == "razorpay" else "USD"

    return {
        "company": company,
        "website": website,
        "target_buyer_persona": package.target_buyer_persona,
        "identified_pain_point": package.target_pain_point,
        "recommended_package_key": package.key,
        "package_name": package.name,
        "category": package.category,
        "reasoning": reasoning,
        "currency": currency,
        "price": price,
        "payment_link": payment_link,
        "provider": provider,
        "key_features": list(package.key_features),
        "deliverables": list(package.deliverables),
        "seo_geo_aio_capabilities": list(package.seo_geo_aio_capabilities),
    }


def generate_commercial_pitch(
    company: str,
    website: str,
    industry: str,
    signals: list[str],
    geography: str = "India",
    recipient_name: str | None = None,
    package_key_override: str | None = None,
    provider_override: str | None = None,
    custom_notes: str | None = None,
) -> dict[str, object]:
    """Generate high-converting sales proposal with concrete deliverables and embedded payment links."""
    diagnosis = diagnose_lead_opportunity(
        company=company,
        website=website,
        signals=signals,
        geography=geography,
        industry=industry,
    )

    package_key = package_key_override or str(diagnosis["recommended_package_key"])
    package = get_package(package_key) or CATALOG["company_os_starter"]

    provider = (provider_override or str(diagnosis["provider"])).lower()
    payment_link = build_payment_link(
        package_key=package.key,
        company=company,
        provider=provider,
    )

    price_str = f"₹{package.price_inr:,}/month" if provider == "razorpay" else f"${package.price_usd}/month"
    payment_name = "Razorpay (Cards, UPI, Netbanking)" if provider == "razorpay" else "PayPal"

    greeting = f"Hi {recipient_name.strip()}," if recipient_name and recipient_name.strip() else f"Hello {company.strip()} Team,"

    # Deliverables and SEO/GEO/AIO bullets
    deliverable_bullets = "\n".join(f"  ✓ {d}" for d in package.deliverables[:3])
    seo_bullets = "\n".join(f"  • {s}" for s in package.seo_geo_aio_capabilities[:2])

    if package.category == "modular_tool":
        pitch_core = (
            f"We noticed recent operational developments at {company} and identified an opportunity to streamline your "
            f"workflows with {package.name}.\n\n"
            f"Target Problem Solved:\n"
            f"{package.target_pain_point}\n\n"
            f"Key Deliverables Included:\n"
            f"{deliverable_bullets}\n\n"
            f"SEO, GEO & AI Visibility Advantage:\n"
            f"{seo_bullets}\n\n"
            f"Autonomous AI execution is fully gated by Owner governance (HITL) for 100% control."
        )
    else:
        pitch_core = (
            f"We noticed your business growth at {company} and would like to introduce the AskforWrite AI Company OS—"
            f"an autonomous operating system unifying CEO planning, Lead Discovery, Content Publishing, and Operations.\n\n"
            f"Target Problem Solved:\n"
            f"{package.target_pain_point}\n\n"
            f"Key Deliverables Included:\n"
            f"{deliverable_bullets}\n\n"
            f"SEO, GEO & AI Optimization Features:\n"
            f"{seo_bullets}\n\n"
            f"Verifiable cryptographic audit chain ensures immutable accountability across every agent action."
        )

    notes_addition = f"\n\nContext: {custom_notes.strip()}" if custom_notes and custom_notes.strip() else ""

    subject = f"Automating operations for {company} — {package.name}"
    body = (
        f"{greeting}\n\n"
        f"{pitch_core}"
        f"{notes_addition}\n\n"
        f"Pricing & Immediate Activation:\n"
        f"You can activate your {package.name} subscription today at {price_str}.\n"
        f"Instant Checkout Link ({payment_name}):\n"
        f"{payment_link}\n\n"
        f"Once payment is received, your dedicated tenant account, admin login, and API access credentials are auto-provisioned immediately.\n\n"
        f"Warm regards,\n"
        f"Vipul Chobisa\n"
        f"AskforWrite AI Solutions"
    )

    return {
        "subject": subject,
        "body_text": body,
        "package_key": package.key,
        "package_name": package.name,
        "payment_link": payment_link,
        "price_str": price_str,
        "provider": provider,
        "target_buyer_persona": package.target_buyer_persona,
        "deliverables": list(package.deliverables),
        "diagnosis": diagnosis,
    }
