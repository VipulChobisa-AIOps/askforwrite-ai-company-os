"""Integration tests for ASK4, SEO, and Marketing capabilities."""

import os
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
import app.db.models  # ensure models are registered
from app.main import app


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)

        def override_get_db():
            try:
                db = cls.TestingSessionLocal()
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)
        cls.manager_key = "test-manager-key-that-is-long-enough-for-validation"
        cls.owner_key = "test-owner-key-that-is-long-enough-for-validation"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        os.environ["OWNER_API_KEY"] = cls.owner_key
        os.environ["APP_ENV"] = "development"
        
        # Seed genesis block
        from app.security.trust_chain import ensure_genesis_block
        db = cls.TestingSessionLocal()
        ensure_genesis_block(db)
        db.commit()
        db.close()

    def test_ask4_ingest_order_success(self):
        resp = self.client.post(
            "/v1/orders/ingest",
            json={
                "transaction_id": "txn_123",
                "amount": 100.0,
                "currency": "USD",
                "customer_email": "test@example.com",
                "idempotency_key": "order_key_1",
            },
            # Webhook endpoint, auth validated via HMAC if secret set
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "CONFIRMED")
        self.assertEqual(data["transaction_id"], "txn_123")
        self.assertIn("task_id", data)

    def test_seo_generate_draft_requests_approval(self):
        resp = self.client.post(
            "/v1/seo/generate-draft",
            json={
                "target_network": "technology",
                "keywords": ["AI", "agents"],
                "idempotency_key": "seo_key_1",
            },
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["status"], "PENDING_APPROVAL")
        self.assertIn("approval_id", data)
        self.assertIn("draft_id", data)

    def test_marketing_generate_campaign_requests_approval(self):
        resp = self.client.post(
            "/v1/marketing/generate-campaign",
            json={
                "campaign_type": "promotional",
                "target_audience": "small businesses",
                "idempotency_key": "marketing_key_1",
            },
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["status"], "PENDING_APPROVAL")
        self.assertIn("approval_id", data)
        self.assertIn("campaign_id", data)
