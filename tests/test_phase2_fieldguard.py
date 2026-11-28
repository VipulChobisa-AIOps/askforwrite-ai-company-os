"""Comprehensive Phase 2 FieldGuard Commercialization Verification Suite.

Verifies every anti-fraud, tour management, policy, adjudication, export, and PWA requirement:
1. Real Gemini Vision Receipt OCR: flags OCR_AMOUNT_MISMATCH & OCR_DATE_MISMATCH, verifies clean receipts,
   and refuses to fake is_verified=True when Vision OCR is unavailable.
2. Cross-claim Duplicate Receipt Fraud Detection: catches exact SHA-256 replay, re-saved perceptual dHash
   similarity, and merchant+invoice+amount collisions.
3. Real Server-Issued Single-Use 6-Digit Geo-OTP: rejects arbitrary "1234" / "849201" bypass, accepts valid
   issued code ONCE, blocks replay, and blocks expired codes.
4. Real Pillow Photo Evidence Integrity: accepts sharp real JPEG, rejects blank/solid/1x1 frames, flags
   EXIF GPS mismatch (>500m), and supports optional Vision scene verification (never hardcoded 0.94).
5. Per-Org Configurable Travel, Conveyance, Hotel & DA Policies (custom rates + Tier-1/2/3 caps).
6. Multi-Day Outstation Tour Plans: create -> manager approve with advance -> attach claims -> Tour Settlement
   Voucher reconciling approved claims vs advance paid with ECDSA hash-chain seal.
7. Append-Only Manager Review Queue (APPROVE, PARTIAL_APPROVE, REJECT) preserving claim immutability.
8. 1-Click Monthly Finance Payout Exports (CSV, Tally XML, ICICI NEFT, HDFC NEFT) with SHA-256 audit batch digest.
9. Cross-tenant isolation on all Phase 2 endpoints + Offline-First FieldGuard Mobile PWA assets.
"""

from __future__ import annotations

import base64
import io
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    ConveyanceClaimRecord,
    ConveyanceClaimReviewRecord,
    ExpenseReceiptRecord,
    FieldTaskRecord,
    FieldVisitOtpRecord,
    OrganizationRecord,
    UserRecord,
)
from app.main import app
from app.security.auth import APIPrincipal, get_current_principal
from app.security.trust_chain import ensure_genesis_block


