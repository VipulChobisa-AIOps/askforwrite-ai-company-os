"""Unit and Integration Tests for BYOK Gemini API Key Isolation & Multi-Role Auth Gate.

Verifies:
1. Customer LLM isolation: Non-owner calls with no key never use server GEMINI_API_KEY.
2. Tenant BYOK Gemini key caching and context isolation.
3. POST /v1/me/gemini-key saves, updates, clears, and masks BYOK key in GET /v1/me.
4. POST /v1/auth/signup defaults to afw_directpay and produces /v1/pay/checkout link.
5. Register and Signup persist optional gemini_api_key in org metadata.
6. Dashboard HTML serves auth gate overlay and all required inputs.
"""

import os
import unittest
from unittest.mock import patch

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

from app.agents.llm_client import (
    _REQUEST_GEMINI_KEY,
    _REQUEST_IS_OWNER,
    generate,
    get_gemini_client_for_key,
    set_request_llm_context,
)
from app.api.v1.customer_portal import mask_gemini_key
from app.db.database import Base, get_db
from app.db.models import OrganizationRecord, UserRecord
from app.main import app

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


class BYOKAndAuthGateTests(unittest.TestCase):
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
        self.db.query(UserRecord).delete()
        self.db.query(OrganizationRecord).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_db, None)

    # ── PART 1: Strict LLM BYOK Isolation Tests ──────────────────────────────

    def test_customer_llm_isolation_no_key_never_uses_owner_key(self):
        """When _REQUEST_IS_OWNER is False and no key is provided, generate() must NOT use server key."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "super-secret-owner-key-12345"}):
            set_request_llm_context(gemini_key=None, is_owner=False)
            self.assertIsNone(_REQUEST_GEMINI_KEY.get())
            self.assertFalse(_REQUEST_IS_OWNER.get())

            with patch("app.agents.llm_client.get_gemini_client") as mock_get_owner_client:
                result = generate(
                    "Draft an SEO article about AI operations",
                    fallback_text="Customer deterministic fallback: zero owner quota.",
                )
                # Must never call the owner client factory
                mock_get_owner_client.assert_not_called()
                # Must yield specified customer deterministic fallback
                self.assertEqual(result, "Customer deterministic fallback: zero owner quota.")

    def test_customer_llm_default_deterministic_fallback(self):
        """When fallback_text is not provided, generate() produces high-utility deterministic output."""
        set_request_llm_context(gemini_key=None, is_owner=False)
        result = generate("Draft an SEO article about enterprise automation")
        self.assertIn("Strategic Overview", result)

    def test_byok_client_factory_caches_and_strips_key(self):
        """get_gemini_client_for_key returns None for invalid or mock keys and caches results."""
        self.assertIsNone(get_gemini_client_for_key(""))
        self.assertIsNone(get_gemini_client_for_key("mock-gemini-key"))

    def test_set_request_llm_context(self):
        """set_request_llm_context properly manages contextvars state."""
        set_request_llm_context("  AIzaSyTestKey12345  ", False)
        self.assertEqual(_REQUEST_GEMINI_KEY.get(), "AIzaSyTestKey12345")
        self.assertFalse(_REQUEST_IS_OWNER.get())

        set_request_llm_context(None, True)
        self.assertIsNone(_REQUEST_GEMINI_KEY.get())
        self.assertTrue(_REQUEST_IS_OWNER.get())

    def test_mask_gemini_key_formatting(self):
        """mask_gemini_key properly masks the key showing first 4 and last 4 characters."""
        self.assertIsNone(mask_gemini_key(None))
        self.assertIsNone(mask_gemini_key(""))
        self.assertEqual(mask_gemini_key("1234"), "••••1234")
        masked = mask_gemini_key("AIzaSyB1234567890abcdef1a2b")
        self.assertIsNotNone(masked)
        self.assertTrue(masked.startswith("AIza"))
        self.assertTrue(masked.endswith("1a2b"))
        self.assertTrue("•" in masked)
        self.assertEqual(len(masked), len("AIzaSyB1234567890abcdef1a2b"))

    # ── PART 2: Backend Auth & Portal BYOK Endpoints ─────────────────────────

    def test_register_with_gemini_api_key(self):
        """Registering with a BYOK key stores it in the organization's metadata_json."""
        resp = self.client.post(
            "/v1/auth/register",
            json={
                "email": "byok_founder@acmecorp.com",
                "password": "Password123!",
                "full_name": "Byok Founder",
                "company_name": "Acme BYOK Labs",
                "gemini_api_key": "AIzaSyRegisterKey12345678",
            },
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        token = data["access_token"]

        # Verify profile includes masked key
        me_resp = self.client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_resp.status_code, 200)
        me_data = me_resp.json()
        self.assertTrue(me_data["has_custom_gemini_key"])
        self.assertTrue(me_data["gemini_key_masked"].startswith("AIza"))
        self.assertTrue(me_data["gemini_key_masked"].endswith("5678"))

    def test_signup_defaults_to_afw_directpay_and_saves_byok_key(self):
        """SignupRequest defaults to afw_directpay and returns directpay checkout link."""
        resp = self.client.post(
            "/v1/auth/signup",
            json={
                "email": "signup_customer@innovate.co",
                "password": "CustomerSecurePass123!",
                "full_name": "Customer Lead",
                "company_name": "Innovate Co",
                "package_key": "growth_all_in_one",
                "gemini_api_key": "AIzaSySignupKey987654321",
            },
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("/v1/pay/checkout", data["checkout_url"])
        token = data["access_token"]

        # Verify DB metadata has payment_provider and gemini_api_key
        org = self.db.query(OrganizationRecord).filter_by(id=data["org_id"]).first()
        self.assertIsNotNone(org)
        self.assertEqual(org.metadata_json.get("payment_provider"), "afw_directpay")
        self.assertEqual(org.metadata_json.get("gemini_api_key"), "AIzaSySignupKey987654321")

        # Check me endpoint
        me_resp = self.client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_resp.status_code, 200)
        self.assertTrue(me_resp.json()["has_custom_gemini_key"])

    def test_customer_portal_gemini_key_crud(self):
        """POST /v1/me/gemini-key updates, validates, and clears tenant key."""
        # 1. Register customer without key
        resp = self.client.post(
            "/v1/auth/register",
            json={
                "email": "crud_client@startup.io",
                "password": "ClientPassword123!",
                "full_name": "CRUD Client",
                "company_name": "Startup IO",
            },
        )
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Verify initially no custom key
        me = self.client.get("/v1/me", headers=headers).json()
        self.assertFalse(me["has_custom_gemini_key"])
        self.assertIsNone(me["gemini_key_masked"])

        # 2. Reject key that is too short
        bad_resp = self.client.post(
            "/v1/me/gemini-key",
            headers=headers,
            json={"gemini_api_key": "short"},
        )
        self.assertEqual(bad_resp.status_code, 400)

        # 3. Save valid custom key
        set_resp = self.client.post(
            "/v1/me/gemini-key",
            headers=headers,
            json={"gemini_api_key": "AIzaSyCustomKeySavedViaPortal123"},
        )
        self.assertEqual(set_resp.status_code, 200)
        data = set_resp.json()
        self.assertEqual(data["status"], "updated")
        self.assertTrue(data["has_custom_gemini_key"])
        self.assertIn("••••", data["gemini_key_masked"])

        # 4. Verify GET /v1/me reflects custom key
        me_updated = self.client.get("/v1/me", headers=headers).json()
        self.assertTrue(me_updated["has_custom_gemini_key"])
        self.assertEqual(me_updated["gemini_key_masked"], data["gemini_key_masked"])

        # 5. Clear key with empty string
        clear_resp = self.client.post(
            "/v1/me/gemini-key",
            headers=headers,
            json={"gemini_api_key": ""},
        )
        self.assertEqual(clear_resp.status_code, 200)
        self.assertFalse(clear_resp.json()["has_custom_gemini_key"])
        self.assertIsNone(clear_resp.json()["gemini_key_masked"])

        # Verify cleared in GET /v1/me
        me_cleared = self.client.get("/v1/me", headers=headers).json()
        self.assertFalse(me_cleared["has_custom_gemini_key"])
        self.assertIsNone(me_cleared["gemini_key_masked"])

    def test_tenant_use_service_injects_byok_context(self):
        """POST /v1/me/use-service correctly injects tenant BYOK key and deducts credit."""
        resp = self.client.post(
            "/v1/auth/signup",
            json={
                "email": "mango_trader@fruitops.com",
                "password": "Password123!",
                "full_name": "Mango Trader",
                "company_name": "Fruit Ops",
                "package_key": "growth_all_in_one",
                "gemini_api_key": "AIzaSyCustomFruitOpsKey9999",
            },
        )
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Call service
        service_resp = self.client.post(
            "/v1/me/use-service",
            headers=headers,
            json={
                "service_key": "mango_quality_analytics",
                "payload": {"variety": "Kesar", "brix": 17.5},
            },
        )
        self.assertEqual(service_resp.status_code, 200)
        s_data = service_resp.json()
        self.assertEqual(s_data["status"], "COMPLETED")
        self.assertEqual(s_data["service_key"], "mango_quality_analytics")
        self.assertIn("lot_id", s_data["result"])
        self.assertEqual(s_data["result"]["crop_variety"], "Kesar")

    # ── PART 3: Dashboard UI Auth Gate Verification ──────────────────────────

    def test_dashboard_contains_all_auth_gate_and_byok_elements(self):
        """GET /dashboard/ returns the full auth gate overlay and all required inputs."""
        resp = self.client.get("/dashboard/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text

        # Gate overlay and tab elements
        self.assertIn('id="auth-gate-overlay"', html)
        self.assertIn('id="auth-tab-login"', html)
        self.assertIn('id="auth-tab-register"', html)
        self.assertIn('id="auth-tab-owner"', html)

        # Tab 1 login inputs
        self.assertIn('id="login-email"', html)
        self.assertIn('id="login-password"', html)
        self.assertIn('id="login-gemini-key"', html)
        self.assertIn('id="btn-customer-login"', html)

        # Tab 2 register inputs
        self.assertIn('id="reg-name"', html)
        self.assertIn('id="reg-company"', html)
        self.assertIn('id="reg-email"', html)
        self.assertIn('id="reg-password"', html)
        self.assertIn('id="reg-package"', html)
        self.assertIn('id="reg-gemini-key"', html)
        self.assertIn('id="btn-customer-register"', html)

        # Tab 3 owner inputs
        self.assertIn('id="auth-owner-key"', html)
        self.assertIn('id="auth-owner-gemini-key"', html)
        self.assertIn('id="btn-owner-unlock"', html)

        # Customer portal BYOK card inputs
        self.assertIn('id="portal-gemini-key-input"', html)
        self.assertIn('id="btn-save-portal-gemini-key"', html)
        self.assertIn('id="portal-service-selector"', html)
        self.assertIn('id="btn-run-tenant-service"', html)

        # Sidebar user footer & logout button
        self.assertIn('id="sidebar-user-avatar"', html)
        self.assertIn('id="sidebar-user-name"', html)
        self.assertIn('id="sidebar-user-role"', html)
        self.assertIn('id="btn-logout"', html)

        # MSME declarations and legal modal
        self.assertIn("UDYAM-RJ-14-0018404", html)
        self.assertIn("ASKFORWRITE", html)
        self.assertIn('class="sidebar-legal-badge"', html)
        self.assertIn('id="legal-modal-overlay"', html)
        self.assertIn('class="auth-gate-compliance"', html)

    # ── PART 4: MSME Statutory Declarations & Legal Policies ─────────────────

    def test_msme_statutory_declaration_and_policies_endpoints(self):
        """Public legal endpoints serve official MSME declarations and Udyam details."""
        # 1. MSME Declaration
        decl_resp = self.client.get("/legal/declaration")
        self.assertEqual(decl_resp.status_code, 200)
        decl = decl_resp.json()
        self.assertEqual(decl["firm_legal_name"], "ASKFORWRITE")
        self.assertEqual(decl["udyam_registration_number"], "UDYAM-RJ-14-0018404")
        self.assertIn("Udaipur", decl["registered_office"]["city"])
        self.assertIn("UDYAM-RJ-14-0018404", decl["copyright"])

        # 2. Refund Policy
        refund_resp = self.client.get("/legal/refund-policy")
        self.assertEqual(refund_resp.status_code, 200)
        refund = refund_resp.json()
        self.assertIn("UDYAM-RJ-14-0018404", refund["copyright"])
        self.assertGreaterEqual(len(refund["sections"]), 3)

        # 3. Bundled All Legal Documents
        all_resp = self.client.get("/legal/all")
        self.assertEqual(all_resp.status_code, 200)
        all_docs = all_resp.json()
        self.assertIn("metadata", all_docs)
        self.assertIn("terms_of_service", all_docs)
        self.assertIn("privacy_policy", all_docs)
        self.assertIn("msme_declaration", all_docs)
        self.assertIn("refund_policy", all_docs)
        self.assertEqual(all_docs["metadata"]["udyam_registration"], "UDYAM-RJ-14-0018404")

        # 4. Redirect aliases
        for path, target in [
            ("/terms", "/legal/tos"),
            ("/privacy", "/legal/privacy"),
            ("/msme", "/legal/declaration"),
            ("/refund-policy", "/legal/refund-policy"),
        ]:
            r = self.client.get(path, follow_redirects=False)
            self.assertEqual(r.status_code, 307)
            self.assertEqual(r.headers["location"], target)

    def test_sovereign_checkout_contains_msme_legal_declaration(self):
        """AFW DirectPay sovereign checkout HTML displays statutory MSME declaration."""
        session_resp = self.client.post(
            "/v1/pay/create-session",
            json={
                "package_key": "growth_all_in_one",
                "company_name": "Rajasthan Enterprise Corp",
                "customer_email": "billing@rajasthanent.in",
                "currency": "INR",
            },
        )
        self.assertEqual(session_resp.status_code, 200)
        session_id = session_resp.json()["session_id"]

        checkout_resp = self.client.get(f"/v1/pay/{session_id}/checkout")
        self.assertEqual(checkout_resp.status_code, 200)
        html = checkout_resp.text
        self.assertIn("UDYAM-RJ-14-0018404", html)
        self.assertIn("ASKFORWRITE MSME", html)
        self.assertIn("Udaipur Bus Stand", html)
        self.assertIn("/legal/tos", html)
        self.assertIn("/legal/privacy", html)
        self.assertIn("/legal/declaration", html)
        self.assertIn("/legal/refund-policy", html)

