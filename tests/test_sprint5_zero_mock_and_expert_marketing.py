"""Test Suite for Sprint 5:
1. US-5.1: Zero-Mock Live SMB Discovery & Live Website SEO/GEO Auditor (smb_search_source.py)
2. US-5.2: 2026 SEO + GEO + AIO + Social Expert Engine (growth_engine.py & POST /v1/growth/audit-domain)
3. US-5.3: Shift-to-Outreach Revenue Loop with Trojan-Horse Previews & HITL Approvals (shift_scheduler.py)
4. US-5.4: Production Database Migration & Customer Portal Quota Guard (customer_portal.py)
"""

from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

import migrations.versions.e5f6a1b2c3d4_add_watchdog_preview_and_shift_tables as sprint5_migration
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
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
    OrganizationRecord,
    OutreachRecord,
    UserRecord,
)
from app.main import app
from app.security.auth import create_access_token, hash_password
from app.services.approvals import decide_approval
from app.services.growth_engine import (
    generate_and_stage_blog,
    generate_omnichannel_social_campaign,
)
from app.services.shift_scheduler import run_autonomous_shift


class Sprint5ZeroMockAndExpertMarketingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.manager_key = "test-manager-key-sprint5-zeromock-32ch"
        cls.owner_key = "test-owner-key-sprint5-zeromock-32ch"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        os.environ["OWNER_API_KEY"] = cls.owner_key
        cls.client = TestClient(app)
        cls.headers = {
            "X-API-Key": cls.manager_key,
            "X-Correlation-ID": "test-sprint5-corr-suite",
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

    # ── US-5.1: Zero-Mock SMB Discovery & SEO/GEO Auditor Tests ───────────────

    def test_curated_directory_has_zero_mock_domains(self):
        """Verify no .example.com, .test, or .invalid domain exists in CURATED_SMB_DIRECTORY."""
        forbidden_substrings = [".example.com", ".example.org", ".example.net", ".test", ".invalid", "mock"]
        total_leads_checked = 0

        for vertical, candidates in CURATED_SMB_DIRECTORY.items():
            self.assertGreater(len(candidates), 0, f"Vertical {vertical} should not be empty")
            for cand in candidates:
                total_leads_checked += 1
                website = cand.get("website", "").lower()
                contact = cand.get("public_contact_channel", "").lower()

                for sub in forbidden_substrings:
                    self.assertNotIn(sub, website, f"Found mock substring '{sub}' in website '{website}' for {vertical}")
                    self.assertNotIn(sub, contact, f"Found mock substring '{sub}' in contact '{contact}' for {vertical}")

                # Ensure valid commercial domain
                domain = website.replace("https://", "").replace("http://", "").split("/")[0]
                self.assertTrue(is_valid_commercial_domain(domain), f"Domain '{domain}' must be a valid commercial domain")

        self.assertGreaterEqual(total_leads_checked, 24, "Should have verified directory entries across all verticals")

    def test_discover_smb_leads_all_8_verticals_zero_mock_and_audit_attached(self):
        """discover_smb_leads across all 8 verticals returns real domains with seo_geo_audit."""
        verticals = [
            "warehouse_automation",
            "mango_quality_analytics",
            "growth_all_in_one",
            "bike_rebalance_analytics",
            "conveyance_fraud_detection",
            "field_operations_automation",
            "ayurvedic_fmcg_automation",
            "fintech_lending_compliance",
        ]

        for vert in verticals:
            leads = discover_smb_leads(vertical=vert, region="India", limit=2)
            self.assertGreaterEqual(len(leads), 1, f"Failed to discover leads for vertical: {vert}")
            for lead in leads:
                domain = lead["domain"]
                self.assertFalse(domain.endswith(".example.com"))
                self.assertFalse(domain.endswith(".test"))
                self.assertFalse(domain.endswith(".invalid"))
                self.assertTrue(is_valid_commercial_domain(domain))

                # Verify SEO/GEO audit is attached to every discovered lead
                self.assertIn("seo_geo_audit", lead)
                audit = lead["seo_geo_audit"]
                self.assertIn("has_json_ld_schema", audit)
                self.assertIn("has_faq_schema", audit)
                self.assertIn("has_llms_txt", audit)
                self.assertIn("has_meta_description", audit)
                self.assertIn("has_open_graph", audit)
                self.assertIn("extracted_emails", audit)
                self.assertIn("seo_geo_gap_score", audit)
                self.assertTrue(0 <= audit["seo_geo_gap_score"] <= 100)

    def test_audit_live_website_seo_geo_offline_and_fallback(self):
        """Verify audit_live_website_seo_geo reports all required keys and handles timeouts cleanly."""
        res = audit_live_website_seo_geo("https://sahyadrifarms.com", timeout=1.0)
        self.assertIn("domain", res)
        self.assertEqual(res["domain"], "sahyadrifarms.com")
        self.assertIn("has_json_ld_schema", res)
        self.assertIn("has_faq_schema", res)
        self.assertIn("has_llms_txt", res)
        self.assertIn("has_meta_description", res)
        self.assertIn("has_open_graph", res)
        self.assertIn("extracted_emails", res)
        self.assertIn("seo_geo_gap_score", res)
        self.assertTrue(0 <= res["seo_geo_gap_score"] <= 100)
        self.assertIn(res["audit_status"], ["LIVE_VERIFIED", "ESTIMATED_OFFLINE"])

    def test_duckduckgo_live_search_adapter(self):
        """Verify _search_duckduckgo_live executes safely and returns list of dicts."""
        res = _search_duckduckgo_live(query="warehouse logistics SMB India", limit=3)
        self.assertIsInstance(res, list)
        for item in res:
            self.assertIn("company", item)
            self.assertIn("website", item)
            self.assertIn("domain", item)
            self.assertTrue(is_valid_commercial_domain(item["domain"]))

    # ── US-5.2: 2026 SEO + GEO + AIO + Social Media Expert Engine ─────────────

    def test_generate_and_stage_blog_2026_seo_geo_aio(self):
        """Verify generate_and_stage_blog outputs all required 2026 Schema graph, llms.txt, and AIO blocks."""
        res = generate_and_stage_blog(
            product_name="AskforWrite Growth OS",
            target_audience="Direct-to-Consumer Brands",
            keywords=["generative engine optimization", "autonomous marketing"],
        )

        # 1. Existing keys preserved
        self.assertIn("title", res)
        self.assertIn("slug", res)
        self.assertIn("primary_keyword", res)
        self.assertIn("meta_description", res)
        self.assertIn("schema_json_ld", res)
        self.assertIn("markdown_body", res)

        # 2. Schema.org @graph with Article, FAQPage (3 Q&As), Organization, SoftwareApplication
        self.assertIn("schema_graph_json_ld", res)
        graph = res["schema_graph_json_ld"]
        self.assertEqual(graph["@context"], "https://schema.org")
        self.assertIn("@graph", graph)
        types = [item["@type"] for item in graph["@graph"]]
        self.assertIn("Article", types)
        self.assertIn("FAQPage", types)
        self.assertIn("Organization", types)
        self.assertIn("SoftwareApplication", types)

        faq = next(item for item in graph["@graph"] if item["@type"] == "FAQPage")
        self.assertEqual(len(faq["mainEntity"]), 3)
        for q in faq["mainEntity"]:
            self.assertEqual(q["@type"], "Question")
            self.assertIn("@type", q["acceptedAnswer"])
            self.assertEqual(q["acceptedAnswer"]["@type"], "Answer")

        # 3. llms.txt manifest
        self.assertIn("llms_txt_manifest", res)
        manifest = res["llms_txt_manifest"]
        self.assertIn("/llms.txt", manifest)
        self.assertIn("SearchGPT", manifest)
        self.assertIn("Google Gemini", manifest)

        # 4. AIO citation blocks
        self.assertIn("aio_citation_blocks", res)
        aio = res["aio_citation_blocks"]
        self.assertIn("entity_triples", aio)
        self.assertIn("authoritative_statistics", aio)
        self.assertIn("direct_answer_snippets", aio)
        self.assertGreaterEqual(len(aio["entity_triples"]), 2)
        self.assertGreaterEqual(len(aio["authoritative_statistics"]), 2)
        self.assertGreaterEqual(len(aio["direct_answer_snippets"]), 2)

        # 5. Local GEO SEO
        self.assertIn("local_geo_seo", res)
        local = res["local_geo_seo"]
        self.assertIn("target_region", local)
        self.assertIn("geo_intent_keywords", local)
        self.assertIn("local_business_metadata", local)
        self.assertIn("google_business_profile_post", local)

    def test_generate_omnichannel_social_campaign_2026_formats(self):
        """Verify generate_omnichannel_social_campaign outputs Reels, Carousel, X thread, and WhatsApp broadcast."""
        res = generate_omnichannel_social_campaign(
            product_name="AskforWrite Growth OS",
            target_audience="SMB Founders & Marketing Directors",
            keywords=["ecommerce growth", "ai sales closer"],
        )

        # 1. Existing keys preserved
        self.assertIn("instagram_meta", res)
        self.assertIn("linkedin", res)
        self.assertIn("google_search_ads", res)
        self.assertIn("ai_campaign_pitch", res)

        # 2. Instagram Reels script (30 seconds, 4 sections)
        self.assertIn("instagram_reels_script", res)
        reels = res["instagram_reels_script"]
        self.assertEqual(reels["duration_seconds"], 30)
        self.assertEqual(len(reels["storyboard"]), 4)
        sections = [s["section"] for s in reels["storyboard"]]
        self.assertIn("Hook", sections[0])
        self.assertIn("Problem", sections[1])
        self.assertIn("Demo", sections[2])
        self.assertIn("Action", sections[3])

        # 3. LinkedIn Carousel slides (5 slides)
        self.assertIn("linkedin_carousel_slides", res)
        slides = res["linkedin_carousel_slides"]
        self.assertEqual(len(slides), 5)
        self.assertEqual(slides[0]["slide_number"], 1)
        self.assertEqual(slides[-1]["slide_number"], 5)

        # 4. Twitter/X Thread (4 posts)
        self.assertIn("twitter_x_thread", res)
        thread = res["twitter_x_thread"]
        self.assertEqual(len(thread), 4)
        self.assertTrue(thread[0].startswith("1/4"))
        self.assertTrue(thread[-1].startswith("4/4"))

        # 5. WhatsApp Direct Broadcast
        self.assertIn("whatsapp_direct_broadcast", res)
        wa = res["whatsapp_direct_broadcast"]
        self.assertIn("message_template", wa)
        self.assertIn("objection_killer", wa)
        self.assertIn("checkout_cta", wa)

    def test_post_growth_audit_domain_endpoint(self):
        """POST /v1/growth/audit-domain runs audit and returns growth prescription with checkout links."""
        payload = {
            "website_url": "sahyadrifarms.com",
            "company_name": "Sahyadri Farms",
        }
        res = self.client.post("/v1/growth/audit-domain", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(data["domain"], "sahyadrifarms.com")
        self.assertEqual(data["company_name"], "Sahyadri Farms")
        self.assertIn("seo_geo_audit", data)
        self.assertIn("checkout_links", data)
        self.assertIn("razorpay_inr", data["checkout_links"])
        self.assertIn("paypal_usd", data["checkout_links"])
        self.assertIn("growth_prescription", data)

        rx = data["growth_prescription"]
        self.assertIn("seo_geo_blog", rx)
        self.assertIn("omnichannel_social", rx)
        self.assertIn("schema_graph_json_ld", rx["seo_geo_blog"])
        self.assertIn("llms_txt_manifest", rx["seo_geo_blog"])
        self.assertIn("instagram_reels_script", rx["omnichannel_social"])
        self.assertIn("whatsapp_direct_broadcast", rx["omnichannel_social"])

    # ── US-5.3: Shift Scheduler Trojan-Horse Outreach Loop Tests ──────────────

    def test_autonomous_shift_stages_outreach_and_approval_dispatches(self):
        """run_autonomous_shift stages OutreachRecord with preview URL, and approving dispatches it."""
        corr_id = f"test-shift-{uuid.uuid4().hex[:8]}"
        shift_res = run_autonomous_shift(db=self.db, shift_type="full_daily_cycle", correlation_id=corr_id)
        self.assertEqual(shift_res["status"], "COMPLETED")

        sdr_step = shift_res.get("step_results", {}).get("outbound_sdr") or shift_res.get("steps", {}).get("outbound_sdr")
        self.assertIsNotNone(sdr_step)
        self.assertEqual(sdr_step["status"], "COMPLETED")
        self.assertIn("outreach_drafts_staged_count", sdr_step)
        self.assertIn("outreach_drafts", sdr_step)

        drafts = sdr_step["outreach_drafts"]
        if drafts:
            first_draft = drafts[0]
            self.assertIn("outreach_id", first_draft)
            self.assertIn("approval_id", first_draft)
            self.assertIn("preview_url", first_draft)
            self.assertTrue(first_draft["preview_url"].startswith("/v1/previews/"))
            self.assertTrue(first_draft["preview_url"].endswith("/html"))

            # Verify in DB
            outreach = self.db.query(OutreachRecord).filter(OutreachRecord.id == first_draft["outreach_id"]).first()
            self.assertIsNotNone(outreach)
            self.assertIn("/v1/previews/", outreach.body_text)

            # Approve via decide_approval and verify dispatch
            if first_draft.get("approval_id"):
                approval = self.db.query(ApprovalRequest).filter(ApprovalRequest.id == first_draft["approval_id"]).first()
                if approval and approval.status == "PENDING":
                    decide_approval(
                        db=self.db,
                        approval_id=approval.id,
                        decision="APPROVED",
                        decided_by="vipul-owner",
                    )
                    self.db.refresh(outreach)
                    self.assertIn(outreach.status, ["SENT", "DISPATCHED"])
                    self.assertIsNotNone(outreach.sent_at)

    # ── US-5.4: Alembic Migration & Customer Portal Quota Guard Tests ─────────

    def test_alembic_migration_e5f6a1b2c3d4_parity(self):
        """Verify Alembic migration e5f6a1b2c3d4 creates watchdog, preview, and shift tables with indexes."""
        alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
        config = Config(str(alembic_ini))
        script_dir = ScriptDirectory.from_config(config)

        heads = script_dir.get_heads()
        self.assertEqual(heads, ["e5f6a1b2c3d4"])

        test_engine = create_engine("sqlite://", poolclass=StaticPool)
        with test_engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)
            orig_op = sprint5_migration.op
            sprint5_migration.op = op
            try:
                sprint5_migration.upgrade()
                conn.commit()

                inspector = inspect(conn)
                tables = inspector.get_table_names()
                self.assertIn("supervisor_alert_records", tables)
                self.assertIn("preview_records", tables)
                self.assertIn("shift_records", tables)
            finally:
                sprint5_migration.op = orig_op

    def test_customer_portal_inactive_org_and_quota_exhaustion(self):
        """POST /v1/me/use-service returns 403 on inactive org and 429 when quota is exhausted."""
        uid_suffix = uuid.uuid4().hex[:8]

        # 1. Inactive organization -> 403 Forbidden
        inactive_org = OrganizationRecord(
            id=f"org-inactive-{uid_suffix}",
            name=f"Inactive Org {uid_suffix}",
            slug=f"org-inactive-{uid_suffix}",
            is_active=False,
            lead_credits_limit=10,
            lead_credits_used=0,
        )
        self.db.add(inactive_org)

        inactive_user = UserRecord(
            id=f"user-inactive-{uid_suffix}",
            email=f"inactive_{uid_suffix}@example.com",
            full_name=f"Inactive User {uid_suffix}",
            password_hash=hash_password("Password123!"),
            role="member",
            org_id=inactive_org.id,
        )
        self.db.add(inactive_user)
        self.db.commit()

        inactive_token = create_access_token(
            user_id=inactive_user.id,
            email=inactive_user.email,
            role="member",
            org_id=inactive_org.id,
        )
        inactive_resp = self.client.post(
            "/v1/me/use-service",
            json={"service_key": "warehouse_automation"},
            headers={"Authorization": f"Bearer {inactive_token}"},
        )
        self.assertEqual(inactive_resp.status_code, 403)
        self.assertIn("inactive", inactive_resp.json()["detail"].lower())

        # 2. Active organization with quota exhausted -> 429 Too Many Requests
        exhausted_org = OrganizationRecord(
            id=f"org-exhausted-{uid_suffix}",
            name=f"Exhausted Org {uid_suffix}",
            slug=f"org-exhausted-{uid_suffix}",
            is_active=True,
            lead_credits_limit=5,
            lead_credits_used=5,
        )
        self.db.add(exhausted_org)

        exhausted_user = UserRecord(
            id=f"user-exhausted-{uid_suffix}",
            email=f"exhausted_{uid_suffix}@example.com",
            full_name=f"Exhausted User {uid_suffix}",
            password_hash=hash_password("Password123!"),
            role="member",
            org_id=exhausted_org.id,
        )
        self.db.add(exhausted_user)
        self.db.commit()

        exhausted_token = create_access_token(
            user_id=exhausted_user.id,
            email=exhausted_user.email,
            role="member",
            org_id=exhausted_org.id,
        )
        exhausted_resp = self.client.post(
            "/v1/me/use-service",
            json={"service_key": "warehouse_automation"},
            headers={"Authorization": f"Bearer {exhausted_token}"},
        )
        self.assertEqual(exhausted_resp.status_code, 429)
        self.assertIn("exhausted", exhausted_resp.json()["detail"].lower())

        # 3. Active organization with credits remaining -> 200 OK and decrements quota
        active_org = OrganizationRecord(
            id=f"org-active-{uid_suffix}",
            name=f"Active Org {uid_suffix}",
            slug=f"org-active-{uid_suffix}",
            is_active=True,
            lead_credits_limit=10,
            lead_credits_used=2,
        )
        self.db.add(active_org)

        active_user = UserRecord(
            id=f"user-active-{uid_suffix}",
            email=f"active_{uid_suffix}@example.com",
            full_name=f"Active User {uid_suffix}",
            password_hash=hash_password("Password123!"),
            role="member",
            org_id=active_org.id,
        )
        self.db.add(active_user)
        self.db.commit()

        active_token = create_access_token(
            user_id=active_user.id,
            email=active_user.email,
            role="member",
            org_id=active_org.id,
        )
        success_resp = self.client.post(
            "/v1/me/use-service",
            json={"service_key": "warehouse_automation"},
            headers={"Authorization": f"Bearer {active_token}"},
        )
        self.assertEqual(success_resp.status_code, 200)
        success_data = success_resp.json()
        self.assertEqual(success_data["credits_remaining"], 7)
        self.assertEqual(success_data["credits_used"], 3)


if __name__ == "__main__":
    unittest.main()
