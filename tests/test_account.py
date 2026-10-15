"""Unit tests for Multi-Tenant Account, User, and Invoice management."""

import os
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set up test environment variables before importing app
os.environ["APP_ENV"] = "development"
os.environ.pop("ALLOW_SQLITE_PRODUCTION", None)
TEST_MANAGER_KEY = "test-manager-key-for-unit-testing-which-is-at-least-32-chars-long"
TEST_OWNER_KEY = "test-owner-key-for-unit-testing-which-is-at-least-32-chars-long"
os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY
os.environ["OWNER_API_KEY"] = TEST_OWNER_KEY

from app.db.database import Base, get_db
from app.db.models import (
    CustomerRecord,
    InvoiceRecord,
    OrganizationRecord,
    SubscriptionRecord,
    UserRecord,
)
from app.main import app

# Create in-memory SQLite database for testing
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

MANAGER_HEADERS = {"X-API-Key": TEST_MANAGER_KEY}
OWNER_HEADERS = {"X-API-Key": TEST_OWNER_KEY}


class AccountServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=test_engine)

    def setUp(self):
        os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY
        os.environ["OWNER_API_KEY"] = TEST_OWNER_KEY
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        # Clear data before each test
        with TestingSessionLocal() as session:
            session.query(InvoiceRecord).delete()
            session.query(SubscriptionRecord).delete()
            session.query(CustomerRecord).delete()
            session.query(UserRecord).delete()
            session.query(OrganizationRecord).delete()
            session.commit()

    def test_create_organization_success(self):
        resp = self.client.post(
            "/v1/accounts/orgs",
            headers=MANAGER_HEADERS,
            json={
                "name": "Acme Technologies",
                "tier": "pro",
                "metadata": {"industry": "EdTech"},
            },
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["name"], "Acme Technologies")
        self.assertEqual(data["slug"], "acme-technologies")
        self.assertEqual(data["tier"], "pro")
        self.assertEqual(data["lead_credits_limit"], 500)
        self.assertEqual(data["outreach_credits_limit"], 250)
        self.assertEqual(data["lead_credits_used"], 0)
        self.assertTrue(data["is_active"])

    def test_create_organization_slug_uniqueness(self):
        # Create first org
        self.client.post(
            "/v1/accounts/orgs",
            headers=MANAGER_HEADERS,
            json={"name": "Alpha Corp"},
        )
        # Create second org with identical name
        resp2 = self.client.post(
            "/v1/accounts/orgs",
            headers=MANAGER_HEADERS,
            json={"name": "Alpha Corp"},
        )
        self.assertEqual(resp2.status_code, 201)
        data2 = resp2.json()
        self.assertEqual(data2["slug"], "alpha-corp-1")

    def test_list_and_get_organization_summary(self):
        # Create org
        org_resp = self.client.post(
            "/v1/accounts/orgs",
            headers=MANAGER_HEADERS,
            json={"name": "Beta Inc", "tier": "starter"},
        ).json()
        org_id = org_resp["id"]

        # Add a user
        self.client.post(
            f"/v1/accounts/orgs/{org_id}/users",
            headers=MANAGER_HEADERS,
            json={"email": "alice@beta.com", "full_name": "Alice Smith", "role": "admin"},
        )

        # Record an invoice
        self.client.post(
            f"/v1/accounts/orgs/{org_id}/invoices",
            headers=MANAGER_HEADERS,
            json={
                "customer_id": "cust-123",
                "provider": "razorpay",
                "provider_invoice_id": "inv_beta_001",
                "amount": 499900,
                "currency": "INR",
                "status": "paid",
            },
        )

        # Get summary
        summary_resp = self.client.get(f"/v1/accounts/orgs/{org_id}", headers=MANAGER_HEADERS)
        self.assertEqual(summary_resp.status_code, 200)
        summary = summary_resp.json()
        self.assertEqual(summary["org"]["name"], "Beta Inc")
        self.assertEqual(summary["members_count"], 1)
        self.assertEqual(len(summary["recent_invoices"]), 1)
        self.assertEqual(summary["recent_invoices"][0]["amount"], 499900)

    def test_update_organization_requires_owner(self):
        org = self.client.post(
            "/v1/accounts/orgs",
            headers=MANAGER_HEADERS,
            json={"name": "Gamma Corp", "tier": "starter"},
        ).json()
        org_id = org["id"]

        # Manager attempt should fail (requires owner)
        manager_attempt = self.client.patch(
            f"/v1/accounts/orgs/{org_id}",
            headers=MANAGER_HEADERS,
            json={"tier": "enterprise"},
        )
        self.assertEqual(manager_attempt.status_code, 403)

        # Owner attempt should succeed
        owner_attempt = self.client.patch(
            f"/v1/accounts/orgs/{org_id}",
            headers=OWNER_HEADERS,
            json={"tier": "enterprise"},
        )
        self.assertEqual(owner_attempt.status_code, 200)
        updated = owner_attempt.json()
        self.assertEqual(updated["tier"], "enterprise")
        self.assertEqual(updated["lead_credits_limit"], 5000)

    def test_user_membership_crud(self):
        org = self.client.post(
            "/v1/accounts/orgs",
            headers=MANAGER_HEADERS,
            json={"name": "Delta Systems"},
        ).json()
        org_id = org["id"]

        # Add user
        create_user = self.client.post(
            f"/v1/accounts/orgs/{org_id}/users",
            headers=MANAGER_HEADERS,
            json={"email": "bob@delta.com", "full_name": "Bob Builder", "role": "member"},
        )
        self.assertEqual(create_user.status_code, 201)
        user_id = create_user.json()["id"]

        # Duplicate email in same org rejected
        dup_user = self.client.post(
            f"/v1/accounts/orgs/{org_id}/users",
            headers=MANAGER_HEADERS,
            json={"email": "bob@delta.com", "full_name": "Bob Another"},
        )
        self.assertEqual(dup_user.status_code, 409)

        # List users
        users_resp = self.client.get(f"/v1/accounts/orgs/{org_id}/users", headers=MANAGER_HEADERS)
        self.assertEqual(users_resp.status_code, 200)
        self.assertEqual(len(users_resp.json()), 1)

        # Delete user
        del_resp = self.client.delete(f"/v1/accounts/orgs/{org_id}/users/{user_id}", headers=MANAGER_HEADERS)
        self.assertEqual(del_resp.status_code, 204)

        # Re-check list
        users_after = self.client.get(f"/v1/accounts/orgs/{org_id}/users", headers=MANAGER_HEADERS).json()
        self.assertEqual(len(users_after), 0)

    def test_credit_quota_consumption_and_limits(self):
        # Create free tier org (limit = 20 lead credits)
        org = self.client.post(
            "/v1/accounts/orgs",
            headers=MANAGER_HEADERS,
            json={"name": "Epsilon Labs", "tier": "free"},
        ).json()
        org_id = org["id"]

        # Consume 15 credits
        consume_resp = self.client.post(
            f"/v1/accounts/orgs/{org_id}/consume-credits",
            headers=MANAGER_HEADERS,
            json={"credit_type": "lead", "amount": 15},
        )
        self.assertEqual(consume_resp.status_code, 200)
        self.assertEqual(consume_resp.json()["credits_remaining"], 5)

        # Attempt to consume 10 more (15 + 10 = 25 > 20 limit) -> Expect 402 Payment Required
        over_resp = self.client.post(
            f"/v1/accounts/orgs/{org_id}/consume-credits",
            headers=MANAGER_HEADERS,
            json={"credit_type": "lead", "amount": 10},
        )
        self.assertEqual(over_resp.status_code, 402)
        self.assertIn("Lead credit quota exceeded", over_resp.json()["detail"])

    def test_inactive_org_blocks_credit_consumption(self):
        org = self.client.post(
            "/v1/accounts/orgs",
            headers=MANAGER_HEADERS,
            json={"name": "Zeta Corp"},
        ).json()
        org_id = org["id"]

        # Deactivate org as owner
        self.client.patch(
            f"/v1/accounts/orgs/{org_id}",
            headers=OWNER_HEADERS,
            json={"is_active": False},
        )

        # Attempt to consume credits
        resp = self.client.post(
            f"/v1/accounts/orgs/{org_id}/consume-credits",
            headers=MANAGER_HEADERS,
            json={"credit_type": "outreach", "amount": 1},
        )
        self.assertEqual(resp.status_code, 403)

    def test_cross_tenant_isolation_enforcement(self):
        """Verify that a bearer token tied to Org A is strictly forbidden from accessing Org B."""
        from app.security.auth import create_access_token

        # Create Org A and Org B
        org_a = self.client.post(
            "/v1/accounts/orgs",
            headers=MANAGER_HEADERS,
            json={"name": "Tenant Alpha"},
        ).json()
        org_b = self.client.post(
            "/v1/accounts/orgs",
            headers=MANAGER_HEADERS,
            json={"name": "Tenant Beta"},
        ).json()

        # Generate access token for Tenant Alpha member
        alpha_token = create_access_token(
            user_id="user-alpha-1",
            email="manager@alpha.com",
            role="manager",
            org_id=org_a["id"],
        )
        alpha_headers = {"Authorization": f"Bearer {alpha_token}"}

        # 1. Tenant Alpha can access their own org summary
        resp_own = self.client.get(f"/v1/accounts/orgs/{org_a['id']}", headers=alpha_headers)
        self.assertEqual(resp_own.status_code, 200)

        # 2. Tenant Alpha is BLOCKED from accessing Tenant Beta summary (403 Forbidden)
        resp_cross = self.client.get(f"/v1/accounts/orgs/{org_b['id']}", headers=alpha_headers)
        self.assertEqual(resp_cross.status_code, 403)
        self.assertIn("Access denied", resp_cross.json()["detail"])

        # 3. Tenant Alpha is BLOCKED from adding members to Tenant Beta
        resp_cross_user = self.client.post(
            f"/v1/accounts/orgs/{org_b['id']}/users",
            headers=alpha_headers,
            json={"email": "attacker@beta.com", "full_name": "Attacker", "role": "admin"},
        )
        self.assertEqual(resp_cross_user.status_code, 403)

