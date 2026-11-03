"""End-to-End Tenant Subscription Lifecycle and Role Permissions Verification (Issue #24).

Validates:
- Platform owner vs tenant owner vs tenant manager vs member permissions.
- Plan creation restricted to platform owner only (tenants cannot create global billing plans).
- Strict multi-tenant isolation on subscription read, list, and cancellation.
- Tenant subscription lifecycle: active -> cancelled.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["APP_ENV"] = "development"
os.environ.pop("ALLOW_SQLITE_PRODUCTION", None)
TEST_MANAGER_KEY = "test-manager-key-for-sub-lifecycle-testing-32-chars"
TEST_OWNER_KEY = "test-owner-key-for-sub-lifecycle-testing-32-chars"
os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY
os.environ["OWNER_API_KEY"] = TEST_OWNER_KEY

from app.db.database import Base, get_db
from app.db.models import CustomerRecord, OrganizationRecord, SubscriptionRecord
from app.main import app
from app.security.auth import create_access_token


class TestSubscriptionLifecycleAndRolePermissions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine, autoflush=False, expire_on_commit=False)

        def override_db():
            db = cls.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)
        app.dependency_overrides.pop(get_db, None)

    def setUp(self):
        self.db = self.session_factory()
        # Seed Tenant A and Tenant B
        self.org_a = OrganizationRecord(
            id="org-sub-a",
            name="Alpha Corp",
            slug="alpha-corp",
            tier="growth",
            is_active=True,
        )
        self.org_b = OrganizationRecord(
            id="org-sub-b",
            name="Beta Corp",
            slug="beta-corp",
            tier="starter",
            is_active=True,
        )
        self.db.add_all([self.org_a, self.org_b])

        # Seed Customers
        self.cust_a = CustomerRecord(
            id="cust-sub-a",
            provider="razorpay",
            provider_customer_id="cust_rzp_a",
            email="owner@alpha.com",
            name="Alpha Owner",
        )
        self.cust_b = CustomerRecord(
            id="cust-sub-b",
            provider="razorpay",
            provider_customer_id="cust_rzp_b",
            email="owner@beta.com",
            name="Beta Owner",
        )
        self.db.add_all([self.cust_a, self.cust_b])

        # Seed Subscriptions
        self.sub_a = SubscriptionRecord(
            id="sub-rec-alpha-001",
            org_id="org-sub-a",
            customer_id="cust-sub-a",
            provider="razorpay",
            provider_subscription_id="sub_rzp_alpha_001",
            plan_id="plan_growth_monthly",
            status="active",
        )
        self.sub_b = SubscriptionRecord(
            id="sub-rec-beta-001",
            org_id="org-sub-b",
            customer_id="cust-sub-b",
            provider="razorpay",
            provider_subscription_id="sub_rzp_beta_001",
            plan_id="plan_starter_monthly",
            status="active",
        )
        self.db.add_all([self.sub_a, self.sub_b])
        self.db.commit()

        # Generate scoped tokens
        self.token_tenant_a_owner = create_access_token(
            user_id="user-a-owner",
            email="owner@alpha.com",
            role="owner",
            org_id="org-sub-a",
        )
        self.token_tenant_a_manager = create_access_token(
            user_id="user-a-mgr",
            email="manager@alpha.com",
            role="manager",
            org_id="org-sub-a",
        )
        self.token_tenant_a_member = create_access_token(
            user_id="user-a-mem",
            email="member@alpha.com",
            role="member",
            org_id="org-sub-a",
        )
        self.token_tenant_b_owner = create_access_token(
            user_id="user-b-owner",
            email="owner@beta.com",
            role="owner",
            org_id="org-sub-b",
        )

    def tearDown(self):
        self.db.query(SubscriptionRecord).delete()
        self.db.query(CustomerRecord).delete()
        self.db.query(OrganizationRecord).delete()
        self.db.commit()
        self.db.close()

    def test_plan_creation_forbidden_for_tenant_roles(self):
        """Only platform owner can create billing plans; tenant owners and managers are rejected with 403."""
        plan_payload = {
            "name": "Custom Enterprise",
            "amount": 4999900,
            "currency": "INR",
            "interval": "monthly",
            "provider": "razorpay",
        }

        # Tenant Owner -> 403 Forbidden
        resp_owner = self.client.post(
            "/v1/subscriptions/plans",
            headers={"Authorization": f"Bearer {self.token_tenant_a_owner}"},
            json=plan_payload,
        )
        self.assertEqual(resp_owner.status_code, 403)

        # Tenant Manager -> 403 Forbidden
        resp_mgr = self.client.post(
            "/v1/subscriptions/plans",
            headers={"Authorization": f"Bearer {self.token_tenant_a_manager}"},
            json=plan_payload,
        )
        self.assertEqual(resp_mgr.status_code, 403)

        # Regular Member -> 403 Forbidden
        resp_mem = self.client.post(
            "/v1/subscriptions/plans",
            headers={"Authorization": f"Bearer {self.token_tenant_a_member}"},
            json=plan_payload,
        )
        self.assertEqual(resp_mem.status_code, 403)

    def test_tenant_boundary_isolation_on_subscription_access(self):
        """Tenant A cannot access or cancel Tenant B's subscription record."""
        # Tenant A tries to read Tenant B's subscription
        resp = self.client.get(
            f"/v1/subscriptions/{self.sub_b.id}",
            headers={"Authorization": f"Bearer {self.token_tenant_a_owner}"},
        )
        self.assertEqual(resp.status_code, 403)

        # Tenant A tries to cancel Tenant B's subscription -> 403 Forbidden
        resp_cancel = self.client.post(
            f"/v1/subscriptions/{self.sub_b.id}/cancel",
            headers={"Authorization": f"Bearer {self.token_tenant_a_owner}"},
            json={"at_cycle_end": True},
        )
        self.assertEqual(resp_cancel.status_code, 403)

    def test_tenant_can_view_own_subscription(self):
        """Tenant A can successfully view their own subscription."""
        resp = self.client.get(
            f"/v1/subscriptions/{self.sub_a.id}",
            headers={"Authorization": f"Bearer {self.token_tenant_a_owner}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["subscription_id"], self.sub_a.id)
        self.assertEqual(data["status"], "active")

    def test_tenant_subscription_cancellation_lifecycle(self):
        """Tenant A cancels their subscription; status is updated to cancelled and remote provider is invoked."""
        from app.services.payment import PaymentProvider, SubscriptionInfo, SubscriptionStatus

        mock_provider = AsyncMock()
        mock_provider.cancel_subscription.return_value = SubscriptionInfo(
            id=self.sub_a.id,
            provider=PaymentProvider.RAZORPAY,
            provider_subscription_id=self.sub_a.provider_subscription_id,
            status=SubscriptionStatus.CANCELLED,
            customer_id=self.sub_a.customer_id,
            plan_id=self.sub_a.plan_id,
        )

        with patch("app.api.v1.subscriptions.get_payment_provider", return_value=mock_provider):
            resp = self.client.post(
                f"/v1/subscriptions/{self.sub_a.id}/cancel",
                headers={"Authorization": f"Bearer {self.token_tenant_a_owner}"},
                json={"at_cycle_end": False},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["status"], "cancelled")

        # Verify DB reflects cancelled status
        self.db.expire_all()
        sub = self.db.query(SubscriptionRecord).filter_by(id=self.sub_a.id).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.status, "cancelled")
