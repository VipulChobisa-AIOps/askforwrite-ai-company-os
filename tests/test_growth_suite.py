"""Comprehensive Tests for the Autonomous AI Growth & Inbound Sales Suite.

Validates:
1. Catalog definition and pricing for growth_all_in_one master bundle
2. Pixel AI Visual & Creative Studio asset generation
3. SEO & GEO Blog Automation Copilot with Schema.org JSON-LD
4. Omnichannel marketing social & ad copy synthesis
5. Atomic unified growth execution with Merkle TrustBlock sealing
6. 24/7 Autonomous Inbound Sales Closer (dialogue, objections, checkout closing)
7. Revenue agent diagnosis matching
8. FastAPI /v1/growth/* endpoints
"""

import os
import unittest
import uuid

from fastapi.testclient import TestClient

from app.agents.revenue_agent import diagnose_lead_opportunity
from app.db.database import Base, SessionLocal, engine
from app.db.models import IdempotencyRecord, LeadRecordRow, TaskRecord, TrustBlock
from app.main import app
from app.services.catalog import build_payment_link, get_package
from app.services.growth_engine import (
    execute_unified_growth_run,
    generate_and_stage_blog,
    generate_creative_assets,
    generate_omnichannel_social_campaign,
    handle_inbound_sales_chat,
)


class GrowthSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)
        cls.manager_key = os.environ.get(
            "MANAGER_API_KEY",
            "pA9F0w_3mK8sL2vX1qZ7jR6tY4uN5bE8oP3iU6yT9rE2wQ1a",
        )

    def setUp(self):
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_growth_catalog_definition(self):
        """Verify growth_all_in_one package attributes and pricing integrity."""
        pkg = get_package("growth_all_in_one")
        self.assertIsNotNone(pkg)
        self.assertEqual(pkg.key, "growth_all_in_one")
        self.assertEqual(pkg.category, "master_bundle")
        self.assertEqual(pkg.price_inr, 9999)
        self.assertEqual(pkg.price_usd, 129)
        self.assertEqual(pkg.tier, "growth_all_in_one")
        self.assertIn("pixel_ai_creative_studio", pkg.entitled_capabilities)
        self.assertIn("inbound_sales_closer", pkg.entitled_capabilities)
        self.assertIn("seo_content_automation", pkg.entitled_capabilities)
        self.assertIn("marketing_campaign_suite", pkg.entitled_capabilities)
        self.assertGreaterEqual(pkg.lead_credits_monthly, 300)

        # Validate payment links
        inr_link = build_payment_link(package_key="growth_all_in_one", company="Acme Retail", provider="razorpay")
        self.assertIn("razorpay.me", inr_link)
        self.assertIn("amount=999900", inr_link)
        self.assertIn("notes_package=growth_all_in_one", inr_link)

        usd_link = build_payment_link(package_key="growth_all_in_one", company="Acme Retail", provider="paypal")
        self.assertIn("paypal.me", usd_link)
        self.assertIn("129", usd_link)

    def test_generate_creative_assets(self):
        """Verify multi-format visual specs generation formatted for Pixel AI."""
        res = generate_creative_assets(
            product_name="Vedic Glow Skin Serum",
            target_audience="Direct-to-consumer skincare buyers in India",
            aspect_ratios=["1:1", "9:16", "16:9"],
        )
        self.assertEqual(res["product_name"], "Vedic Glow Skin Serum")
        self.assertEqual(len(res["variants"]), 3)

        feed_variant = next(v for v in res["variants"] if v["aspect_ratio"] == "1:1")
        self.assertEqual(feed_variant["dimensions"], "1080x1080")
        self.assertIn("Instagram Feed", feed_variant["channel_placement"])
        self.assertIn("Vedic Glow Skin Serum", feed_variant["prompt_recipe"])
        self.assertIn("primary", feed_variant["color_palette"])

        story_variant = next(v for v in res["variants"] if v["aspect_ratio"] == "9:16")
        self.assertEqual(story_variant["dimensions"], "1080x1920")

    def test_generate_and_stage_blog(self):
        """Verify SEO and Generative Engine Optimized (GEO) article generation."""
        res = generate_and_stage_blog(
            product_name="AyurPulse",
            target_audience="Holistic health seekers",
            keywords=["ayurvedic immunity booster", "herbal wellness daily"],
        )
        self.assertIn("AyurPulse", res["title"])
        self.assertEqual(res["primary_keyword"], "ayurvedic immunity booster")
        self.assertIn("https://schema.org", res["schema_json_ld"]["@context"])
        self.assertEqual(res["schema_json_ld"]["@type"], "Article")
        self.assertIn("Direct Answer for Generative Engines (GEO)", res["markdown_body"])
        self.assertIn("What is AyurPulse?", res["markdown_body"])

    def test_generate_omnichannel_social_campaign(self):
        """Verify Meta, LinkedIn, and Google Ads copy generation."""
        res = generate_omnichannel_social_campaign(
            product_name="TaskStream AI",
            target_audience="Startup founders",
            keywords=["task automation", "founder productivity"],
        )
        self.assertIn("instagram_meta", res)
        self.assertIn("linkedin", res)
        self.assertIn("google_search_ads", res)
        self.assertTrue(len(res["instagram_meta"]["hashtags"]) >= 3)
        self.assertIn("TaskStream AI", res["google_search_ads"]["headline_1"])

    def test_execute_unified_growth_run_with_trust_sealing(self):
        """Verify atomic growth run creates TaskRecord, AuditLog, and seals TrustBlock."""
        corr_id = str(uuid.uuid4())
        idemp_key = f"growth-test-{uuid.uuid4()}"
        initial_block_count = self.db.query(TrustBlock).count()

        res = execute_unified_growth_run(
            db=self.db,
            client_name="Jaipur Artisan Crafts",
            product_or_service="Handcrafted Blue Pottery",
            target_audience="Home decor enthusiasts and boutique gift buyers",
            keywords=["jaipur blue pottery", "handcrafted home decor"],
            correlation_id=corr_id,
            agent_id="test-manager",
            idempotency_key=idemp_key,
        )

        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["package_name"], "AskforWrite Autonomous AI Growth & Inbound Sales Suite")
        self.assertIn("inr_razorpay", res["checkout_links"])
        self.assertIn("creative_assets", res)
        self.assertIn("seo_geo_blog", res)
        self.assertIn("omnichannel_campaign", res)

        # Verify task persistence
        task = self.db.get(TaskRecord, res["task_id"])
        self.assertIsNotNone(task)
        self.assertEqual(task.status, "COMPLETED")

        # Verify cryptographic trust block sealed
        new_block_count = self.db.query(TrustBlock).count()
        self.assertEqual(new_block_count, initial_block_count + 1)
        latest_block = self.db.query(TrustBlock).order_by(TrustBlock.index.desc()).first()
        self.assertEqual(latest_block.capability_name, "autonomous_growth_suite")

        # Verify idempotency
        idemp_record = self.db.query(IdempotencyRecord).filter_by(idempotency_key=idemp_key).first()
        self.assertIsNotNone(idemp_record)

        # Re-running with same idempotency returns cached result
        res_cached = execute_unified_growth_run(
            db=self.db,
            client_name="Jaipur Artisan Crafts",
            product_or_service="Handcrafted Blue Pottery",
            target_audience="Home decor enthusiasts and boutique gift buyers",
            keywords=["jaipur blue pottery", "handcrafted home decor"],
            correlation_id=corr_id,
            agent_id="test-manager",
            idempotency_key=idemp_key,
        )
        self.assertEqual(res_cached["task_id"], res["task_id"])

    def test_inbound_sales_closer_chat(self):
        """Verify 24/7 autonomous sales closer handles consultation, objections, and closes deal."""
        session_id = str(uuid.uuid4())
        contact = f"prospect_{uuid.uuid4().hex[:6]}@example.com"

        # 1. Price query
        res1 = handle_inbound_sales_chat(
            db=self.db,
            session_id=session_id,
            prospect_name="Rohit Verma",
            prospect_contact=contact,
            message="How much does this cost per month?",
            currency="INR",
        )
        self.assertIn("₹9,999", res1["reply"])
        self.assertFalse(res1["checkout_link_attached"])

        # 2. Price objection handling
        res2 = handle_inbound_sales_chat(
            db=self.db,
            session_id=session_id,
            prospect_name="Rohit Verma",
            prospect_contact=contact,
            message="That seems expensive compared to hiring a cheap freelancer",
            currency="INR",
        )
        self.assertIn("Traditional agencies charge", res2["reply"])
        self.assertFalse(res2["checkout_link_attached"])

        # 3. Technical complexity objection handling
        res3 = handle_inbound_sales_chat(
            db=self.db,
            session_id=session_id,
            prospect_name="Rohit Verma",
            prospect_contact=contact,
            message="Do I need technical or coding skills to run this?",
            currency="INR",
        )
        self.assertIn("zero technical or coding knowledge required", res3["reply"])

        # 4. Closing the sale with live checkout link
        res4 = handle_inbound_sales_chat(
            db=self.db,
            session_id=session_id,
            prospect_name="Rohit Verma",
            prospect_contact=contact,
            message="I am ready to buy, send me the checkout link to start",
            currency="INR",
        )
        self.assertTrue(res4["checkout_link_attached"])
        self.assertIsNotNone(res4["checkout_link"])
        self.assertIn("razorpay.me", res4["checkout_link"])

        # Verify lead status updated
        lead = self.db.query(LeadRecordRow).filter_by(public_contact_channel=contact).first()
        self.assertIsNotNone(lead)
        self.assertEqual(lead.status, "QUALIFIED")

    def test_revenue_agent_diagnose_growth_suite(self):
        """Verify revenue diagnosis engine matches growth_all_in_one for creative + inbound closer signals."""
        diagnosis = diagnose_lead_opportunity(
            company="D2C Apparel Brand",
            website="https://d2capparel.in",
            signals=[
                "Need automated ad photos and reels for instagram",
                "Looking for an all-in-one growth suite with whatsapp sales closer",
                "Solo founder replacing expensive marketing agency",
            ],
            geography="Mumbai, India",
            industry="Apparel & E-commerce",
        )
        self.assertEqual(diagnosis["recommended_package_key"], "growth_all_in_one")
        self.assertEqual(diagnosis["currency"], "INR")
        self.assertEqual(diagnosis["price"], 9999)
        self.assertIn("razorpay.me", str(diagnosis["payment_link"]))

    def test_growth_suite_api_endpoints(self):
        """Verify /v1/growth/* endpoints return expected schema and responses."""
        # 1. Status endpoint
        resp_status = self.client.get("/v1/growth/status")
        self.assertEqual(resp_status.status_code, 200)
        data = resp_status.json()
        self.assertEqual(data["status"], "OPERATIONAL")
        self.assertEqual(data["package_key"], "growth_all_in_one")
        self.assertTrue(data["closer_active"])

        # 2. Creative specs endpoint
        resp_creative = self.client.post(
            "/v1/growth/creative",
            json={
                "product_name": "Artisan Leather Wallet",
                "target_audience": "Urban minimalist gift buyers",
                "aspect_ratios": ["1:1", "16:9"],
            },
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp_creative.status_code, 200)
        c_data = resp_creative.json()
        self.assertEqual(len(c_data["variants"]), 2)

        # 3. Inbound closer chat endpoint
        resp_chat = self.client.post(
            "/v1/growth/inbound-closer/chat",
            json={
                "session_id": str(uuid.uuid4()),
                "prospect_name": "Anita Roy",
                "prospect_contact": "anita@startupdemo.in",
                "message": "Hi, how does your AI handle WhatsApp sales closing?",
                "currency": "INR",
            },
        )
        self.assertEqual(resp_chat.status_code, 200)
        chat_data = resp_chat.json()
        self.assertIn("reply", chat_data)
        self.assertEqual(chat_data["recommended_package"], "growth_all_in_one")


if __name__ == "__main__":
    unittest.main()
