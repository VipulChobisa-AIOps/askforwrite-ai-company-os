"""Shared real-system screenshot & customer walkthrough video catalog for public sales pages.

Every asset listed here is captured directly from the live AskforWrite AI Company OS UI
via scripts/capture_product_media.py (stored under app/dashboard/media/ and served at
/dashboard/media/ and /static/media/).
"""

from __future__ import annotations

import html
from typing import Any

MEDIA_BASE = "/dashboard/media"

SYSTEM_SCREENSHOTS: list[dict[str, Any]] = [
    {
        "id": "customer-portal",
        "category": "customer",
        "badge": "CUSTOMER PORTAL",
        "title": "Self-Service Customer Workspace & Deliverable Acceptance",
        "caption": "Customers sign in to their isolated workspace to track onboarding milestones, inspect QA-verified deliverables, accept work with 1 click, submit support tickets, and manage DPDP privacy controls.",
        "src": f"{MEDIA_BASE}/screenshots/01-customer-portal.png",
        "cta_label": "Open Customer Portal",
        "cta_href": "/dashboard/#portal",
    },
    {
        "id": "customer-agent-console",
        "category": "customer",
        "badge": "AGENT RUN CONSOLE",
        "title": "On-Demand AI Agent Execution & 18-Field Evidence Drawer",
        "caption": "Run entitled AI employees directly from the browser in Simulation or Live-with-Approval mode, then inspect inputs, outputs, latency, and cryptographic provenance inside the 18-Field Evidence Drawer.",
        "src": f"{MEDIA_BASE}/screenshots/02-customer-agent-console.png",
        "cta_label": "Explore AI Services",
        "cta_href": "/services",
    },
    {
        "id": "command-center",
        "category": "operations",
        "badge": "COMMAND CENTER",
        "title": "Unified AI Command Dock, 12 Tools & 9 Specialist AI Employees",
        "caption": "Operate every connected commercial capability from one control center: launch the 60-second Opportunity Scanner, invoke specialist agents, and monitor real-time pipeline stages.",
        "src": f"{MEDIA_BASE}/screenshots/03-command-center.png",
        "cta_label": "Launch Workspace",
        "cta_href": "/dashboard/",
    },
    {
        "id": "hitl-approvals",
        "category": "governance",
        "badge": "HITL GOVERNANCE",
        "title": "Human-in-the-Loop (HITL) 1-Click Approval Gate",
        "caption": "Zero rogue AI actions: every outbound email, WordPress publication, commercial proposal, and billing adjustment pauses in your Approvals queue until you review and click Approve or Reject.",
        "src": f"{MEDIA_BASE}/screenshots/04-hitl-approvals.png",
        "cta_label": "See Governance Architecture",
        "cta_href": "/#governance",
    },
    {
        "id": "growth-seo-suite",
        "category": "growth",
        "badge": "GROWTH & SEO/GEO",
        "title": "Autonomous SEO/GEO Copilot, Pixel AI Studio & 24/7 AI Closer",
        "caption": "Generate structured Schema.org JSON-LD articles, /llms.txt AI search manifests, 7-channel campaign copy, and Pixel AI creative specs with built-in commercial honesty guards.",
        "src": f"{MEDIA_BASE}/screenshots/05-growth-seo-suite.png",
        "cta_label": "View Growth Suite",
        "cta_href": "/services/growth_all_in_one",
    },
    {
        "id": "stocksense-inventory",
        "category": "operations",
        "badge": "VERTICAL AI · LOGISTICS",
        "title": "Warehouse StockSense AI — Pareto ABC-XYZ, EOQ & ROP Engine",
        "caption": "Upload SKU inventory snapshots to compute Economic Order Quantities, safety-stock variance, dead-stock liquidation priorities, and critical replenishment manifests in milliseconds.",
        "src": f"{MEDIA_BASE}/screenshots/06-stocksense-inventory.png",
        "cta_label": "Explore Warehouse AI",
        "cta_href": "/solutions/warehouse-automation",
    },
    {
        "id": "trust-ledger",
        "category": "governance",
        "badge": "ECDSA NIST P-256",
        "title": "Tamper-Evident Merkle Cryptographic Trust Ledger",
        "caption": "Every approved workflow, deliverable sign-off, quality certificate, and payment reconciliation is hashed and ECDSA-signed into a verifiable chain you can audit anytime.",
        "src": f"{MEDIA_BASE}/screenshots/07-trust-ledger.png",
        "cta_label": "View Trust Engine",
        "cta_href": "/services/trust_engine",
    },
    {
        "id": "directpay-checkout",
        "category": "governance",
        "badge": "AFW DIRECTPAY",
        "title": "Multi-Rail Checkout — 0%-Fee DirectPay UPI QR, Razorpay & PayPal",
        "caption": "Select a ₹4,999 14-Day Pilot or any clustered subscription plan and settle transparently in INR or USD via Instant UPI QR, Direct Bank Wire, Razorpay, or PayPal.",
        "src": f"{MEDIA_BASE}/screenshots/08-directpay-checkout.png",
        "cta_label": "Compare Plans",
        "cta_href": "/#pricing",
    },
]

