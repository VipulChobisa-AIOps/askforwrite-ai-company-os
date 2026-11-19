"""Canonical SEO, AIO, GEO, Schema.org Entity Graph, Social Cards & SSR Homepage Helpers.

Single source of truth for:
- Unified Organization Schema (@id, UDYAM-RJ-14-0018404, sameAs cross-domain graph)
- Complete Open Graph (with 1200x630 PNG og:image) & Twitter/X Card tags
- Environment-gated Search Console / Bing verification tags (zero fake placeholders)
- Unified Browser + Search/AI Crawler detection (including OAI-SearchBot, ChatGPT-User, Google-Extended)
- Public SSR Commercial Homepage HTML5 renderer for GET /
- Branded HTML 404 renderer for browsers
"""

from __future__ import annotations

import html
import json
import os
from datetime import date
from typing import Any

from fastapi import Request

BASE_URL = "https://os.askforwrite.com"
OG_IMAGE_URL = f"{BASE_URL}/og-image.png"
FAVICON_URL = f"{BASE_URL}/favicon.ico"
LASTMOD_ISO = date.today().isoformat()

# Unified Organization Entity — identical across /, /services, /solutions, /legal, and /dashboard
CANONICAL_ORG_SCHEMA: dict[str, Any] = {
    "@type": "Organization",
    "@id": f"{BASE_URL}/#organization",
    "name": "AskforWrite",
    "alternateName": "AskforWrite AI Company OS",
    "legalName": "ASKFORWRITE",
    "identifier": "UDYAM-RJ-14-0018404",
    "url": BASE_URL,
    "logo": {
        "@type": "ImageObject",
        "url": OG_IMAGE_URL,
        "width": 1200,
        "height": 630,
    },
    "image": OG_IMAGE_URL,
    "email": "info@askforwrite.in",
    "founder": {
        "@type": "Person",
        "name": "Vipul Kumar Chobisa",
    },
    "address": {
        "@type": "PostalAddress",
        "addressLocality": "Udaipur",
        "addressRegion": "Rajasthan",
        "postalCode": "313001",
        "addressCountry": "IN",
    },
    "sameAs": [
        "https://askforwrite.com",
        "https://askforwrite.in",
        "https://github.com/VipulChobisa-AIOps",
    ],
}

BOT_AND_BROWSER_UA_TOKENS: tuple[str, ...] = (
    "mozilla",
    "googlebot",
    "google-extended",
    "google-inspectiontool",
    "bingbot",
    "gptbot",
    "oai-searchbot",
    "chatgpt-user",
    "perplexitybot",
    "perplexity-user",
    "claudebot",
    "claude-web",
    "anthropic-ai",
    "applebot",
    "meta-externalagent",
    "amazonbot",
    "duckduckbot",
    "yandex",
    "slurp",
    "askforwrite",
)


def is_browser_or_crawler(request: Request) -> bool:
    """Return True when the caller is a browser or search/AI crawler expecting HTML rather than raw API JSON."""
    accept = request.headers.get("accept", "").lower()
    ua = request.headers.get("user-agent", "").lower()
    wants_json = "application/json" in accept and "text/html" not in accept
    if wants_json:
        return False
    return "text/html" in accept or any(tok in ua for tok in BOT_AND_BROWSER_UA_TOKENS)


DEFAULT_GSC_VERIFICATION_TOKEN = "9Hq89c2XOt2-x9ww4QZeJgB2TAR_2Z8nBoPQd1DPRmc"


def verification_meta_tags() -> str:
    """Emit Google Search Console / Bing Webmaster verification tags (never fake placeholders)."""
    tags: list[str] = []
    gsc = os.environ.get("GOOGLE_SITE_VERIFICATION", DEFAULT_GSC_VERIFICATION_TOKEN).strip()
    if gsc and "verification-ready" not in gsc.lower():
        tags.append(f'<meta name="google-site-verification" content="{html.escape(gsc)}">')
    bing = os.environ.get("BING_SITE_VERIFICATION", "").strip()
    if bing and "verification-ready" not in bing.lower():
        tags.append(f'<meta name="msvalidate.01" content="{html.escape(bing)}">')
    return "\n  ".join(tags)


