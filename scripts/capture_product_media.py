"""Reproducible real-system screenshot & customer walkthrough video generator.

Boots an isolated local AskforWrite AI Company OS server backed by a temporary SQLite DB
with realistic demo workspace data (never touching production Neon DB or live credentials),
captures 8 crisp 1440x900 direct system PNG screenshots, and records 2 smooth 1280x720
customer-perspective walkthrough videos (MP4 H.264 + WebM + poster PNGs) stored in
app/dashboard/media/.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from PIL import Image
from playwright.sync_api import Browser, Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
MEDIA_ROOT = REPO_ROOT / "app" / "dashboard" / "media"
SHOTS_DIR = MEDIA_ROOT / "screenshots"
VIDEOS_DIR = MEDIA_ROOT / "videos"

OWNER_KEY = "demo-owner-key-capture-must-be-32ch!!"
MANAGER_KEY = "demo-mgr-key-capture-must-be-32char!!"
JWT_SECRET = "demo-jwt-secret-capture-32-chars-min!"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _find_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        candidates = sorted(Path(local_app, "ms-playwright").rglob("*ffmpeg*.exe"))
        if candidates:
            return str(candidates[-1])
    raise RuntimeError("ffmpeg binary not found (checked PATH and LOCALAPPDATA/ms-playwright)")


def _optimize_png(path: Path, max_width: int = 1280) -> None:
    """Resize cleanly and quantize/compress PNG while preserving sharp UI text."""
    with Image.open(path) as img:
        if img.width > max_width:
            ratio = max_width / float(img.width)
            img = img.resize((max_width, int(round(img.height * ratio))), Image.Resampling.LANCZOS)
        # Convert to adaptive 256-color palette (fast, sharp UI text, 3-4x smaller!)
        rgb = img.convert("RGB")
        pal = rgb.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        pal.save(path, format="PNG", optimize=True)


def _inject_caption_hud(page: Page, step_badge: str, headline: str, subline: str) -> None:
    """Inject a sleek floating caption HUD at bottom of viewport during video recording."""
    page.evaluate(
        """([badge, title, sub]) => {
            let hud = document.getElementById('afw-demo-hud');
            if (!hud) {
                hud = document.createElement('div');
                hud.id = 'afw-demo-hud';
                Object.assign(hud.style, {
                    position: 'fixed',
                    left: '50%',
                    bottom: '22px',
                    transform: 'translateX(-50%)',
                    zIndex: '999999',
                    maxWidth: '880px',
                    width: 'calc(100% - 64px)',
                    background: 'rgba(6, 10, 22, 0.92)',
                    border: '1px solid rgba(56, 189, 248, 0.55)',
                    boxShadow: '0 18px 50px rgba(0, 0, 0, 0.65), 0 0 0 1px rgba(99, 102, 241, 0.25)',
                    borderRadius: '14px',
                    padding: '13px 20px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '14px',
                    backdropFilter: 'blur(12px)',
                    fontFamily: 'system-ui, -apple-system, Segoe UI, sans-serif',
                    pointerEvents: 'none',
                    transition: 'opacity 0.25s ease',
                });
                document.body.appendChild(hud);
            }
            hud.innerHTML = `
                <span style="background:linear-gradient(135deg,#4f46e5,#06b6d4);color:#fff;font-weight:800;font-size:12px;letter-spacing:0.06em;padding:5px 11px;border-radius:999px;white-space:nowrap;">${badge}</span>
                <div style="min-width:0;">
                    <div style="color:#ffffff;font-weight:700;font-size:15px;line-height:1.25;">${title}</div>
                    <div style="color:#94a3b8;font-size:12.5px;line-height:1.35;margin-top:2px;">${sub}</div>
                </div>
            `;
        }""",
        [step_badge, headline, subline],
    )


def _highlight_and_click(page: Page, selector: str, pause_before: float = 0.65, pause_after: float = 1.0) -> None:
    """Highlight an element with a visible focus ring before clicking so viewers track every step."""
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=15000)
    loc.scroll_into_view_if_needed()
    try:
        loc.evaluate(
            """el => {
                el.dataset._origShadow = el.style.boxShadow || '';
                el.dataset._origOutline = el.style.outline || '';
                el.style.outline = '3px solid #38bdf8';
                el.style.boxShadow = '0 0 0 6px rgba(56, 189, 248, 0.32)';
            }"""
        )
    except Exception:
        pass
    time.sleep(pause_before)
    loc.click()
    try:
        loc.evaluate(
            """el => {
                el.style.outline = el.dataset._origOutline || '';
                el.style.boxShadow = el.dataset._origShadow || '';
            }"""
        )
    except Exception:
        pass
    time.sleep(pause_after)


def _seed_demo_workspace(base_url: str) -> dict[str, str]:
    """Seed realistic customer + owner operational workspace data."""
    owner_h = {"X-API-Key": OWNER_KEY, "X-Correlation-ID": "media-seed-owner"}
    with httpx.Client(base_url=base_url, timeout=20.0) as client:
        # 1. Primary Customer Organization: Vertex Digital Studio
        reg = client.post(
            "/v1/auth/register",
            json={
                "email": "ops@vertexdigital.in",
                "password": "DemoCustomer!2026",
                "full_name": "Priya Nair",
                "company_name": "Vertex Digital Studio",
                "role": "customer",
            },
        )
        assert reg.status_code in (200, 201), reg.text
        org_id = reg.json()["org_id"]

        # 2. Second Organization for rich multi-tenant Owner dashboard
        reg2 = client.post(
            "/v1/auth/register",
            json={
                "email": "ops@kaverilogistics.in",
                "password": "DemoCustomer!2026",
                "full_name": "Rohan Mehta",
                "company_name": "Kaveri ColdChain Logistics",
                "role": "customer",
            },
        )
        assert reg2.status_code in (200, 201), reg2.text
        org2_id = reg2.json()["org_id"]

        # 3. Ensure CS account + Growth Suite upgrade + confirmed renewal
        client.post(
            f"/v1/cs/customers/{org_id}/ensure",
            json={"sku_key": "managed_seo_content_pilot", "primary_contact_name": "Priya Nair"},
            headers=owner_h,
        )
        client.post(
            f"/v1/cs/subscriptions/{org_id}/plan-change",
            headers=owner_h,
            json={"action": "upgrade", "new_sku_key": "growth", "billing_interval": "monthly", "currency": "INR"},
        )
        client.post(
            f"/v1/cs/subscriptions/{org_id}/events",
            headers=owner_h,
            json={
                "event_type": "subscription_renewed",
                "target_state": "ACTIVE",
                "idempotency_key": f"demo-sub-{uuid.uuid4().hex[:8]}",
                "billing_category": "RENEWAL_CONFIRMED",
                "is_provider_confirmed": True,
                "provider": "razorpay",
                "provider_subscription_id": "sub_vertex_growth_01",
                "internal_sku": "growth",
                "billing_interval": "monthly",
                "amount": 6999.0,
                "currency": "INR",
                "renewal_date": (datetime.now(UTC) + timedelta(days=27)).isoformat(),
            },
        )

        # 4. Seed two deliverables: one DELIVERED (ready for customer Accept), one QUALITY_REVIEW
        d1 = client.post(
            "/v1/cs/deliveries",
            headers=owner_h,
            json={
                "org_id": org_id,
                "title": "Technical SEO & GEO Baseline Audit (vertexdigital.in)",
                "original_requirement": "Complete 14-point technical SEO, Schema.org FAQPage, and /llms.txt readiness audit",
                "approved_scope": ["Technical Crawl & Core Web Vitals", "Schema.org JSON-LD Plan", "/llms.txt Manifest"],
                "sku_key": "managed_seo_content_pilot",
                "service_id": "seo_blog_copilot",
            },
        )
        d1_id = d1.json()["delivery_id"]
        for st in ("IN_PROGRESS", "QUALITY_REVIEW"):
            client.post(f"/v1/cs/deliveries/{d1_id}/transition", headers=owner_h, json={"target_state": st, "note": st})
        client.post(
            f"/v1/cs/deliveries/{d1_id}/qa-review",
            headers=owner_h,
            json={
                "passed": True,
                "checks": [
                    {"name": "schema_json_ld_valid", "passed": True},
                    {"name": "llms_txt_verified", "passed": True},
                ],
                "output_artifacts": {"report_url": "https://os.askforwrite.com/services/managed_seo_content_pilot"},
            },
        )
        client.post(
            f"/v1/cs/deliveries/{d1_id}/transition",
            headers=owner_h,
            json={"target_state": "DELIVERED", "note": "Ready for customer review & acceptance"},
        )

        d2 = client.post(
            "/v1/cs/deliveries",
            headers=owner_h,
            json={
                "org_id": org_id,
                "title": "2x 1,500-Word Commercial SEO/GEO Articles + JSON-LD",
                "original_requirement": "Two human-edited authority articles staged as WordPress drafts",
                "approved_scope": ["Pillar Guide #1", "Comparison Guide #2", "FAQPage + Article JSON-LD"],
                "sku_key": "managed_seo_content_pilot",
                "service_id": "seo_blog_copilot",
            },
        )
        d2_id = d2.json()["delivery_id"]
        client.post(f"/v1/cs/deliveries/{d2_id}/transition", headers=owner_h, json={"target_state": "IN_PROGRESS", "note": "Drafting"})

        # 5. Seed real SMB Discovery + Manager workflow -> populates Leads, Approvals & Trust Ledger
        client.post(
            "/v1/manager/execute",
            headers=owner_h,
            json={
                "objective": "Identify Indian WordPress B2B agencies needing SEO/GEO automation",
                "limit": 5,
                "idempotency_key": f"demo-mgr-{uuid.uuid4().hex[:8]}",
            },
        )
        # Seed a pending HITL approval card
        client.post(
            f"/v1/cs/subscriptions/{org_id}/refund",
            headers=owner_h,
            json={
                "amount_inr": 499.0,
                "currency": "INR",
                "reason": "HITL Governance Demo — Owner review before any billing adjustment",
            },
        )
        # Seed a live SEO draft awaiting HITL approval
        client.post(
            "/v1/seo/draft",
            headers=owner_h,
            json={
                "target_network": "askforwrite.com",
                "keywords": ["AI Company OS", "HITL Multi-Agent Governance", "GEO Optimization"],
                "idempotency_key": f"demo-seo-{uuid.uuid4().hex[:8]}",
            },
        )
        # Trigger StockSense inventory analysis to populate Trust Ledger blocks
        client.post(
            "/v1/inventory/analyze",
            headers=owner_h,
            json={
                "warehouse_name": "Jaipur Dark-Store Hub #1",
                "items": [
                    {"sku": "SKU-COLD-101", "name": "Organic Alphonso Crate 5kg", "current_stock": 14, "safety_stock": 40, "annual_demand": 4800, "unit_cost": 850, "lead_time_days": 3},
                    {"sku": "SKU-FMCG-204", "name": "Cold-Pressed Mustard Oil 1L", "current_stock": 180, "safety_stock": 120, "annual_demand": 9200, "unit_cost": 210, "lead_time_days": 5},
                    {"sku": "SKU-PACK-309", "name": "Insulated Export Corrugated Box", "current_stock": 22, "safety_stock": 75, "annual_demand": 12000, "unit_cost": 48, "lead_time_days": 4},
                    {"sku": "SKU-SLOW-412", "name": "Legacy Promo Display Stand", "current_stock": 310, "safety_stock": 20, "annual_demand": 60, "unit_cost": 650, "lead_time_days": 14},
                ],
            },
        )

        # Compute health & growth signals for Vertex Digital Studio
        client.get(f"/v1/cs/customers/{org_id}/health", headers=owner_h)
        client.post(f"/v1/cs/growth/{org_id}/evaluate", headers=owner_h)

        return {
            "customer_email": "ops@vertexdigital.in",
            "customer_password": "DemoCustomer!2026",
            "org_id": org_id,
            "org2_id": org2_id,
        }


def _block_external_fonts(context) -> None:
    context.route(
        re.compile(r"^https?://fonts\.(googleapis|gstatic)\.com/"),
        lambda route: route.fulfill(status=200, content_type="text/css", body=""),
    )


def _capture_screenshots(browser: Browser, base_url: str, seeded: dict[str, str]) -> None:
    """Capture 8 high-resolution, sharp direct system PNG screenshots."""
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    _block_external_fonts(ctx)
    page = ctx.new_page()

    try:
        # ── A. Customer Perspective Screens ──────────────────────────────
        page.goto(f"{base_url}/dashboard/", wait_until="domcontentloaded")
        page.locator("#auth-gate-overlay").wait_for(state="visible")
        page.fill("#login-email", seeded["customer_email"])
        page.fill("#login-password", seeded["customer_password"])
        page.click("#btn-customer-login")
        page.locator("#auth-gate-overlay").wait_for(state="hidden")
        page.locator("#portal-p3-deliveries-list").wait_for(state="visible")
        time.sleep(1.2)

        # 01: Customer Self-Service Portal
        _hide_toasts(page)
        p1 = SHOTS_DIR / "01-customer-portal.png"
        page.screenshot(path=str(p1), full_page=False)
        _optimize_png(p1)
        print("Saved:", p1.name)

        # 02: Customer Agent Run Console + Live Execution Evidence Drawer
        page.click("#nav-cw-run-console")
        page.locator("#page-cw-run-console.active").wait_for(state="visible")
        page.locator("#cw-run-agent-select option[value='discovery_sdr_agent']").wait_for(state="attached")
        page.select_option("#cw-run-agent-select", "discovery_sdr_agent")
        page.select_option("#cw-run-mode-select", "SIMULATION")
        page.click("#btn-cw-execute-agent")
        page.locator("#btn-cw-inspect-last-evidence").wait_for(state="visible", timeout=15000)
        page.click("#btn-cw-inspect-last-evidence")
        page.locator("#cw-evidence-drawer").wait_for(state="visible")
        time.sleep(0.8)
        p2 = SHOTS_DIR / "02-customer-agent-console.png"
        page.screenshot(path=str(p2), full_page=False)
        _optimize_png(p2)
        print("Saved:", p2.name)
        page.click("#btn-cw-close-evidence")

        # Logout customer -> login as Owner for command center, HITL, growth, vertical AI & trust ledger
        page.click("#btn-logout")
        page.locator("#auth-gate-overlay").wait_for(state="visible")
        page.click("#auth-tab-btn-owner")
        page.fill("#auth-owner-key", OWNER_KEY)
        page.click("#btn-owner-unlock")
        page.locator("#auth-gate-overlay").wait_for(state="hidden")
        time.sleep(1.4)

        # 03: Command Center & Service Tools Dock
        _hide_toasts(page)
        p3 = SHOTS_DIR / "03-command-center.png"
        page.screenshot(path=str(p3), full_page=False)
        _optimize_png(p3)
        print("Saved:", p3.name)

        # 04: HITL Approvals Queue
        page.click("#nav-approvals")
        page.locator("#page-approvals.active").wait_for(state="visible")
        time.sleep(1.0)
        p4 = SHOTS_DIR / "04-hitl-approvals.png"
        page.screenshot(path=str(p4), full_page=False)
        _optimize_png(p4)
        print("Saved:", p4.name)

        # 05: Autonomous Growth, SEO/GEO & Pixel AI Suite
        page.click("#nav-growth")
        page.locator("#page-growth.active").wait_for(state="visible")
        time.sleep(1.0)
        p5 = SHOTS_DIR / "05-growth-seo-suite.png"
        page.screenshot(path=str(p5), full_page=False)
        _optimize_png(p5)
        print("Saved:", p5.name)

        # 06: Vertical Operations AI — Warehouse StockSense
        page.click("#nav-inventory")
        page.locator("#page-inventory.active").wait_for(state="visible")
        # Trigger UI analyze button if available so live results appear
        btn_inv = page.locator("#page-inventory button.primary-btn").first
        if btn_inv.is_visible():
            try:
                btn_inv.click()
                time.sleep(1.2)
            except Exception:
                pass
        _hide_toasts(page)
        p6 = SHOTS_DIR / "06-stocksense-inventory.png"
        page.screenshot(path=str(p6), full_page=False)
        _optimize_png(p6)
        print("Saved:", p6.name)

        # 07: ECDSA NIST P-256 Trust Ledger
        page.click("#nav-trust-chain")
        page.locator("#page-trust-chain.active").wait_for(state="visible")
        verify_btn = page.locator("#page-trust-chain button:has-text('Verify')").first
        if verify_btn.is_visible():
            try:
                verify_btn.click()
                time.sleep(1.0)
            except Exception:
                pass
        _hide_toasts(page)
        p7 = SHOTS_DIR / "07-trust-ledger.png"
        page.screenshot(path=str(p7), full_page=False)
        _optimize_png(p7)
        print("Saved:", p7.name)

        # 08: Verified DirectPay Checkout (14-Day Managed SEO Pilot)
        page.goto(f"{base_url}/v1/pay/checkout?package=managed_seo_content_pilot&company=Vertex+Digital+Studio", wait_until="domcontentloaded")
        time.sleep(0.8)
        p8 = SHOTS_DIR / "08-directpay-checkout.png"
        page.screenshot(path=str(p8), full_page=False)
        _optimize_png(p8)
        print("Saved:", p8.name)
    finally:
        ctx.close()


def _hide_toasts(page: Page) -> None:
    try:
        page.evaluate("() => { document.querySelectorAll('.toast').forEach(e => e.remove()); }")
    except Exception:
        pass


def _transcode_video(ffmpeg_bin: str, raw_webm: Path, out_mp4: Path, out_webm: Path) -> None:
    """Convert raw Playwright WebM into crisp, fast-loading VP9 WebM (+ MP4 container fallback)."""
    # 1. Crisp VP9 WebM (supported natively in Chrome, Edge, Firefox, Android, Safari 16+/iOS 17+)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(raw_webm),
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "32",
            "-b:v",
            "0",
            "-deadline",
            "good",
            "-cpu-used",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "24",
            "-an",
            str(out_webm),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # 2. Stream-copy VP9 into faststart MP4 container for players preferring .mp4
    try:
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                str(out_webm),
                "-c:v",
                "copy",
                "-movflags",
                "+faststart",
                "-an",
                str(out_mp4),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        # If MP4 mux fails for any reason, remove partial file cleanly (WebM source remains primary)
        if out_mp4.exists():
            out_mp4.unlink()


def _record_walkthrough_videos(browser: Browser, base_url: str, seeded: dict[str, str], ffmpeg_bin: str) -> None:
    """Record 2 crisp 1280x720 walkthrough videos showing customer operation & governance."""
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="afw_video_raw_") as raw_dir:
        # ── VIDEO 1: Customer Perspective — Daily Workspace Operation ────
        ctx1 = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=raw_dir,
            record_video_size={"width": 1280, "height": 720},
        )
        _block_external_fonts(ctx1)
        page1 = ctx1.new_page()
        try:
            page1.goto(f"{base_url}/dashboard/", wait_until="domcontentloaded")
            page1.locator("#auth-gate-overlay").wait_for(state="visible")
            _inject_caption_hud(
                page1,
                "STEP 1 / 4",
                "Customer Portal Sign-In (Tenant-Isolated Workspace)",
                "Every customer receives a private org workspace with role-based access & BYOK Gemini key isolation.",
            )
            time.sleep(1.5)
            page1.fill("#login-email", seeded["customer_email"])
            page1.fill("#login-password", seeded["customer_password"])
            _highlight_and_click(page1, "#btn-customer-login", pause_before=0.7, pause_after=1.4)
            page1.locator("#auth-gate-overlay").wait_for(state="hidden")
            page1.locator("#portal-p3-deliveries-list").wait_for(state="visible")

            _inject_caption_hud(
                page1,
                "STEP 2 / 4",
                "Review AI Deliverables & Accept With 1 Click",
                "Track onboarding milestones, inspect QA-verified SEO/GEO deliverables, and approve work directly.",
            )
            time.sleep(1.4)
            # Scroll to deliverables & click Accept
            accept_btn = page1.locator("#portal-p3-deliveries-list button:has-text('Accept')")
            if accept_btn.count() >= 1:
                _highlight_and_click(page1, "#portal-p3-deliveries-list button:has-text('Accept')", pause_before=0.8, pause_after=1.6)
            else:
                page1.evaluate("window.scrollBy({top: 320, behavior: 'smooth'})")
                time.sleep(1.6)

            _inject_caption_hud(
                page1,
                "STEP 3 / 4",
                "Transparent Subscription Plans & Credit Ledger",
                "Switch clustered plans anytime, monitor monthly lead & AI run quotas, and download invoices.",
            )
            _highlight_and_click(page1, "#nav-cw-billing", pause_before=0.6, pause_after=1.8)

            _inject_caption_hud(
                page1,
                "STEP 4 / 4",
                "Execute Entitled AI Agents & Inspect Cryptographic Evidence",
                "Run specialist agents on demand and verify every execution inside the 15-field Evidence Drawer.",
            )
            _highlight_and_click(page1, "#nav-cw-run-console", pause_before=0.6, pause_after=1.0)
            page1.locator("#cw-run-agent-select option[value='discovery_sdr_agent']").wait_for(state="attached")
            page1.select_option("#cw-run-agent-select", "discovery_sdr_agent")
            page1.select_option("#cw-run-mode-select", "SIMULATION")
            _highlight_and_click(page1, "#btn-cw-execute-agent", pause_before=0.6, pause_after=1.5)
            page1.locator("#btn-cw-inspect-last-evidence").wait_for(state="visible", timeout=15000)
            _highlight_and_click(page1, "#btn-cw-inspect-last-evidence", pause_before=0.6, pause_after=2.2)

            poster1 = VIDEOS_DIR / "poster-customer-demo.png"
            page1.screenshot(path=str(poster1))
            _optimize_png(poster1, max_width=1280)
            video1_path = Path(page1.video.path())
        finally:
            ctx1.close()

        _transcode_video(
            ffmpeg_bin,
            video1_path,
            VIDEOS_DIR / "customer-workspace-demo.mp4",
            VIDEOS_DIR / "customer-workspace-demo.webm",
        )
        mp4_1 = VIDEOS_DIR / "customer-workspace-demo.mp4"
        webm_1 = VIDEOS_DIR / "customer-workspace-demo.webm"
        print(
            "Video 1 ready:",
            f"MP4={mp4_1.stat().st_size // 1024 if mp4_1.exists() else 0}KB",
            f"WebM={webm_1.stat().st_size // 1024 if webm_1.exists() else 0}KB",
        )

        # ── VIDEO 2: End-to-End Checkout -> Command Center -> HITL -> Trust Ledger ─
        ctx2 = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=raw_dir,
            record_video_size={"width": 1280, "height": 720},
        )
        _block_external_fonts(ctx2)
        page2 = ctx2.new_page()
        try:
            page2.goto(
                f"{base_url}/v1/pay/checkout?package=managed_seo_content_pilot&company=Vertex+Digital+Studio",
                wait_until="domcontentloaded",
            )
            _inject_caption_hud(
                page2,
                "STEP 1 / 4",
                "Verified Checkout — Zero-Fee UPI QR, Razorpay & PayPal",
                "Select a 14-Day Pilot (₹4,999) or Clustered Plan and settle cleanly via DirectPay UPI, Bank Wire, or Card.",
            )
            time.sleep(2.2)
            page2.evaluate("window.scrollBy({top: 260, behavior: 'smooth'})")
            time.sleep(1.6)

            page2.goto(f"{base_url}/dashboard/", wait_until="domcontentloaded")
            page2.locator("#auth-gate-overlay").wait_for(state="visible")
            page2.click("#auth-tab-btn-owner")
            page2.fill("#auth-owner-key", OWNER_KEY)
            page2.click("#btn-owner-unlock")
            page2.locator("#auth-gate-overlay").wait_for(state="hidden")
            time.sleep(1.2)

            _inject_caption_hud(
                page2,
                "STEP 2 / 4",
                "Unified AI Command Center & 9 Specialist AI Employees",
                "Launch 12 connected commercial tools, scan prospect websites in 60s, and monitor live revenue pipeline.",
            )
            time.sleep(2.2)
            page2.evaluate("window.scrollBy({top: 320, behavior: 'smooth'})")
            time.sleep(1.5)

            _inject_caption_hud(
                page2,
                "STEP 3 / 4",
                "Human-in-the-Loop (HITL) Approval Gate — Zero Rogue Actions",
                "Every outbound email, WordPress publish, and billing action pauses for your 1-click approval.",
            )
            _highlight_and_click(page2, "#nav-approvals", pause_before=0.5, pause_after=1.5)
            approve_btn = page2.locator("#approvals-grid .action-btn.approve")
            if approve_btn.count() >= 1:
                _highlight_and_click(page2, "#approvals-grid .action-btn.approve", pause_before=0.6, pause_after=0.9)
                page2.locator("#modal-overlay").wait_for(state="visible")
                page2.fill("#decision-note", "Approved in live customer demo walkthrough")
                _highlight_and_click(page2, "#btn-approve", pause_before=0.5, pause_after=1.4)

            _inject_caption_hud(
                page2,
                "STEP 4 / 4",
                "Immutable ECDSA NIST P-256 Cryptographic Trust Ledger",
                "Every approved workflow, deliverable, and payment settlement is sealed into a verifiable Merkle chain.",
            )
            _highlight_and_click(page2, "#nav-trust-chain", pause_before=0.6, pause_after=2.6)

            poster2 = VIDEOS_DIR / "poster-governance-demo.png"
            page2.screenshot(path=str(poster2))
            _optimize_png(poster2, max_width=1280)
            video2_path = Path(page2.video.path())
        finally:
            ctx2.close()

        _transcode_video(
            ffmpeg_bin,
            video2_path,
            VIDEOS_DIR / "checkout-to-governance-demo.mp4",
            VIDEOS_DIR / "checkout-to-governance-demo.webm",
        )
        mp4_2 = VIDEOS_DIR / "checkout-to-governance-demo.mp4"
        webm_2 = VIDEOS_DIR / "checkout-to-governance-demo.webm"
        print(
            "Video 2 ready:",
            f"MP4={mp4_2.stat().st_size // 1024 if mp4_2.exists() else 0}KB",
            f"WebM={webm_2.stat().st_size // 1024 if webm_2.exists() else 0}KB",
        )


def main() -> None:
    ffmpeg_bin = _find_ffmpeg()
    print("Using ffmpeg:", ffmpeg_bin)
    port = _find_free_port()

    with tempfile.TemporaryDirectory(prefix="afw_media_srv_", ignore_cleanup_errors=True) as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_file = (tmp_path / "media_demo.db").as_posix()
        log_file_path = tmp_path / "uvicorn.log"
        runner = tmp_path / "run_srv.py"
        runner.write_text(
            textwrap.dedent(
                f"""
                import sys, dotenv
                dotenv.load_dotenv = lambda *a, **kw: False
                sys.path.insert(0, {str(REPO_ROOT)!r})
                import app.db.models  # noqa: F401
                from app.db.database import Base, engine
                Base.metadata.create_all(bind=engine, checkfirst=True)
                import uvicorn
                uvicorn.run("app.main:app", host="127.0.0.1", port={port}, log_level="warning")
                """
            ).strip(),
            encoding="utf-8",
        )

        env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LOCALAPPDATA", "USERPROFILE", "COMSPEC", "PATHEXT") if k in os.environ}
        env.update(
            {
                "APP_ENV": "development",
                "ALLOW_LIVE_SIDE_EFFECTS": "false",
                "ENABLE_EXTERNAL_SIDE_EFFECTS": "false",
                "ALLOW_SQLITE_TEST": "true",
                "PAYMENT_MODE": "sandbox",
                "PAYMENT_PROVIDER": "sovereign",
                "SMTP_MODE": "sandbox_sink",
                "OUTREACH_DISPATCH_PROVIDER": "mock",
                "DATABASE_URL": f"sqlite:///{db_file}",
                "NEON_DATABASE_URL": "",
                "DATABASE_URL_UNPOOLED": "",
                "OWNER_API_KEY": OWNER_KEY,
                "MANAGER_API_KEY": MANAGER_KEY,
                "JWT_SECRET_KEY": JWT_SECRET,
                "GEMINI_API_KEY": "mock-gemini-key",
                "GOOGLE_API_KEY": "mock-gemini-key",
                "PYTHONIOENCODING": "utf-8",
            }
        )

        log_f = open(log_file_path, "w", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(runner)], cwd=str(REPO_ROOT), env=env, stdout=log_f, stderr=subprocess.STDOUT)
        base_url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    log_f.flush()
                    raise RuntimeError(log_file_path.read_text(encoding="utf-8", errors="ignore"))
                try:
                    if httpx.get(f"{base_url}/health", timeout=1.5).status_code == 200:
                        break
                except Exception:
                    time.sleep(0.2)
            else:
                raise TimeoutError("Demo capture server failed to boot")

            seeded = _seed_demo_workspace(base_url)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    _capture_screenshots(browser, base_url, seeded)
                    _record_walkthrough_videos(browser, base_url, seeded, ffmpeg_bin)
                finally:
                    browser.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            log_f.close()

    print("\nALL MEDIA GENERATED SUCCESSFULLY:")
    for p in sorted(MEDIA_ROOT.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(MEDIA_ROOT)} ({p.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
