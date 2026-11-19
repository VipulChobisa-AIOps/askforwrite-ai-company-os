"""Public SEO, AEO, and GEO Service Landing Pages Router.

Provides dedicated, crawlable, indexable HTML5 landing pages for:
- GET /services — Complete Service Directory with ItemList Schema.org JSON-LD
- GET /services/{service_key} — Individual Service Landing Page for each of the 14 Catalog SKUs
  with canonical URL, Open Graph tags, semantic H1/H2/H3 hierarchy, buyer persona, problem solved,
  deliverables, transparent INR/USD pricing, limitations, FAQs, and Schema.org @graph JSON-LD.
"""

from __future__ import annotations

import html
import json
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse

from app.services.catalog import MODULAR_SME_TIERS, PRICING_CLUSTERS, get_all_packages, get_package

router = APIRouter(tags=["seo-service-pages"])


@router.get("/services", response_class=HTMLResponse, include_in_schema=False)
def list_service_landing_pages() -> HTMLResponse:
    """Render an indexable HTML5 directory of all verified AskforWrite AI Company OS services."""
    packages = get_all_packages()
    item_list_elements = []
    cards_html = []

    tier_cards_html = []
    tier_sku_map = {
        "launch": "company_os_starter",
        "growth": "growth_all_in_one",
        "operations": "operations_suite",
        "business_pro": "company_os_pro",
        "enterprise": "company_os_enterprise",
    }
    for t_key, tier in MODULAR_SME_TIERS.items():
        bp = tier.get("base_price", {})
        ap = tier.get("annual_price", {})
        inc_clusters = tier.get("included_clusters", [])
        cluster_badges = "".join(
            f'<span class="cluster-pill">{html.escape(str(PRICING_CLUSTERS.get(ck, {}).get("name", ck)).split(":")[0])}</span>'
            for ck in inc_clusters
        )
        checkout_sku = tier_sku_map.get(t_key, t_key)
        highlighted = " featured-tier" if t_key == "growth" else ""
        credits = tier.get("included_credits", {})
        tier_cards_html.append(
            f"""
            <article class="tier-card{highlighted}">
              <div class="tier-top">
                <span class="badge">{html.escape(t_key.replace('_', ' ').upper())}</span>
                <div class="cluster-pills">{cluster_badges}</div>
              </div>
              <h3>{html.escape(str(tier.get('name', t_key)))}</h3>
              <p class="desc">{html.escape(str(tier.get('target_sme', '')))}</p>
              <div class="tier-price">₹{int(bp.get('inr', 0)):,}<span>/mo · ${int(bp.get('usd', 0))} USD</span></div>
              <div class="tier-annual">Annual (-{int(ap.get('discount_pct', 20))}%): ₹{int(ap.get('inr', 0)):,}/mo (${int(ap.get('usd', 0))}/mo)</div>
              <p class="meta"><strong>Capacity:</strong> {int(tier.get('agent_limit', 2))} Agents · {int(tier.get('seat_limit', 2))} Seats · {int(credits.get('lead_credits', 50)):,} Leads · {int(credits.get('ai_execution_credits', 150)):,} AI Runs</p>
              <a class="tier-cta" href="/v1/pay/checkout?package={html.escape(checkout_sku)}">Subscribe via DirectPay →</a>
            </article>
            """
        )

    cluster_cards_html = []
    for ck, cl in PRICING_CLUSTERS.items():
        svcs = ", ".join(str(s) for s in cl.get("services", []))
        cluster_cards_html.append(
            f"""
            <div class="cluster-card">
              <div class="badge">CLUSTER {int(cl.get('cluster_number', 1))}</div>
              <h3>{html.escape(str(cl.get('name', ck)))}</h3>
              <p class="desc">{html.escape(str(cl.get('tagline', '')))}</p>
              <p class="meta"><strong>Tools &amp; Services:</strong> <code>{html.escape(svcs)}</code></p>
            </div>
            """
        )

    for idx, pkg in enumerate(packages, start=1):
        url = f"https://os.askforwrite.com/services/{pkg.key}"
        item_list_elements.append(
            {
                "@type": "ListItem",
                "position": idx,
                "name": pkg.name,
                "url": url,
                "description": pkg.description,
            }
        )
        cards_html.append(
            f"""
            <article class="service-card">
              <span class="badge">{html.escape(pkg.category.replace('_', ' ').upper())}</span>
              <h2><a href="/services/{html.escape(pkg.key)}">{html.escape(pkg.name)}</a></h2>
              <p class="desc">{html.escape(pkg.description)}</p>
              <p class="meta"><strong>Target Buyer:</strong> {html.escape(pkg.target_buyer_persona)}</p>
              <p class="meta"><strong>Problem Solved:</strong> {html.escape(pkg.target_pain_point)}</p>
              <div class="price-row">
                <span class="price">₹{pkg.price_inr:,} INR <small>/ ${pkg.price_usd} USD</small></span>
                <a class="cta-link" href="/services/{html.escape(pkg.key)}">View Specs &amp; Deliverables →</a>
              </div>
            </article>
            """
        )

    schema_graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "name": "AskforWrite",
                "legalName": "ASKFORWRITE",
                "identifier": "UDYAM-RJ-14-0018404",
                "url": "https://os.askforwrite.com",
                "email": "info@askforwrite.in",
            },
            {
                "@type": "ItemList",
                "name": "AskforWrite AI Company OS — Verified Commercial Services",
                "numberOfItems": len(packages),
                "itemListElement": item_list_elements,
            },
            {
                "@type": "FAQPage",
                "@id": "https://os.askforwrite.com/services#faq",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": "How does AskforWrite AI Company OS clustered subscription pricing work?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "AskforWrite groups its 16 AI tools into 4 functional clusters (Content/SEO/Creative, Sales/Discovery/AI Closer, Field Ops/Vertical AI, and Governance/Trust Ledger) across 5 monthly subscription tiers: Launch (₹2,999/$39), Growth Suite (₹6,999/$89), Operations Suite (₹9,999/$129), Business Pro (₹17,999/$229), and Enterprise (₹44,999/$549), with 20% annual savings and stackable modular add-ons."
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "Can customers run AskforWrite services via both the Web Portal and REST API?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "Yes. Every subscribed organization receives entitlement-driven access to dedicated workspace dashboards inside os.askforwrite.com as well as authenticated Bearer-token execution via POST /v1/me/use-service."
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "How are SEO and Generative Engine Optimization (GEO) deliverables structured?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "AskforWrite's SEO Copilot and Growth Suite generate structured Markdown articles, Schema.org JSON-LD graphs (Article, FAQPage, Organization, SoftwareApplication), /llms.txt manifests for AI crawlers, and 7-channel social copy."
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "How do organizations activate a service with zero payment gateway commission?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "Checkout links use AFW DirectPay supporting Instant UPI QR (GPay, PhonePe, Paytm, BHIM), Polygon/Base/Solana USDC stablecoins, and Direct Bank Wire with automated ECDSA NIST P-256 TrustBlock receipts."
                        },
                    },
                ],
            },
        ],
    }

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Clustered AI Subscriptions &amp; Modular Service Catalog | AskforWrite Company OS</title>
  <meta name="description" content="Explore AskforWrite Company OS clustered subscriptions (₹2,999 to ₹44,999/mo) across 4 AI capability clusters: Content & SEO Studio, Sales & AI Closer, Field & Vertical AI (Warehouse, Field Force, Produce Vision, Urban Mobility), and ECDSA Trust Ledger.">
  <link rel="canonical" href="https://os.askforwrite.com/services">
  <meta property="og:title" content="AskforWrite AI Company OS — Clustered Subscriptions &amp; AI Services Catalog">
  <meta property="og:description" content="4 functional AI clusters, 5 transparent INR/USD subscription tiers with 20% annual discount, stackable add-ons, and ECDSA NIST P-256 audit verification.">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://os.askforwrite.com/services">
  <script type="application/ld+json">{json.dumps(schema_graph)}</script>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0b0f19; color: #f8fafc; margin: 0; padding: 0; line-height: 1.6; }}
    header, main, footer {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 2.2rem; margin-bottom: 8px; color: #ffffff; }}
    h2.section-title {{ font-size: 1.5rem; margin: 32px 0 8px; color: #e2e8f0; border-bottom: 1px solid #1e293b; padding-bottom: 8px; }}
    .section-sub {{ color: #94a3b8; margin: 0 0 18px; }}
    .clusters-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px; margin-bottom: 28px; }}
    .cluster-card {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 16px; }}
    .cluster-card h3 {{ margin: 8px 0 6px; font-size: 1.05rem; color: #f8fafc; }}
    .tiers-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(215px, 1fr)); gap: 16px; margin-bottom: 36px; }}
    .tier-card {{ background: #111827; border: 1px solid #1e293b; border-radius: 14px; padding: 18px; display: flex; flex-direction: column; justify-content: space-between; }}
    .tier-card.featured-tier {{ border-color: #6366f1; box-shadow: 0 0 0 1px rgba(99,102,241,0.45); background: linear-gradient(180deg, rgba(79,70,229,0.14), #111827); }}
    .tier-card h3 {{ margin: 10px 0 6px; font-size: 1.05rem; color: #ffffff; }}
    .tier-top {{ display: flex; justify-content: space-between; align-items: center; gap: 6px; flex-wrap: wrap; }}
    .cluster-pills {{ display: flex; gap: 4px; flex-wrap: wrap; }}
    .cluster-pill {{ font-size: 0.68rem; background: #1e293b; color: #cbd5e1; padding: 2px 6px; border-radius: 999px; }}
    .tier-price {{ font-size: 1.45rem; font-weight: 800; color: #34d399; margin: 10px 0 2px; }}
    .tier-price span {{ font-size: 0.82rem; font-weight: 500; color: #94a3b8; }}
    .tier-annual {{ font-size: 0.78rem; color: #a5b4fc; margin-bottom: 10px; }}
    .tier-cta {{ display: inline-block; text-align: center; background: #4f46e5; color: #ffffff; text-decoration: none; font-weight: 700; padding: 9px 12px; border-radius: 8px; margin-top: 12px; font-size: 0.85rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; margin-top: 20px; }}
    .service-card {{ background: #111827; border: 1px solid #1e293b; border-radius: 12px; padding: 20px; }}
    .service-card h2 a {{ color: #60a5fa; text-decoration: none; }}
    .badge {{ display: inline-block; font-size: 0.72rem; background: #1e3a8a; color: #93c5fd; padding: 2px 8px; border-radius: 999px; font-weight: 700; }}
    .desc {{ font-size: 0.9rem; color: #cbd5e1; }}
    .meta {{ font-size: 0.82rem; color: #94a3b8; }}
    .price-row {{ display: flex; justify-content: space-between; align-items: center; margin-top: 16px; padding-top: 12px; border-top: 1px solid #1e293b; }}
    .price {{ font-weight: 700; color: #34d399; }}
    .cta-link {{ color: #93c5fd; text-decoration: none; font-weight: 600; }}
    nav a, footer a {{ color: #94a3b8; margin-right: 16px; text-decoration: none; }}
  </style>
</head>
<body>
  <header>
    <nav>
      <a href="/dashboard/">Command Center</a>
      <a href="/services">All Services</a>
      <a href="/dashboard/#portal">Customer Portal</a>
      <a href="/llms.txt">LLMs.txt</a>
      <a href="/legal/tos">Terms</a>
      <a href="/legal/privacy">Privacy</a>
      <a href="/legal/refund-policy">Refund Policy</a>
    </nav>
    <h1>AskforWrite AI Company OS — Verified Service &amp; Capability Directory</h1>
    <p>Clustered Subscriptions &amp; Modular Tools: every capability is organized into 4 functional AI clusters across 5 transparent monthly INR/USD tiers (save 20% annually), backed by HITL governance and ECDSA NIST P-256 cryptographic audit logs.</p>
  </header>
  <main>
    <h2 class="section-title">1. The 4 Functional AI Capability Clusters</h2>
    <p class="section-sub">Related tools, specialist agents, and operational services grouped cleanly so teams only pay for the capabilities they need.</p>
    <section class="clusters-grid">
      {"".join(cluster_cards_html)}
    </section>

    <h2 class="section-title">2. Clustered Monthly &amp; Annual Subscription Plans</h2>
    <p class="section-sub">Start with a single cluster, bundle Growth or Operations, or unlock all 4 clusters with stackable add-on modules and 0%-commission AFW DirectPay checkout.</p>
    <section class="tiers-grid">
      {"".join(tier_cards_html)}
    </section>

    <h2 class="section-title">3. All Standalone Tools, Entry Packs &amp; Bundled SKUs ({len(packages)})</h2>
    <section class="grid">
      {"".join(cards_html)}
    </section>
  </main>
  <footer>
    <p>© 2026 ASKFORWRITE (MSME Udyam Registration: UDYAM-RJ-14-0018404) • Udaipur, Rajasthan, India - 313001 • <a href="mailto:info@askforwrite.in">info@askforwrite.in</a></p>
  </footer>
</body>
</html>"""
    return HTMLResponse(content=page_html, status_code=status.HTTP_200_OK)


@router.get("/services/{service_key}", response_class=HTMLResponse, include_in_schema=False)
def get_service_landing_page(service_key: str) -> HTMLResponse:
    """Render a dedicated, SEO/AEO/GEO-optimized HTML5 landing page for a specific catalog service."""
    clean_key = service_key.strip().lower()
    pkg = get_package(clean_key)
    if not pkg:
        from app.api.v1.solutions_pages import SOLUTION_SLUGS, solution_detail_page

        if clean_key in SOLUTION_SLUGS:
            return solution_detail_page(clean_key)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Service '{service_key}' not found in catalog")

    canonical_url = f"https://os.askforwrite.com/services/{pkg.key}"
    checkout_url = f"/v1/pay/checkout?package={pkg.key}"

    related_links = []
    for other in get_all_packages():
        if other.key != pkg.key and len(related_links) < 4:
            related_links.append(
                f'<li><a href="/services/{html.escape(other.key)}">{html.escape(other.name)} (₹{other.price_inr:,} / ${other.price_usd})</a></li>'
            )

    faqs = [
        {
            "q": f"Who is {pkg.name} designed for?",
            "a": f"{pkg.name} is built specifically for {pkg.target_buyer_persona} seeking to solve: {pkg.target_pain_point}",
        },
        {
            "q": f"What concrete deliverables do I receive with {pkg.name}?",
            "a": f"Customers receive: {'; '.join(pkg.deliverables)}. Monthly quotas include {pkg.lead_credits_monthly} discovery/service credits and {pkg.outreach_credits_monthly} outreach credits.",
        },
        {
            "q": f"How much does {pkg.name} cost and how is it activated?",
            "a": f"{pkg.name} is priced at ₹{pkg.price_inr:,} INR (${pkg.price_usd} USD). Upon verified payment via Razorpay, PayPal, or AFW DirectPay (UPI/USDC/Bank Wire), your tenant organization, admin account, and service entitlements are provisioned automatically.",
        },
    ]

    schema_graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "name": "AskforWrite",
                "legalName": "ASKFORWRITE",
                "identifier": "UDYAM-RJ-14-0018404",
                "url": "https://os.askforwrite.com",
            },
            {
                "@type": "Service",
                "name": pkg.name,
                "serviceType": pkg.category,
                "description": pkg.description,
                "provider": {"@type": "Organization", "name": "AskforWrite"},
                "url": canonical_url,
                "audience": {"@type": "BusinessAudience", "audienceType": pkg.target_buyer_persona},
                "offers": [
                    {
                        "@type": "Offer",
                        "price": str(pkg.price_inr),
                        "priceCurrency": "INR",
                        "availability": "https://schema.org/InStock",
                        "url": f"https://os.askforwrite.com{checkout_url}",
                    },
                    {
                        "@type": "Offer",
                        "price": str(pkg.price_usd),
                        "priceCurrency": "USD",
                        "availability": "https://schema.org/InStock",
                        "url": f"https://os.askforwrite.com{checkout_url}&currency=USD",
                    },
                ],
            },
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["q"],
                        "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
                    }
                    for item in faqs
                ],
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://os.askforwrite.com/dashboard/"},
                    {"@type": "ListItem", "position": 2, "name": "Services", "item": "https://os.askforwrite.com/services"},
                    {"@type": "ListItem", "position": 3, "name": pkg.name, "item": canonical_url},
                ],
            },
        ],
    }

    features_li = "".join(f"<li>{html.escape(f)}</li>" for f in pkg.key_features)
    deliverables_li = "".join(f"<li>{html.escape(d)}</li>" for d in pkg.deliverables)
    seo_geo_li = "".join(f"<li>{html.escape(s)}</li>" for s in pkg.seo_geo_aio_capabilities)
    faq_blocks = "".join(
        f"<div class='faq-item'><h3>{html.escape(item['q'])}</h3><p>{html.escape(item['a'])}</p></div>"
        for item in faqs
    )

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(pkg.name)} — Pricing, Deliverables &amp; AI Workflow | AskforWrite</title>
  <meta name="description" content="{html.escape(pkg.description[:155])}">
  <link rel="canonical" href="{canonical_url}">
  <meta property="og:title" content="{html.escape(pkg.name)} | AskforWrite AI Company OS">
  <meta property="og:description" content="{html.escape(pkg.description)}">
  <meta property="og:type" content="product">
  <meta property="og:url" content="{canonical_url}">
  <script type="application/ld+json">{json.dumps(schema_graph)}</script>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0b0f19; color: #f8fafc; margin: 0; padding: 0; line-height: 1.65; }}
    header, main, footer {{ max-width: 960px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 2.2rem; color: #ffffff; margin-bottom: 8px; }}
    h2 {{ font-size: 1.4rem; color: #93c5fd; margin-top: 28px; border-bottom: 1px solid #1e293b; padding-bottom: 6px; }}
    .card {{ background: #111827; border: 1px solid #1e293b; border-radius: 12px; padding: 20px; margin-top: 16px; }}
    .cta-btn {{ display: inline-block; background: #4f46e5; color: #ffffff; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 700; margin-right: 12px; }}
    .cta-secondary {{ display: inline-block; background: #1e293b; color: #e2e8f0; padding: 12px 20px; border-radius: 8px; text-decoration: none; font-weight: 600; }}
    nav a, footer a, ul a {{ color: #60a5fa; text-decoration: none; margin-right: 14px; }}
  </style>
</head>
<body>
  <header>
    <nav>
      <a href="/dashboard/">Home</a>
      <a href="/services">All Services</a>
      <a href="/dashboard/#portal">Customer Portal</a>
      <a href="/legal/tos">Terms</a>
      <a href="/legal/privacy">Privacy</a>
      <a href="/legal/refund-policy">Refunds</a>
    </nav>
    <p><small>SKU: <code>{html.escape(pkg.key)}</code> • Category: {html.escape(pkg.category)} • Tier: {html.escape(pkg.tier)}</small></p>
    <h1>{html.escape(pkg.name)}</h1>
    <p>{html.escape(pkg.description)}</p>
    <div class="card">
      <strong>Commercial Pricing:</strong> ₹{pkg.price_inr:,} INR / ${pkg.price_usd} USD
      &nbsp;|&nbsp; <strong>Included Quotas:</strong> {pkg.lead_credits_monthly} Service/Lead Credits &amp; {pkg.outreach_credits_monthly} Outreach Credits
      <div style="margin-top:16px;">
        <a class="cta-btn" href="{checkout_url}">Purchase &amp; Activate Instant Access →</a>
        <a class="cta-secondary" href="/dashboard/#portal">Sign In to Customer Portal</a>
      </div>
    </div>
  </header>
  <main>
    <section>
      <h2>Target Buyer Persona &amp; Operational Problem Solved</h2>
      <p><strong>Intended Buyer Persona:</strong> {html.escape(pkg.target_buyer_persona)}</p>
      <p><strong>Core Operational Problem Solved:</strong> {html.escape(pkg.target_pain_point)}</p>
    </section>
    <section>
      <h2>Key Capabilities &amp; Technical Workflow</h2>
      <ul>{features_li}</ul>
    </section>
    <section>
      <h2>Concrete Customer Deliverables &amp; Output Format</h2>
      <ul>{deliverables_li}</ul>
    </section>
    <section>
      <h2>SEO, AEO &amp; Generative Engine Optimization (GEO) Readiness</h2>
      <ul>{seo_geo_li}</ul>
    </section>
    <section>
      <h2>Governance, Dependencies &amp; Operational Safeguards</h2>
      <p>All executions are tenant-isolated, rate-limited by organizational credit quotas, and sealed into the AskforWrite ECDSA NIST P-256 cryptographic Merkle ledger. External outreach and manual bank/UPI settlements require explicit Owner Human-in-the-Loop (HITL) approval.</p>
    </section>
    <section>
      <h2>Frequently Asked Questions (FAQ)</h2>
      {faq_blocks}
    </section>
    <section>
      <h2>Related AskforWrite AI Services</h2>
      <ul>{"".join(related_links)}</ul>
    </section>
  </main>
  <footer>
    <p>© 2026 ASKFORWRITE (UDYAM-RJ-14-0018404) • <a href="/services">Back to All Services</a> • <a href="/llms.txt">AI Crawler Manifest (/llms.txt)</a></p>
  </footer>
</body>
</html>"""
    return HTMLResponse(content=page_html, status_code=status.HTTP_200_OK)
