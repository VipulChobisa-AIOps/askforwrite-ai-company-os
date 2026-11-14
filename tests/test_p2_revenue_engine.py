"""Comprehensive test suite for P2 First Customer Acquisition & Revenue Engine.

Tests are isolated using an in-memory SQLite StaticPool DB and strict simulation
mode (`APP_ENV=development`), ensuring zero live emails, zero live web scraping,
and zero external payment charges occur during test execution.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import OrganizationRecord, P2PaymentReconciliationRecord
from app.main import app


class P2CommercialRevenueEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._prev_env = {
            k: os.environ.get(k)
            for k in ("APP_ENV", "OWNER_API_KEY", "MANAGER_API_KEY", "RAZORPAY_WEBHOOK_SECRET", "ALLOW_LIVE_SIDE_EFFECTS")
        }
        cls.owner_key = "test-p2-owner-key-must-be-32-chars!"
        cls.manager_key = "test-p2-manager-key-must-be-32ch!"
        os.environ["APP_ENV"] = "development"
        os.environ["ALLOW_LIVE_SIDE_EFFECTS"] = "false"
        os.environ["OWNER_API_KEY"] = cls.owner_key
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test-rzp-webhook-secret-p2"

        cls.test_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.test_engine)
        Base.metadata.create_all(bind=cls.test_engine)
        cls.client = TestClient(app)
        cls.owner_headers = {"X-API-Key": cls.owner_key, "X-Correlation-ID": "p2-test-owner"}
        cls.manager_headers = {"X-API-Key": cls.manager_key, "X-Correlation-ID": "p2-test-mgr"}

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=cls.test_engine)
        for k, v in cls._prev_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=self.test_engine)
        Base.metadata.create_all(bind=self.test_engine)
        self.db = self.TestSessionLocal()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()

    def _ingest_real_agency(
        self,
        *,
        company: str = "RankCraft SEO Jaipur",
        website: str = "https://rankcraftjaipur.in",
        email: str = "founder@rankcraftjaipur.in",
    ) -> dict:
        resp = self.client.post(
            "/v1/commercial/prospects/ingest",
            headers=self.manager_headers,
            json={
                "company": company,
                "website": website,
                "location": "Jaipur, Rajasthan, India",
                "source_url": f"{website.rstrip('/')}/services",
                "business_category": "Digital Marketing & SEO Agency",
                "source_type": "manual_owner_curation",
                "public_email": email,
                "public_contact_verified": True,
                "contact_verification_method": "public_contact_page",
                "actual_services": ["Technical SEO", "Content Marketing", "Local SEO"],
                "target_customers": ["Indian B2B SaaS", "SME Clinics"],
                "visible_seo_content_activity": ["Monthly agency blog"],
                "publicly_verifiable_needs": ["Irregular blog cadence", "Missing Schema.org JSON-LD"],
                "research_claims": [
                    {
                        "category": "service_offering",
                        "statement": "Lists SEO retainers and content writing on /services page.",
                        "classification": "VERIFIED_FACT",
                        "source_url": f"{website.rstrip('/')}/services",
                    }
                ],
                "inspect_live_website": False,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def test_01_catalog_offer_contract_and_prospect_dedup_qualification(self) -> None:
        # 1. Verify catalog pilot contract directly matches catalog truth
        offer = self.client.get("/v1/commercial/offer/managed_seo_content_pilot", headers=self.manager_headers)
        self.assertEqual(offer.status_code, 200)
        odata = offer.json()
        self.assertEqual(odata["price_inr"], 4999)
        self.assertEqual(odata["price_usd"], 59)
        self.assertEqual(odata["billing_type"], "managed_pilot_14d")
        self.assertGreaterEqual(len(odata["non_guarantees"]), 2)

        # 2. Reject synthetic / non-commercial fixture domains cleanly
        bad_resp = self.client.post(
            "/v1/commercial/prospects/ingest",
            headers=self.manager_headers,
            json={
                "company": "Synthetic Example Agency",
                "website": "https://fakeagency.example.com",
                "location": "Mumbai, India",
                "source_url": "https://directory.example/list",
                "source_type": "test_fixtures",
            },
        )
        self.assertEqual(bad_resp.status_code, 422)

        # 3. Ingest genuine India SEO agency + check 6-criterion breakdown
        ag = self._ingest_real_agency()
        self.assertFalse(ag["is_synthetic"])
        self.assertEqual(ag["pipeline_status"], "QUALIFIED")
        self.assertGreaterEqual(ag["qualification_score"], 60.0)
        criteria = ag["qualification_breakdown"]["criteria"]
        for key in ("icp_fit", "need_evidence", "activity_website_quality", "service_fit", "contact_validity", "evidence_freshness"):
            self.assertIn(key, criteria)

        # 4. Deduplication across www./URL and normalized company identity
        dup = self._ingest_real_agency(
            company="RankCraft SEO Jaipur LLP",
            website="https://www.rankcraftjaipur.in/about",
            email="founder@rankcraftjaipur.in",
        )
        self.assertEqual(dup["lead_id"], ag["lead_id"])
        listed = self.client.get("/v1/commercial/prospects", headers=self.manager_headers).json()
        self.assertEqual(listed["count"], 1)

        # 5. Configurable requalification criteria weights
        req = self.client.post(
            f"/v1/commercial/prospects/{ag['lead_id']}/requalify",
            headers=self.manager_headers,
            json={"min_qualify_score": 50.0, "weights": {"icp_fit": 30, "evidence_of_need": 25}},
        )
        self.assertEqual(req.status_code, 200)
        self.assertEqual(req.json()["lead_id"], ag["lead_id"])

        # 6. Live web discovery is honestly BLOCKED in non-production/unverified mode
        disc = self.client.post(
            "/v1/commercial/prospects/discover",
            headers=self.owner_headers,
            json={"query": "SEO agency Bengaluru India", "limit": 3},
        )
        self.assertEqual(disc.status_code, 200)
        self.assertEqual(disc.json()["status"], "BLOCKED")
        self.assertEqual(disc.json()["discovered"], [])

    def test_02_brief_outreach_honesty_hitl_simulation_separation_and_suppression(self) -> None:
        ag = self._ingest_real_agency(
            company="Deccan Digital Media",
            website="https://deccandigital.in",
            email="hello@deccandigital.in",
        )
        lead_id = ag["lead_id"]

        # 1. Account intelligence brief strictly separates facts, inferences, and assumptions
        brief_resp = self.client.post(f"/v1/commercial/prospects/{lead_id}/brief", headers=self.manager_headers)
        self.assertEqual(brief_resp.status_code, 200)
        brief = brief_resp.json()
        self.assertTrue(brief["verified_facts"])
        self.assertTrue(brief["reasonable_inferences"])
        self.assertTrue(brief["unverified_assumptions"])
        self.assertTrue(brief["suggested_discovery_questions"])

        # 2. Honesty validator blocks fabricated call references, #1 guarantees, and invented discounts
        for bad_line in (
            "Following up as we discussed on our call yesterday about SEO.",
            "We guarantee #1 Google ranking within 14 days for every client.",
            "Claim your special 50% off expires today pilot offer.",
        ):
            bad_out = self.client.post(
                "/v1/commercial/outreach/prepare",
                headers=self.manager_headers,
                json={"lead_id": lead_id, "recipient_email": "hello@deccandigital.in", "body_override": bad_line},
            )
            self.assertEqual(bad_out.status_code, 422, f"Should reject fabricated claim: {bad_line}")

        # 3. Prepare valid outreach -> awaits Owner HITL approval
        prep = self.client.post(
            "/v1/commercial/outreach/prepare",
            headers=self.manager_headers,
            json={"lead_id": lead_id, "recipient_email": "hello@deccandigital.in", "recipient_name": "Aarav"},
        )
        self.assertEqual(prep.status_code, 200, prep.text)
        odata = prep.json()
        self.assertEqual(odata["status"], "PENDING_APPROVAL")
        self.assertFalse(odata["external_sent"])
        outreach_id = odata["outreach_id"]
        approval_id = odata["approval_id"]

        # Duplicate outreach without follow-up permission is blocked
        dup_prep = self.client.post(
            "/v1/commercial/outreach/prepare",
            headers=self.manager_headers,
            json={"lead_id": lead_id, "recipient_email": "hello@deccandigital.in"},
        )
        self.assertEqual(dup_prep.status_code, 422)

        # Dispatch BEFORE approval is strictly forbidden
        unauth_disp = self.client.post(
            f"/v1/commercial/outreach/{outreach_id}/dispatch",
            headers=self.owner_headers,
        )
        self.assertEqual(unauth_disp.status_code, 403)

        # 4. Owner approves via HITL endpoint (marks APPROVED without faking external send)
        appr = self.client.post(
            f"/v1/approvals/{approval_id}/decision",
            headers=self.owner_headers,
            json={"decision": "APPROVED", "reason": "Verified factual draft"},
        )
        self.assertEqual(appr.status_code, 200, appr.text)

        # 5. Dispatch in SIMULATION environment records SIMULATED_SENT, never counting as live send
        disp = self.client.post(
            f"/v1/commercial/outreach/{outreach_id}/dispatch",
            headers=self.owner_headers,
        )
        self.assertEqual(disp.status_code, 200, disp.text)
        ddata = disp.json()
        self.assertEqual(ddata["status"], "SIMULATED_SENT")
        self.assertFalse(ddata["external_sent"])
        self.assertEqual(ddata["delivery_mode"], "SIMULATED")

        cc = self.client.get("/v1/commercial/control-centre", headers=self.manager_headers).json()
        self.assertEqual(cc["verified_commercial_metrics"]["outreach_sent"], 0)
        self.assertEqual(cc["simulation_and_test_metrics"]["simulated_outreach_sent"], 1)

        # 6. Suppression / Opt-out persists in DB and blocks all future outreach
        unsub = self.client.post(
            "/v1/outreach/unsubscribe",
            json={"email": "hello@deccandigital.in", "lead_id": lead_id},
        )
        self.assertEqual(unsub.status_code, 200, unsub.text)
        blocked_prep = self.client.post(
            "/v1/commercial/outreach/prepare",
            headers=self.manager_headers,
            json={"lead_id": lead_id, "recipient_email": "hello@deccandigital.in", "allow_follow_up": True},
        )
        self.assertEqual(blocked_prep.status_code, 422)

    def test_03_end_to_end_discovery_proposal_settlement_onboarding_delivery_and_renewal(self) -> None:
        ag = self._ingest_real_agency(
            company="Narmada Search Studio",
            website="https://narmadasearch.in",
            email="kavya@narmadasearch.in",
        )
        lead_id = ag["lead_id"]

        # 1. Response + discovery notes transition lead cleanly to DISCOVERY
        resp_log = self.client.post(
            f"/v1/commercial/pipeline/{lead_id}/responses",
            headers=self.manager_headers,
            json={
                "summary": "Interested in testing the 14-day pilot for 2 B2B SaaS clients.",
                "source": "email_reply",
                "sentiment": "interested",
                "discovery_notes": "Team needs consistent technical audits and schema-marked editorial drafts.",
            },
        )
        self.assertEqual(resp_log.status_code, 200, resp_log.text)
        self.assertEqual(resp_log.json()["pipeline_status"], "DISCOVERY")

        # 2. Generate catalog-backed multi-clause proposal (HITL gated)
        prop = self.client.post(
            "/v1/commercial/proposals",
            headers=self.manager_headers,
            json={
                "lead_id": lead_id,
                "sku_key": "managed_seo_content_pilot",
                "currency": "INR",
                "custom_problem_statement": "Confirmed agency bottleneck delivering schema-verified B2B articles on time.",
            },
        )
        self.assertEqual(prop.status_code, 200, prop.text)
        pdata = prop.json()
        self.assertEqual(pdata["status"], "AWAITING_OWNER_APPROVAL")
        self.assertEqual(pdata["pricing"]["total_amount"], 4999.0)
        proposal_id = pdata["proposal_id"]

        # Sharing & checkout blocked until Owner approves proposal
        self.assertEqual(
            self.client.post(f"/v1/commercial/proposals/{proposal_id}/share", headers=self.owner_headers).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/v1/commercial/proposals/{proposal_id}/checkout",
                headers=self.owner_headers,
                json={"provider": "afw_directpay", "customer_email": "kavya@narmadasearch.in"},
            ).status_code,
            403,
        )

        # Owner approves proposal -> shares -> generates AFW DirectPay checkout
        self.assertEqual(
            self.client.post(
                f"/v1/approvals/{pdata['approval_id']}/decision",
                headers=self.owner_headers,
                json={"decision": "APPROVED", "reason": "Catalog scope & price verified"},
            ).status_code,
            200,
        )
        shared = self.client.post(f"/v1/commercial/proposals/{proposal_id}/share", headers=self.owner_headers)
        self.assertEqual(shared.status_code, 200)
        self.assertEqual(shared.json()["status"], "SHARED")

        chk = self.client.post(
            f"/v1/commercial/proposals/{proposal_id}/checkout",
            headers=self.owner_headers,
            json={
                "provider": "afw_directpay",
                "customer_email": "kavya@narmadasearch.in",
                "customer_name": "Kavya Nair",
                "preferred_rail": "upi_direct",
            },
        )
        self.assertEqual(chk.status_code, 200, chk.text)
        cdata = chk.json()
        self.assertFalse(cdata["customer_activated"])
        session_id = cdata["checkout_reference"]

        # Checkout creation MUST NOT activate customer or count revenue
        cc_before = self.client.get("/v1/commercial/control-centre", headers=self.manager_headers).json()
        self.assertEqual(cc_before["verified_commercial_metrics"]["verified_payments"], 0)
        self.assertEqual(cc_before["verified_commercial_metrics"]["verified_revenue_inr"], 0.0)

        # 3. Buyer submits UTR reference first -> status AWAITING_OWNER_CONFIRMATION -> Owner confirms -> WON + Engagement
        sub_utr = self.client.post(
            f"/v1/pay/{session_id}/verify",
            json={"rail": "upi_direct", "proof_reference": "412345678901"},
        )
        self.assertEqual(sub_utr.status_code, 200, sub_utr.text)
        settled = self.client.post(f"/v1/pay/{session_id}/confirm-owner", headers=self.owner_headers)
        self.assertEqual(settled.status_code, 200, settled.text)

        engs = self.client.get("/v1/commercial/engagements", headers=self.manager_headers).json()
        self.assertEqual(engs["count"], 1)
        eng = engs["engagements"][0]
        engagement_id = eng["engagement_id"]
        org_id = eng["org_id"]
        self.assertEqual(eng["status"], "ONBOARDING_PENDING_INPUTS")
        self.assertIn("seo_content_automation", eng["entitlements"])

        # Pipeline moved cleanly to WON & Control Centre counts INR 4,999 verified revenue
        cc_after = self.client.get("/v1/commercial/control-centre", headers=self.manager_headers).json()
        self.assertEqual(cc_after["verified_commercial_metrics"]["verified_payments"], 1)
        self.assertEqual(cc_after["verified_commercial_metrics"]["verified_revenue_inr"], 4999.0)
        self.assertEqual(cc_after["verified_commercial_metrics"]["active_paying_customers"], 1)

        # 4. Delivery blocked before required onboarding inputs
        self.assertEqual(
            self.client.post(f"/v1/commercial/engagements/{engagement_id}/deliver", headers=self.manager_headers).status_code,
            422,
        )

        # Submit onboarding inputs -> run P1 pilot delivery workflow (staged, NOT marked complete prematurely)
        onb = self.client.post(
            f"/v1/commercial/engagements/{engagement_id}/onboarding",
            headers=self.manager_headers,
            json={
                "target_domain": "narmadasearch.in",
                "cms_delivery_mode": "markdown_html_export",
                "priority_topics": ["Technical SEO Audit for Indian SaaS", "Schema.org JSON-LD Guide"],
            },
        )
        self.assertEqual(onb.status_code, 200, onb.text)
        self.assertEqual(onb.json()["status"], "ONBOARDING_READY")

        deliv = self.client.post(f"/v1/commercial/engagements/{engagement_id}/deliver", headers=self.manager_headers)
        self.assertEqual(deliv.status_code, 200, deliv.text)
        d_json = deliv.json()
        self.assertEqual(d_json["status"], "DELIVERY_IN_PROGRESS")
        self.assertEqual(d_json["deliverables"]["stage_status"], "STAGED_FOR_REVIEW")
        self.assertTrue(d_json["workflow_run_id"])
        for artifact_key in ("seo_audit_report", "keyword_cluster", "article_1", "article_2", "schema_json_ld"):
            self.assertIn(artifact_key, d_json["deliverables"])

        # Confirm delivery completed -> capture genuine feedback & honest renewal recommendation
        comp = self.client.post(
            f"/v1/commercial/engagements/{engagement_id}/complete-delivery",
            headers=self.owner_headers,
            json={"delivery_channel_proof": "Delivered Markdown & JSON-LD bundle via portal"},
        )
        self.assertEqual(comp.status_code, 200, comp.text)
        self.assertEqual(comp.json()["status"], "DELIVERY_COMPLETED")

        fb = self.client.post(
            f"/v1/commercial/engagements/{engagement_id}/feedback-renewal",
            headers=self.manager_headers,
            json={
                "rating": 5,
                "comments": "Audit uncovered real canonical issues and both schema articles are ready for publishing.",
                "interested_in_renewal": True,
            },
        )
        self.assertEqual(fb.status_code, 200, fb.text)
        fb_json = fb.json()
        self.assertEqual(fb_json["status"], "RENEWAL_RECOMMENDED")
        self.assertTrue(fb_json["renewal_recommendation"]["auto_charge_disabled"])
        self.assertTrue(fb_json["renewal_recommendation"]["approval_required_for_charge"])

        # 5. Verify 12-step real-world acceptance checklist & registry agent execution
        chk_list = self.client.get("/v1/commercial/acceptance-checklist", headers=self.manager_headers).json()
        self.assertEqual(chk_list["total_steps"], 12)
        self.assertEqual(chk_list["summary"]["NOT_TESTED"], 12)

        upd_step = self.client.post(
            "/v1/commercial/acceptance-checklist/2",
            headers=self.owner_headers,
            json={"verification_status": "SANDBOX_VERIFIED", "evidence_summary": "Verified INR 4999 pilot SKU"},
        )
        self.assertEqual(upd_step.status_code, 200)
        self.assertEqual(upd_step.json()["verification_status"], "SANDBOX_VERIFIED")

        ag_exec = self.client.post(
            "/v1/registry/agents/market_research_agent/execute",
            headers=self.owner_headers,
            json={"input": {"sku_key": "managed_seo_content_pilot"}},
        )
        self.assertEqual(ag_exec.status_code, 200, ag_exec.text)
        self.assertEqual(ag_exec.json()["result"]["offer_contract"]["price_inr"], 4999)

        # Ensure organization is active paid prior to refund test
        org_row = self.db.get(OrganizationRecord, org_id)
        self.assertIsNotNone(org_row)
        self.assertTrue(org_row.is_active)

    def test_04_razorpay_webhook_settlement_idempotency_retry_and_refund_revocation(self) -> None:
        ag = self._ingest_real_agency(
            company="Kaveri Growth Media",
            website="https://kaverigrowth.in",
            email="rohan@kaverigrowth.in",
        )
        lead_id = ag["lead_id"]

        prop = self.client.post(
            "/v1/commercial/proposals",
            headers=self.manager_headers,
            json={"lead_id": lead_id, "sku_key": "managed_seo_content_pilot", "currency": "INR"},
        ).json()
        self.client.post(
            f"/v1/approvals/{prop['approval_id']}/decision",
            headers=self.owner_headers,
            json={"decision": "APPROVED", "reason": "Approved"},
        )
        chk = self.client.post(
            f"/v1/commercial/proposals/{prop['proposal_id']}/checkout",
            headers=self.owner_headers,
            json={"provider": "razorpay", "customer_email": "rohan@kaverigrowth.in"},
        ).json()
        recon_id = chk["reconciliation_id"]

        # 1. Simulate unverified / underpaid retry queue entry -> blocked retry
        recon = self.db.get(P2PaymentReconciliationRecord, recon_id)
        recon.verification_state = "RETRY_NEEDED"
        recon.received_amount = 100.0  # underpaid compared to INR 4,999
        self.db.add(recon)
        self.db.commit()

        retry_blocked = self.client.post(
            f"/v1/commercial/reconciliation/{recon_id}/retry",
            headers=self.owner_headers,
        )
        self.assertEqual(retry_blocked.status_code, 200)
        self.assertEqual(retry_blocked.json()["status"], "RETRY_BLOCKED_UNVERIFIED_AMOUNT")

        # 2. Signed Razorpay payment.captured webhook activates customer idempotently
        secret = os.environ["RAZORPAY_WEBHOOK_SECRET"]
        payment_id = f"pay_p2_{uuid.uuid4().hex[:12]}"
        cap_payload = json.dumps(
            {
                "event": "payment.captured",
                "event_id": f"evt_cap_{payment_id}",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": payment_id,
                            "order_id": chk["checkout_reference"],
                            "amount": 499900,
                            "currency": "INR",
                            "email": "rohan@kaverigrowth.in",
                            "notes": {
                                "package_key": "managed_seo_content_pilot",
                                "company_name": "Kaveri Growth Media",
                                "email": "rohan@kaverigrowth.in",
                            },
                        }
                    }
                },
            }
        ).encode("utf-8")
        cap_sig = hmac.new(secret.encode("utf-8"), cap_payload, hashlib.sha256).hexdigest()

        w1 = self.client.post(
            "/v1/webhooks/payment",
            content=cap_payload,
            headers={"Content-Type": "application/json", "x-razorpay-signature": cap_sig},
        )
        self.assertEqual(w1.status_code, 200, w1.text)
        w1_json = w1.json()
        self.assertEqual(w1_json["p2_reconciliation"]["status"], "ACTIVATION_COMPLETED")
        org_id = w1_json["p2_reconciliation"]["activated_org_id"]

        # Replay exact same webhook event -> safely deduplicated
        w_dup = self.client.post(
            "/v1/webhooks/payment",
            content=cap_payload,
            headers={"Content-Type": "application/json", "x-razorpay-signature": cap_sig},
        )
        self.assertEqual(w_dup.status_code, 200)
        self.assertEqual(w_dup.json()["status"], "duplicate")

        eng_id = w1_json["p2_reconciliation"]["engagement_id"]
        self.client.post(
            f"/v1/commercial/engagements/{eng_id}/onboarding",
            headers=self.manager_headers,
            json={"target_domain": "kaverigrowth.in", "priority_topics": ["B2B SEO"]},
        )

        # 3. Full Razorpay refund.processed revokes engagement, downgrades org, & blocks delivery
        refund_payload = json.dumps(
            {
                "event": "refund.processed",
                "event_id": f"evt_rfnd_{payment_id}",
                "payload": {
                    "refund": {
                        "entity": {
                            "id": f"rfnd_{uuid.uuid4().hex[:10]}",
                            "payment_id": payment_id,
                            "amount": 499900,
                            "currency": "INR",
                        }
                    }
                },
            }
        ).encode("utf-8")
        rfnd_sig = hmac.new(secret.encode("utf-8"), refund_payload, hashlib.sha256).hexdigest()
        w_rfnd = self.client.post(
            "/v1/webhooks/payment",
            content=refund_payload,
            headers={"Content-Type": "application/json", "x-razorpay-signature": rfnd_sig},
        )
        self.assertEqual(w_rfnd.status_code, 200, w_rfnd.text)

        self.db.expire_all()
        revoked_org = self.db.get(OrganizationRecord, org_id)
        self.assertEqual(revoked_org.tier, "free")
        self.assertEqual((revoked_org.metadata_json or {}).get("entitled_capabilities"), [])

        # Delivery MUST fail after refund revocation
        blocked_deliv = self.client.post(
            f"/v1/commercial/engagements/{eng_id}/deliver",
            headers=self.manager_headers,
        )
        self.assertEqual(blocked_deliv.status_code, 422)


if __name__ == "__main__":
    unittest.main()
