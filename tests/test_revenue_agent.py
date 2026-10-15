"""Unit tests for Commercial Catalog, Revenue Agent Diagnosis, and Webhook Auto-Provisioning."""

import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["APP_ENV"] = "development"
os.environ.pop("ALLOW_SQLITE_PRODUCTION", None)
TEST_MANAGER_KEY = "test-manager-key-for-unit-testing-which-is-at-least-32-chars-long"
TEST_OWNER_KEY = "test-owner-key-for-unit-testing-which-is-at-least-32-chars-long"
os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY
os.environ["OWNER_API_KEY"] = TEST_OWNER_KEY

from app.db.database import Base, get_db
from app.db.models import (
    ApprovalRequest,
    InvoiceRecord,
    LeadRecordRow,
    OrganizationRecord,
    OutreachRecord,
    UserRecord,
    WebhookEventRecord,
)
from app.main import app

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


MANAGER_HEADERS = {"X-API-Key": TEST_MANAGER_KEY}
OWNER_HEADERS = {"X-API-Key": TEST_OWNER_KEY}


class RevenueAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=test_engine)

    def setUp(self):
        os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY
        os.environ["OWNER_API_KEY"] = TEST_OWNER_KEY
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.db = TestingSessionLocal()
        # Clean tables between tests
        self.db.query(WebhookEventRecord).delete()
        self.db.query(InvoiceRecord).delete()
        self.db.query(UserRecord).delete()
        self.db.query(OutreachRecord).delete()
        self.db.query(ApprovalRequest).delete()
        self.db.query(LeadRecordRow).delete()
        self.db.query(OrganizationRecord).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_db, None)

    def test_get_commercial_catalog(self):
        """GET /v1/revenue/catalog returns all modular tools and master bundles with pricing."""
        resp = self.client.get("/v1/revenue/catalog")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["count"], 7)
        keys = [pkg["key"] for pkg in data["packages"]]
        self.assertIn("seo_blog_copilot", keys)
        self.assertIn("marketing_suite", keys)
        self.assertIn("field_force", keys)
        self.assertIn("trust_engine", keys)
        self.assertIn("company_os_starter", keys)
        self.assertIn("company_os_pro", keys)
        self.assertIn("company_os_enterprise", keys)

        # Verify pricing structure
        seo_pkg = next(p for p in data["packages"] if p["key"] == "seo_blog_copilot")
        self.assertEqual(seo_pkg["price_inr"], 1999)
        self.assertEqual(seo_pkg["price_usd"], 29)
        self.assertIn("razorpay", seo_pkg["razorpay_checkout_url"].lower())
        self.assertIn("paypal", seo_pkg["paypal_checkout_url"].lower())
        self.assertIn("Content agencies", seo_pkg["target_buyer_persona"])
        self.assertGreaterEqual(len(seo_pkg["deliverables"]), 3)
        self.assertGreaterEqual(len(seo_pkg["key_features"]), 3)
        self.assertGreaterEqual(len(seo_pkg["seo_geo_aio_capabilities"]), 2)

    def test_diagnose_modular_seo_tool(self):
        """Diagnose lead with content & blogging bottlenecks recommends SEO Blog Copilot."""
        resp = self.client.post(
            "/v1/revenue/diagnose",
            json={
                "company": "Apex Media House",
                "website": "https://apexmedia.example.com",
                "industry": "Digital Media & Publishing",
                "geography": "Mumbai, India",
                "observed_signals": ["struggling with regular blog content", "slow organic SEO ranking on wordpress"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["recommended_package_key"], "seo_blog_copilot")
        self.assertEqual(data["category"], "modular_tool")
        self.assertEqual(data["currency"], "INR")
        self.assertEqual(data["price"], 1999)
        self.assertIn("razorpay", data["payment_link"].lower())
        self.assertIn("Content agencies", data["target_buyer_persona"])
        self.assertGreaterEqual(len(data["deliverables"]), 3)
        self.assertGreaterEqual(len(data["seo_geo_aio_capabilities"]), 2)

    def test_diagnose_modular_field_force_tool(self):
        """Diagnose company with workforce attendance and GPS problems recommends Field Force."""
        resp = self.client.post(
            "/v1/revenue/diagnose",
            json={
                "company": "FastLogistics Courier",
                "website": "https://fastlogistics.example.com",
                "industry": "Express Delivery",
                "geography": "Delhi, India",
                "observed_signals": ["field supervisor coordination issues", "manual attendance fraud"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["recommended_package_key"], "field_force")
        self.assertEqual(data["price"], 3999)

    def test_diagnose_global_lead_recommends_paypal(self):
        """Diagnose US/global lead selects PayPal provider and USD pricing."""
        resp = self.client.post(
            "/v1/revenue/diagnose",
            json={
                "company": "Omni Agency USA",
                "website": "https://omniagency.com",
                "industry": "Marketing & Ads",
                "geography": "Austin, TX, USA",
                "observed_signals": ["scaling ad creative variations", "high agency copy costs"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["recommended_package_key"], "marketing_suite")
        self.assertEqual(data["provider"], "paypal")
        self.assertEqual(data["currency"], "USD")
        self.assertEqual(data["price"], 39)
        self.assertIn("paypal", data["payment_link"].lower())

    def test_pitch_lead_end_to_end_flow(self):
        """POST /v1/revenue/pitch-lead diagnoses lead, generates pitch with payment link, and queues approval."""
        lead = LeadRecordRow(
            id="lead-pitch-001",
            domain="contentcreators.in",
            task_id="task-pitch-1",
            company="Content Creators Studio",
            website="https://contentcreators.in",
            industry="Content & Media",
            geography="Bengaluru, India",
            observed_signals=["need automated wordpress blog publishing", "organic seo keyword growth"],
            sources=[],
            fit_score=0.85,
            confidence=0.9,
            public_contact_channel="contact@contentcreators.in",
            recommended_next_step="commercial_pitch",
            do_not_contact=False,
            status="QUALIFIED",
        )
        self.db.add(lead)
        self.db.commit()

        resp = self.client.post(
            "/v1/revenue/pitch-lead",
            headers=MANAGER_HEADERS,
            json={
                "lead_id": lead.id,
                "idempotency_key": "pitch-lead-test-001",
                "recipient_name": "Rohan Sharma",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "PENDING_APPROVAL")
        self.assertEqual(data["package_key"], "seo_blog_copilot")
        self.assertIn("Content Creators Studio", data["subject"])
        self.assertIn("razorpay", data["payment_link"].lower())
        self.assertIsNotNone(data["approval_id"])

        # Verify OutreachRecord in DB
        outreach = self.db.get(OutreachRecord, data["outreach_id"])
        self.assertIsNotNone(outreach)
        self.assertIn(data["payment_link"], outreach.body_text)

    def test_webhook_auto_provisions_tenant_on_razorpay_payment(self):
        """Simulate Razorpay payment capture webhook: auto-creates tenant Organization, User, and Invoice."""
        webhook_payload = {
            "entity": "event",
            "account_id": "acc_123",
            "event": "payment.captured",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_test_98765",
                        "amount": 799900,  # ₹7,999 in paise (Company OS Starter)
                        "currency": "INR",
                        "status": "captured",
                        "email": "founder@techstartup.in",
                        "contact": "+919876543210",
                        "notes": {
                            "notes_company": "TechStartup Innovations",
                            "notes_package": "company_os_starter",
                        },
                    }
                }
            },
        }

        secret = "rzp_test_webhook_secret_key"
        payload_bytes = json.dumps(webhook_payload).encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

        # Send webhook with valid Razorpay header
        with patch.dict(os.environ, {"RAZORPAY_KEY_SECRET": secret}):
            resp = self.client.post(
                "/v1/webhooks/payment",
                content=payload_bytes,
                headers={
                    "X-Razorpay-Signature": sig,
                    "Content-Type": "application/json",
                },
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("provisioning", data)
        self.assertEqual(data["provisioning"]["status"], "provisioned")
        self.assertEqual(data["provisioning"]["email"], "founder@techstartup.in")

        # Verify Organization created
        org = self.db.query(OrganizationRecord).filter_by(name="TechStartup Innovations").first()
        self.assertIsNotNone(org)
        self.assertEqual(org.tier, "starter")
        self.assertEqual(org.lead_credits_limit, 150)
        self.assertEqual(org.outreach_credits_limit, 75)

        # Verify User created with role manager
        user = self.db.query(UserRecord).filter_by(email="founder@techstartup.in").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.org_id, org.id)
        self.assertIn(user.role, {"admin", "manager"})
        self.assertIsNotNone(user.password_hash)
        self.assertTrue(user.is_active)

        # Verify Invoice created
        inv = self.db.query(InvoiceRecord).filter_by(org_id=org.id).first()
        self.assertIsNotNone(inv)
        self.assertEqual(inv.status, "paid")
        self.assertEqual(inv.amount, 799900)
        self.assertEqual(inv.currency, "INR")
        self.assertEqual(inv.metadata_json.get("customer_email"), "founder@techstartup.in")


if __name__ == "__main__":
    unittest.main()
