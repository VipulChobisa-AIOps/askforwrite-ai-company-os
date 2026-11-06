"""Automated Verification for Revenue Readiness Audit Findings (Findings 1, 2, 3, 6, 9).

Validates:
- Finding 3: Public opportunity scan (/v1/previews/scan) pricing and checkout consistency with authoritative catalog.
- Finding 1: Prospect contact verification status (UNVERIFIED_SYNTHETIC vs VERIFIED_EXTRACTED / VERIFIED_CURATED).
- Finding 2: Outreach approval policy assignment (MANUAL_STRICT vs VERIFIED_BATCH_ELIGIBLE).
- Finding 6: Secure single-use account activation link and durable onboarding email retry queue.
- Finding 9: Unified 14-stage CEO commercial acquisition and revenue funnel (/v1/revenue/funnel).
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["APP_ENV"] = "development"
TEST_MANAGER_KEY = "test-manager-key-for-rev-readiness-audit-32-chars"
TEST_OWNER_KEY = "test-owner-key-for-rev-readiness-audit-32-chars"
os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY
os.environ["OWNER_API_KEY"] = TEST_OWNER_KEY

from app.agents.smb_search_source import audit_live_website_seo_geo, discover_smb_leads
from app.db.database import Base, get_db
from app.db.models import ApprovalRequest, LeadRecordRow, OrganizationRecord, UserRecord
from app.main import app
from app.services.catalog import get_package
from app.services.payment import PaymentProvider, WebhookEvent
from app.services.provisioning import auto_provision_tenant_on_payment


class TestRevenueReadinessAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine, autoflush=False, expire_on_commit=False)

        from app.security.auth import APIPrincipal, require_manager

        def override_db():
            db = cls.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_manager] = lambda: APIPrincipal(subject="test-manager", role="manager")
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        from app.security.auth import require_manager
        Base.metadata.drop_all(bind=cls.engine)
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_manager, None)

    def setUp(self):
        self.db = self.session_factory()
        self.manager_headers = {"X-API-Key": TEST_MANAGER_KEY}

    def tearDown(self):
        self.db.close()

    def test_finding_3_public_scan_offer_to_checkout_consistency(self):
        """Public opportunity scan must return pricing and SKU that match CATALOG and checkout 100%."""
        resp = self.client.post(
            "/v1/previews/scan",
            json={"url": "https://acmeretail.in", "company_name": "Acme Retail"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        pkg_key = data["recommended_package"]
        pkg = get_package(pkg_key)
        self.assertIsNotNone(pkg)
        self.assertEqual(pkg.key, "managed_seo_content_pilot")

        # Exact pricing match between scan offer and authoritative catalog
        self.assertEqual(data["price_inr"], pkg.price_inr)
        self.assertEqual(data["price_usd"], pkg.price_usd)
        self.assertEqual(data["package_name"], pkg.name)
        self.assertEqual(data["price_inr"], 4999)
        self.assertEqual(data["price_usd"], 59)
        self.assertIn(f"package={pkg.key}", data["checkout_url"])

    def test_finding_1_prospect_contact_verification_classification(self):
        """Synthetic fallback emails (contact@domain) are explicitly marked UNVERIFIED_SYNTHETIC."""
        # Audit with timeout=0 (offline fallback -> synthetic email)
        audit = audit_live_website_seo_geo("https://unverified-example.co.in", timeout=0.0)
        self.assertFalse(audit["is_contact_verified"])
        self.assertEqual(audit["contact_verification_status"], "UNVERIFIED_SYNTHETIC")

        # Curated SMB leads with contact@domain are classified accurately
        leads = discover_smb_leads(vertical="seo_blog_copilot", limit=3)
        self.assertTrue(len(leads) > 0)
        for ld in leads:
            self.assertIn("is_contact_verified", ld)
            self.assertIn("contact_verification_status", ld)
            if ld["public_contact_channel"] == f"contact@{ld['domain']}":
                self.assertFalse(ld["is_contact_verified"])
                self.assertEqual(ld["contact_verification_status"], "UNVERIFIED_SYNTHETIC")

    def test_finding_2_outreach_approval_policy_for_unverified_vs_verified(self):
        """Outreach to generic contact@domain triggers MANUAL_STRICT policy; verified founder email is VERIFIED_BATCH_ELIGIBLE."""
        org = OrganizationRecord(
            id="org-rev-audit-1",
            name="Rev Audit Org",
            slug="rev-audit-org",
            tier="starter",
            lead_credits_limit=50,
            outreach_credits_limit=50,
            is_active=True,
        )
        lead_unverified = LeadRecordRow(
            id="lead-unv-001",
            org_id=org.id,
            domain="genericbrand.in",
            task_id="task-unv",
            company="Generic Brand",
            website="https://genericbrand.in",
            industry="Retail",
            geography="India",
            observed_signals=["Missing schema"],
            sources=["web"],
            fit_score=0.85,
            confidence=0.85,
            public_contact_channel="contact@genericbrand.in",
            recommended_next_step="outreach",
            do_not_contact=False,
            status="QUALIFIED",
        )
        lead_verified = LeadRecordRow(
            id="lead-ver-001",
            org_id=org.id,
            domain="verifiedbrand.in",
            task_id="task-ver",
            company="Verified Brand",
            website="https://verifiedbrand.in",
            industry="SaaS",
            geography="India",
            observed_signals=["Missing llms.txt"],
            sources=["web"],
            fit_score=0.92,
            confidence=0.90,
            public_contact_channel="founder.ceo@verifiedbrand.in",
            recommended_next_step="outreach",
            do_not_contact=False,
            status="QUALIFIED",
        )
        self.db.add_all([org, lead_unverified, lead_verified])
        self.db.commit()

        # Draft for unverified contact
        r1 = self.client.post(
            "/v1/outreach/draft",
            headers=self.manager_headers,
            json={"lead_id": lead_unverified.id, "org_id": org.id, "idempotency_key": "idem-unv-1"},
        )
        self.assertEqual(r1.status_code, 200)
        appr1 = self.db.get(ApprovalRequest, r1.json()["approval_id"])
        self.assertFalse(appr1.detail["is_contact_verified"])
        self.assertEqual(appr1.detail["approval_policy"], "MANUAL_STRICT")

        # Draft for verified decision-maker contact
        r2 = self.client.post(
            "/v1/outreach/draft",
            headers=self.manager_headers,
            json={"lead_id": lead_verified.id, "org_id": org.id, "idempotency_key": "idem-ver-1"},
        )
        self.assertEqual(r2.status_code, 200)
        appr2 = self.db.get(ApprovalRequest, r2.json()["approval_id"])
        self.assertTrue(appr2.detail["is_contact_verified"])
        self.assertEqual(appr2.detail["approval_policy"], "VERIFIED_BATCH_ELIGIBLE")

    def test_finding_6_activation_link_and_onboarding_email_retry_queue(self):
        """Provisioning generates a 48h activation link and queues retry if SMTP dispatch fails."""
        event = WebhookEvent(
            id="evt_rev_audit_prov_01",
            provider=PaymentProvider.RAZORPAY,
            event_type="payment.captured",
            raw_event_type="payment.captured",
            resource_type="payment",
            resource_id="pay_rev_01",
            data={
                "payload": {
                    "payment": {
                        "entity": {
                            "email": "newclient@pilotcorp.in",
                            "notes": {"notes_package": "managed_seo_content_pilot", "notes_company": "Pilot Corp"},
                            "amount": 499900,
                            "currency": "INR",
                        }
                    }
                }
            },
        )

        # Simulate SMTP transient failure during onboarding
        failing_dispatcher = MagicMock()
        failing_dispatcher.send.side_effect = RuntimeError("SMTP connection timed out")

        with patch("app.services.provisioning.get_email_dispatcher", return_value=failing_dispatcher):
            res = auto_provision_tenant_on_payment(self.db, event)

        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "provisioned")
        self.assertIn("https://os.askforwrite.com/activate?token=", res["activation_url"])

        user = self.db.get(UserRecord, res["user_id"])
        self.assertIsNotNone(user)
        self.assertEqual(user.metadata_json["onboarding_delivery_status"], "RETRY_QUEUED")
        self.assertIn("activation_token", user.metadata_json)

    def test_finding_9_unified_ceo_revenue_funnel_endpoint(self):
        """GET /v1/revenue/funnel returns all 14 funnel stages, conversion rates, and persistent prospect journey."""
        resp = self.client.get("/v1/revenue/funnel", headers=self.manager_headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "OK")

        kpis = body["kpis"]
        expected_keys = {
            "leads_discovered",
            "verified_prospects",
            "qualified_opportunities",
            "previews_generated",
            "preview_views",
            "proposals_issued",
            "outreach_approved",
            "outreach_delivered",
            "replies_received",
            "checkout_initiated",
            "payments_completed",
            "active_subscriptions",
            "mrr_inr",
            "churn_count",
        }
        self.assertTrue(expected_keys.issubset(set(kpis.keys())))
        self.assertIn("conversion_rates", body)
        self.assertIn("prospect_funnel", body)
        self.assertIsInstance(body["prospect_funnel"], list)
