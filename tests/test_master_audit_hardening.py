"""Master Audit Hardening & End-to-End Revenue Loop Verification Suite.

Validates all P0, P1, P2, and P3 remediations implemented during the production readiness audit:
1. Strict multi-tenant isolation across accounts, invoices, credits, leads, revenue pitches, and subscriptions.
2. Privilege escalation prevention on user creation and unauthenticated access blocking on webhooks/watchdog.
3. SSRF protection against localhost, loopback, link-local (169.254.169.254), and RFC1918 private networks.
4. Webhook signature enforcement on /v1/orders/ingest, replay protection on AFW DirectPay, and production HITL gating for unconfirmed Web3 hashes.
5. Zero plaintext password storage in UserRecord.metadata_json and existing-user plan upgrade on payment capture.
6. Customer Portal execution for all catalog services (/v1/me/use-service).
7. Public SEO/AEO/GEO endpoints (/robots.txt, /sitemap.xml, /llms.txt, /legal/declaration?format=text, and Schema.org JSON-LD).
8. Complete end-to-end Customer-to-Revenue lifecycle demonstration.
"""

from __future__ import annotations

import os
import unittest
import uuid

from fastapi.testclient import TestClient

from app.agents.sources import fetch_and_enrich_website, is_safe_public_url
from app.db.database import Base, SessionLocal, engine, get_db
from app.db.models import (
    InvoiceRecord,
    LeadRecordRow,
    OrganizationRecord,
    UserRecord,
)
from app.main import app
from app.security.auth import create_access_token
from app.security.trust_chain import verify_chain_integrity
from app.services.payment import PaymentProvider, WebhookEvent
from app.services.provisioning import auto_provision_tenant_on_payment
from app.services.sovereign_pay import create_sovereign_pay_session


class MasterAuditHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.manager_key = "test-manager-key-master-audit-32chars!!"
        cls.owner_key = "test-owner-key-master-audit-32chars!!!!"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        os.environ["OWNER_API_KEY"] = cls.owner_key
        cls.client = TestClient(app)
        cls.manager_headers = {"X-API-Key": cls.manager_key}
        cls.owner_headers = {"X-API-Key": cls.owner_key}

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

    def test_01_multi_tenant_isolation_and_privilege_escalation_blocked(self):
        """Verify Tenant A admin cannot read/mutate Tenant B invoices, credits, leads, or escalate to owner."""
        org_a = OrganizationRecord(
            id=f"org-a-{uuid.uuid4().hex[:8]}",
            name="Tenant Alpha",
            slug=f"tenant-alpha-{uuid.uuid4().hex[:6]}",
            tier="starter",
            lead_credits_limit=50,
            outreach_credits_limit=25,
            is_active=True,
        )
        org_b = OrganizationRecord(
            id=f"org-b-{uuid.uuid4().hex[:8]}",
            name="Tenant Beta",
            slug=f"tenant-beta-{uuid.uuid4().hex[:6]}",
            tier="pro",
            lead_credits_limit=200,
            outreach_credits_limit=100,
            is_active=True,
        )
        lead_b = LeadRecordRow(
            id=str(uuid.uuid4()),
            org_id=org_b.id,
            domain="betacorp.in",
            task_id=str(uuid.uuid4()),
            company="Beta Corp India",
            website="https://betacorp.in",
            industry="SaaS",
            geography="India",
            observed_signals=["enterprise automation"],
            sources=[{"source": "test"}],
            product_match="company_os_pro",
            fit_score=0.92,
            confidence=0.90,
            public_contact_channel="ops@betacorp.in",
            recommended_next_step="outreach_review",
            do_not_contact=False,
            status="DISCOVERED",
        )
        self.db.add_all([org_a, org_b, lead_b])
        self.db.commit()

        token_a = create_access_token(
            user_id=f"user-a-{uuid.uuid4().hex[:6]}",
            email="admin@tenantalpha.in",
            role="admin",
            org_id=org_a.id,
        )
        headers_a = {"Authorization": f"Bearer {token_a}"}

        # 1. Tenant A listing orgs only sees Tenant A
        orgs_resp = self.client.get("/v1/accounts/orgs", headers=headers_a)
        self.assertEqual(orgs_resp.status_code, 200)
        org_ids = [o["id"] for o in orgs_resp.json()]
        self.assertEqual(org_ids, [org_a.id])

        # 2. Tenant A cannot list or create invoices or consume credits for Tenant B
        self.assertEqual(
            self.client.get(f"/v1/accounts/orgs/{org_b.id}/invoices", headers=headers_a).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/v1/accounts/orgs/{org_b.id}/consume-credits",
                headers=headers_a,
                json={"credit_type": "lead", "amount": 5},
            ).status_code,
            403,
        )

        # 3. Tenant A cannot assign 'owner' or 'manager' role to a new user in their org
        esc_resp = self.client.post(
            f"/v1/accounts/orgs/{org_a.id}/users",
            headers=headers_a,
            json={"email": "hacker@tenantalpha.in", "full_name": "Escalation User", "role": "owner"},
        )
        self.assertEqual(esc_resp.status_code, 403)

        # 4. Tenant A cannot GET, PATCH, DELETE, or PITCH Tenant B's lead
        self.assertEqual(self.client.get(f"/v1/leads/{lead_b.id}", headers=headers_a).status_code, 403)
        self.assertEqual(
            self.client.patch(
                f"/v1/leads/{lead_b.id}",
                headers=headers_a,
                json={"status": "QUALIFIED"},
            ).status_code,
            403,
        )
        self.assertEqual(self.client.delete(f"/v1/leads/{lead_b.id}", headers=headers_a).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/v1/revenue/pitch-lead",
                headers=headers_a,
                json={
                    "lead_id": lead_b.id,
                    "recipient_email": "ops@betacorp.in",
                    "idempotency_key": f"pitch-{uuid.uuid4()}",
                },
            ).status_code,
            403,
        )

        # 5. Unauthenticated requests to /v1/webhooks/events and /v1/watchdog/telemetry are rejected
        self.assertEqual(self.client.get("/v1/webhooks/events").status_code, 401)
        self.assertEqual(self.client.get("/v1/watchdog/telemetry").status_code, 401)

    def test_02_ssrf_protection_blocks_internal_and_metadata_urls(self):
        """Verify SSRF protection blocks localhost, loopback, 169.254.169.254, and private RFC1918 IPs."""
        unsafe_urls = [
            "http://127.0.0.1:8000/v1/project/status",
            "http://localhost:5432",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.15/internal",
            "http://192.168.1.1/admin",
            "http://172.16.0.5/secret",
        ]
        for url in unsafe_urls:
            self.assertFalse(is_safe_public_url(url), f"Expected SSRF block for {url}")
            enrich_res = fetch_and_enrich_website(url)
            self.assertTrue(enrich_res.get("blocked_ssrf"), f"Expected blocked_ssrf for {url}")

        self.assertTrue(is_safe_public_url("https://sahyadrifarms.com"))

        # API endpoint rejection
        resp_enrich = self.client.post(
            "/v1/leads/enrich",
            headers=self.manager_headers,
            json={"website": "http://169.254.169.254/latest/meta-data/"},
        )
        self.assertEqual(resp_enrich.status_code, 422)

        resp_scan = self.client.post(
            "/v1/previews/scan",
            json={"url": "http://127.0.0.1:8000/admin"},
        )
        self.assertEqual(resp_scan.status_code, 400)

    def test_03_order_signature_and_sovereign_pay_replay_and_prod_gating(self):
        """Verify /v1/orders/ingest requires signature in production, and AFW DirectPay blocks replay & unconfirmed prod Web3 hashes."""
        old_secret = os.environ.get("ASK4_WEBHOOK_SECRET")
        old_env = os.environ.get("APP_ENV")
        try:
            os.environ["APP_ENV"] = "production"
            os.environ["ASK4_WEBHOOK_SECRET"] = "super-secret-ask4-hmac-key-32chars"
            # Missing signature header in production must fail with 401
            order_resp = self.client.post(
                "/v1/orders/ingest",
                json={
                    "transaction_id": f"TX-{uuid.uuid4().hex[:8]}",
                    "amount": 499.0,
                    "currency": "INR",
                    "customer_email": "student@university.edu",
                    "idempotency_key": f"idem-{uuid.uuid4()}",
                },
            )
            self.assertEqual(order_resp.status_code, 401)
        finally:
            if old_secret is not None:
                os.environ["ASK4_WEBHOOK_SECRET"] = old_secret
            else:
                os.environ.pop("ASK4_WEBHOOK_SECRET", None)
            if old_env is not None:
                os.environ["APP_ENV"] = old_env
            else:
                os.environ.pop("APP_ENV", None)

        # Replay protection across two sessions
        sess1 = create_sovereign_pay_session(
            package_key="seo_blog_copilot",
            company_name="Replay Test 1",
            customer_email=f"r1-{uuid.uuid4().hex[:6]}@sahyadrifarms.com",
            currency="INR",
            db=self.db,
        )
        sess2 = create_sovereign_pay_session(
            package_key="seo_blog_copilot",
            company_name="Replay Test 2",
            customer_email=f"r2-{uuid.uuid4().hex[:6]}@sahyadrifarms.com",
            currency="INR",
            db=self.db,
        )
        shared_utr = f"99{uuid.uuid4().int % 10**10:010d}"
        r1 = self.client.post(
            f"/v1/pay/{sess1.session_id}/verify",
            json={"rail": "upi_direct", "proof_reference": shared_utr},
        )
        self.assertEqual(r1.status_code, 200)

        # Replaying the exact same UTR on sess2 must be rejected with 400
        r2 = self.client.post(
            f"/v1/pay/{sess2.session_id}/verify",
            json={"rail": "upi_direct", "proof_reference": shared_utr},
        )
        self.assertEqual(r2.status_code, 400)
        self.assertIn("Duplicate payment proof", r2.json()["detail"])

        # Production gating for unconfirmed Web3 tx hash
        old_env = os.environ.get("APP_ENV")
        old_rpc = os.environ.get("WEB3_RPC_URL")
        try:
            os.environ["APP_ENV"] = "production"
            os.environ["WEB3_RPC_URL"] = ""
            sess_prod = create_sovereign_pay_session(
                package_key="trust_engine",
                company_name="Prod Web3 Gate Co",
                customer_email=f"prodweb3-{uuid.uuid4().hex[:6]}@signzy.com",
                currency="USD",
                preferred_rail="web3_usdc",
                db=self.db,
            )
            tx_hash = "0x" + uuid.uuid4().hex + uuid.uuid4().hex
            r_prod = self.client.post(
                f"/v1/pay/{sess_prod.session_id}/verify",
                json={"rail": "web3_usdc", "proof_reference": tx_hash},
            )
            self.assertEqual(r_prod.status_code, 200)
            self.assertEqual(r_prod.json()["status"], "AWAITING_CONFIRMATION")
        finally:
            if old_env is not None:
                os.environ["APP_ENV"] = old_env
            else:
                os.environ.pop("APP_ENV", None)
            if old_rpc is not None:
                os.environ["WEB3_RPC_URL"] = old_rpc
            else:
                os.environ.pop("WEB3_RPC_URL", None)

    def test_04_provisioning_no_plaintext_password_and_upgrades_existing_signup(self):
        """Verify auto_provision_tenant_on_payment never stores plaintext password and upgrades existing signup users."""
        email = f"signup-upgrade-{uuid.uuid4().hex[:6]}@wareiq.com"
        reg_resp = self.client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": "SecurePassword123!",
                "full_name": "Rohan Sharma",
                "company_name": "WareIQ Supply Chain",
                "role": "admin",
            },
        )
        self.assertEqual(reg_resp.status_code, 201)
        org_id = reg_resp.json()["org_id"]

        # Initially on 'free' tier
        org_before = self.db.get(OrganizationRecord, org_id)
        self.assertEqual(org_before.tier, "free")

        # Now payment webhook arrives for company_os_pro
        event = WebhookEvent(
            id=f"evt_{uuid.uuid4().hex[:10]}",
            provider=PaymentProvider.RAZORPAY,
            event_type="payment.captured",
            raw_event_type="payment.captured",
            resource_type="payment",
            resource_id=f"pay_{uuid.uuid4().hex[:10]}",
            data={
                "payload": {
                    "payment": {
                        "entity": {
                            "email": email,
                            "amount": 1999900,
                            "currency": "INR",
                            "notes": {
                                "notes_company": "WareIQ Supply Chain",
                                "notes_package": "company_os_pro",
                            },
                        }
                    }
                }
            },
        )
        prov = auto_provision_tenant_on_payment(self.db, event)
        self.assertEqual(prov["status"], "already_provisioned")
        self.assertNotIn("temp_password", prov)

        self.db.refresh(org_before)
        self.assertEqual(org_before.tier, "pro")
        self.assertEqual(org_before.lead_credits_limit, 600)
        inv = self.db.query(InvoiceRecord).filter_by(org_id=org_id).first()
        self.assertIsNotNone(inv)
        self.assertEqual(inv.amount, 1999900)

    def test_05_seo_aeo_geo_and_legal_public_endpoints(self):
        """Verify /robots.txt, /sitemap.xml, /llms.txt, /legal/declaration?format=text, and dashboard JSON-LD."""
        robots = self.client.get("/robots.txt")
        self.assertEqual(robots.status_code, 200)
        self.assertIn("Sitemap: https://os.askforwrite.com/sitemap.xml", robots.text)
        self.assertIn("GPTBot", robots.text)

        sitemap = self.client.get("/sitemap.xml")
        self.assertEqual(sitemap.status_code, 200)
        self.assertIn("<urlset", sitemap.text)
        self.assertIn("https://os.askforwrite.com/llms.txt", sitemap.text)

        llms = self.client.get("/llms.txt")
        self.assertEqual(llms.status_code, 200)
        self.assertIn("UDYAM-RJ-14-0018404", llms.text)
        self.assertIn("seo_blog_copilot", llms.text)

        decl_txt = self.client.get("/legal/declaration?format=text")
        self.assertEqual(decl_txt.status_code, 200)
        self.assertIn("UDYAM-RJ-14-0018404", decl_txt.text)

        dash = self.client.get("/dashboard/")
        self.assertEqual(dash.status_code, 200)
        self.assertIn("application/ld+json", dash.text)
        self.assertIn("SoftwareApplication", dash.text)
        self.assertIn("FAQPage", dash.text)

    def test_06_complete_end_to_end_revenue_lifecycle(self):
        """Demonstrate complete lifecycle: Discovery -> Pitch -> Owner Approval -> Payment -> Provisioning -> Service Execution."""
        # Reset any global warehouse_automation leads from prior runs so shared DB stays clean
        for row in self.db.query(LeadRecordRow).filter(LeadRecordRow.org_id.is_(None)).all():
            if row.status == "CONTACTED":
                row.status = "DISCOVERED"
        self.db.commit()

        e2e_org = OrganizationRecord(
            id=f"org-e2e-{uuid.uuid4().hex[:8]}",
            name="E2E Pipeline Org",
            slug=f"e2e-org-{uuid.uuid4().hex[:6]}",
            tier="pro",
            lead_credits_limit=100,
            outreach_credits_limit=100,
            is_active=True,
        )
        self.db.add(e2e_org)
        self.db.commit()

        # 1. Discover SMB Leads scoped to e2e_org
        disc_resp = self.client.post(
            "/v1/leads/discover-smb",
            headers=self.manager_headers,
            json={"vertical": "warehouse_automation", "region": "India", "limit": 2, "org_id": e2e_org.id},
        )
        self.assertEqual(disc_resp.status_code, 200)
        leads = disc_resp.json()["leads"]
        self.assertGreaterEqual(len(leads), 1)
        lead_id = leads[0]["lead_id"]

        # 2. Pitch Lead (creates OutreachRecord + ApprovalRequest)
        buyer_email = f"buyer-{uuid.uuid4().hex[:6]}@emiza.in"
        pitch_resp = self.client.post(
            "/v1/revenue/pitch-lead",
            headers=self.manager_headers,
            json={
                "lead_id": lead_id,
                "org_id": e2e_org.id,
                "recipient_email": buyer_email,
                "recipient_name": "VP Supply Chain",
                "idempotency_key": f"e2e-pitch-{uuid.uuid4()}",
            },
        )
        self.assertEqual(pitch_resp.status_code, 200)
        pitch_data = pitch_resp.json()
        self.assertEqual(pitch_data["status"], "PENDING_APPROVAL")
        self.assertTrue(len(pitch_data["payment_link"]) > 10)

        # 3. Owner Approves & Dispatches Outreach via /v1/approvals/{approval_id}/decide
        approval_id = pitch_data["approval_id"]
        approve_outreach = self.client.post(
            f"/v1/approvals/{approval_id}/decide",
            headers=self.owner_headers,
            json={"decision": "APPROVED", "reason": "Verified warehouse fit"},
        )
        self.assertEqual(approve_outreach.status_code, 200)
        self.assertEqual(approve_outreach.json()["status"], "APPROVED")

        # 4. Buyer Initiates Checkout Session & Submits UPI Proof
        pay_sess = self.client.post(
            "/v1/pay/create-session",
            json={
                "package_key": "warehouse_automation",
                "company_name": "Emiza Supply Chain",
                "customer_email": buyer_email,
                "currency": "INR",
                "preferred_rail": "upi_direct",
            },
        )
        self.assertEqual(pay_sess.status_code, 200)
        session_id = pay_sess.json()["session_id"]

        utr = f"88{uuid.uuid4().int % 10**10:010d}"
        verify_resp = self.client.post(
            f"/v1/pay/{session_id}/verify",
            json={"rail": "upi_direct", "proof_reference": utr},
        )
        self.assertEqual(verify_resp.status_code, 200)
        self.assertEqual(verify_resp.json()["status"], "AWAITING_CONFIRMATION")

        # 5. Owner Confirms Payment -> Seals TrustBlock & Auto-Provisions Tenant Workspace + Invoice
        confirm_resp = self.client.post(
            f"/v1/pay/{session_id}/confirm-owner",
            headers=self.owner_headers,
        )
        self.assertEqual(confirm_resp.status_code, 200)
        prov = confirm_resp.json()["provisioning"]
        self.assertEqual(prov["status"], "provisioned")
        org_id = prov["org_id"]
        user_id = prov["user_id"]

        # Verify no plaintext temp_password stored in UserRecord.metadata_json
        user_rec = self.db.get(UserRecord, user_id)
        self.assertNotIn("temp_password", user_rec.metadata_json or {})

        # 6. Provisioned Customer Executes Entitled Services via Portal (/v1/me/use-service)
        customer_token = create_access_token(
            user_id=user_id,
            email=buyer_email,
            role="admin",
            org_id=org_id,
        )
        cust_headers = {"Authorization": f"Bearer {customer_token}"}

        for svc_key in ("warehouse_automation", "seo_blog_copilot", "trust_engine"):
            svc_resp = self.client.post(
                "/v1/me/use-service",
                headers=cust_headers,
                json={"service_key": svc_key, "payload": {}},
            )
            self.assertEqual(svc_resp.status_code, 200, f"Failed executing {svc_key}: {svc_resp.text}")
            self.assertEqual(svc_resp.json()["status"], "COMPLETED")

        # 7. Verify Cryptographic Trust Chain Integrity
        chain = verify_chain_integrity(self.db)
        self.assertTrue(chain["chain_valid"])
        self.assertEqual(len(chain["errors"]), 0)

    def test_07_erc20_transfer_log_decoding_and_validation(self):
        """Verify ERC-20 Transfer(from, to, value) log topic decoding for USDC/USDT contracts, recipient, and amount."""
        from app.services.sovereign_pay import (
            ERC20_TRANSFER_TOPIC0,
            decode_erc20_transfer_logs,
        )

        merchant_wallet = "0x365b009C15F75f05fb9094e9B3D122146E75ce97"
        sender_topic = "0x0000000000000000000000001111111111111111111111111111111111111111"
        recipient_clean = merchant_wallet.lower().replace("0x", "")
        recipient_topic = "0x" + ("0" * 24) + recipient_clean
        # $49.00 USD in 6-decimal USDC = 49_000_000 = 0x2ebec40
        amount_hex = hex(49_000_000)[2:].rjust(64, "0")
        valid_log = {
            "address": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",  # Polygon Native USDC
            "topics": [ERC20_TRANSFER_TOPIC0, sender_topic, recipient_topic],
            "data": "0x" + amount_hex,
        }

        decoded = decode_erc20_transfer_logs(
            logs=[valid_log],
            expected_recipient=merchant_wallet,
            expected_amount_usd=49.0,
        )
        self.assertEqual(decoded["token_symbol"], "USDC")
        self.assertEqual(decoded["network"], "Polygon")
        self.assertAlmostEqual(decoded["amount_usd"], 49.0)

        # Wrong token contract should raise ValueError
        bad_contract_log = {**valid_log, "address": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"}
        with self.assertRaises(ValueError):
            decode_erc20_transfer_logs([bad_contract_log], merchant_wallet, 49.0)

        # Wrong recipient wallet should raise ValueError
        wrong_recipient_topic = "0x0000000000000000000000002222222222222222222222222222222222222222"
        bad_recipient_log = {**valid_log, "topics": [ERC20_TRANSFER_TOPIC0, sender_topic, wrong_recipient_topic]}
        with self.assertRaises(ValueError):
            decode_erc20_transfer_logs([bad_recipient_log], merchant_wallet, 49.0)

        # Insufficient USD amount ($10 instead of $49) should raise ValueError
        low_amount_hex = hex(10_000_000)[2:].rjust(64, "0")
        low_amount_log = {**valid_log, "data": "0x" + low_amount_hex}
        with self.assertRaises(ValueError):
            decode_erc20_transfer_logs([low_amount_log], merchant_wallet, 49.0)

    def test_08_live_penny_test_and_bank_settlement_reconciliation(self):
        """Verify P2 live ₹1/$1 penny-test creation, payment fulfillment, and bank statement UTR reconciliation."""
        penny_email = f"penny-{uuid.uuid4().hex[:6]}@askforwrite.in"
        penny_resp = self.client.post(
            "/v1/pay/live-penny-test",
            headers=self.owner_headers,
            json={
                "rail": "upi_direct",
                "owner_email": penny_email,
            },
        )
        self.assertEqual(penny_resp.status_code, 200, penny_resp.text)
        penny_data = penny_resp.json()
        self.assertEqual(penny_data["status"], "PENNY_TEST_READY")
        self.assertEqual(penny_data["amount"], 1.0)
        invoice_id = penny_data["invoice_id"]

        # Reconcile InvoiceRecord against actual bank payout statement UTR
        bank_utr = f"SBIN26{uuid.uuid4().hex[:10].upper()}"
        reconcile_resp = self.client.post(
            "/v1/pay/reconcile-settlement",
            headers=self.owner_headers,
            json={
                "invoice_id": invoice_id,
                "bank_statement_utr": bank_utr,
                "settled_amount": 1.0,
                "settlement_date": "2026-10-29",
                "notes": "SBI Merchant Payout Batch #1029",
            },
        )
        self.assertEqual(reconcile_resp.status_code, 200, reconcile_resp.text)
        rec_data = reconcile_resp.json()
        self.assertEqual(rec_data["status"], "RECONCILED")
        self.assertTrue(len(rec_data["trust_block"]["block_hash"]) > 16)

        # Verify ledger endpoint lists the reconciled invoice
        ledger_resp = self.client.get("/v1/pay/reconciliation-ledger", headers=self.manager_headers)
        self.assertEqual(ledger_resp.status_code, 200)
        self.assertGreaterEqual(ledger_resp.json()["reconciled_count"], 1)

    def test_09_vertical_ssr_solutions_pages_and_ops_preflight(self):
        """Verify P3 indexable SSR vertical landing pages (/solutions/*), sitemap inclusion, and P0/P1 ops preflight."""
        hub = self.client.get("/solutions")
        self.assertEqual(hub.status_code, 200)
        self.assertIn("application/ld+json", hub.text)
        self.assertIn("ItemList", hub.text)

        for slug in ("warehouse-automation", "field-force", "produce-quality-ai"):
            page = self.client.get(f"/solutions/{slug}")
            self.assertEqual(page.status_code, 200, f"Failed GET /solutions/{slug}")
            self.assertIn(f'rel="canonical" href="https://os.askforwrite.com/solutions/{slug}"', page.text)
            self.assertIn("google-site-verification", page.text)
            self.assertIn("msvalidate.01", page.text)
            self.assertIn("BreadcrumbList", page.text)
            self.assertIn("FAQPage", page.text)

        sitemap = self.client.get("/sitemap.xml")
        self.assertIn("https://os.askforwrite.com/solutions/warehouse-automation", sitemap.text)
        self.assertIn("https://os.askforwrite.com/solutions/field-force", sitemap.text)
        self.assertIn("https://os.askforwrite.com/solutions/produce-quality-ai", sitemap.text)

        preflight = self.client.get("/v1/ops/preflight", headers=self.manager_headers)
        self.assertEqual(preflight.status_code, 200, preflight.text)
        pf_data = preflight.json()
        self.assertTrue(pf_data["database"]["healthy"])
        self.assertIn("/solutions/warehouse-automation", pf_data["vertical_solution_pages"])


if __name__ == "__main__":
    unittest.main()