def social_meta_tags(
    *,
    title: str,
    description: str,
    canonical_url: str,
    og_type: str = "website",
    image_url: str = OG_IMAGE_URL,
) -> str:
    """Return complete Open Graph + Twitter/X Card + Favicon + Verification meta tags."""
    safe_t = html.escape(title)
    safe_d = html.escape(description)
    safe_u = html.escape(canonical_url)
    safe_img = html.escape(image_url)
    verif = verification_meta_tags()
    verif_line = f"\n  {verif}" if verif else ""
    return (
        f'<link rel="canonical" href="{safe_u}">\n'
        f'  <link rel="icon" href="{FAVICON_URL}" sizes="any">\n'
        f'  <link rel="icon" type="image/svg+xml" href="{BASE_URL}/dashboard/icon-192.svg">\n'
        f'  <meta property="og:site_name" content="AskforWrite AI Company OS">\n'
        f'  <meta property="og:title" content="{safe_t}">\n'
        f'  <meta property="og:description" content="{safe_d}">\n'
        f'  <meta property="og:type" content="{html.escape(og_type)}">\n'
        f'  <meta property="og:url" content="{safe_u}">\n'
        f'  <meta property="og:image" content="{safe_img}">\n'
        f'  <meta property="og:image:width" content="1200">\n'
        f'  <meta property="og:image:height" content="630">\n'
        f'  <meta property="og:image:alt" content="{safe_t}">\n'
        f'  <meta name="twitter:card" content="summary_large_image">\n'
        f'  <meta name="twitter:title" content="{safe_t}">\n'
        f'  <meta name="twitter:description" content="{safe_d}">\n'
        f'  <meta name="twitter:image" content="{safe_img}">{verif_line}'
    )


def clamp_meta(text: str, max_len: int = 155) -> str:
    """Trim meta descriptions cleanly at a word boundary without ugly mid-word cuts."""
    clean = " ".join(text.split())
    if len(clean) <= max_len:
        return clean
    clipped = clean[: max_len - 1].rsplit(" ", 1)[0].rstrip(".,;:-")
    return f"{clipped}…"


def build_short_title(name: str, suffix: str = " | AskforWrite", max_len: int = 60) -> str:
    """Keep HTML <title> strictly <= 60 chars to avoid Google SERP truncation."""
    clean = name.replace("AskforWrite ", "").strip()
    candidate = f"{clean}{suffix}"
    if len(candidate) <= max_len:
        return candidate
    budget = max_len - len(suffix)
    clipped = clean[:budget].rsplit(" ", 1)[0].rstrip("—-:, ")
    return f"{clipped}{suffix}"


