"""Unit tests for Commercial Wrapper: Customer Signup & Tenant-Aware Rate Limiting."""

import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import AuditLog, OrganizationRecord, UserRecord
from app.main import app
from app.middleware import RateLimitMiddleware
from app.security.auth import verify_password


class TestCustomerSignupOnboarding(unittest.TestCase):
    """Tests for the self-serve customer signup flow."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

        def override_get_db():
            s = self.session_factory()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.db = self.session_factory()

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(self.engine)

    @patch("app.api.v1.auth.get_email_dispatcher")
    def test_customer_signup_success(self, mock_dispatcher_fn):
        mock_dispatcher = MagicMock()
        mock_dispatcher_fn.return_value = mock_dispatcher

        payload = {
            "company_name": "Apex Distribution Ltd",
            "email": "director@apexdistro.com",
            "password": "SecurePassword123!",
            "full_name": "Rajesh Sharma",
            "package_key": "field_force",
            "payment_provider": "razorpay",
        }

        resp = self.client.post("/v1/auth/signup", json=payload)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()

        self.assertEqual(data["status"], "registered")
        self.assertEqual(data["email"], "director@apexdistro.com")
        self.assertEqual(data["full_name"], "Rajesh Sharma")
        self.assertEqual(data["org_name"], "Apex Distribution Ltd")
        self.assertEqual(data["tier"], "modular_field_ops")
        self.assertEqual(data["lead_credits_limit"], 50)
        self.assertEqual(data["outreach_credits_limit"], 25)
        self.assertIn("razorpay.me", data["checkout_url"])
        self.assertIn("access_token", data)

        # Verify DB records
        user = self.db.query(UserRecord).filter_by(id=data["user_id"]).first()
        self.assertIsNotNone(user)
        self.assertEqual(user.role, "admin")
        self.assertTrue(verify_password("SecurePassword123!", user.password_hash))

        org = self.db.query(OrganizationRecord).filter_by(id=data["org_id"]).first()
        self.assertIsNotNone(org)
        self.assertEqual(org.tier, "modular_field_ops")

        audit = self.db.query(AuditLog).filter_by(action="customer_signed_up").first()
        self.assertIsNotNone(audit)

        # Verify onboarding email
        mock_dispatcher.send.assert_called_once()
        email_kwargs = mock_dispatcher.send.call_args[1]
        self.assertEqual(email_kwargs["recipient_email"], "director@apexdistro.com")
        self.assertIn("AskforWrite Field Operations Automation Suite", email_kwargs["subject"])

    def test_customer_signup_duplicate_email_fails(self):
        # Create an account first
        payload = {
            "company_name": "First Corp",
            "email": "duplicate@corp.com",
            "password": "Password123",
            "full_name": "Test User",
            "package_key": "company_os_starter",
        }
        with patch("app.api.v1.auth.get_email_dispatcher"):
            r1 = self.client.post("/v1/auth/signup", json=payload)
        self.assertEqual(r1.status_code, 201)

        # Attempt to signup with duplicate email
        with patch("app.api.v1.auth.get_email_dispatcher"):
            r2 = self.client.post("/v1/auth/signup", json=payload)
        self.assertEqual(r2.status_code, 409)
        self.assertIn("already exists", r2.json()["detail"])

    def test_customer_signup_short_password_fails(self):
        payload = {
            "company_name": "Test Co",
            "email": "short@corp.com",
            "password": "123",  # Under min_length=6
            "full_name": "Short Pass",
        }
        resp = self.client.post("/v1/auth/signup", json=payload)
        self.assertEqual(resp.status_code, 422)


class TestTenantAwareRateLimiter(unittest.TestCase):
    """Tests for RateLimitMiddleware tenant and tier sensitivity."""

    def test_rate_limiter_tier_limits(self):
        test_app = FastAPI()
        test_app.add_middleware(RateLimitMiddleware)

        @test_app.get("/api/data")
        def get_data():
            return {"data": 42}

        client = TestClient(test_app)

        # 1. Enterprise tier request
        resp_ent = client.get("/api/data", headers={"X-Org-Tier": "enterprise", "X-Org-ID": "ent-org-1"})
        self.assertEqual(resp_ent.status_code, 200)
        self.assertEqual(resp_ent.headers.get("x-ratelimit-limit"), "2400")

        # 2. Pro tier request
        resp_pro = client.get("/api/data", headers={"X-Org-Tier": "pro", "X-Org-ID": "pro-org-1"})
        self.assertEqual(resp_pro.status_code, 200)
        self.assertEqual(resp_pro.headers.get("x-ratelimit-limit"), "600")

        # 3. Starter tier request
        resp_starter = client.get("/api/data", headers={"X-Org-Tier": "starter", "X-Org-ID": "starter-org-1"})
        self.assertEqual(resp_starter.status_code, 200)
        self.assertEqual(resp_starter.headers.get("x-ratelimit-limit"), "120")

        # 4. Default / anonymous request
        resp_def = client.get("/api/data")
        self.assertEqual(resp_def.status_code, 200)
        self.assertEqual(resp_def.headers.get("x-ratelimit-limit"), "60")

    def test_rate_limiter_auth_endpoint_limit(self):
        test_app = FastAPI()
        test_app.add_middleware(RateLimitMiddleware)

        @test_app.post("/v1/auth/login")
        def mock_login():
            return {"status": "ok"}

        client = TestClient(test_app)
        resp = client.post("/v1/auth/login")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("x-ratelimit-limit"), "20")

    def test_rate_limiter_exceeded_returns_429(self):
        test_app = FastAPI()
        test_app.add_middleware(RateLimitMiddleware)

        @test_app.post("/v1/approvals/abc/decision")
        def mock_decision():
            return {"status": "approved"}

        client = TestClient(test_app)
        # Approval decision limit is 10 requests per minute
        headers = {"X-API-Key": "test-key-limit-exceed"}
        for i in range(10):
            r = client.post("/v1/approvals/abc/decision", headers=headers)
            self.assertEqual(r.status_code, 200)

        # 11th request must exceed limit and return 429
        r_exceeded = client.post("/v1/approvals/abc/decision", headers=headers)
        self.assertEqual(r_exceeded.status_code, 429)
        self.assertIn("Rate limit exceeded", r_exceeded.json()["detail"])
        self.assertEqual(r_exceeded.headers.get("x-ratelimit-remaining"), "0")
        self.assertIn("retry-after", r_exceeded.headers)
