"""Test Suite for Sprint 4:
1. US-4.1: High-Converting SMB Lead Discovery Engine (smb_search_source.py & POST /v1/leads/discover-smb)
2. US-4.2: Trojan-Horse Proof-First Public Preview Generator (POST /v1/previews/generate, GET /v1/previews/{token}, GET /v1/previews/{token}/html)
3. US-4.3: Autonomous Daily Shift Scheduler & CEO Executive Briefing (POST /v1/scheduler/run-shift, GET /v1/scheduler/briefing, GET /v1/scheduler/status)
4. US-4.4: Embeddable 24/7 Inbound Sales Closer Widget (/dashboard/widget.js) & Command Center Shift UI Controls
"""

from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.smb_search_source import discover_smb_leads
from app.db.database import Base, SessionLocal, engine, get_db
from app.db.models import (
    LeadRecordRow,
    ShiftRecord,
    TrustBlock,
)
from app.main import app
from app.services.previews import generate_trojan_horse_preview, get_preview_by_token
from app.services.shift_scheduler import run_autonomous_shift


class Sprint4RevenueMultipliersAndShiftsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.manager_key = "test-manager-key-sprint4-revenue-shifts"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        cls.client = TestClient(app)
        cls.headers = {
            "X-API-Key": cls.manager_key,
            "X-Correlation-ID": "test-sprint4-corr-001",
        }

    def setUp(self):
        self.db = SessionLocal()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_db, None)

    # ── US-4.1 Tests: SMB Lead Discovery Engine ──────────────────────────────
    def test_smb_search_source_discovery_across_verticals(self):
        """Test discover_smb_leads across distinct catalog verticals."""
        # 1. Warehouse Automation
        wh_leads = discover_smb_leads(vertical="warehouse_automation", region="Maharashtra", limit=3)
        self.assertGreaterEqual(len(wh_leads), 1)
        first_wh = wh_leads[0]
        self.assertIn("company", first_wh)
        self.assertIn("domain", first_wh)
        self.assertEqual(first_wh["recommended_package"], "warehouse_automation")
        self.assertIn("estimated_roi", first_wh)
        self.assertIn("net_monthly_savings_inr", first_wh["estimated_roi"])

        # 2. Mango Quality Analytics
        mango_leads = discover_smb_leads(vertical="mango_quality_analytics", region="India", limit=2)
        self.assertGreaterEqual(len(mango_leads), 1)
        first_mango = mango_leads[0]
        self.assertEqual(first_mango["recommended_package"], "mango_quality_analytics")
        all_signals = " ".join([s for l in mango_leads for s in l.get("observed_signals", [])]).lower()
        self.assertTrue("export" in all_signals or "mango" in all_signals or "quality" in all_signals)

        # 3. Growth All-in-One
        growth_leads = discover_smb_leads(vertical="growth_all_in_one", region="India", limit=2)
        self.assertGreaterEqual(len(growth_leads), 1)
        self.assertEqual(growth_leads[0]["recommended_package"], "growth_all_in_one")

        # 4. Bike Rebalance Analytics
        bike_leads = discover_smb_leads(vertical="bike_rebalance_analytics", region="Bengaluru", limit=2)
        self.assertGreaterEqual(len(bike_leads), 1)
        self.assertEqual(bike_leads[0]["recommended_package"], "bike_rebalance_analytics")

    def test_post_leads_discover_smb_endpoint_and_trust_block(self):
        """POST /v1/leads/discover-smb must discover leads, persist to DB, and seal TrustBlock."""
        payload = {
            "vertical": "warehouse_automation",
            "region": "India",
            "limit": 2,
        }
        res = self.client.post("/v1/leads/discover-smb", json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(data["vertical"], "warehouse_automation")
        self.assertGreaterEqual(data["leads_count"], 1)
        self.assertIn("block_hash", data)

        # Check DB persistence
        first_lead = data["leads"][0]
        lead_id = first_lead["lead_id"]
        persisted = self.db.query(LeadRecordRow).filter_by(id=lead_id).first()
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.product_match, "warehouse_automation")
        self.assertEqual(persisted.status, "DISCOVERED")

        # Verify TrustBlock was sealed
        block = self.db.query(TrustBlock).filter_by(block_hash=data["block_hash"]).first()
        self.assertIsNotNone(block)
        self.assertEqual(block.capability_name, "smb_lead_discovery")
        self.assertEqual(block.action, "discover_smb")

    # ── US-4.2 Tests: Trojan-Horse Proof-First Public Preview Generator ──────
    def test_generate_trojan_horse_preview_service_and_db(self):
        """generate_trojan_horse_preview must create preview with audit, benchmarks, payment links, and TrustBlock."""
        co_name = f"Apex Freight {uuid.uuid4().hex[:6]}"
        dom = f"apexfreight-{uuid.uuid4().hex[:6]}.example.com"
        preview = generate_trojan_horse_preview(
            db=self.db,
            company_name=co_name,
            domain=dom,
            recommended_package="warehouse_automation",
        )

        self.assertEqual(preview["status"], "COMPLETED")
        self.assertTrue(preview["preview_token"].startswith("prev_"))
        self.assertEqual(preview["company_name"], co_name)
        self.assertIn("custom_audit", preview)
        self.assertIn("roi_multiplier", preview["custom_audit"])
        self.assertIn("sample_deliverable", preview)
        self.assertIn("sample_snippet", preview["sample_deliverable"])
        self.assertIn("benchmarks", preview)
        self.assertIn("payment_links", preview)
        self.assertIn("razorpay", preview["payment_links"])
        self.assertIn("paypal", preview["payment_links"])

        # Check DB record
        rec = get_preview_by_token(self.db, preview["preview_token"], increment_view=True)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.views_count, 1)

        # Check TrustBlock
        block = self.db.query(TrustBlock).filter_by(block_hash=preview["trust_block_hash"]).first()
        self.assertIsNotNone(block)
        self.assertEqual(block.capability_name, "trojan_horse_preview")

    def test_post_previews_generate_and_get_public_endpoints(self):
        """HTTP endpoints for generating, fetching JSON, and rendering HTML for previews."""
        co_name = f"Konkan Produce {uuid.uuid4().hex[:6]}"
        dom = f"konkanfresh-{uuid.uuid4().hex[:6]}.example.com"

        # 1. POST /v1/previews/generate
        gen_res = self.client.post(
            "/v1/previews/generate",
            json={
                "company_name": co_name,
                "domain": dom,
                "recommended_package": "mango_quality_analytics",
            },
            headers=self.headers,
        )
        self.assertEqual(gen_res.status_code, 200)
        gen_data = gen_res.json()
        token = gen_data["preview_token"]
        self.assertTrue(token.startswith("prev_"))
        self.assertIn("razorpay", gen_data["payment_links"])
        self.assertIn("paypal", gen_data["payment_links"])

        # 2. GET /v1/previews/{preview_token} (Public JSON)
        get_res = self.client.get(f"/v1/previews/{token}")
        self.assertEqual(get_res.status_code, 200)
        get_data = get_res.json()
        self.assertEqual(get_data["company_name"], co_name)
        self.assertEqual(get_data["views_count"], 1)

        # Re-fetch increments views_count
        get_res2 = self.client.get(f"/v1/previews/{token}")
        self.assertEqual(get_res2.status_code, 200)
        self.assertEqual(get_res2.json()["views_count"], 2)

        # 3. GET /v1/previews/{preview_token}/html (Public HTML)
        html_res = self.client.get(f"/v1/previews/{token}/html")
        self.assertEqual(html_res.status_code, 200)
        self.assertEqual(html_res.headers["content-type"], "text/html; charset=utf-8")
        html_body = html_res.text
        self.assertIn(co_name, html_body)
        self.assertIn("Trojan-Horse Proof-First Preview", html_body)
        self.assertIn("Razorpay", html_body)
        self.assertIn("PayPal", html_body)
        self.assertIn("Cryptographic Ledger Seal", html_body)

        # 4. Non-existent preview token returns 404
        fake_res = self.client.get("/v1/previews/prev_non_existent_token_999")
        self.assertEqual(fake_res.status_code, 404)

        fake_html_res = self.client.get("/v1/previews/prev_non_existent_token_999/html")
        self.assertEqual(fake_html_res.status_code, 404)

    # ── US-4.3 Tests: Autonomous Shift Scheduler & CEO Briefing ───────────────
    def test_run_autonomous_shift_service_and_trust_block(self):
        """run_autonomous_shift executes all 4 worker steps and seals a TrustBlock."""
        shift_res = run_autonomous_shift(
            db=self.db,
            shift_type="full_daily_cycle",
            correlation_id=f"test-shift-{uuid.uuid4().hex[:8]}",
        )

        self.assertEqual(shift_res["status"], "COMPLETED")
        self.assertTrue(shift_res["shift_id"].startswith("shift_"))
        self.assertIn("steps", shift_res)
        steps = shift_res["steps"]

        # Step 1: outbound_sdr
        self.assertIn("outbound_sdr", steps)
        self.assertEqual(steps["outbound_sdr"]["status"], "COMPLETED")
        self.assertGreaterEqual(steps["outbound_sdr"]["leads_discovered_count"], 1)

        # Step 2: owned_media_seo
        self.assertIn("owned_media_seo", steps)
        self.assertEqual(steps["owned_media_seo"]["status"], "COMPLETED")
        self.assertGreaterEqual(steps["owned_media_seo"]["networks_targeted_count"], 4)

        # Step 3: order_fulfillment
        self.assertIn("order_fulfillment", steps)
        self.assertEqual(steps["order_fulfillment"]["status"], "COMPLETED")

        # Step 4: watchdog_audit
        self.assertIn("watchdog_audit", steps)
        self.assertEqual(steps["watchdog_audit"]["status"], "COMPLETED")

        # TrustBlock verified
        block = self.db.query(TrustBlock).filter_by(block_hash=shift_res["trust_block_hash"]).first()
        self.assertIsNotNone(block)
        self.assertEqual(block.capability_name, "autonomous_shift_scheduler")
        self.assertEqual(block.action, "run_shift")

        # ShiftRecord verified
        shift_rec = self.db.query(ShiftRecord).filter_by(shift_id=shift_res["shift_id"]).first()
        self.assertIsNotNone(shift_rec)
        self.assertEqual(shift_rec.status, "COMPLETED")

    def test_scheduler_api_endpoints_and_ceo_briefing(self):
        """POST /v1/scheduler/run-shift, GET /v1/scheduler/briefing, GET /v1/scheduler/status."""
        # 1. Trigger shift via HTTP
        shift_api_res = self.client.post(
            "/v1/scheduler/run-shift?shift_type=full_daily_cycle",
            headers=self.headers,
        )
        self.assertEqual(shift_api_res.status_code, 200)
        shift_data = shift_api_res.json()
        self.assertEqual(shift_data["status"], "COMPLETED")
        self.assertIn("trust_block_hash", shift_data)

        # 2. GET /v1/scheduler/briefing
        briefing_res = self.client.get("/v1/scheduler/briefing", headers=self.headers)
        self.assertEqual(briefing_res.status_code, 200)
        briefing = briefing_res.json()

        self.assertIn("Vipul Choubisa", briefing["owner"])
        self.assertIn("revenue", briefing)
        self.assertIn("total_revenue_inr", briefing["revenue"])
        self.assertIn("tenants", briefing)
        self.assertIn("active_tenants", briefing["tenants"])
        self.assertIn("governance", briefing)
        self.assertIn("pending_hitl_approvals", briefing["governance"])
        self.assertIn("watchdog", briefing)
        self.assertIn("health_score", briefing["watchdog"])
        self.assertIn("latest_shift", briefing)
        self.assertIsNotNone(briefing["latest_shift"])
        self.assertEqual(briefing["latest_shift"]["status"], "COMPLETED")

        # 3. GET /v1/scheduler/status
        status_res = self.client.get("/v1/scheduler/status", headers=self.headers)
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertEqual(status_data["status"], "OPERATIONAL")
        self.assertIn("employee_roster", status_data)
        self.assertIn("outbound_sdr", status_data["employee_roster"])
        self.assertIn("owned_media_seo", status_data["employee_roster"])
        self.assertIn("order_fulfillment", status_data["employee_roster"])
        self.assertIn("watchdog_audit", status_data["employee_roster"])

    # ── US-4.4 Tests: Widget & Command Center UI Controls ─────────────────────
    def test_widget_js_served_and_contains_closer_logic(self):
        """GET /dashboard/widget.js must be served statically with self-contained closer logic."""
        widget_res = self.client.get("/dashboard/widget.js")
        self.assertEqual(widget_res.status_code, 200)
        js_text = widget_res.text

        self.assertIn("afw-launcher", js_text)
        self.assertIn("afw-chat-window", js_text)
        self.assertIn("/v1/growth/sales-closer/chat", js_text)
        self.assertIn("afw-btn-razorpay", js_text)
        self.assertIn("afw-btn-paypal", js_text)
        self.assertIn("AFWSalesCloser", js_text)

    def test_dashboard_ui_elements_for_autonomous_shift_and_briefing(self):
        """index.html and dashboard.js must contain required Shift and CEO Briefing wiring."""
        html_path = Path("app/dashboard/index.html")
        self.assertTrue(html_path.exists())
        html_content = html_path.read_text(encoding="utf-8")

        self.assertIn("btn-run-autonomous-shift", html_content)
        self.assertIn("ceo-briefing-summary", html_content)
        self.assertIn("shift-status-badge", html_content)
        self.assertIn("btn-refresh-ceo-briefing", html_content)

        js_path = Path("app/dashboard/dashboard.js")
        self.assertTrue(js_path.exists())
        js_content = js_path.read_text(encoding="utf-8")

        self.assertIn("fetchCeoBriefing", js_content)
        self.assertIn("renderCeoBriefing", js_content)
        self.assertIn("btn-run-autonomous-shift", js_content)
        self.assertIn("/v1/scheduler/run-shift", js_content)
        self.assertIn("/v1/scheduler/briefing", js_content)

    def test_sales_closer_chat_alias_endpoint(self):
        """POST /v1/growth/sales-closer/chat must respond with consultative reply and payment links."""
        chat_res = self.client.post(
            "/v1/growth/sales-closer/chat",
            json={
                "session_id": f"sess-{uuid.uuid4().hex[:8]}",
                "prospect_name": "Rohan Gupta",
                "prospect_contact": "rohan@techcorp.example.com",
                "message": "What is the price of the all-in-one growth suite?",
                "currency": "INR",
                "channel": "widget_test",
            },
        )
        self.assertEqual(chat_res.status_code, 200)
        data = chat_res.json()
        self.assertIn("reply", data)
        self.assertIn("payment_links", data)
        self.assertIn("razorpay", data["payment_links"])
        self.assertIn("paypal", data["payment_links"])