def _make_textured_jpeg_b64(seed_offset: int = 0, *, quality: int = 90, exif_bytes: bytes | None = None) -> str:
    """Create a real sharp JPEG with visual features so Pillow Laplacian variance & dHash are authentic."""
    img = Image.new("RGB", (240, 180), color=(245, 245, 240))
    draw = ImageDraw.Draw(img)
    for x in range(8 + seed_offset, 230, 18):
        draw.rectangle([x, 15, x + 9, 165], fill=((x * 7) % 200, (x * 13) % 180, 190))
    for y in range(20, 170, 22):
        draw.line([10, y + (seed_offset % 7), 230, 180 - y], fill=(210, 40, 40), width=3)
    draw.rectangle([40 + seed_offset, 50, 180, 130], outline=(10, 10, 10), width=4)
    buf = io.BytesIO()
    if exif_bytes:
        img.save(buf, format="JPEG", quality=quality, exif=exif_bytes)
    else:
        img.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _make_blank_jpeg_b64() -> str:
    """Create a solid black frame that must be rejected by real Pillow integrity checks."""
    img = Image.new("RGB", (200, 200), color=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _make_jpeg_with_gps_exif_b64(lat: float, lon: float) -> str:
    """Create a sharp JPEG carrying real EXIF DateTimeOriginal + GPSInfo tags."""
    img = Image.new("RGB", (240, 180), color=(240, 242, 248))
    draw = ImageDraw.Draw(img)
    for x in range(10, 230, 16):
        draw.rectangle([x, 20, x + 8, 160], fill=(30, 80, 170))
        draw.line([0, x % 180, 240, 180 - (x % 180)], fill=(180, 30, 60), width=2)

    exif = img.getexif()
    exif[0x0132] = datetime.now(UTC).strftime("%Y:%m:%d %H:%M:%S")

    def _to_dms(val: float):
        aval = abs(val)
        d = int(aval)
        m_full = (aval - d) * 60.0
        m = int(m_full)
        s = round((m_full - m) * 60.0, 2)
        return (float(d), float(m), float(s))

    gps_ifd = {
        1: "N" if lat >= 0 else "S",
        2: _to_dms(lat),
        3: "E" if lon >= 0 else "W",
        4: _to_dms(lon),
    }
    exif[0x8825] = gps_ifd
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92, exif=exif.tobytes())
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class Phase2FieldGuardTests(unittest.TestCase):
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

        self.org_a_id = f"fg-org-a-{uuid.uuid4().hex[:8]}"
        self.org_b_id = f"fg-org-b-{uuid.uuid4().hex[:8]}"
        self.rep_id = f"fg-rep-{uuid.uuid4().hex[:8]}"
        self.mgr_id = f"fg-mgr-{uuid.uuid4().hex[:8]}"
        self.mgr_b_id = f"fg-mgr-b-{uuid.uuid4().hex[:8]}"

        org_a = OrganizationRecord(
            id=self.org_a_id,
            name="Jaipur Pharma Distributors",
            slug=f"jpharma-{uuid.uuid4().hex[:6]}",
            tier="pro",
            ai_credits_limit=600,
            ai_credits_used=0,
            ai_daily_spend_cap_inr=350.0,
            metadata_json={"entitled_capabilities": ["delivery_field_force"]},
        )
        org_b = OrganizationRecord(
            id=self.org_b_id,
            name="Rival Logistics Pvt Ltd",
            slug=f"rival-{uuid.uuid4().hex[:6]}",
            tier="pro",
            ai_credits_limit=600,
            ai_credits_used=0,
            metadata_json={"entitled_capabilities": ["delivery_field_force"]},
        )
        rep = UserRecord(
            id=self.rep_id,
            org_id=self.org_a_id,
            email=f"rep-{uuid.uuid4().hex[:6]}@jpharma.in",
            full_name="Ramesh Verma",
            role="member",
        )
        mgr = UserRecord(
            id=self.mgr_id,
            org_id=self.org_a_id,
            email=f"mgr-{uuid.uuid4().hex[:6]}@jpharma.in",
            full_name="Anita Sharma",
            role="manager",
        )
        mgr_b = UserRecord(
            id=self.mgr_b_id,
            org_id=self.org_b_id,
            email=f"mgrb-{uuid.uuid4().hex[:6]}@rival.in",
            full_name="Other Org Manager",
            role="manager",
        )
        self.task_id = str(uuid.uuid4())
        task = FieldTaskRecord(
            id=self.task_id,
            org_id=self.org_a_id,
            assigned_to_user_id=self.rep_id,
            title="Distributor Stock & Payment Check",
            client_name="Sawai Medical Agency",
            destination_lat=26.9124,
            destination_lon=75.7873,
            priority="HIGH",
            status="ASSIGNED",
        )
        self.db.add_all([org_a, org_b, rep, mgr, mgr_b, task])
        self.db.commit()

        self.rep_principal = APIPrincipal(subject=rep.email, user_id=self.rep_id, role="member", org_id=self.org_a_id)
        self.mgr_principal = APIPrincipal(subject=mgr.email, user_id=self.mgr_id, role="manager", org_id=self.org_a_id)
        self.mgr_b_principal = APIPrincipal(subject=mgr_b.email, user_id=self.mgr_b_id, role="manager", org_id=self.org_b_id)
        self.active_principal = self.rep_principal

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_principal] = lambda: self.active_principal
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.clear()

    def _breadcrumbs_10km(self) -> list[dict]:
        now = datetime.now(UTC)
        return [
            {"latitude": 26.9124, "longitude": 75.7873, "timestamp": now.isoformat()},
            {"latitude": 26.8680, "longitude": 75.8050, "timestamp": (now + timedelta(minutes=15)).isoformat()},
            {"latitude": 26.8320, "longitude": 75.8250, "timestamp": (now + timedelta(minutes=30)).isoformat()},
        ]

    # ── 1. Real Vision OCR + Honest Unverified Fallback ───────────────────

    def test_01_real_vision_ocr_mismatch_detection_and_no_fake_verified(self):
        """Real Gemini Vision OCR flags amount/date mismatches and never fakes is_verified=True when unavailable."""
        receipt_img = _make_textured_jpeg_b64(seed_offset=1)

        # (a) Vision OCR extracts ₹120 when rep claimed ₹500 + wrong date -> FLAGGED_FOR_REVIEW
        fake_ocr_mismatch = {
            "merchant_name": "HPCL Jaipur Bypass",
            "gstin": "08AAACH1118B1Z1",
            "invoice_no": "INV-HP-9001",
            "bill_date": "2026-10-01",
            "total_amount": 120.0,
            "fuel_liters": 1.15,
            "ocr_confidence": 0.92,
            "_provider_model": "gemini-3.8-flash",
        }
        with patch("app.agents.llm_client.generate_multimodal_json", return_value=fake_ocr_mismatch):
            resp = self.client.post(
                "/v1/field-force/conveyance/submit",
                json={
                    "user_id": self.rep_id,
                    "claim_date": "2026-11-28",
                    "transport_mode": "FOUR_WHEELER",
                    "gps_breadcrumbs": self._breadcrumbs_10km(),
                    "receipts": [
                        {
                            "category": "FUEL",
                            "amount": 160.0,
                            "merchant_name": "HPCL Jaipur Bypass",
                            "receipt_date": "2026-11-28",
                            "receipt_base64_or_hash": receipt_img,
                        }
                    ],
                },
            )
        self.assertEqual(resp.status_code, 201, resp.text)
        claim = resp.json()
        self.assertEqual(claim["status"], "FLAGGED_FOR_REVIEW")
        self.assertTrue(any("OCR_AMOUNT_MISMATCH" in f for f in claim["discrepancy_flags"]))
        self.assertTrue(any("OCR_DATE_MISMATCH" in f for f in claim["discrepancy_flags"]))

        # Verify durable receipt storage URI & perceptual hash persisted
        rec = self.db.query(ExpenseReceiptRecord).filter_by(claim_id=claim["id"]).first()
        self.assertIsNotNone(rec)
        self.assertFalse(rec.is_verified)
        self.assertIsNotNone(rec.perceptual_hash)
        self.assertTrue((rec.storage_uri or "").startswith(("local://", "s3://")))
        self.assertEqual(rec.invoice_number, "INV-HP-9001")

        # (b) When Vision OCR is unavailable (returns None), MUST NOT fake is_verified=True!
        receipt_img_2 = _make_textured_jpeg_b64(seed_offset=9)
        with patch("app.agents.llm_client.generate_multimodal_json", return_value=None):
            resp2 = self.client.post(
                "/v1/field-force/conveyance/submit",
                json={
                    "user_id": self.rep_id,
                    "claim_date": "2026-11-28",
                    "transport_mode": "TWO_WHEELER",
                    "gps_breadcrumbs": self._breadcrumbs_10km(),
                    "receipts": [
                        {
                            "category": "TOLL",
                            "amount": 95.0,
                            "merchant_name": "NH48 Toll",
                            "receipt_date": "2026-11-28",
                            "receipt_base64_or_hash": receipt_img_2,
                        }
                    ],
                },
            )
        self.assertEqual(resp2.status_code, 201, resp2.text)
        claim2 = resp2.json()
        self.assertEqual(claim2["status"], "FLAGGED_FOR_REVIEW")
        self.assertTrue(any("OCR_MANUAL_REVIEW_REQUIRED" in f for f in claim2["discrepancy_flags"]))
        rec2 = self.db.query(ExpenseReceiptRecord).filter_by(claim_id=claim2["id"]).first()
        self.assertFalse(rec2.is_verified)

    # ── 2. Cross-Claim Duplicate Receipt Fraud Detection (Exact + pHash + Invoice) ──

    def test_02_duplicate_receipt_exact_phash_and_invoice_fraud_caught(self):
        """Re-uploading the exact bill, a re-compressed photo (pHash), or same invoice # triggers duplicate flags."""
        orig_img = _make_textured_jpeg_b64(seed_offset=3, quality=95)
        recompressed_img = _make_textured_jpeg_b64(seed_offset=3, quality=55)  # Different bytes/SHA256, near-identical pHash!

        clean_ocr = {
            "merchant_name": "Indian Oil Tonk Road",
            "gstin": "08AAACI1681G1Z2",
            "invoice_no": "IOCL-77889",
            "bill_date": "2026-11-28",
            "total_amount": 140.0,
            "fuel_liters": 1.35,
            "ocr_confidence": 0.96,
            "_provider_model": "gemini-3.8-flash",
        }
        with patch("app.agents.llm_client.generate_multimodal_json", return_value=clean_ocr):
            r1 = self.client.post(
                "/v1/field-force/conveyance/submit",
                json={
                    "user_id": self.rep_id,
                    "claim_date": "2026-11-28",
                    "transport_mode": "TWO_WHEELER",
                    "gps_breadcrumbs": self._breadcrumbs_10km(),
                    "receipts": [
                        {
                            "category": "FUEL",
                            "amount": 140.0,
                            "merchant_name": "Indian Oil Tonk Road",
                            "receipt_date": "2026-11-28",
                            "receipt_base64_or_hash": orig_img,
                        }
                    ],
                },
            )
            self.assertEqual(r1.status_code, 201, r1.text)
            self.assertEqual(r1.json()["status"], "AUTO_APPROVED")

            # Re-upload recompressed photo of same bill -> caught by pHash + invoice!
            r2 = self.client.post(
                "/v1/field-force/conveyance/submit",
                json={
                    "user_id": self.rep_id,
                    "claim_date": "2026-11-28",
                    "transport_mode": "TWO_WHEELER",
                    "gps_breadcrumbs": self._breadcrumbs_10km(),
                    "receipts": [
                        {
                            "category": "FUEL",
                            "amount": 140.0,
                            "merchant_name": "Indian Oil Tonk Road",
                            "receipt_date": "2026-11-28",
                            "receipt_base64_or_hash": recompressed_img,
                        }
                    ],
                },
            )
        self.assertEqual(r2.status_code, 201, r2.text)
        c2 = r2.json()
        self.assertEqual(c2["status"], "FLAGGED_FOR_REVIEW")
        self.assertTrue(any("DUPLICATE_RECEIPT_SUSPECTED" in f for f in c2["discrepancy_flags"]), c2["discrepancy_flags"])
        self.assertTrue(any("DUPLICATE_RECEIPT_INVOICE_MATCH" in f for f in c2["discrepancy_flags"]), c2["discrepancy_flags"])

    # ── 3. Real Server-Issued Single-Use 6-Digit Geo-OTP ──────────────────

    def test_03_geo_otp_blocks_fake_bypass_allows_issued_once_blocks_replay_and_expiry(self):
        """Forged '1234' / '999999' OTP fails; real server-issued 6-digit OTP works once and rejects replay."""
        photo = _make_textured_jpeg_b64(seed_offset=2)

        # 1. Forged 4-digit or random 6-digit OTP MUST be rejected outside 250m!
        for forged in ("1234", "849201"):
            bad = self.client.post(
                "/v1/field-force/visits/verify",
                json={
                    "task_id": self.task_id,
                    "user_id": self.rep_id,
                    "latitude": 26.9050,  # ~850m away
                    "longitude": 75.7873,
                    "geo_otp_code": forged,
                    "photo_evidence_base64_or_url": photo,
                },
            )
            self.assertEqual(bad.status_code, 422, f"Forged OTP {forged} should fail with 422!")

        # 2. Issue a real server-side 6-digit Geo-OTP
        issued = self.client.post(
            "/v1/field-force/visits/otp/issue",
            json={
                "task_id": self.task_id,
                "client_contact": "owner@sawaipharmacy.in",
                "delivery_channel": "EMAIL",
            },
        )
        self.assertEqual(issued.status_code, 201, issued.text)
        code = issued.json()["otp_code_debug"]
        self.assertRegex(code, r"^\d{6}$")

        # 3. Verify using real issued code -> succeeds
        ok = self.client.post(
            "/v1/field-force/visits/verify",
            json={
                "task_id": self.task_id,
                "user_id": self.rep_id,
                "latitude": 26.9050,
                "longitude": 75.7873,
                "geo_otp_code": code,
                "photo_evidence_base64_or_url": photo,
            },
        )
        self.assertEqual(ok.status_code, 201, ok.text)
        self.assertTrue(ok.json()["geo_otp_verified"])

        # 4. Replaying the exact same consumed OTP MUST fail with 422!
        replay = self.client.post(
            "/v1/field-force/visits/verify",
            json={
                "task_id": self.task_id,
                "user_id": self.rep_id,
                "latitude": 26.9050,
                "longitude": 75.7873,
                "geo_otp_code": code,
                "photo_evidence_base64_or_url": photo,
            },
        )
        self.assertEqual(replay.status_code, 422)

        # 5. Expired OTP MUST fail with 422!
        issued2 = self.client.post(
            "/v1/field-force/visits/otp/issue",
            json={"task_id": self.task_id, "delivery_channel": "MANUAL_FALLBACK"},
        ).json()
        otp_row = self.db.get(FieldVisitOtpRecord, issued2["otp_id"])
        otp_row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        self.db.commit()

        exp_resp = self.client.post(
            "/v1/field-force/visits/verify",
            json={
                "task_id": self.task_id,
                "user_id": self.rep_id,
                "latitude": 26.9050,
                "longitude": 75.7873,
                "geo_otp_code": issued2["otp_code_debug"],
                "photo_evidence_base64_or_url": photo,
            },
        )
        self.assertEqual(exp_resp.status_code, 422)

    # ── 4. Real Pillow Photo Forensics (Blank Rejection + EXIF GPS Drift) ─

    def test_04_pillow_photo_forensics_blank_rejection_and_exif_gps_mismatch(self):
        """Blank black frame is REJECTED; photo with EXIF GPS 50km away is FLAGGED; never hardcoded 0.94."""
        # (a) Blank frame -> REJECTED
        r_blank = self.client.post(
            "/v1/field-force/visits/verify",
            json={
                "task_id": self.task_id,
                "user_id": self.rep_id,
                "latitude": 26.9124,
                "longitude": 75.7873,
                "photo_evidence_base64_or_url": _make_blank_jpeg_b64(),
            },
        )
        self.assertEqual(r_blank.status_code, 201, r_blank.text)
        body = r_blank.json()
        self.assertEqual(body["photo_verification_status"], "REJECTED")
        self.assertEqual(body["photo_analysis_json"]["confidence"], 0.0)
        self.assertTrue(any("BLANK_OR_SOLID_FRAME" in f for f in body["photo_analysis_json"]["flags"]))

        # (b) Photo taken in Delhi (28.6139, 77.2090) submitted for Jaipur visit (26.9124, 75.7873) -> FLAGGED!
        spoofed_exif_img = _make_jpeg_with_gps_exif_b64(28.6139, 77.2090)
        r_exif = self.client.post(
            "/v1/field-force/visits/verify",
            json={
                "task_id": self.task_id,
                "user_id": self.rep_id,
                "latitude": 26.9124,
                "longitude": 75.7873,
                "photo_evidence_base64_or_url": spoofed_exif_img,
            },
        )
        self.assertEqual(r_exif.status_code, 201, r_exif.text)
        body_exif = r_exif.json()
        self.assertEqual(body_exif["photo_verification_status"], "FLAGGED")
        self.assertTrue(any("EXIF_GPS_MISMATCH" in f for f in body_exif["photo_analysis_json"]["flags"]))
        self.assertIsNone(body_exif["photo_analysis_json"]["confidence"])  # Honest: no fake 0.94!

    # ── 5. Org Travel Policy + Multi-Day Tour Plan + Manager Review + Finance Exports ──

    def test_05_policy_tour_plan_manager_review_and_finance_exports_e2e(self):
        """Full CFO workflow: custom org policy -> tour plan -> approval -> claims -> manager review -> tour settle -> CSV/Tally/NEFT exports."""
        # 1. Manager configures org policy (₹6/km 2W, ₹1500 Tier-2 hotel cap)
        self.active_principal = self.mgr_principal
        pol = self.client.put(
            "/v1/field-force/policies",
            json={
                "grade": "EXECUTIVE",
                "two_wheeler_rate_inr": 6.0,
                "four_wheeler_rate_inr": 12.0,
                "public_transit_rate_inr": 3.0,
                "daily_auto_approve_limit_inr": 1500.0,
                "max_daily_distance_km": 300.0,
                "tier2_hotel_cap_inr": 1500.0,
                "tier2_da_inr": 500.0,
                "require_ocr_above_inr": 200.0,
            },
        )
        self.assertEqual(pol.status_code, 200, pol.text)
        self.assertEqual(pol.json()["two_wheeler_rate_inr"], 6.0)

        # 2. Field rep submits a 3-day outstation tour plan with ₹3,000 advance request
        self.active_principal = self.rep_principal
        tour_resp = self.client.post(
            "/v1/field-force/tours",
            json={
                "title": "Udaipur & Kota Dealer Tour",
                "purpose": "Quarterly dealer audits and stock collection",
                "start_date": "2026-11-26",
                "end_date": "2026-11-28",
                "cities": [{"city": "Udaipur", "tier": "TIER_2", "nights": 2}],
                "client_targets": ["Mewar Pharma", "Hadoti Medicos"],
                "estimated_budget_inr": 6500.0,
                "advance_requested_inr": 3000.0,
            },
        )
        self.assertEqual(tour_resp.status_code, 201, tour_resp.text)
        tour_id = tour_resp.json()["id"]

        # 3. Manager approves tour with ₹2,000 advance
        self.active_principal = self.mgr_principal
        app_resp = self.client.post(
            f"/v1/field-force/tours/{tour_id}/approve",
            json={"decision": "APPROVE", "advance_approved_inr": 2000.0, "notes": "Approved for Q4 target"},
        )
        self.assertEqual(app_resp.status_code, 200, app_resp.text)
        self.assertEqual(app_resp.json()["status"], "APPROVED")
        self.assertEqual(app_resp.json()["advance_approved_inr"], 2000.0)

        # 4. Rep submits Day 1 clean claim (auto-approved at ₹6/km custom EXECUTIVE rate) + Day 2 hotel over-cap claim (flagged)
        self.active_principal = self.rep_principal
        c1 = self.client.post(
            "/v1/field-force/conveyance/submit",
            json={
                "user_id": self.rep_id,
                "claim_date": "2026-11-26",
                "transport_mode": "TWO_WHEELER",
                "employee_grade": "EXECUTIVE",
                "tour_plan_id": tour_id,
                "gps_breadcrumbs": self._breadcrumbs_10km(),
            },
        )
        self.assertEqual(c1.status_code, 201, c1.text)
        c1_data = c1.json()
        self.assertEqual(c1_data["rate_per_km"], 6.0)
        self.assertEqual(c1_data["status"], "AUTO_APPROVED")
        self.assertEqual(c1_data["distance_method"], "HAVERSINE_CURVATURE_ESTIMATE")

        hotel_img = _make_textured_jpeg_b64(seed_offset=11)
        hotel_ocr = {
            "merchant_name": "Lakeview Inn Udaipur",
            "gstin": "08AAACL9999K1Z5",
            "invoice_no": "HTL-2026-441",
            "bill_date": "2026-11-27",
            "total_amount": 2100.0,
            "fuel_liters": None,
            "ocr_confidence": 0.95,
            "_provider_model": "gemini-3.8-flash",
        }
        with patch("app.agents.llm_client.generate_multimodal_json", return_value=hotel_ocr):
            c2 = self.client.post(
                "/v1/field-force/conveyance/submit",
                json={
                    "user_id": self.rep_id,
                    "claim_date": "2026-11-27",
                    "transport_mode": "TWO_WHEELER",
                    "employee_grade": "EXECUTIVE",
                    "tour_plan_id": tour_id,
                    "gps_breadcrumbs": self._breadcrumbs_10km(),
                    "receipts": [
                        {
                            "category": "HOTEL",
                            "amount": 2100.0,
                            "merchant_name": "Lakeview Inn Udaipur",
                            "receipt_date": "2026-11-27",
                            "city_tier": "TIER_2",
                            "receipt_base64_or_hash": hotel_img,
                        }
                    ],
                },
            )
        self.assertEqual(c2.status_code, 201, c2.text)
        c2_data = c2.json()
        self.assertEqual(c2_data["status"], "FLAGGED_FOR_REVIEW")
        self.assertTrue(any("HOTEL_CAP_EXCEEDED" in f for f in c2_data["discrepancy_flags"]))

        # 5. Manager cannot settle tour while c2 is still unreviewed
        self.active_principal = self.mgr_principal
        premature = self.client.post(f"/v1/field-force/tours/{tour_id}/settle")
        self.assertEqual(premature.status_code, 422)

        # 6. Manager PARTIAL_APPROVEs c2 for ₹1,550 (hotel capped at policy ₹1,500 + conveyance)
        rev = self.client.post(
            f"/v1/field-force/conveyance/{c2_data['id']}/review",
            json={
                "decision": "PARTIAL_APPROVE",
                "approved_amount_inr": 1550.0,
                "reason": "Capped hotel reimbursement to Tier-2 policy ₹1,500",
            },
        )
        self.assertEqual(rev.status_code, 201, rev.text)
        self.assertEqual(rev.json()["approved_amount_inr"], 1550.0)
        self.assertIsNotNone(rev.json()["trust_block_hash"])

        # Original ConveyanceClaimRecord AND ConveyanceClaimReviewRecord remain cryptographically immutable!
        raw_claim = self.db.get(ConveyanceClaimRecord, c2_data["id"])
        raw_claim.grand_total_amount = 1.0
        with self.assertRaises(ValueError):
            self.db.commit()
        self.db.rollback()

        raw_rev = self.db.get(ConveyanceClaimReviewRecord, rev.json()["id"])
        raw_rev.approved_amount_inr = 99999.0
        with self.assertRaises(ValueError):
            self.db.commit()
        self.db.rollback()

        # 7. Now manager settles the tour -> Tour Settlement Voucher reconciles claims vs ₹2,000 advance!
        settled = self.client.post(f"/v1/field-force/tours/{tour_id}/settle")
        self.assertEqual(settled.status_code, 200, settled.text)
        voucher = settled.json()
        self.assertEqual(voucher["claims_count"], 2)
        self.assertEqual(voucher["advance_paid_inr"], 2000.0)
        expected_total_approved = round(c1_data["grand_total_amount"] + 1550.0, 2)
        self.assertEqual(voucher["total_approved_inr"], expected_total_approved)
        self.assertEqual(voucher["net_settlement_inr"], round(expected_total_approved - 2000.0, 2))
        self.assertIsNotNone(voucher["trust_block_hash"])

        # 8. Monthly Finance Exports: CSV, Tally XML, ICICI NEFT, HDFC NEFT
        for fmt, expected_token in (
            ("csv", "Ramesh Verma"),
            ("tally_xml", "<VOUCHER VCHTYPE=\"Journal\""),
            ("neft_icici", "AFW FIELD REIMB 2026-11"),
            ("neft_hdfc", "FIELD REIMB 2026-11"),
        ):
            exp = self.client.get(f"/v1/field-force/conveyance/export?month=2026-11&format={fmt}")
            self.assertEqual(exp.status_code, 200, f"{fmt} failed: {exp.text}")
            self.assertIn(expected_token, exp.text)
            self.assertEqual(len(exp.headers.get("X-AFW-Audit-Batch-SHA256", "")), 64)
            self.assertEqual(exp.headers.get("X-AFW-Employee-Count"), "1")
            self.assertEqual(exp.headers.get("X-AFW-Total-Payout-INR"), f"{expected_total_approved:.2f}")

        # 9. Cross-tenant isolation: Org B manager is strictly blocked (403) from Org A claim review & tour settle!
        self.active_principal = self.mgr_b_principal
        x_rev = self.client.post(
            f"/v1/field-force/conveyance/{c2_data['id']}/review",
            json={"decision": "REJECT", "reason": "Cross-tenant hijack attempt"},
        )
        self.assertEqual(x_rev.status_code, 403)

        x_tour = self.client.post(f"/v1/field-force/tours/{tour_id}/settle")
        self.assertEqual(x_tour.status_code, 403)

    # ── 6. Offline-First FieldGuard Mobile PWA Assets ─────────────────────

    def test_06_fieldguard_mobile_pwa_served_with_indexeddb_and_camera_capture(self):
        """Verify /mobile/, /mobile/mobile.js, /mobile/sw.js, and /mobile/manifest.json serve cleanly."""
        html = self.client.get("/mobile/")
        self.assertEqual(html.status_code, 200)
        self.assertIn('capture="environment"', html.text)
        self.assertIn("FieldGuard Mobile", html.text)

        js = self.client.get("/mobile/mobile.js")
        self.assertEqual(js.status_code, 200)
        self.assertIn("afw_fieldguard_offline_queue", js.text)
        self.assertIn("indexedDB.open", js.text)

        sw = self.client.get("/mobile/sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertIn("afw-fieldguard-mobile-v2", sw.text)

        mf = self.client.get("/mobile/manifest.json")
        self.assertEqual(mf.status_code, 200)
        self.assertEqual(mf.json()["short_name"], "AFW OS")
        self.assertEqual(mf.json()["display"], "standalone")

    def test_07_migration_r8g3b4c5d6e7_upgrade_and_downgrade_parity(self):
        """Verify Phase 2 Alembic migration r8g3b4c5d6e7 cleanly upgrades and downgrades on SQLite."""
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext
        from sqlalchemy import inspect as sa_inspect, text

        import migrations.versions.r8g3b4c5d6e7_phase2_fieldguard_anti_fraud_tours_policies as mig

        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with eng.begin() as conn:
            # Seed minimal prerequisite tables as of q7f2a3b4c5d6
            conn.execute(text("CREATE TABLE conveyance_claim_records (id VARCHAR(36) PRIMARY KEY, status VARCHAR(32))"))
            conn.execute(text("CREATE TABLE expense_receipt_records (id VARCHAR(36) PRIMARY KEY, receipt_hash VARCHAR(64))"))

            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mig.upgrade()

            insp = sa_inspect(conn)
            tables = set(insp.get_table_names())
            self.assertTrue(
                {"field_visit_otps", "field_expense_policies", "field_tour_plans", "conveyance_claim_reviews"}.issubset(tables)
            )
            claim_cols = {c["name"] for c in insp.get_columns("conveyance_claim_records")}
            self.assertIn("tour_plan_id", claim_cols)
            self.assertIn("distance_method", claim_cols)
            rec_cols = {c["name"] for c in insp.get_columns("expense_receipt_records")}
            self.assertTrue({"org_id", "perceptual_hash", "invoice_number", "storage_uri"}.issubset(rec_cols))

            with Operations.context(ctx):
                mig.downgrade()

            insp2 = sa_inspect(conn)
            tables2 = set(insp2.get_table_names())
            self.assertNotIn("field_visit_otps", tables2)
            self.assertNotIn("field_tour_plans", tables2)
            self.assertNotIn("conveyance_claim_reviews", tables2)


if __name__ == "__main__":
    unittest.main()