def render_public_homepage_html() -> str:
    """Render the clean, crawlable, public SSR commercial homepage at https://os.askforwrite.com/."""
    from app.api.v1.solutions_pages import SOLUTION_SLUGS
    from app.services.catalog import CATALOG, MODULAR_SME_TIERS, PRICING_CLUSTERS

    title = "AskforWrite AI Company OS — Governed Multi-Agent Business OS"
    description = (
        "Autonomous multi-agent AI OS for SMBs: 4 capability clusters, 5 subscription plans "
        "(₹2,999–₹44,999/mo), HITL governance, BYOK privacy & ECDSA Trust Ledger."
    )

    faqs = [
        {
            "q": "What is AskforWrite AI Company OS?",
            "a": "AskforWrite AI Company OS is a governed multi-agent business operating system combining SEO/GEO content automation, 24/7 AI sales closing, Warehouse StockSense AI, Field Force GPS verification, Produce Quality Vision AI, Urban Mobility rebalancing, and ECDSA NIST P-256 cryptographic audit ledgers.",
        },
        {
            "q": "How are AskforWrite subscriptions clustered and priced?",
            "a": "All 16 tools are organized into 4 functional clusters across 5 monthly tiers with 20% annual savings: Launch (₹2,999/$39), Growth Suite (₹6,999/$89), Operations Suite (₹9,999/$129), Business Pro (₹17,999/$229), and Enterprise (₹44,999/$549), plus stackable modular add-ons and one-off entry packs.",
        },
        {
            "q": "How does AskforWrite enforce Human-in-the-Loop (HITL) and cryptographic governance?",
            "a": "External outreach, commercial proposals, and manual payment settlements require explicit Owner or Tenant Admin approval and are sealed into an immutable ECDSA NIST P-256 Merkle Trust Ledger.",
        },
        {
            "q": "Which payment rails does AFW DirectPay support and what are the gateway fees?",
            "a": "AFW DirectPay settles directly with 0% gateway commission via ISO-compliant Instant UPI QR (GPay, PhonePe, Paytm, BHIM in INR), Web3 USDC on Polygon, Base, and Solana, and Direct Bank Wire (NEFT/RTGS/IMPS/SWIFT) alongside Razorpay and PayPal.",
        },
        {
            "q": "How does Strict Bring-Your-Own-Key (BYOK) Gemini isolation protect tenant data?",
            "a": "Each organization is isolated by org_id with role-based access control and BYOK Gemini API keys stored encrypted, masked in API responses, never shared across tenants, and never used to train external AI models.",
        },
        {
            "q": "Can teams run AskforWrite workflows via both Web Portal and REST API?",
            "a": "Yes. Every subscribed organization receives entitlement-driven workspace dashboards inside os.askforwrite.com/dashboard/ plus authenticated Bearer-token execution via POST /v1/me/use-service.",
        },
    ]

    schema_graph = {
        "@context": "https://schema.org",
        "@graph": [
            CANONICAL_ORG_SCHEMA,
            {
                "@type": "WebSite",
                "@id": f"{BASE_URL}/#website",
                "url": f"{BASE_URL}/",
                "name": "AskforWrite AI Company OS",
                "publisher": {"@id": f"{BASE_URL}/#organization"},
                "inLanguage": "en",
            },
            {
                "@type": "SoftwareApplication",
                "@id": f"{BASE_URL}/#software",
                "name": "AskforWrite AI Company OS",
                "applicationCategory": "BusinessApplication",
                "operatingSystem": "Web, Cloud, Android PWA, REST API",
                "url": f"{BASE_URL}/",
                "image": OG_IMAGE_URL,
                "publisher": {"@id": f"{BASE_URL}/#organization"},
                "offers": {
                    "@type": "AggregateOffer",
                    "lowPrice": "999",
                    "highPrice": "44999",
                    "priceCurrency": "INR",
                    "offerCount": str(len(CATALOG)),
                    "url": f"{BASE_URL}/services",
                },
            },
            {
                "@type": "FAQPage",
                "@id": f"{BASE_URL}/#faq",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["q"],
                        "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
                    }
                    for item in faqs
                ],
            },
        ],
    }

    cluster_cards = []
    for cl in sorted(PRICING_CLUSTERS.values(), key=lambda x: int(x.get("cluster_number", 0))):
        svcs = ", ".join(str(s) for s in cl.get("services", []))
        cluster_cards.append(
            f"""
            <article class="card">
              <span class="badge">CLUSTER {int(cl.get('cluster_number', 1))}</span>
              <h3>{html.escape(str(cl.get('name', '')))}</h3>
              <p>{html.escape(str(cl.get('tagline', '')))}</p>
              <p class="meta"><strong>Included tools:</strong> <code>{html.escape(svcs)}</code></p>
            </article>
            """
        )

    tier_sku_map = {
        "launch": "company_os_starter",
        "growth": "growth_all_in_one",
        "operations": "operations_suite",
        "business_pro": "company_os_pro",
        "enterprise": "company_os_enterprise",
    }
    tier_cards = []
    for t_key, tier in MODULAR_SME_TIERS.items():
        bp = tier.get("base_price", {})
        ap = tier.get("annual_price", {})
        cr = tier.get("included_credits", {})
        checkout_sku = tier_sku_map.get(t_key, t_key)
        featured = " featured" if t_key == "growth" else ""
        tier_cards.append(
            f"""
            <article class="card{featured}">
              <span class="badge">{html.escape(t_key.replace('_', ' ').upper())}</span>
              <h3>{html.escape(str(tier.get('name', t_key)))}</h3>
              <p class="meta">{html.escape(str(tier.get('target_sme', '')))}</p>
              <div class="price">₹{int(bp.get('inr', 0)):,}<span>/mo · ${int(bp.get('usd', 0))} USD</span></div>
              <div class="annual">Annual (-20%): ₹{int(ap.get('inr', 0)):,}/mo (${int(ap.get('usd', 0))}/mo)</div>
              <p class="meta">{int(tier.get('agent_limit', 2))} Agents · {int(tier.get('seat_limit', 2))} Seats · {int(cr.get('lead_credits', 50)):,} Leads · {int(cr.get('ai_execution_credits', 150)):,} AI Runs</p>
              <div class="actions">
                <a class="btn-primary" href="/v1/pay/checkout?package={html.escape(checkout_sku)}">Activate Plan →</a>
                <a class="btn-secondary" href="/services/{html.escape(checkout_sku)}">Full Specs</a>
              </div>
            </article>
            """
        )

    solution_links = "".join(
        f'<li><a href="/solutions/{html.escape(slug)}"><strong>{html.escape(info["headline"])}</strong></a> — {html.escape(info["subheadline"])}</li>'
        for slug, info in SOLUTION_SLUGS.items()
    )

    faq_html = "".join(
        f'<div class="faq-item"><h3>{html.escape(item["q"])}</h3><p>{html.escape(item["a"])}</p></div>'
        for item in faqs
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <meta name="description" content="{html.escape(description)}">
  {social_meta_tags(title=title, description=description, canonical_url=f"{BASE_URL}/")}
  <script type="application/ld+json">{json.dumps(schema_graph)}</script>
  <style>
    :root {{ --bg:#0b0f19; --card:#111827; --border:#1e293b; --text:#f8fafc; --muted:#94a3b8; --accent:#4f46e5; --cyan:#38bdf8; --green:#34d399; }}
    * {{ box-sizing:border-box; }}
    body {{ font-family: system-ui,-apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--text); margin:0; line-height:1.65; }}
    header, main, footer {{ max-width:1180px; margin:0 auto; padding:24px; }}
    nav {{ display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:14px; padding-bottom:20px; border-bottom:1px solid var(--border); }}
    .brand {{ font-weight:800; font-size:1.1rem; color:#fff; text-decoration:none; letter-spacing:0.02em; }}
    .nav-links {{ display:flex; flex-wrap:wrap; gap:16px; align-items:center; }}
    .nav-links a {{ color:#cbd5e1; text-decoration:none; font-size:0.92rem; font-weight:500; }}
    .nav-links a:hover {{ color:var(--cyan); }}
    .hero {{ padding:40px 0 28px; }}
    .hero h1 {{ font-size:clamp(1.9rem,4vw,2.75rem); line-height:1.18; margin:12px 0 14px; color:#fff; }}
    .hero p {{ max-width:820px; font-size:1.08rem; color:#cbd5e1; }}
    .hero-cta {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:24px; }}
    .btn-primary {{ display:inline-block; background:var(--accent); color:#fff; padding:11px 20px; border-radius:8px; text-decoration:none; font-weight:700; font-size:0.92rem; }}
    .btn-secondary {{ display:inline-block; background:#1e293b; color:#e2e8f0; padding:11px 18px; border-radius:8px; text-decoration:none; font-weight:600; font-size:0.92rem; border:1px solid #334155; }}
    h2 {{ font-size:1.55rem; margin:38px 0 10px; color:#fff; border-bottom:1px solid var(--border); padding-bottom:8px; }}
    .grid-4 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:16px; margin-top:16px; }}
    .grid-5 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(215px,1fr)); gap:16px; margin-top:16px; }}
    .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:18px; display:flex; flex-direction:column; justify-content:space-between; }}
    .card.featured {{ border-color:#6366f1; background:linear-gradient(180deg,rgba(79,70,229,0.16),var(--card)); }}
    .card h3 {{ margin:10px 0 6px; font-size:1.05rem; color:#fff; }}
    .badge {{ display:inline-block; font-size:0.72rem; font-weight:700; background:#1e3a8a; color:#93c5fd; padding:2px 9px; border-radius:999px; letter-spacing:0.04em; width:fit-content; }}
    .price {{ font-size:1.45rem; font-weight:800; color:var(--green); margin:10px 0 2px; }}
    .price span {{ font-size:0.82rem; font-weight:500; color:var(--muted); }}
    .annual {{ font-size:0.78rem; color:#a5b4fc; margin-bottom:8px; }}
    .meta {{ font-size:0.84rem; color:var(--muted); }}
    .actions {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }}
    .actions .btn-primary, .actions .btn-secondary {{ padding:8px 12px; font-size:0.82rem; }}
    .trust-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; margin-top:16px; }}
    ul.sol-list {{ padding-left:20px; }}
    ul.sol-list li {{ margin-bottom:10px; color:#cbd5e1; }}
    ul.sol-list a {{ color:var(--cyan); text-decoration:none; }}
    .faq-item {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px 20px; margin-top:12px; }}
    .faq-item h3 {{ margin:0 0 6px; font-size:1.02rem; color:#93c5fd; }}
    .faq-item p {{ margin:0; color:#cbd5e1; font-size:0.93rem; }}
    footer {{ border-top:1px solid var(--border); margin-top:40px; color:var(--muted); font-size:0.86rem; }}
    footer a {{ color:#93c5fd; text-decoration:none; margin-right:14px; }}
  </style>
</head>
<body>
  <header>
    <nav aria-label="Primary Navigation">
      <a class="brand" href="/">AskforWrite AI Company OS</a>
      <div class="nav-links">
        <a href="/services">Pricing &amp; Services</a>
        <a href="/solutions">Vertical AI Solutions</a>
        <a href="/dashboard/">Launch Workspace</a>
        <a href="/dashboard/#portal">Customer Portal</a>
        <a href="/llms.txt">LLMs.txt</a>
        <a href="https://askforwrite.com">AskforWrite.com</a>
      </div>
    </nav>
    <div class="hero">
      <span class="badge">MULTI-AGENT BUSINESS OPERATING SYSTEM · MSME UDYAM-RJ-14-0018404</span>
      <h1>AskforWrite AI Company OS — Autonomous Multi-Agent Business Operating System</h1>
      <p>Replace fragmented marketing agencies, manual SDR outreach, spreadsheets, and unaudited AI scripts with one governed operating system. Built with 4 modular AI capability clusters, Human-in-the-Loop (HITL) approval controls, Strict BYOK Gemini isolation, 0%-fee AFW DirectPay settlements, and an ECDSA NIST P-256 cryptographic Trust Ledger.</p>
      <div class="hero-cta">
        <a class="btn-primary" href="/dashboard/">Open Command Center &amp; Customer Portal →</a>
        <a class="btn-secondary" href="/services">Compare Clustered Subscriptions</a>
        <a class="btn-secondary" href="/solutions">Explore Vertical AI Solutions</a>
      </div>
    </div>
  </header>

  <main>
    <section>
      <h2>4 Functional AI Capability Clusters</h2>
      <p class="meta">Related specialist agents, workflows, and vertical AI engines grouped into four clean capability pillars.</p>
      <div class="grid-4">{"".join(cluster_cards)}</div>
    </section>

    <section>
      <h2>Transparent Clustered Subscription Pricing (INR &amp; USD)</h2>
      <p class="meta">Start with one cluster or run your entire company on all four. Save 20% on annual billing, add stackable modular add-ons anytime, or start with a 14-day Done-For-You SEO Pilot (₹4,999 / $59).</p>
      <div class="grid-5">{"".join(tier_cards)}</div>
    </section>

    <section>
      <h2>Vertical AI Operating Systems Built for Real Operations</h2>
      <p class="meta">Dedicated production-verified AI suites connecting live operational telemetry to deterministic optimization and tamper-evident audit proofs:</p>
      <ul class="sol-list">{solution_links}</ul>
    </section>

    <section>
      <h2>Enterprise Governance, Security &amp; Direct Settlement Architecture</h2>
      <div class="trust-grid">
        <div class="card"><h3>Human-in-the-Loop (HITL) Gates</h3><p class="meta">Every external outreach email, commercial proposal, and manual payment verification requires explicit Owner or Tenant Admin approval before execution.</p></div>
        <div class="card"><h3>ECDSA NIST P-256 Trust Ledger</h3><p class="meta">Every workflow execution, quality inspection, and payment receipt is hashed and cryptographically sealed into a tamper-evident Merkle chain.</p></div>
        <div class="card"><h3>Strict BYOK Gemini Isolation</h3><p class="meta">Tenants supply their own Gemini API keys—stored encrypted, masked in responses, isolated per organization, and zero markup on LLM tokens.</p></div>
        <div class="card"><h3>0%-Fee AFW DirectPay</h3><p class="meta">Accept Instant ISO UPI QR (GPay, PhonePe, Paytm, BHIM), Web3 USDC (Polygon/Base/Solana), and Bank Wire alongside Razorpay &amp; PayPal.</p></div>
      </div>
    </section>

    <section>
      <h2>Frequently Asked Questions</h2>
      {faq_html}
    </section>
  </main>

  <footer>
    <p>
      <a href="/services">All 16 Services</a>
      <a href="/solutions">Vertical Solutions</a>
      <a href="/legal/tos">Terms of Service</a>
      <a href="/legal/privacy">Privacy Policy</a>
      <a href="/legal/refund-policy">Refund Policy</a>
      <a href="/legal/declaration">MSME Declaration</a>
      <a href="/llms.txt">LLMs.txt</a>
      <a href="/llms-full.txt">LLMs-Full.txt</a>
      <a href="/sitemap.xml">Sitemap</a>
    </p>
    <p>© 2026 ASKFORWRITE (Proprietor: Vipul Kumar Chobisa · MSME Udyam Registration: UDYAM-RJ-14-0018404) • Udaipur, Rajasthan, India - 313001 • <a href="mailto:info@askforwrite.in">info@askforwrite.in</a></p>
  </footer>
</body>
</html>"""


def render_404_html(path: str) -> str:
    """Render a clean branded HTML 404 page with navigation links for human visitors."""
    safe_path = html.escape(path)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Page Not Found (404) | AskforWrite AI Company OS</title>
  <meta name="robots" content="noindex, follow">
  <link rel="icon" href="{FAVICON_URL}">
  <style>
    body {{ font-family:system-ui,-apple-system,sans-serif; background:#0b0f19; color:#f8fafc; margin:0; display:flex; min-height:100vh; align-items:center; justify-content:center; padding:24px; }}
    .box {{ max-width:560px; background:#111827; border:1px solid #1e293b; border-radius:14px; padding:32px; text-align:center; }}
    h1 {{ font-size:2rem; margin:0 0 8px; color:#fff; }}
    p {{ color:#94a3b8; margin:0 0 22px; }}
    .links {{ display:flex; flex-wrap:wrap; gap:10px; justify-content:center; }}
    a {{ background:#1e293b; color:#e2e8f0; padding:10px 16px; border-radius:8px; text-decoration:none; font-weight:600; font-size:0.9rem; }}
    a.primary {{ background:#4f46e5; color:#fff; }}
  </style>
</head>
<body>
  <div class="box">
    <h1>404 — Page Not Found</h1>
    <p>The URL <code>{safe_path}</code> does not exist on AskforWrite AI Company OS.</p>
    <div class="links">
      <a class="primary" href="/">Go to Homepage</a>
      <a href="/services">Browse Services &amp; Pricing</a>
      <a href="/solutions">Vertical AI Solutions</a>
      <a href="/dashboard/">Open Dashboard</a>
    </div>
  </div>
</body>
</html>"""
