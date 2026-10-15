"""Tests for AskforWrite Fraud-Proof Conveyance & Expense Auto-Settlement Engine."""

import unittest
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    ConveyanceClaimRecord,
    OrganizationRecord,
    UserRecord,
)
from app.main import app
from app.security.auth import APIPrincipal, get_current_principal
from app.security.trust_chain import ensure_genesis_block


class FieldConveyanceTests(unittest.TestCase):
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
            name="Swift Distribution Network",
            slug=f"swift-{uuid.uuid4().hex[:6]}",
            tier="pro",
        )
        user = UserRecord(
            id=self.user_id,
            org_id=self.org_id,
            email=f"rider-{uuid.uuid4().hex[:6]}@swiftdist.in",
            full_name="Sunil Kumar",
            role="member",
        )
        self.db.add_all([org, user])
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

    def test_stationary_gps_drift_is_filtered_out(self):
        """Simulates 10 breadcrumbs drifting 5-15 meters while employee is stationary -> filtered to 0 km."""
        now = datetime.now(UTC)
        # 10 points within a 15-meter box over 1 hour
        base_lat, base_lon = 28.6139, 77.2090
        breadcrumbs = []
        for i in range(10):
            # Tiny coordinate perturbations (<15 meters)
            offset = (i % 3) * 0.00008
            breadcrumbs.append({
                "latitude": base_lat + offset,
                "longitude": base_lon + offset,
                "timestamp": (now + timedelta(minutes=i * 6)).isoformat(),
            })

        resp = self.client.post(
            "/v1/field-force/conveyance/calculate",
            json={
                "user_id": self.user_id,
                "claim_date": "2026-10-11",
                "transport_mode": "TWO_WHEELER",
                "gps_breadcrumbs": breadcrumbs,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["distance_telemetry"]
        # Raw distance may show fake drift (~0.05 - 0.2 km), but filtered road distance must be 0.0 km
        self.assertEqual(data["verified_road_distance_km"], 0.0)

    def test_compliant_conveyance_and_receipt_is_auto_approved(self):
        """Submits legitimate 10 km route + toll receipt -> auto-approved and sealed into TrustBlock."""
        now = datetime.now(UTC)
        # 3 points along a real 10 km route from CP to South Delhi
        breadcrumbs = [
            {"latitude": 28.6139, "longitude": 77.2090, "timestamp": now.isoformat()},
            {"latitude": 28.5700, "longitude": 77.2200, "timestamp": (now + timedelta(minutes=15)).isoformat()},
            {"latitude": 28.5355, "longitude": 77.2410, "timestamp": (now + timedelta(minutes=30)).isoformat()},
        ]

        resp = self.client.post(
            "/v1/field-force/conveyance/submit",
            json={
                "user_id": self.user_id,
                "claim_date": "2026-10-11",
                "transport_mode": "TWO_WHEELER",
                "gps_breadcrumbs": breadcrumbs,
                "receipts": [
                    {
                        "category": "TOLL",
                        "amount": 80.0,
                        "merchant_name": "DND Flyway Toll Plaza",
                        "receipt_date": "2026-10-11",
                        "receipt_base64_or_hash": "receipt-img-sample-valid-hash-00129",
                    }
                ],
                "notes": "Client delivery round in South Delhi",
            },
        )
        self.assertEqual(resp.status_code, 201)
        claim = resp.json()
        self.assertEqual(claim["status"], "AUTO_APPROVED")
        self.assertGreater(claim["verified_road_distance_km"], 8.0)
        self.assertGreater(claim["total_conveyance_amount"], 35.0)
        self.assertEqual(claim["total_expenses_amount"], 80.0)
        self.assertEqual(claim["receipt_count"], 1)
        self.assertEqual(len(claim["discrepancy_flags"]), 0)
        self.assertIsNotNone(claim["trust_block_hash"])

    def test_receipt_date_mismatch_flags_claim_for_review(self):
        """Submitting a receipt with date mismatch flags claim for supervisor review."""
        now = datetime.now(UTC)
        breadcrumbs = [
            {"latitude": 28.6139, "longitude": 77.2090, "timestamp": now.isoformat()},
            {"latitude": 28.5355, "longitude": 77.2410, "timestamp": (now + timedelta(minutes=25)).isoformat()},
        ]

        resp = self.client.post(
            "/v1/field-force/conveyance/submit",
            json={
                "user_id": self.user_id,
                "claim_date": "2026-10-11",
                "transport_mode": "TWO_WHEELER",
                "gps_breadcrumbs": breadcrumbs,
                "receipts": [
                    {
                        "category": "FUEL",
                        "amount": 500.0,
                        "merchant_name": "Indian Oil Station",
                        "receipt_date": "2026-09-15",  # Old receipt from last month!
                        "receipt_base64_or_hash": "receipt-img-sample-old-date-00129",
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 201)
        claim = resp.json()
        self.assertEqual(claim["status"], "FLAGGED_FOR_REVIEW")
        self.assertTrue(any("RECEIPT_DATE_MISMATCH" in f for f in claim["discrepancy_flags"]))

    def test_conveyance_records_are_cryptographically_immutable(self):
        """Attempts to tamper with an approved claim via direct ORM update are blocked."""
        now = datetime.now(UTC)
        breadcrumbs = [
            {"latitude": 28.6139, "longitude": 77.2090, "timestamp": now.isoformat()},
            {"latitude": 28.5355, "longitude": 77.2410, "timestamp": (now + timedelta(minutes=20)).isoformat()},
        ]
        resp = self.client.post(
            "/v1/field-force/conveyance/submit",
            json={
                "user_id": self.user_id,
                "claim_date": "2026-10-11",
                "transport_mode": "TWO_WHEELER",
                "gps_breadcrumbs": breadcrumbs,
            },
        )
        claim_id = resp.json()["id"]
        rec = self.db.query(ConveyanceClaimRecord).filter_by(id=claim_id).first()

        rec.grand_total_amount = 9999.0  # Attempt to forge payout
        with self.assertRaises(ValueError):
            self.db.commit()
        self.db.rollback()


if __name__ == "__main__":
    unittest.main()
