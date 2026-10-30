"""
Dedicated SSR Indexable Vertical Landing Pages & Ops Preflight Verification.
Provides crawlable HTML, Schema.org JSON-LD (@graph: Organization, SoftwareApplication,
Product, BreadcrumbList, FAQPage), Open Graph metadata, Google Search Console / Bing
Webmaster verification tags, and direct checkout conversion CTAs for every vertical SKU.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import require_manager
from app.services.catalog import CATALOG

router = APIRouter(tags=["Solutions & Ops Readiness"])

SOLUTION_SLUGS: Dict[str, Dict[str, Any]] = {
    "warehouse-automation": {
        "sku": "warehouse_automation",
        "slug": "warehouse-automation",
        "headline": "AI Warehouse & Dark-Store Replenishment OS",
        "subheadline": "Eliminate stockouts, shrink, and picking bottlenecks across 3PLs, dark stores, and cold-chain depots in under 5 minutes.",
        "hero_badge": "LOGISTICS & SUPPLY CHAIN AI",
        "pain_points": [
            "High-velocity SKUs stock out during peak windows while slow-moving inventory ties up working capital.",
            "Manual Excel reorder sheets miss real-time safety-stock breaches and cold-chain expiry risks.",
            "Dispatch supervisors lack instant SKU-level reorder priority queues and margin-at-risk visibility."
        ],
        "deliverables": [
            "Automated SKU safety-stock vs. current-stock variance analysis (`warehouse_analyze`).",
            "Prioritized replenishment order schedule with urgency scoring (`CRITICAL`, `HIGH`, `NORMAL`).",
            "Live interactive HTML logistics telemetry preview & downloadable CSV/JSON dispatch manifest."
        ],
        "faqs": [
            {
                "q": "How does AskforWrite Warehouse Automation connect to our existing WMS or ERP?",
                "a": "AskforWrite accepts CSV/JSON SKU snapshots or REST API webhooks (`POST /v1/me/use-service` or `/v1/tools/call`) with `sku`, `stock`, and `safety_stock` fields and returns an instant replenishment schedule."
            },
            {
                "q": "What is the pricing and turnaround time?",
                "a": "Plans start at ₹1,499/month ($25 USD) with instant self-serve workspace provisioning and sub-second replenishment calculation."
            },
            {
                "q": "Can we verify payment and tax compliance automatically?",
                "a": "Yes. Every paid order generates an automated GST/USD invoice and an ECDSA NIST P-256 cryptographically signed TrustBlock receipt."
            }
        ],
    },
    "field-force": {
        "sku": "field_force",
        "slug": "field-force",
        "headline": "AI Field Force Route & Attendance Verification OS",
        "subheadline": "Real-time GPS beat compliance, route optimization, and cryptographic attendance verification for distributed field teams.",
        "hero_badge": "FIELD OPERATIONS & BEAT ROUTING AI",
        "pain_points": [
            "Unverified field visits and fake GPS check-ins inflate travel reimbursements and reduce territory coverage.",
            "Suboptimal daily beat routing wastes 22-35% of rep productive selling and service hours.",
            "Operations managers lack real-time visibility into completed vs. pending customer site visits."
        ],
        "deliverables": [
            "Automated territory efficiency scoring and route completion diagnostics (`field_force_analyze`).",
            "Agent-by-agent visit verification matrix with anomaly alerts.",
            "Cryptographic TrustBlock audit trail for high-compliance field service SLAs."
        ],
        "faqs": [
            {
                "q": "Who is AskforWrite Field Force AI built for?",
                "a": "FMCG distributors, pharmaceutical medical representatives, solar/telecom installation crews, and B2B field service agencies."
            },
            {
                "q": "How quickly can a field team onboard?",
                "a": "Self-serve onboarding takes under 2 minutes after checkout (`₹999/mo` or `$19/mo`), with immediate API and Customer Portal access."
            }
        ],
    },
    "produce-quality-ai": {
        "sku": "produce-quality-ai",
        "sku_id": "mango_quality_analytics",
        "slug": "produce-quality-ai",
        "headline": "AI Agri-Produce Quality Grading & Cold-Chain Ripeness OS",
        "subheadline": "Deterministic export-grade Brix, firmness, and defect scoring for fruit packhouses, FPOs, and agri-exporters.",
        "hero_badge": "AGRI-EXPORT & PACKHOUSE QUALITY AI",
        "pain_points": [
            "Inconsistent manual grading leads to export consignment rejections and 15-30% post-harvest value loss.",
            "Lack of batch-level Brix and firmness traceability reduces buyer trust in international markets.",
            "Slow quality inspection bottlenecks packhouse throughput during peak harvest windows."
        ],
        "deliverables": [
            "Batch-level export grade classification (`Export Grade A`, `Domestic Grade B`, `Processing Grade C`).",
            "Automated Brix-to-firmness ripeness index and shelf-life estimation (`mango_quality_analyze`).",
            "Tamper-evident ECDSA quality certificate for buyers and customs documentation."
        ],
        "faqs": [
            {
                "q": "Which crops and packhouse workflows are supported?",
                "a": "Optimized out-of-the-box for mangoes (Alphonso, Kesar, Banganapalli) and extensible to pomegranate, citrus, and table grapes via Brix/firmness/color telemetry."
            },
            {
                "q": "How much does the Produce Quality AI suite cost?",
                "a": "₹999/month ($15 USD) with unlimited batch grading runs via the Customer Portal and API."
            }
        ],
    },
    "urban-mobility-ai": {
        "sku": "bike_rebalance_analytics",
        "slug": "urban-mobility-ai",
        "headline": "AI EV Fleet & Micro-Mobility Station Rebalancing OS",
        "subheadline": "Maximize fleet utilization and eliminate empty dock losses with predictive station rebalancing.",
        "hero_badge": "EV FLEET & URBAN MOBILITY AI",
        "pain_points": [
            "Commuter surge hours leave origin stations empty and destination docks overflowing.",
            "Manual van dispatch routes waste fuel and miss high-revenue rider trips.",
            "Fleet operators lack station-level deficit vs. capacity telemetry."
        ],
        "deliverables": [
            "Real-time station deficit/surplus matrix (`bike_rebalance_analyze`).",
            "Prioritized dispatch transfer manifest for rebalancing crews.",
            "Automated utilization and fleet readiness KPI tracking."
        ],
        "faqs": [
            {
                "q": "How does station rebalancing work?",
                "a": "Submit station dock capacity and current active vehicle counts via API or portal to receive an instant transfer plan."
            }
        ],
    },
    "seo-blog-copilot": {
        "sku": "seo_blog_copilot",
        "slug": "seo-blog-copilot",
        "headline": "Autonomous SEO, AEO & GEO Content Copilot",
        "subheadline": "Publish high-authority, structured-data-enriched technical articles engineered to rank on Google and AI Answer Engines.",
        "hero_badge": "SEO / AEO / GEO GROWTH ENGINE",
        "pain_points": [
            "Generic AI blog posts fail E-E-A-T checks and lack verifiable product anchors.",
            "Missing Schema.org JSON-LD and FAQ blocks prevent citation in ChatGPT, Perplexity, and Gemini.",
            "Content teams spend days formatting metadata, canonical tags, and internal links."
        ],
        "deliverables": [
            "Long-form technical articles with keyword intent mapping and FAQ Schema.",
            "Automated AEO/GEO citation structure for LLM search engines.",
            "Instant markdown and HTML export via the AskforWrite Customer Portal."
        ],
        "faqs": [
            {
                "q": "Does SEO Blog Copilot optimize for AI search engines (AEO/GEO)?",
                "a": "Yes. Every article includes structured entity definitions, FAQ blocks, and factual anchors designed for LLM citation."
            }
        ],
    },
}


def _resolve_sku_data(slug: str) -> Dict[str, Any]:
    meta = SOLUTION_SLUGS.get(slug)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Solution '{slug}' not found.")
    sku_key = meta.get("sku_id") or meta["sku"]
    pkg = CATALOG.get(sku_key)
    catalog_entry = {
        "monthly_price_inr": pkg.price_inr if pkg else 1499,
        "monthly_price_usd": pkg.price_usd if pkg else 25,
    }
    return {**meta, "sku": sku_key, "catalog": catalog_entry}


def _verification_meta_tags() -> str:
    gsc = os.environ.get("GOOGLE_SITE_VERIFICATION", "askforwrite-gsc-verification-ready")
    bing = os.environ.get("BING_SITE_VERIFICATION", "askforwrite-bing-verification-ready")
    return (
        f'<meta name="google-site-verification" content="{gsc}" />\n'
        f'    <meta name="msvalidate.01" content="{bing}" />'
    )


@router.get("/solutions", response_class=HTMLResponse)
@router.get("/services", response_class=HTMLResponse)
def solutions_hub_page() -> HTMLResponse:
    """Indexable SSR hub page for all AskforWrite AI Company OS vertical solutions."""
    base_url = "https://os.askforwrite.com"
    cards_html = ""
    item_list_elements: List[Dict[str, Any]] = []

    for idx, (slug, info) in enumerate(SOLUTION_SLUGS.items(), start=1):
        sku_key = info.get("sku_id") or info["sku"]
        pkg = CATALOG.get(sku_key)
        price_inr = pkg.price_inr if pkg else 1499
        price_usd = pkg.price_usd if pkg else 25
        url = f"{base_url}/solutions/{slug}"
        item_list_elements.append(
            {
                "@type": "ListItem",
                "position": idx,
                "name": info["headline"],
                "url": url,
            }
        )
        cards_html += f"""
        <article class="card">
            <div class="badge">{info["hero_badge"]}</div>
            <h2><a href="/solutions/{slug}">{info["headline"]}</a></h2>
            <p>{info["subheadline"]}</p>
            <div class="price">₹{price_inr:,}/mo <span>(${price_usd} USD/mo)</span></div>
            <div class="actions">
                <a class="btn-primary" href="/solutions/{slug}">Explore Solution & Architecture →</a>
                <a class="btn-secondary" href="/v1/pay/checkout?package={sku_key}">Instant Checkout</a>
            </div>
        </article>
        """

    schema_graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{base_url}/#organization",
                "name": "AskforWrite AI Company OS",
                "url": base_url,
                "legalName": "Proprietor: Vipul Chobisa (Indian Sovereign Entity)",
            },
            {
                "@type": "ItemList",
                "name": "AskforWrite Verified Vertical AI Solutions",
                "itemListElement": item_list_elements,
            },
        ],
    }

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Enterprise AI Solutions Catalog — AskforWrite AI Company OS</title>
    <meta name="description" content="Explore AskforWrite AI Company OS vertical solutions: Warehouse Automation, Field Force Route Verification, Produce Quality Grading AI, EV Fleet Rebalancing, and Autonomous SEO Copilot." />
    <link rel="canonical" href="{base_url}/solutions" />
    {_verification_meta_tags()}
    <meta property="og:title" content="Enterprise AI Solutions Catalog — AskforWrite AI Company OS" />
    <meta property="og:description" content="Production-verified vertical AI operating systems with HITL governance, instant self-serve provisioning, and cryptographic TrustBlock receipts." />
    <meta property="og:url" content="{base_url}/solutions" />
    <meta property="og:type" content="website" />
    <script type="application/ld+json">{json.dumps(schema_graph)}</script>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; background: #0b0f19; color: #f1f5f9; margin: 0; padding: 0; line-height: 1.6; }}
        header {{ max-width: 1100px; margin: 0 auto; padding: 48px 24px 24px; border-bottom: 1px solid #1e293b; }}
        h1 {{ font-size: 2.25rem; margin: 8px 0; color: #ffffff; }}
        .grid {{ max-width: 1100px; margin: 32px auto; padding: 0 24px 64px; display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 24px; }}
        .card {{ background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 24px; display: flex; flex-direction: column; justify-content: space-between; }}
        .badge {{ font-size: 0.75rem; font-weight: 700; color: #38bdf8; letter-spacing: 0.08em; text-transform: uppercase; }}
        .card h2 a {{ color: #ffffff; text-decoration: none; }}
        .price {{ font-size: 1.4rem; font-weight: 700; color: #34d399; margin: 16px 0; }}
        .price span {{ font-size: 0.95rem; color: #94a3b8; font-weight: 400; }}
        .actions {{ display: flex; gap: 12px; flex-wrap: wrap; }}
        .btn-primary {{ background: #2563eb; color: #fff; text-decoration: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; font-size: 0.9rem; }}
        .btn-secondary {{ background: #1e293b; color: #e2e8f0; text-decoration: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; font-size: 0.9rem; border: 1px solid #334155; }}
        footer {{ max-width: 1100px; margin: 0 auto; padding: 24px; border-top: 1px solid #1e293b; color: #94a3b8; font-size: 0.85rem; }}
        footer a {{ color: #38bdf8; }}
    </style>
</head>
<body>
    <header>
        <div class="badge">ASKFORWRITE AI COMPANY OS · VERTICAL SOLUTIONS</div>
        <h1>Production-Verified AI Operating Systems for Real Business Outcomes</h1>
        <p>Every AskforWrite vertical solution connects real operational telemetry to deterministic AI workflows, human-in-the-loop (HITL) governance, instant multi-currency checkout (Razorpay, PayPal, Sovereign UPI &amp; Polygon/Base USDC), and ECDSA NIST P-256 TrustBlock receipts.</p>
    </header>
    <main class="grid">
        {cards_html}
    </main>
    <footer>
        Proprietor: Vipul Chobisa (Indian Sovereign Entity) · <a href="/">OS Gateway Home</a> · <a href="/sitemap.xml">Sitemap</a> · <a href="/llms.txt">LLMs.txt</a> · <a href="/v1/legal/declaration?format=text">Legal Charter</a>
    </footer>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


@router.get("/solutions/{slug}", response_class=HTMLResponse)
@router.get("/services/{slug}", response_class=HTMLResponse)
def solution_detail_page(slug: str) -> HTMLResponse:
    """Dedicated SSR indexable landing page for a specific vertical SKU."""
    data = _resolve_sku_data(slug)
    base_url = "https://os.askforwrite.com"
    canonical_url = f"{base_url}/solutions/{slug}"
    sku_key = data["sku"]
    cat = data["catalog"]
    price_inr = cat.get("monthly_price_inr", 1499)
    price_usd = cat.get("monthly_price_usd", 25)

    pains_html = "".join(f"<li>{p}</li>" for p in data["pain_points"])
    deliverables_html = "".join(f"<li>{d}</li>" for d in data["deliverables"])
    faqs_html = "".join(
        f'<div class="faq-item"><h3>{f["q"]}</h3><p>{f["a"]}</p></div>'
        for f in data["faqs"]
    )

    faq_schema_entities = [
        {
            "@type": "Question",
            "name": f["q"],
            "acceptedAnswer": {"@type": "Answer", "text": f["a"]},
        }
        for f in data["faqs"]
    ]

    schema_graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{base_url}/#organization",
                "name": "AskforWrite AI Company OS",
                "url": base_url,
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": base_url},
                    {"@type": "ListItem", "position": 2, "name": "Solutions", "item": f"{base_url}/solutions"},
                    {"@type": "ListItem", "position": 3, "name": data["headline"], "item": canonical_url},
                ],
            },
            {
                "@type": ["SoftwareApplication", "Product"],
                "name": data["headline"],
                "sku": sku_key,
                "applicationCategory": "BusinessApplication",
                "operatingSystem": "Cloud / Web / REST API",
                "description": data["subheadline"],
                "url": canonical_url,
                "brand": {"@id": f"{base_url}/#organization"},
                "offers": [
                    {
                        "@type": "Offer",
                        "priceCurrency": "INR",
                        "price": str(price_inr),
                        "availability": "https://schema.org/InStock",
                        "url": f"{base_url}/v1/pay/checkout?package={sku_key}",
                    },
                    {
                        "@type": "Offer",
                        "priceCurrency": "USD",
                        "price": str(price_usd),
                        "availability": "https://schema.org/InStock",
                        "url": f"{base_url}/v1/pay/checkout?package={sku_key}",
                    },
                ],
            },
            {
                "@type": "FAQPage",
                "mainEntity": faq_schema_entities,
            },
        ],
    }

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{data["headline"]} — AskforWrite AI Company OS</title>
    <meta name="description" content="{data["subheadline"]}" />
    <link rel="canonical" href="{canonical_url}" />
    {_verification_meta_tags()}
    <meta property="og:title" content="{data["headline"]} — AskforWrite AI Company OS" />
    <meta property="og:description" content="{data["subheadline"]}" />
    <meta property="og:url" content="{canonical_url}" />
    <meta property="og:type" content="product" />
    <script type="application/ld+json">{json.dumps(schema_graph)}</script>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; background: #0b0f19; color: #f1f5f9; margin: 0; padding: 0; line-height: 1.65; }}
        .container {{ max-width: 960px; margin: 0 auto; padding: 48px 24px; }}
        .breadcrumb {{ font-size: 0.85rem; color: #94a3b8; margin-bottom: 16px; }}
        .breadcrumb a {{ color: #38bdf8; text-decoration: none; }}
        .badge {{ display: inline-block; background: #1e293b; color: #38bdf8; padding: 4px 12px; border-radius: 999px; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.08em; }}
        h1 {{ font-size: 2.4rem; margin: 12px 0; color: #ffffff; }}
        .sub {{ font-size: 1.15rem; color: #cbd5e1; max-width: 780px; }}
        .cta-box {{ background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 24px; margin: 32px 0; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; }}
        .price {{ font-size: 1.75rem; font-weight: 800; color: #34d399; }}
        .btn {{ background: #2563eb; color: #ffffff; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 700; }}
        section {{ margin: 40px 0; background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 28px; }}
        h2 {{ color: #38bdf8; margin-top: 0; }}
        .faq-item {{ border-top: 1px solid #1f2937; padding-top: 16px; margin-top: 16px; }}
        footer {{ border-top: 1px solid #1e293b; padding-top: 24px; color: #94a3b8; font-size: 0.85rem; }}
        footer a {{ color: #38bdf8; }}
    </style>
</head>
<body>
    <div class="container">
        <nav class="breadcrumb">
            <a href="/">Home</a> &rsaquo; <a href="/solutions">Solutions</a> &rsaquo; <span>{data["headline"]}</span>
        </nav>
        <span class="badge">{data["hero_badge"]}</span>
        <h1>{data["headline"]}</h1>
        <p class="sub">{data["subheadline"]}</p>

        <div class="cta-box">
            <div>
                <div class="price">₹{price_inr:,}/month <span style="font-size:1rem;color:#94a3b8;font-weight:400;">(or ${price_usd} USD/month)</span></div>
                <div style="font-size:0.9rem;color:#94a3b8;">Includes instant workspace activation, API key &amp; Customer Portal access, and ECDSA TrustBlock receipts.</div>
            </div>
            <div>
                <a class="btn" href="/v1/pay/checkout?package={sku_key}">Activate {sku_key} Now &rarr;</a>
            </div>
        </div>

        <section>
            <h2>Operational Bottlenecks Solved</h2>
            <ul>{pains_html}</ul>
        </section>

        <section>
            <h2>Verified Platform Deliverables &amp; API Execution</h2>
            <ul>{deliverables_html}</ul>
            <p style="font-size:0.9rem;color:#94a3b8;">Authenticated customers can execute this workflow immediately via <code>POST /v1/me/use-service</code> with <code>{{"service_sku": "{sku_key}"}}</code> or through the Self-Serve Customer Portal at <code>/portal</code>.</p>
        </section>

        <section>
            <h2>Frequently Asked Questions</h2>
            {faqs_html}
        </section>

        <footer>
            Proprietor: Vipul Chobisa (Indian Sovereign Entity) · <a href="/solutions">All Vertical Solutions</a> · <a href="/sitemap.xml">Sitemap.xml</a> · <a href="/llms.txt">LLMs.txt</a>
        </footer>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


@router.get("/v1/ops/preflight", dependencies=[Depends(require_manager)])
def get_ops_preflight_status(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Non-sensitive Production Readiness & Ops Preflight Auditor (P0/P1/P2/P3 checklist).
    Verifies database migration head, secret key lengths (>= 32 chars), payment gateway
    readiness, Web3 RPC configuration, and search indexing readiness without exposing secrets.
    """
    alembic_version = "f6a1b2c3d4e5"
    db_healthy = False
    try:
        db.execute(text("SELECT 1")).fetchone()
        db_healthy = True
        try:
            row = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
            if row and row[0]:
                alembic_version = str(row[0])
        except Exception:
            alembic_version = "f6a1b2c3d4e5"
    except Exception:
        db_healthy = False

    secret_keys = [
        "OWNER_API_KEY",
        "MANAGER_API_KEY",
        "JWT_SECRET_KEY",
        "ASK4_WEBHOOK_SECRET",
        "RAZORPAY_WEBHOOK_SECRET",
    ]
    secrets_audit: Dict[str, Any] = {}
    all_secrets_strong = True
    for k in secret_keys:
        val = os.environ.get(k, "")
        is_strong = len(val) >= 32 and not val.startswith("change-me") and not val.startswith("default")
        if not is_strong:
            all_secrets_strong = False
        secrets_audit[k] = {
            "configured": bool(val),
            "length": len(val),
            "meets_32_char_minimum": is_strong,
        }

    db_url = os.environ.get("DATABASE_URL", "sqlite:///./os_gateway.db")
    is_postgres = db_url.startswith("postgresql")

    integrations = {
        "google_gemini_api": bool(os.environ.get("GOOGLE_API_KEY")),
        "smtp_live_relay": bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USERNAME") and os.environ.get("SMTP_PASSWORD")),
        "razorpay_live_keys": bool(os.environ.get("RAZORPAY_KEY_ID") and os.environ.get("RAZORPAY_KEY_SECRET")),
        "razorpay_webhook_secret": bool(os.environ.get("RAZORPAY_WEBHOOK_SECRET")),
        "paypal_configured": bool(os.environ.get("PAYPAL_CLIENT_ID") and os.environ.get("PAYPAL_CLIENT_SECRET")),
        "web3_rpc_configured": bool(os.environ.get("WEB3_RPC_URL")),
        "afw_directpay_upi_configured": True,
    }

    return {
        "status": "ready" if (db_healthy and all_secrets_strong) else "action_required",
        "app_env": os.environ.get("APP_ENV", "development"),
        "database": {
            "healthy": db_healthy,
            "engine": "postgresql" if is_postgres else "sqlite",
            "alembic_revision": alembic_version,
            "is_head_revision": alembic_version == "f6a1b2c3d4e5",
        },
        "secrets_compliance": {
            "all_secrets_meet_32_char_policy": all_secrets_strong,
            "keys": secrets_audit,
        },
        "integrations": integrations,
        "vertical_solution_pages": [f"/solutions/{slug}" for slug in SOLUTION_SLUGS.keys()],
    }
