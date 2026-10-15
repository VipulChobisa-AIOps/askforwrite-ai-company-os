"""Tests for AskforWrite Autonomous Field Force Zero-Trust Presence & Attendance Engine."""

import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    FieldAttendanceRecord,
    OrganizationRecord,
    UserRecord,
)
from app.main import app
from app.security.auth import APIPrincipal, get_current_principal
from app.security.trust_chain import ensure_genesis_block


class FieldPresenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=cls.engine, expire_on_commit=False
        )
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        self.db = self.TestingSessionLocal()
        ensure_genesis_block(self.db)

        # Seed test org & user
        self.org_id = f"test-org-{uuid.uuid4().hex[:8]}"
        self.user_id = f"test-user-{uuid.uuid4().hex[:8]}"

        org = OrganizationRecord(
            id=self.org_id,
            name="Apex Field Logistics Ltd",
            slug=f"apex-{uuid.uuid4().hex[:6]}",
            tier="pro",
        )
        user = UserRecord(
            id=self.user_id,
            org_id=self.org_id,
            email=f"executive-{uuid.uuid4().hex[:6]}@apexlogistics.in",
            full_name="Rajesh Sharma",
            role="member",
        )
        self.db.add(org)
        self.db.add(user)
        self.db.commit()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_principal] = lambda: APIPrincipal(
            subject=self.user_id,
            role="manager",
            org_id=self.org_id,
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.clear()

    def test_create_and_list_geofence(self):
        """Manager creates a geofence hub and verifies it in the tenant hub list."""
        resp = self.client.post(
            "/v1/field-force/geofences",
            json={
                "name": "Delhi Regional Logistics Hub",
                "latitude": 28.6139,
                "longitude": 77.2090,
                "radius_meters": 200.0,
                "address": "Connaught Place, New Delhi",
            },
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["name"], "Delhi Regional Logistics Hub")
        self.assertEqual(data["radius_meters"], 200.0)

        list_resp = self.client.get("/v1/field-force/geofences")
        self.assertEqual(list_resp.status_code, 200)
        hubs = list_resp.json()
        self.assertTrue(any(h["name"] == "Delhi Regional Logistics Hub" for h in hubs))

    def test_verified_checkin_inside_geofence_seals_to_trust_chain(self):
        """Employee checks in with valid sensors inside the geofence -> VERIFIED and sealed."""
        # 1. Create hub at Connaught Place (28.6139, 77.2090)
        geofence_resp = self.client.post(
            "/v1/field-force/geofences",
            json={
                "name": "CP Center",
                "latitude": 28.6139,
                "longitude": 77.2090,
                "radius_meters": 150.0,
            },
        )
        geofence_id = geofence_resp.json()["id"]

        # 2. Check in 25 meters away from hub center
        checkin_resp = self.client.post(
            "/v1/field-force/attendance/check-in",
            json={
                "user_id": self.user_id,
                "latitude": 28.6140,
                "longitude": 77.2091,
                "accuracy_meters": 8.0,
                "device_fingerprint": "hw-sec-chip-001293a",
                "is_mock_provider": False,
                "wifi_bssid_hash": "a1b2c3d4e5f60718293a",
                "geofence_id": geofence_id,
                "idempotency_key": f"checkin-{uuid.uuid4().hex[:8]}",
            },
        )
        self.assertEqual(checkin_resp.status_code, 201)
        result = checkin_resp.json()
        self.assertEqual(result["status"], "VERIFIED")
        self.assertFalse(result["is_mock_location_detected"])
        self.assertIsNotNone(result["trust_block_hash"])

        # Verify attendance record exists in DB and is immutable
        rec = self.db.query(FieldAttendanceRecord).filter_by(id=result["id"]).first()
        self.assertIsNotNone(rec)
        self.assertEqual(rec.status, "VERIFIED")

    def test_anti_spoofing_rejects_mock_location_apps(self):
        """Anti-spoofing flags mock GPS providers and returns HTTP 400."""
        resp = self.client.post(
            "/v1/field-force/attendance/check-in",
            json={
                "user_id": self.user_id,
                "latitude": 28.6139,
                "longitude": 77.2090,
                "accuracy_meters": 5.0,
                "device_fingerprint": "fake-device-001",
                "is_mock_provider": True,  # Fake GPS active!
                "idempotency_key": f"checkin-spoof-{uuid.uuid4().hex[:8]}",
            },
        )
        self.assertEqual(resp.status_code, 400)
        err = resp.json()
        self.assertEqual(err["detail"]["error"], "SPOOFING_DETECTED")

    def test_out_of_bounds_checkin_is_rejected(self):
        """Employee checks in 5 km away from assigned site -> rejected HTTP 422."""
        geofence_resp = self.client.post(
            "/v1/field-force/geofences",
            json={
                "name": "Noida Sector 62 Branch",
                "latitude": 28.6280,
                "longitude": 77.3649,
                "radius_meters": 100.0,
            },
        )
        geofence_id = geofence_resp.json()["id"]

        # Check-in at Gurgaon (35 km away)
        resp = self.client.post(
            "/v1/field-force/attendance/check-in",
            json={
                "user_id": self.user_id,
                "latitude": 28.4595,
                "longitude": 77.0266,
                "accuracy_meters": 10.0,
                "device_fingerprint": "hw-sec-chip-001293a",
                "is_mock_provider": False,
                "geofence_id": geofence_id,
                "idempotency_key": f"checkin-oob-{uuid.uuid4().hex[:8]}",
            },
        )
        self.assertEqual(resp.status_code, 422)
        err = resp.json()
        self.assertEqual(err["detail"]["error"], "OUT_OF_BOUNDS")

    def test_teleportation_speed_anomaly_rejected(self):
        """Detects impossible ground teleportation (>160 km/h) between consecutive check-ins."""
        # First check-in at Delhi
        key1 = f"checkin-delhi-{uuid.uuid4().hex[:8]}"
        self.client.post(
            "/v1/field-force/attendance/check-in",
            json={
                "user_id": self.user_id,
                "latitude": 28.6139,
                "longitude": 77.2090,
                "accuracy_meters": 10.0,
                "device_fingerprint": "hw-sec-chip-001293a",
                "is_mock_provider": False,
                "idempotency_key": key1,
            },
        )

        # Immediate second check-in claiming Mumbai (1,150 km away 2 seconds later)
        key2 = f"checkin-mumbai-{uuid.uuid4().hex[:8]}"
        resp = self.client.post(
            "/v1/field-force/attendance/check-in",
            json={
                "user_id": self.user_id,
                "latitude": 19.0760,
                "longitude": 72.8777,
                "accuracy_meters": 10.0,
                "device_fingerprint": "hw-sec-chip-001293a",
                "is_mock_provider": False,
                "idempotency_key": key2,
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"]["error"], "SPOOFING_DETECTED")

    def test_attendance_records_are_cryptographically_immutable(self):
        """Attendance records cannot be mutated or deleted even via direct ORM updates."""
        checkin_resp = self.client.post(
            "/v1/field-force/attendance/check-in",
            json={
                "user_id": self.user_id,
                "latitude": 28.6139,
                "longitude": 77.2090,
                "accuracy_meters": 10.0,
                "device_fingerprint": "hw-sec-chip-001293a",
                "is_mock_provider": False,
                "idempotency_key": f"checkin-immutable-{uuid.uuid4().hex[:8]}",
            },
        )
        rec_id = checkin_resp.json()["id"]
        rec = self.db.query(FieldAttendanceRecord).filter_by(id=rec_id).first()

        # Attempt to forge attendance status
        rec.status = "FORGED_STATUS"
        with self.assertRaises(ValueError):
            self.db.commit()
        self.db.rollback()


if __name__ == "__main__":
    unittest.main()
