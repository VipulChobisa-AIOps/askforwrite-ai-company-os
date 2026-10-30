"""Competitor Adversarial Audit & TDD Verification Suite.

Tests every discovered vulnerability, crash, multi-tenant leak, SSRF bypass,
broken endpoint contract, and edge case across AskforWrite AI Company OS.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agents.discovery import COMPETITOR_DOMAINS
from app.agents.smb_search_source import CURATED_SMB_DIRECTORY, discover_smb_leads
from app.db.database import Base, SessionLocal, engine, get_db
from app.db.models import (
    InvoiceRecord,
    LeadRecordRow,
    OrganizationRecord,
    OutreachRecord,
    UserRecord,
)
from app.main import app
from app.security.auth import create_access_token, hash_password
from app.services.payment import PaymentProvider, get_payment_provider


class CompetitorAdversarialAuditTests(unittest.TestCase):
    """Adversarial TDD test suite targeting competitor-grade bugs across all system units."""

    @classmethod
    def setUpClass(cls):
        os.environ["APP_ENV"] = "development"
        cls.manager_key = "test-manager-key-adversarial-audit-32chars"
        cls.owner_key = "test-owner-key-adversarial-audit-32chars!!"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        os.environ["OWNER_API_KEY"] = cls.owner_key
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        cls.manager_headers = {
            "X-API-Key": cls.manager_key,
            "X-Correlation-ID": "adv-mgr-corr",
        }
        cls.owner_headers = {
            "X-API-Key": cls.owner_key,
            "X-Correlation-ID": "adv-owner-corr",
        }
        cls.mobile_headers = {
            "Authorization": f"Bearer {cls.manager_key}",
        }

    def setUp(self):
        self.db = SessionLocal()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_db, None)

    def _create_tenant_org_and_token(self, tier: str = "growth_all_in_one") -> tuple[OrganizationRecord, UserRecord, str]:
        suffix = uuid.uuid4().hex[:8]
        org = OrganizationRecord(
            id=f"org-adv-{suffix}",
            name=f"Adversarial Org {suffix}",
            slug=f"adv-org-{suffix}",
            tier=tier,
            lead_credits_limit=50,
            lead_credits_used=0,
            outreach_credits_limit=50,
            outreach_credits_used=0,
            is_active=True,
        )
        user = UserRecord(
            id=f"usr-adv-{suffix}",
            email=f"founder-{suffix}@advtest.in",
            password_hash=hash_password("StrongPass123!"),
            full_name="Adversarial Tester",
            role="admin",
            org_id=org.id,
            is_active=True,
        )
        self.db.add_all([org, user])
        self.db.commit()
        token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
            org_id=org.id,
        )
        return org, user, token

    # ── 1. Customer Portal `/v1/me/use-service` Growth Suite Crash ─────────────

    def test_01_customer_portal_use_service_growth_all_in_one_succeeds(self):
        """POST /v1/me/use-service with service_key='growth_all_in_one' must not crash with TypeError."""
        org, _user, token = self._create_tenant_org_and_token(tier="growth_all_in_one")
        headers = {"Authorization": f"Bearer {token}"}

        resp = self.client.post(
            "/v1/me/use-service",
            headers=headers,
            json={
                "service_key": "growth_all_in_one",
                "payload": {
                    "product_name": "Autonomous Supply Chain Cloud",
                    "target_audience": "3PL Operations Directors",
                    "keywords": ["warehouse automation", "inventory AI"],
                },
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "COMPLETED")
        self.assertEqual(body["service_key"], "growth_all_in_one")
        self.assertIn("result", body)
        self.db.refresh(org)
        self.assertEqual(org.lead_credits_used, 1)

    # ── 2. Mobile Bridge `/v1/mobile/conveyance/claim` Crash ───────────────────

    def test_02_mobile_conveyance_claim_succeeds_without_import_or_attribute_error(self):
        """POST /v1/mobile/conveyance/claim must calculate & persist claim without ImportError/AttributeError."""
        resp = self.client.post(
            "/v1/mobile/conveyance/claim",
            headers=self.mobile_headers,
            json={
                "date": "2026-10-30",
                "distance_km": 22.5,
                "vehicle_type": "two_wheeler",
                "purpose": "Udaipur industrial area client visits",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["status"], "submitted")
        self.assertGreater(data["amount"], 0)
        self.assertEqual(data["currency"], "INR")
        self.assertIn("approval_status", data)
        self.assertIsInstance(data["fraud_flag"], bool)

    # ── 3. Mobile Bridge `/v1/mobile/attendance/check-in` Check-Out Support ───

    def test_03_mobile_attendance_supports_check_in_and_check_out(self):
        """POST /v1/mobile/attendance/check-in must honor check_type='check_out' instead of always checking in."""
        # Step 1: Check-in
        in_resp = self.client.post(
            "/v1/mobile/attendance/check-in",
            headers=self.mobile_headers,
            json={
                "latitude": 24.5855,
                "longitude": 73.7126,
                "accuracy_meters": 8.0,
                "check_type": "check_in",
            },
        )
        self.assertEqual(in_resp.status_code, 200, in_resp.text)
        self.assertEqual(in_resp.json()["event_type"], "CHECK_IN")

        # Step 2: Check-out using check_type='check_out'
        out_resp = self.client.post(
            "/v1/mobile/attendance/check-in",
            headers=self.mobile_headers,
            json={
                "latitude": 24.5860,
                "longitude": 73.7130,
                "accuracy_meters": 9.0,
                "check_type": "check_out",
            },
        )
        self.assertEqual(out_resp.status_code, 200, out_resp.text)
        out_data = out_resp.json()
        self.assertEqual(out_data["event_type"], "CHECK_OUT")

    # ── 4. Legal Declaration Plain Text Rendering ─────────────────────────────

    def test_04_legal_declaration_plain_text_does_not_split_string_into_chars(self):
        """GET /legal/declaration?format=text must render full statutory protection sentence, not single chars."""
        resp = self.client.get("/legal/declaration?format=text")
        self.assertEqual(resp.status_code, 200)
        text = resp.text
        self.assertIn("As a formally registered MSME under the MSMED Act, 2006", text)
        self.assertNotIn("- A\n- s\n-  \n- a", text)

    # ── 5. SSRF Protection on `/v1/growth/audit-domain` ───────────────────────

    def test_05_growth_audit_domain_rejects_ssrf_internal_targets(self):
        """POST /v1/growth/audit-domain must reject loopback, private IP, and cloud metadata URLs with 400."""
        unsafe_targets = [
            "http://127.0.0.1:8000/health",
            "http://localhost/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/internal",
        ]
        for target in unsafe_targets:
            resp = self.client.post("/v1/growth/audit-domain", json={"website_url": target})
            self.assertEqual(
                resp.status_code,
                400,
                f"Expected 400 for SSRF target {target}, got {resp.status_code}: {resp.text}",
            )

    # ── 6. Competitor Domains Excluded from SMB Discovery ─────────────────────

    def test_06_smb_discovery_excludes_competitor_domains(self):
        """CURATED_SMB_DIRECTORY and discover_smb_leads must never return domains listed in COMPETITOR_DOMAINS."""
        for vertical, candidates in CURATED_SMB_DIRECTORY.items():
            for cand in candidates:
                website = cand.get("website", "").lower()
                for comp_dom in COMPETITOR_DOMAINS:
                    self.assertNotIn(
                        comp_dom,
                        website,
                        f"Curated candidate {website} in {vertical} is a blocked competitor domain ({comp_dom})!",
                    )

        leads = discover_smb_leads(vertical="field_operations_automation", limit=10)
        self.assertGreater(len(leads), 0)
        for lead in leads:
            self.assertNotIn(
                lead["domain"].lower(),
                COMPETITOR_DOMAINS,
                f"Discovered lead {lead['domain']} is a blocked competitor domain!",
            )

    # ── 7. Multi-Tenant Quota & Isolation on `/v1/leads/discover`, `/enrich`, `/v1/revenue/pitch-lead` ──

    def test_07_tenant_jwt_without_explicit_org_id_consumes_credits_and_enforces_isolation(self):
        """When a tenant JWT calls /v1/leads/enrich or /v1/revenue/pitch-lead without payload.org_id,
        their org_id must still be enforced for tenant access and credit consumption."""
        org_a, _user_a, token_a = self._create_tenant_org_and_token(tier="growth_all_in_one")
        org_b, _user_b, _token_b = self._create_tenant_org_and_token(tier="growth_all_in_one")
        headers_a = {"Authorization": f"Bearer {token_a}"}

        lead_a = LeadRecordRow(
            id=str(uuid.uuid4()),
            org_id=org_a.id,
            domain="freshmangoesindia.in",
            task_id=str(uuid.uuid4()),
            company="Fresh Mangoes India",
            website="https://freshmangoesindia.in",
            industry="AgriTech",
            geography="India",
            observed_signals=["export quality inspection"],
            sources=[{"source": "test"}],
            product_match="mango_quality_ai",
            fit_score=0.91,
            confidence=0.90,
            public_contact_channel="exports@freshmangoesindia.in",
            recommended_next_step="outreach_review",
            do_not_contact=False,
            status="DISCOVERED",
        )
        lead_b = LeadRecordRow(
            id=str(uuid.uuid4()),
            org_id=org_b.id,
            domain="otherorglogistics.in",
            task_id=str(uuid.uuid4()),
            company="Other Org Logistics",
            website="https://otherorglogistics.in",
            industry="Logistics",
            geography="India",
            observed_signals=["warehouse inventory"],
            sources=[{"source": "test"}],
            product_match="warehouse_automation",
            fit_score=0.89,
            confidence=0.88,
            public_contact_channel="ops@otherorglogistics.in",
            recommended_next_step="outreach_review",
            do_not_contact=False,
            status="DISCOVERED",
        )
        self.db.add_all([lead_a, lead_b])
        self.db.commit()

        # Tenant A cannot pitch Tenant B's lead even when omitting org_id in payload
        cross_pitch = self.client.post(
            "/v1/revenue/pitch-lead",
            headers=headers_a,
            json={"lead_id": lead_b.id, "idempotency_key": f"idem-cross-{uuid.uuid4().hex[:8]}"},
        )
        self.assertEqual(cross_pitch.status_code, 403, cross_pitch.text)

        # Tenant A pitching their own lead without payload.org_id consumes 1 outreach credit on org_a
        own_pitch = self.client.post(
            "/v1/revenue/pitch-lead",
            headers=headers_a,
            json={"lead_id": lead_a.id, "idempotency_key": f"idem-own-{uuid.uuid4().hex[:8]}"},
        )
        self.assertEqual(own_pitch.status_code, 200, own_pitch.text)
        self.db.refresh(org_a)
        self.assertEqual(org_a.outreach_credits_used, 1)

        # Tenant A enriching their own lead without payload.org_id consumes lead credit on org_a
        enrich_resp = self.client.post(
            "/v1/leads/enrich",
            headers=headers_a,
            json={"lead_ids": [lead_a.id]},
        )
        self.assertEqual(enrich_resp.status_code, 200, enrich_resp.text)
        self.db.refresh(org_a)
        self.assertGreaterEqual(org_a.lead_credits_used, 1)

    # ── 8. Cross-Tenant Isolation on Reconciliation Ledger & Audit Summary ────

    def test_08_reconciliation_ledger_and_audit_summary_tenant_scoped(self):
        """Tenant A must not see Tenant B's reconciled invoices in reconciliation ledger."""
        org_a, _user_a, token_a = self._create_tenant_org_and_token()
        org_b, _user_b, _token_b = self._create_tenant_org_and_token()
        headers_a = {"Authorization": f"Bearer {token_a}"}

        inv_b = InvoiceRecord(
            id=f"inv-b-{uuid.uuid4().hex[:8]}",
            org_id=org_b.id,
            customer_id=f"cust-b-{uuid.uuid4().hex[:6]}",
            provider="afw_directpay",
            provider_invoice_id=f"AFW-INV-{uuid.uuid4().hex[:8]}",
            provider_payment_id="UTR998877665544",
            amount=999900,
            currency="INR",
            status="paid",
            metadata_json={
                "reconciliation": {
                    "reconciled": True,
                    "bank_statement_utr": "SBIN0099887766",
                    "settled_amount": 9999.0,
                    "settlement_date": "2026-10-30",
                }
            },
        )
        self.db.add(inv_b)
        self.db.commit()

        ledger_resp = self.client.get("/v1/pay/reconciliation-ledger", headers=headers_a)
        self.assertEqual(ledger_resp.status_code, 200)
        ledger_ids = [item["invoice_id"] for item in ledger_resp.json()["invoices"]]
        self.assertNotIn(inv_b.id, ledger_ids)

    # ── 9. Outreach Record-Reply Conflict & SENT Reply Handling ───────────────

    def test_09_outreach_record_reply_handles_unsent_409_and_sent_200(self):
        """POST /v1/outreach/{id}/record-reply on PENDING_APPROVAL returns 409, and on SENT returns 200 without AttributeError."""
        lead = LeadRecordRow(
            id=str(uuid.uuid4()),
            org_id=None,
            domain="conflictcheck.in",
            task_id=str(uuid.uuid4()),
            company="Conflict Check Pvt Ltd",
            website="https://conflictcheck.in",
            industry="SaaS",
            geography="India",
            observed_signals=["automation"],
            sources=[{"source": "test"}],
            product_match="company_os_starter",
            fit_score=0.85,
            confidence=0.85,
            public_contact_channel="hello@conflictcheck.in",
            recommended_next_step="outreach_review",
            do_not_contact=False,
            status="DISCOVERED",
        )
        outreach_pending = OutreachRecord(
            id=str(uuid.uuid4()),
            lead_id=lead.id,
            task_id=str(uuid.uuid4()),
            recipient_email="hello@conflictcheck.in",
            subject="Subject",
            body_text="Body",
            status="PENDING_APPROVAL",
            idempotency_key=f"idem-reply-{uuid.uuid4().hex[:8]}",
        )
        outreach_sent = OutreachRecord(
            id=str(uuid.uuid4()),
            lead_id=lead.id,
            task_id=str(uuid.uuid4()),
            recipient_email="hello@conflictcheck.in",
            subject="Subject Sent",
            body_text="Body Sent",
            status="SENT",
            idempotency_key=f"idem-reply-sent-{uuid.uuid4().hex[:8]}",
        )
        self.db.add_all([lead, outreach_pending, outreach_sent])
        self.db.commit()

        # Unsent outreach record must return 409 Conflict
        resp_409 = self.client.post(
            f"/v1/outreach/{outreach_pending.id}/record-reply",
            headers=self.manager_headers,
            json={"reply_text": "Interested in demo", "intent": "interested", "channel": "email_notes"},
        )
        self.assertEqual(resp_409.status_code, 409, resp_409.text)

        # Sent outreach record must return 200 OK without crashing on record.package_key
        resp_200 = self.client.post(
            f"/v1/outreach/{outreach_sent.id}/record-reply",
            headers=self.manager_headers,
            json={"reply_text": "We have budget approved for Q4 deployment", "intent": "interested", "channel": "email_notes"},
        )
        self.assertEqual(resp_200.status_code, 200, resp_200.text)
        self.assertEqual(resp_200.json()["status"], "QUALIFIED_AND_PROPOSAL_DRAFTED")

    # ── 10. Razorpay Webhook Verification & Sitemap `/services` Coverage ──────

    def test_10_razorpay_webhook_verification_with_key_secret_when_webhook_secret_set(self):
        """RazorpayProvider.verify_webhook must validate signatures signed with RAZORPAY_KEY_SECRET
        even if RAZORPAY_WEBHOOK_SECRET is empty or also set in environment."""
        import asyncio

        payload = b'{"event":"payment.captured"}'
        key_secret = "rzp_dynamic_key_secret_test"
        sig = hmac.new(key_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

        with patch.dict(
            os.environ,
            {
                "RAZORPAY_KEY_SECRET": key_secret,
                "RAZORPAY_WEBHOOK_SECRET": "different_or_default_webhook_secret",
            },
        ):
            provider = get_payment_provider(PaymentProvider.RAZORPAY)
            valid = asyncio.run(provider.verify_webhook(payload, {"x-razorpay-signature": sig}))
            self.assertTrue(valid)

        sitemap = self.client.get("/sitemap.xml")
        self.assertEqual(sitemap.status_code, 200)
        self.assertIn("https://os.askforwrite.com/services", sitemap.text)
        self.assertIn("https://os.askforwrite.com/services/warehouse-automation", sitemap.text)


if __name__ == "__main__":
    unittest.main()
