"""Phase 4 Market Entry Tests.

Validates the final production-hardening layer:
1. Customer Self-Service Portal (/v1/me/*)
2. Audit Log Export (JSON + CSV) (/v1/audit/*)
3. Legal Endpoints (/legal/tos, /legal/privacy)
4. Billing Enforcement (quota wall returns HTTP 402)
5. OpenAPI Schema Completeness
"""

import io
import os
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import AuditLog, InvoiceRecord, OrganizationRecord, UserRecord
from app.main import app
from app.security.auth import create_access_token, hash_password, verify_password

# ── Test setup ────────────────────────────────────────────────────────────────


class Phase4BaseTest(unittest.TestCase):
    """Shared in-memory DB and TestClient setup for all Phase 4 tests."""

    @classmethod
    def setUpClass(cls):
        os.environ["APP_ENV"] = "development"
        cls.manager_key = "test-manager-api-key-32-chars-long-xxx"
        cls.owner_key = "test-owner-api-key-32-chars-long-xxx"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        os.environ["OWNER_API_KEY"] = cls.owner_key

        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.session_factory = sessionmaker(
            bind=cls.engine, autoflush=False, expire_on_commit=False
        )

        def override_get_db():
            s = cls.session_factory()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)
        cls.db = cls.session_factory()

        # Seed an org + user for portal tests
        cls.org = OrganizationRecord(
            id="ph4-org-001",
            name="Phase4 Corp",
            slug="phase4-corp",
            tier="modular_field_ops",
            lead_credits_limit=50,
            lead_credits_used=20,
            outreach_credits_limit=25,
            outreach_credits_used=5,
            is_active=True,
            metadata_json={"package_key": "field_force", "package_name": "Field Operations Suite"},
        )
        cls.user = UserRecord(
            id="ph4-user-001",
            org_id="ph4-org-001",
            email="admin@phase4corp.com",
            full_name="Phase Four Admin",
            role="admin",
            password_hash=hash_password("SecurePass123!"),
            is_active=True,
        )
        cls.db.add(cls.org)
        cls.db.add(cls.user)

        # Seed an invoice
        cls.invoice = InvoiceRecord(
            id="ph4-inv-001",
            org_id="ph4-org-001",
            customer_id="ph4-cust-001",
            provider="razorpay",
            provider_invoice_id="inv_ph4test001",
            provider_payment_id="pay_ph4test001",
            amount=399900,
            currency="INR",
            status="paid",
            metadata_json={"package_key": "field_force"},
        )
        cls.db.add(cls.invoice)

        # Seed some audit logs
        for i in range(5):
            cls.db.add(
                AuditLog(
                    task_id=f"task-ph4-{i}",
                    correlation_id=f"corr-ph4-{i}",
                    agent_id="test_agent",
                    capability_name="field_attendance" if i % 2 == 0 else "lead_discovery",
                    action="check_in" if i % 2 == 0 else "execute_discovery",
                    input_payload={"org_id": "ph4-org-001"},
                    output_payload={"result": "ok"},
                    status="COMPLETED",
                )
            )
        cls.db.commit()

        # JWT bearer token for the seeded user
        cls.bearer_token = create_access_token(
            user_id="ph4-user-001",
            email="admin@phase4corp.com",
            role="admin",
            org_id="ph4-org-001",
        )
        cls.auth_headers = {"Authorization": f"Bearer {cls.bearer_token}"}

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(cls.engine)


# ── 1. Customer Self-Service Portal Tests ─────────────────────────────────────


