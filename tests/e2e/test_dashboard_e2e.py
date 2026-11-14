"""Playwright Browser E2E Verification Suite for AskforWrite AI Company OS (P3.1).

Runs real headless Chromium flows on Desktop (1440x900) and Mobile (390x844)
against an isolated local Uvicorn server backed by a temporary SQLite database
with seeded synthetic data and APP_ENV=development / ALLOW_LIVE_SIDE_EFFECTS=false.

Never touches production Neon PostgreSQL or live .env credentials.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

OWNER_KEY = "e2e-owner-key-synthetic-must-be-32ch!"
MANAGER_KEY = "e2e-mgr-key-synthetic-must-be-32ch!"
JWT_SECRET = "e2e-jwt-secret-must-be-32-chars-min!"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _seed_synthetic_data(base_url: str) -> dict[str, str]:
    """Seed deterministic synthetic orgs, deliverables, renewals, and approvals via API."""
    owner_headers = {"X-API-Key": OWNER_KEY, "X-Correlation-ID": "e2e-seed-owner"}
    mgr_headers = {"X-API-Key": MANAGER_KEY, "X-Correlation-ID": "e2e-seed-mgr"}

    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        # 1. Primary agency customer org (seeded with P3 CS account, deliverable, renewal)
        reg_agency = client.post(
            "/v1/auth/register",
            json={
                "email": "agency@acme-synthetic.test",
                "password": "SyntheticPassword!123",
                "full_name": "Asha Synthetic",
                "company_name": "Acme Digital Agency",
                "role": "customer",
            },
        )
        assert reg_agency.status_code in (200, 201), reg_agency.text
        agency = reg_agency.json()
        agency_org_id = agency["org_id"]

        # 2. Empty state org (zero deliverables, zero tickets)
        reg_empty = client.post(
            "/v1/auth/register",
            json={
                "email": "empty@acme-synthetic.test",
                "password": "SyntheticPassword!123",
                "full_name": "Empty Org User",
                "company_name": "Zero State Co",
                "role": "customer",
            },
        )
        assert reg_empty.status_code in (200, 201), reg_empty.text

        # 3. Ensure CS account & onboarding workflow
        ens = client.post(
            f"/v1/cs/customers/{agency_org_id}/ensure",
            json={"sku_key": "managed_seo_content_pilot", "primary_contact_name": "Asha Synthetic"},
            headers=owner_headers,
        )
        assert ens.status_code == 200, ens.text

        onb = client.get(
            f"/v1/cs/customers/{agency_org_id}/onboarding",
            headers=owner_headers,
        )
        assert onb.status_code == 200, onb.text

        # 4. Create a deliverable and advance it cleanly through QA -> DELIVERED for customer acceptance
        d_resp = client.post(
            "/v1/cs/deliveries",
            headers=owner_headers,
            json={
                "org_id": agency_org_id,
                "title": "Technical SEO Baseline Audit",
                "original_requirement": "Deliver 10-point technical SEO & schema baseline audit",
                "approved_scope": ["Crawl report", "Core Web Vitals review"],
                "sku_key": "managed_seo_content_pilot",
                "service_id": "seo_blog_copilot",
            },
        )
        assert d_resp.status_code in (200, 201), d_resp.text
        delivery_id = d_resp.json()["delivery_id"]

        for state in ("IN_PROGRESS", "QUALITY_REVIEW"):
            tr = client.post(
                f"/v1/cs/deliveries/{delivery_id}/transition",
                headers=owner_headers,
                json={"target_state": state, "note": f"E2E seed -> {state}"},
            )
            assert tr.status_code == 200, tr.text

        qa = client.post(
            f"/v1/cs/deliveries/{delivery_id}/qa-review",
            headers=owner_headers,
            json={
                "passed": True,
                "checks": [{"name": "links_verified", "passed": True}],
                "output_artifacts": {"report_url": "https://synthetic-artifact.example.test/seo-audit.pdf"},
            },
        )
        assert qa.status_code == 200, qa.text

        delivered = client.post(
            f"/v1/cs/deliveries/{delivery_id}/transition",
            headers=owner_headers,
            json={"target_state": "DELIVERED", "note": "Ready for customer portal sign-off"},
        )
        assert delivered.status_code == 200, delivered.text

        # 5. Seed subscription profile + confirmed renewal event & compute health + growth
        plan_resp = client.post(
            f"/v1/cs/subscriptions/{agency_org_id}/plan-change",
            headers=owner_headers,
            json={
                "action": "upgrade",
                "new_sku_key": "growth",
                "billing_interval": "monthly",
                "currency": "INR",
            },
        )
        assert plan_resp.status_code == 200, plan_resp.text
        renewal_date = (datetime.now(UTC) + timedelta(days=25)).isoformat()
        sub_ev = client.post(
            f"/v1/cs/subscriptions/{agency_org_id}/events",
            headers=owner_headers,
            json={
                "event_type": "subscription_renewed",
                "target_state": "ACTIVE",
                "idempotency_key": f"e2e-sub-renew-{uuid.uuid4()}",
                "billing_category": "RENEWAL_CONFIRMED",
                "is_provider_confirmed": True,
                "provider": "razorpay",
                "provider_subscription_id": "sub_e2e_synthetic_001",
                "internal_sku": "growth",
                "billing_interval": "monthly",
                "amount": 4999.0,
                "currency": "INR",
                "renewal_date": renewal_date,
            },
        )
        assert sub_ev.status_code == 200, sub_ev.text

        health = client.get(f"/v1/cs/customers/{agency_org_id}/health", headers=owner_headers)
        assert health.status_code == 200, health.text

        growth = client.post(f"/v1/cs/growth/{agency_org_id}/evaluate", headers=owner_headers)
        assert growth.status_code == 200, growth.text

        # 6. Seed a PENDING approval for Founder Approval workflow test via HITL refund gate
        appr = client.post(
            f"/v1/cs/subscriptions/{agency_org_id}/refund",
            headers=owner_headers,
            json={
                "amount_inr": 500.0,
                "currency": "INR",
                "reason": "Synthetic E2E founder approval gate test",
            },
        )
        assert appr.status_code in (200, 201), appr.text
        appr_body = appr.json()

        return {
            "agency_org_id": agency_org_id,
            "agency_email": "agency@acme-synthetic.test",
            "empty_email": "empty@acme-synthetic.test",
            "password": "SyntheticPassword!123",
            "delivery_id": delivery_id,
            "approval_id": appr_body["approval_id"],
        }


@pytest.fixture(scope="module")
def live_e2e_server() -> Generator[dict[str, str], None, None]:
    """Launch an isolated Uvicorn server in a subprocess with clean synthetic SQLite state."""
    port = _find_free_port()
    with tempfile.TemporaryDirectory(prefix="afw_p31_e2e_", ignore_cleanup_errors=True) as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_file = (tmp_path / "e2e_isolated.db").as_posix()
        log_file_path = tmp_path / "uvicorn_e2e.log"
        runner_script = tmp_path / "run_e2e_server.py"
        runner_script.write_text(
            textwrap.dedent(
                f"""
                import sys
                import dotenv
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

        clean_env = {
            key: os.environ[key]
            for key in (
                "PATH",
                "SYSTEMROOT",
                "TEMP",
                "TMP",
                "LOCALAPPDATA",
                "USERPROFILE",
                "COMSPEC",
                "PATHEXT",
            )
            if key in os.environ
        }
        clean_env.update(
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
        proc = subprocess.Popen(
            [sys.executable, str(runner_script)],
            cwd=str(REPO_ROOT),
            env=clean_env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 20.0
            ready = False
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    log_f.flush()
                    raise RuntimeError(
                        f"E2E server exited prematurely: {log_file_path.read_text(encoding='utf-8', errors='ignore')}"
                    )
                try:
                    resp = httpx.get(f"{base_url}/health", timeout=1.5)
                    if resp.status_code == 200:
                        ready = True
                        break
                except Exception:
                    time.sleep(0.2)
            if not ready:
                log_f.flush()
                raise TimeoutError(
                    f"E2E server did not respond on {base_url}/health: "
                    f"{log_file_path.read_text(encoding='utf-8', errors='ignore')}"
                )

            seeded = _seed_synthetic_data(base_url)
            seeded["base_url"] = base_url
            yield seeded
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            log_f.close()


@pytest.fixture(scope="module")
def browser_instance() -> Generator[Browser, None, None]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@contextmanager
def _recorded_page(
    browser: Browser,
    *,
    width: int,
    height: int,
    allowed_5xx_paths: tuple[str, ...] = (),
) -> Generator[tuple[BrowserContext, Page, dict[str, list[str]]], None, None]:
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    telemetry: dict[str, list[str]] = {
        "console_errors": [],
        "page_errors": [],
        "unexpected_5xx": [],
    }
    page.on(
        "console",
        lambda msg: telemetry["console_errors"].append(msg.text) if msg.type == "error" else None,
    )
    page.on("pageerror", lambda err: telemetry["page_errors"].append(str(err)))
    page.on(
        "response",
        lambda resp: (
            telemetry["unexpected_5xx"].append(f"{resp.status} {resp.url}")
            if resp.status >= 500 and not any(p in resp.url for p in allowed_5xx_paths)
            else None
        ),
    )
    try:
        yield context, page, telemetry
    finally:
        context.close()


def _assert_clean_telemetry(telemetry: dict[str, list[str]], *, allow_console_error_substrings: tuple[str, ...] = ()) -> None:
    assert telemetry["page_errors"] == [], f"Uncaught JS pageerror(s): {telemetry['page_errors']}"
    assert telemetry["unexpected_5xx"] == [], f"Unexpected HTTP >=500 response(s): {telemetry['unexpected_5xx']}"
    remaining_console = [
        err for err in telemetry["console_errors"]
        if not any(sub in err for sub in allow_console_error_substrings)
    ]
    assert remaining_console == [], f"Unexpected browser console errors: {remaining_console}"


def test_desktop_auth_empty_error_offline_and_customer_portal_e2e(
    live_e2e_server: dict[str, str],
    browser_instance: Browser,
) -> None:
    """Verify Customer login/logout, invalid creds, unauthorized nav isolation, empty/error/offline states, onboarding, deliverables, and tickets on Desktop."""
    base_url = live_e2e_server["base_url"]

    with _recorded_page(
        browser_instance,
        width=1440,
        height=900,
        allowed_5xx_paths=("/v1/me/support/tickets",),
    ) as (context, page, telemetry):
        page.goto(f"{base_url}/dashboard/", wait_until="domcontentloaded")
        page.locator("#auth-gate-overlay").wait_for(state="visible")

        # 1. Invalid login shows explicit error state
        page.fill("#login-email", live_e2e_server["agency_email"])
        page.fill("#login-password", "WrongPassword!")
        page.click("#btn-customer-login")
        err_msg = page.locator("#auth-gate-message")
        err_msg.wait_for(state="visible")
        assert len(err_msg.inner_text().strip()) > 0
        assert page.locator("#auth-gate-overlay").is_visible()

        # 2. Empty customer org -> verify empty states and unauthorized nav items stay hidden
        page.fill("#login-email", live_e2e_server["empty_email"])
        page.fill("#login-password", live_e2e_server["password"])
        page.click("#btn-customer-login")
        page.locator("#auth-gate-overlay").wait_for(state="hidden")
        page.locator("#portal-p3-deliveries-list").wait_for(state="visible")

        page.locator("#nav-approvals").wait_for(state="visible")
        assert not page.locator("#nav-dashboard").is_visible()
        assert not page.locator("#nav-organizations").is_visible()
        assert not page.locator("#nav-revenue").is_visible()
        assert not page.locator("#nav-commercial-os").is_visible()
        assert not page.locator("#nav-customer-success").is_visible()
        assert "No service deliverables" in page.locator("#portal-p3-deliveries-list").inner_text()
        assert "No support tickets" in page.locator("#portal-p3-tickets-list").inner_text()

        # Subscription & billing contract view works for customer role
        page.click("#nav-cw-billing")
        page.locator("#cw-pricing-contracts-list").wait_for(state="visible")
        contracts_txt = page.locator("#cw-pricing-contracts-list").inner_text().lower()
        assert "launch" in contracts_txt and "growth" in contracts_txt

        # Logout
        page.click("#btn-logout")
        page.locator("#auth-gate-overlay").wait_for(state="visible")

        # 3. Primary agency customer login
        page.fill("#login-email", live_e2e_server["agency_email"])
        page.fill("#login-password", live_e2e_server["password"])
        page.click("#btn-customer-login")
        page.locator("#auth-gate-overlay").wait_for(state="hidden")
        page.locator("#portal-p3-deliveries-list").wait_for(state="visible")

        # Verify onboarding progress task completion advances UI & backend state
        summary_before = page.locator("#portal-p3-onboarding-summary").inner_text()
        complete_btns = page.locator("#portal-p3-onboarding-tasks .portal-task-complete-btn")
        assert complete_btns.count() >= 1
        complete_btns.first.click()
        page.wait_for_function(
            "prev => document.querySelector('#portal-p3-onboarding-summary')?.textContent !== prev",
            arg=summary_before,
        )

        # Verify deliverable customer acceptance flow
        accept_btn = page.locator("#portal-p3-deliveries-list button:has-text('Accept')")
        assert accept_btn.count() == 1
        accept_btn.first.click()
        page.locator("#portal-p3-deliveries-list:has-text('ACCEPTED')").wait_for(state="visible")

        # Verify API failure shows meaningful error state and NO fake success message
        def fail_ticket_post(route):
            if route.request.method == "POST":
                route.fulfill(
                    status=500,
                    content_type="application/json",
                    body='{"detail":"Simulated server error while creating ticket"}',
                )
            else:
                route.continue_()

        page.route("**/v1/me/support/tickets", fail_ticket_post)
        page.fill("#portal-ticket-subject", "GSC Property Verification Help")
        page.fill("#portal-ticket-description", "Need verification token guidance for domain property.")
        page.click("#btn-portal-create-ticket")
        page.locator("#portal-p3-error").wait_for(state="visible")
        assert "Simulated server error" in page.locator("#portal-p3-error").inner_text()

        # Unroute mock failure -> real submission succeeds and persists ticket in UI
        page.unroute("**/v1/me/support/tickets", fail_ticket_post)
        page.click("#btn-portal-create-ticket")
        page.locator("#portal-p3-tickets-list:has-text('GSC Property Verification Help')").wait_for(state="visible")

        # Verify explicit offline mode state (zero simulated success)
        context.set_offline(True)
        page.evaluate("window.dispatchEvent(new Event('offline'))")
        page.locator("#offline-status-banner").wait_for(state="visible")
        assert "BLOCKED" in page.locator("#data-mode-badge").inner_text()
        page.fill("#portal-ticket-subject", "Should Fail Offline")
        page.fill("#portal-ticket-description", "Cannot succeed while offline.")
        page.click("#btn-portal-create-ticket")
        page.locator("#portal-p3-error").wait_for(state="visible")
        assert "Should Fail Offline" not in page.locator("#portal-p3-tickets-list").inner_text()

        context.set_offline(False)
        page.evaluate("window.dispatchEvent(new Event('online'))")
        page.locator("#offline-status-banner").wait_for(state="hidden")

        page.click("#btn-logout")
        page.locator("#auth-gate-overlay").wait_for(state="visible")

        _assert_clean_telemetry(
            telemetry,
            allow_console_error_substrings=(
                "status of 401",
                "status of 500",
                "ERR_INTERNET_DISCONNECTED",
                "Failed to fetch",
                "Billing invoices fetch",
            ),
        )


def test_desktop_owner_lifecycle_delivery_health_tickets_renewals_and_approvals_e2e(
    live_e2e_server: dict[str, str],
    browser_instance: Browser,
) -> None:
    """Verify Owner dashboard, HITL approval flow, CS 360 lifecycle, delivery creation, health score, ticket resolution, and renewals on Desktop."""
    base_url = live_e2e_server["base_url"]
    agency_org_id = live_e2e_server["agency_org_id"]

    with _recorded_page(browser_instance, width=1440, height=900) as (_context, page, telemetry):
        page.goto(f"{base_url}/dashboard/", wait_until="domcontentloaded")
        page.locator("#auth-gate-overlay").wait_for(state="visible")

        # Owner invalid key failure state
        page.click("#auth-tab-btn-owner")
        page.fill("#auth-owner-key", "wrong-owner-key")
        page.click("#btn-owner-unlock")
        page.locator("#auth-gate-message").wait_for(state="visible")
        assert page.locator("#auth-gate-overlay").is_visible()

        # Valid Owner login
        page.fill("#auth-owner-key", OWNER_KEY)
        page.click("#btn-owner-unlock")
        page.locator("#auth-gate-overlay").wait_for(state="hidden")
        page.locator("#nav-customer-success").wait_for(state="visible")

        # Approvals workflow + Empty state check on REJECTED filter
        page.click("#nav-approvals")
        page.locator("#page-approvals.active").wait_for(state="visible")
        page.click("#filter-rejected")
        assert "No approval requests" in page.locator("#approvals-grid").inner_text()

        page.click("#filter-pending")
        approve_btn = page.locator("#approvals-grid .action-btn.approve")
        assert approve_btn.count() >= 1
        approve_btn.first.click()
        page.locator("#modal-overlay").wait_for(state="visible")
        page.fill("#decision-note", "Verified in Playwright P3.1 E2E")
        page.click("#btn-approve")
        page.locator("#modal-overlay").wait_for(state="hidden")
        page.click("#filter-approved")
        page.locator("#approvals-grid:has-text('Subscription Pricing Or Refund Action')").wait_for(state="visible")

        # Customer Success Control Centre
        page.click("#nav-customer-success")
        page.locator("#page-customer-success.active").wait_for(state="visible")
        page.locator("#p3-cc-live-kpis").wait_for(state="visible")

        # Subtab: Customer 360 & Onboarding/Delivery
        page.click('[data-p3tab="customers-delivery"]')
        page.locator("#p3-panel-customers-delivery").wait_for(state="visible")
        page.locator(f"#p3-customers-tbody:has-text('{agency_org_id}')").wait_for(state="visible")

        # Select seeded org and create a new deliverable
        page.fill("#p3-active-org-id", agency_org_id)
        page.click("#btn-p3-refresh-all")
        page.fill("#p3-deliv-title", "Playwright Verified Keyword Map")
        page.fill("#p3-deliv-req", "Provide 15 high-intent keywords mapped to pages")
        page.click("#btn-p3-create-delivery")
        page.locator("#p3-deliveries-tbody:has-text('Playwright Verified Keyword Map')").wait_for(state="visible")

        # Subtab: Health, Support & Improvements
        page.click('[data-p3tab="health-support"]')
        page.locator("#p3-panel-health-support").wait_for(state="visible")
        page.click("#btn-p3-compute-health")
        page.locator("#p3-health-viewer:has-text('Score:')").wait_for(state="visible")
        health_text = page.locator("#p3-health-viewer").inner_text()
        assert any(state in health_text for state in ("HEALTHY", "NEEDS_ATTENTION", "AT_RISK", "INSUFFICIENT_DATA"))

        # Resolve the ticket submitted by the customer earlier
        ticket_row = page.locator("#p3-tickets-tbody tr", has_text="GSC Property Verification Help")
        ticket_row.wait_for(state="visible")
        ticket_row.locator("button:has-text('Resolve')").click()
        page.locator("#p3-tickets-tbody tr:has-text('GSC Property Verification Help'):has-text('RESOLVED')").wait_for(
            state="visible"
        )

        # Subtab: Subscriptions, Growth & Unit Economics
        page.click('[data-p3tab="subs-growth-ue"]')
        page.locator("#p3-panel-subs-growth-ue").wait_for(state="visible")
        page.locator(f"#p3-renewals-tbody:has-text('{agency_org_id}'):has-text('ACTIVE')").wait_for(state="visible")
        page.locator("#p3-ue-viewer:has-text('Net Verified Revenue:')").wait_for(state="visible")

        # Subtab: Ops Readiness, Compliance & 12-Step
        page.click('[data-p3tab="ops-compliance"]')
        page.locator("#p3-panel-ops-compliance").wait_for(state="visible")
        assert len(page.locator("#p3-ops-summary").inner_text().strip()) > 0
        assert len(page.locator("#p3-acceptance-steps-list").inner_text().strip()) > 0

        # Logout
        page.click("#btn-logout")
        page.locator("#auth-gate-overlay").wait_for(state="visible")

        _assert_clean_telemetry(
            telemetry,
            allow_console_error_substrings=("status of 401",),
        )


def test_mobile_viewport_navigation_and_cs_workflows_e2e(
    live_e2e_server: dict[str, str],
    browser_instance: Browser,
) -> None:
    """Verify responsive navigation, mobile drawer open/close, Customer Success views, and Customer Portal on 390x844 mobile viewport."""
    base_url = live_e2e_server["base_url"]

    with _recorded_page(browser_instance, width=390, height=844) as (_context, page, telemetry):
        page.goto(f"{base_url}/dashboard/", wait_until="domcontentloaded")
        page.locator("#auth-gate-overlay").wait_for(state="visible")

        # Owner unlock on mobile
        page.click("#auth-tab-btn-owner")
        page.fill("#auth-owner-key", OWNER_KEY)
        page.click("#btn-owner-unlock")
        page.locator("#auth-gate-overlay").wait_for(state="hidden")

        # Mobile hamburger opens sidebar drawer
        sidebar = page.locator("#sidebar")
        page.click("#menu-toggle")
        assert "open" in (sidebar.get_attribute("class") or "")

        # Clicking nav item navigates and auto-closes sidebar drawer cleanly
        page.click("#nav-customer-success")
        page.locator("#page-customer-success.active").wait_for(state="visible")
        assert not re.search(r"\bopen\b", sidebar.get_attribute("class") or "")

        # Mobile P3 subtabs switch cleanly
        page.click('[data-p3tab="health-support"]')
        page.locator("#p3-panel-health-support").wait_for(state="visible")
        page.click('[data-p3tab="subs-growth-ue"]')
        page.locator("#p3-panel-subs-growth-ue").wait_for(state="visible")

        # Re-open mobile drawer to logout
        page.click("#menu-toggle")
        page.click("#btn-logout")
        page.locator("#auth-gate-overlay").wait_for(state="visible")

        # Customer portal works cleanly on mobile viewport
        page.click("#auth-tab-btn-login")
        page.fill("#login-email", live_e2e_server["agency_email"])
        page.fill("#login-password", live_e2e_server["password"])
        page.click("#btn-customer-login")
        page.locator("#auth-gate-overlay").wait_for(state="hidden")
        page.locator("#portal-p3-cs-card").wait_for(state="visible")
        assert "Acme Digital Agency" in page.locator("#portal-org-name").inner_text()

        _assert_clean_telemetry(telemetry)
