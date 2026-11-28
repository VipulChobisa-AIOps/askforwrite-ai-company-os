"""Adversarial & End-to-End Verification Suite for Phase 0 & Phase 1 Strategic Action Plan.

Covers every critical security vulnerability and commercial upgrade:
1. Login brute-force rate limit CANNOT be bypassed with rotating random X-API-Key / Bearer headers.
2. Logout persists across simulated worker restarts (clearing in-memory _REVOKED_TOKENS).
3. Hard-deleted user tokens fail closed immediately with HTTP 401 (never trusting stale JWT claims).
4. _get_signing_secret() fails closed inside the function in production (never falling back to API keys/constants).
5. PBKDF2-HMAC-SHA256 defaults to OWASP 600,000 iterations while keeping 100K backward compatibility.
6. Mango & Bike modules cleanly decoupled from OS (404 routes, 410 portal) & archived locally.
7. Digital Asset & Content QA Benchmark Engine: anti-slop gate, Schema.org validation, claim hygiene,
   and ECDSA-signed Human-Review Receipt verified publicly in JSON & HTML.
8. Managed AI Usage-Credit pool: atomic reserve, HTTP 402 on exhaustion (zero canned output),
   refund on failure, 0-credit BYOK mode, daily spend cap, and prepaid top-up packs.
9. 10-Emails/Day Sniper Outbound cap at dispatch + Svix-signed Resend webhook (delivered/bounced/complained)
   + 7-day bounce circuit breaker + Sniper Monitor endpoint.
10. StockSense math fixes (exact normal CDF service level, real exponential smoothing, no hardcoded SKU).
11. Migration q7f2a3b4c5d6 upgrade/downgrade parity.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["APP_ENV"] = "development"
TEST_OWNER_KEY = "phase0-owner-key-must-be-at-least-32-characters-long-123456"
TEST_MANAGER_KEY = "phase0-manager-key-must-be-at-least-32-characters-long-7890"
os.environ["OWNER_API_KEY"] = TEST_OWNER_KEY
os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY

from app.agents.llm_client import _deterministic_fallback
from app.db.database import Base, get_db
from app.db.models import (
    ApprovalRequest,
    ExecutionEvidenceRecord,
    OrganizationRecord,
    OutreachRecord,
    UserRecord,
)
from app.main import app
from app.middleware import RateLimitMiddleware
from app.security.auth import (
    _REVOKED_TOKENS,
    _REVOKED_USERS,
    _get_signing_secret,
    create_access_token,
    hash_password,
    verify_password,
)
from app.services.billing_ledger import (
    DailySpendCapExceededError,
    grant_ai_credit_topup,
    refund_ai_credit_reservation,
    reserve_ai_credits,
)
from app.services.catalog import CATALOG
from app.services.inventory_analytics import compute_reorder_recommendations, detect_dead_stock, execute_inventory_audit
from app.services.outreach import dispatch_outreach
from app.services.p2_outreach_pipeline import check_outbound_deliverability_health


class Phase0Phase1StrategicPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, autoflush=False, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(cls.engine)

    def setUp(self):
        os.environ["APP_ENV"] = "development"
        os.environ["OWNER_API_KEY"] = TEST_OWNER_KEY
        os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY
        self.db = self.Session()
        for tbl in reversed(Base.metadata.sorted_tables):
            self.db.execute(tbl.delete())
        self.db.commit()

        def _override_db():
            s = self.Session()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = _override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_db, None)

    def _seed_tenant(self, *, ai_credits_limit: int = 150, tier: str = "starter", caps: list[str] | None = None):
        org_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        email = f"founder-{uuid.uuid4().hex[:8]}@agency.in"
        pw_hash = hash_password("StrongPass123!")
        org = OrganizationRecord(
            id=org_id,
            name="Acme Content Agency",
            slug=f"acme-{uuid.uuid4().hex[:6]}",
            tier=tier,
            lead_credits_limit=100,
            outreach_credits_limit=50,
            ai_credits_limit=ai_credits_limit,
            ai_credits_used=0,
            ai_daily_spend_cap_inr=100.0,
            ai_billing_mode="MANAGED_CREDITS",
            is_active=True,
            metadata_json={
                "package_key": "managed_seo_content_pilot",
                "entitled_capabilities": caps or [
                    "seo_content_automation",
                    "digital_qa",
                    "marketing_campaign_suite",
                    "trust_ledger_audit",
                    "warehouse_automation",
                ],
            },
        )
        user = UserRecord(
            id=user_id,
            org_id=org_id,
            email=email,
            full_name="Priya Editor",
            role="tenant_admin",
            password_hash=pw_hash,
            is_active=True,
        )
        self.db.add_all([org, user])
        self.db.commit()
        tok = create_access_token(
            user_id=user_id,
            email=email,
            role="tenant_admin",
            org_id=org_id,
            password_hash=pw_hash,
            token_version=0,
        )
        return org, user, tok

    # ── 1. P0 SECURITY FIXES ─────────────────────────────────────────────────

    def test_01_login_rate_limit_blocks_rotating_headers_bypass(self):
        stub = FastAPI()
        with patch.dict(os.environ, {"APP_ENV": "production", "RATE_LIMIT_AUTH": "20"}):
            stub.add_middleware(RateLimitMiddleware)

            @stub.post("/v1/auth/login")
            def _stub_login():
                return {"ok": True}

            c = TestClient(stub)
            blocked = 0
            for i in range(45):
                r = c.post(
                    "/v1/auth/login",
                    headers={
                        "X-API-Key": f"attacker-random-key-{i}",
                        "Authorization": f"Bearer attacker-random-jwt-{i}",
                        "X-Forwarded-For": "198.51.100.77",
                    },
                )
                if r.status_code == 429:
                    blocked += 1
            self.assertEqual(blocked, 25, f"Expected 25/45 blocked under 20/min cap, got {blocked}")

    def test_02_logout_survives_process_restart_and_deleted_user_fails_closed(self):
        org, user, tok = self._seed_tenant()
        hdrs = {"Authorization": f"Bearer {tok}"}

        # Before logout: succeeds
        self.assertEqual(self.client.get("/v1/auth/me", headers=hdrs).status_code, 200)

        # Logout revokes persistently in DB + bumps token_version
        logout_resp = self.client.post("/v1/auth/logout", headers=hdrs)
        self.assertEqual(logout_resp.status_code, 200)

        # Simulate complete worker restart by wiping in-memory revocation sets
        _REVOKED_TOKENS.clear()
        _REVOKED_USERS.clear()

        # Token MUST still be rejected with 401 after restart
        after_restart = self.client.get("/v1/auth/me", headers=hdrs)
        self.assertEqual(after_restart.status_code, 401)

        # Now test deleted user failing closed even without logout
        _, user2, tok2 = self._seed_tenant()
        hdrs2 = {"Authorization": f"Bearer {tok2}"}
        self.assertEqual(self.client.get("/v1/auth/me", headers=hdrs2).status_code, 200)

        # Hard-delete user row directly (like DELETE /orgs/{org}/users/{id}) and clear memory sets
        self.db.query(UserRecord).filter_by(id=user2.id).delete()
        self.db.commit()
        _REVOKED_TOKENS.clear()
        _REVOKED_USERS.clear()

        deleted_resp = self.client.get("/v1/auth/me", headers=hdrs2)
        self.assertEqual(deleted_resp.status_code, 401)

    def test_03_signing_secret_fails_closed_in_production_and_pbkdf2_600k(self):
        # Never falls back to OWNER_API_KEY or public constant in production
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "JWT_SECRET_KEY": "",
                "SECRET_KEY": "",
                "AUTH_SECRET_KEY": "",
                "OWNER_API_KEY": TEST_OWNER_KEY,
                "MANAGER_API_KEY": TEST_MANAGER_KEY,
            },
        ):
            with self.assertRaises(RuntimeError):
                _get_signing_secret()

        # OWASP 600K PBKDF2 default + backward compatibility with legacy 100K hashes
        h600 = hash_password("AuditSecret#2026")
        self.assertTrue(h600.startswith("pbkdf2:sha256:600000$"))
        self.assertTrue(verify_password("AuditSecret#2026", h600))
        self.assertFalse(verify_password("WrongPass", h600))

        # Verify legacy 100K hash still verifies cleanly
        salt = "0123456789abcdef0123456789abcdef"
        legacy_key = hashlib.pbkdf2_hmac("sha256", b"LegacyPass!", salt.encode(), 100_000).hex()
        legacy_hash = f"pbkdf2:sha256:100000${salt}${legacy_key}"
        self.assertTrue(verify_password("LegacyPass!", legacy_hash))

    # ── 2. MANGO & BIKE EXTRACTION ───────────────────────────────────────────

    def test_04_mango_and_bike_decoupled_from_os_and_preserved_locally(self):
        self.assertNotIn("mango_quality_analytics", CATALOG)
        self.assertNotIn("bike_rebalance_analytics", CATALOG)
        self.assertIn("ai_credits_100", CATALOG)
        self.assertIn("ai_credits_500", CATALOG)
        self.assertIn("ai_credits_2000", CATALOG)

        # Unmounted routes return 404
        self.assertEqual(self.client.get("/v1/quality/status").status_code, 404)
        self.assertEqual(self.client.get("/v1/mobility/status").status_code, 404)

        # Portal rejects extracted SKUs with 410 Gone
        org, _, tok = self._seed_tenant(caps=["all_access"])
        r = self.client.post(
            "/v1/me/use-service",
            headers={"Authorization": f"Bearer {tok}"},
            json={"service_key": "mango_quality_analytics", "payload": {}},
        )
        self.assertEqual(r.status_code, 410)

        # Preserved standalone locally
        standalone_dir = Path(r"c:\Users\vipul\AI\Documents\mango and bike\extracted_os_services")
        self.assertTrue((standalone_dir / "quality_analytics.py").exists())
        self.assertTrue((standalone_dir / "mobility_analytics.py").exists())
        self.assertTrue((standalone_dir / "README_STANDALONE.md").exists())

    # ── 3. DIGITAL QA BENCHMARK & SIGNED HUMAN-REVIEW RECEIPTS ───────────────

    def test_05_digital_qa_protocol_blocks_slop_and_issues_signed_receipt(self):
        org, user, tok = self._seed_tenant()
        hdrs = {"Authorization": f"Bearer {tok}"}

        # Create org-specific Brand & Anti-Slop Protocol
        proto_resp = self.client.post(
            "/v1/digital-qa/protocols",
            headers=hdrs,
            json={
                "name": "B2B SaaS Editorial Protocol",
                "min_score": 80,
                "min_word_count": 120,
                "mandatory_terms": ["AskforWrite"],
                "forbidden_terms": ["CompetitorXYZ"],
                "require_schema_ld": True,
                "require_faq": True,
                "require_live_llm": True,
                "is_default": True,
            },
        )
        self.assertEqual(proto_resp.status_code, 201)

        # Bad draft with fallback boilerplate, AI slop, forbidden term, and unsupported guarantee -> MUST FAIL
        bad_resp = self.client.post(
            "/v1/digital-qa/evaluate",
            headers=hdrs,
            json={
                "title": "Slop Draft",
                "content": "# Bad Draft\nIn today's fast-paced landscape, delve into CompetitorXYZ with guaranteed ROI and #1 Google ranking.",
                "used_fallback": True,
            },
        )
        self.assertEqual(bad_resp.status_code, 200)
        bad_data = bad_resp.json()
        self.assertFalse(bad_data["passed"])
        codes = {d["code"] for d in bad_data["defects"]}
        self.assertIn("FALLBACK_BOILERPLATE_BLOCKED", codes)
        self.assertIn("FORBIDDEN_BRAND_TERM_VIOLATION", codes)
        self.assertIn("UNSUPPORTED_GUARANTEE_OR_SUPERLATIVE", codes)

        # Signing off a failed QA report must be rejected (400)
        sign_fail = self.client.post(
            f"/v1/digital-qa/reports/{bad_data['receipt_id']}/sign-off",
            headers=hdrs,
            json={"review_notes": "Attempted bypass"},
        )
        self.assertEqual(sign_fail.status_code, 400)

        # High-quality live-LLM draft with clean structure, FAQ, Schema JSON-LD -> PASSES & SIGNS
        body_words = " ".join(["AskforWrite engineering teams verify search architecture and entity clarity across publishing pipelines."] * 14)
        good_article = (
            "# Practical B2B SEO & Digital QA Architecture\n\n"
            f"## 1. Executive Summary\n{body_words}\n\n"
            "## 2. Brand Protocol Verification\nEvery draft checks mandatory terminology and citation links like [Google Docs](https://developers.google.com/search).\n\n"
            "## 3. Editorial Governance\nHuman editors verify factual accuracy before WordPress staging.\n\n"
            "## Frequently Asked Questions (FAQ)\n**Q: How does Digital QA prevent AI slop?**\nA: Automated cliche blocking and live-LLM enforcement gate every article.\n\n"
            '```json\n{"@context": "https://schema.org", "@type": "Article", "headline": "Practical B2B SEO & Digital QA Architecture"}\n```'
        )
        good_resp = self.client.post(
            "/v1/digital-qa/evaluate",
            headers=hdrs,
            json={
                "title": "Practical B2B SEO & Digital QA Architecture",
                "content": good_article,
                "keywords": ["AskforWrite", "SEO"],
                "used_fallback": False,
            },
        )
        self.assertEqual(good_resp.status_code, 200)
        good_data = good_resp.json()
        self.assertTrue(good_data["passed"], f"Expected PASS, defects={good_data['defects']}")
        self.assertGreaterEqual(good_data["overall_score"], 85)

        # Human editorial sign-off seals ECDSA NIST P-256 block
        sign_resp = self.client.post(
            f"/v1/digital-qa/reports/{good_data['receipt_id']}/sign-off",
            headers=hdrs,
            json={"review_notes": "Verified all facts & Schema markup.", "target_url": "https://askforwrite.com/blog/qa"},
        )
        self.assertEqual(sign_resp.status_code, 200)
        signed = sign_resp.json()
        self.assertEqual(signed["human_reviewer"], user.email)

        # Public verification receipt works in both JSON and printable HTML
        pub_json = self.client.get(f"/v1/digital-qa/receipts/{good_data['receipt_id']}?format=json")
        self.assertEqual(pub_json.status_code, 200)
        self.assertTrue(pub_json.json()["cryptographic_verification"]["verified"])

        pub_html = self.client.get(f"/v1/digital-qa/receipts/{good_data['receipt_id']}?format=html")
        self.assertEqual(pub_html.status_code, 200)
        self.assertIn("VERIFIED HUMAN-REVIEWED DELIVERABLE", pub_html.text)

    # ── 4. MANAGED AI USAGE CREDITS & ZERO CANNED FALLBACK ───────────────────

    def test_06_managed_ai_credits_pool_402_refund_byok_and_no_fake_crm_debrief(self):
        # Invented CRM debrief canned text is permanently gone
        fallback_crm = _deterministic_fallback("Summarize CRM debrief for client visit")
        self.assertNotIn("Client confirmed strong operational alignment", fallback_crm)
        self.assertIn("LIVE_LLM_UNAVAILABLE", fallback_crm)

        # Org with 0 AI credits gets HTTP 402 Payment Required (never silent canned text)
        org_empty, _, tok_empty = self._seed_tenant(ai_credits_limit=0)
        resp_402 = self.client.post(
            "/v1/me/use-service",
            headers={"Authorization": f"Bearer {tok_empty}"},
            json={"service_key": "marketing_suite", "payload": {"product_name": "Acme"}},
        )
        self.assertEqual(resp_402.status_code, 402)
        self.assertEqual(resp_402.json()["detail"]["error_code"], "INSUFFICIENT_AI_CREDITS")

        # Prepaid top-up adds +100 AI credits cleanly
        topup = grant_ai_credit_topup(self.db, org_id=org_empty.id, pack_key="ai_credits_100", actor="test")
        self.assertEqual(topup["credits_added"], 100)
        self.assertEqual(topup["ai_credits_remaining"], 100)

        # Atomic reserve, refund, and BYOK zero-deduction
        res = reserve_ai_credits(
            self.db,
            org_id=org_empty.id,
            cost=10,
            idempotency_key="ai-res-1",
            execution_id="exec-1",
        )
        self.assertEqual(res["balance_after"], 90)
        ref = refund_ai_credit_reservation(
            self.db,
            org_id=org_empty.id,
            cost=10,
            idempotency_key="ai-res-1",
            execution_id="exec-1",
        )
        self.assertEqual(ref["balance_after"], 100)

        # BYOK supplied -> 0 credits deducted
        byok = reserve_ai_credits(
            self.db,
            org_id=org_empty.id,
            cost=10,
            idempotency_key="ai-res-byok",
            execution_id="exec-byok",
            byok_supplied=True,
        )
        self.assertTrue(byok["byok_zero_credit"])
        self.assertEqual(byok["balance_after"], 100)

        # Daily spend cap circuit breaker triggers when today's provider cost >= cap
        self.db.add(
            ExecutionEvidenceRecord(
                execution_id="exec-spend-cap",
                tenant_id=org_empty.id,
                agent_id="seo_content_agent",
                execution_mode="PRODUCTION",
                input_reference="ref-in",
                output_reference="ref-out",
                status="COMPLETED",
                provider_cost_inr=120.0,
                started_at=datetime.now(UTC),
                evidence_reference="ev-1",
                output_origin="LIVE_PROVIDER_VERIFIED",
            )
        )
        self.db.commit()
        with self.assertRaises(DailySpendCapExceededError):
            reserve_ai_credits(
                self.db,
                org_id=org_empty.id,
                cost=5,
                idempotency_key="ai-res-cap",
                execution_id="exec-cap",
            )

        # GET /v1/me/ai-credits works cleanly
        bal_resp = self.client.get("/v1/me/ai-credits", headers={"Authorization": f"Bearer {tok_empty}"})
        self.assertEqual(bal_resp.status_code, 200)
        self.assertEqual(bal_resp.json()["ai_credits_remaining"], 100)

    # ── 5. 10-EMAILS/DAY SNIPER OUTBOUND & RESEND SVIX WEBHOOK ───────────────

    def test_07_sniper_outbound_10_daily_cap_resend_webhook_and_bounce_breaker(self):
        now = datetime.now(UTC)
        # Seed 10 dispatched outreach records today
        for i in range(10):
            self.db.add(
                OutreachRecord(
                    id=f"out-today-{i}",
                    lead_id=f"lead-{i}",
                    task_id=f"task-{i}",
                    recipient_email=f"founder{i}@realagency{i}.in",
                    subject="Pilot scope",
                    body_text="Honest pitch",
                    status="DISPATCHED",
                    sent_at=now,
                    idempotency_key=f"idem-today-{i}",
                    metadata_json={"provider_message_id": f"re_msg_{i}"},
                )
            )
        # Seed 11th approved outreach ready to dispatch -> MUST BE BLOCKED by 10/day cap
        appr = ApprovalRequest(
            id="appr-11",
            task_id="task-11",
            action="external_sales_outreach",
            status="APPROVED",
            detail={},
            idempotency_key="appr-idem-11",
            request_hash="req-hash-11",
            requested_by="agent",
        )
        out11 = OutreachRecord(
            id="out-today-11",
            lead_id="lead-11",
            task_id="task-11",
            recipient_email="founder11@realagency11.in",
            subject="Pilot scope",
            body_text="Honest pitch",
            status="PENDING_APPROVAL",
            approval_id="appr-11",
            idempotency_key="idem-today-11",
        )
        self.db.add_all([appr, out11])
        self.db.commit()

        with self.assertRaises(ValueError) as ctx:
            dispatch_outreach(self.db, "out-today-11", "corr-11", "owner")
        self.assertIn("10/10", str(ctx.exception))

        # Test Svix-signed Resend webhook -> email.delivered & email.bounced & bounce circuit breaker
        raw_secret = b"supersecretresendkey1234567890ab"
        whsec = "whsec_" + base64.b64encode(raw_secret).decode("utf-8")

        def _send_resend_event(ev_type: str, msg_id: str, email: str, valid_sig: bool = True):
            body = json.dumps({"type": ev_type, "data": {"email_id": msg_id, "to": [email]}}).encode("utf-8")
            svix_id = f"msg_{uuid.uuid4().hex[:8]}"
            svix_ts = str(int(datetime.now(UTC).timestamp()))
            sig_b64 = base64.b64encode(
                hmac.new(raw_secret, f"{svix_id}.{svix_ts}.".encode("utf-8") + body, hashlib.sha256).digest()
            ).decode("utf-8")
            if not valid_sig:
                sig_b64 = "aW52YWxpZHNpZ25hdHVyZQ=="
            with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": whsec}):
                return self.client.post(
                    "/v1/webhooks/resend",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "svix-id": svix_id,
                        "svix-timestamp": svix_ts,
                        "svix-signature": f"v1,{sig_b64}",
                    },
                )

        # Invalid Svix signature rejected (401)
        self.assertEqual(_send_resend_event("email.delivered", "re_msg_0", "founder0@realagency0.in", valid_sig=False).status_code, 401)

        # Valid email.delivered transitions status to DELIVERED
        r_del = _send_resend_event("email.delivered", "re_msg_0", "founder0@realagency0.in", valid_sig=True)
        self.assertEqual(r_del.status_code, 200)
        self.assertEqual(r_del.json()["updated_status"], "DELIVERED")

        # Valid email.bounced transitions status to BOUNCED -> 1/10 = 10% bounce > 5% -> trips circuit breaker!
        r_bnc = _send_resend_event("email.bounced", "re_msg_1", "founder1@realagency1.in", valid_sig=True)
        self.assertEqual(r_bnc.status_code, 200)
        self.assertEqual(r_bnc.json()["updated_status"], "BOUNCED")

        health = check_outbound_deliverability_health(self.db)
        self.assertFalse(health["deliverability_healthy"])
        self.assertGreater(health["bounce_rate_7d_pct"], 5.0)

        # Owner Sniper Monitor endpoint works
        mon = self.client.get("/v1/outreach/sniper-monitor", headers={"X-API-Key": TEST_OWNER_KEY})
        self.assertEqual(mon.status_code, 200)
        self.assertEqual(mon.json()["daily_send_cap"], 10)
        self.assertFalse(mon.json()["deliverability_health_7d"]["deliverability_healthy"])

    # ── 6. STOCKSENSE MATH FIXES & MIGRATION PARITY ──────────────────────────

    def test_08_inventory_math_fixes_and_migration_q7f2a3b4c5d6_parity(self):
        # 1. Exact normal CDF (Z=1.96 -> 97.5%, NOT 112.7%)
        audit = execute_inventory_audit(self.db, service_level_z=1.96)
        self.assertEqual(audit["audit_metrics"]["service_level_target"], "97.5%")

        # 2. Real exponential smoothing when history supplied
        recs = compute_reorder_recommendations(
            [{"sku": "S1", "name": "Part", "category": "C", "daily_demand": 10.0, "daily_demand_history": [10.0, 20.0], "lead_time_days": 5, "current_stock": 10, "annual_demand": 3650, "order_cost": 100, "holding_cost_annual": 20}],
            forecast_alpha=0.3,
        )
        self.assertEqual(recs[0]["forecast_daily_demand"], 13.0)

        # 3. No hardcoded SKU-FAS-007 leaked into dead-stock report
        dead = detect_dead_stock([{"sku": "X1", "name": "Old Widget", "unit_cost": 100.0, "current_stock": 10, "last_sold_days_ago": 120}])
        self.assertNotIn("SKU-FAS-007", dead["items"][0]["recommended_liquidation_action"])

        # 4. Alembic q7f2a3b4c5d6 upgrade/downgrade parity
        import migrations.versions.q7f2a3b4c5d6_phase0_phase1_security_digital_qa_ai_credits as mig
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext
        import sqlalchemy as sa

        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with eng.connect() as conn:
            conn.execute(sa.text("CREATE TABLE organizations (id VARCHAR(36) PRIMARY KEY, name VARCHAR(200))"))
            conn.commit()
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)
            orig_op = mig.op
            mig.op = op
            try:
                mig.upgrade()
                conn.commit()
                insp = inspect(conn)
                tables = set(insp.get_table_names())
                self.assertTrue({"revoked_tokens", "digital_qa_protocols", "digital_qa_reports"}.issubset(tables))
                org_cols = {c["name"] for c in insp.get_columns("organizations")}
                self.assertTrue({"ai_credits_limit", "ai_credits_used", "ai_daily_spend_cap_inr", "ai_billing_mode"}.issubset(org_cols))

                mig.downgrade()
                conn.commit()
                tables_after = set(inspect(conn).get_table_names())
                self.assertTrue({"revoked_tokens", "digital_qa_protocols", "digital_qa_reports"}.isdisjoint(tables_after))
            finally:
                mig.op = orig_op


if __name__ == "__main__":
    unittest.main()