DEMO_VIDEOS: list[dict[str, str]] = [
    {
        "id": "customer-workspace",
        "badge": "VIDEO 1 · CUSTOMER VIEW",
        "title": "How Customers Operate AskforWrite OS Daily",
        "duration": "0:24",
        "summary": "Real screen recording from a customer login: inspect active plan & onboarding checklist, accept a QA-verified SEO deliverable with 1 click, view billing credits, execute an AI agent, and open the cryptographic Evidence Drawer.",
        "webm": f"{MEDIA_BASE}/videos/customer-workspace-demo.webm",
        "poster": f"{MEDIA_BASE}/videos/poster-customer-demo.png",
    },
    {
        "id": "checkout-governance",
        "badge": "VIDEO 2 · END-TO-END FLOW",
        "title": "From Checkout to AI Execution, HITL Approval & Trust Ledger",
        "duration": "0:22",
        "summary": "Real screen recording walking through verified checkout (UPI QR / Razorpay / PayPal), the 12-tool AI Command Center, 1-click Human-in-the-Loop approval gating, and ECDSA NIST P-256 Trust Ledger verification.",
        "webm": f"{MEDIA_BASE}/videos/checkout-to-governance-demo.webm",
        "poster": f"{MEDIA_BASE}/videos/poster-governance-demo.png",
    },
]

CUSTOMER_JOURNEY_STEPS: list[dict[str, str]] = [
    {
        "step": "01",
        "short_title": "Select Plan & Checkout",
        "title": "Pick a 14-Day Pilot (₹4,999) or Clustered Plan & Complete Verified Checkout",
        "description": "Choose only the AI capability cluster you need—or start with the fixed-scope 14-Day Managed SEO & Content Pilot. Settle cleanly via Instant ISO UPI QR (0% AskforWrite commission), Direct Bank Wire, Razorpay (INR), or PayPal (USD).",
        "customer_action": "Select SKU -> Verify pricing & billing cycle -> Complete UPI / Razorpay / PayPal checkout",
        "endpoint": "GET /services  |  POST /v1/pay/sovereign/initiate",
        "screenshot": f"{MEDIA_BASE}/screenshots/08-directpay-checkout.png",
        "alt": "AskforWrite DirectPay multi-rail checkout screen",
    },
    {
        "step": "02",
        "short_title": "Sign In to Customer Portal",
        "title": "Access Your Isolated Multi-Tenant Portal & Complete Onboarding Checklist",
        "description": "Once payment confirms, your dedicated tenant organization unlocks with role-based access, active plan entitlements, onboarding tasks, and optional Bring-Your-Own-Key (BYOK) Gemini API isolation.",
        "customer_action": "Open /dashboard/#portal -> Sign in -> Submit target domain & priority goals",
        "endpoint": "POST /v1/auth/login  |  POST /v1/me/pilot/intake",
        "screenshot": f"{MEDIA_BASE}/screenshots/01-customer-portal.png",
        "alt": "AskforWrite Customer Self-Service Portal workspace",
    },
    {
        "step": "03",
        "short_title": "Run AI Agents & Tools",
        "title": "Execute Entitled AI Agents Directly From Browser or REST API",
        "description": "Select an entitled specialist agent (SEO/GEO Copilot, SMB Discovery, StockSense Warehouse AI, Produce Vision, Field Force) inside the Agent Run Console, choose Simulation or HITL Live mode, and inspect the 18-Field Evidence Drawer.",
        "customer_action": "Open Agent Run Console -> Select AI Agent -> Click Run Agent -> Inspect Evidence",
        "endpoint": "POST /v1/me/use-service  |  POST /v1/cw/runs/execute",
        "screenshot": f"{MEDIA_BASE}/screenshots/02-customer-agent-console.png",
        "alt": "AskforWrite Customer Agent Run Console and Execution Evidence Drawer",
    },
    {
        "step": "04",
        "short_title": "Review & 1-Click Approve",
        "title": "Review Every External Draft Inside the HITL Approval Gate",
        "description": "Nothing goes out unreviewed. Outbound outreach emails, WordPress articles, and proposals wait in your Approvals queue until you inspect the exact copy and click Approve (which auto-dispatches cleanly) or Reject.",
        "customer_action": "Open Approvals -> Inspect staged draft -> Click Approve & Dispatch or Request Revision",
        "endpoint": "GET /v1/approvals?status=PENDING  |  POST /v1/approvals/{id}/decision",
        "screenshot": f"{MEDIA_BASE}/screenshots/04-hitl-approvals.png",
        "alt": "AskforWrite Human-in-the-Loop Approval Gate screen",
    },
    {
        "step": "05",
        "short_title": "Accept & Verify Proof",
        "title": "Accept Deliverables & Verify Cryptographic ECDSA TrustBlock Receipts",
        "description": "Review QA-checked deliverables in your Customer Portal, click Accept (or request up to 2 revision rounds on pilots), and verify immutable NIST P-256 cryptographic proofs in the Trust Ledger.",
        "customer_action": "Click Accept Deliverable -> Audit Merkle Chain -> Export Compliance Report",
        "endpoint": "POST /v1/me/deliveries/{id}/respond  |  GET /v1/trust/verify",
        "screenshot": f"{MEDIA_BASE}/screenshots/07-trust-ledger.png",
        "alt": "AskforWrite ECDSA NIST P-256 Cryptographic Trust Ledger screen",
    },
]

