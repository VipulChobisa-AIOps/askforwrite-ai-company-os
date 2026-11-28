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
    """Render the interactive, visual, crawlable public SSR AI product & sales homepage for os.askforwrite.com & os.askforwrite.in."""
    from app.api.v1.solutions_pages import SOLUTION_SLUGS
    from app.services.catalog import CATALOG, MODULAR_SME_TIERS, PRICING_CLUSTERS
    from app.services.media_showcase import (
        CUSTOMER_JOURNEY_STEPS,
        DEMO_VIDEOS,
        SYSTEM_SCREENSHOTS,
        get_screenshot_for_sku,
    )

    title = "AskforWrite AI Company OS — Governed Multi-Agent Business OS"
    description = (
        "Interactive multi-agent AI OS for SMBs: real customer portal, 4 capability clusters, "
        "5 plans (₹2,999–₹44,999/mo), HITL governance & ECDSA Trust Ledger."
    )

    faqs = [
        {
            "q": "What is AskforWrite AI Company OS and how do customers operate it?",
            "a": "AskforWrite AI Company OS is a governed multi-agent business operating system combining a self-service Customer Portal, SEO/GEO content automation, 24/7 AI sales closing, Warehouse StockSense AI, Field Force GPS verification, Produce Quality Vision AI, Urban Mobility rebalancing, and ECDSA NIST P-256 cryptographic audit ledgers. Customers sign in to their isolated portal, run entitled AI agents or review staged drafts, approve work with 1 click, and verify TrustBlock receipts.",
        },
        {
            "q": "How are AskforWrite subscriptions clustered and priced?",
            "a": "All 16 tools are organized into 4 functional clusters across 5 monthly tiers with 20% annual savings: Launch (₹2,999/$39), Growth Suite (₹6,999/$89), Operations Suite (₹9,999/$129), Business Pro (₹17,999/$229), and Enterprise (₹44,999/$549), plus a 14-day Done-For-You Managed SEO & Content Pilot (₹4,999/$59 one-time).",
        },
        {
            "q": "How does AskforWrite enforce Human-in-the-Loop (HITL) and cryptographic governance?",
            "a": "External outreach emails, WordPress live publications, commercial proposals, and manual payment settlements pause in the Approvals queue until the Owner or Tenant Admin clicks Approve. Every decision is sealed into an immutable ECDSA NIST P-256 Merkle Trust Ledger.",
        },
        {
            "q": "Which payment rails does AFW DirectPay support and what are the gateway fees?",
            "a": "AFW DirectPay charges 0% AskforWrite platform commission on Instant ISO UPI QR (GPay, PhonePe, Paytm, BHIM in INR) and Direct Bank Wire (NEFT/RTGS/IMPS/SWIFT), alongside Razorpay (INR) and PayPal (USD).",
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
                "screenshot": [f"{BASE_URL}{s['src']}" for s in SYSTEM_SCREENSHOTS[:4]],
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
                "@type": "VideoObject",
                "@id": f"{BASE_URL}/#customer-demo-video",
                "name": DEMO_VIDEOS[0]["title"],
                "description": DEMO_VIDEOS[0]["summary"],
                "thumbnailUrl": f"{BASE_URL}{DEMO_VIDEOS[0]['poster']}",
                "uploadDate": f"{LASTMOD_ISO}T00:00:00+00:00",
                "contentUrl": f"{BASE_URL}{DEMO_VIDEOS[0]['webm']}",
                "embedUrl": f"{BASE_URL}/#demo",
                "publisher": {"@id": f"{BASE_URL}/#organization"},
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

    # Hero quick-preview screens (top 4 most impactful customer & governance views)
    hero_screens = [
        SYSTEM_SCREENSHOTS[0],  # Customer Portal
        SYSTEM_SCREENSHOTS[2],  # Command Center
        SYSTEM_SCREENSHOTS[3],  # HITL Approvals
        SYSTEM_SCREENSHOTS[6],  # Trust Ledger
    ]
    hero_tabs_html = "".join(
        f'<button type="button" class="hero-tab{" active" if i == 0 else ""}" data-hero-idx="{i}">{html.escape(s["badge"])}</button>'
        for i, s in enumerate(hero_screens)
    )

    # Video chapters
    video_cards_html = "".join(
        f"""
        <button type="button" class="video-chapter-btn{" active" if i == 0 else ""}" data-video-idx="{i}">
          <div class="vc-top">
            <span class="badge-soft">{html.escape(v["badge"])}</span>
            <span class="vc-dur">{html.escape(v["duration"])}</span>
          </div>
          <strong>{html.escape(v["title"])}</strong>
          <p>{html.escape(v["summary"])}</p>
        </button>
        """
        for i, v in enumerate(DEMO_VIDEOS)
    )

    # Interactive 5-step customer journey stepper
    journey_tabs_html = "".join(
        f"""
        <button type="button" class="journey-step-btn{" active" if i == 0 else ""}" data-step-idx="{i}">
          <span class="step-num">{html.escape(st["step"])}</span>
          <span class="step-name">{html.escape(st["short_title"])}</span>
        </button>
        """
        for i, st in enumerate(CUSTOMER_JOURNEY_STEPS)
    )
    first_step = CUSTOMER_JOURNEY_STEPS[0]

    # Full 8-screen gallery cards
    gallery_cards_html = "".join(
        f"""
        <article class="shot-card" data-category="{html.escape(s["category"])}" data-shot-idx="{i}">
          <div class="shot-chrome">
            <span class="dot red"></span><span class="dot amber"></span><span class="dot green"></span>
            <span class="shot-url">os.askforwrite.com · {html.escape(s["badge"])}</span>
            <button type="button" class="shot-zoom-btn" data-open-lightbox="{i}" aria-label="Zoom {html.escape(s['title'])}">⤢ Zoom</button>
          </div>
          <div class="shot-img-wrap" data-open-lightbox="{i}">
            <img src="{html.escape(s["src"])}" alt="{html.escape(s["title"])}" loading="lazy" width="1280" height="800" />
            <div class="shot-hover-pill">Click to inspect full screen</div>
          </div>
          <div class="shot-body">
            <span class="badge-soft">{html.escape(s["badge"])}</span>
            <h3>{html.escape(s["title"])}</h3>
            <p>{html.escape(s["caption"])}</p>
            <a class="shot-link" href="{html.escape(s["cta_href"])}">{html.escape(s["cta_label"])} →</a>
          </div>
        </article>
        """
        for i, s in enumerate(SYSTEM_SCREENSHOTS)
    )

    cluster_cards = []
    for cl in sorted(PRICING_CLUSTERS.values(), key=lambda x: int(x.get("cluster_number", 0))):
        svcs = ", ".join(str(s) for s in cl.get("services", []))
        cluster_cards.append(
            f"""
            <article class="card cluster-glass">
              <div>
                <span class="badge">CLUSTER {int(cl.get('cluster_number', 1))}</span>
                <h3>{html.escape(str(cl.get('name', '')))}</h3>
                <p class="desc">{html.escape(str(cl.get('tagline', '')))}</p>
              </div>
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
        popular_tag = '<span class="popular-pill">MOST POPULAR</span>' if t_key == "growth" else ""
        m_inr = int(bp.get("inr", 0))
        m_usd = int(bp.get("usd", 0))
        a_inr = int(ap.get("inr", 0))
        a_usd = int(ap.get("usd", 0))
        tier_cards.append(
            f"""
            <article class="card pricing-card{featured}" data-m-inr="{m_inr}" data-m-usd="{m_usd}" data-a-inr="{a_inr}" data-a-usd="{a_usd}">
              <div>
                <div class="tier-head">
                  <span class="badge">{html.escape(t_key.replace('_', ' ').upper())}</span>
                  {popular_tag}
                </div>
                <h3>{html.escape(str(tier.get('name', t_key)))}</h3>
                <p class="meta">{html.escape(str(tier.get('target_sme', '')))}</p>
                <div class="price-display">
                  <span class="price-main">₹{m_inr:,}</span><span class="price-unit">/mo</span>
                </div>
                <div class="annual-sub">Annual (-20%): ₹{a_inr:,}/mo · ${a_usd} USD/mo</div>
                <ul class="tier-specs">
                  <li><strong>{int(tier.get('agent_limit', 2))}</strong> AI Agents · <strong>{int(tier.get('seat_limit', 2))}</strong> Team Seats</li>
                  <li><strong>{int(cr.get('lead_credits', 50)):,}</strong> Leads · <strong>{int(cr.get('ai_execution_credits', 150)):,}</strong> AI Runs/mo</li>
                  <li>BYOK Gemini + ECDSA Trust Ledger</li>
                </ul>
              </div>
              <div class="actions">
                <a class="btn-primary full" rel="nofollow" href="/v1/pay/checkout?package={html.escape(checkout_sku)}">Activate Plan →</a>
                <a class="btn-secondary full" href="/services/{html.escape(checkout_sku)}">View Specs &amp; Demo</a>
              </div>
            </article>
            """
        )

    solution_cards_html = ""
    for slug, info in SOLUTION_SLUGS.items():
        sku_key = info.get("sku_id") or info["sku"]
        pkg = CATALOG.get(sku_key)
        p_inr = pkg.price_inr if pkg else 3999
        p_usd = pkg.price_usd if pkg else 49
        shot = get_screenshot_for_sku(sku_key)
        solution_cards_html += f"""
        <article class="card sol-card">
          <div class="sol-thumb">
            <img src="{html.escape(shot['src'])}" alt="{html.escape(info['headline'])}" loading="lazy" width="640" height="400" />
          </div>
          <div class="sol-body">
            <span class="badge-soft">{html.escape(info['hero_badge'])}</span>
            <h3><a href="/solutions/{html.escape(slug)}">{html.escape(info['headline'])}</a></h3>
            <p class="meta">{html.escape(info['subheadline'])}</p>
            <div class="sol-foot">
              <span class="sol-price">₹{p_inr:,}/mo <small>(${p_usd})</small></span>
              <a class="shot-link" href="/solutions/{html.escape(slug)}">Explore Solution →</a>
            </div>
          </div>
        </article>
        """

    faq_html = "".join(
        f"""
        <details class="faq-item"{' open' if idx == 0 else ''}>
          <summary>{html.escape(item["q"])}</summary>
          <p>{html.escape(item["a"])}</p>
        </details>
        """
        for idx, item in enumerate(faqs)
    )

    hero_screens_json = json.dumps(hero_screens).replace("</", "<\\/")
    videos_json = json.dumps(DEMO_VIDEOS).replace("</", "<\\/")
    steps_json = json.dumps(CUSTOMER_JOURNEY_STEPS).replace("</", "<\\/")
    shots_json = json.dumps(SYSTEM_SCREENSHOTS).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <meta name="description" content="{html.escape(description)}">
  {social_meta_tags(title=title, description=description, canonical_url=f"{BASE_URL}/")}
  <script type="application/ld+json">{json.dumps(schema_graph)}</script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg:#060913; --bg2:#0b1120; --card:#0f172a; --card2:#111c33;
      --border:rgba(148,163,184,0.16); --border-hi:rgba(99,102,241,0.52);
      --text:#f8fafc; --muted:#94a3b8; --soft:#cbd5e1;
      --indigo:#6366f1; --indigo-dark:#4f46e5; --cyan:#38bdf8; --emerald:#34d399;
    }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{
      font-family:'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
      background:
        radial-gradient(900px 520px at 12% -6%, rgba(79,70,229,0.22), transparent 60%),
        radial-gradient(760px 480px at 88% 4%, rgba(14,165,233,0.16), transparent 55%),
        var(--bg);
      color:var(--text); margin:0; line-height:1.62; overflow-x:hidden;
    }}
    h1,h2,h3,.brand {{ font-family:'Plus Jakarta Sans','Inter',system-ui,sans-serif; letter-spacing:-0.02em; }}
    code {{ font-family:'JetBrains Mono',ui-monospace,monospace; font-size:0.82em; background:rgba(15,23,42,0.9); padding:2px 6px; border-radius:5px; color:#93c5fd; }}
    .wrap {{ max-width:1220px; margin:0 auto; padding:0 22px; }}

    /* Sticky Glass Navbar */
    .topbar {{
      position:sticky; top:0; z-index:80;
      background:rgba(6,9,19,0.82); backdrop-filter:blur(14px);
      border-bottom:1px solid var(--border);
    }}
    .nav-inner {{ display:flex; align-items:center; justify-content:space-between; gap:14px; padding:14px 0; flex-wrap:wrap; }}
    .brand {{ display:inline-flex; align-items:center; gap:10px; font-weight:800; font-size:1.05rem; color:#fff; text-decoration:none; }}
    .brand-mark {{
      width:30px; height:30px; border-radius:8px;
      background:linear-gradient(135deg,#4f46e5,#06b6d4);
      display:inline-flex; align-items:center; justify-content:center;
      box-shadow:0 6px 20px rgba(79,70,229,0.4);
    }}
    .nav-links {{ display:flex; flex-wrap:wrap; gap:18px; align-items:center; }}
    .nav-links a {{ color:var(--soft); text-decoration:none; font-size:0.88rem; font-weight:600; transition:color 0.15s; }}
    .nav-links a:hover {{ color:var(--cyan); }}
    .nav-cta {{
      background:linear-gradient(135deg,#4f46e5,#0ea5e9); color:#fff !important;
      padding:8px 15px; border-radius:9px; font-weight:700 !important;
      box-shadow:0 8px 22px rgba(79,70,229,0.32);
    }}

    /* Buttons & Badges */
    .badge {{
      display:inline-flex; align-items:center; gap:7px; font-size:0.72rem; font-weight:800;
      background:rgba(79,70,229,0.18); border:1px solid rgba(99,102,241,0.42);
      color:#c7d2fe; padding:4px 11px; border-radius:999px; letter-spacing:0.05em; width:fit-content;
    }}
    .badge-soft {{
      display:inline-block; font-size:0.7rem; font-weight:700; letter-spacing:0.06em;
      background:rgba(56,189,248,0.13); color:var(--cyan); padding:3px 9px; border-radius:999px;
    }}
    .pulse-dot {{ width:8px; height:8px; border-radius:50%; background:var(--emerald); box-shadow:0 0 0 4px rgba(52,211,153,0.22); }}
    .btn-primary {{
      display:inline-flex; align-items:center; justify-content:center; gap:8px;
      background:linear-gradient(135deg,#4f46e5,#6366f1); color:#fff;
      padding:12px 20px; border-radius:10px; text-decoration:none; font-weight:700;
      font-size:0.92rem; border:1px solid rgba(129,140,248,0.4); cursor:pointer;
      box-shadow:0 10px 26px rgba(79,70,229,0.32); transition:transform 0.15s, filter 0.15s;
    }}
    .btn-primary:hover {{ transform:translateY(-1px); filter:brightness(1.08); }}
    .btn-secondary {{
      display:inline-flex; align-items:center; justify-content:center; gap:8px;
      background:rgba(30,41,59,0.82); color:#e2e8f0; padding:12px 18px; border-radius:10px;
      text-decoration:none; font-weight:600; font-size:0.92rem;
      border:1px solid rgba(148,163,184,0.26); cursor:pointer; transition:border-color 0.15s, background 0.15s;
    }}
    .btn-secondary:hover {{ border-color:var(--cyan); background:rgba(30,41,59,1); }}
    .btn-primary.full, .btn-secondary.full {{ width:100%; padding:10px 14px; font-size:0.84rem; }}

    /* Split Hero */
    .hero {{ padding:52px 0 42px; display:grid; grid-template-columns:1.03fr 1.07fr; gap:36px; align-items:center; }}
    .hero h1 {{ font-size:clamp(2rem,3.6vw,3.05rem); line-height:1.12; margin:14px 0 16px; color:#fff; }}
    .grad-text {{ background:linear-gradient(95deg,#fff 20%,#38bdf8 65%,#a5b4fc 100%); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }}
    .hero-sub {{ font-size:1.03rem; color:var(--soft); margin:0 0 22px; max-width:580px; }}
    .hero-cta {{ display:flex; flex-wrap:wrap; gap:11px; margin-bottom:24px; }}
    .proof-strip {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }}
    .proof-box {{ background:rgba(15,23,42,0.75); border:1px solid var(--border); border-radius:11px; padding:11px 12px; }}
    .proof-box strong {{ display:block; font-size:0.95rem; color:#fff; }}
    .proof-box span {{ font-size:0.76rem; color:var(--muted); }}

    /* Browser Showcase Frame in Hero */
    .browser-frame {{
      background:#070c18; border:1px solid rgba(99,102,241,0.38); border-radius:16px;
      overflow:hidden; box-shadow:0 28px 70px rgba(0,0,0,0.6), 0 0 0 1px rgba(56,189,248,0.14);
    }}
    .browser-bar {{
      display:flex; align-items:center; justify-content:space-between; gap:10px;
      padding:10px 14px; background:#0d1526; border-bottom:1px solid var(--border); flex-wrap:wrap;
    }}
    .dots {{ display:flex; gap:6px; align-items:center; }}
    .dot {{ width:9px; height:9px; border-radius:50%; display:inline-block; }}
    .dot.red {{ background:#ef4444; }} .dot.amber {{ background:#f59e0b; }} .dot.green {{ background:#22c55e; }}
    .hero-tabs {{ display:flex; gap:5px; flex-wrap:wrap; }}
    .hero-tab {{
      background:transparent; border:1px solid transparent; color:var(--muted);
      font-size:0.69rem; font-weight:700; padding:4px 9px; border-radius:999px; cursor:pointer;
    }}
    .hero-tab.active {{ background:rgba(99,102,241,0.24); border-color:rgba(129,140,248,0.55); color:#e0e7ff; }}
    .hero-stage {{ position:relative; background:#03060d; }}
    .hero-stage img {{ width:100%; height:auto; display:block; }}
    .hero-play-overlay {{
      position:absolute; right:14px; bottom:14px;
      background:rgba(6,9,19,0.88); backdrop-filter:blur(8px);
      border:1px solid rgba(56,189,248,0.6); color:#fff; text-decoration:none;
      padding:8px 14px; border-radius:999px; font-size:0.8rem; font-weight:700;
      display:inline-flex; align-items:center; gap:7px; box-shadow:0 8px 24px rgba(0,0,0,0.55);
    }}
    .hero-stage-cap {{
      padding:12px 16px; background:#0b1222; border-top:1px solid var(--border);
      display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;
    }}
    .hero-stage-cap strong {{ font-size:0.86rem; color:#fff; display:block; }}
    .hero-stage-cap span {{ font-size:0.78rem; color:var(--muted); }}

    /* Section Styling */
    section.block {{ padding:46px 0 18px; }}
    .sec-head {{ display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:14px; margin-bottom:22px; }}
    .sec-head h2 {{ font-size:clamp(1.45rem,2.5vw,2.05rem); margin:8px 0 6px; color:#fff; }}
    .sec-head p {{ margin:0; color:var(--muted); max-width:720px; font-size:0.95rem; }}

    /* Video Demo Theater */
    .demo-theater {{
      display:grid; grid-template-columns:1.55fr 0.95fr; gap:20px; align-items:start;
      background:linear-gradient(155deg,rgba(15,23,42,0.92),rgba(9,14,28,0.96));
      border:1px solid rgba(56,189,248,0.28); border-radius:18px; padding:22px;
    }}
    .video-shell {{ background:#03060e; border:1px solid var(--border); border-radius:13px; overflow:hidden; }}
    .video-bar {{
      display:flex; justify-content:space-between; align-items:center; padding:10px 14px;
      background:#0c1426; border-bottom:1px solid var(--border); font-size:0.82rem; font-weight:700; color:#e0e7ff;
    }}
    .video-shell video {{ width:100%; height:auto; display:block; aspect-ratio:16/9; background:#020617; }}
    .video-chapters {{ display:flex; flex-direction:column; gap:12px; }}
    .video-chapter-btn {{
      text-align:left; background:rgba(15,23,42,0.75); border:1px solid var(--border);
      border-radius:12px; padding:14px 16px; color:var(--text); cursor:pointer; transition:border-color 0.15s, background 0.15s;
    }}
    .video-chapter-btn:hover, .video-chapter-btn.active {{
      border-color:var(--cyan); background:rgba(30,41,59,0.85);
      box-shadow:0 0 0 1px rgba(56,189,248,0.3);
    }}
    .vc-top {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:7px; }}
    .vc-dur {{ font-family:'JetBrains Mono',monospace; font-size:0.75rem; color:var(--emerald); font-weight:600; }}
    .video-chapter-btn strong {{ display:block; font-size:0.94rem; margin-bottom:5px; color:#fff; }}
    .video-chapter-btn p {{ margin:0; font-size:0.81rem; color:var(--muted); line-height:1.5; }}

    /* Interactive 5-Step Customer Journey */
    .journey-box {{
      margin-top:22px; background:var(--card); border:1px solid var(--border);
      border-radius:16px; padding:22px;
    }}
    .journey-tabs {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:8px; margin-bottom:20px; }}
    .journey-step-btn {{
      display:flex; align-items:center; gap:9px; text-align:left; padding:10px 12px;
      background:#0a1120; border:1px solid var(--border); border-radius:10px;
      color:var(--muted); cursor:pointer; font-weight:600; font-size:0.8rem;
    }}
    .journey-step-btn.active {{
      background:linear-gradient(135deg,rgba(79,70,229,0.28),rgba(14,165,233,0.16));
      border-color:var(--indigo); color:#fff;
    }}
    .step-num {{
      width:24px; height:24px; border-radius:7px; background:rgba(99,102,241,0.25); color:#c7d2fe;
      display:inline-flex; align-items:center; justify-content:center; font-family:'JetBrains Mono',monospace;
      font-size:0.74rem; font-weight:700; flex-shrink:0;
    }}
    .journey-step-btn.active .step-num {{ background:var(--indigo); color:#fff; }}
    .journey-panel {{ display:grid; grid-template-columns:0.95fr 1.15fr; gap:24px; align-items:center; }}
    .journey-copy h3 {{ font-size:1.25rem; margin:8px 0 10px; color:#fff; line-height:1.3; }}
    .journey-copy p {{ color:var(--soft); font-size:0.92rem; margin:0 0 14px; }}
    .journey-meta-card {{
      background:#080e1d; border:1px solid var(--border); border-radius:10px;
      padding:12px 14px; font-size:0.82rem; color:var(--muted); margin-bottom:10px;
    }}
    .journey-meta-card strong {{ color:var(--cyan); display:block; margin-bottom:3px; font-size:0.74rem; text-transform:uppercase; letter-spacing:0.05em; }}
    .journey-shot {{ border:1px solid var(--border); border-radius:12px; overflow:hidden; background:#03060d; }}
    .journey-shot img {{ width:100%; height:auto; display:block; }}

    /* Live Interactive 60s Scanner */
    .scanner-card {{
      background:linear-gradient(135deg,rgba(79,70,229,0.18),rgba(14,165,233,0.12) 55%,rgba(15,23,42,0.96));
      border:1px solid rgba(99,102,241,0.45); border-radius:18px; padding:26px;
    }}
    .scanner-form {{ display:grid; grid-template-columns:1.6fr 1fr auto; gap:10px; margin-top:16px; }}
    .scanner-input {{
      background:#070c18; border:1px solid rgba(148,163,184,0.28); color:#fff;
      padding:12px 14px; border-radius:10px; font-size:0.92rem; outline:none; width:100%;
    }}
    .scanner-input:focus {{ border-color:var(--cyan); box-shadow:0 0 0 3px rgba(56,189,248,0.18); }}
    .sample-chips {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; align-items:center; font-size:0.78rem; color:var(--muted); }}
    .chip-btn {{
      background:rgba(15,23,42,0.9); border:1px solid var(--border); color:#93c5fd;
      padding:4px 10px; border-radius:999px; font-size:0.76rem; cursor:pointer;
    }}
    .chip-btn:hover {{ border-color:var(--cyan); color:#fff; }}
    .scan-output {{
      margin-top:16px; padding:18px; background:rgba(6,9,19,0.9);
      border:1px solid rgba(52,211,153,0.35); border-radius:12px; display:none;
    }}
    .scan-output.visible {{ display:block; }}

    /* Direct System Screenshot Gallery */
    .filter-row {{ display:flex; gap:8px; flex-wrap:wrap; }}
    .filter-pill {{
      background:var(--card); border:1px solid var(--border); color:var(--soft);
      padding:7px 14px; border-radius:999px; font-size:0.82rem; font-weight:600; cursor:pointer;
    }}
    .filter-pill.active {{ background:var(--indigo); border-color:var(--indigo); color:#fff; }}
    .gallery-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:20px; }}
    .shot-card {{
      background:var(--card); border:1px solid var(--border); border-radius:14px; overflow:hidden;
      display:flex; flex-direction:column; transition:transform 0.18s, border-color 0.18s;
    }}
    .shot-card:hover {{ transform:translateY(-3px); border-color:rgba(56,189,248,0.5); }}
    .shot-card.hidden {{ display:none; }}
    .shot-chrome {{
      display:flex; align-items:center; gap:6px; padding:8px 12px; background:#0a1120;
      border-bottom:1px solid var(--border); font-size:0.72rem; color:var(--muted);
    }}
    .shot-url {{ margin-left:4px; font-family:'JetBrains Mono',monospace; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .shot-zoom-btn {{
      margin-left:auto; background:rgba(30,41,59,0.9); border:1px solid var(--border); color:#cbd5e1;
      border-radius:6px; padding:2px 8px; font-size:0.72rem; cursor:pointer;
    }}
    .shot-img-wrap {{ position:relative; cursor:zoom-in; background:#020617; overflow:hidden; }}
    .shot-img-wrap img {{ width:100%; height:auto; display:block; transition:transform 0.25s; }}
    .shot-card:hover .shot-img-wrap img {{ transform:scale(1.02); }}
    .shot-hover-pill {{
      position:absolute; left:12px; bottom:10px; background:rgba(6,9,19,0.85); color:#e2e8f0;
      font-size:0.72rem; font-weight:600; padding:4px 9px; border-radius:999px; border:1px solid var(--border);
    }}
    .shot-body {{ padding:16px 18px 18px; display:flex; flex-direction:column; gap:8px; flex:1; }}
    .shot-body h3 {{ margin:0; font-size:1rem; color:#fff; }}
    .shot-body p {{ margin:0; font-size:0.84rem; color:var(--muted); flex:1; }}
    .shot-link {{ color:var(--cyan); text-decoration:none; font-weight:700; font-size:0.84rem; margin-top:4px; }}

    /* Pricing Controls & Cards */
    .pricing-controls {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
    .toggle-group {{
      display:inline-flex; background:#0a1120; border:1px solid var(--border);
      border-radius:10px; padding:3px; gap:3px;
    }}
    .toggle-btn {{
      background:transparent; border:none; color:var(--muted); font-size:0.8rem; font-weight:700;
      padding:7px 12px; border-radius:7px; cursor:pointer;
    }}
    .toggle-btn.active {{ background:var(--indigo); color:#fff; }}
    .pilot-banner {{
      background:linear-gradient(120deg,rgba(16,185,129,0.16),rgba(79,70,229,0.18),rgba(15,23,42,0.96));
      border:1px solid rgba(52,211,153,0.45); border-radius:16px; padding:22px 24px;
      display:flex; justify-content:space-between; align-items:center; gap:18px; flex-wrap:wrap; margin-bottom:20px;
    }}
    .grid-4 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(255px,1fr)); gap:16px; }}
    .grid-5 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; }}
    .card {{
      background:var(--card); border:1px solid var(--border); border-radius:14px;
      padding:18px; display:flex; flex-direction:column; justify-content:space-between;
    }}
    .card.featured {{
      border-color:var(--border-hi);
      background:linear-gradient(180deg,rgba(79,70,229,0.2),var(--card));
      box-shadow:0 16px 40px rgba(79,70,229,0.18);
    }}
    .tier-head {{ display:flex; justify-content:space-between; align-items:center; gap:6px; flex-wrap:wrap; }}
    .popular-pill {{ font-size:0.65rem; font-weight:800; background:rgba(52,211,153,0.2); color:var(--emerald); padding:2px 8px; border-radius:999px; }}
    .card h3 {{ margin:10px 0 6px; font-size:1.05rem; color:#fff; }}
    .desc {{ font-size:0.87rem; color:var(--soft); }}
    .meta {{ font-size:0.83rem; color:var(--muted); }}
    .price-display {{ margin:12px 0 2px; }}
    .price-main {{ font-size:1.65rem; font-weight:800; color:var(--emerald); }}
    .price-unit {{ font-size:0.82rem; color:var(--muted); margin-left:3px; }}
    .annual-sub {{ font-size:0.76rem; color:#a5b4fc; margin-bottom:10px; }}
    .tier-specs {{ margin:0 0 14px; padding-left:18px; font-size:0.82rem; color:var(--soft); }}
    .tier-specs li {{ margin-bottom:5px; }}
    .actions {{ display:flex; flex-direction:column; gap:8px; margin-top:8px; }}

    /* Visual Solutions Grid */
    .sol-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:18px; }}
    .sol-card {{ padding:0; overflow:hidden; }}
    .sol-thumb {{ background:#020617; border-bottom:1px solid var(--border); overflow:hidden; max-height:175px; }}
    .sol-thumb img {{ width:100%; height:175px; object-fit:cover; object-position:top; display:block; }}
    .sol-body {{ padding:16px 18px 18px; display:flex; flex-direction:column; gap:8px; flex:1; }}
    .sol-body h3 a {{ color:#fff; text-decoration:none; }}
    .sol-body h3 a:hover {{ color:var(--cyan); }}
    .sol-foot {{ display:flex; justify-content:space-between; align-items:center; margin-top:auto; padding-top:10px; border-top:1px solid var(--border); }}
    .sol-price {{ font-weight:800; color:var(--emerald); font-size:0.95rem; }}
    .sol-price small {{ color:var(--muted); font-weight:500; }}

    /* Accordion FAQs */
    details.faq-item {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:15px 18px; margin-top:10px; }}
    details.faq-item summary {{ cursor:pointer; font-weight:700; color:#e0e7ff; font-size:0.98rem; list-style:none; display:flex; justify-content:space-between; align-items:center; gap:12px; }}
    details.faq-item summary::after {{ content:"+"; color:var(--cyan); font-size:1.25rem; font-weight:700; }}
    details.faq-item[open] summary::after {{ content:"−"; }}
    details.faq-item p {{ margin:10px 0 0; color:var(--soft); font-size:0.91rem; }}

    /* Lightbox Modal */
    .lightbox {{
      position:fixed; inset:0; z-index:200; background:rgba(2,6,17,0.92); backdrop-filter:blur(10px);
      display:none; align-items:center; justify-content:center; padding:20px;
    }}
    .lightbox.open {{ display:flex; }}
    .lb-inner {{
      max-width:1120px; width:100%; background:#0a1120; border:1px solid rgba(56,189,248,0.45);
      border-radius:16px; overflow:hidden; box-shadow:0 30px 90px rgba(0,0,0,0.75);
    }}
    .lb-top {{ display:flex; justify-content:space-between; align-items:center; padding:12px 18px; border-bottom:1px solid var(--border); gap:10px; }}
    .lb-top strong {{ color:#fff; font-size:0.96rem; }}
    .lb-controls {{ display:flex; gap:8px; }}
    .lb-btn {{ background:#1e293b; border:1px solid var(--border); color:#fff; padding:6px 12px; border-radius:8px; cursor:pointer; font-weight:700; font-size:0.82rem; }}
    .lb-img {{ width:100%; max-height:70vh; object-fit:contain; display:block; background:#020617; }}
    .lb-cap {{ padding:14px 18px; border-top:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; gap:14px; flex-wrap:wrap; font-size:0.86rem; color:var(--soft); }}

    footer {{ border-top:1px solid var(--border); margin-top:52px; padding:28px 0 40px; color:var(--muted); font-size:0.85rem; }}
    footer a {{ color:#93c5fd; text-decoration:none; margin-right:14px; }}

    @media (max-width: 960px) {{
      .hero, .demo-theater, .journey-panel {{ grid-template-columns:1fr; }}
      .journey-tabs {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
      .scanner-form {{ grid-template-columns:1fr; }}
    }}
    @media (max-width: 600px) {{
      .proof-strip {{ grid-template-columns:1fr; }}
      .gallery-grid {{ grid-template-columns:1fr; }}
      .nav-links {{ gap:10px; }}
      .journey-tabs {{ grid-template-columns:1fr; }}
    }}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="wrap nav-inner">
      <a class="brand" href="/">
        <span class="brand-mark" aria-hidden="true">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M4 20L12 4L20 20H4Z" fill="#fff"/></svg>
        </span>
        <span>AskforWrite AI Company OS</span>
      </a>
      <nav class="nav-links" aria-label="Primary Navigation">
        <a href="#demo">Customer Demo</a>
        <a href="#screenshots">Screenshots</a>
        <a href="#scanner">Free AI Audit</a>
        <a href="#pricing">Pricing</a>
        <a href="/solutions">Vertical AI</a>
        <a href="/dashboard/#portal">Customer Portal</a>
        <a class="nav-cta" href="/dashboard/">Launch Workspace →</a>
      </nav>
    </div>
  </div>

  <header class="wrap">
    <div class="hero">
      <div>
        <span class="badge"><span class="pulse-dot"></span> MULTI-AGENT AI OPERATING SYSTEM · MSME UDYAM-RJ-14-0018404</span>
        <h1>Operate Your AI Workforce With <span class="grad-text">Live Proof, 1-Click Approvals &amp; Zero Rogue Sends</span></h1>
        <p class="hero-sub">Replace disconnected marketing agencies, spreadsheets, and black-box scripts with one visual, tenant-isolated AI operating system. See real screenshots and interactive walkthrough videos of how customers run SEO/GEO audits, AI sales agents, Warehouse StockSense, and ECDSA-verified deliverables every day.</p>
        <div class="hero-cta">
          <a class="btn-primary" href="#demo">▶ Watch Customer Walkthrough</a>
          <a class="btn-secondary" href="#scanner">⚡ Free 60s Website AI Audit</a>
          <a class="btn-secondary" href="/services/managed_seo_content_pilot">Start ₹4,999 14-Day Pilot →</a>
        </div>
        <div class="proof-strip">
          <div class="proof-box"><strong>16 Modular AI Tools</strong><span>4 clusters · Portal + REST API</span></div>
          <div class="proof-box"><strong>100% HITL Governed</strong><span>1-click approval before external send</span></div>
          <div class="proof-box"><strong>ECDSA NIST P-256</strong><span>Tamper-evident TrustBlock receipts</span></div>
        </div>
      </div>

      <div class="browser-frame" aria-label="Interactive Live Product Preview">
        <div class="browser-bar">
          <div class="dots"><span class="dot red"></span><span class="dot amber"></span><span class="dot green"></span></div>
          <div class="hero-tabs" id="hero-tabs">{hero_tabs_html}</div>
        </div>
        <div class="hero-stage">
          <img id="hero-preview-img" src="{html.escape(hero_screens[0]['src'])}" alt="{html.escape(hero_screens[0]['title'])}" width="1280" height="800" />
          <a class="hero-play-overlay" href="#demo" id="hero-play-jump">▶ Play 24s Customer Walkthrough</a>
        </div>
        <div class="hero-stage-cap">
          <div>
            <strong id="hero-preview-title">{html.escape(hero_screens[0]['title'])}</strong>
            <span id="hero-preview-sub">{html.escape(hero_screens[0]['caption'][:115])}…</span>
          </div>
          <a class="shot-link" id="hero-preview-cta" href="{html.escape(hero_screens[0]['cta_href'])}">Try Live →</a>
        </div>
      </div>
    </div>
  </header>

  <main class="wrap">
    <!-- ── SECTION 1: INTERACTIVE VIDEO DEMO & 5-STEP CUSTOMER OPERATING GUIDE ── -->
    <section class="block" id="demo">
      <div class="sec-head">
        <div>
          <span class="badge-soft">INTERACTIVE CUSTOMER WALKTHROUGH · REAL SYSTEM VIDEOS</span>
          <h2>See Exactly How Customers Operate AskforWrite OS</h2>
          <p>Real unedited screen recordings directly from the running AskforWrite AI Company OS interface—from logging into an isolated Customer Portal and approving deliverables to running AI agents and verifying ECDSA TrustBlocks.</p>
        </div>
        <a class="btn-secondary" href="/dashboard/#portal">Open Customer Portal →</a>
      </div>

      <div class="demo-theater">
        <div class="video-shell">
          <div class="video-bar">
            <span id="active-video-title">▶ {html.escape(DEMO_VIDEOS[0]['title'])}</span>
            <span style="color:#34d399;font-size:0.74rem;">DIRECT SYSTEM CAPTURE</span>
          </div>
          <video id="afw-demo-video" controls playsinline preload="metadata" poster="{html.escape(DEMO_VIDEOS[0]['poster'])}">
            <source id="vid-src-webm" src="{html.escape(DEMO_VIDEOS[0]['webm'])}" type="video/webm" />
          </video>
        </div>
        <div class="video-chapters" id="video-chapters">
          {video_cards_html}
        </div>
      </div>

      <div class="journey-box" id="how-it-works">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px;">
          <div>
            <span class="badge-soft">STEP-BY-STEP USABILITY TOUR</span>
            <h3 style="margin:6px 0 0;font-size:1.15rem;color:#fff;">Click Any Step to Inspect the Customer Experience</h3>
          </div>
          <span class="meta">Click 01–05 below to preview each real workspace screen</span>
        </div>
        <div class="journey-tabs" id="journey-tabs">{journey_tabs_html}</div>
        <div class="journey-panel">
          <div class="journey-copy">
            <span class="badge" id="j-step-pill">STEP {html.escape(first_step['step'])} OF 05</span>
            <h3 id="j-step-title">{html.escape(first_step['title'])}</h3>
            <p id="j-step-desc">{html.escape(first_step['description'])}</p>
            <div class="journey-meta-card">
              <strong>Customer Click Flow</strong>
              <span id="j-step-action">{html.escape(first_step['customer_action'])}</span>
            </div>
            <div class="journey-meta-card">
              <strong>Backed By Live Endpoints</strong>
              <code id="j-step-endpoint">{html.escape(first_step['endpoint'])}</code>
            </div>
          </div>
          <div class="journey-shot">
            <img id="j-step-img" src="{html.escape(first_step['screenshot'])}" alt="{html.escape(first_step['alt'])}" loading="lazy" width="1280" height="800" />
          </div>
        </div>
      </div>
    </section>

    <!-- ── SECTION 2: LIVE INTERACTIVE 60-SECOND WEBSITE SEO/GEO SCANNER ── -->
    <section class="block" id="scanner">
      <div class="scanner-card">
        <span class="badge"><span class="pulse-dot"></span> LIVE INTERACTIVE PRODUCT DEMO · TRY BEFORE YOU BUY</span>
        <h2 style="margin:10px 0 6px;font-size:clamp(1.35rem,2.4vw,1.9rem);color:#fff;">Run a Free 60-Second Live AI SEO &amp; GEO Audit Right Here</h2>
        <p class="meta" style="max-width:760px;color:#cbd5e1;">Test the live AskforWrite AI Opportunity Scanner on your own website right now. We inspect real HTML headers, Schema.org JSON-LD, and AI crawler readiness (<code>/llms.txt</code>) in seconds.</p>
        <form class="scanner-form" id="home-scanner-form">
          <input class="scanner-input" type="text" id="home-scan-url" placeholder="Enter your website (e.g. https://yourcompany.com)" required />
          <input class="scanner-input" type="text" id="home-scan-company" placeholder="Company name (optional)" />
          <button class="btn-primary" type="submit" id="home-scan-btn">Run Live Audit →</button>
        </form>
        <div class="sample-chips">
          <span>Try instant example:</span>
          <button type="button" class="chip-btn" data-sample-url="https://askforwrite.com" data-sample-co="AskforWrite">askforwrite.com</button>
          <button type="button" class="chip-btn" data-sample-url="https://www.wpoets.com" data-sample-co="WPoets">wpoets.com</button>
        </div>
        <div class="scan-output" id="home-scan-output" aria-live="polite"></div>
      </div>
    </section>

    <!-- ── SECTION 3: DIRECT SYSTEM SCREENSHOTS GALLERY + LIGHTBOX ── -->
    <section class="block" id="screenshots">
      <div class="sec-head">
        <div>
          <span class="badge-soft">DIRECT SCREENSHOTS FROM THE LIVE SYSTEM</span>
          <h2>Explore Every Workspace Screen Inside AskforWrite OS</h2>
          <p>Zero mock wireframes—every image below is captured directly from our running multi-tenant application. Filter by workflow or click any screen to zoom in full resolution.</p>
        </div>
        <div class="filter-row" id="gallery-filters">
          <button type="button" class="filter-pill active" data-filter="all">All Screens ({len(SYSTEM_SCREENSHOTS)})</button>
          <button type="button" class="filter-pill" data-filter="customer">Customer Portal</button>
          <button type="button" class="filter-pill" data-filter="growth">Growth &amp; SEO</button>
          <button type="button" class="filter-pill" data-filter="operations">Operations AI</button>
          <button type="button" class="filter-pill" data-filter="governance">Governance &amp; Pay</button>
        </div>
      </div>
      <div class="gallery-grid" id="gallery-grid">{gallery_cards_html}</div>
    </section>

    <!-- ── SECTION 4: INTERACTIVE CLUSTERED PRICING & 14-DAY PILOT ── -->
    <section class="block" id="pricing">
      <div class="sec-head">
        <div>
          <span class="badge-soft">TRANSPARENT INR &amp; USD PRICING · SAVE 20% ANNUALLY</span>
          <h2>Clustered AI Subscription Plans &amp; 14-Day Pilot</h2>
          <p>Start with one capability cluster, try our fixed-scope 14-day Done-For-You pilot first, or unlock all 4 AI clusters for your whole company.</p>
        </div>
        <div class="pricing-controls">
          <div class="toggle-group" role="group" aria-label="Billing cycle">
            <button type="button" class="toggle-btn active" data-billing="monthly">Monthly</button>
            <button type="button" class="toggle-btn" data-billing="annual">Annual (-20%)</button>
          </div>
          <div class="toggle-group" role="group" aria-label="Currency">
            <button type="button" class="toggle-btn active" data-currency="inr">INR ₹</button>
            <button type="button" class="toggle-btn" data-currency="usd">USD $</button>
          </div>
        </div>
      </div>

      <div class="pilot-banner">
        <div>
          <span class="badge-soft" style="background:rgba(52,211,153,0.18);color:#34d399;">RECOMMENDED ENTRY · ONE-TIME NON-RENEWING</span>
          <h3 style="margin:8px 0 6px;font-size:1.3rem;color:#fff;">14-Day Managed SEO &amp; Content Pilot — ₹4,999 <small style="color:#94a3b8;font-weight:500;">($59 USD)</small></h3>
          <p class="meta" style="color:#cbd5e1;margin:0;max-width:740px;">Technical SEO &amp; GEO baseline audit + commercial keyword cluster + 2 human-edited 1,500+ word Schema.org JSON-LD articles staged as drafts (up to 2 revision rounds; live publish only on your approval).</p>
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <a class="btn-primary" rel="nofollow" href="/v1/pay/checkout?package=managed_seo_content_pilot">Start ₹4,999 Pilot →</a>
          <a class="btn-secondary" href="/services/managed_seo_content_pilot">View 14-Day Scope</a>
        </div>
      </div>

      <div class="grid-5" id="pricing-grid">{"".join(tier_cards)}</div>
    </section>

    <!-- ── SECTION 5: 4 FUNCTIONAL CLUSTERS & VERTICAL AI SOLUTIONS ── -->
    <section class="block" id="clusters">
      <div class="sec-head">
        <div>
          <span class="badge-soft">MODULAR ARCHITECTURE</span>
          <h2>4 Functional AI Capability Clusters</h2>
          <p>Related specialist agents, workflows, and vertical AI engines grouped into four clear pillars.</p>
        </div>
        <a class="btn-secondary" href="/services">Compare All 16 SKUs →</a>
      </div>
      <div class="grid-4">{"".join(cluster_cards)}</div>
    </section>

    <section class="block" id="solutions">
      <div class="sec-head">
        <div>
          <span class="badge-soft">PRODUCTION VERTICAL AI ENGINES</span>
          <h2>Vertical AI Operating Systems Built for Real Operations</h2>
          <p>Each vertical module combines live telemetry ingestion, deterministic optimization, and ECDSA NIST P-256 audit proofs.</p>
        </div>
        <a class="btn-secondary" href="/solutions">All Vertical Solutions →</a>
      </div>
      <div class="sol-grid">{solution_cards_html}</div>
    </section>

    <!-- ── SECTION 6: GOVERNANCE & FAQS ── -->
    <section class="block" id="governance">
      <div class="sec-head">
        <div>
          <span class="badge-soft">ZERO-TRUST ENTERPRISE GOVERNANCE</span>
          <h2>Human-in-the-Loop Security &amp; Direct Settlement Architecture</h2>
        </div>
      </div>
      <div class="grid-4">
        <div class="card"><h3>Human-in-the-Loop (HITL) Gates</h3><p class="meta">Every external outreach email, WordPress live publish, commercial proposal, and manual settlement requires explicit Owner or Tenant Admin approval before execution.</p></div>
        <div class="card"><h3>ECDSA NIST P-256 Trust Ledger</h3><p class="meta">Every workflow execution, quality inspection, deliverable acceptance, and payment receipt is hashed and cryptographically sealed into a tamper-evident Merkle chain.</p></div>
        <div class="card"><h3>Strict BYOK Gemini Isolation</h3><p class="meta">Tenants supply their own Gemini API keys—stored encrypted, masked in responses, strictly isolated per org_id, with zero markup on LLM tokens.</p></div>
        <div class="card"><h3>0%-Commission AFW DirectPay</h3><p class="meta">Settle directly via Instant ISO UPI QR (GPay, PhonePe, Paytm, BHIM) or ICICI Bank Wire (NEFT/RTGS/IMPS/SWIFT) alongside Razorpay (INR) and PayPal (USD).</p></div>
      </div>
    </section>

    <section class="block" id="faq">
      <div class="sec-head">
        <div>
          <span class="badge-soft">FREQUENTLY ASKED QUESTIONS</span>
          <h2>Answers for Founders, Agencies &amp; Operations Teams</h2>
        </div>
      </div>
      {faq_html}
    </section>
  </main>

  <footer class="wrap">
    <p>
      <a href="/services">All 16 Services</a>
      <a href="/solutions">Vertical Solutions</a>
      <a href="/dashboard/#portal">Customer Portal</a>
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

  <!-- Full-Screen Screenshot Lightbox Modal -->
  <div class="lightbox" id="shot-lightbox" role="dialog" aria-modal="true" aria-label="System screenshot viewer">
    <div class="lb-inner">
      <div class="lb-top">
        <strong id="lb-title">System Screenshot</strong>
        <div class="lb-controls">
          <button type="button" class="lb-btn" id="lb-prev">← Prev</button>
          <button type="button" class="lb-btn" id="lb-next">Next →</button>
          <button type="button" class="lb-btn" id="lb-close">✕ Close</button>
        </div>
      </div>
      <img class="lb-img" id="lb-img" src="{html.escape(SYSTEM_SCREENSHOTS[0]['src'])}" alt="{html.escape(SYSTEM_SCREENSHOTS[0]['title'])}" />
      <div class="lb-cap">
        <span id="lb-caption"></span>
        <a class="shot-link" id="lb-cta" href="/dashboard/">Open in Workspace →</a>
      </div>
    </div>
  </div>

  <script>
  (function() {{
    const HERO_SCREENS = {hero_screens_json};
    const VIDEOS = {videos_json};
    const STEPS = {steps_json};
    const SHOTS = {shots_json};

    // 1. Hero interactive preview tabs
    const heroImg = document.getElementById('hero-preview-img');
    const heroTitle = document.getElementById('hero-preview-title');
    const heroSub = document.getElementById('hero-preview-sub');
    const heroCta = document.getElementById('hero-preview-cta');
    document.querySelectorAll('[data-hero-idx]').forEach(btn => {{
      btn.addEventListener('click', () => {{
        const s = HERO_SCREENS[Number(btn.dataset.heroIdx)];
        if (!s) return;
        document.querySelectorAll('[data-hero-idx]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        heroImg.src = s.src; heroImg.alt = s.title;
        heroTitle.textContent = s.title;
        heroSub.textContent = s.caption.slice(0, 118) + '…';
        heroCta.href = s.cta_href;
      }});
    }});

    // 2. Video demo chapter switcher
    const vidEl = document.getElementById('afw-demo-video');
    const vidTitle = document.getElementById('active-video-title');
    const srcWebm = document.getElementById('vid-src-webm');
    function selectVideo(idx, autoplay) {{
      const v = VIDEOS[idx];
      if (!v || !vidEl) return;
      document.querySelectorAll('[data-video-idx]').forEach(b => b.classList.toggle('active', Number(b.dataset.videoIdx) === idx));
      vidTitle.textContent = '▶ ' + v.title;
      vidEl.poster = v.poster;
      srcWebm.src = v.webm;
      vidEl.load();
      if (autoplay) {{ vidEl.play().catch(() => {{}}); }}
    }}
    document.querySelectorAll('[data-video-idx]').forEach(btn => {{
      btn.addEventListener('click', () => selectVideo(Number(btn.dataset.videoIdx), true));
    }});
    const heroPlay = document.getElementById('hero-play-jump');
    if (heroPlay) {{
      heroPlay.addEventListener('click', () => {{ setTimeout(() => vidEl && vidEl.play().catch(() => {{}}), 350); }});
    }}

    // 3. Interactive 5-Step Customer Journey
    document.querySelectorAll('[data-step-idx]').forEach(btn => {{
      btn.addEventListener('click', () => {{
        const st = STEPS[Number(btn.dataset.stepIdx)];
        if (!st) return;
        document.querySelectorAll('[data-step-idx]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('j-step-pill').textContent = 'STEP ' + st.step + ' OF 05';
        document.getElementById('j-step-title').textContent = st.title;
        document.getElementById('j-step-desc').textContent = st.description;
        document.getElementById('j-step-action').textContent = st.customer_action;
        document.getElementById('j-step-endpoint').textContent = st.endpoint;
        const img = document.getElementById('j-step-img');
        img.src = st.screenshot; img.alt = st.alt;
      }});
    }});

    // 4. Screenshot Gallery Category Filters + Lightbox
    document.querySelectorAll('[data-filter]').forEach(pill => {{
      pill.addEventListener('click', () => {{
        const f = pill.dataset.filter;
        document.querySelectorAll('[data-filter]').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        document.querySelectorAll('.shot-card').forEach(card => {{
          card.classList.toggle('hidden', f !== 'all' && card.dataset.category !== f);
        }});
      }});
    }});

    const lb = document.getElementById('shot-lightbox');
    let lbIdx = 0;
    function renderLightbox(idx) {{
      lbIdx = (idx + SHOTS.length) % SHOTS.length;
      const s = SHOTS[lbIdx];
      document.getElementById('lb-title').textContent = s.badge + ' — ' + s.title;
      const im = document.getElementById('lb-img');
      im.src = s.src; im.alt = s.title;
      document.getElementById('lb-caption').textContent = s.caption;
      const cta = document.getElementById('lb-cta');
      cta.href = s.cta_href; cta.textContent = s.cta_label + ' →';
      lb.classList.add('open');
    }}
    document.querySelectorAll('[data-open-lightbox]').forEach(el => {{
      el.addEventListener('click', () => renderLightbox(Number(el.dataset.openLightbox)));
    }});
    document.getElementById('lb-prev').addEventListener('click', () => renderLightbox(lbIdx - 1));
    document.getElementById('lb-next').addEventListener('click', () => renderLightbox(lbIdx + 1));
    document.getElementById('lb-close').addEventListener('click', () => lb.classList.remove('open'));
    lb.addEventListener('click', (e) => {{ if (e.target === lb) lb.classList.remove('open'); }});
    document.addEventListener('keydown', (e) => {{
      if (!lb.classList.contains('open')) return;
      if (e.key === 'Escape') lb.classList.remove('open');
      if (e.key === 'ArrowLeft') renderLightbox(lbIdx - 1);
      if (e.key === 'ArrowRight') renderLightbox(lbIdx + 1);
    }});

    // 5. Interactive Pricing Toggle (Monthly/Annual + INR/USD)
    let billing = 'monthly';
    let currency = 'inr';
    function refreshPricing() {{
      document.querySelectorAll('.pricing-card').forEach(card => {{
        const val = Number(card.dataset[(billing === 'annual' ? 'a' : 'm') + (currency === 'usd' ? 'Usd' : 'Inr')] || 0);
        const alt = Number(card.dataset[(billing === 'annual' ? 'a' : 'm') + (currency === 'usd' ? 'Inr' : 'Usd')] || 0);
        const sym = currency === 'usd' ? '$' : '₹';
        const altSym = currency === 'usd' ? '₹' : '$';
        card.querySelector('.price-main').textContent = sym + val.toLocaleString(currency === 'inr' ? 'en-IN' : 'en-US');
        card.querySelector('.price-unit').textContent = billing === 'annual' ? '/mo (billed yearly)' : '/mo';
        card.querySelector('.annual-sub').textContent = (billing === 'annual' ? '20% annual savings applied · ' : 'Save 20% on annual · ') + altSym + alt.toLocaleString(currency === 'usd' ? 'en-IN' : 'en-US') + '/mo';
      }});
    }}
    document.querySelectorAll('[data-billing]').forEach(b => {{
      b.addEventListener('click', () => {{
        billing = b.dataset.billing;
        document.querySelectorAll('[data-billing]').forEach(x => x.classList.toggle('active', x === b));
        refreshPricing();
      }});
    }});
    document.querySelectorAll('[data-currency]').forEach(b => {{
      b.addEventListener('click', () => {{
        currency = b.dataset.currency;
        document.querySelectorAll('[data-currency]').forEach(x => x.classList.toggle('active', x === b));
        refreshPricing();
      }});
    }});

    // 6. Live 60-Second Website SEO/GEO Opportunity Scanner
    const scanForm = document.getElementById('home-scanner-form');
    const scanOut = document.getElementById('home-scan-output');
    const scanBtn = document.getElementById('home-scan-btn');
    document.querySelectorAll('[data-sample-url]').forEach(chip => {{
      chip.addEventListener('click', () => {{
        document.getElementById('home-scan-url').value = chip.dataset.sampleUrl;
        document.getElementById('home-scan-company').value = chip.dataset.sampleCo || '';
      }});
    }});
    if (scanForm) {{
      scanForm.addEventListener('submit', async (e) => {{
        e.preventDefault();
        const urlVal = document.getElementById('home-scan-url').value.trim();
        const coVal = document.getElementById('home-scan-company').value.trim();
        if (!urlVal) return;
        scanBtn.disabled = true;
        scanBtn.textContent = 'Scanning live site…';
        scanOut.classList.add('visible');
        scanOut.innerHTML = '<div style="color:#93c5fd;font-weight:600;">⚡ Auditing live HTML, Schema.org JSON-LD, and /llms.txt crawler readiness…</div>';
        try {{
          const resp = await fetch('/v1/previews/scan', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ url: urlVal, company_name: coVal || null }}),
          }});
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || 'Audit could not complete');
          const leaks = (data.top_pain_leaks || []).map(l => '<li>' + String(l).replace(/</g, '&lt;') + '</li>').join('');
          scanOut.innerHTML =
            '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:10px;">' +
              '<div><strong style="color:#fff;font-size:1rem;">Live Audit: ' + String(data.domain || urlVal).replace(/</g, '&lt;') + '</strong>' +
              '<div style="color:#94a3b8;font-size:0.82rem;">Status: ' + String(data.audit_status || 'LIVE_VERIFIED').replace(/</g, '&lt;') + '</div></div>' +
              '<span style="background:rgba(52,211,153,0.18);color:#34d399;padding:5px 12px;border-radius:999px;font-weight:800;font-size:0.86rem;">SEO/GEO Gap Score: ' + Number(data.seo_geo_gap_score || 0) + '/100</span>' +
            '</div>' +
            '<ul style="margin:0 0 14px;padding-left:18px;color:#e2e8f0;font-size:0.88rem;">' + leaks + '</ul>' +
            '<div style="display:flex;gap:10px;flex-wrap:wrap;">' +
              (data.preview_url ? '<a class="btn-secondary" href="' + encodeURI(data.preview_url) + '">Open Full Audit Preview →</a>' : '') +
              '<a class="btn-primary" rel="nofollow" href="' + encodeURI(data.checkout_url || '/v1/pay/checkout?package=managed_seo_content_pilot') + '">Fix in 14-Day Pilot (₹4,999) →</a>' +
            '</div>';
        }} catch (err) {{
          scanOut.innerHTML = '<div style="color:#fca5a5;">Unable to scan that URL right now: ' + String(err.message || err).replace(/</g, '&lt;') + '</div>';
        }} finally {{
          scanBtn.disabled = false;
          scanBtn.textContent = 'Run Live Audit →';
        }}
      }});
    }}
  }})();
  </script>
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
