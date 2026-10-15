"""Tests for AskforWrite Multimodal Proof-of-Execution & Client Visit Debrief Engine."""

import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    ClientVisitRecord,
    FieldTaskRecord,
    OrganizationRecord,
    UserRecord,
)
from app.main import app
from app.security.auth import APIPrincipal, get_current_principal
from app.security.trust_chain import ensure_genesis_block


class FieldVerificationTests(unittest.TestCase):
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
        self.user_id = f"exec-{uuid.uuid4().hex[:8]}"

        org = OrganizationRecord(
            id=self.org_id,
            name="MedTech Field Services",
            slug=f"medtech-{uuid.uuid4().hex[:6]}",
            tier="pro",
        )
        user = UserRecord(
            id=self.user_id,
            org_id=self.org_id,
            email=f"rep-{uuid.uuid4().hex[:6]}@medtech.in",
            full_name="Deepak Joshi",
            role="member",
        )
        # Seed an assigned field task at Connaught Place (28.6328, 77.2197)
        self.task_id = str(uuid.uuid4())
        task = FieldTaskRecord(
            id=self.task_id,
            org_id=self.org_id,
            assigned_to_user_id=self.user_id,
            title="Hospital Equipment Calibration",
            client_name="Fortis Escorts Clinic",
            destination_lat=28.6328,
            destination_lon=77.2197,
            priority="HIGH",
            status="ASSIGNED",
        )

        self.db.add_all([org, user, task])
        self.db.commit()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_principal] = lambda: APIPrincipal(
            subject=self.user_id,
            role="member",
            org_id=self.org_id,
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.clear()

    def test_verified_client_visit_completes_task_and_seals_to_trust_chain(self):
        """Executive within 30m of client site captures valid photo evidence -> completed & sealed."""
        sample_photo_b64 = "data:image/jpeg;base64," + ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" * 5)
        resp = self.client.post(
            "/v1/field-force/visits/verify",
            json={
                "task_id": self.task_id,
                "user_id": self.user_id,
                "latitude": 28.6329,
                "longitude": 77.2198,
                "accuracy_meters": 5.0,
                "photo_evidence_base64_or_url": sample_photo_b64,
                "expected_photo_tags": ["storefront", "calibration_tag"],
                "notes": "Calibration completed successfully with clinic superintendent.",
            },
        )
        self.assertEqual(resp.status_code, 201)
        visit = resp.json()
        self.assertEqual(visit["client_name"], "Fortis Escorts Clinic")
        self.assertLess(visit["distance_from_site_meters"], 50.0)
        self.assertEqual(visit["photo_verification_status"], "VERIFIED")
        self.assertIsNotNone(visit["trust_block_hash"])

        # Verify task transitioned to COMPLETED
        task_in_db = self.db.query(FieldTaskRecord).filter_by(id=self.task_id).first()
        self.assertEqual(task_in_db.status, "COMPLETED")
        self.assertIsNotNone(task_in_db.completed_at)

    def test_visit_outside_radius_rejected_without_otp(self):
        """Executive 2 km away from client site without OTP is rejected."""
        resp = self.client.post(
            "/v1/field-force/visits/verify",
            json={
                "task_id": self.task_id,
                "user_id": self.user_id,
                "latitude": 28.6139,  # 2.1 km away
                "longitude": 77.2090,
                "accuracy_meters": 10.0,
                "photo_evidence_base64_or_url": "dummy_photo_data_which_is_long_enough_to_pass_minimum_length_checks_here",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_visit_outside_radius_accepted_with_geo_otp(self):
        """Executive slightly outside perimeter is accepted when client confirms Geo-OTP."""
        resp = self.client.post(
            "/v1/field-force/visits/verify",
            json={
                "task_id": self.task_id,
                "user_id": self.user_id,
                "latitude": 28.6300,  # 350m away
                "longitude": 77.2170,
                "accuracy_meters": 10.0,
                "geo_otp_code": "849201",  # Verified OTP from client
                "photo_evidence_base64_or_url": "dummy_photo_data_which_is_long_enough_to_pass_minimum_length_checks_here",
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.json()["geo_otp_verified"])

    def test_voice_note_synthesizes_structured_crm_debrief(self):
        """Spoken voice note is converted to structured CRM fields (sentiment, orders, follow-up)."""
        # First complete visit
        self.client.post(
            "/v1/field-force/visits/verify",
            json={
                "task_id": self.task_id,
                "user_id": self.user_id,
                "latitude": 28.6328,
                "longitude": 77.2197,
                "geo_otp_code": "12345",
            },
        )

        voice_text = (
            "Met Dr. Sharma. Client was very happy and excited with the calibration demonstration. "
            "They placed an order for 25 units of the test kit. "
            "Please follow up with invoice next Tuesday."
        )

        resp = self.client.post(
            "/v1/field-force/visits/debrief",
            json={
                "task_id": self.task_id,
                "user_id": self.user_id,
                "raw_audio_transcript_or_base64": voice_text,
            },
        )
        self.assertEqual(resp.status_code, 200)
        crm = resp.json()["structured_crm_data"]
        self.assertEqual(crm["client_sentiment"], "POSITIVE")
        self.assertEqual(len(crm["orders_booked"]), 1)
        self.assertEqual(crm["orders_booked"][0]["quantity"], 25)
        self.assertEqual(crm["orders_booked"][0]["unit"], "units")
        self.assertIn("follow up", crm["follow_up_action"].lower())

    def test_client_visit_records_are_cryptographically_immutable(self):
        """Attempts to forge or mutate visit records via ORM are blocked."""
        resp = self.client.post(
            "/v1/field-force/visits/verify",
            json={
                "task_id": self.task_id,
                "user_id": self.user_id,
                "latitude": 28.6328,
                "longitude": 77.2197,
                "geo_otp_code": "12345",
            },
        )
        visit_id = resp.json()["id"]
        rec = self.db.query(ClientVisitRecord).filter_by(id=visit_id).first()

        rec.photo_verification_status = "FORGED_STATUS"
        with self.assertRaises(ValueError):
            self.db.commit()
        self.db.rollback()


if __name__ == "__main__":
    unittest.main()