SKU_SCREENSHOT_MAP: dict[str, dict[str, str]] = {
    "managed_seo_content_pilot": {
        "src": f"{MEDIA_BASE}/screenshots/05-growth-seo-suite.png",
        "alt": "AskforWrite Managed SEO & GEO Growth Suite interface",
        "label": "Live Growth & SEO/GEO Copilot Workspace",
        "video_id": "customer-workspace",
    },
    "seo_blog_copilot": {
        "src": f"{MEDIA_BASE}/screenshots/05-growth-seo-suite.png",
        "alt": "AskforWrite SEO and GEO Blog Copilot screen",
        "label": "SEO/GEO Content & Schema.org Studio",
        "video_id": "customer-workspace",
    },
    "marketing_suite": {
        "src": f"{MEDIA_BASE}/screenshots/05-growth-seo-suite.png",
        "alt": "AskforWrite Omnichannel Marketing Suite screen",
        "label": "Omnichannel Campaign & Pixel AI Studio",
        "video_id": "customer-workspace",
    },
    "pixel_ai_pack": {
        "src": f"{MEDIA_BASE}/screenshots/05-growth-seo-suite.png",
        "alt": "AskforWrite Pixel AI Creative Studio screen",
        "label": "Pixel AI Creative Spec Studio",
        "video_id": "customer-workspace",
    },
    "growth_all_in_one": {
        "src": f"{MEDIA_BASE}/screenshots/03-command-center.png",
        "alt": "AskforWrite AI Command Center and Growth Suite dock",
        "label": "Unified Command Center & Autonomous Growth Suite",
        "video_id": "checkout-governance",
    },
    "warehouse_automation": {
        "src": f"{MEDIA_BASE}/screenshots/06-stocksense-inventory.png",
        "alt": "AskforWrite Warehouse StockSense AI inventory replenishment screen",
        "label": "Warehouse StockSense AI — Pareto ABC-XYZ & EOQ/ROP Console",
        "video_id": "customer-workspace",
    },
    "operations_suite": {
        "src": f"{MEDIA_BASE}/screenshots/06-stocksense-inventory.png",
        "alt": "AskforWrite Operations Suite vertical AI console",
        "label": "Operations Suite — Logistics, Field & Vertical AI Engines",
        "video_id": "checkout-governance",
    },
    "trust_engine": {
        "src": f"{MEDIA_BASE}/screenshots/07-trust-ledger.png",
        "alt": "AskforWrite ECDSA NIST P-256 Trust Ledger verification screen",
        "label": "ECDSA NIST P-256 Merkle Cryptographic Trust Ledger",
        "video_id": "checkout-governance",
    },
    "field_force": {
        "src": f"{MEDIA_BASE}/screenshots/03-command-center.png",
        "alt": "AskforWrite Field Force GPS and Operations Command Center",
        "label": "Zero-Trust Field Force & Command Center",
        "video_id": "checkout-governance",
    },
}


