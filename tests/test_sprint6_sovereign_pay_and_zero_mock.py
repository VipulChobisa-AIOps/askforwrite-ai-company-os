"""Test Suite for Sprint 6:
1. US-6.1: Zero-Mock Live SMB Discovery & Live Website SEO/GEO Auditor (smb_search_source.py)
2. US-6.2: 2026 SEO + GEO + AI-SEO (AIO) + Local Geo + Social Media Expert (growth_engine.py & growth_suite.py)
3. US-6.3: Sovereign Zero-Fee Payment Gateway (AFW DirectPay - sovereign_pay.py & /v1/pay)
"""

from __future__ import annotations

import os
import unittest
import uuid

from fastapi.testclient import TestClient

from app.agents.smb_search_source import (
    CURATED_SMB_DIRECTORY,
    _search_duckduckgo_live,
    audit_live_website_seo_geo,
    discover_smb_leads,
    is_valid_commercial_domain,
)
from app.db.database import Base, SessionLocal, engine, get_db
from app.db.models import (
    ApprovalRequest,
    InvoiceRecord,
    OrganizationRecord,
    TrustBlock,
    UserRecord,
)
from app.main import app
from app.security.trust_chain import verify_chain_integrity
from app.services.catalog import build_payment_link
from app.services.growth_engine import (
    generate_and_stage_blog,
    generate_omnichannel_social_campaign,
)
from app.services.previews import generate_trojan_horse_preview
from app.services.shift_scheduler import run_autonomous_shift
from app.services.sovereign_pay import (
    create_sovereign_pay_session,
    generate_inline_qr_svg,
    get_sovereign_pay_session,
    verify_onchain_tx,
)


class Sprint6ZeroMockAndSovereignPayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.manager_key = "test-manager-key-sprint6-32characters"
        cls.owner_key = "test-owner-key-sprint6-32characters"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        os.environ["OWNER_API_KEY"] = cls.owner_key
        cls.client = TestClient(app)
        cls.headers = {
            "X-API-Key": cls.manager_key,
            "X-Correlation-ID": "test-sprint6-corr",
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

    # ── US-6.1: Zero-Mock SMB Discovery & Live SEO/GEO Auditor ───────────────

    def test_curated_smb_directory_zero_mock_all_verticals(self):
        """Verify CURATED_SMB_DIRECTORY has 0 mock/reserved domains across all 8 verticals."""
        required_verticals = [
            "mango_quality_analytics",
            "bike_rebalance_analytics",
            "warehouse_automation",
            "field_operations_automation",
            "seo_blog_copilot",
            "marketing_suite",
            "growth_all_in_one",
            "trust_engine",
        ]
        mock_indicators = [".example.com", ".example.org", ".example", ".test", ".invalid", ".localhost", "mock.", "dummy."]

        for vert in required_verticals:
            self.assertIn(vert, CURATED_SMB_DIRECTORY, f"Vertical '{vert}' missing from CURATED_SMB_DIRECTORY")
            candidates = CURATED_SMB_DIRECTORY[vert]
            self.assertGreaterEqual(len(candidates), 3, f"Vertical '{vert}' must have at least 3 curated SMBs")

            for cand in candidates:
                website = cand["website"].lower()
                contact = cand["public_contact_channel"].lower()
                for mock in mock_indicators:
                    self.assertNotIn(mock, website, f"Found mock indicator '{mock}' in {website}")
                    self.assertNotIn(mock, contact, f"Found mock indicator '{mock}' in {contact}")

    def test_verifiable_commercial_domains_included(self):
        """Verify real, verifiable commercial domains specified in the brief are present."""
        all_websites = []
        for cands in CURATED_SMB_DIRECTORY.values():
            for c in cands:
                all_websites.append(c["website"].lower())

        expected_domains = [
            "sahyadrifarms.com",
            "kaybeeexports.com",
            "desaiagrifoods.com",
            "jainirrigation.com",
            "yulu.bike",
            "mybyk.in",
            "zypp.app",
            "emiza.in",
            "wareiq.com",
            "prozo.com",
            "trackofield.com",
            "minimalist.co",
            "kapiva.in",
            "plumgoodness.com",
            "signzy.com",
            "karza.in",
        ]
        for exp in expected_domains:
            found = any(exp in w for w in all_websites)
            self.assertTrue(found, f"Expected verified domain '{exp}' not found in CURATED_SMB_DIRECTORY")

    def test_is_valid_commercial_domain_strict_filter(self):
        """Test strict rejection of any .example.com, .test, .invalid, or mock domains."""
        self.assertFalse(is_valid_commercial_domain("test.example.com"))
        self.assertFalse(is_valid_commercial_domain("company.test"))
        self.assertFalse(is_valid_commercial_domain("internal.invalid"))
        self.assertFalse(is_valid_commercial_domain("service.localhost"))
        self.assertFalse(is_valid_commercial_domain("mock.company.com"))
        self.assertFalse(is_valid_commercial_domain(""))

        self.assertTrue(is_valid_commercial_domain("sahyadrifarms.com"))
        self.assertTrue(is_valid_commercial_domain("trackofield.com"))
        self.assertTrue(is_valid_commercial_domain("minimalist.co"))
        self.assertTrue(is_valid_commercial_domain("signzy.com"))

    def test_discover_smb_leads_attaches_seo_geo_audit(self):
        """Verify discover_smb_leads returns zero mock domains with seo_geo_audit attached."""
        leads = discover_smb_leads(vertical="growth_all_in_one", region="India", limit=5)
        self.assertGreaterEqual(len(leads), 1)

        for lead in leads:
            domain = lead["domain"]
            self.assertTrue(is_valid_commercial_domain(domain))
            self.assertNotIn("example.com", domain)

            audit = lead.get("seo_geo_audit")
            self.assertIsNotNone(audit)
            self.assertIn("has_json_ld_schema", audit)
            self.assertIn("has_faq_schema", audit)
            self.assertIn("has_llms_txt", audit)
            self.assertIn("has_meta_description", audit)
            self.assertIn("has_open_graph", audit)
            self.assertIn("extracted_emails", audit)
            self.assertIn("detected_gaps", audit)
            self.assertIsInstance(audit["detected_gaps"], list)
            self.assertIn("seo_geo_gap_score", audit)
            self.assertGreaterEqual(audit["seo_geo_gap_score"], 0)
            self.assertLessEqual(audit["seo_geo_gap_score"], 100)

    def test_audit_live_website_seo_geo_structure_and_fallback(self):
        """Verify audit_live_website_seo_geo returns detected_gaps list and gap score."""
        audit = audit_live_website_seo_geo("https://sahyadrifarms.com", timeout=2.5)
        self.assertIn("detected_gaps", audit)
        self.assertIsInstance(audit["detected_gaps"], list)
        self.assertIn("seo_geo_gap_score", audit)
        self.assertIn("has_json_ld_schema", audit)
        self.assertIn("has_faq_schema", audit)
        self.assertIn("has_llms_txt", audit)
        self.assertIn("extracted_emails", audit)
        self.assertIn("target_url", audit)

    def test_duckduckgo_live_search_adapter(self):
        """Verify keyless DuckDuckGo live search adapter executes and returns valid structure."""
        results = _search_duckduckgo_live("AgriTech exporters Nashik", limit=3)
        self.assertIsInstance(results, list)
        for r in results:
            self.assertTrue(is_valid_commercial_domain(r.get("domain", "")))

    def test_autonomous_shift_succeeds_in_production_env(self):
        """Verify run_autonomous_shift and lead discovery succeed when APP_ENV='production'."""
        old_env = os.environ.get("APP_ENV")
        try:
            os.environ["APP_ENV"] = "production"
            shift = run_autonomous_shift(
                db=self.db,
                shift_type="production_daily_cycle",
            )
            self.assertEqual(shift["status"], "COMPLETED")
            outbound = shift["steps"]["outbound_sdr"]
            self.assertEqual(outbound["status"], "COMPLETED")
            self.assertGreater(outbound["leads_discovered_count"], 0)
        finally:
            if old_env is not None:
                os.environ["APP_ENV"] = old_env
            else:
                os.environ.pop("APP_ENV", None)

    # ── US-6.2: 2026 SEO + GEO + AIO + Social Expert Engine ──────────────────

    def test_generate_and_stage_blog_upgraded_keys(self):
        """Verify generate_and_stage_blog returns all 2026 SEO, GEO, AIO, and Local Geo structures."""
        blog = generate_and_stage_blog(
            product_name="AskforWrite Growth Suite",
            target_audience="D2C Brand Founders & Solo Entrepreneurs",
            keywords=["AI Marketing Automation", "2026 SEO", "Generative Engine Optimization"],
        )

        # Preserved core keys
        self.assertIn("title", blog)
        self.assertIn("slug", blog)
        self.assertIn("markdown_body", blog)
        self.assertIn("meta_description", blog)
        self.assertIn("schema_json_ld", blog)

        # 2026 Upgraded Keys
        self.assertIn("schema_graph_json_ld", blog)
        graph = blog["schema_graph_json_ld"].get("@graph", [])
        types_in_graph = [item.get("@type") for item in graph]
        self.assertIn("Article", types_in_graph)
        self.assertIn("FAQPage", types_in_graph)
        self.assertIn("Organization", types_in_graph)
        self.assertIn("SoftwareApplication", types_in_graph)

        # Check FAQPage has 3 questions
        faq_item = next(item for item in graph if item.get("@type") == "FAQPage")
        self.assertGreaterEqual(len(faq_item.get("mainEntity", [])), 3)

        # /llms.txt manifest
        self.assertIn("llms_txt_manifest", blog)
        self.assertIn("/llms.txt", blog["llms_txt_manifest"])
        self.assertIn("Perplexity", blog["llms_txt_manifest"])

        # AIO citation blocks
        self.assertIn("aio_citation_blocks", blog)
        aio = blog["aio_citation_blocks"]
        self.assertIn("entity_triples", aio)
        self.assertIn("authoritative_statistics", aio)
        self.assertIn("direct_answer_snippets", aio)

        # Local Geo SEO
        self.assertIn("local_geo_seo", blog)
        geo = blog["local_geo_seo"]
        self.assertIn("geo_intent_keywords", geo)
        self.assertIn("local_business_metadata", geo)
        self.assertIn("google_business_profile_post", geo)

    def test_generate_omnichannel_social_campaign_upgraded_keys(self):
        """Verify generate_omnichannel_social_campaign returns Reels, LinkedIn, Twitter, and WhatsApp scripts."""
        campaign = generate_omnichannel_social_campaign(
            product_name="AskforWrite OS",
            target_audience="FMCG Manufacturers",
            keywords=["Field Operations", "GPS Tracking"],
        )

        # Preserved keys
        self.assertIn("instagram_meta", campaign)
        self.assertIn("linkedin", campaign)
        self.assertIn("google_search_ads", campaign)

        # 2026 Upgraded Keys
        # 1. Instagram Reels Storyboard (30s: Hook, Agitation, AI Proof Demo, CTA)
        self.assertIn("instagram_reels_script", campaign)
        reels = campaign["instagram_reels_script"]
        self.assertEqual(reels.get("duration_seconds"), 30)
        sections = [s["section"] for s in reels.get("storyboard", [])]
        self.assertTrue(any("Hook" in s for s in sections))
        self.assertTrue(any("Agitation" in s or "Problem" in s for s in sections))
        self.assertTrue(any("Demo" in s or "Proof" in s for s in sections))
        self.assertTrue(any("CTA" in s or "Action" in s for s in sections))

        # 2. LinkedIn 5-slide Carousel
        self.assertIn("linkedin_carousel_slides", campaign)
        slides = campaign["linkedin_carousel_slides"]
        self.assertEqual(len(slides), 5)

        # 3. Twitter 4-post thread
        self.assertIn("twitter_x_thread", campaign)
        thread = campaign["twitter_x_thread"]
        self.assertEqual(len(thread), 4)

        # 4. WhatsApp Direct Broadcast
        self.assertIn("whatsapp_direct_broadcast", campaign)
        wa = campaign["whatsapp_direct_broadcast"]
        self.assertIn("message_template", wa)
        self.assertIn("checkout_cta", wa)

    def test_growth_audit_domain_api_endpoint(self):
        """Test POST /v1/growth/audit-domain accepts target_keywords and returns full prescription."""
        payload = {
            "website_url": "https://sahyadrifarms.com",
            "company_name": "Sahyadri Farms Post Harvest",
            "target_keywords": ["Fresh Produce Export", "Brix Quality Grading"],
        }
        resp = self.client.post("/v1/growth/audit-domain", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(data["company_name"], "Sahyadri Farms Post Harvest")

        # seo_geo_audit
        self.assertIn("seo_geo_audit", data)
        self.assertIn("detected_gaps", data["seo_geo_audit"])

        # checkout_links includes afw_directpay
        self.assertIn("checkout_links", data)
        links = data["checkout_links"]
        self.assertIn("razorpay_inr", links)
        self.assertIn("paypal_usd", links)
        self.assertIn("afw_directpay", links)
        self.assertIn("os.askforwrite.com/v1/pay/checkout", links["afw_directpay"])

        # growth_prescription
        self.assertIn("growth_prescription", data)
        gp = data["growth_prescription"]
        self.assertIn("seo_geo_blog", gp)
        self.assertIn("omnichannel_social", gp)
        self.assertIn("schema_graph_json_ld", gp["seo_geo_blog"])
        self.assertIn("instagram_reels_script", gp["omnichannel_social"])

    # ── US-6.3: Sovereign Zero-Fee Payment Gateway (AFW DirectPay) ───────────

    def test_catalog_build_payment_link_supports_afw_directpay(self):
        """Verify build_payment_link with provider='afw_directpay' builds sovereign checkout URL."""
        link = build_payment_link(
            package_key="growth_all_in_one",
            company="Sahyadri Farms",
            provider="afw_directpay",
        )
        self.assertTrue(link.startswith("https://os.askforwrite.com/v1/pay/checkout"))
        self.assertIn("package=growth_all_in_one", link)
        self.assertIn("company=Sahyadri+Farms", link)

    def test_previews_payment_links_includes_afw_directpay(self):
        """Verify generate_trojan_horse_preview returns afw_directpay link."""
        preview = generate_trojan_horse_preview(
            db=self.db,
            company_name="WareIQ Logistics",
            domain="wareiq.com",
            recommended_package="warehouse_automation",
        )
        links = preview.get("payment_links", {})
        self.assertIn("afw_directpay", links)
        self.assertIn("v1/pay/checkout", links["afw_directpay"])

    def test_pure_python_svg_qr_generation(self):
        """Verify generate_inline_qr_svg generates self-contained valid SVG string."""
        sample_uri = "upi://pay?pa=askforwrite@okhdfcbank&pn=AskforWrite&am=9999.00&cu=INR&tn=AFW+OS&tr=sample123"
        svg = generate_inline_qr_svg(sample_uri)
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.strip().endswith("</svg>"))
        self.assertIn("xmlns=\"http://www.w3.org/2000/svg\"", svg)
        self.assertIn("<rect", svg)

    def test_verify_onchain_tx_format_validation(self):
        """Verify verify_onchain_tx accepts valid 0x + 64 hex hashes and rejects invalid ones."""
        valid_evm_tx = "0x" + "a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0"
        result = verify_onchain_tx(valid_evm_tx)
        self.assertTrue(result["verified"])
        self.assertEqual(result["tx_hash"], valid_evm_tx)

        # Invalid formats
        with self.assertRaises(ValueError):
            verify_onchain_tx("0xshort")
        with self.assertRaises(ValueError):
            verify_onchain_tx("not_a_hex_hash")

    def test_create_sovereign_session_endpoint(self):
        """Test POST /v1/pay/create-session returns all 3 settlement rails."""
        payload = {
            "package_key": "growth_all_in_one",
            "company_name": "Kay Bee Exports Fresh Produce",
            "customer_email": "exports@kaybeeexports.com",
            "currency": "INR",
            "preferred_rail": "upi_direct",
        }
        resp = self.client.post("/v1/pay/create-session", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        session_id = data.get("session_id")
        self.assertIsNotNone(session_id)
        self.assertEqual(data["company_name"], "Kay Bee Exports Fresh Produce")
        self.assertEqual(data["amount"], 9999.0)
        self.assertEqual(data["currency"], "INR")
        self.assertTrue(data["zero_gateway_fee"])

        # Rail 1: UPI Direct
        self.assertTrue(data["upi_uri"].startswith("upi://pay?pa="))
        self.assertIn("am=9999.00", data["upi_uri"])
        self.assertIn("<svg", data["upi_qr_svg"])

        # Rail 2: Web3 USDC
        self.assertIn("usdc_payload", data)
        self.assertEqual(data["usdc_payload"]["token"], "USDC")
        self.assertIn("supported_networks", data["usdc_payload"])

        # Rail 3: Bank wire invoice
        self.assertIn("bank_wire_invoice", data)
        expected_bank = os.getenv("AFW_BANK_NAME", "HDFC Bank Ltd")
        self.assertEqual(data["bank_wire_invoice"]["beneficiary"]["bank_name"], expected_bank)
        self.assertIn("digital_seal_hash", data["bank_wire_invoice"])

        # Verify session is retrievable
        session = get_sovereign_pay_session(session_id)
        self.assertIsNotNone(session)
        self.assertEqual(session.status, "PENDING")

    def test_get_checkout_html_page(self):
        """Test GET /v1/pay/{session_id}/checkout returns styled HTML checkout page."""
        session = create_sovereign_pay_session(
            package_key="field_force",
            company_name="TrackoField Workforce",
            customer_email="sales@trackofield.com",
            currency="INR",
        )
        resp = self.client.get(f"/v1/pay/{session.session_id}/checkout")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])
        html_content = resp.text

        # Verify key UI components
        self.assertIn("AFW DirectPay", html_content)
        self.assertIn("TrackoField Workforce", html_content)
        self.assertIn("Instant UPI QR", html_content)
        self.assertIn("USDC Web3", html_content)
        self.assertIn("Direct Bank Wire", html_content)
        self.assertIn(os.getenv("AFW_MERCHANT_UPI_VPA", "askforwrite@okhdfcbank"), html_content)
        self.assertIn("Instant Activation & Trust Block Verification", html_content)

    def test_direct_query_param_checkout_endpoint(self):
        """Test GET /v1/pay/checkout?package=growth_all_in_one&company=Minimalist+Skincare."""
        resp = self.client.get("/v1/pay/checkout?package=growth_all_in_one&company=Minimalist+Skincare")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])
        self.assertIn("Minimalist Skincare", resp.text)

    def test_verify_sovereign_payment_upi_gated_and_owner_confirmed(self):
        """Test UPI verification enters AWAITING_OWNER_CONFIRMATION, creates ApprovalRequest, and requires Owner confirmation."""
        unique_email = f"billing-{uuid.uuid4().hex[:8]}@kaybeeexports.com"
        session = create_sovereign_pay_session(
            package_key="growth_all_in_one",
            company_name="Kay Bee Fresh Produce",
            customer_email=unique_email,
            currency="INR",
            preferred_rail="upi_direct",
        )

        utr_12_digits = "412345678901"
        payload = {
            "rail": "upi_direct",
            "proof_reference": utr_12_digits,
        }

        # Step 1: Customer submits payment proof
        resp = self.client.post(f"/v1/pay/{session.session_id}/verify", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["status"], "AWAITING_CONFIRMATION")
        self.assertEqual(data["approval_status"], "PENDING_OWNER_CONFIRMATION")
        self.assertEqual(data["rail"], "upi_direct")
        self.assertEqual(data["proof_reference"], utr_12_digits)
        self.assertIn("Awaiting founder/owner verification", data["message"])

        # Session state transitioned to AWAITING_OWNER_CONFIRMATION
        session_after_verify = get_sovereign_pay_session(session.session_id)
        self.assertEqual(session_after_verify.status, "AWAITING_OWNER_CONFIRMATION")
        self.assertEqual(session_after_verify.verification_proof, utr_12_digits)

        # Durable ApprovalRequest created in database
        approval = self.db.query(ApprovalRequest).filter_by(task_id=f"sovereign_pay_{session.session_id}").first()
        self.assertIsNotNone(approval)
        self.assertEqual(approval.status, "PENDING")
        self.assertEqual(approval.action, "sovereign_payment_verification")
        self.assertEqual(approval.detail["rail"], "upi_direct")
        self.assertEqual(approval.detail["proof_reference"], utr_12_digits)

        # Step 2: Non-owner (Manager) cannot confirm settlement (403 Forbidden)
        manager_headers = {"X-API-Key": self.manager_key, "X-Correlation-ID": "test-mgr-corr"}
        forbidden_resp = self.client.post(f"/v1/pay/{session.session_id}/confirm-owner", headers=manager_headers)
        self.assertEqual(forbidden_resp.status_code, 403)

        # Step 3: Owner confirms settlement
        owner_headers = {"X-API-Key": self.owner_key, "X-Correlation-ID": "test-owner-corr"}
        confirm_resp = self.client.post(f"/v1/pay/{session.session_id}/confirm-owner", headers=owner_headers)
        self.assertEqual(confirm_resp.status_code, 200)
        confirm_data = confirm_resp.json()

        self.assertEqual(confirm_data["status"], "CONFIRMED_AND_PROVISIONED")
        self.assertEqual(confirm_data["rail"], "upi_direct")
        self.assertEqual(confirm_data["proof_reference"], utr_12_digits)

        # 1. TrustBlock sealed
        self.assertIn("trust_block", confirm_data)
        block_idx = confirm_data["trust_block"]["index"]
        block = self.db.query(TrustBlock).filter_by(index=block_idx).first()
        self.assertIsNotNone(block)
        self.assertEqual(block.capability_name, "afw_sovereign_pay")
        self.assertEqual(block.action, "sovereign_payment_verified_by_owner")
        self.assertTrue(len(block.signature) > 20)

        # 2. Multi-tenant Auto-Provisioning
        prov = confirm_data["provisioning"]
        self.assertEqual(prov["status"], "provisioned")
        org_id = prov["org_id"]
        user_id = prov["user_id"]

        org = self.db.query(OrganizationRecord).filter_by(id=org_id).first()
        self.assertIsNotNone(org)
        self.assertEqual(org.tier, "growth_all_in_one")
        self.assertEqual(org.metadata_json.get("payment_provider"), "afw_directpay")

        user = self.db.query(UserRecord).filter_by(id=user_id).first()
        self.assertIsNotNone(user)
        self.assertEqual(user.email, unique_email)
        self.assertEqual(user.role, "admin")
        self.assertTrue(user.is_active)

        invoice = self.db.query(InvoiceRecord).filter_by(org_id=org_id).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.status, "paid")
        self.assertEqual(invoice.amount, 999900)  # in paise
        self.assertEqual(invoice.currency, "INR")

        # 3. ApprovalRequest updated to APPROVED
        self.db.refresh(approval)
        self.assertEqual(approval.status, "APPROVED")
        self.assertEqual(approval.decided_by, "owner")

        # 4. Session state updated to COMPLETED
        updated_session = get_sovereign_pay_session(session.session_id)
        self.assertEqual(updated_session.status, "COMPLETED")
        self.assertEqual(updated_session.verification_proof, utr_12_digits)

    def test_verify_sovereign_payment_bank_wire_gated_and_owner_confirmed(self):
        """Test Bank Wire verification enters AWAITING_OWNER_CONFIRMATION and completes upon Owner confirmation."""
        unique_email = f"wire-{uuid.uuid4().hex[:8]}@jainirrigation.com"
        session = create_sovereign_pay_session(
            package_key="field_force",
            company_name="Jain Irrigation Systems",
            customer_email=unique_email,
            currency="INR",
            preferred_rail="bank_wire_direct",
        )

        wire_ref = "CMS-NEFT-2026-998811"
        payload = {
            "rail": "bank_wire_direct",
            "proof_reference": wire_ref,
        }

        # Step 1: Customer submits bank wire reference
        resp = self.client.post(f"/v1/pay/{session.session_id}/verify", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "AWAITING_CONFIRMATION")
        self.assertEqual(data["rail"], "bank_wire_direct")

        # Step 2: Owner confirms
        owner_headers = {"X-API-Key": self.owner_key, "X-Correlation-ID": "test-owner-wire-corr"}
        confirm_resp = self.client.post(f"/v1/pay/{session.session_id}/confirm-owner", headers=owner_headers)
        self.assertEqual(confirm_resp.status_code, 200)
        confirm_data = confirm_resp.json()
        self.assertEqual(confirm_data["status"], "CONFIRMED_AND_PROVISIONED")
        self.assertEqual(confirm_data["rail"], "bank_wire_direct")
        self.assertEqual(confirm_data["proof_reference"], wire_ref)

    def test_verify_sovereign_payment_web3_usdc(self):
        """Test verifying Web3 0x64 hex hash seals TrustBlock and provisions in USD."""
        unique_email = f"web3-{uuid.uuid4().hex[:8]}@prozo.com"
        session = create_sovereign_pay_session(
            package_key="warehouse_automation",
            company_name="Prozo Warehousing",
            customer_email=unique_email,
            currency="USD",
            preferred_rail="web3_usdc",
        )

        valid_tx_hash = "0x" + "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        payload = {
            "rail": "web3_usdc",
            "proof_reference": valid_tx_hash,
        }
        resp = self.client.post(f"/v1/pay/{session.session_id}/verify", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["status"], "VERIFIED")
        self.assertEqual(data["rail"], "web3_usdc")

        # Verify TrustBlock
        block_idx = data["trust_block"]["index"]
        block = self.db.query(TrustBlock).filter_by(index=block_idx).first()
        self.assertIsNotNone(block)
        self.assertEqual(block.capability_name, "afw_sovereign_pay")

        # Verify USD invoice
        org_id = data["provisioning"]["org_id"]
        inv = self.db.query(InvoiceRecord).filter_by(org_id=org_id).first()
        self.assertIsNotNone(inv)
        self.assertEqual(inv.currency, "USD")
        self.assertEqual(inv.status, "paid")

    def test_verify_payment_invalid_proof_rejected(self):
        """Test invalid proofs are rejected with 400 Bad Request."""
        session = create_sovereign_pay_session(
            package_key="trust_engine",
            company_name="Signzy Compliance",
            customer_email="sales@signzy.com",
            currency="INR",
        )

        # Invalid UPI (too short)
        resp1 = self.client.post(
            f"/v1/pay/{session.session_id}/verify",
            json={"rail": "upi_direct", "proof_reference": "12345"},
        )
        self.assertEqual(resp1.status_code, 400)
        self.assertIn("12-digit", resp1.json()["detail"])

        # Invalid Web3 hash (not 0x prefix or not 64 hex chars)
        resp2 = self.client.post(
            f"/v1/pay/{session.session_id}/verify",
            json={"rail": "web3_usdc", "proof_reference": "not_a_valid_hash_format"},
        )
        self.assertEqual(resp2.status_code, 400)

    def test_trust_chain_integrity_after_sovereign_payments(self):
        """Verify the full ECDSA NIST P-256 Merkle chain remains 100% valid after sovereign blocks."""
        integrity = verify_chain_integrity(self.db)
        self.assertTrue(integrity["chain_valid"])
        self.assertEqual(len(integrity["errors"]), 0)
        self.assertGreaterEqual(integrity["total_blocks"], 1)


if __name__ == "__main__":
    unittest.main()
