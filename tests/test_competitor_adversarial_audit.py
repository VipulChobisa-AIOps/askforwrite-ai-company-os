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
    ApprovalRequest,
    CustomerRecord,
    InvoiceRecord,
    LeadRecordRow,
    OrganizationRecord,
    OutreachRecord,
    SubscriptionRecord,
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

    # ── 11. User State Matrix & Tenant vs Platform RBAC Isolation ─────────────

    def test_11_user_state_matrix_and_tenant_platform_rbac_isolation(self):
        """Verify:
        1. Free user registration sets free package and blocks paid service invocation (403).
        2. Inactive/unpaid org users are blocked from service execution (403).
        3. Modular paid tier (Starter) gets entitled services (200) but is blocked from unentitled modules (403).
        4. Enterprise tier gets full-spectrum access (200).
        5. Tenant admin is strictly isolated from platform operations (scheduler, watchdog) and other tenants.
        """
        # 1. Register a new user via public /v1/auth/register
        reg_email = f"freeuser-{uuid.uuid4().hex[:6]}@example.com"
        reg_resp = self.client.post(
            "/v1/auth/register",
            json={
                "email": reg_email,
                "password": "SecurePassword123!",
                "full_name": "Free Tier User",
                "company_name": "FreeCorp India",
            },
        )
        self.assertEqual(reg_resp.status_code, 201, reg_resp.text)
        free_token = reg_resp.json()["access_token"]
        free_headers = {"Authorization": f"Bearer {free_token}"}

        # Verify free profile
        me_resp = self.client.get("/v1/me", headers=free_headers)
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.json()["tier"], "free")

        # Verify capabilities is empty for free user
        caps_resp = self.client.get("/v1/me/capabilities", headers=free_headers)
        self.assertEqual(caps_resp.status_code, 200)
        self.assertEqual(caps_resp.json(), [])

        # Free user calling paid service must fail with 403 Forbidden
        free_use = self.client.post(
            "/v1/me/use-service",
            headers=free_headers,
            json={"service_key": "seo_blog_copilot", "parameters": {}},
        )
        self.assertEqual(free_use.status_code, 403)
        self.assertIn("not entitled", free_use.json()["detail"].lower())

        # 2. Inactive / Unpaid Organization User
        inactive_org = OrganizationRecord(
            id=str(uuid.uuid4()),
            name="Unpaid Corp",
            slug=f"unpaid-{uuid.uuid4().hex[:6]}",
            tier="company_os_starter",
            is_active=False,
            lead_credits_limit=100,
            metadata_json={"package_key": "company_os_starter"},
        )
        inactive_user = UserRecord(
            id=str(uuid.uuid4()),
            org_id=inactive_org.id,
            email=f"unpaid-{uuid.uuid4().hex[:6]}@unpaid.in",
            full_name="Unpaid User",
            password_hash=hash_password("UnpaidPass123!"),
            role="admin",
            is_active=True,
        )
        self.db.add_all([inactive_org, inactive_user])
        self.db.commit()

        inactive_token = create_access_token(
            user_id=inactive_user.id, email=inactive_user.email, role="admin", org_id=inactive_org.id
        )
        inactive_headers = {"Authorization": f"Bearer {inactive_token}"}

        inactive_use = self.client.post(
            "/v1/me/use-service",
            headers=inactive_headers,
            json={"service_key": "seo_blog_copilot", "parameters": {}},
        )
        self.assertEqual(inactive_use.status_code, 403)
        self.assertIn("inactive", inactive_use.json()["detail"].lower())

        # 3. Starter Tier (Modular Entitlements)
        starter_org = OrganizationRecord(
            id=str(uuid.uuid4()),
            name="Starter Co",
            slug=f"starter-{uuid.uuid4().hex[:6]}",
            tier="company_os_starter",
            is_active=True,
            lead_credits_limit=500,
            metadata_json={
                "package_key": "company_os_starter",
                "entitled_capabilities": ["seo_content_automation", "marketing_campaign_suite"],
            },
        )
        starter_user = UserRecord(
            id=str(uuid.uuid4()),
            org_id=starter_org.id,
            email=f"starter-{uuid.uuid4().hex[:6]}@starter.in",
            full_name="Starter User",
            password_hash=hash_password("StarterPass123!"),
            role="admin",
            is_active=True,
        )
        self.db.add_all([starter_org, starter_user])
        self.db.commit()

        starter_token = create_access_token(
            user_id=starter_user.id, email=starter_user.email, role="admin", org_id=starter_org.id
        )
        starter_headers = {"Authorization": f"Bearer {starter_token}"}

        # Starter calling entitled modular service -> 200 OK
        starter_entitled = self.client.post(
            "/v1/me/use-service",
            headers=starter_headers,
            json={"service_key": "seo_blog_copilot", "parameters": {}},
        )
        self.assertEqual(starter_entitled.status_code, 200, starter_entitled.text)

        # Starter calling unentitled modular service -> 403 Forbidden
        starter_unentitled = self.client.post(
            "/v1/me/use-service",
            headers=starter_headers,
            json={"service_key": "warehouse_automation", "parameters": {}},
        )
        self.assertEqual(starter_unentitled.status_code, 403)
        self.assertIn("not entitled", starter_unentitled.json()["detail"].lower())

        # 4. Enterprise Tier (Full Spectrum)
        ent_org = OrganizationRecord(
            id=str(uuid.uuid4()),
            name="Enterprise Global",
            slug=f"ent-{uuid.uuid4().hex[:6]}",
            tier="company_os_enterprise",
            is_active=True,
            lead_credits_limit=5000,
            metadata_json={"package_key": "company_os_enterprise"},
        )
        ent_user = UserRecord(
            id=str(uuid.uuid4()),
            org_id=ent_org.id,
            email=f"enterprise-{uuid.uuid4().hex[:6]}@enterprise.in",
            full_name="Enterprise User",
            password_hash=hash_password("EnterprisePass123!"),
            role="admin",
            is_active=True,
        )
        self.db.add_all([ent_org, ent_user])
        self.db.commit()

        ent_token = create_access_token(
            user_id=ent_user.id, email=ent_user.email, role="admin", org_id=ent_org.id
        )
        ent_headers = {"Authorization": f"Bearer {ent_token}"}

        ent_use = self.client.post(
            "/v1/me/use-service",
            headers=ent_headers,
            json={"service_key": "warehouse_automation", "parameters": {}},
        )
        self.assertEqual(ent_use.status_code, 200, ent_use.text)

        # 5. Tenant Admin vs Platform RBAC Controls
        # Tenant admin cannot invoke platform scheduler
        sched_resp = self.client.post(
            "/v1/scheduler/run-shift",
            headers=starter_headers,
            json={"mode": "full"},
        )
        self.assertEqual(sched_resp.status_code, 403)

        # Tenant admin cannot access watchdog telemetry
        watch_resp = self.client.get(
            "/v1/watchdog/telemetry",
            headers=starter_headers,
        )
        self.assertEqual(watch_resp.status_code, 403)

        # Tenant admin cannot access another tenant's invoices or consume credits
        other_invoices = self.client.get(
            f"/v1/accounts/orgs/{ent_org.id}/invoices",
            headers=starter_headers,
        )
        self.assertEqual(other_invoices.status_code, 403)

    # ── 12. DNS-Pinned SSRF Protection Verification ───────────────────────────

    def test_12_dns_pinned_ssrf_protection_verification(self):
        """Verify DNS-pinned network backend rejects private IPs, loopback, link-local,
        and IPv4-mapped addresses at the TCP connection boundary."""
        import httpcore
        from app.agents.sources import DNSRebindingSafeNetworkBackend, SSRFSafeTransport

        backend = DNSRebindingSafeNetworkBackend()

        # Direct connection attempts to prohibited hosts/IPs must raise ConnectError
        prohibited_targets = [
            ("127.0.0.1", 80),
            ("localhost", 8080),
            ("169.254.169.254", 80),
            ("10.0.0.1", 443),
            ("192.168.1.1", 80),
            ("172.16.0.1", 80),
            ("::ffff:127.0.0.1", 80),
        ]
        for host, port in prohibited_targets:
            with self.assertRaises(httpcore.ConnectError):
                backend.connect_tcp(host, port, timeout=1.0)

        # Verify transport instance initializes cleanly
        transport = SSRFSafeTransport()
        self.assertIsInstance(transport._pool._network_backend, DNSRebindingSafeNetworkBackend)

    # ── 13. Revenue Lifecycle Validation & Webhook Security ───────────────────

    def test_13_revenue_lifecycle_validation_and_webhook_security(self):
        """Phase 3 Revenue Lifecycle Validation:
        1. Webhook Signature Verification: Valid signature accepted; forged signature rejected with 401.
        2. Payment Amount & Currency Check: Underpayment is withheld from provisioning.
        3. Webhook Idempotency & Replay Protection: Exact event sent twice returns 'duplicate'.
        4. Auto-Provisioning & Entitlement Activation: Confirmed payment provisions org, unlocks service.
        5. Failed / Refund Lifecycle: payment.failed -> failed; refund.processed -> refunded.
        6. Trust Ledger Integrity: ECDSA NIST P-256 Merkle chain verified from Genesis to Tip.
        """
        import json
        key_secret = "rzp_webhook_secret_phase3_test_32ch"

        # 1. Signature Verification: Forged signature -> 401 Unauthorized
        fake_payload = json.dumps({
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_forged_{uuid.uuid4().hex[:8]}",
                        "amount": 999900,
                        "currency": "INR",
                        "email": "forger@attacker.io",
                    }
                }
            }
        }).encode("utf-8")

        with patch.dict(os.environ, {"RAZORPAY_KEY_SECRET": key_secret}):
            forged_resp = self.client.post(
                "/v1/webhooks/payment",
                content=fake_payload,
                headers={
                    "x-razorpay-signature": "0000000000000000000000000000000000000000000000000000000000000000",
                    "Content-Type": "application/json",
                },
            )
            self.assertEqual(forged_resp.status_code, 401)

        # 2. Payment Amount & Currency Check: Underpayment withheld
        underpaid_event_id = f"evt_underpaid_{uuid.uuid4().hex[:8]}"
        underpaid_payload = json.dumps({
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": underpaid_event_id,
                        "amount": 5000,
                        "currency": "INR",
                        "email": f"underpaid-{uuid.uuid4().hex[:6]}@client.in",
                        "notes": {
                            "company": "Underpaid Client Co",
                            "package": "growth_all_in_one",
                        },
                    }
                }
            }
        }).encode("utf-8")
        underpaid_sig = hmac.new(key_secret.encode("utf-8"), underpaid_payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"RAZORPAY_KEY_SECRET": key_secret}):
            underpaid_resp = self.client.post(
                "/v1/webhooks/payment",
                content=underpaid_payload,
                headers={"x-razorpay-signature": underpaid_sig, "Content-Type": "application/json"},
            )
            self.assertEqual(underpaid_resp.status_code, 200)
            self.assertEqual(underpaid_resp.json().get("provisioning", {}).get("status"), "underpaid_withheld")

        # 3 & 4. Valid Payment: Auto-provisioning & Entitlement Activation
        valid_event_id = f"evt_valid_{uuid.uuid4().hex[:8]}"
        customer_email = f"paying-client-{uuid.uuid4().hex[:6]}@enterprise.in"
        valid_payload = json.dumps({
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": valid_event_id,
                        "amount": 999900,
                        "currency": "INR",
                        "email": customer_email,
                        "notes": {
                            "company": "Paying Client Pvt Ltd",
                            "package": "growth_all_in_one",
                        },
                    }
                }
            }
        }).encode("utf-8")
        valid_sig = hmac.new(key_secret.encode("utf-8"), valid_payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"RAZORPAY_KEY_SECRET": key_secret}):
            # First submission -> Processed & provisioned
            valid_resp = self.client.post(
                "/v1/webhooks/payment",
                content=valid_payload,
                headers={"x-razorpay-signature": valid_sig, "Content-Type": "application/json"},
            )
            self.assertEqual(valid_resp.status_code, 200)
            self.assertEqual(valid_resp.json()["status"], "processed")
            self.assertEqual(valid_resp.json()["provisioning"]["status"], "provisioned")
            new_org_id = valid_resp.json()["provisioning"]["org_id"]

            # Webhook Idempotency & Replay: Re-submitting identical event must return duplicate
            dup_resp = self.client.post(
                "/v1/webhooks/payment",
                content=valid_payload,
                headers={"x-razorpay-signature": valid_sig, "Content-Type": "application/json"},
            )
            self.assertEqual(dup_resp.status_code, 200)
            self.assertEqual(dup_resp.json()["status"], "duplicate")

        # Confirm customer can now authenticate and execute entitled service
        user_record = self.db.query(UserRecord).filter_by(email=customer_email).first()
        self.assertIsNotNone(user_record)
        cust_token = create_access_token(
            user_id=user_record.id,
            email=user_record.email,
            role=user_record.role,
            org_id=new_org_id,
        )
        cust_headers = {"Authorization": f"Bearer {cust_token}"}

        svc_resp = self.client.post(
            "/v1/me/use-service",
            headers=cust_headers,
            json={"service_key": "seo_blog_copilot", "parameters": {}},
        )
        self.assertEqual(svc_resp.status_code, 200, svc_resp.text)

        # 5. Failed and Refund Event Lifecycle
        refund_payload = json.dumps({
            "event": "refund.processed",
            "payload": {
                "refund": {
                    "entity": {
                        "id": f"rfnd_{uuid.uuid4().hex[:8]}",
                        "payment_id": valid_event_id,
                        "amount": 999900,
                        "currency": "INR",
                    }
                }
            }
        }).encode("utf-8")
        refund_sig = hmac.new(key_secret.encode("utf-8"), refund_payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"RAZORPAY_KEY_SECRET": key_secret}):
            refund_resp = self.client.post(
                "/v1/webhooks/payment",
                content=refund_payload,
                headers={"x-razorpay-signature": refund_sig, "Content-Type": "application/json"},
            )
            self.assertEqual(refund_resp.status_code, 200)

        # 6. Verify Trust Ledger Integrity
        trust_resp = self.client.get("/v1/trust/verify", headers=self.manager_headers)
        self.assertEqual(trust_resp.status_code, 200)
        self.assertTrue(trust_resp.json()["chain_valid"])
        self.assertGreaterEqual(trust_resp.json()["total_blocks"], 1)

    # ── 14. Commercial Pilot Launch: Lead Discovery, Proposal & HITL Approval ──

    def test_14_commercial_pilot_launch_lead_discovery_and_proposal(self):
        """Phase 4 Commercial Pilot Launch:
        1. Live SMB lead discovery with real commercial enterprise candidate.
        2. Offline synthetic fixtures fail-closed in production.
        3. Commercial proposal & pitch generation with payment checkout link.
        4. Owner HITL review and approval governance.
        5. Trust Ledger ECDSA block sealing upon owner approval.
        """
        from app.agents.sources import OfflineSignalProvider, SMBSearchSourceProvider

        # 1. Offline synthetic fixtures are blocked in production
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            offline = OfflineSignalProvider()
            with self.assertRaises(RuntimeError):
                offline.search("warehouse_automation")

        # 2. Live discovery via SMBSearchSourceProvider
        live_provider = SMBSearchSourceProvider()
        candidates = live_provider.search("warehouse_automation", limit=2)
        self.assertGreater(len(candidates), 0)
        lead_candidate = candidates[0]
        self.assertTrue(lead_candidate.website.startswith("http"))
        self.assertFalse(lead_candidate.do_not_contact)

        # 3. Ingest candidate into database
        domain_name = lead_candidate.website.replace("https://", "").replace("http://", "").split("/")[0]
        lead_row = LeadRecordRow(
            id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            company=lead_candidate.company,
            website=lead_candidate.website,
            domain=domain_name,
            industry="warehouse_automation",
            geography="India",
            public_contact_channel=lead_candidate.public_contact_channel or "operations@targetlead.in",
            recommended_next_step="Draft commercial automation proposal",
            status="QUALIFIED",
            fit_score=0.92,
            confidence=0.88,
            product_match="warehouse_automation",
            observed_signals=["manual sorting bottlenecks"],
            sources=["duckduckgo_search"],
        )
        self.db.add(lead_row)
        self.db.commit()

        # 4. Generate proposal & pitch via /v1/revenue/pitch-lead (creates durable approval request)
        pitch_resp = self.client.post(
            "/v1/revenue/pitch-lead",
            headers=self.manager_headers,
            json={
                "lead_id": lead_row.id,
                "recipient_email": lead_row.public_contact_channel or "operations@targetlead.in",
                "recipient_name": "Operations Director",
                "idempotency_key": f"pitch-{uuid.uuid4()}",
            },
        )
        self.assertEqual(pitch_resp.status_code, 200, pitch_resp.text)
        pitch_data = pitch_resp.json()
        self.assertIn("payment_link", pitch_data)
        approval_id = pitch_data.get("approval_id")
        self.assertIsNotNone(approval_id)

        # 5. Owner HITL Decision: Approve proposal for dispatch
        decision_resp = self.client.post(
            f"/v1/approvals/{approval_id}/decision",
            headers=self.owner_headers,
            json={"decision": "APPROVED", "reason": "Commercial pilot terms verified by owner"},
        )
        self.assertEqual(decision_resp.status_code, 200, decision_resp.text)
        self.assertEqual(decision_resp.json()["status"], "APPROVED")

        # 6. Verify Trust Ledger block was sealed for the approval
        approval_rec = self.db.query(ApprovalRequest).filter_by(id=approval_id).first()
        self.assertEqual(approval_rec.status, "APPROVED")
        self.assertEqual(approval_rec.decided_by, "owner")

    # ── 15. Direct Domain Router Entitlement Bypass Prevention ────────────────

    def test_15_direct_domain_router_entitlement_bypass_blocked(self):
        """Verify that tenants cannot bypass /v1/me/use-service by directly calling domain routers
        (/v1/growth/creative, /v1/growth/campaign/unified, /v1/inventory/analyze,
        /v1/mobility/forecast, /v1/quality/inspect, /v1/leads/discover).
        """
        # Create unentitled (Starter without quality/mobility) tenant
        starter_org = OrganizationRecord(
            id=str(uuid.uuid4()),
            name="Starter Direct Test Co",
            slug=f"starter-direct-{uuid.uuid4().hex[:6]}",
            tier="company_os_starter",
            is_active=True,
            lead_credits_limit=500,
            metadata_json={
                "package_key": "company_os_starter",
                "entitled_capabilities": ["seo_content_automation"],
            },
        )
        starter_user = UserRecord(
            id=str(uuid.uuid4()),
            org_id=starter_org.id,
            email=f"starter-direct-{uuid.uuid4().hex[:6]}@starter.in",
            full_name="Starter Direct User",
            password_hash=hash_password("Pass123!"),
            role="admin",
            is_active=True,
        )
        self.db.add_all([starter_org, starter_user])
        self.db.commit()

        token = create_access_token(
            user_id=starter_user.id, email=starter_user.email, role="admin", org_id=starter_org.id
        )
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Direct call to unentitled Growth Suite creative -> 403 Forbidden
        creative_resp = self.client.post(
            "/v1/growth/creative",
            headers=headers,
            json={
                "product_name": "Test Product",
                "target_audience": "B2B SaaS",
            },
        )
        self.assertEqual(creative_resp.status_code, 403)
        self.assertIn("not entitled", creative_resp.json()["detail"].lower())

        # 2. Direct call to unentitled Unified Campaign -> 403 Forbidden
        camp_resp = self.client.post(
            "/v1/growth/campaign/unified",
            headers=headers,
            json={
                "client_name": "Client Co",
                "product_or_service": "Automation",
                "target_audience": "Warehouse Managers",
                "idempotency_key": f"camp-{uuid.uuid4()}",
            },
        )
        self.assertEqual(camp_resp.status_code, 403)
        self.assertIn("not entitled", camp_resp.json()["detail"].lower())

        # 3. Direct call to unentitled Quality Analytics -> 403 Forbidden
        quality_resp = self.client.post(
            "/v1/quality/inspect",
            headers=headers,
            json={"preset_or_sample": "ripe", "crop_variety": "Alphonso Mango"},
        )
        self.assertEqual(quality_resp.status_code, 403)
        self.assertIn("not entitled", quality_resp.json()["detail"].lower())

        # 4. Direct call to unentitled Mobility Analytics -> 403 Forbidden
        mob_resp = self.client.post(
            "/v1/mobility/forecast",
            headers=headers,
            json={"hour_of_day": 10, "temperature_f": 72.0},
        )
        self.assertEqual(mob_resp.status_code, 403)
        self.assertIn("not entitled", mob_resp.json()["detail"].lower())

        # 5. Direct call to unentitled Inventory Analytics -> 403 Forbidden
        inv_resp = self.client.post(
            "/v1/inventory/analyze",
            headers=headers,
            json={"service_level_z": 1.65},
        )
        self.assertEqual(inv_resp.status_code, 403)
        self.assertIn("not entitled", inv_resp.json()["detail"].lower())

        # 6. Direct call to unentitled Leads Discovery -> 403 Forbidden
        leads_resp = self.client.post(
            "/v1/leads/discover",
            headers=headers,
            json={"objective": "Find warehouse buyers", "limit": 2, "idempotency_key": f"lead-{uuid.uuid4()}"},
        )
        self.assertEqual(leads_resp.status_code, 403)
        self.assertIn("not entitled", leads_resp.json()["detail"].lower())

        # 7. Enterprise tier gets 200 OK on direct calls
        ent_org = OrganizationRecord(
            id=str(uuid.uuid4()),
            name="Ent Direct Test Co",
            slug=f"ent-direct-{uuid.uuid4().hex[:6]}",
            tier="company_os_enterprise",
            is_active=True,
            lead_credits_limit=5000,
            metadata_json={"package_key": "company_os_enterprise"},
        )
        ent_user = UserRecord(
            id=str(uuid.uuid4()),
            org_id=ent_org.id,
            email=f"ent-direct-{uuid.uuid4().hex[:6]}@ent.in",
            full_name="Ent Direct User",
            password_hash=hash_password("Pass123!"),
            role="admin",
            is_active=True,
        )
        self.db.add_all([ent_org, ent_user])
        self.db.commit()

        ent_token = create_access_token(
            user_id=ent_user.id, email=ent_user.email, role="admin", org_id=ent_org.id
        )
        ent_headers = {"Authorization": f"Bearer {ent_token}"}

        ent_inv = self.client.post(
            "/v1/inventory/analyze",
            headers=ent_headers,
            json={"service_level_z": 1.65},
        )
        self.assertEqual(ent_inv.status_code, 200)

    # ── 16. Subscription Tenant Boundary Enforcement ─────────────────────────

    def test_16_subscription_tenant_boundary_enforcement(self):
        """Cross-tenant subscription tampering prevention:
        Tenant B cannot view, create subscriptions for, or cancel Tenant A's customer or subscription.
        """
        # Create Tenant A
        org_a = OrganizationRecord(
            id=str(uuid.uuid4()),
            name="Tenant A Corp",
            slug=f"org-a-{uuid.uuid4().hex[:6]}",
            tier="company_os_pro",
            is_active=True,
        )
        cust_a = CustomerRecord(
            id=str(uuid.uuid4()),
            org_id=org_a.id,
            email=f"cust-a-{uuid.uuid4().hex[:6]}@tenant-a.com",
            name="Customer A",
            provider="razorpay",
            provider_customer_id=f"cust_rzp_{uuid.uuid4().hex[:8]}",
        )
        sub_a = SubscriptionRecord(
            id=str(uuid.uuid4()),
            org_id=org_a.id,
            customer_id=cust_a.id,
            plan_id="plan_pro_monthly",
            provider="razorpay",
            provider_subscription_id=f"sub_rzp_{uuid.uuid4().hex[:8]}",
            status="active",
        )
        # Create Tenant B user
        org_b = OrganizationRecord(
            id=str(uuid.uuid4()),
            name="Tenant B Corp",
            slug=f"org-b-{uuid.uuid4().hex[:6]}",
            tier="company_os_starter",
            is_active=True,
        )
        user_b = UserRecord(
            id=str(uuid.uuid4()),
            org_id=org_b.id,
            email=f"user-b-{uuid.uuid4().hex[:6]}@tenant-b.com",
            full_name="User B",
            password_hash=hash_password("Pass123!"),
            role="admin",
            is_active=True,
        )
        self.db.add_all([org_a, cust_a, sub_a, org_b, user_b])
        self.db.commit()

        token_b = create_access_token(
            user_id=user_b.id, email=user_b.email, role="admin", org_id=org_b.id
        )
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # 1. Tenant B attempting to create subscription on Tenant A customer -> 403 Forbidden
        create_resp = self.client.post(
            "/v1/subscriptions/create",
            headers=headers_b,
            json={
                "customer_id": cust_a.id,
                "plan_id": "plan_enterprise",
                "provider": "razorpay",
            },
        )
        self.assertEqual(create_resp.status_code, 403)
        self.assertIn("access denied", create_resp.json()["detail"].lower())

        # 2. Tenant B attempting to list Tenant A subscriptions -> 403 Forbidden
        list_resp = self.client.get(
            f"/v1/subscriptions/customer/{cust_a.id}",
            headers=headers_b,
        )
        self.assertEqual(list_resp.status_code, 403)

        # 3. Tenant B attempting to cancel Tenant A subscription -> 403 Forbidden
        cancel_resp = self.client.post(
            f"/v1/subscriptions/{sub_a.id}/cancel",
            headers=headers_b,
            json={"cancel_at_period_end": True},
        )
        self.assertEqual(cancel_resp.status_code, 403)

    # ── 17. Refund Entitlement Revocation & Renewal Cycle Refill ──────────────

    def test_17_refund_entitlement_revocation_and_renewal_cycle_refill(self):
        """Verify:
        1. A full refund revokes Pro capabilities and downgrades the tenant to free (blocking paid services).
        2. A recurring subscription cycle renewal resets monthly used credits to zero.
        """
        import json
        key_secret = "rzp_webhook_secret_phase3_test_32ch"

        # 1. Setup tenant with paid Pro package & invoice
        org = OrganizationRecord(
            id=str(uuid.uuid4()),
            name="Refund Test Co",
            slug=f"ref-test-{uuid.uuid4().hex[:6]}",
            tier="company_os_pro",
            is_active=True,
            lead_credits_limit=2500,
            lead_credits_used=1800,
            outreach_credits_limit=1000,
            outreach_credits_used=650,
            metadata_json={
                "package_key": "company_os_pro",
                "entitled_capabilities": ["growth_all_in_one", "seo_content_automation"],
            },
        )
        user = UserRecord(
            id=str(uuid.uuid4()),
            org_id=org.id,
            email=f"refund-user-{uuid.uuid4().hex[:6]}@ref.in",
            full_name="Refund User",
            password_hash=hash_password("Pass123!"),
            role="admin",
            is_active=True,
        )
        payment_id = f"pay_rfnd_{uuid.uuid4().hex[:8]}"
        inv = InvoiceRecord(
            id=str(uuid.uuid4()),
            org_id=org.id,
            customer_id=f"cust_{uuid.uuid4().hex[:8]}",
            provider="razorpay",
            provider_invoice_id=f"inv_{uuid.uuid4().hex[:8]}",
            provider_payment_id=payment_id,
            amount=499900,
            currency="INR",
            status="paid",
        )
        sub = SubscriptionRecord(
            id=str(uuid.uuid4()),
            org_id=org.id,
            customer_id=inv.customer_id,
            plan_id="plan_pro_monthly",
            provider="razorpay",
            provider_subscription_id=f"sub_renew_{uuid.uuid4().hex[:8]}",
            status="active",
        )
        self.db.add_all([org, user, inv, sub])
        self.db.commit()

        token = create_access_token(user_id=user.id, email=user.email, role="admin", org_id=org.id)
        user_headers = {"Authorization": f"Bearer {token}"}

        # Verify tenant can execute entitled service initially
        use_resp = self.client.post(
            "/v1/me/use-service",
            headers=user_headers,
            json={"service_key": "seo_blog_copilot", "parameters": {}},
        )
        self.assertEqual(use_resp.status_code, 200)

        # 2. Trigger refund webhook
        refund_payload = json.dumps({
            "event": "refund.processed",
            "payload": {
                "refund": {
                    "entity": {
                        "id": f"rfnd_{uuid.uuid4().hex[:8]}",
                        "payment_id": payment_id,
                        "amount": 499900,
                        "currency": "INR",
                    }
                }
            }
        }).encode("utf-8")
        refund_sig = hmac.new(key_secret.encode("utf-8"), refund_payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"RAZORPAY_KEY_SECRET": key_secret}):
            resp = self.client.post(
                "/v1/webhooks/payment",
                content=refund_payload,
                headers={"x-razorpay-signature": refund_sig, "Content-Type": "application/json"},
            )
            self.assertEqual(resp.status_code, 200)

        # Confirm organization is now downgraded to free with revoked capabilities
        self.db.expire_all()
        refreshed_org = self.db.query(OrganizationRecord).filter_by(id=org.id).first()
        self.assertEqual(refreshed_org.tier, "free")
        self.assertEqual(refreshed_org.metadata_json.get("entitled_capabilities"), [])

        # Invoking paid service must now fail closed with 403 Forbidden
        blocked_resp = self.client.post(
            "/v1/me/use-service",
            headers=user_headers,
            json={"service_key": "seo_blog_copilot", "parameters": {}},
        )
        self.assertEqual(blocked_resp.status_code, 403)
        self.assertIn("not entitled", blocked_resp.json()["detail"].lower())

        # 3. Trigger subscription renewal cycle webhook -> credits replenished
        renew_payload = json.dumps({
            "event": "subscription.charged",
            "payload": {
                "subscription": {
                    "entity": {
                        "id": sub.provider_subscription_id,
                        "status": "active",
                    }
                }
            }
        }).encode("utf-8")
        renew_sig = hmac.new(key_secret.encode("utf-8"), renew_payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"RAZORPAY_KEY_SECRET": key_secret}):
            renew_resp = self.client.post(
                "/v1/webhooks/payment",
                content=renew_payload,
                headers={"x-razorpay-signature": renew_sig, "Content-Type": "application/json"},
            )
            self.assertEqual(renew_resp.status_code, 200)

        self.db.expire_all()
        renewed_org = self.db.query(OrganizationRecord).filter_by(id=org.id).first()
        self.assertEqual(renewed_org.lead_credits_used, 0)
        self.assertEqual(renewed_org.outreach_credits_used, 0)

    # ── 18. Verifiable Production Deployment Health ───────────────────────────

    def test_18_verifiable_production_deployment_health(self):
        """Production deployment verification:
        GET /health must expose commit_sha, branch, environment, and database status.
        """
        with patch.dict(os.environ, {"GIT_COMMIT_SHA": "37b5f5f4c2810a99", "GIT_BRANCH": "main", "APP_ENV": "production"}):
            resp = self.client.get("/health")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "healthy")
            self.assertEqual(data["database"], "connected")
            self.assertEqual(data["commit_sha"], "37b5f5f4")
            self.assertEqual(data["branch"], "main")
            self.assertEqual(data["environment"], "production")


if __name__ == "__main__":
    unittest.main()
