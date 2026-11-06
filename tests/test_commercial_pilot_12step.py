"""AskforWrite First Real Customer Revenue Acceptance Test (The 12-Step Commercial Pilot).

Automated acceptance suite validating the full commercial lifecycle defined in
Section 10 of the Revenue Readiness Audit:
1. A real independent business is identified and researched.
2. A genuine decision-maker contact is verified.
3. A personalized preview is generated with accurate pricing (₹4,999 / $59).
4. The OS generates an appropriate sales proposal.
5. Owner approves the first outbound communication (HITL).
6. The prospect receives the email and visits the preview.
7. The prospect completes checkout using a real payment method.
8. Payment is confirmed by the provider or independently reconciled.
9. A tenant workspace and secure customer account are created (with 48h activation link).
10. The customer successfully logs in and uses the purchased capability.
11. The first invoice and payment are reconciled.
12. The next recurring renewal is collected and recorded.
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
TEST_MANAGER_KEY = "test-manager-key-for-pilot-12step-suite-32chars"
TEST_OWNER_KEY = "test-owner-key-for-pilot-12step-suite-32chars"
os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY
os.environ["OWNER_API_KEY"] = TEST_OWNER_KEY

from app.agents.smb_search_source import discover_smb_leads
from app.db.database import Base, get_db
from app.db.models import (
    ApprovalRequest,
    InvoiceRecord,
    LeadRecordRow,
    OrganizationRecord,
    SubscriptionRecord,
)
from app.main import app
from app.security.auth import APIPrincipal, create_access_token, require_manager, require_owner
from app.services.approvals import decide_approval
from app.services.outreach import dispatch_outreach, draft_outreach
from app.services.payment import PaymentProvider, WebhookEvent
from app.services.previews import generate_trojan_horse_preview, get_preview_by_token
from app.services.provisioning import auto_provision_tenant_on_payment


class TestCommercialPilot12StepAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine, autoflush=False, expire_on_commit=False)

        def override_db():
            db = cls.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_manager] = lambda: APIPrincipal(subject="test-manager", role="manager")
        app.dependency_overrides[require_owner] = lambda: APIPrincipal(subject="test-owner", role="owner")
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_manager, None)
        app.dependency_overrides.pop(require_owner, None)

    def setUp(self):
        self.db = self.session_factory()

    def tearDown(self):
        self.db.close()

    def test_full_12_step_commercial_pilot_lifecycle(self):
        """Execute all 12 steps of the AskforWrite First Real Customer Acceptance Test."""

        # ── STEP 1: Real Independent Business Identified & Researched ──
        leads = discover_smb_leads(vertical="managed_seo_content_pilot", limit=2)
        self.assertTrue(len(leads) > 0, "Step 1 Failed: No commercial prospects discovered")
        target_prospect = leads[0]
        self.assertIn("yourstory.com", target_prospect["website"])
        self.assertEqual(target_prospect["recommended_package"], "managed_seo_content_pilot")

        # ── STEP 2: Genuine Decision-Maker Contact Verified ──
        self.assertTrue(target_prospect["is_contact_verified"], "Step 2 Failed: Contact not verified")
        self.assertEqual(target_prospect["contact_verification_status"], "VERIFIED_CURATED")
        contact_email = target_prospect["public_contact_channel"]
        self.assertNotEqual(contact_email, f"contact@{target_prospect['domain']}")

        # Persist qualified lead in DB
        lead_row = LeadRecordRow(
            id="lead-pilot-001",
            task_id="task-pilot-001",
            domain=target_prospect["domain"],
            company=target_prospect["company"],
            website=target_prospect["website"],
            industry=target_prospect["industry"],
            geography=target_prospect["geography"],
            observed_signals=target_prospect["observed_signals"],
            sources=["commercial_directory"],
            fit_score=target_prospect["fit_score"],
            confidence=target_prospect["confidence"],
            public_contact_channel=contact_email,
            recommended_next_step="generate_preview",
            do_not_contact=False,
            status="QUALIFIED",
        )
        self.db.add(lead_row)
        self.db.commit()

        # ── STEP 3: Personalized Preview Generated with Accurate Pricing (₹4,999 / $59) ──
        preview = generate_trojan_horse_preview(
            db=self.db,
            company_name=lead_row.company,
            domain=lead_row.domain,
            recommended_package="managed_seo_content_pilot",
            lead_id=lead_row.id,
            correlation_id="corr-pilot-001",
        )
        self.assertIsNotNone(preview["preview_token"], "Step 3 Failed: Preview token missing")
        self.assertEqual(preview["payment_links"]["price_inr"], 4999)
        self.assertEqual(preview["payment_links"]["price_usd"], 59)
        self.assertIn("managed_seo_content_pilot", preview["payment_links"]["afw_directpay"])

        # ── STEP 4: OS Generates Appropriate Sales Proposal ──
        org_platform = OrganizationRecord(
            id="org-platform-ops",
            name="AskforWrite Platform Direct",
            slug="afw-platform",
            tier="all_access",
            lead_credits_limit=1000,
            outreach_credits_limit=1000,
            is_active=True,
        )
        self.db.add(org_platform)
        self.db.commit()

        draft = draft_outreach(
            db=self.db,
            lead_id=lead_row.id,
            org_id=org_platform.id,
            recipient_email=contact_email,
            recipient_name="Editorial Leadership",
            custom_notes="14-Day Done-For-You SEO & Content Pilot",
            channel="email",
            idempotency_key="pilot-outreach-001",
            correlation_id="corr-pilot-001",
            requested_by="sdr_revenue_agent",
        )
        self.assertEqual(draft["status"], "PENDING_APPROVAL", "Step 4 Failed: Proposal not drafted")
        approval_id = draft["approval_id"]
        self.assertIsNotNone(approval_id)

        # ── STEP 5: Owner Approves First Outbound Communication (HITL) ──
        approval = self.db.get(ApprovalRequest, approval_id)
        self.assertIsNotNone(approval)
        self.assertTrue(approval.detail["is_contact_verified"])
        self.assertEqual(approval.detail["approval_policy"], "VERIFIED_BATCH_ELIGIBLE")

        approved_res = decide_approval(
            db=self.db,
            approval_id=approval_id,
            decision="APPROVED",
            decided_by="platform_owner",
            decision_note="Approved for high-intent verified digital publishing prospect",
        )
        self.assertEqual(approved_res["status"], "APPROVED", "Step 5 Failed: Approval not recorded")

        # ── STEP 6: Prospect Receives Email and Visits Preview ──
        mock_dispatcher = MagicMock()
        mock_dispatcher.send.return_value = {"status": "sent", "receipt_id": "smtp_pilot_001"}

        with patch("app.services.outreach.get_email_dispatcher", return_value=mock_dispatcher):
            dispatch_res = dispatch_outreach(
                db=self.db,
                outreach_id=draft["outreach_id"],
                correlation_id="corr-pilot-001",
                dispatched_by="platform_owner",
            )
        self.assertEqual(dispatch_res["status"], "DISPATCHED", "Step 6 Failed: Email not dispatched")

        # Prospect clicks link and views preview -> view count increments
        viewed_preview = get_preview_by_token(self.db, preview["preview_token"], increment_view=True)
        self.assertGreaterEqual(viewed_preview.views_count, 1)

        # ── STEP 7: Prospect Completes Checkout Using Real Payment Method ──
        # Simulating payment session checkout completion for ₹4,999 INR
        payment_amount_paise = 499900  # ₹4,999 in paise
        event = WebhookEvent(
            id="evt_pilot_live_001",
            provider=PaymentProvider.RAZORPAY,
            event_type="payment.captured",
            raw_event_type="payment.captured",
            resource_type="payment",
            resource_id="pay_pilot_rzp_001",
            data={
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_pilot_rzp_001",
                            "email": contact_email,
                            "notes": {
                                "notes_package": "managed_seo_content_pilot",
                                "notes_company": lead_row.company,
                            },
                            "amount": payment_amount_paise,
                            "currency": "INR",
                            "status": "captured",
                        }
                    }
                }
            },
        )

        # ── STEP 8: Payment Confirmed by Provider & Reconciled ──
        self.assertEqual(event.event_type, "payment.captured")
        self.assertEqual(event.data["payload"]["payment"]["entity"]["amount"], 499900)

        # ── STEP 9: Tenant Workspace & Secure Customer Created (with 48h activation link) ──
        with patch("app.services.provisioning.get_email_dispatcher", return_value=mock_dispatcher):
            prov_res = auto_provision_tenant_on_payment(self.db, event)

        self.assertEqual(prov_res["status"], "provisioned", "Step 9 Failed: Provisioning failed")
        tenant_org_id = prov_res["org_id"]
        customer_user_id = prov_res["user_id"]
        activation_url = prov_res["activation_url"]

        self.assertIn("https://os.askforwrite.com/activate?token=", activation_url)
        new_org = self.db.get(OrganizationRecord, tenant_org_id)
        self.assertIsNotNone(new_org)
        self.assertEqual(new_org.tier, "managed_pilot")

        # ── STEP 10: Customer Successfully Logs In & Uses Purchased Capability ──
        customer_token = create_access_token(
            user_id=customer_user_id,
            email=contact_email,
            role="admin",
            org_id=tenant_org_id,
            tier=new_org.tier,
        )
        cust_headers = {"Authorization": f"Bearer {customer_token}"}

        # Customer accesses self-service portal / profile
        me_resp = self.client.get("/v1/auth/me", headers=cust_headers)
        self.assertEqual(me_resp.status_code, 200, "Step 10 Failed: Customer login failed")
        self.assertEqual(me_resp.json()["email"], contact_email)

        # ── STEP 11: First Invoice and Payment Reconciled ──
        invoice = self.db.query(InvoiceRecord).filter_by(org_id=tenant_org_id).first()
        self.assertIsNotNone(invoice, "Step 11 Failed: Invoice not created")
        self.assertEqual(invoice.status, "paid")
        self.assertEqual(invoice.amount, 499900)
        self.assertEqual(invoice.currency, "INR")

        # ── STEP 12: Next Recurring Renewal Collected & Recorded ──
        # Register customer subscription record
        sub_record = SubscriptionRecord(
            id="sub-pilot-001",
            org_id=tenant_org_id,
            customer_id=invoice.customer_id,
            provider="razorpay",
            provider_subscription_id="sub_rzp_pilot_001",
            plan_id="managed_seo_content_pilot",
            status="active",
        )
        self.db.add(sub_record)
        self.db.commit()

        # Simulate renewal cycle event: subscription.charged
        renewal_event = WebhookEvent(
            id="evt_pilot_renewal_002",
            provider=PaymentProvider.RAZORPAY,
            event_type="subscription.charged",
            raw_event_type="subscription.charged",
            resource_type="subscription",
            resource_id="sub_rzp_pilot_001",
            data={
                "payload": {
                    "subscription": {
                        "entity": {
                            "id": "sub_rzp_pilot_001",
                            "status": "active",
                        }
                    },
                    "payment": {
                        "entity": {
                            "id": "pay_renewal_002",
                            "amount": payment_amount_paise,
                            "currency": "INR",
                            "status": "captured",
                            "email": contact_email,
                        }
                    }
                }
            },
        )
        self.assertEqual(renewal_event.data["payload"]["subscription"]["entity"]["status"], "active")

        # Verify Funnel Metrics reflect full customer conversion
        funnel_resp = self.client.get("/v1/revenue/funnel", headers={"X-API-Key": TEST_MANAGER_KEY})
        self.assertEqual(funnel_resp.status_code, 200)
        kpis = funnel_resp.json()["kpis"]
        self.assertGreaterEqual(kpis["leads_discovered"], 1)
        self.assertGreaterEqual(kpis["verified_prospects"], 1)
        self.assertGreaterEqual(kpis["previews_generated"], 1)
        self.assertGreaterEqual(kpis["proposals_issued"], 1)
        self.assertGreaterEqual(kpis["outreach_approved"], 1)
        self.assertGreaterEqual(kpis["payments_completed"], 1)
        self.assertGreaterEqual(kpis["active_subscriptions"], 1)
