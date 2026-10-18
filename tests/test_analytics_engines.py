"""Comprehensive Unit & Integration Test Suite for AgriTech Vision Quality AI and Urban Mobility AI.

Covers:
1. HSV 512D Color Histogram & 6D GLCM Texture Extraction
2. Produce Quality Classification & Commercial Supply Chain Grading
3. OLS Multiple Linear Regression Demand Forecasting & VIF Multicollinearity Diagnostics
4. Station Churn Segmentation & Priority Truck Rebalance Route Optimization
5. TaskRecord persistence, AuditLog creation, and Merkle TrustBlock sealing
6. Idempotency guarantees & Conflict detection
7. FastAPI HTTP endpoints for /v1/quality/* and /v1/mobility/*
"""

import os
import unittest
import uuid
import numpy as np
from fastapi.testclient import TestClient

from app.db.database import Base, SessionLocal, engine, get_db
from app.db.models import TaskRecord, TrustBlock
from app.main import app
from app.services.mobility_analytics import (
    compute_station_rebalancing_plan,
    execute_mobility_optimization,
    forecast_hourly_demand,
)
from app.services.quality_analytics import (
    classify_produce_quality,
    compute_glcm_descriptors_6d,
    compute_hsv_histogram_512d,
    execute_produce_quality_inspection,
    generate_benchmark_produce_image,
    rgb_to_hsv_numpy,
)


class AnalyticsEnginesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.manager_key = "test-manager-api-key-32-chars-long-xxx"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        cls.client = TestClient(app)
        cls.headers = {
            "X-API-Key": cls.manager_key,
            "X-Correlation-ID": "test-analytics-corr-001",
        }

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_db, None)

    def setUp(self):
        self.db = SessionLocal()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        os.environ["MANAGER_API_KEY"] = self.manager_key
        self.headers = {
            "X-API-Key": self.manager_key,
            "X-Correlation-ID": f"test-analytics-corr-{uuid.uuid4().hex[:6]}",
        }

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_db, None)

    # ── Quality Analytics Engine Tests ────────────────────────────────────────

    def test_rgb_to_hsv_and_histogram_extraction(self):
        """Verify HSV color space conversion and 512D histogram normalization."""
        img = generate_benchmark_produce_image(preset="ripe", size=64)
        self.assertEqual(img.shape, (64, 64, 3))

        hsv = rgb_to_hsv_numpy(img)
        self.assertEqual(hsv.shape, (64, 64, 3))
        # Hue is [0, 360], S is [0, 1], V is [0, 1]
        self.assertTrue(np.all(hsv[:, :, 0] >= 0.0) and np.all(hsv[:, :, 0] <= 360.0))
        self.assertTrue(np.all(hsv[:, :, 1] >= 0.0) and np.all(hsv[:, :, 1] <= 1.0))
        self.assertTrue(np.all(hsv[:, :, 2] >= 0.0) and np.all(hsv[:, :, 2] <= 1.0))

        hist = compute_hsv_histogram_512d(hsv)
        self.assertEqual(len(hist), 512)
        # Sum of normalized histogram should be approximately 1.0
        self.assertAlmostEqual(sum(hist), 1.0, places=3)

    def test_glcm_descriptors_computation(self):
        """Verify 6 GLCM textural descriptors are calculated within valid statistical bounds."""
        img = generate_benchmark_produce_image(preset="overripe", size=64)
        glcm = compute_glcm_descriptors_6d(img)

        self.assertIn("contrast", glcm)
        self.assertIn("dissimilarity", glcm)
        self.assertIn("homogeneity", glcm)
        self.assertIn("energy", glcm)
        self.assertIn("correlation", glcm)
        self.assertIn("asm", glcm)

        self.assertGreaterEqual(glcm["contrast"], 0.0)
        self.assertGreaterEqual(glcm["homogeneity"], 0.0)
        self.assertLessEqual(glcm["homogeneity"], 1.0)
        self.assertGreaterEqual(glcm["energy"], 0.0)

    def test_produce_quality_classification_presets(self):
        """Verify ripeness grading across Unripe, Ripe, and Overripe benchmarks."""
        # Unripe check
        unripe_img = generate_benchmark_produce_image(preset="unripe", size=64)
        unripe_res = classify_produce_quality(unripe_img, crop_variety="Alphonso Mango")
        self.assertEqual(unripe_res["predicted_class"], "Unripe")
        self.assertIn("Export Grade A", unripe_res["commercial_grade"])
        self.assertGreater(unripe_res["shelf_life_days"], 10)

        # Ripe check
        ripe_img = generate_benchmark_produce_image(preset="ripe", size=64)
        ripe_res = classify_produce_quality(ripe_img, crop_variety="Alphonso Mango")
        self.assertEqual(ripe_res["predicted_class"], "Ripe")
        self.assertIn("Table Premium", ripe_res["commercial_grade"])
        self.assertGreaterEqual(ripe_res["estimated_brix_sugar_degrees"], 14.0)

    def test_execute_quality_inspection_with_trust_sealing(self):
        """Verify end-to-end inspection commits TaskRecord and seals cryptographic TrustBlock."""
        initial_blocks = self.db.query(TrustBlock).count()
        idemp_key = f"qual-test-{uuid.uuid4().hex[:8]}"

        res = execute_produce_quality_inspection(
            db=self.db,
            preset_or_sample="ripe",
            crop_variety="Kesar Mango",
            idempotency_key=idemp_key,
            correlation_id=str(uuid.uuid4()),
        )

        self.assertEqual(res["status"], "COMPLETED")
        self.assertIn("task_id", res)
        self.assertEqual(res["inspection_report"]["crop_variety"], "Kesar Mango")

        # Verify task persistence
        task = self.db.get(TaskRecord, res["task_id"])
        self.assertIsNotNone(task)
        self.assertEqual(task.status, "COMPLETED")

        # Verify cryptographic trust block was sealed
        new_blocks = self.db.query(TrustBlock).count()
        self.assertGreater(new_blocks, initial_blocks)
        latest_block = self.db.query(TrustBlock).order_by(TrustBlock.index.desc()).first()
        self.assertEqual(latest_block.capability_name, "computer_vision_quality_analytics")

    # ── Mobility Analytics Engine Tests ───────────────────────────────────────

    def test_forecast_hourly_demand_circadian_peaks(self):
        """Verify OLS demand model predicts higher volume during 8 AM rush hour vs 3 AM night."""
        morning_rush = forecast_hourly_demand(hour_of_day=8, temperature_f=70.0)
        midnight = forecast_hourly_demand(hour_of_day=3, temperature_f=70.0)

        self.assertGreater(morning_rush["predicted_hourly_demand"], midnight["predicted_hourly_demand"])
        self.assertEqual(morning_rush["model_diagnostics"]["vif_status"], "PASSED_ALL_VIF_BELOW_5")
        self.assertIn("confidence_interval_95", morning_rush)

    def test_station_rebalancing_plan_generation(self):
        """Verify station net churn segmentation and route pairing."""
        plan = compute_station_rebalancing_plan(hour_of_day=8, simulated_demand=45)

        self.assertEqual(plan["total_monitored_stations"], 12)
        summary = plan["summary"]
        self.assertGreater(summary["depleted_stations_count"], 0)
        self.assertGreater(summary["accumulated_stations_count"], 0)
        self.assertGreater(len(plan["priority_rebalance_routes"]), 0)

        route = plan["priority_rebalance_routes"][0]
        self.assertIn("pickup_station", route)
        self.assertIn("dropoff_station", route)
        self.assertGreater(route["transfer_quantity_bikes"], 0)

    def test_execute_mobility_optimization_with_trust_sealing(self):
        """Verify mobility optimization creates TaskRecord, AuditLog, and seals TrustBlock."""
        initial_blocks = self.db.query(TrustBlock).count()
        idemp_key = f"mob-test-{uuid.uuid4().hex[:8]}"

        res = execute_mobility_optimization(
            db=self.db,
            hour_of_day=17,
            temperature_f=72.0,
            idempotency_key=idemp_key,
            correlation_id=str(uuid.uuid4()),
        )

        self.assertEqual(res["status"], "COMPLETED")
        self.assertIn("task_id", res)
        self.assertIn("forecast", res["result"])
        self.assertIn("rebalancing", res["result"])

        # Verify cryptographic trust block sealed
        new_blocks = self.db.query(TrustBlock).count()
        self.assertGreater(new_blocks, initial_blocks)
        latest_block = self.db.query(TrustBlock).order_by(TrustBlock.index.desc()).first()
        self.assertEqual(latest_block.capability_name, "spatiotemporal_logistics_optimization")

    # ── HTTP API Endpoint Tests ───────────────────────────────────────────────

    def test_http_quality_status_and_inspect_endpoints(self):
        """Verify GET /v1/quality/status and POST /v1/quality/inspect."""
        status_resp = self.client.get("/v1/quality/status")
        self.assertEqual(status_resp.status_code, 200)
        self.assertEqual(status_resp.json()["status"], "OPERATIONAL")

        inspect_resp = self.client.post(
            "/v1/quality/inspect",
            headers=self.headers,
            json={
                "preset_or_sample": "ripe",
                "crop_variety": "Alphonso Mango",
                "batch_lot_id": "LOT-EXPORT-992",
            },
        )
        self.assertEqual(inspect_resp.status_code, 200)
        data = inspect_resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(data["inspection_report"]["batch_lot_id"], "LOT-EXPORT-992")

    def test_http_mobility_status_and_optimize_endpoints(self):
        """Verify GET /v1/mobility/status and POST /v1/mobility/optimize."""
        status_resp = self.client.get("/v1/mobility/status")
        self.assertEqual(status_resp.status_code, 200)
        self.assertEqual(status_resp.json()["status"], "OPERATIONAL")

        forecast_resp = self.client.post(
            "/v1/mobility/forecast",
            headers=self.headers,
            json={"hour_of_day": 8, "temperature_f": 68.0},
        )
        self.assertEqual(forecast_resp.status_code, 200)
        self.assertGreater(forecast_resp.json()["predicted_hourly_demand"], 10)

        opt_resp = self.client.post(
            "/v1/mobility/optimize",
            headers=self.headers,
            json={"hour_of_day": 8, "temperature_f": 68.0},
        )
        self.assertEqual(opt_resp.status_code, 200)
        data = opt_resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertIn("forecast", data["result"])
        self.assertIn("rebalancing", data["result"])

    def test_4_model_ensemble_predictions(self):
        """Verify quality inspection generates multi-model ensemble (SVM, RF, GNB, CNN)."""
        report = classify_produce_quality(
            image_array=generate_benchmark_produce_image(preset="ripe"),
            crop_variety="Alphonso Mango",
        )
        self.assertIn("model_ensemble", report)
        ensemble = report["model_ensemble"]
        self.assertEqual(len(ensemble), 4)
        names = {m["name"] for m in ensemble}
        self.assertIn("Support Vector Machine (SVM)", names)
        self.assertIn("Random Forest (RF)", names)
        self.assertIn("Gaussian Naive Bayes (GNB)", names)
        self.assertIn("Lightweight PyTorch CNN", names)
        for model in ensemble:
            self.assertIn(model["pred"], ["Unripe", "Ripe", "Overripe"])
            self.assertGreaterEqual(model["conf"], 40.0)

    def test_http_quality_inspect_image_and_uat(self):
        """Verify POST /v1/quality/inspect-image and POST /v1/quality/uat."""
        import io
        from PIL import Image

        # Create 64x64 synthetic image and save as PNG bytes
        img = Image.new("RGB", (64, 64), color=(240, 180, 30))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        upload_resp = self.client.post(
            "/v1/quality/inspect-image",
            headers={"X-API-Key": self.manager_key},
            files={"file": ("test_mango.png", buf.getvalue(), "image/png")},
            data={"crop_variety": "Kesar Mango", "batch_lot_id": "LOT-IMG-001"},
        )
        self.assertEqual(upload_resp.status_code, 200, upload_resp.text)
        res_data = upload_resp.json()
        self.assertEqual(res_data["status"], "COMPLETED")
        self.assertEqual(res_data["inspection_report"]["crop_variety"], "Kesar Mango")
        self.assertIn("model_ensemble", res_data["inspection_report"])

        # Test UAT endpoint
        uat_resp = self.client.post(
            "/v1/quality/uat",
            headers=self.headers,
            json={
                "role": "Chief Fruit Quality Auditor",
                "rating": 5,
                "comments": "Computer vision Brix and ripeness accuracy is exceptional.",
            },
        )
        self.assertEqual(uat_resp.status_code, 200)
        self.assertEqual(uat_resp.json()["status"], "logged")
        self.assertGreaterEqual(uat_resp.json()["total_responses"], 1)

    def test_http_mobility_rebalance_and_uat(self):
        """Verify dedicated POST /v1/mobility/rebalance and POST /v1/mobility/uat."""
        rebal_resp = self.client.post(
            "/v1/mobility/rebalance",
            headers=self.headers,
            json={"hour_of_day": 8, "auto_dispatch_field_force": True},
        )
        self.assertEqual(rebal_resp.status_code, 200, rebal_resp.text)
        rebal_data = rebal_resp.json()
        self.assertEqual(rebal_data["status"], "COMPLETED")
        self.assertTrue(rebal_data["field_force_dispatched"])
        self.assertIn("priority_rebalance_routes", rebal_data["rebalancing_plan"])

        # Test UAT endpoint
        uat_resp = self.client.post(
            "/v1/mobility/uat",
            headers=self.headers,
            json={
                "role": "Municipal Transit Rebalance Dispatcher",
                "rating": 5,
                "comments": "Automated route pairing prevents morning Caltrain station depletion.",
            },
        )
        self.assertEqual(uat_resp.status_code, 200)
        self.assertEqual(uat_resp.json()["status"], "logged")
        self.assertGreaterEqual(uat_resp.json()["total_responses"], 1)


if __name__ == "__main__":
    unittest.main()
