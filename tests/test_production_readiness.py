"""Production readiness tests for AskforWrite AI Company OS.

Validates production-critical behaviors:
- Database configuration enforcement
- HITL approval governance controls
- Middleware behavior (CORS, rate limiting, request ID)
- Trust chain integrity guarantees
- Pending approvals dashboard endpoint
"""

import os
import unittest

from fastapi.testclient import TestClient


class ProductionReadinessTests(unittest.TestCase):
    """Tests that validate production deployment requirements."""

    @classmethod
    def setUpClass(cls):
        os.environ["APP_ENV"] = "development"
        cls.manager_key = "test-manager-key-that-is-long-enough-for-validation"
        cls.owner_key = "test-owner-key-that-is-long-enough-for-validation-x"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        os.environ["OWNER_API_KEY"] = cls.owner_key

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        import app.db.models
        from app.db.database import Base, get_db
        from app.main import app

        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine, autoflush=False, expire_on_commit=False)

        def override_get_db():
            session = cls.session_factory()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        from app.db.database import Base, get_db
        from app.main import app

        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=cls.engine)

    # ── Database Configuration ────────────────────────────────────────

    def test_non_development_rejects_sqlite(self):
        from app.db.database import validate_database_configuration

        with self.assertRaises(ValueError):
            validate_database_configuration("production", "sqlite:///test.db")
        with self.assertRaises(ValueError):
            validate_database_configuration("staging", "sqlite:///test.db")
        # development is fine with SQLite
        validate_database_configuration("development", "sqlite:///test.db")

    def test_postgresql_url_accepted_for_all_environments(self):
        from app.db.database import validate_database_configuration

        pg_url = "postgresql+psycopg://user:pass@localhost:5432/db"
        validate_database_configuration("production", pg_url)
        validate_database_configuration("staging", pg_url)
        validate_database_configuration("development", pg_url)

    # ── HITL Governance: Owner-Only Endpoints ─────────────────────────

    def test_manager_cannot_decide_approvals(self):
        """Manager agents must NOT be able to approve/reject — only Owner."""
        resp = self.client.post(
            "/v1/approvals/fake-id/decision",
            json={"decision": "APPROVED"},
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Owner role required", resp.json()["detail"])

    def test_manager_cannot_list_approvals(self):
        """Approval queue listing is Owner-only."""
        resp = self.client.get(
            "/v1/approvals",
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 403)

    def test_owner_can_view_pending_count(self):
        """Owner dashboard quick-check endpoint returns pending count."""
        resp = self.client.get(
            "/v1/approvals/pending/count",
            headers={"X-API-Key": self.owner_key},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("pending_approvals", data)
        self.assertIn("action_required", data)
        self.assertIsInstance(data["pending_approvals"], int)

    def test_manager_cannot_view_pending_count(self):
        """Pending count is Owner-only."""
        resp = self.client.get(
            "/v1/approvals/pending/count",
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 403)

    # ── Middleware: Request ID Propagation ─────────────────────────────

    def test_response_includes_request_id_header(self):
        """Every response must carry X-Request-ID for traceability."""
        resp = self.client.get("/health")
        self.assertIn("x-request-id", resp.headers)
        self.assertTrue(len(resp.headers["x-request-id"]) > 0)

    def test_request_id_echoed_when_provided(self):
        """Client-provided X-Request-ID should be echoed back."""
        custom_id = "custom-trace-id-12345"
        resp = self.client.get(
            "/health",
            headers={"X-Request-ID": custom_id},
        )
        self.assertEqual(resp.headers.get("x-request-id"), custom_id)

    # ── Middleware: Rate Limiting ──────────────────────────────────────

    def test_rate_limiting_disabled_in_development(self):
        """Rate limiting should not be active in development mode."""
        resp = self.client.get(
            "/health",
            headers={"X-API-Key": self.manager_key},
        )
        # In development mode, rate limit headers should NOT be present
        self.assertNotIn("x-ratelimit-limit", resp.headers)

    # ── API Key Security ──────────────────────────────────────────────

    def test_missing_api_key_returns_401(self):
        resp = self.client.get("/v1/project/status")
        self.assertEqual(resp.status_code, 401)

    def test_invalid_api_key_returns_401(self):
        resp = self.client.get(
            "/v1/project/status",
            headers={"X-API-Key": "invalid-key-that-wont-match-anything-at-all"},
        )
        self.assertEqual(resp.status_code, 401)

    # ── Trust Chain Integrity ─────────────────────────────────────────

    def test_trust_verify_endpoint_accessible(self):
        resp = self.client.get(
            "/v1/trust/verify",
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("chain_valid", data)
        self.assertTrue(data["chain_valid"])
        self.assertEqual(data["protocol"], "AFW-COMPANY-OS-TRUST-CHAIN-V2")

    # ── Health Check ──────────────────────────────────────────────────

    def test_health_returns_database_status(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["database"], "connected")

    # ── Version Correctness ───────────────────────────────────────────

    def test_project_status_reflects_production_version(self):
        resp = self.client.get(
            "/v1/project/status",
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["version"], "0.2.0")
        self.assertIn("trust_blocks", data["operating_model"]["l4_data_layer"]["counts"])
