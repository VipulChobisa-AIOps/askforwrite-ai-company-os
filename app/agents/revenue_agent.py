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
    "warehouse_automation": (
        "warehouse", "inventory", "stock", "stockout", "reorder", "eoq",
        "sku", "depreciation", "dead stock", "deadstock", "holding cost",
        "stocksense", "barcode", "storage layout", "stocktake", "3pl", "fulfillment",
    ),
    "mango_quality_analytics": (
        "mango", "produce", "fruit", "harvest", "ripeness", "agri", "agritech",
        "cold chain", "cold-chain", "packhouse", "grading", "brix", "sugar",
        "shelf life", "shelf-life", "colorimetry", "hsv", "glcm", "export rejection",
        "perishable", "horticulture", "sorting",
    ),
    "bike_rebalance_analytics": (
        "bike", "bicycle", "micro-mobility", "micromobility", "scooter",
        "dock", "docking", "station churn", "rebalance", "rebalancing",
        "fleet demand", "transit", "circadian", "commuter peak", "rush hour",
        "truck rebalance", "turnover ratio", "bike-share", "ebike",
    ),
}

# Alias for external agents and service introspection
SERVICE_KEYWORD_MAP = KEYWORDS_MAP

# Domain pain point diagnoses and ROI impact metrics
PAIN_POINT_DIAGNOSIS: dict[str, dict[str, object]] = {
    "mango_quality_analytics": {
        "pain_points": [
            "Subjective manual sorting causes 15-20% export container rejection at destination ports",
            "Lack of non-destructive Brix and firmness measurements leads to shelf-life uncertainty",
            "Cold chain breakdown risks and non-uniform ripening across distributed packhouses",
        ],
        "roi_formula": "Saves ₹3,50,000 - ₹8,00,000 per perishable export container via automated CV defect sorting",
        "roi_multiplier": 5.2,
    },
    "bike_rebalance_analytics": {
        "pain_points": [
            "Station starvation and dock overflow causing up to 28% commuter churn during peak rush hours",
            "Inefficient rebalancing truck dispatch routes increasing fuel costs and transit lag",
            "Unpredictable circadian tidal fleet demand across metro transit corridors",
        ],
        "roi_formula": "Increases daily ride turnover by 24% while reducing truck rebalancing fuel consumption by 35%",
        "roi_multiplier": 4.8,
    },
    "warehouse_automation": {
        "pain_points": [
            "Unscheduled stockouts of critical high-margin SKUs causing missed SLAs and penalties",
            "Capital tied up in dead stock (>90 days idle) increasing warehouse holding expenses",
            "Manual reorder calculations without dynamic lead-time safety stock buffers",
        ],
        "roi_formula": "Reduces carrying costs by 22% and eliminates 95% of preventable stockouts via dynamic EOQ",
        "roi_multiplier": 6.1,
    },
    "field_operations_automation": {
        "pain_points": [
            "Proxy attendance and mock-location GPS spoofing across distributed on-ground workforce",
            "Unverified client visits resulting in disputed conveyance mileage reimbursements",
            "Supervisor coordination lag delaying end-of-day CRM debrief logging",
        ],
        "roi_formula": "Saves 15+ supervisory hours weekly and cuts mileage fraud claims by 30%",
        "roi_multiplier": 4.5,
    },
    "seo_blog_copilot": {
        "pain_points": [
            "High agency retainers for slow, generic content creation without topical depth",
            "Lack of Generative Engine Optimization (GEO) structured for ChatGPT and Perplexity",
            "Manual formatting, JSON-LD schema creation, and multi-site CMS publishing",
        ],
        "roi_formula": "Replaces ₹50,000/mo freelance copywriter spend with automated topical authority articles",
        "roi_multiplier": 8.0,
    },
    "marketing_suite": {
        "pain_points": [
            "Fragmented ad copy production across Meta, Google, and LinkedIn",
            "Slow iteration on creative ad angles and audience hooks",
            "High agency commission fees with unpredictable conversion rates",
        ],
        "roi_formula": "Generates complete multi-channel campaign copy in seconds with 3x higher click-through",
        "roi_multiplier": 5.0,
    },
    "trust_engine": {
        "pain_points": [
            "Regulatory compliance audit friction for fintech, healthtech, and enterprise clients",
            "Tamperable centralized logs that fail third-party SOC 2 and ISO verification",
            "Disputed transactions and operational workflow non-repudiation vulnerabilities",
        ],
        "roi_formula": "Provides instant cryptographic Merkle proof, eliminating audit preparation fees",
        "roi_multiplier": 7.5,
    },
    "growth_all_in_one": {
        "pain_points": [
            "Solo founders juggling disparate graphic tools, SEO agencies, and WhatsApp chat support",
            "Leads going cold because replies take more than 5 minutes",
            "High customer acquisition cost with low website conversion",
        ],
        "roi_formula": "Provides an entire autonomous marketing & sales closer team for ₹9,999/mo",
        "roi_multiplier": 10.0,
    },
}


def calculate_estimated_roi(package_key: str, monthly_budget_inr: float = 50000.0) -> dict[str, object]:
    """Calculate projected cost savings and ROI multiplier for a given package."""
    diag = PAIN_POINT_DIAGNOSIS.get(package_key, PAIN_POINT_DIAGNOSIS["growth_all_in_one"])
    multiplier = float(diag.get("roi_multiplier", 4.0))
    projected_value = monthly_budget_inr * multiplier
    net_savings = projected_value - monthly_budget_inr
    return {
        "package_key": package_key,
        "monthly_budget_inr": monthly_budget_inr,
        "projected_value_inr": projected_value,
        "net_monthly_savings_inr": net_savings,
        "roi_multiplier": f"{multiplier}x",
        "roi_summary": str(diag.get("roi_formula", "")),
        "key_pain_points": list(diag.get("pain_points", [])),
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
        "warehouse_automation": "warehouse_automation",
        "mango_quality_analytics": "mango_quality_analytics",
        "bike_rebalance_analytics": "bike_rebalance_analytics",
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
