"""
Dedicated SSR Indexable Vertical Landing Pages & Ops Preflight Verification.
Provides crawlable HTML, unified Schema.org JSON-LD (@graph: Organization with sameAs,
SoftwareApplication, Product, BreadcrumbList, FAQPage), Open Graph + PNG og:image + Twitter Cards,
environment-gated Search Console / Bing verification tags, and rich 650+ word vertical depth.
"""
from __future__ import annotations

import html as html_lib
import json
import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import require_platform_manager
from app.services.catalog import CATALOG
from app.services.seo_meta import (
    BASE_URL,
    CANONICAL_ORG_SCHEMA,
    OG_IMAGE_URL,
    clamp_meta,
    social_meta_tags,
)

router = APIRouter(tags=["Solutions & Ops Readiness"])

SOLUTION_SLUGS: Dict[str, Dict[str, Any]] = {
    "warehouse-automation": {
        "sku": "warehouse_automation",
        "slug": "warehouse-automation",
        "short_title": "Warehouse StockSense AI | AskforWrite OS",
        "headline": "AI Warehouse & Dark-Store Replenishment OS",
        "subheadline": "Eliminate stockouts, shrink, and picking bottlenecks across 3PLs, dark stores, and cold-chain depots in under 5 minutes.",
        "hero_badge": "LOGISTICS & SUPPLY CHAIN AI",
        "cluster_name": "Operations Suite (Cluster 3 + 4)",
        "cluster_sku": "operations_suite",
        "cluster_price_inr": 9999,
        "cluster_price_usd": 129,
        "pain_points": [
            "High-velocity SKUs stock out during peak windows while slow-moving inventory ties up working capital.",
            "Manual Excel reorder sheets miss real-time safety-stock breaches and cold-chain expiry risks.",
            "Dispatch supervisors lack instant SKU-level reorder priority queues and margin-at-risk visibility.",
        ],
        "deliverables": [
            "Automated SKU safety-stock vs. current-stock variance analysis (`warehouse_analyze`).",
            "Pareto ABC-XYZ classification, dynamic Economic Order Quantity (EOQ), and Reorder Point (ROP) computation.",
            "Prioritized replenishment order schedule with urgency scoring (`CRITICAL`, `HIGH`, `NORMAL`) and dead-stock liquidation alerts.",
            "Live interactive HTML logistics telemetry preview & downloadable CSV/JSON dispatch manifest.",
        ],
        "architecture_steps": [
            "Ingest SKU inventory CSV, ERP snapshot, or webhook JSON (`sku`, `stock`, `annual_demand`, `unit_cost`, `lead_time_days`) via Portal or REST API.",
            "Compute deterministic Pareto ABC revenue tiers, XYZ demand volatility classes, safety stock buffers, and reorder point thresholds in milliseconds.",
            "Flag stockout exposure, capital trapped in dead/slow-moving inventory, and prioritized vendor PO quantities.",
            "Seal every inventory audit snapshot into the ECDSA NIST P-256 Merkle Trust Ledger for CFO and warehouse SLA compliance.",
        ],
        "benchmarks": [
            "Sub-second ABC-XYZ + EOQ + ROP calculation across thousands of SKUs with zero spreadsheet errors.",
            "Supports multi-warehouse dark stores, FMCG distributors, D2C fulfillment centers, and cold-chain depots.",
            "Bundle with Field Force GPS, Produce Vision AI, and Urban Mobility AI in the ₹9,999/mo Operations Suite (save ₹5,997/mo vs standalone).",
        ],
        "faqs": [
            {
                "q": "How does AskforWrite Warehouse Automation connect to our existing WMS or ERP?",
                "a": "AskforWrite accepts CSV/JSON SKU snapshots or REST API webhooks (POST /v1/me/use-service or /v1/tools/call) with sku, stock, demand, and safety_stock fields and returns an instant replenishment schedule.",
            },
            {
                "q": "What is the pricing and turnaround time?",
                "a": "Standalone Warehouse StockSense AI starts at ₹3,999/month ($49 USD) — or bundle all 4 Field & Vertical AI engines plus the ECDSA Trust Ledger in the Operations Suite at ₹9,999/month ($129 USD) with 20% annual savings.",
            },
            {
                "q": "How does StockSense handle dead stock and safety-stock surges?",
                "a": "Every run classifies SKUs into ABC value tiers and XYZ demand-variability classes, surfacing high-risk stockout SKUs alongside trapped dead-stock capital recommended for liquidation or redistribution.",
            },
            {
                "q": "Can we verify payment and operational compliance automatically?",
                "a": "Yes. Every paid order and inventory analysis generates an automated invoice and an ECDSA NIST P-256 cryptographically signed TrustBlock receipt.",
            },
        ],
    },
    "field-force": {
        "sku": "field_force",
        "slug": "field-force",
        "short_title": "Field Force GPS & Route AI | AskforWrite OS",
        "headline": "AI Field Force Route & Attendance Verification OS",
        "subheadline": "Real-time GPS beat compliance, route optimization, and cryptographic attendance verification for distributed field teams.",
        "hero_badge": "FIELD OPERATIONS & BEAT ROUTING AI",
        "cluster_name": "Operations Suite (Cluster 3 + 4)",
        "cluster_sku": "operations_suite",
        "cluster_price_inr": 9999,
        "cluster_price_usd": 129,
        "pain_points": [
            "Unverified field visits and fake GPS check-ins inflate travel reimbursements and reduce territory coverage.",
            "Suboptimal daily beat routing wastes 22–35% of rep productive selling and service hours.",
            "Operations managers lack real-time visibility into completed vs. pending customer site visits and conveyance claims.",
        ],
        "deliverables": [
            "Automated territory efficiency scoring and route completion diagnostics (`field_force_analyze`).",
            "Zero-trust anti-spoof GPS attendance, geofenced site check-ins, and Geo-OTP visit verification.",
            "Automated conveyance claim verification tied to verified travel legs and anomaly alerts.",
            "Cryptographic TrustBlock audit trail for high-compliance field service SLAs and payroll audits.",
        ],
        "architecture_steps": [
            "Field agents check in via Android/iOS mobile PWA (`/dashboard/#mobile`) with live GPS coordinates, timestamps, and customer Geo-OTP verification.",
            "The Zero-Trust Field Ops engine validates geofence distance, velocity plausibility, and beat plan adherence in real time.",
            "Supervisors review flagged conveyance anomalies and territory coverage metrics in the unified Command Center.",
            "Approved attendance logs, visit proofs, and conveyance settlements are cryptographically sealed with ECDSA NIST P-256 signatures.",
        ],
        "benchmarks": [
            "Eliminates ghost visits and inflated mileage claims through geofenced GPS + Geo-OTP verification.",
            "Works seamlessly offline-first via installable PWA on budget Android smartphones across Tier-2/3 territories.",
            "Bundle with Warehouse StockSense, Produce Vision, and Urban Mobility AI in the ₹9,999/mo Operations Suite.",
        ],
        "faqs": [
            {
                "q": "Who is AskforWrite Field Force AI built for?",
                "a": "FMCG distributors, pharmaceutical medical representatives, solar/telecom installation crews, agri-input field officers, and B2B field service agencies.",
            },
            {
                "q": "How quickly can a field team onboard?",
                "a": "Self-serve onboarding takes under 2 minutes after checkout (₹3,999/mo or $49/mo standalone, or ₹9,999/mo in the Operations Suite), with immediate mobile PWA, API, and Customer Portal access.",
            },
            {
                "q": "How does AskforWrite prevent fake GPS check-ins and inflated conveyance claims?",
                "a": "Check-ins are cross-validated against geofence radius, timestamp intervals, customer Geo-OTP proofs, and immutable ECDSA TrustBlock hashes before conveyance claims are approved.",
            },
            {
                "q": "Does the field app require native app-store downloads?",
                "a": "No. Field reps install the lightweight Progressive Web App (PWA) directly from the browser on Android or iOS with zero MDM friction.",
            },
        ],
    },
    "produce-quality-ai": {
        "sku": "produce-quality-ai",
        "sku_id": "mango_quality_analytics",
        "slug": "produce-quality-ai",
        "short_title": "Produce Quality Vision AI | AskforWrite OS",
        "headline": "AI Agri-Produce Quality Grading & Cold-Chain Ripeness OS",
        "subheadline": "Deterministic export-grade Brix, firmness, and defect scoring for fruit packhouses, FPOs, and agri-exporters.",
        "hero_badge": "AGRI-EXPORT & PACKHOUSE QUALITY AI",
        "cluster_name": "Operations Suite (Cluster 3 + 4)",
        "cluster_sku": "operations_suite",
        "cluster_price_inr": 9999,
        "cluster_price_usd": 129,
        "pain_points": [
            "Inconsistent manual grading leads to export consignment rejections and 15–30% post-harvest value loss.",
            "Lack of batch-level Brix and firmness traceability reduces buyer trust in international markets.",
            "Slow quality inspection bottlenecks packhouse throughput during peak harvest windows.",
        ],
        "deliverables": [
            "Batch-level export grade classification (`Export Grade A`, `Domestic Grade B`, `Processing Grade C`).",
            "512D HSV + GLCM computer vision colorimetry, Brix ripeness estimation, and cold-chain shelf-life prediction (`mango_quality_analyze`).",
            "Defect percentage and blemish breakdown with packhouse dispatch prioritization.",
            "Tamper-evident ECDSA NIST P-256 quality certificate for international buyers and customs documentation.",
        ],
        "architecture_steps": [
            "Packhouse operators upload fruit lot telemetry or capture produce imagery directly in the Customer Portal or REST API.",
            "A 4-model ensemble combines 512D HSV chromatic histograms, GLCM surface texture features, Brix sugar estimates, and firmness metrics.",
            "Each consignment receives deterministic Export/Domestic/Processing grading plus remaining cold-chain shelf-life hours.",
            "Every grading decision emits a verifiable ECDSA NIST P-256 TrustBlock certificate shareable with importers and retail chains.",
        ],
        "benchmarks": [
            "Standardizes subjective manual visual grading into reproducible, lot-level numerical quality scores.",
            "Optimized out-of-the-box for Alphonso, Kesar, and Banganapalli mangoes and extensible to pomegranate, citrus, and table grapes.",
            "Included standalone at ₹3,999/mo ($49 USD) or bundled with Warehouse & Field Force AI in the ₹9,999/mo Operations Suite.",
        ],
        "faqs": [
            {
                "q": "Which crops and packhouse workflows are supported?",
                "a": "Optimized out-of-the-box for mangoes (Alphonso, Kesar, Banganapalli) and extensible to pomegranate, citrus, and table grapes via Brix, firmness, and HSV/GLCM color telemetry.",
            },
            {
                "q": "How much does the Produce Quality AI suite cost?",
                "a": "₹3,999/month ($49 USD) standalone — or ₹9,999/month ($129 USD) bundled in the Operations Suite with Warehouse StockSense, Field Force GPS, Urban Mobility AI, and ECDSA Trust Ledger.",
            },
            {
                "q": "Can exporters share verifiable quality certificates with international buyers?",
                "a": "Yes. Each batch inspection is sealed into an immutable ECDSA NIST P-256 TrustBlock so importers, cold-chain partners, and customs brokers can verify authenticity.",
            },
            {
                "q": "Can we integrate Produce Quality AI into our packhouse ERP or sorting line?",
                "a": "Yes. Authenticated REST endpoints (POST /v1/me/use-service with service_key mango_quality_analytics) return deterministic JSON grading payloads in under a second.",
            },
        ],
    },
    "urban-mobility-ai": {
        "sku": "bike_rebalance_analytics",
        "slug": "urban-mobility-ai",
        "short_title": "Urban Mobility Fleet AI | AskforWrite OS",
        "headline": "AI EV Fleet & Micro-Mobility Station Rebalancing OS",
        "subheadline": "Maximize fleet utilization and eliminate empty dock losses with predictive station rebalancing.",
        "hero_badge": "EV FLEET & URBAN MOBILITY AI",
        "cluster_name": "Operations Suite (Cluster 3 + 4)",
        "cluster_sku": "operations_suite",
        "cluster_price_inr": 9999,
        "cluster_price_usd": 129,
        "pain_points": [
            "Commuter surge hours leave origin stations empty and destination docks overflowing.",
            "Manual van dispatch routes waste fuel and miss high-revenue peak-hour rider trips.",
            "Fleet operators lack station-level deficit vs. capacity telemetry and hourly demand forecasts.",
        ],
        "deliverables": [
            "Real-time station deficit/surplus matrix and dock saturation heat scoring (`bike_rebalance_analyze`).",
            "Hourly OLS commuter demand forecasting factoring time-of-day, weather, and station capacity.",
            "Prioritized dispatch transfer manifest for battery-swap and rebalancing truck crews.",
            "Automated fleet utilization KPI tracking sealed in the ECDSA Trust Ledger.",
        ],
        "architecture_steps": [
            "Ingest live station telemetry (station ID, capacity, active EVs/bikes, coordinates, and hourly demand window) via CSV or API.",
            "Predict upcoming hourly station inflow/outflow imbalance using deterministic spatiotemporal forecasting.",
            "Match surplus donor docks to high-deficit priority stations to minimize truck transfer distance and empty-dock penalties.",
            "Dispatch verified transfer manifests to field crews and log operational SLA compliance on the Trust Ledger.",
        ],
        "benchmarks": [
            "Designed for EV two-wheeler rentals, campus bike-share networks, battery-swapping stations, and last-mile delivery fleets.",
            "Generates actionable dock-to-dock transfer manifests in milliseconds via Web Portal or REST API.",
            "Available standalone at ₹3,999/mo ($49 USD) or inside the ₹9,999/mo Operations Suite with Field Force GPS & Warehouse AI.",
        ],
        "faqs": [
            {
                "q": "How does station rebalancing work?",
                "a": "Submit station dock capacity and current active vehicle counts via API or the Customer Portal to receive an instant surplus/deficit diagnosis and prioritized truck transfer plan.",
            },
            {
                "q": "Which mobility operators benefit most from AskforWrite Urban Mobility AI?",
                "a": "EV scooter and e-bike rental networks, city bike-share systems, quick-commerce EV battery-swapping hubs, and smart-campus micro-mobility fleets.",
            },
            {
                "q": "What is the pricing for Urban Mobility AI?",
                "a": "₹3,999/month ($49 USD) standalone, or bundle all 4 Cluster 3 vertical AI engines plus the ECDSA Trust Ledger in the Operations Suite at ₹9,999/month ($129 USD).",
            },
            {
                "q": "Can rebalancing manifests connect to our field dispatchers?",
                "a": "Yes. Pair Urban Mobility AI with AskforWrite Field Force GPS inside the Operations Suite to verify rebalancing van arrivals and dock handoffs with Geo-OTP.",
            },
        ],
    },
    "seo-blog-copilot": {
        "sku": "seo_blog_copilot",
        "slug": "seo-blog-copilot",
        "short_title": "SEO, AEO & GEO Blog Copilot | AskforWrite",
        "headline": "Autonomous SEO, AEO & GEO Content Copilot",
        "subheadline": "Publish high-authority, structured-data-enriched technical articles engineered to rank on Google and AI Answer Engines.",
        "hero_badge": "SEO / AEO / GEO GROWTH ENGINE",
        "cluster_name": "Growth Suite (Cluster 1 + 2)",
        "cluster_sku": "growth_all_in_one",
        "cluster_price_inr": 6999,
        "cluster_price_usd": 89,
        "pain_points": [
            "Generic AI blog posts fail Google E-E-A-T checks and lack verifiable product anchors.",
            "Missing Schema.org JSON-LD, FAQPage markup, and /llms.txt blocks prevent citation in ChatGPT, Perplexity, and Google AI Overviews.",
            "Content teams spend days formatting metadata, canonical tags, internal links, and multi-channel social snippets.",
        ],
        "deliverables": [
            "Long-form technical articles with keyword intent mapping, entity definitions, and FAQPage Schema.org JSON-LD.",
            "Automated AEO/GEO citation blocks and /llms.txt manifests structured for SearchGPT, Perplexity, Claude, and Gemini.",
            "Human-in-the-Loop (HITL) WordPress publishing bridge across up to 4 sites plus Markdown/HTML export.",
            "Paired 7-channel social promotion scripts ready for LinkedIn, Instagram, X, and Google Search Ads.",
        ],
        "architecture_steps": [
            "Scan target domain SEO/GEO gaps with the 60-second Opportunity Scanner to identify missing schema, thin pages, and keyword openings.",
            "Generate entity-dense long-form articles paired with Article, Organization, SoftwareApplication, and FAQPage Schema.org @graph payloads.",
            "Review staged drafts inside the HITL Approval Gate so zero unreviewed content ever publishes automatically.",
            "Publish straight to WordPress or export clean Markdown/HTML with an ECDSA TrustBlock proof record.",
        ],
        "benchmarks": [
            "Standalone SEO & GEO Copilot starts at ₹1,999/month ($29 USD), or upgrade to Launch (₹2,999/mo) for Pixel AI + Marketing Suite.",
            "Bundle full Content/SEO/Creative + Lead Discovery + 24/7 WhatsApp/Web AI Closer in the Growth Suite at ₹6,999/month ($89 USD).",
            "Strict BYOK Gemini isolation keeps tenant prompts, brand voice, and drafts 100% private with zero token markup.",
        ],
        "faqs": [
            {
                "q": "Does SEO Blog Copilot optimize for AI search engines (AEO/GEO)?",
                "a": "Yes. Every article includes structured entity definitions, direct-answer blocks, Schema.org FAQPage + Article JSON-LD, and /llms.txt manifests designed for Google AI Overviews, SearchGPT, Perplexity, and Claude citation.",
            },
            {
                "q": "Does it publish directly to WordPress safely?",
                "a": "Yes. Our WordPress publishing bridge stages drafts with Human-in-the-Loop (HITL) approval gates so your team reviews and approves every post before it goes live.",
            },
            {
                "q": "How much does SEO Blog Copilot cost?",
                "a": "Standalone SEO & GEO Blog Copilot is ₹1,999/month ($29 USD). Launch (Cluster 1: SEO + Marketing + Pixel AI) is ₹2,999/month ($39 USD), and Growth Suite (Clusters 1+2 with 24/7 AI Sales Closer) is ₹6,999/month ($89 USD).",
            },
            {
                "q": "Can we start with a Done-For-You pilot before subscribing?",
                "a": "Yes. Our 14-Day Done-For-You Managed SEO & Content Pilot (₹4,999 / $59 one-time) audits your site, deploys Schema.org + /llms.txt, and delivers ready-to-publish authority articles.",
            },
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
        "monthly_price_inr": pkg.price_inr if pkg else 3999,
        "monthly_price_usd": pkg.price_usd if pkg else 49,
    }
    return {**meta, "sku": sku_key, "catalog": catalog_entry}


@router.get("/solutions", response_class=HTMLResponse)
def solutions_hub_page() -> HTMLResponse:
    """Indexable SSR hub page for all AskforWrite AI Company OS vertical solutions."""
    cards_html = ""
    item_list_elements: List[Dict[str, Any]] = []

    for idx, (slug, info) in enumerate(SOLUTION_SLUGS.items(), start=1):
        sku_key = info.get("sku_id") or info["sku"]
        pkg = CATALOG.get(sku_key)
        price_inr = pkg.price_inr if pkg else 3999
        price_usd = pkg.price_usd if pkg else 49
        url = f"{BASE_URL}/solutions/{slug}"
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
            <div class="badge">{html_lib.escape(info["hero_badge"])}</div>
            <h2><a href="/solutions/{html_lib.escape(slug)}">{html_lib.escape(info["headline"])}</a></h2>
            <p>{html_lib.escape(info["subheadline"])}</p>
            <div class="price">₹{price_inr:,}/mo <span>(${price_usd} USD/mo · Annual -20%)</span></div>
            <div class="actions">
                <a class="btn-primary" href="/solutions/{html_lib.escape(slug)}">Explore Solution &amp; Architecture →</a>
                <a class="btn-secondary" href="/v1/pay/checkout?package={html_lib.escape(sku_key)}">Instant Checkout</a>
            </div>
        </article>
        """

    page_title = "Vertical AI Solutions Catalog | AskforWrite OS"
    page_desc = clamp_meta(
        "Production vertical AI systems by AskforWrite: Warehouse StockSense, Field Force GPS, Produce Vision Grading, EV Fleet Rebalancing & SEO/GEO Copilot.",
        155,
    )

    schema_graph = {
        "@context": "https://schema.org",
        "@graph": [
            CANONICAL_ORG_SCHEMA,
            {
                "@type": "ItemList",
                "@id": f"{BASE_URL}/solutions#catalog",
                "name": "AskforWrite Verified Vertical AI Solutions",
                "numberOfItems": len(item_list_elements),
                "itemListElement": item_list_elements,
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{BASE_URL}/"},
                    {"@type": "ListItem", "position": 2, "name": "Vertical Solutions", "item": f"{BASE_URL}/solutions"},
                ],
            },
            {
                "@type": "FAQPage",
                "@id": f"{BASE_URL}/solutions#faq",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": "Which vertical AI solutions are available on AskforWrite AI Company OS?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "AskforWrite offers modular vertical AI solutions for Warehouse StockSense Inventory Automation, Field Force GPS & Route Verification, Agri-Produce Computer Vision Quality Grading, Urban EV Fleet & Micro-Mobility Rebalancing, and Autonomous SEO/GEO & Omnichannel Growth.",
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "How fast can a business deploy and access a vertical AI workspace?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "Subscribers can select a standalone module or the Operations Suite, complete checkout via AFW DirectPay (0% fee UPI QR, USDC Web3, or Bank Wire), and immediately access entitled dashboards, REST APIs, and the Self-Serve Customer Portal.",
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "Are AI decisions and commercial transactions cryptographically auditable?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "Yes. Sensitive operational actions use Human-in-the-Loop (HITL) governance and every verified execution, quality certificate, and billing settlement is sealed into an immutable ECDSA NIST P-256 Merkle Trust Ledger.",
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "What pricing options are supported for Indian SMBs and global teams?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "Standalone vertical AI modules start at ₹1,999–₹3,999/month ($29–$49 USD/month), or bundle all 4 Field & Vertical AI engines plus the ECDSA Trust Ledger in the Operations Suite at ₹9,999/month ($129 USD/month) with 20% annual savings.",
                        },
                    },
                ],
            },
        ],
    }

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{html_lib.escape(page_title)}</title>
    <meta name="description" content="{html_lib.escape(page_desc)}" />
    {social_meta_tags(title=page_title, description=page_desc, canonical_url=f"{BASE_URL}/solutions")}
    <script type="application/ld+json">{json.dumps(schema_graph)}</script>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; background: #0b0f19; color: #f1f5f9; margin: 0; padding: 0; line-height: 1.6; }}
        header {{ max-width: 1100px; margin: 0 auto; padding: 32px 24px 24px; border-bottom: 1px solid #1e293b; }}
        nav {{ margin-bottom: 18px; }}
        nav a {{ color: #94a3b8; text-decoration: none; margin-right: 16px; font-size: 0.9rem; }}
        nav a:hover {{ color: #38bdf8; }}
        h1 {{ font-size: 2.25rem; margin: 8px 0; color: #ffffff; }}
        .grid {{ max-width: 1100px; margin: 32px auto; padding: 0 24px 48px; display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 24px; }}
        .card {{ background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 24px; display: flex; flex-direction: column; justify-content: space-between; }}
        .badge {{ font-size: 0.75rem; font-weight: 700; color: #38bdf8; letter-spacing: 0.08em; text-transform: uppercase; }}
        .card h2 a {{ color: #ffffff; text-decoration: none; }}
        .price {{ font-size: 1.4rem; font-weight: 700; color: #34d399; margin: 16px 0; }}
        .price span {{ font-size: 0.92rem; color: #94a3b8; font-weight: 400; }}
        .actions {{ display: flex; gap: 12px; flex-wrap: wrap; }}
        .btn-primary {{ background: #4f46e5; color: #fff; text-decoration: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; font-size: 0.9rem; }}
        .btn-secondary {{ background: #1e293b; color: #e2e8f0; text-decoration: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; font-size: 0.9rem; border: 1px solid #334155; }}
        .bundle-banner {{ max-width: 1100px; margin: 0 auto 36px; padding: 0 24px; }}
        .bundle-inner {{ background: linear-gradient(135deg, rgba(79,70,229,0.2), #111827); border: 1px solid #4f46e5; border-radius: 14px; padding: 24px; display: flex; justify-content: space-between; align-items: center; gap: 18px; flex-wrap: wrap; }}
        footer {{ max-width: 1100px; margin: 0 auto; padding: 24px; border-top: 1px solid #1e293b; color: #94a3b8; font-size: 0.85rem; }}
        footer a {{ color: #38bdf8; text-decoration: none; margin-right: 12px; }}
    </style>
</head>
<body>
    <header>
        <nav>
            <a href="/">Home</a>
            <a href="/services">Clustered Pricing &amp; Services</a>
            <a href="/solutions">Vertical Solutions</a>
            <a href="/dashboard/">Workspace</a>
            <a href="/llms.txt">LLMs.txt</a>
        </nav>
        <div class="badge">ASKFORWRITE AI COMPANY OS · VERTICAL SOLUTIONS</div>
        <h1>Production-Verified AI Operating Systems for Real Business Outcomes</h1>
        <p>Every AskforWrite vertical solution connects real operational telemetry to deterministic AI workflows, human-in-the-loop (HITL) governance, instant multi-currency checkout (Razorpay, PayPal, Sovereign UPI &amp; Polygon/Base USDC), and ECDSA NIST P-256 TrustBlock receipts.</p>
    </header>
    <main>
        <div class="grid">{cards_html}</div>
        <div class="bundle-banner">
            <div class="bundle-inner">
                <div>
                    <div class="badge">BEST VALUE FOR OPERATIONS TEAMS</div>
                    <h2 style="margin:6px 0;color:#fff;">Bundle All 4 Field &amp; Vertical AI Engines in the Operations Suite</h2>
                    <p style="margin:0;color:#cbd5e1;max-width:680px;">Get Warehouse StockSense AI + Field Force GPS/PWA + Produce Quality Vision AI + Urban Mobility AI + ECDSA Trust Ledger together for <strong>₹9,999/month ($129 USD)</strong> — or ₹7,999/mo billed annually.</p>
                </div>
                <a class="btn-primary" href="/v1/pay/checkout?package=operations_suite">Subscribe to Operations Suite →</a>
            </div>
        </div>
    </main>
    <footer>
        © 2026 ASKFORWRITE (MSME Udyam: UDYAM-RJ-14-0018404) · <a href="/">Home</a> · <a href="/services">All Services</a> · <a href="/sitemap.xml">Sitemap</a> · <a href="/llms.txt">LLMs.txt</a> · <a href="/legal/declaration">Legal Charter</a>
    </footer>
</body>
</html>"""
    return HTMLResponse(content=page_html, status_code=200)


@router.get("/solutions/{slug}", response_class=HTMLResponse)
def solution_detail_page(slug: str) -> HTMLResponse:
    """Dedicated SSR indexable landing page for a specific vertical SKU."""
    data = _resolve_sku_data(slug)
    canonical_url = f"{BASE_URL}/solutions/{slug}"
    sku_key = data["sku"]
    cat = data["catalog"]
    price_inr = cat.get("monthly_price_inr", 3999)
    price_usd = cat.get("monthly_price_usd", 49)
    annual_inr = round(price_inr * 0.8)
    annual_usd = round(price_usd * 0.8)
    short_title = data.get("short_title") or f"{data['headline'][:42]} | AskforWrite"
    meta_desc = clamp_meta(
        f"{data['subheadline']} Priced at ₹{price_inr:,}/mo (${price_usd} USD) with instant activation, REST API & ECDSA NIST P-256 Trust Ledger.",
        155,
    )

    pains_html = "".join(f"<li>{html_lib.escape(p)}</li>" for p in data["pain_points"])
    deliverables_html = "".join(f"<li>{html_lib.escape(d)}</li>" for d in data["deliverables"])
    arch_html = "".join(
        f"<li><strong>Step {i}:</strong> {html_lib.escape(step)}</li>"
        for i, step in enumerate(data.get("architecture_steps", []), start=1)
    )
    bench_html = "".join(f"<li>{html_lib.escape(b)}</li>" for b in data.get("benchmarks", []))
    faqs_html = "".join(
        f'<div class="faq-item"><h3>{html_lib.escape(f["q"])}</h3><p>{html_lib.escape(f["a"])}</p></div>'
        for f in data["faqs"]
    )
    other_solutions = "".join(
        f'<li><a href="/solutions/{html_lib.escape(s)}">{html_lib.escape(info["headline"])}</a> — {html_lib.escape(info["hero_badge"])}</li>'
        for s, info in SOLUTION_SLUGS.items()
        if s != slug
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
            CANONICAL_ORG_SCHEMA,
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{BASE_URL}/"},
                    {"@type": "ListItem", "position": 2, "name": "Solutions", "item": f"{BASE_URL}/solutions"},
                    {"@type": "ListItem", "position": 3, "name": data["headline"], "item": canonical_url},
                ],
            },
            {
                "@type": ["SoftwareApplication", "Product"],
                "@id": f"{canonical_url}#product",
                "name": data["headline"],
                "sku": sku_key,
                "image": OG_IMAGE_URL,
                "applicationCategory": "BusinessApplication",
                "operatingSystem": "Cloud / Web / REST API",
                "description": data["subheadline"],
                "url": canonical_url,
                "brand": {"@id": f"{BASE_URL}/#organization"},
                "offers": [
                    {
                        "@type": "Offer",
                        "priceCurrency": "INR",
                        "price": str(price_inr),
                        "priceValidUntil": "2027-12-31",
                        "availability": "https://schema.org/InStock",
                        "url": f"{BASE_URL}/v1/pay/checkout?package={sku_key}",
                    },
                    {
                        "@type": "Offer",
                        "priceCurrency": "USD",
                        "price": str(price_usd),
                        "priceValidUntil": "2027-12-31",
                        "availability": "https://schema.org/InStock",
                        "url": f"{BASE_URL}/v1/pay/checkout?package={sku_key}&currency=USD",
                    },
                ],
            },
            {
                "@type": "FAQPage",
                "@id": f"{canonical_url}#faq",
                "mainEntity": faq_schema_entities,
            },
        ],
    }

    cluster_name = data.get("cluster_name", "Operations Suite")
    cluster_sku = data.get("cluster_sku", "operations_suite")
    cluster_inr = int(data.get("cluster_price_inr", 9999))
    cluster_usd = int(data.get("cluster_price_usd", 129))

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{html_lib.escape(short_title)}</title>
    <meta name="description" content="{html_lib.escape(meta_desc)}" />
    {social_meta_tags(title=short_title, description=meta_desc, canonical_url=canonical_url, og_type="product")}
    <script type="application/ld+json">{json.dumps(schema_graph)}</script>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; background: #0b0f19; color: #f1f5f9; margin: 0; padding: 0; line-height: 1.65; }}
        .container {{ max-width: 960px; margin: 0 auto; padding: 36px 24px 48px; }}
        .breadcrumb {{ font-size: 0.85rem; color: #94a3b8; margin-bottom: 16px; }}
        .breadcrumb a {{ color: #38bdf8; text-decoration: none; }}
        .badge {{ display: inline-block; background: #1e293b; color: #38bdf8; padding: 4px 12px; border-radius: 999px; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.08em; }}
        h1 {{ font-size: 2.3rem; margin: 12px 0; color: #ffffff; line-height: 1.2; }}
        .sub {{ font-size: 1.12rem; color: #cbd5e1; max-width: 780px; }}
        .cta-box {{ background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 24px; margin: 28px 0; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; }}
        .price {{ font-size: 1.7rem; font-weight: 800; color: #34d399; }}
        .btn {{ display: inline-block; background: #4f46e5; color: #ffffff; padding: 12px 22px; border-radius: 8px; text-decoration: none; font-weight: 700; }}
        .btn-alt {{ display: inline-block; background: #1e293b; color: #e2e8f0; padding: 11px 18px; border-radius: 8px; text-decoration: none; font-weight: 600; border: 1px solid #334155; }}
        section {{ margin: 28px 0; background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 26px; }}
        h2 {{ color: #38bdf8; margin-top: 0; font-size: 1.35rem; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 0.92rem; }}
        th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #1f2937; }}
        th {{ color: #93c5fd; }}
        .faq-item {{ border-top: 1px solid #1f2937; padding-top: 14px; margin-top: 14px; }}
        .faq-item h3 {{ margin: 0 0 6px; font-size: 1.02rem; color: #e2e8f0; }}
        ul a {{ color: #60a5fa; text-decoration: none; }}
        footer {{ border-top: 1px solid #1e293b; padding-top: 24px; color: #94a3b8; font-size: 0.85rem; }}
        footer a {{ color: #38bdf8; text-decoration: none; margin-right: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <nav class="breadcrumb">
            <a href="/">Home</a> &rsaquo; <a href="/solutions">Solutions</a> &rsaquo; <span>{html_lib.escape(data["headline"])}</span>
        </nav>
        <span class="badge">{html_lib.escape(data["hero_badge"])}</span>
        <h1>{html_lib.escape(data["headline"])}</h1>
        <p class="sub">{html_lib.escape(data["subheadline"])}</p>

        <div class="cta-box">
            <div>
                <div class="price">₹{price_inr:,}/month <span style="font-size:0.98rem;color:#94a3b8;font-weight:400;">(${price_usd} USD/mo · Annual -20%: ₹{annual_inr:,}/mo / ${annual_usd})</span></div>
                <div style="font-size:0.9rem;color:#94a3b8;">Includes instant workspace activation, REST API &amp; Customer Portal access, Strict BYOK privacy, and ECDSA NIST P-256 TrustBlock receipts.</div>
            </div>
            <div style="display:flex;gap:10px;flex-wrap:wrap;">
                <a class="btn" href="/v1/pay/checkout?package={html_lib.escape(sku_key)}">Activate {html_lib.escape(sku_key)} →</a>
                <a class="btn-alt" href="/services/{html_lib.escape(sku_key)}">Full SKU Specs</a>
            </div>
        </div>

        <section>
            <h2>Operational Bottlenecks Solved</h2>
            <ul>{pains_html}</ul>
        </section>

        <section>
            <h2>End-to-End Architecture &amp; Telemetry Pipeline</h2>
            <ol>{arch_html}</ol>
            <p style="font-size:0.9rem;color:#94a3b8;">Authenticated tenants execute this workflow programmatically via <code>POST /v1/me/use-service</code> with <code>{{"service_key": "{html_lib.escape(sku_key)}"}}</code> or interactively through the Self-Serve Customer Portal at <code>/dashboard/#portal</code>.</p>
        </section>

        <section>
            <h2>Verified Platform Deliverables &amp; Operational Benchmarks</h2>
            <ul>{deliverables_html}</ul>
            <ul>{bench_html}</ul>
        </section>

        <section>
            <h2>Standalone Module vs. Clustered Subscription Comparison</h2>
            <table>
                <thead>
                    <tr><th>Option</th><th>Monthly Price</th><th>Annual (-20%)</th><th>Best For</th></tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong>Standalone: {html_lib.escape(sku_key)}</strong></td>
                        <td>₹{price_inr:,}/mo (${price_usd} USD)</td>
                        <td>₹{annual_inr:,}/mo (${annual_usd} USD)</td>
                        <td>Single-workflow teams needing focused vertical automation</td>
                    </tr>
                    <tr>
                        <td><strong>{html_lib.escape(cluster_name)}</strong></td>
                        <td>₹{cluster_inr:,}/mo (${cluster_usd} USD)</td>
                        <td>₹{round(cluster_inr * 0.8):,}/mo (${round(cluster_usd * 0.8)} USD)</td>
                        <td>Teams bundling multi-agent workflows + ECDSA Trust Ledger <a href="/v1/pay/checkout?package={html_lib.escape(cluster_sku)}" style="color:#38bdf8;">(Checkout →)</a></td>
                    </tr>
                    <tr>
                        <td><strong>Business Pro (All 4 Clusters)</strong></td>
                        <td>₹17,999/mo ($229 USD)</td>
                        <td>₹14,399/mo ($183 USD)</td>
                        <td>Multi-department SMBs running Sales, SEO, Field Ops &amp; Governance</td>
                    </tr>
                </tbody>
            </table>
        </section>

        <section>
            <h2>Frequently Asked Questions</h2>
            {faqs_html}
        </section>

        <section>
            <h2>Explore Other AskforWrite Vertical AI Solutions</h2>
            <ul>{other_solutions}</ul>
        </section>

        <footer>
            © 2026 ASKFORWRITE (MSME Udyam: UDYAM-RJ-14-0018404 · Udaipur, Rajasthan, India) · <a href="/">Home</a> · <a href="/services">All 16 Services</a> · <a href="/solutions">All Vertical Solutions</a> · <a href="/sitemap.xml">Sitemap</a> · <a href="/llms.txt">LLMs.txt</a> · <a href="/legal/tos">Terms</a>
        </footer>
    </div>
</body>
</html>"""
    return HTMLResponse(content=page_html, status_code=200)


def _get_alembic_expected_heads() -> list[str]:
    """Inspect expected Alembic head revision(s) dynamically from migrations/."""
    try:
        from pathlib import Path
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        repo_root = Path(__file__).resolve().parents[3]
        cfg = Config(str(repo_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(repo_root / "migrations"))
        return list(ScriptDirectory.from_config(cfg).get_heads())
    except Exception:
        return []


@router.get("/v1/ops/preflight", dependencies=[Depends(require_platform_manager)])
def get_ops_preflight_status(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Non-sensitive Production Readiness & Ops Preflight Auditor (P0/P1/P2/P3 checklist).
    Verifies database migration head, secret key lengths (>= 32 chars), payment gateway
    readiness, Web3 RPC configuration, and search indexing readiness without exposing secrets.
    """
    expected_heads = _get_alembic_expected_heads()
    alembic_version = "not_stamped"
    db_healthy = False
    try:
        db.execute(text("SELECT 1")).fetchone()
        db_healthy = True
        try:
            row = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
            if row and row[0]:
                alembic_version = str(row[0])
        except Exception:
            alembic_version = "not_stamped"
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

    db_url = os.environ.get("NEON_DATABASE_URL") or os.environ.get("DATABASE_URL", "sqlite:///./os_gateway.db")
    is_postgres = db_url.startswith(("postgresql", "postgres"))

    integrations = {
        "google_gemini_api": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
        "smtp_live_relay": bool(os.environ.get("SMTP_HOST") and (os.environ.get("SMTP_USERNAME") or os.environ.get("SMTP_USER")) and os.environ.get("SMTP_PASSWORD")),
        "razorpay_live_keys": bool(os.environ.get("RAZORPAY_KEY_ID") and os.environ.get("RAZORPAY_KEY_SECRET")),
        "razorpay_webhook_secret": bool(os.environ.get("RAZORPAY_WEBHOOK_SECRET")),
        "paypal_configured": bool(os.environ.get("PAYPAL_CLIENT_ID") and os.environ.get("PAYPAL_CLIENT_SECRET")),
        "gsc_oauth_configured": bool(os.environ.get("GSC_CLIENT_ID") and os.environ.get("GSC_CLIENT_SECRET") and os.environ.get("GSC_REDIRECT_URI")),
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
            "expected_heads": expected_heads,
            "is_head_revision": alembic_version in expected_heads if expected_heads else False,
        },
        "secrets_compliance": {
            "all_secrets_meet_32_char_policy": all_secrets_strong,
            "keys": secrets_audit,
        },
        "integrations": integrations,
        "vertical_solution_pages": [f"/solutions/{slug}" for slug in SOLUTION_SLUGS.keys()],
    }
