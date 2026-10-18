"""Sprint 1 Comprehensive Test Suite.

Validates:
1. Catalog Completeness: warehouse_automation, ask4_academic_order, pixel_ai_pack, enterprise/all_access
2. Sales Agent Brain Alignment: SERVICE_KEYWORD_MAP, PAIN_POINT_DIAGNOSIS, ROI calculators, keyword diagnosis
3. StockSense Inventory Analytics Engine: Pareto ABC-XYZ, ROP/EOQ, dead stock, TrustBlock sealing, /status, /analyze, /reorder-plan, /uat
4. Order Fulfillment: /v1/orders/{transaction_id}/fulfill
5. Customer Portal: /v1/me/use-service execution across all 5 target services
6. System Introspection: /v1/capabilities and /v1/project/status synchronization
"""

from __future__ import annotations

import os
import unittest
import uuid

from fastapi.testclient import TestClient

from app.agents.revenue_agent import (
    PAIN_POINT_DIAGNOSIS,
    SERVICE_KEYWORD_MAP,
    calculate_estimated_roi,
    diagnose_lead_opportunity,
)
from app.agents.sources import INDIA_B2B_DIRECTORY
from app.db.database import Base, SessionLocal, engine
from app.db.models import OrganizationRecord, TrustBlock, UserRecord
from app.main import app
from app.security.auth import create_access_token, hash_password
from app.services.catalog import get_package
from app.services.inventory_analytics import (
    DEFAULT_BENCHMARK_SKUS,
    compute_abc_analysis,
    compute_reorder_recommendations,
    detect_dead_stock,
)
from app.services.orders import ingest_order


