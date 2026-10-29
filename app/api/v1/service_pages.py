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

from app.services.catalog import CATALOG, get_all_packages, get_package

router = APIRouter(tags=["seo-service-pages"])


@router.get("/services", response_class=HTMLResponse, include_in_schema=False)
def list_service_landing_pages() -> HTMLResponse:
    """Render an indexable HTML5 directory of all 14 AskforWrite AI Company OS services."""
    packages = get_all_packages()
    item_list_elements = []
    cards_html = []

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
        ],
    }

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Business Services &amp; Modular Automation Catalog | AskforWrite Company OS</title>
  <meta name="description" content="Explore all 14 verified AI services from AskforWrite Company OS: Warehouse StockSense AI, Field Force GPS Automation, Produce Quality Vision AI, Urban Mobility Forecasting, SEO/GEO Blog Copilot, and Cryptographic Trust Ledgers.">
  <link rel="canonical" href="https://os.askforwrite.com/services">
  <meta property="og:title" content="AskforWrite AI Company OS — Verified AI Services &amp; Pricing Catalog">
  <meta property="og:description" content="Governed multi-agent AI services with transparent INR/USD pricing, concrete deliverables, and ECDSA NIST P-256 audit verification.">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://os.askforwrite.com/services">
  <script type="application/ld+json">{json.dumps(schema_graph)}</script>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0b0f19; color: #f8fafc; margin: 0; padding: 0; line-height: 1.6; }}
    header, main, footer {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 2.2rem; margin-bottom: 8px; color: #ffffff; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; margin-top: 24px; }}
    .service-card {{ background: #111827; border: 1px solid #1e293b; border-radius: 12px; padding: 20px; }}
    .service-card h2 a {{ color: #60a5fa; text-decoration: none; }}
    .badge {{ display: inline-block; font-size: 0.75rem; background: #1e3a8a; color: #93c5fd; padding: 2px 8px; border-radius: 999px; }}
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
    <p>Every service listed below is backed by a verified execution engine, transparent INR/USD pricing, Human-in-the-Loop (HITL) governance, and ECDSA NIST P-256 cryptographic audit logs.</p>
  </header>
  <main>
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
    pkg = get_package(service_key.strip().lower())
    if not pkg:
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