def get_screenshot_for_sku(sku_key: str) -> dict[str, str]:
    """Return the best matching direct system screenshot metadata for any catalog SKU."""
    return SKU_SCREENSHOT_MAP.get(
        (sku_key or "").strip().lower(),
        {
            "src": f"{MEDIA_BASE}/screenshots/01-customer-portal.png",
            "alt": "AskforWrite AI Company OS Customer Self-Service Portal",
            "label": "AskforWrite AI Company OS — Customer Workspace",
            "video_id": "customer-workspace",
        },
    )


def render_inline_product_preview_section(sku_key: str, product_name: str) -> str:
    """Render a crisp real-system screenshot + interactive walkthrough video preview block for /services/* and /solutions/*."""
    shot = get_screenshot_for_sku(sku_key)
    video = DEMO_VIDEOS[0] if shot.get("video_id") == "customer-workspace" else DEMO_VIDEOS[1]
    safe_name = html.escape(product_name)
    return f"""
    <section class="media-showcase-box" style="margin:28px 0;background:linear-gradient(145deg,rgba(15,23,42,0.96),rgba(17,24,39,0.92));border:1px solid rgba(56,189,248,0.28);border-radius:16px;padding:24px;">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:16px;">
        <div>
          <span style="display:inline-block;font-size:0.72rem;font-weight:700;letter-spacing:0.06em;background:rgba(56,189,248,0.14);color:#38bdf8;padding:3px 10px;border-radius:999px;">REAL SYSTEM SCREENSHOT &amp; CUSTOMER DEMO</span>
          <h2 style="margin:8px 0 4px;border:none;padding:0;color:#fff;font-size:1.35rem;">See How Customers Operate {safe_name} Live</h2>
          <p style="margin:0;color:#94a3b8;font-size:0.9rem;">Direct capture from the live AskforWrite AI Company OS interface—plus a playable customer walkthrough video.</p>
        </div>
        <a href="/#demo" style="background:rgba(79,70,229,0.2);border:1px solid rgba(99,102,241,0.5);color:#c7d2fe;text-decoration:none;padding:9px 14px;border-radius:9px;font-weight:700;font-size:0.84rem;">Open Full Interactive Tour →</a>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(290px,100%),1fr));gap:18px;align-items:start;">
        <figure style="margin:0;background:#070b14;border:1px solid #1e293b;border-radius:12px;overflow:hidden;">
          <div style="display:flex;align-items:center;gap:6px;padding:8px 12px;background:#0f172a;border-bottom:1px solid #1e293b;font-size:0.74rem;color:#94a3b8;">
            <span style="width:8px;height:8px;border-radius:50%;background:#ef4444;display:inline-block;"></span>
            <span style="width:8px;height:8px;border-radius:50%;background:#f59e0b;display:inline-block;"></span>
            <span style="width:8px;height:8px;border-radius:50%;background:#22c55e;display:inline-block;"></span>
            <span style="margin-left:6px;font-family:monospace;">os.askforwrite.com/dashboard/</span>
          </div>
          <img src="{html.escape(shot['src'])}" alt="{html.escape(shot['alt'])}" loading="lazy" style="width:100%;height:auto;display:block;" />
          <figcaption style="padding:10px 14px;font-size:0.82rem;color:#cbd5e1;border-top:1px solid #1e293b;"><strong>Direct Screenshot:</strong> {html.escape(shot['label'])}</figcaption>
        </figure>
        <div style="background:#070b14;border:1px solid #1e293b;border-radius:12px;overflow:hidden;">
          <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 12px;background:#0f172a;border-bottom:1px solid #1e293b;font-size:0.74rem;color:#93c5fd;font-weight:700;">
            <span>▶ {html.escape(video['title'])}</span>
            <span style="color:#94a3b8;">{html.escape(video['duration'])}</span>
          </div>
          <video controls playsinline preload="metadata" poster="{html.escape(video['poster'])}" style="width:100%;height:auto;display:block;background:#020617;">
            <source src="{html.escape(video['webm'])}" type="video/webm" />
          </video>
          <div style="padding:10px 14px;font-size:0.82rem;color:#94a3b8;border-top:1px solid #1e293b;">{html.escape(video['summary'])}</div>
        </div>
      </div>
    </section>
    """
