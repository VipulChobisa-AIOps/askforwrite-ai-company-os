"""Test Suite for Sprint 3:
1. LLM Client Generation across Marketing, Growth Suite, and Field Verification
2. Marketing Campaign auto-dispatch upon HITL Approval (decide_approval -> APPROVED)
3. 4-Site WordPress REST Publisher Bridge (askforwrite.in, theaiscene.in, careersathi.in, edutechguide.in)
4. Direct POST /v1/seo/drafts/{id}/publish & GET /v1/seo/networks
5. Automated B2C Order Fulfillment Worker (fulfill_order & batch fulfill_pending_orders)
6. GET /v1/orders and POST /v1/orders/fulfill-pending
"""

import os
import unittest
import uuid

from fastapi.testclient import TestClient

from app.db.database import Base, SessionLocal, engine, get_db
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    MarketingCampaignRecord,
    OrderRecord,
    SeoDraftRecord,
    TaskRecord,
    TrustBlock,
)
from app.main import app
from app.services.approvals import decide_approval
from app.services.field_verification import (
    analyze_photo_evidence,
    synthesize_voice_transcript_to_crm,
)
from app.services.growth_engine import (
    generate_and_stage_blog,
    generate_creative_assets,
    generate_omnichannel_social_campaign,
    handle_inbound_sales_chat,
)
from app.services.marketing import execute_marketing_campaign
from app.services.orders import fulfill_order, fulfill_pending_orders, list_orders
from app.services.wordpress_publisher import (
    get_supported_networks,
    publish_seo_draft_to_wordpress,
)


class Sprint3LlmWordPressAndFulfillmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.manager_key = "test-manager-key-sprint3-wp-fulfillment"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        cls.client = TestClient(app)
        cls.headers = {
            "X-API-Key": cls.manager_key,
            "X-Correlation-ID": "test-sprint3-corr-001",
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

    def test_marketing_campaign_llm_and_approval_auto_dispatch(self):
        """Marketing campaign generation must call LLM for all channels and auto-dispatch upon approval."""
        idemp_key = f"idemp-mkt-{uuid.uuid4().hex[:8]}"
        res = execute_marketing_campaign(
            db=self.db,
            campaign_type="omnichannel_b2b_launch",
            target_audience="Warehouse Operations Managers",
            idempotency_key=idemp_key,
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
            agent_id="marketing_specialist",
        )

        self.assertEqual(res["status"], "PENDING_APPROVAL")
        campaign_id = res["campaign_id"]
        approval_id = res["approval_id"]

        campaign = self.db.query(MarketingCampaignRecord).filter_by(id=campaign_id).first()
        self.assertIsNotNone(campaign)
        self.assertIn("instagram", campaign.ad_copy)
        self.assertIn("facebook", campaign.ad_copy)
        self.assertIn("twitter", campaign.ad_copy)
        self.assertIn("linkedin", campaign.ad_copy)

        # Decide approval as APPROVED -> must auto-dispatch MarketingCampaignRecord
        decision_res = decide_approval(
            db=self.db,
            approval_id=approval_id,
            decision="APPROVED",
            decided_by="owner",
            reason="Ad creative approved for live ad network dispatch",
        )

        self.assertEqual(decision_res["status"], "APPROVED")
        self.assertEqual(decision_res.get("auto_executed_action"), "marketing_campaign_dispatched")

        self.db.refresh(campaign)
        self.assertEqual(campaign.status, "DISPATCHED")
        self.assertIsNotNone(campaign.decided_at)

    def test_wordpress_publisher_supported_networks(self):
        """Supported networks must include the AskforWrite authority platforms."""
        networks = get_supported_networks()
        expected = [
            "askforwrite.in",
            "askforwrite.com",
            "ask4write.com",
            "askforwrite.info",
            "shop.ask4write.com",
            "node.askforwrite.in",
        ]
        for net in expected:
            self.assertIn(net, networks)
            self.assertTrue(networks[net]["base_url"].startswith("https://"))

        # Test HTTP endpoint GET /v1/seo/networks
        resp = self.client.get("/v1/seo/networks", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("networks", data)
        self.assertEqual(data["total_networks"], len(expected))

    def test_publish_seo_draft_to_wordpress_direct_and_endpoint(self):
        """Direct WordPress publisher call must publish, log AuditLog, and seal a TrustBlock."""
        task = TaskRecord(
            id=f"task-seo-{uuid.uuid4().hex[:8]}",
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
            objective="SEO Article for AskforWrite",
            status="PENDING",
        )
        self.db.add(task)

        draft = SeoDraftRecord(
            id=f"draft-{uuid.uuid4().hex[:8]}",
            task_id=task.id,
            target_network="askforwrite.com",
            keywords=["deep learning", "multimodal ai"],
            content="# Deep Learning in 2026\n\nMultimodal foundation models are automating enterprise workflows.",
            status="DRAFT",
        )
        self.db.add(draft)
        self.db.commit()

        initial_blocks = self.db.query(TrustBlock).count()
        pub_res = publish_seo_draft_to_wordpress(
            db=self.db,
            draft_id=draft.id,
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
        )

        self.assertEqual(pub_res["status"], "PUBLISHED")
        self.assertEqual(pub_res["network"], "askforwrite.com")
        self.assertTrue(pub_res["url"].startswith("https://askforwrite.com/articles/"))
        self.assertIsNotNone(pub_res["block_hash"])

        self.db.refresh(draft)
        self.assertEqual(draft.status, "PUBLISHED")
        self.assertIsNotNone(draft.decided_at)

        new_blocks = self.db.query(TrustBlock).count()
        self.assertEqual(new_blocks, initial_blocks + 1)

        # Test HTTP endpoint POST /v1/seo/drafts/{id}/publish
        draft2 = SeoDraftRecord(
            id=f"draft-api-{uuid.uuid4().hex[:8]}",
            task_id=task.id,
            target_network="ask4write.com",
            keywords=["tech jobs", "ai careers"],
            content="# AI Career Acceleration\n\nUpskilling for autonomous agent orchestration.",
            status="DRAFT",
        )
        self.db.add(draft2)
        self.db.commit()

        api_resp = self.client.post(f"/v1/seo/drafts/{draft2.id}/publish", headers=self.headers)
        self.assertEqual(api_resp.status_code, 200)
        api_data = api_resp.json()
        self.assertEqual(api_data["status"], "PUBLISHED")
        self.assertTrue(api_data["url"].startswith("https://ask4write.com/articles/"))

    def test_seo_approval_auto_triggers_wordpress_publishing(self):
        """When an SEO draft approval is decided as APPROVED, it must auto-publish via WordPress bridge."""
        task = TaskRecord(
            id=f"task-seo-bridge-{uuid.uuid4().hex[:8]}",
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
            objective="SEO Article Auto Publish Test",
            status="PENDING",
        )
        self.db.add(task)

        draft = SeoDraftRecord(
            id=f"seo-bridge-{uuid.uuid4().hex[:8]}",
            task_id=task.id,
            target_network="shop.ask4write.com",
            keywords=["edutech", "ai tutor"],
            content="# Next Gen EduTech\nAI tutors personalized for higher education.",
            status="DRAFT",
        )
        self.db.add(draft)

        appr = ApprovalRequest(
            id=f"appr-wp-{uuid.uuid4().hex[:8]}",
            task_id=task.id,
            action="live_publishing",
            detail={"seo_draft_id": draft.id},
            idempotency_key=f"idemp-wp-{uuid.uuid4().hex[:8]}",
            request_hash=f"hash-{uuid.uuid4().hex[:8]}",
            status="PENDING",
            requested_by="seo_copilot",
        )
        self.db.add(appr)
        self.db.commit()

        draft.approval_id = appr.id
        self.db.commit()

        decision = decide_approval(
            db=self.db,
            approval_id=appr.id,
            decision="APPROVED",
            decided_by="owner",
            reason="Verified content quality for shop.ask4write.com",
        )

        self.assertEqual(decision["status"], "APPROVED")
        self.assertEqual(decision.get("auto_executed_action"), "seo_draft_published")

        self.db.refresh(draft)
        self.assertEqual(draft.status, "PUBLISHED")

        audit = (
            self.db.query(AuditLog)
            .filter_by(action="wordpress_publish", task_id=draft.task_id)
            .first()
        )
        self.assertIsNotNone(audit)

    def test_fulfill_order_llm_synthesis_and_trust_block(self):
        """Fulfill order must synthesize deliverable summary via LLM and seal a TrustBlock."""
        tx_id = f"tx_fulfill_test_{uuid.uuid4().hex[:8]}"
        task = TaskRecord(
            id=f"task-ord-{uuid.uuid4().hex[:8]}",
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
            objective="Fulfill B2C Deliverable Order",
            status="PENDING",
        )
        self.db.add(task)

        order = OrderRecord(
            transaction_id=tx_id,
            customer_email="info@askforwrite.in",
            amount=4999.0,
            currency="INR",
            status="CONFIRMED",
            task_id=task.id,
        )
        self.db.add(order)
        self.db.commit()

        initial_blocks = self.db.query(TrustBlock).count()
        res = fulfill_order(
            db=self.db,
            transaction_id=tx_id,
            fulfilled_by="fulfillment_worker",
        )

        self.assertEqual(res["status"], "FULFILLED")
        self.assertEqual(res["transaction_id"], tx_id)
        self.assertIn("deliverable_summary", res["delivery"])
        self.assertTrue(len(res["delivery"]["deliverable_summary"]) > 10)

        self.db.refresh(order)
        self.assertEqual(order.status, "FULFILLED")

        self.db.refresh(task)
        self.assertEqual(task.status, "COMPLETED")

        new_blocks = self.db.query(TrustBlock).count()
        self.assertEqual(new_blocks, initial_blocks + 1)

    def test_batch_fulfill_pending_orders_and_endpoints(self):
        """fulfill_pending_orders and endpoints GET /v1/orders & POST /v1/orders/fulfill-pending."""
        # Create 2 confirmed orders
        tx1 = f"tx_batch_1_{uuid.uuid4().hex[:8]}"
        tx2 = f"tx_batch_2_{uuid.uuid4().hex[:8]}"
        o1 = OrderRecord(
            transaction_id=tx1,
            customer_email="batch1@corp.example.com",
            amount=15000.0,
            currency="INR",
            status="CONFIRMED",
        )
        o2 = OrderRecord(
            transaction_id=tx2,
            customer_email="batch2@corp.example.com",
            amount=25000.0,
            currency="INR",
            status="CONFIRMED",
        )
        self.db.add_all([o1, o2])
        self.db.commit()

        # Test list_orders service
        all_orders = list_orders(self.db)
        self.assertGreaterEqual(len(all_orders), 2)
        confirmed_orders = list_orders(self.db, status="CONFIRMED")
        self.assertTrue(any(o["transaction_id"] == tx1 for o in confirmed_orders))
        self.assertTrue(any(o["transaction_id"] == tx2 for o in confirmed_orders))

        # Test batch fulfill endpoint POST /v1/orders/fulfill-pending
        batch_resp = self.client.post("/v1/orders/fulfill-pending", headers=self.headers)
        self.assertEqual(batch_resp.status_code, 200)
        batch_data = batch_resp.json()
        self.assertGreaterEqual(batch_data["fulfilled_count"], 2)

        # Test direct fulfill_pending_orders service with a new confirmed order
        tx_direct = f"tx_direct_{uuid.uuid4().hex[:8]}"
        o_direct = OrderRecord(
            transaction_id=tx_direct,
            customer_email="direct@corp.example.com",
            amount=9999.0,
            currency="INR",
            status="CONFIRMED",
        )
        self.db.add(o_direct)
        self.db.commit()
        direct_res = fulfill_pending_orders(self.db, limit=10)
        self.assertGreaterEqual(direct_res["fulfilled_count"], 1)
        self.assertTrue(any(o["transaction_id"] == tx_direct for o in direct_res["orders"]))

        # Test GET /v1/orders endpoint
        orders_resp = self.client.get("/v1/orders?status=FULFILLED", headers=self.headers)
        self.assertEqual(orders_resp.status_code, 200)
        orders_data = orders_resp.json()
        self.assertIn("orders", orders_data)
        fulfilled_txs = [o["transaction_id"] for o in orders_data["orders"]]
        self.assertIn(tx1, fulfilled_txs)
        self.assertIn(tx2, fulfilled_txs)
        self.assertIn(tx_direct, fulfilled_txs)

    def test_growth_suite_and_field_verification_llm_enrichment(self):
        """Growth Suite and Field Verification must provide AI-synthesized fields alongside deterministic keys."""
        # 1. Creative Assets
        creatives = generate_creative_assets(
            product_name="AskforWrite Growth Suite",
            target_audience="E-commerce Founders",
        )
        self.assertIn("ai_creative_synthesis", creatives)
        self.assertIn("variants", creatives)
        self.assertEqual(len(creatives["variants"]), 3)

        # 2. Staged Blog
        blog = generate_and_stage_blog(
            product_name="AskforWrite OS",
            target_audience="B2B Executives",
            keywords=["ai company os", "autonomous ops"],
        )
        self.assertIn("ai_editorial_synthesis", blog)
        self.assertIn("schema_json_ld", blog)
        self.assertIn("markdown_body", blog)

        # 3. Omnichannel Social Campaign
        social = generate_omnichannel_social_campaign(
            product_name="AskforWrite OS",
            target_audience="Founders",
            keywords=["ai growth engine"],
        )
        self.assertIn("ai_campaign_pitch", social)
        self.assertIn("instagram_meta", social)
        self.assertIn("linkedin", social)
        self.assertIn("google_search_ads", social)

        # 4. Inbound Sales Closer
        closer = handle_inbound_sales_chat(
            db=self.db,
            session_id=f"sess-{uuid.uuid4().hex[:8]}",
            prospect_name="Anita Roy",
            prospect_contact="+919876543210",
            message="How much does your growth package cost and can you send a checkout link?",
            currency="INR",
        )
        self.assertIn("ai_synthesized_pitch", closer)
        self.assertIn("reply", closer)
        self.assertIn("checkout_link", closer)
        self.assertTrue(closer["checkout_link_attached"])

        # 5. Field Verification Photo Evidence
        status, photo_analysis = analyze_photo_evidence(
            photo_data="A" * 120,
            expected_tags=["storefront", "shelf_inventory"],
        )
        self.assertEqual(status, "VERIFIED")
        self.assertIn("ai_inspection_notes", photo_analysis)
        self.assertIn("detected_tags", photo_analysis)

        # 6. Field Verification Voice Debrief
        voice_summary = synthesize_voice_transcript_to_crm(
            raw_text="Met with the regional manager. Client was very happy and confirmed an order for 50 units."
        )
        self.assertIn("meeting_summary", voice_summary)
        self.assertEqual(voice_summary["client_sentiment"], "POSITIVE")
        self.assertEqual(len(voice_summary["orders_booked"]), 1)
        self.assertEqual(voice_summary["orders_booked"][0]["quantity"], 50)


if __name__ == "__main__":
    unittest.main()
