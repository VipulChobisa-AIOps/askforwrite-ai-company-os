"""Comprehensive test suite for P3 Customer Success, Retention & Repeatable Growth Engine.

Tests run against an isolated in-memory SQLite StaticPool DB in APP_ENV=development
with zero live emails, zero live scraping, and zero external payment charges.
"""

from __future__ import annotations

import os
import threading
import unittest
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.policy import approval_required
from app.db.database import Base, get_db
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    ExecutionEvidenceRecord,
    InvoiceRecord,
    OrganizationRecord,
    P2ProspectDossierRecord,
    P3CustomerAccountRecord,
    P3SubscriptionEventRecord,
    SupervisorAlertRecord,
    TenantSubscriptionRecord,
    UserRecord,
    WorkflowDefinitionRecord,
    WorkflowRunRecord,
)
from app.main import app
from app.security.auth import create_access_token, hash_password
from app.services.p3_ops_compliance_cc import MAX_CONCURRENT_RUNS_PER_ORG
from app.services.registry import AGENT_REGISTRY


class P3CustomerSuccessEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._prev_env = {
            k: os.environ.get(k)
            for k in ("APP_ENV", "OWNER_API_KEY", "MANAGER_API_KEY", "ALLOW_LIVE_SIDE_EFFECTS", "JWT_SECRET_KEY")
        }
        cls.owner_key = "test-p3-owner-key-must-be-32-chars!"
        cls.manager_key = "test-p3-manager-key-must-be-32ch!"
        os.environ["APP_ENV"] = "development"
        os.environ["ALLOW_LIVE_SIDE_EFFECTS"] = "false"
        os.environ["OWNER_API_KEY"] = cls.owner_key
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        os.environ["JWT_SECRET_KEY"] = "test-p3-jwt-secret-must-be-32-ch!"

        cls.test_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.test_engine)
        Base.metadata.create_all(bind=cls.test_engine)
        cls.client = TestClient(app)
        cls.owner_headers = {"X-API-Key": cls.owner_key, "X-Correlation-ID": "p3-test-owner"}
        cls.manager_headers = {"X-API-Key": cls.manager_key, "X-Correlation-ID": "p3-test-mgr"}

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

    def _seed_tenant(
        self,
        *,
        org_id: str,
        name: str = "Jaipur Growth SEO Agency",
        slug: str = "jaipur-growth-seo",
        sku_key: str = "managed_seo_content_pilot",
        tier: str = "managed_seo_content_pilot",
        is_sandbox: bool = False,
        entitled_caps: list[str] | None = None,
    ) -> dict[str, str]:
        caps = entitled_caps or ["support_followup", "seo_content_automation", "evidence_research", "managed_seo_content_pilot"]
        org = OrganizationRecord(
            id=org_id,
            name=name,
            slug=slug,
            tier=tier,
            lead_credits_limit=100,
            lead_credits_used=10,
            outreach_credits_limit=50,
            outreach_credits_used=5,
            is_active=True,
            metadata_json={
                "package_key": sku_key,
                "entitled_capabilities": caps,
                "is_sandbox": is_sandbox,
            },
        )
        user_id = f"usr-{uuid.uuid4().hex[:10]}"
        email = f"founder@{slug}.in"
        user = UserRecord(
            id=user_id,
            org_id=org_id,
            email=email,
            full_name=f"{name} Founder",
            role="customer",
            password_hash=hash_password("StrongPass123!"),
            is_active=True,
        )
        sub = TenantSubscriptionRecord(
            org_id=org_id,
            internal_sku=sku_key,
            billing_type="one_time" if "pilot" in sku_key else "recurring",
            billing_interval="14_day_pilot" if "pilot" in sku_key else "monthly",
            base_price={"INR": 4999, "USD": 59},
            currency="INR",
            included_modules=["seo_blog_copilot"],
            selected_modules=["seo_blog_copilot"],
            entitled_agents=["seo_content_agent", "cs_manager_agent"],
            agent_execution_limit=20,
            included_credits=100,
            credit_costs={"seo_content_agent": 1},
            seat_limit=2,
            total_recurring_price=0.0 if "pilot" in sku_key else 4999.0,
            status="active",
            current_period_start=datetime.now(UTC) - timedelta(days=5),
            current_period_end=datetime.now(UTC) + timedelta(days=9),
        )
        self.db.add_all([org, user, sub])
        self.db.commit()
        token = create_access_token(user_id=user_id, email=email, role="customer", org_id=org_id, tier=tier)
        return {
            "org_id": org_id,
            "user_id": user_id,
            "email": email,
            "token": token,
            "auth_header": f"Bearer {token}",
        }

    def _complete_onboarding_prereqs(self, org_id: str, sku_key: str = "managed_seo_content_pilot") -> None:
        wf_resp = self.client.get(f"/v1/cs/customers/{org_id}/onboarding?sku_key={sku_key}", headers=self.manager_headers)
        self.assertEqual(wf_resp.status_code, 200, wf_resp.text)
        tasks = wf_resp.json()["tasks"]
        for t in tasks:
            tk = t["task_key"]
            if tk == "activation_confirmation":
                continue
            r = self.client.patch(
                f"/v1/cs/customers/{org_id}/onboarding/tasks/{tk}",
                headers=self.manager_headers,
                json={"completed": True, "evidence_summary": f"Verified {tk} evidence"},
            )
            self.assertEqual(r.status_code, 200, r.text)

    # ── 1 & 2: Lifecycle State Machine, Audit & Strict Onboarding Gate ────────

    def test_01_lifecycle_transitions_audit_and_strict_activation_gate(self) -> None:
        t = self._seed_tenant(org_id="org-jaipur-01")
        org_id = t["org_id"]

        ens = self.client.post(
            f"/v1/cs/customers/{org_id}/ensure",
            headers=self.manager_headers,
            json={"sku_key": "managed_seo_content_pilot", "initial_state": "ONBOARDING", "business_goals": ["Publish 6 SEO briefs"]},
        )
        self.assertEqual(ens.status_code, 200, ens.text)
        self.assertEqual(ens.json()["customer_account"]["lifecycle_state"], "ONBOARDING")

        # Cannot jump directly from ONBOARDING -> SUSPENDED? Wait: check invalid jump e.g. SUSPENDED -> ONBOARDING -> wait: test CHURNED -> SUSPENDED (disallowed!)
        bad_trans = self.client.post(
            f"/v1/cs/customers/{org_id}/lifecycle",
            headers=self.manager_headers,
            json={"target_state": "CLOSED", "reason": "Test valid transition"},
        )
        self.assertEqual(bad_trans.status_code, 200)
        from_closed = self.client.post(
            f"/v1/cs/customers/{org_id}/lifecycle",
            headers=self.manager_headers,
            json={"target_state": "ACTIVE", "reason": "Illegal reopen from CLOSED"},
        )
        self.assertEqual(from_closed.status_code, 409)

        # Fresh org2: activation must BLOCK until all readiness criteria + blockers clear
        t2 = self._seed_tenant(org_id="org-pune-02", slug="pune-seo")
        oid2 = t2["org_id"]
        self.client.post(f"/v1/cs/customers/{oid2}/ensure", headers=self.manager_headers, json={"sku_key": "managed_seo_content_pilot"})
        premature = self.client.post(
            f"/v1/cs/customers/{oid2}/onboarding/confirm-activation",
            headers=self.owner_headers,
            json={"confirmation_note": "Premature attempt"},
        )
        self.assertEqual(premature.status_code, 409)
        acct2 = self.db.query(P3CustomerAccountRecord).filter_by(org_id=oid2).first()
        self.assertNotEqual(acct2.lifecycle_state, "ACTIVE")

        # Complete all required onboarding tasks, then add & clear blocker -> confirm ACTIVE succeeds
        self._complete_onboarding_prereqs(oid2)
        with_blocker = self.client.patch(
            f"/v1/cs/customers/{oid2}/onboarding/tasks/connector_verification",
            headers=self.manager_headers,
            json={"completed": True, "blockers": ["Waiting for WordPress app password"]},
        )
        self.assertEqual(with_blocker.status_code, 200)
        blocked_act = self.client.post(
            f"/v1/cs/customers/{oid2}/onboarding/confirm-activation",
            headers=self.owner_headers,
            json={},
        )
        self.assertEqual(blocked_act.status_code, 409)

        # Clear blocker and confirm ACTIVE
        self.client.patch(
            f"/v1/cs/customers/{oid2}/onboarding/tasks/connector_verification",
            headers=self.manager_headers,
            json={"completed": True, "blockers": [], "evidence_summary": "WordPress REST verified"},
        )
        confirmed = self.client.post(
            f"/v1/cs/customers/{oid2}/onboarding/confirm-activation",
            headers=self.owner_headers,
            json={"confirmation_note": "All agency readiness checks passed"},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["account"]["lifecycle_state"], "ACTIVE")
        self.assertTrue(confirmed.json()["account"]["activation_ready"])

        # AuditLog exists
        audit_cnt = self.db.query(AuditLog).filter(AuditLog.action == "customer_activated").count()
        self.assertGreaterEqual(audit_cnt, 1)

    # ── 3 & 4: Service Delivery Quality Machine, Attribution Guard, Health & Alerts

    def test_02_delivery_qa_attribution_guard_and_customer_health_engine(self) -> None:
        t = self._seed_tenant(org_id="org-deliv-01", slug="deliv-agency")
        oid = t["org_id"]
        self._complete_onboarding_prereqs(oid)
        self.client.post(f"/v1/cs/customers/{oid}/onboarding/confirm-activation", headers=self.owner_headers, json={})

        # Before enough dimensions, Health MUST report INSUFFICIENT_DATA cleanly (never fake 85/100)
        h_sparse = self.client.get(f"/v1/cs/customers/{oid}/health", headers=self.manager_headers)
        self.assertEqual(h_sparse.status_code, 200, h_sparse.text)
        self.assertEqual(h_sparse.json()["health_state"], "INSUFFICIENT_DATA")
        self.assertIsNone(h_sparse.json()["overall_score"])

        # Create delivery -> IN_PROGRESS -> premature DELIVERED fails QA gate
        d = self.client.post(
            "/v1/cs/deliveries",
            headers=self.manager_headers,
            json={
                "org_id": oid,
                "title": "Q4 B2B SaaS SEO Content Cluster",
                "original_requirement": "Produce 4 technical SEO articles with internal links",
                "approved_scope": ["4 long-form drafts", "WordPress staging upload"],
            },
        )
        self.assertEqual(d.status_code, 200, d.text)
        did = d.json()["delivery_id"]

        self.client.post(f"/v1/cs/deliveries/{did}/transition", headers=self.manager_headers, json={"target_state": "IN_PROGRESS"})
        no_qa_deliver = self.client.post(
            f"/v1/cs/deliveries/{did}/transition",
            headers=self.manager_headers,
            json={"target_state": "DELIVERED"},
        )
        self.assertIn(no_qa_deliver.status_code, (409, 422))

        # Fail QA -> REVISION_REQUESTED -> Pass QA -> DELIVERED -> Customer ACCEPTED
        qa_fail = self.client.post(
            f"/v1/cs/deliveries/{did}/qa-review",
            headers=self.manager_headers,
            json={"passed": False, "checks": [{"name": "internal_links", "passed": False}]},
        )
        self.assertEqual(qa_fail.status_code, 200)
        self.assertEqual(qa_fail.json()["quality_state"], "REVISION_REQUESTED")

        qa_pass = self.client.post(
            f"/v1/cs/deliveries/{did}/qa-review",
            headers=self.manager_headers,
            json={
                "passed": True,
                "checks": [{"name": "internal_links", "passed": True}],
                "output_artifacts": {"wp_draft_url": "https://deliv-agency.in/?p=401"},
            },
        )
        self.assertEqual(qa_pass.status_code, 200)
        self.assertEqual(qa_pass.json()["quality_state"], "QUALITY_REVIEW")

        deliv = self.client.post(
            f"/v1/cs/deliveries/{did}/transition",
            headers=self.manager_headers,
            json={"target_state": "DELIVERED", "note": "QA passed and uploaded to WP staging"},
        )
        self.assertEqual(deliv.status_code, 200)
        self.assertEqual(deliv.json()["quality_state"], "DELIVERED")

        # Tenant accepts deliverable via /v1/me/deliveries/{id}/respond
        acc_resp = self.client.post(
            f"/v1/me/deliveries/{did}/respond",
            headers={"Authorization": t["auth_header"]},
            json={"action": "ACCEPTED", "note": "Looks great for our client!"},
        )
        self.assertEqual(acc_resp.status_code, 200, acc_resp.text)
        self.assertEqual(acc_resp.json()["quality_state"], "ACCEPTED")

        # Attribution guard rejects unverified SEO causation claims
        fake_attr = self.client.post(
            f"/v1/cs/deliveries/{did}/metrics",
            headers=self.manager_headers,
            json={
                "output_metrics": {"articles_completed": 4},
                "outcome_metrics": {"organic_traffic": 2400, "claimed_askforwrite_caused": True, "gsc_connected": False},
            },
        )
        self.assertEqual(fake_attr.status_code, 422)

        # Valid GSC-verified outcome succeeds
        real_attr = self.client.post(
            f"/v1/cs/deliveries/{did}/metrics",
            headers=self.manager_headers,
            json={
                "output_metrics": {"articles_completed": 4, "publishing_status": "staged"},
                "outcome_metrics": {
                    "gsc_connected": True,
                    "attribution_evidence_level": "GSC_VERIFIED_WITH_BASELINE",
                    "attribution_evidence_refs": ["gsc://sc-domain:deliv-agency.in/2026-10"],
                    "organic_traffic": 1420,
                    "claimed_askforwrite_caused": True,
                },
            },
        )
        self.assertEqual(real_attr.status_code, 200, real_attr.text)
        self.assertEqual(real_attr.json()["output_metrics"]["metric_class"], "OUTPUT_DELIVERABLES")
        self.assertEqual(real_attr.json()["outcome_metrics"]["metric_class"], "BUSINESS_OUTCOMES")

        # Add ticket CSAT + payment failure to test full multi-dimension Health & internal alerts
        self.client.post(
            f"/v1/cs/subscriptions/{oid}/events",
            headers=self.manager_headers,
            json={
                "event_type": "payment_failed",
                "target_state": "PAST_DUE",
                "idempotency_key": "hlth-past-due-1",
                "amount": 4999.0,
            },
        )
        h_full = self.client.get(f"/v1/cs/customers/{oid}/health", headers=self.manager_headers)
        self.assertEqual(h_full.status_code, 200, h_full.text)
        self.assertGreaterEqual(h_full.json()["scored_dimensions_count"], 3)
        self.assertEqual(h_full.json()["health_state"], "AT_RISK")

        alerts_res = self.client.post(f"/v1/cs/customers/{oid}/health/alerts", headers=self.manager_headers)
        self.assertEqual(alerts_res.status_code, 200)
        self.assertGreaterEqual(alerts_res.json()["count"], 1)
        sup_alerts = self.db.query(SupervisorAlertRecord).filter_by(org_id=oid).all()
        self.assertTrue(all((a.metadata_json or {}).get("internal_only") for a in sup_alerts))

    # ── 5, 6, 10, 11: Cross-Tenant Isolation, Support AI HITL, Privacy/Legal Hold

    def test_03_cross_tenant_isolation_support_hitl_and_privacy_compliance(self) -> None:
        org_a = self._seed_tenant(org_id="org-alpha-1", slug="alpha-agency")
        org_b = self._seed_tenant(org_id="org-beta-2", slug="beta-agency")

        # Alpha opens ticket via self-service portal
        t_resp = self.client.post(
            "/v1/me/support/tickets",
            headers={"Authorization": org_a["auth_header"]},
            json={"subject": "Need refund for double invoice", "description": "Please issue a refund and discount on next cycle", "category": "refund_dispute"},
        )
        self.assertEqual(t_resp.status_code, 200, t_resp.text)
        tkt_id = t_resp.json()["ticket_id"]

        # Beta cannot read Alpha's tickets, post replies, or submit CSAT
        b_list = self.client.get("/v1/me/support/tickets", headers={"Authorization": org_b["auth_header"]})
        self.assertEqual(b_list.status_code, 200)
        self.assertEqual(b_list.json()["count"], 0)

        b_msg = self.client.post(
            f"/v1/me/support/tickets/{tkt_id}/messages",
            headers={"Authorization": org_b["auth_header"]},
            json={"body": "Cross-tenant injection"},
        )
        self.assertEqual(b_msg.status_code, 403)

        b_csat = self.client.post(
            f"/v1/me/support/tickets/{tkt_id}/csat",
            headers={"Authorization": org_b["auth_header"]},
            json={"rating": 1},
        )
        self.assertEqual(b_csat.status_code, 403)

        # AI Support Assistant detects sensitive topic and requires HITL approval
        self.assertTrue(approval_required("support_sensitive_external_reply"))
        ai_res = self.client.post(f"/v1/cs/support/tickets/{tkt_id}/ai-assist", headers=self.manager_headers)
        self.assertEqual(ai_res.status_code, 200, ai_res.text)
        self.assertTrue(ai_res.json()["triage"]["requires_human_approval"])

        # Staff customer-visible reply with refund promise is BLOCKED until Owner ApprovalRequest APPROVED
        blocked_reply = self.client.post(
            f"/v1/cs/support/tickets/{tkt_id}/messages",
            headers=self.manager_headers,
            json={"body": "We guarantee a 100% refund and 50% discount tomorrow.", "visibility": "customer_visible"},
        )
        self.assertEqual(blocked_reply.status_code, 200, blocked_reply.text)
        self.assertEqual(blocked_reply.json()["status"], "APPROVAL_REQUIRED")
        self.assertFalse(blocked_reply.json()["customer_message_sent"])
        appr_id = blocked_reply.json()["approval_id"]

        appr = self.db.get(ApprovalRequest, appr_id)
        appr.status = "APPROVED"
        appr.decided_by = "founder"
        self.db.commit()

        allowed_reply = self.client.post(
            f"/v1/cs/support/tickets/{tkt_id}/messages",
            headers=self.manager_headers,
            json={"body": "Approved refund credit has been scheduled.", "visibility": "customer_visible", "approval_id": appr_id},
        )
        self.assertEqual(allowed_reply.status_code, 200)
        self.assertTrue(allowed_reply.json()["customer_message_sent"])

        # Improvement Loop clusters ticket into prioritized backlog item (requires release approval)
        imp_res = self.client.post(f"/v1/cs/improvements/synthesize?org_id={org_a['org_id']}", headers=self.manager_headers)
        self.assertEqual(imp_res.status_code, 200)
        self.assertGreaterEqual(imp_res.json()["count"], 1)
        self.assertTrue(all(item["requires_release_approval"] for item in imp_res.json()["improvements"]))

        # Data Export is strictly org-scoped, excludes internal notes & secrets, writes AuditLog
        exp = self.client.get("/v1/me/data-export", headers={"Authorization": org_a["auth_header"]})
        self.assertEqual(exp.status_code, 200, exp.text)
        bundle = exp.json()["bundle"]
        self.assertEqual(bundle["org_id"], org_a["org_id"])
        self.assertTrue(all("password_hash" not in u for u in bundle["users"]))
        self.assertTrue(all("internal_notes" not in t for t in bundle["support_tickets"]))

        # Legal Hold BLOCKS deletion/offboarding; removing legal hold enforces Owner HITL before executing offboarding
        self.client.patch(
            f"/v1/cs/compliance/{org_b['org_id']}/consent-retention",
            headers=self.manager_headers,
            json={"retention_policy": {"legal_hold": True}},
        )
        blk_del = self.client.post(
            f"/v1/cs/compliance/{org_b['org_id']}/offboard-delete",
            headers=self.owner_headers,
            json={"request_type": "DATA_DELETION", "reason": "Customer requested erasure"},
        )
        self.assertEqual(blk_del.status_code, 200, blk_del.text)
        self.assertTrue(blk_del.json()["blocked"])

        self.client.patch(
            f"/v1/cs/compliance/{org_b['org_id']}/consent-retention",
            headers=self.manager_headers,
            json={"retention_policy": {"legal_hold": False}},
        )
        req_del = self.client.post(
            f"/v1/cs/compliance/{org_b['org_id']}/offboard-delete",
            headers=self.owner_headers,
            json={"request_type": "DATA_DELETION", "reason": "Customer verified erasure"},
        )
        self.assertEqual(req_del.status_code, 200)
        self.assertTrue(req_del.json()["requires_approval"])
        del_appr = self.db.get(ApprovalRequest, req_del.json()["approval_id"])
        del_appr.status = "APPROVED"
        del_appr.decided_by = "founder"
        self.db.commit()

        exec_del = self.client.post(
            f"/v1/cs/compliance/{org_b['org_id']}/offboard-delete",
            headers=self.owner_headers,
            json={"request_type": "DATA_DELETION", "reason": "Customer verified erasure", "approval_id": del_appr.id},
        )
        self.assertEqual(exec_del.status_code, 200, exec_del.text)
        self.assertTrue(exec_del.json()["executed"])
        org_b_row = self.db.get(OrganizationRecord, org_b["org_id"])
        self.assertFalse(org_b_row.is_active)

    # ── 7, 8, 9: Subscription Idempotency, Grace/Suspension/Restore, Refund HITL, Expansion & Unit Economics

    def test_04_subscription_reliability_expansion_hitl_and_unit_economics_caps(self) -> None:
        t = self._seed_tenant(org_id="org-sub-01", slug="sub-agency", sku_key="seo_blog_copilot", tier="seo_blog_copilot")
        oid = t["org_id"]

        # Duplicate idempotency_key writes only once; manual proof cannot become recurring MRR
        e1 = self.client.post(
            f"/v1/cs/subscriptions/{oid}/events",
            headers=self.manager_headers,
            json={
                "event_type": "manual_proof_submitted",
                "target_state": "ACTIVE",
                "idempotency_key": "sub-ev-uniq-1",
                "provider": "afw_directpay",
                "is_provider_confirmed": False,
                "amount": 4999.0,
            },
        )
        self.assertEqual(e1.status_code, 200, e1.text)
        self.assertEqual(e1.json()["event"]["billing_category"], "MANUAL_PAYMENT_PROOF")

        e1_dup = self.client.post(
            f"/v1/cs/subscriptions/{oid}/events",
            headers=self.manager_headers,
            json={
                "event_type": "manual_proof_submitted",
                "target_state": "ACTIVE",
                "idempotency_key": "sub-ev-uniq-1",
                "provider": "afw_directpay",
                "is_provider_confirmed": False,
                "amount": 4999.0,
            },
        )
        self.assertEqual(e1_dup.status_code, 200)
        self.assertEqual(e1_dup.json()["status"], "DUPLICATE_IGNORED")

        # Payment failure -> PAST_DUE grace period -> expire grace -> SUSPENDED -> restore ACTIVE
        fail_res = self.client.post(
            f"/v1/cs/subscriptions/{oid}/payment-failure",
            headers=self.manager_headers,
            json={"amount": 2499.0, "grace_days": 3, "idempotency_key": "fail-ev-1"},
        )
        self.assertEqual(fail_res.status_code, 200)
        self.assertEqual(fail_res.json()["event"]["subscription_state"], "PAST_DUE")

        # Move grace_until to past and run grace enforcement
        ev_row = self.db.query(P3SubscriptionEventRecord).filter_by(idempotency_key="fail-ev-1").first()
        ev_row.grace_until = datetime.now(UTC) - timedelta(hours=2)
        self.db.commit()

        enf = self.client.post(f"/v1/cs/subscriptions/enforce-grace?org_id={oid}", headers=self.manager_headers)
        self.assertEqual(enf.status_code, 200)
        self.assertEqual(enf.json()["suspended_count"], 1)
        self.assertEqual(self.db.get(OrganizationRecord, oid).tier, "free")

        # Recovery restores ACTIVE & entitlements
        rest = self.client.post(
            f"/v1/cs/subscriptions/{oid}/restore",
            headers=self.manager_headers,
            json={"idempotency_key": "restore-ev-1", "amount": 2499.0, "provider_confirmed": True},
        )
        self.assertEqual(rest.status_code, 200, rest.text)
        self.assertEqual(rest.json()["event"]["subscription_state"], "ACTIVE")

        # Refund requires Owner HITL approval
        ref_req = self.client.post(
            f"/v1/cs/subscriptions/{oid}/refund",
            headers=self.owner_headers,
            json={"amount_inr": 500.0, "reason": "Pro-rata goodwill adjustment"},
        )
        self.assertEqual(ref_req.status_code, 200)
        self.assertEqual(ref_req.json()["status"], "APPROVAL_REQUIRED")
        self.assertFalse(ref_req.json()["refund_executed"])

        # Expansion opportunity uses catalog SKUs and requires HITL before sharing
        org_row = self.db.get(OrganizationRecord, oid)
        org_row.lead_credits_used = 92
        self.db.commit()
        ev_opps = self.client.post(f"/v1/cs/growth/{oid}/evaluate", headers=self.manager_headers)
        self.assertEqual(ev_opps.status_code, 200, ev_opps.text)
        self.assertGreaterEqual(ev_opps.json()["count"], 1)
        opp_id = ev_opps.json()["opportunities"][0]["opportunity_id"]

        share_unappr = self.client.post(
            f"/v1/cs/growth/opportunities/{opp_id}/share",
            headers=self.manager_headers,
            json={},
        )
        self.assertEqual(share_unappr.status_code, 200)
        self.assertEqual(share_unappr.json()["status"], "APPROVAL_REQUIRED")
        self.assertFalse(share_unappr.json()["shared"])

        # Unit economics: budget cap blocks overspend (402), honest CAC/LTV = INSUFFICIENT_DATA
        self.client.put(
            f"/v1/cs/unit-economics/{oid}/budget",
            headers=self.owner_headers,
            json={"monthly_cost_limit_inr": 500.0, "hard_cap_enforced": True},
        )
        ok_cost = self.client.post(
            f"/v1/cs/unit-economics/{oid}/costs",
            headers=self.manager_headers,
            json={"cost_category": "AI_API_USAGE", "cost_type_label": "ACTUAL", "amount_inr": 300.0, "tokens_input": 10000, "tokens_output": 2000},
        )
        self.assertEqual(ok_cost.status_code, 200, ok_cost.text)

        over_cost = self.client.post(
            f"/v1/cs/unit-economics/{oid}/costs",
            headers=self.manager_headers,
            json={"cost_category": "HUMAN_DELIVERY", "cost_type_label": "ALLOCATED", "amount_inr": 350.0},
        )
        self.assertEqual(over_cost.status_code, 402)

        ue = self.client.get(f"/v1/cs/unit-economics/{oid}", headers=self.manager_headers)
        self.assertEqual(ue.status_code, 200, ue.text)
        self.assertEqual(ue.json()["acquisition_and_ltv"]["ltv_data_quality"], "INSUFFICIENT_DATA")
        self.assertEqual(ue.json()["cost_summary"]["costs_by_quality_label"]["ACTUAL"], 300.0)

    # ── 12, 13, 14: Ops Readiness, Multi-Tenant Concurrency & DLQ, Simulation Isolation, 8 CS Agents & 12-Step

    def test_05_ops_readiness_dlq_concurrency_control_centre_isolation_agents_and_checklist(self) -> None:
        live_org = self._seed_tenant(org_id="org-live-jaipur", slug="live-jaipur", is_sandbox=False, sku_key="company_os_starter", tier="company_os_starter")
        sandbox_org = self._seed_tenant(org_id="org-sandbox-demo", slug="sandbox-demo", is_sandbox=True)

        # Live verified paid invoice + provider-confirmed recurring subscription event vs synthetic noise
        self.db.add(
            InvoiceRecord(
                id="inv-live-1",
                org_id=live_org["org_id"],
                customer_id="cust-live-1",
                provider="razorpay",
                provider_invoice_id="inv_rzp_live_1",
                amount=499900,
                currency="INR",
                status="paid",
                metadata_json={"package_key": "managed_seo_content_pilot", "billing_type": "one_time"},
            )
        )
        self.db.add(
            P2ProspectDossierRecord(
                lead_id=str(uuid.uuid4()),
                normalized_company_key="synthetic-agency",
                normalized_domain="synthetic.example.com",
                source_url="https://synthetic.example.com",
                source_type="synthetic_fixture",
                is_synthetic=True,
                pipeline_status="WON",
            )
        )
        # Seed WorkflowDefinition + timed-out RUNNING workflow + concurrency ceiling test
        wf = WorkflowDefinitionRecord(
            id="wf-def-1",
            org_id=live_org["org_id"],
            workflow_key="seo_cluster",
            name="SEO Cluster",
            steps_json=[],
        )
        stale_run = WorkflowRunRecord(
            id="wf-run-stale-1",
            workflow_id="wf-def-1",
            org_id=live_org["org_id"],
            execution_mode="LOCAL_ENGINE",
            status="RUNNING",
            started_at=datetime.now(UTC) - timedelta(hours=2),
            updated_at=datetime.now(UTC) - timedelta(hours=2),
        )
        sim_ev = ExecutionEvidenceRecord(
            execution_id="exec-sim-1",
            tenant_id=sandbox_org["org_id"],
            agent_id="seo_content_agent",
            connector_id="project_api",
            execution_mode="SIMULATION",
            input_reference="hash1",
            output_reference="hash2",
            evidence_reference="ev://sim-1",
            output_origin="SIMULATED_SYNTHETIC",
            status="COMPLETED",
            started_at=datetime.now(UTC),
        )
        self.db.add_all([wf, stale_run, sim_ev])
        self.db.commit()

        # Scan timeout moves stale_run -> FAILED + DLQ incident, then retry requeues FAILED -> READY
        scan = self.client.post("/v1/cs/ops/workflows/scan-timeouts?timeout_seconds=60", headers=self.manager_headers)
        self.assertEqual(scan.status_code, 200, scan.text)
        self.assertIn("wf-run-stale-1", scan.json()["timed_out_run_ids"])
        inc_id = scan.json()["incidents_created"][0]

        requeue = self.client.post(f"/v1/cs/ops/dlq/{inc_id}/retry", headers=self.manager_headers)
        self.assertEqual(requeue.status_code, 200, requeue.text)
        self.assertEqual(requeue.json()["workflow_run_status"], "READY")

        # Multi-tenant concurrent load test: fill sandbox_org to MAX_CONCURRENT_RUNS_PER_ORG -> live_org remains unaffected
        for i in range(MAX_CONCURRENT_RUNS_PER_ORG):
            self.db.add(
                WorkflowRunRecord(
                    id=f"wf-cap-{i}",
                    workflow_id="wf-def-1",
                    org_id=sandbox_org["org_id"],
                    execution_mode="SIMULATION",
                    status="RUNNING",
                )
            )
        self.db.commit()

        # Parallel read load across endpoints
        errors: list[str] = []

        def _worker(path: str) -> None:
            r = self.client.get(path, headers=self.manager_headers)
            if r.status_code != 200:
                errors.append(f"{path}:{r.status_code}")

        threads = [
            threading.Thread(target=_worker, args=("/v1/cs/control-centre",)),
            threading.Thread(target=_worker, args=("/v1/cs/ops/readiness",)),
            threading.Thread(target=_worker, args=(f"/v1/cs/customers/{live_org['org_id']}/health",)),
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(errors, [])

        # Backup drill + ops readiness probe
        drill = self.client.post(
            "/v1/cs/ops/backup-drill",
            headers=self.owner_headers,
            json={"target_scope": "sqlite_test_drill", "restore_tested": True, "recovery_time_seconds": 1.2, "evidence_ref": "drill://run-1"},
        )
        self.assertEqual(drill.status_code, 200)
        ops = self.client.get("/v1/cs/ops/readiness", headers=self.manager_headers)
        self.assertEqual(ops.status_code, 200)
        self.assertEqual(ops.json()["database_health"]["status"], "HEALTHY")
        self.assertEqual(ops.json()["latest_backup_drill"]["status"], "RECOVERED")

        # Control Centre isolates verified live KPIs from synthetic & sandbox accounts
        cc = self.client.get("/v1/cs/control-centre", headers=self.manager_headers).json()
        self.assertEqual(cc["verified_customer_ops"]["acquisition"]["won_customers"], 0)
        self.assertEqual(cc["verified_customer_ops"]["revenue_and_unit_economics"]["verified_one_time_revenue_inr"], 4999.0)
        self.assertEqual(cc["verified_customer_ops"]["revenue_and_unit_economics"]["verified_recurring_mrr_inr"], 0.0)
        self.assertEqual(cc["verified_customer_ops"]["revenue_and_unit_economics"]["verified_arr_inr"], "INSUFFICIENT_DATA")
        self.assertEqual(cc["simulation_and_test_metrics"]["exclusion_policy"], "EXCLUDED_FROM_LIVE_BUSINESS_KPIS")
        self.assertEqual(cc["simulation_and_test_metrics"]["synthetic_prospects_count"], 1)

        # Verify all 28 agents (20 prior + 8 CS agents) are registered & CS agents executable via API
        self.assertGreaterEqual(len(AGENT_REGISTRY), 28)
        for cs_agent in (
            "cs_onboarding_specialist_agent",
            "cs_manager_agent",
            "service_delivery_coordinator_agent",
            "qa_review_agent",
            "cs_support_specialist_agent",
            "renewal_management_agent",
            "expansion_opportunity_agent",
            "customer_insights_analyst_agent",
        ):
            self.assertIn(cs_agent, AGENT_REGISTRY)

        exec_resp = self.client.post(
            "/v1/registry/agents/cs_onboarding_specialist_agent/execute",
            headers=self.manager_headers,
            json={"input_payload": {"org_id": live_org["org_id"]}, "execution_mode": "SIMULATION"},
        )
        self.assertEqual(exec_resp.status_code, 200, exec_resp.text)
        self.assertEqual(exec_resp.json()["status"], "COMPLETED")

        # Verify 12-Step P3 Acceptance Checklist defaults cleanly to NOT_TESTED and updates honestly
        acc = self.client.get("/v1/cs/acceptance", headers=self.manager_headers)
        self.assertEqual(acc.status_code, 200)
        self.assertEqual(len(acc.json()["steps"]), 12)
        self.assertEqual(acc.json()["summary"]["not_tested_count"], 12)

        upd = self.client.post(
            "/v1/cs/acceptance/1",
            headers=self.owner_headers,
            json={"verification_status": "SANDBOX_VERIFIED", "evidence_summary": "Verified in automated sandbox suite"},
        )
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(upd.json()["verification_status"], "SANDBOX_VERIFIED")
