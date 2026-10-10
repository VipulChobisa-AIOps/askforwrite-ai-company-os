"""Unit tests for User Authentication, Password Hashing, and Role Separation (Admin vs Customer)."""

import os
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["APP_ENV"] = "development"
os.environ.pop("ALLOW_SQLITE_PRODUCTION", None)
TEST_MANAGER_KEY = "test-manager-key-for-unit-testing-which-is-at-least-32-chars-long"
TEST_OWNER_KEY = "test-owner-key-for-unit-testing-which-is-at-least-32-chars-long"
os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY
os.environ["OWNER_API_KEY"] = TEST_OWNER_KEY

from app.db.database import Base, get_db
from app.db.models import OrganizationRecord, UserRecord
from app.main import app
from app.security.auth import hash_password, verify_password

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


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=test_engine)

    def setUp(self):
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.db = TestingSessionLocal()
        # Clean tables
        self.db.query(UserRecord).delete()
        self.db.query(OrganizationRecord).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_db, None)

    def test_password_hash_and_verify(self):
        """Test PBKDF2 password hashing and verification."""
        password = "SecurePassword123!"
        hashed = hash_password(password)
        self.assertTrue(hashed.startswith("pbkdf2:sha256:"))
        self.assertTrue(verify_password(password, hashed))
        self.assertFalse(verify_password("WrongPassword!", hashed))

    def test_register_creates_org_and_admin_user(self):
        """Registering a new organization creates tenant and returns bearer token."""
        resp = self.client.post(
            "/v1/auth/register",
            json={
                "email": "buyer@acmecorp.com",
                "password": "BuyerPassword123!",
                "full_name": "Alice Buyer",
                "company_name": "Acme Industrial Corp",
                "role": "admin",
            },
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["email"], "buyer@acmecorp.com")
        self.assertEqual(data["role"], "admin")
        self.assertTrue(data["access_token"])
        self.assertTrue(data["portal_access"]["admin"])
        self.assertTrue(data["portal_access"]["customer"])

        # Verify DB persistence
        user = self.db.query(UserRecord).filter_by(email="buyer@acmecorp.com").first()
        self.assertIsNotNone(user)
        self.assertTrue(verify_password("BuyerPassword123!", user.password_hash))

    def test_login_successful_and_fetch_profile(self):
        """Test login with email/password and subsequent GET /v1/auth/me using Bearer token."""
        # 1. Register
        self.client.post(
            "/v1/auth/register",
            json={
                "email": "client@techstartup.in",
                "password": "StartupSecret2026!",
                "full_name": "Rajesh Kumar",
                "company_name": "TechStartup IN",
                "role": "customer",
            },
        )

        # 2. Login
        login_resp = self.client.post(
            "/v1/auth/login",
            json={
                "email": "client@techstartup.in",
                "password": "StartupSecret2026!",
                "portal": "customer",
            },
        )
        self.assertEqual(login_resp.status_code, 200)
        token = login_resp.json()["access_token"]

        # 3. Access profile via Bearer token
        me_resp = self.client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(me_resp.status_code, 200)
        me_data = me_resp.json()
        self.assertEqual(me_data["email"], "client@techstartup.in")
        self.assertEqual(me_data["org_name"], "TechStartup IN")
        self.assertEqual(me_data["tier"], "free")
        self.assertGreaterEqual(me_data["lead_credits_remaining"], 20)

    def test_login_wrong_password_returns_401(self):
        """Login with wrong password fails with 401."""
        self.client.post(
            "/v1/auth/register",
            json={
                "email": "user@example.com",
                "password": "CorrectPassword123!",
                "full_name": "John Doe",
                "company_name": "Example Corp",
            },
        )

        resp = self.client.post(
            "/v1/auth/login",
            json={
                "email": "user@example.com",
                "password": "WrongPassword123!",
            },
        )
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Invalid email or password", resp.json()["detail"])

    def test_admin_portal_rejects_non_admin_role(self):
        """Attempting to login to admin portal with a regular customer/member role returns 403."""
        # Create organization and member user directly
        org = OrganizationRecord(
            name="Simple Client Org",
            slug="simple-client",
            tier="free",
        )
        self.db.add(org)
        self.db.commit()

        user = UserRecord(
            org_id=org.id,
            email="member@simpleclient.com",
            full_name="Member User",
            role="member",  # Regular member, not admin or owner
            password_hash=hash_password("MemberPassword123!"),
            is_active=True,
        )
        self.db.add(user)
        self.db.commit()

        # Try admin portal login
        resp = self.client.post(
            "/v1/auth/login",
            json={
                "email": "member@simpleclient.com",
                "password": "MemberPassword123!",
                "portal": "admin",
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Admin access required", resp.json()["detail"])
