"""Tests for Pixel AI Mobile Bridge and Production Security Headers."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.database import Base, engine
from app.main import app


class MobileAndSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        cls.manager_key = os.environ.get("MANAGER_API_KEY", "test-manager-api-key-32-chars-long-xxx")
        cls.owner_key = os.environ.get("OWNER_API_KEY", "test-owner-api-key-32-chars-long-xxx")

    # ── Security Headers Tests ────────────────────────────────────────

    def test_security_headers_present(self):
        """Verify baseline security headers are attached to all HTTP responses."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(resp.headers.get("x-frame-options"), "SAMEORIGIN")
        self.assertEqual(resp.headers.get("referrer-policy"), "strict-origin-when-cross-origin")
        self.assertIn("default-src", resp.headers.get("content-security-policy", ""))
        self.assertIn("geolocation=(self)", resp.headers.get("permissions-policy", ""))

    def test_hsts_enforced_in_production(self):
        """Verify Strict-Transport-Security header is injected when in production."""
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            # Create a fresh TestClient with production env
            client = TestClient(app)
            resp = client.get("/health")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("max-age=", resp.headers.get("strict-transport-security", ""))

    # ── Pixel AI Mobile Bridge Tests ──────────────────────────────────

    def test_mobile_bridge_status(self):
        """Verify /v1/mobile/status returns online with capabilities list."""
        resp = self.client.get("/v1/mobile/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "online")
        self.assertIn("gps_geofence_attendance", data["capabilities"])
        self.assertIn("pixel_conversational_copilot", data["capabilities"])

    def test_pwa_mobile_manifest(self):
        """Verify PWA web manifest contains required properties for installation."""
        resp = self.client.get("/mobile/manifest.json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["short_name"], "AFW OS")
        self.assertEqual(data["display"], "standalone")
        self.assertGreaterEqual(len(data["icons"]), 1)

    def test_portal_and_app_redirects(self):
        """Verify /portal and /app redirect smoothly to the SPA interface."""
        resp = self.client.get("/portal", follow_redirects=False)
        self.assertEqual(resp.status_code, 307)
        self.assertIn("/dashboard/#portal", resp.headers.get("location", ""))

        resp_app = self.client.get("/app", follow_redirects=False)
        self.assertEqual(resp_app.status_code, 307)
        self.assertIn("/dashboard/#portal", resp_app.headers.get("location", ""))

    def test_device_registration(self):
        """Verify field worker mobile device can register for push dispatches."""
        headers = {"Authorization": f"Bearer {self.manager_key}"}
        payload = {
            "device_id": "test-device-uuid-12345",
            "platform": "android",
            "app_version": "2.1.0",
            "device_model": "Pixel 8 Pro",
        }
        resp = self.client.post("/v1/mobile/device/register", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "registered")
        self.assertEqual(resp.json()["device_id"], "test-device-uuid-12345")

    def test_pixel_assistant_conversational_query(self):
        """Verify PixelBot conversational assistant answers field instructions."""
        headers = {"Authorization": f"Bearer {self.manager_key}"}
        resp = self.client.post(
            "/v1/mobile/pixel/assist",
            json={"prompt": "What are my client visits for today?"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("reply", data)
        self.assertIn("PixelBot", data["agent"])
        self.assertEqual(data["suggested_action"]["type"], "OPEN_TASKS")

    def test_pixel_assistant_checkin_intent(self):
        """Verify PixelBot checkin intent suggests GPS check-in action."""
        headers = {"Authorization": f"Bearer {self.manager_key}"}
        resp = self.client.post(
            "/v1/mobile/pixel/assist",
            json={"prompt": "I want to check in at the warehouse"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["suggested_action"]["type"], "TRIGGER_CHECKIN")

    def test_mobile_checkin_endpoint(self):
        """Verify /v1/mobile/attendance/check-in records attendance."""
        headers = {"Authorization": f"Bearer {self.manager_key}"}
        payload = {
            "latitude": 26.9124,
            "longitude": 75.7873,
            "accuracy_meters": 8.5,
            "check_type": "check_in",
            "mock_provider_detected": False,
        }
        resp = self.client.post("/v1/mobile/attendance/check-in", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("attendance_id", data)
        self.assertEqual(data["event_type"], "CHECK_IN")

    def test_unauthenticated_mobile_rejected(self):
        """Verify unauthenticated requests to protected mobile endpoints fail with 401 or 422."""
        payload = {
            "latitude": 26.9124,
            "longitude": 75.7873,
            "accuracy_meters": 8.5,
            "check_type": "check_in",
        }
        resp = self.client.post("/v1/mobile/attendance/check-in", json=payload)
        self.assertIn(resp.status_code, (401, 422))

        # With explicitly invalid Bearer token
        resp_invalid = self.client.post(
            "/v1/mobile/attendance/check-in",
            json=payload,
            headers={"Authorization": "Bearer invalid.token.payload"},
        )
        self.assertEqual(resp_invalid.status_code, 401)



if __name__ == "__main__":
    unittest.main()