class Sprint1CatalogInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        cls.manager_key = os.environ.get(
            "MANAGER_API_KEY",
            "pA9F0w_3mK8sL2vX1qZ7jR6tY4uN5bE8oP3iU6yT9rE2wQ1a",
        )
        cls.manager_headers = {"X-API-Key": cls.manager_key}

    def setUp(self):
        self.db = SessionLocal()
        # Create a test organization and customer user for portal tests
        self.org_id = f"org-test-{uuid.uuid4().hex[:8]}"
        self.user_id = f"usr-test-{uuid.uuid4().hex[:8]}"
        self.user_email = f"sprint1-{uuid.uuid4().hex[:6]}@example.com"

        org = OrganizationRecord(
            id=self.org_id,
            name="Sprint 1 Logistics & Fresh Produce Corp",
            slug=f"sprint1-{uuid.uuid4().hex[:6]}",
            tier="enterprise",
            lead_credits_limit=5000,
            outreach_credits_limit=2500,
            is_active=True,
            metadata_json={"package_key": "all_access"},
        )
        user = UserRecord(
            id=self.user_id,
            org_id=self.org_id,
            email=self.user_email,
            full_name="Sprint One Test Admin",
            role="owner",
            password_hash=hash_password("SuperSecret2026!"),
            is_active=True,
        )
        self.db.add(org)
        self.db.add(user)
        self.db.commit()

        # Bearer token for portal requests
        self.token = create_access_token(
            user_id=self.user_id,
            email=self.user_email,
            role="owner",
            org_id=self.org_id,
        )
        self.portal_headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.db.close()

    # ── 1. Catalog Completeness Tests ─────────────────────────────────────────

    def test_catalog_warehouse_automation_sku(self):
        pkg = get_package("warehouse_automation")
        self.assertIsNotNone(pkg)
        self.assertEqual(pkg.key, "warehouse_automation")
        self.assertEqual(pkg.category, "modular_tool")
        self.assertEqual(pkg.price_inr, 4999)
        self.assertEqual(pkg.price_usd, 59)
        self.assertIn("inventory_analytics", pkg.entitled_capabilities)
        self.assertIn("Dynamic Reorder Point (ROP)", pkg.key_features[1])

    def test_catalog_b2c_one_off_skus(self):
        # ask4_academic_order (INR 999 / USD 15)
        ask4 = get_package("ask4_academic_order")
        self.assertIsNotNone(ask4)
        self.assertEqual(ask4.category, "b2c_one_off")
        self.assertEqual(ask4.price_inr, 999)
        self.assertEqual(ask4.price_usd, 15)

        # pixel_ai_pack (INR 1,499 / USD 19)
        pixel = get_package("pixel_ai_pack")
        self.assertIsNotNone(pixel)
        self.assertEqual(pixel.category, "b2c_one_off")
        self.assertEqual(pixel.price_inr, 1499)
        self.assertEqual(pixel.price_usd, 19)

    def test_catalog_enterprise_and_all_access_bundles(self):
        ent = get_package("company_os_enterprise")
        self.assertIsNotNone(ent)
        self.assertIn("warehouse_automation", ent.entitled_capabilities)
        self.assertIn("mango_quality_analytics", ent.entitled_capabilities)
        self.assertIn("bike_rebalance_analytics", ent.entitled_capabilities)

        all_acc = get_package("all_access")
        self.assertIsNotNone(all_acc)
        self.assertEqual(all_acc.price_inr, 59999)
        self.assertIn("warehouse_automation", all_acc.entitled_capabilities)
        self.assertIn("ask4_academic_order", all_acc.entitled_capabilities)
        self.assertIn("pixel_ai_pack", all_acc.entitled_capabilities)

    # ── 2. Sales Agent Brain Alignment Tests ──────────────────────────────────

    def test_service_keyword_map_contains_mango_bike_warehouse(self):
        self.assertIn("mango_quality_analytics", SERVICE_KEYWORD_MAP)
        self.assertIn("bike_rebalance_analytics", SERVICE_KEYWORD_MAP)
        self.assertIn("warehouse_automation", SERVICE_KEYWORD_MAP)

        mango_kws = SERVICE_KEYWORD_MAP["mango_quality_analytics"]
        self.assertIn("brix", mango_kws)
        self.assertIn("packhouse", mango_kws)
        self.assertIn("ripeness", mango_kws)

        bike_kws = SERVICE_KEYWORD_MAP["bike_rebalance_analytics"]
        self.assertIn("station churn", bike_kws)
        self.assertIn("micro-mobility", bike_kws)
        self.assertIn("rebalance", bike_kws)

    def test_pain_point_diagnosis_and_roi_calculator(self):
        self.assertIn("mango_quality_analytics", PAIN_POINT_DIAGNOSIS)
        self.assertIn("bike_rebalance_analytics", PAIN_POINT_DIAGNOSIS)
        self.assertIn("warehouse_automation", PAIN_POINT_DIAGNOSIS)

        roi_mango = calculate_estimated_roi("mango_quality_analytics", monthly_budget_inr=50000)
        self.assertEqual(roi_mango["package_key"], "mango_quality_analytics")
        self.assertGreater(roi_mango["projected_value_inr"], 50000)
        self.assertEqual(roi_mango["roi_multiplier"], "5.2x")

        roi_inv = calculate_estimated_roi("warehouse_automation", monthly_budget_inr=40000)
        self.assertEqual(roi_inv["roi_multiplier"], "6.1x")

    def test_diagnose_lead_opportunity_mango(self):
        diag = diagnose_lead_opportunity(
            company="Ratnagiri Mango Packhouse Exports",
            website="https://ratnagirimango.example.com",
            signals=["operating cold chain packhouse", "Brix ripeness grading and shelf life testing"],
            geography="Maharashtra, India",
            industry="Agriculture & Food Exports",
        )
        self.assertEqual(diag["recommended_package_key"], "mango_quality_analytics")
        self.assertEqual(diag["currency"], "INR")
        self.assertEqual(diag["price"], 3999)

    def test_diagnose_lead_opportunity_bike(self):
        diag = diagnose_lead_opportunity(
            company="Bengaluru MicroMobility Fleet",
            website="https://bengalurubikes.example.com",
            signals=["bike-share dock overflow", "station churn during commuter peak rush hour"],
            geography="Bengaluru, India",
            industry="Urban Mobility",
        )
        self.assertEqual(diag["recommended_package_key"], "bike_rebalance_analytics")
        self.assertEqual(diag["currency"], "INR")
        self.assertEqual(diag["price"], 3999)

    def test_diagnose_lead_opportunity_warehouse(self):
        diag = diagnose_lead_opportunity(
            company="National 3PL Fulfillment Hub",
            website="https://national3pl.example.com",
            signals=["warehouse stockout on high-velocity SKUs", "dead stock holding cost reduction and dynamic EOQ"],
            geography="Gujarat, India",
            industry="Warehousing & Logistics",
        )
        self.assertEqual(diag["recommended_package_key"], "warehouse_automation")
        self.assertEqual(diag["currency"], "INR")
        self.assertEqual(diag["price"], 4999)

    def test_india_b2b_directory_entries(self):
        companies = [entry["company"] for entry in INDIA_B2B_DIRECTORY]
        self.assertIn("Maharashtra Fresh Produce Exports", companies)
        self.assertIn("MetroMobility Fleet Labs", companies)
        self.assertIn("Gujarat Warehousing Co", companies)

    # ── 3. StockSense Inventory Analytics Engine Tests ────────────────────────

    def test_stocksense_abc_xyz_analysis_logic(self):
        res = compute_abc_analysis(DEFAULT_BENCHMARK_SKUS)
        self.assertGreater(res["total_catalog_value"], 0)
        self.assertGreater(res["class_a_count"], 0)
        self.assertGreater(res["class_b_count"], 0)
        self.assertGreater(res["class_c_count"], 0)

        # Check that composite abc_xyz_class was computed
        first_item = res["items"][0]
        self.assertIn(first_item["abc_class"], {"A", "B", "C"})
        self.assertIn(first_item["xyz_class"], {"X", "Y", "Z"})
        self.assertIn("abc_xyz_class", first_item)
        self.assertIn("coefficient_of_variation", first_item)

    def test_stocksense_reorder_and_dead_stock_logic(self):
        reorders = compute_reorder_recommendations(DEFAULT_BENCHMARK_SKUS)
        self.assertEqual(len(reorders), len(DEFAULT_BENCHMARK_SKUS))
        reorder_keys = {"sku", "current_stock", "reorder_point", "eoq", "reorder_needed"}
        for r in reorders:
            self.assertTrue(reorder_keys.issubset(r.keys()))

        dead = detect_dead_stock(DEFAULT_BENCHMARK_SKUS, threshold_days=90)
        self.assertGreater(dead["dead_stock_count"], 0)
        self.assertGreater(dead["total_capital_locked_inr"], 0)

    def test_inventory_status_endpoint(self):
        resp = self.client.get("/v1/inventory/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ONLINE")
        self.assertIn("StockSense", data["engine"])
        self.assertIn("pareto_abc_segmentation", data["supported_features"])

    def test_inventory_analyze_and_reorder_endpoints(self):
        # /v1/inventory/analyze
        resp = self.client.post(
            "/v1/inventory/analyze",
            json={"service_level_z": 1.65, "forecast_alpha": 0.3},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertIn("audit_metrics", data)
        self.assertIn("trust_block", data)
        self.assertGreater(data["audit_metrics"]["total_skus"], 0)

        # /v1/inventory/reorder-plan
        resp_reorder = self.client.post(
            "/v1/inventory/reorder-plan",
            json={"service_level_z": 1.65},
        )
        self.assertEqual(resp_reorder.status_code, 200)
        data_reorder = resp_reorder.json()
        self.assertGreater(data_reorder["total_evaluated"], 0)
        self.assertIn("recommendations", data_reorder)

    def test_inventory_uat_endpoint(self):
        resp = self.client.post(
            "/v1/inventory/uat",
            json={
                "operator_id": "wh-auditor-99",
                "rating": 5,
                "notes": "Verified EOQ accuracy against Q3 dispatch actuals.",
                "discrepancy_reported": False,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "RECORDED")
        self.assertEqual(data["entry"]["operator_id"], "wh-auditor-99")

    # ── 4. Order Ingest and Fulfillment Tests ─────────────────────────────────

    def test_order_fulfillment_lifecycle(self):
        tx_id = f"tx_sprint1_{uuid.uuid4().hex[:10]}"
        # 1. Ingest order
        ingest_res = ingest_order(
            db=self.db,
            transaction_id=tx_id,
            amount=999.0,
            currency="INR",
            customer_email="academic_client@example.com",
            idempotency_key=f"idemp-{tx_id}",
        )
        self.assertIn(ingest_res["status"], {"PENDING", "CONFIRMED"})

        # 2. Call fulfill endpoint
        fulfill_resp = self.client.post(
            f"/v1/orders/{tx_id}/fulfill",
            headers=self.manager_headers,
        )
        self.assertEqual(fulfill_resp.status_code, 200)
        fulfill_data = fulfill_resp.json()
        self.assertEqual(fulfill_data["status"], "FULFILLED")
        self.assertEqual(fulfill_data["transaction_id"], tx_id)
        self.assertEqual(fulfill_data["delivery"]["status"], "FULFILLED")

        # 3. Verify TrustBlock was sealed for fulfillment
        tip = self.db.query(TrustBlock).order_by(TrustBlock.index.desc()).first()
        self.assertIsNotNone(tip)
        self.assertIn(tip.action, {"fulfill_order", "genesis_sealing", "inventory_audit_sealed"})

    # ── 5. Customer Portal /v1/me/use-service Tests ───────────────────────────

    def test_customer_portal_use_service_mango(self):
        resp = self.client.post(
            "/v1/me/use-service",
            headers=self.portal_headers,
            json={
                "service_key": "mango_quality_analytics",
                "payload": {"variety": "Kesar", "sample_count": 3},
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(data["service_key"], "mango_quality_analytics")
        self.assertIn("lot_id", data["result"])
        self.assertIn("inspection_summary", data["result"])

    def test_customer_portal_use_service_bike(self):
        resp = self.client.post(
            "/v1/me/use-service",
            headers=self.portal_headers,
            json={
                "service_key": "bike_rebalance_analytics",
                "payload": {"hour_of_day": 8, "temperature_c": 22.0},
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertIn("demand_forecast", data["result"])
        self.assertIn("priority_rebalancing_dispatch", data["result"])

    def test_customer_portal_use_service_warehouse(self):
        resp = self.client.post(
            "/v1/me/use-service",
            headers=self.portal_headers,
            json={
                "service_key": "warehouse_automation",
                "payload": {"service_level_z": 1.65},
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertIn("audit_metrics", data["result"])

    def test_customer_portal_use_service_ask4(self):
        resp = self.client.post(
            "/v1/me/use-service",
            headers=self.portal_headers,
            json={
                "service_key": "ask4_academic_order",
                "payload": {"topic": "Cryptographic Zero-Knowledge Audit Chains"},
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertIn("Scholarly Synthesis", data["result"]["title"])
        self.assertTrue(data["result"]["integrity_sealed"])

    def test_customer_portal_use_service_pixel_ai(self):
        resp = self.client.post(
            "/v1/me/use-service",
            headers=self.portal_headers,
            json={
                "service_key": "pixel_ai_pack",
                "payload": {"product_name": "AskforWrite OS", "aspect_ratios": ["1:1", "9:16"]},
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertIn("variants", data["result"])
        self.assertEqual(len(data["result"]["variants"]), 2)

    def test_customer_portal_use_service_invalid(self):
        resp = self.client.post(
            "/v1/me/use-service",
            headers=self.portal_headers,
            json={"service_key": "non_existent_unsupported_sku"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("not executable", resp.json()["detail"])

    # ── 6. System Introspection Tests ─────────────────────────────────────────

    def test_capabilities_endpoint(self):
        resp = self.client.get("/v1/capabilities", headers=self.manager_headers)
        self.assertEqual(resp.status_code, 200)
        caps = {c["id"] for c in resp.json()["capabilities"]}
        self.assertIn("mango_quality_analytics", caps)
        self.assertIn("bike_rebalance_analytics", caps)
        self.assertIn("warehouse_automation", caps)
        self.assertIn("growth_suite", caps)
        self.assertIn("customer_portal", caps)
        self.assertIn("mobile_bridge", caps)

    def test_project_status_endpoint(self):
        resp = self.client.get("/v1/project/status", headers=self.manager_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "operational")

        connected = {item["name"] for item in data["operating_model"]["l3_connected_capabilities"]}
        self.assertIn("mango_quality_analytics", connected)
        self.assertIn("bike_rebalance_analytics", connected)
        self.assertIn("warehouse_automation", connected)
        self.assertIn("growth_suite", connected)
        self.assertIn("customer_portal", connected)
        self.assertIn("mobile_bridge", connected)


if __name__ == "__main__":
    unittest.main()