class TestCustomerPortalGetMe(Phase4BaseTest):
    """Tests for GET /v1/me — user profile and org summary."""

    def test_get_me_returns_full_profile(self):
        resp = self.client.get("/v1/me", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()

        self.assertEqual(data["user_id"], "ph4-user-001")
        self.assertEqual(data["email"], "admin@phase4corp.com")
        self.assertEqual(data["full_name"], "Phase Four Admin")
        self.assertEqual(data["role"], "admin")
        self.assertEqual(data["org_id"], "ph4-org-001")
        self.assertEqual(data["org_name"], "Phase4 Corp")
        self.assertEqual(data["tier"], "modular_field_ops")
        self.assertTrue(data["is_active"])
        self.assertIn("credits", data)
        self.assertIn("capabilities", data)
        self.assertIn("portal_url", data)

    def test_get_me_credit_balance_correct(self):
        resp = self.client.get("/v1/me", headers=self.auth_headers)
        credits = resp.json()["credits"]

        self.assertEqual(credits["lead_credits_limit"], 50)
        self.assertEqual(credits["lead_credits_used"], 20)
        self.assertEqual(credits["lead_credits_remaining"], 30)
        self.assertAlmostEqual(credits["lead_utilization_pct"], 40.0)

        self.assertEqual(credits["outreach_credits_limit"], 25)
        self.assertEqual(credits["outreach_credits_used"], 5)
        self.assertEqual(credits["outreach_credits_remaining"], 20)
        self.assertAlmostEqual(credits["outreach_utilization_pct"], 20.0)

    def test_get_me_capabilities_not_empty(self):
        resp = self.client.get("/v1/me", headers=self.auth_headers)
        capabilities = resp.json()["capabilities"]
        self.assertIsInstance(capabilities, list)
        self.assertGreater(len(capabilities), 0)
        # Each capability entry should have name and description
        for cap in capabilities:
            self.assertIn("capability", cap)
            self.assertIn("description", cap)

    def test_get_me_requires_auth(self):
        resp = self.client.get("/v1/me")
        self.assertEqual(resp.status_code, 401)

    def test_get_me_invalid_token_rejected(self):
        resp = self.client.get("/v1/me", headers={"Authorization": "Bearer invalid.token.here"})
        self.assertEqual(resp.status_code, 401)


class TestCustomerPortalUsage(Phase4BaseTest):
    """Tests for GET /v1/me/usage — credit usage endpoint."""

    def test_usage_endpoint_returns_credit_breakdown(self):
        resp = self.client.get("/v1/me/usage", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()

        self.assertIn("lead_credits_limit", data)
        self.assertIn("lead_credits_used", data)
        self.assertIn("lead_credits_remaining", data)
        self.assertIn("lead_utilization_pct", data)
        self.assertIn("outreach_credits_limit", data)
        self.assertIn("outreach_credits_remaining", data)

    def test_usage_values_match_profile(self):
        usage = self.client.get("/v1/me/usage", headers=self.auth_headers).json()
        profile_credits = self.client.get("/v1/me", headers=self.auth_headers).json()["credits"]
        self.assertEqual(usage["lead_credits_used"], profile_credits["lead_credits_used"])
        self.assertEqual(usage["lead_credits_remaining"], profile_credits["lead_credits_remaining"])


class TestCustomerPortalBilling(Phase4BaseTest):
    """Tests for GET /v1/me/billing — invoice history endpoint."""

    def test_billing_returns_invoice_list(self):
        resp = self.client.get("/v1/me/billing", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        invoices = resp.json()
        self.assertIsInstance(invoices, list)
        self.assertGreater(len(invoices), 0)

    def test_billing_invoice_fields_present(self):
        invoices = self.client.get("/v1/me/billing", headers=self.auth_headers).json()
        inv = invoices[0]
        self.assertIn("invoice_id", inv)
        self.assertIn("amount", inv)
        self.assertIn("currency", inv)
        self.assertIn("status", inv)
        self.assertIn("provider", inv)
        self.assertIn("created_at", inv)

    def test_billing_invoice_values_correct(self):
        invoices = self.client.get("/v1/me/billing", headers=self.auth_headers).json()
        inv = invoices[0]
        self.assertEqual(inv["invoice_id"], "ph4-inv-001")
        self.assertEqual(inv["amount"], 399900)
        self.assertEqual(inv["currency"], "INR")
        self.assertEqual(inv["status"], "paid")
        self.assertEqual(inv["provider"], "razorpay")


class TestCustomerPortalCapabilities(Phase4BaseTest):
    """Tests for GET /v1/me/capabilities — entitled capabilities endpoint."""

    def test_capabilities_endpoint_returns_list(self):
        resp = self.client.get("/v1/me/capabilities", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        caps = resp.json()
        self.assertIsInstance(caps, list)
        self.assertGreater(len(caps), 0)

    def test_each_capability_has_description(self):
        caps = self.client.get("/v1/me/capabilities", headers=self.auth_headers).json()
        for cap in caps:
            self.assertIn("capability", cap)
            self.assertIn("description", cap)
            self.assertIsInstance(cap["description"], str)
            self.assertGreater(len(cap["description"]), 0)


class TestPasswordChange(Phase4BaseTest):
    """Tests for POST /v1/me/change-password."""

    def test_password_change_success(self):
        # Use a separate user so we don't break other tests
        db = self.session_factory()
        new_user = UserRecord(
            id="ph4-pw-change-user",
            org_id="ph4-org-001",
            email="pwchange@phase4corp.com",
            full_name="PW Change User",
            role="member",
            password_hash=hash_password("OldPassword123"),
            is_active=True,
        )
        db.add(new_user)
        db.commit()
        db.close()

        token = create_access_token(
            user_id="ph4-pw-change-user",
            email="pwchange@phase4corp.com",
            role="member",
            org_id="ph4-org-001",
        )

        resp = self.client.post(
            "/v1/me/change-password",
            json={"current_password": "OldPassword123", "new_password": "NewSecurePass456!"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "password_updated")

        # Verify the new password actually works
        db2 = self.session_factory()
        updated = db2.get(UserRecord, "ph4-pw-change-user")
        self.assertTrue(verify_password("NewSecurePass456!", updated.password_hash))
        db2.close()

    def test_password_change_wrong_current_fails(self):
        resp = self.client.post(
            "/v1/me/change-password",
            json={"current_password": "WrongPassword", "new_password": "NewPass999!"},
            headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 401)
        self.assertIn("incorrect", resp.json()["detail"].lower())

    def test_password_change_short_new_password_fails(self):
        resp = self.client.post(
            "/v1/me/change-password",
            json={"current_password": "SecurePass123!", "new_password": "short"},
            headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 422)


# ── 2. Audit Log Export Tests ─────────────────────────────────────────────────


class TestAuditExportJSON(Phase4BaseTest):
    """Tests for GET /v1/audit/export?format=json."""

    def test_json_export_returns_entries(self):
        resp = self.client.get(
            "/v1/audit/export",
            headers={"X-API-Key": self.owner_key},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertIn("total", data)
        self.assertIn("entries", data)
        self.assertIn("format", data)
        self.assertIn("generated_at", data)
        self.assertEqual(data["format"], "json")
        self.assertGreater(data["total"], 0)

    def test_json_export_entry_fields(self):
        resp = self.client.get(
            "/v1/audit/export",
            headers={"X-API-Key": self.owner_key},
        )
        entry = resp.json()["entries"][0]
        for field in ["id", "task_id", "correlation_id", "capability_name", "action", "status", "created_at"]:
            self.assertIn(field, entry)

    def test_json_export_filter_by_capability(self):
        resp = self.client.get(
            "/v1/audit/export?capability=field_attendance",
            headers={"X-API-Key": self.owner_key},
        )
        self.assertEqual(resp.status_code, 200)
        entries = resp.json()["entries"]
        for entry in entries:
            self.assertEqual(entry["capability_name"], "field_attendance")

    def test_json_export_filter_by_action(self):
        resp = self.client.get(
            "/v1/audit/export?action=check_in",
            headers={"X-API-Key": self.owner_key},
        )
        self.assertEqual(resp.status_code, 200)
        entries = resp.json()["entries"]
        for entry in entries:
            self.assertEqual(entry["action"], "check_in")

    def test_export_requires_owner_key(self):
        # Manager should get 403
        resp = self.client.get(
            "/v1/audit/export",
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 403)

    def test_export_requires_auth(self):
        resp = self.client.get("/v1/audit/export")
        self.assertEqual(resp.status_code, 401)


class TestAuditExportCSV(Phase4BaseTest):
    """Tests for GET /v1/audit/export?format=csv."""

    def test_csv_export_content_type(self):
        resp = self.client.get(
            "/v1/audit/export?format=csv",
            headers={"X-API-Key": self.owner_key},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("text/csv", resp.headers.get("content-type", ""))

    def test_csv_export_has_attachment_header(self):
        resp = self.client.get(
            "/v1/audit/export?format=csv",
            headers={"X-API-Key": self.owner_key},
        )
        cd = resp.headers.get("content-disposition", "")
        self.assertIn("attachment", cd)
        self.assertIn(".csv", cd)

    def test_csv_export_has_correct_columns(self):
        resp = self.client.get(
            "/v1/audit/export?format=csv",
            headers={"X-API-Key": self.owner_key},
        )
        import csv
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        self.assertGreater(len(rows), 0)
        expected_cols = {"id", "task_id", "capability_name", "action", "status", "created_at"}
        actual_cols = set(rows[0].keys())
        for col in expected_cols:
            self.assertIn(col, actual_cols)


class TestAuditSummary(Phase4BaseTest):
    """Tests for GET /v1/audit/summary."""

    def test_summary_returns_aggregate(self):
        resp = self.client.get(
            "/v1/audit/summary",
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertIn("total_events", data)
        self.assertIn("by_action", data)
        self.assertIn("generated_at", data)
        self.assertGreater(data["total_events"], 0)

    def test_summary_by_action_correct_structure(self):
        data = self.client.get(
            "/v1/audit/summary",
            headers={"X-API-Key": self.manager_key},
        ).json()
        for item in data["by_action"]:
            self.assertIn("capability_name", item)
            self.assertIn("action", item)
            self.assertIn("count", item)
            self.assertGreater(item["count"], 0)


# ── 3. Legal Endpoint Tests ───────────────────────────────────────────────────


class TestLegalEndpoints(Phase4BaseTest):
    """Tests for public /legal/* endpoints — no auth required."""

    def test_tos_returns_200(self):
        resp = self.client.get("/legal/tos")
        self.assertEqual(resp.status_code, 200)

    def test_tos_has_required_sections(self):
        data = self.client.get("/legal/tos").json()
        self.assertIn("title", data)
        self.assertIn("effective_date", data)
        self.assertIn("sections", data)
        self.assertGreater(len(data["sections"]), 5)
        # Each section needs heading and body
        for section in data["sections"]:
            self.assertIn("heading", section)
            self.assertIn("body", section)
            self.assertGreater(len(section["body"]), 50)

    def test_tos_plain_text_format(self):
        resp = self.client.get("/legal/tos?format=text")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp.headers.get("content-type", ""))
        text = resp.text
        self.assertIn("Terms of Service", text)
        self.assertIn("Effective:", text)

    def test_privacy_returns_200(self):
        resp = self.client.get("/legal/privacy")
        self.assertEqual(resp.status_code, 200)

    def test_privacy_has_required_sections(self):
        data = self.client.get("/legal/privacy").json()
        self.assertIn("title", data)
        self.assertIn("effective_date", data)
        self.assertIn("sections", data)
        self.assertGreater(len(data["sections"]), 5)

    def test_privacy_plain_text_format(self):
        resp = self.client.get("/legal/privacy?format=text")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp.headers.get("content-type", ""))
        self.assertIn("Privacy Policy", resp.text)

    def test_legal_accessible_without_auth(self):
        """Legal endpoints must be publicly accessible — no auth header needed."""
        for endpoint in ["/legal/tos", "/legal/privacy"]:
            resp = self.client.get(endpoint)
            self.assertNotEqual(resp.status_code, 401, f"{endpoint} returned 401 — should be public")
            self.assertNotEqual(resp.status_code, 403, f"{endpoint} returned 403 — should be public")

    def test_invalid_format_rejected(self):
        resp = self.client.get("/legal/tos?format=xml")
        self.assertEqual(resp.status_code, 422)


# ── 4. Billing Enforcement (Quota Wall) ──────────────────────────────────────


class TestBillingEnforcement(Phase4BaseTest):
    """Tests that quota exhaustion correctly returns HTTP 402."""

    def test_lead_quota_exhaustion_returns_402(self):
        """Consuming more than the limit must return 402 Payment Required."""
        resp = self.client.post(
            "/v1/accounts/orgs/ph4-org-001/consume-credits",
            json={"credit_type": "lead", "amount": 100},  # 100 > 30 remaining
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 402)
        detail = resp.json()["detail"]
        self.assertIn("quota exceeded", detail.lower())
        self.assertIn("Upgrade", detail)

    def test_outreach_quota_exhaustion_returns_402(self):
        """Consuming more than the outreach limit must return 402."""
        resp = self.client.post(
            "/v1/accounts/orgs/ph4-org-001/consume-credits",
            json={"credit_type": "outreach", "amount": 50},  # 50 > 20 remaining
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 402)
        self.assertIn("quota exceeded", resp.json()["detail"].lower())

    def test_valid_credit_consumption_succeeds(self):
        """Consuming within the limit must succeed."""
        resp = self.client.post(
            "/v1/accounts/orgs/ph4-org-001/consume-credits",
            json={"credit_type": "lead", "amount": 1},
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["allowed"])
        self.assertEqual(data["consumed"], 1)
        self.assertIn("credits_remaining", data)

    def test_invalid_credit_type_returns_400(self):
        resp = self.client.post(
            "/v1/accounts/orgs/ph4-org-001/consume-credits",
            json={"credit_type": "faketoken", "amount": 5},
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 400)

    def test_inactive_org_returns_403(self):
        """Suspended/inactive org must be blocked from consuming credits."""
        db = self.session_factory()
        inactive_org = OrganizationRecord(
            id="ph4-inactive-org",
            name="Inactive Corp",
            slug="inactive-corp",
            tier="starter",
            lead_credits_limit=100,
            lead_credits_used=0,
            outreach_credits_limit=50,
            outreach_credits_used=0,
            is_active=False,
        )
        db.add(inactive_org)
        db.commit()
        db.close()

        resp = self.client.post(
            "/v1/accounts/orgs/ph4-inactive-org/consume-credits",
            json={"credit_type": "lead", "amount": 1},
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("inactive", resp.json()["detail"].lower())


# ── 5. OpenAPI Schema Completeness ───────────────────────────────────────────


class TestOpenAPISchema(Phase4BaseTest):
    """Validates that OpenAPI schema is complete and all Phase 4 routes are registered."""

    def test_openapi_schema_accessible(self):
        resp = self.client.get("/openapi.json")
        self.assertEqual(resp.status_code, 200)
        schema = resp.json()
        self.assertIn("info", schema)
        self.assertIn("paths", schema)
        self.assertIn("tags", schema)

    def test_openapi_version_correct(self):
        schema = self.client.get("/openapi.json").json()
        self.assertEqual(schema["info"]["version"], "0.2.0")

    def test_openapi_has_contact_info(self):
        schema = self.client.get("/openapi.json").json()
        self.assertIn("contact", schema["info"])
        self.assertEqual(schema["info"]["contact"]["email"], "support@askforwrite.in")

    def test_openapi_has_license_info(self):
        schema = self.client.get("/openapi.json").json()
        self.assertIn("license", schema["info"])

    def test_customer_portal_routes_in_schema(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/v1/me", paths)
        self.assertIn("/v1/me/usage", paths)
        self.assertIn("/v1/me/billing", paths)
        self.assertIn("/v1/me/capabilities", paths)
        self.assertIn("/v1/me/change-password", paths)

    def test_audit_export_routes_in_schema(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/v1/audit/export", paths)
        self.assertIn("/v1/audit/summary", paths)

    def test_legal_routes_in_schema(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/legal/tos", paths)
        self.assertIn("/legal/privacy", paths)

    def test_openapi_tag_descriptions_present(self):
        tags = self.client.get("/openapi.json").json().get("tags", [])
        tag_names = {t["name"] for t in tags}
        required_tags = {
            "authentication", "customer-portal", "accounts", "leads",
            "outreach", "field-force", "audit-export", "legal",
        }
        for tag in required_tags:
            self.assertIn(tag, tag_names, f"OpenAPI tag '{tag}' is missing from schema")

    def test_docs_ui_accessible(self):
        resp = self.client.get("/docs")
        self.assertEqual(resp.status_code, 200)

    def test_redoc_ui_accessible(self):
        resp = self.client.get("/redoc")
        self.assertEqual(resp.status_code, 200)
