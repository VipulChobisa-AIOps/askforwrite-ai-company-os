"""End-to-End Real-World Multi-Agent Commercial Simulation Test.

Executes the entire lifecycle of AskforWrite Company OS in an isolated test environment:
1. System Health & Genesis Block Verification
2. Manager Multi-Agent Workflow (Discovery -> Evidence Research -> HITL Outreach Gate)
3. Owner Decision on Outreach Gate
4. Sales Requirement Capture & Proposal Generation
5. Owner Proposal Delivery HITL Gate (Request & Approval)
6. Proposal Delivery Dispatch to Field Force Client
7. Commercial Payment Capture Webhook & Automated Tenant Provisioning
8. Cryptographic Trust Ledger Chain Integrity Verification
"""

import os
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.clients.field_force import get_field_force_client
from app.db.database import Base, get_db
from app.db.models import (
    InvoiceRecord,
    OrganizationRecord,
)
from app.main import app
from app.security.trust_chain import ensure_genesis_block
from app.services.payment import PaymentProvider, WebhookEvent
from app.services.provisioning import auto_provision_tenant_on_payment


class FakeFieldForceClient:
    """Mock field force client for simulation."""
    async def create_and_verify_task(self, *, title, description, assigned_to, due_date, idempotency_key, correlation_id):
        return {
            "task_id": "ff_task_mock_123",
            "status": "DISPATCHED",
            "assigned_to": assigned_to,
            "readback_status": "VERIFIED",
        }


class TestRealWorldEndToEndSimulation(unittest.TestCase):
    """Full lifecycle simulation of the Company OS from prospect to paying tenant."""

    @classmethod
    def setUpClass(cls):
        cls.manager_key = "test-manager-api-key-32-chars-long-xxx"
        cls.owner_key = "test-owner-api-key-32-chars-long-xxx"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        os.environ["OWNER_API_KEY"] = cls.owner_key
        os.environ["APP_ENV"] = "development"

        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine, autoflush=False, expire_on_commit=False)

        # Seed Genesis trust block
        session = cls.session_factory()
        try:
            ensure_genesis_block(session)
            session.commit()
        finally:
            session.close()

        def override_get_db():
            s = cls.session_factory()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_field_force_client] = lambda: FakeFieldForceClient()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        Base.metadata.drop_all(cls.engine)

    def test_full_commercial_lifecycle(self):
        # ── Step 1: Healthcheck ──────────────────────────────────────────────
        health_resp = self.client.get("/health")
        self.assertEqual(health_resp.status_code, 200)
        self.assertEqual(health_resp.json()["status"], "healthy")

        # ── Step 2: Manager Multi-Agent Orchestration ─────────────────────────
        corr_id = str(uuid.uuid4())
        mgr_resp = self.client.post(
            "/v1/manager/execute",
            headers={
                "X-API-Key": self.manager_key,
                "X-Correlation-ID": corr_id,
            },
            json={
                "objective": "Target field operations logistics prospects in Rajasthan",
                "limit": 10,
                "idempotency_key": "sim-mgr-001",
            },
        )
        self.assertEqual(mgr_resp.status_code, 200)
        mgr_data = mgr_resp.json()
        self.assertEqual(mgr_data["status"], "HUMAN_APPROVAL_REQUIRED")
        self.assertGreater(mgr_data["qualified_lead_count"], 0)
        outreach_approval_id = mgr_data["approval_ids"][0]

        # Get the discovery leads
        disc_leads = self.client.get(
            "/v1/discovery/leads",
            headers={"X-API-Key": self.manager_key},
        ).json()["leads"]
        eligible_lead = next(
            l for l in disc_leads if l["company"] == "Rajasthan AgriLogistics Pvt Ltd"
        )
        lead_id = eligible_lead["lead_id"]
        company_name = eligible_lead["company"]

        # ── Step 3: Owner HITL Decision on Outreach ──────────────────────────
        owner_decision = self.client.post(
            f"/v1/approvals/{outreach_approval_id}/decision",
            headers={
                "X-API-Key": self.owner_key,
                "X-Correlation-ID": corr_id,
            },
            json={
                "decision": "APPROVED",
                "reason": "Authorized sales requirement conversation",
            },
        )
        self.assertEqual(owner_decision.status_code, 200)
        self.assertEqual(owner_decision.json()["status"], "APPROVED")

        # ── Step 4: Sales Requirement Capture & Proposal Generation ──────────
        sales_notes = (
            "Regional logistics operator managing 40 on-ground drivers across 12 hubs. "
            "Experiencing proxy attendance and route deviations. Budget 200,000 INR."
        )
        sales_resp = self.client.post(
            "/v1/sales/execute",
            headers={
                "X-API-Key": self.manager_key,
                "X-Correlation-ID": corr_id,
            },
            json={
                "lead_id": lead_id,
                "conversation_notes": sales_notes,
                "channel": "meeting_notes",
                "idempotency_key": "sim-sales-001",
            },
        )
        self.assertEqual(sales_resp.status_code, 200)
        sales_data = sales_resp.json()
        proposal_id = sales_data["proposal_id"]
        requirement_id = sales_data["requirement_id"]
        task_id = sales_data["task_id"]
        self.assertEqual(sales_data["proposal_status"], "AWAITING_APPROVAL")

        # ── Step 5: Owner Delivery Gate Approval ─────────────────────────────
        del_approval_id = sales_data["approval_id"]
        self.assertIsNotNone(del_approval_id)

        # Owner approves proposal delivery
        del_decision = self.client.post(
            f"/v1/approvals/{del_approval_id}/decision",
            headers={
                "X-API-Key": self.owner_key,
                "X-Correlation-ID": corr_id,
            },
            json={
                "decision": "APPROVED",
                "reason": "Proposal delivery authorized by Owner",
            },
        )
        self.assertEqual(del_decision.status_code, 200)
        self.assertEqual(del_decision.json()["status"], "APPROVED")


        # ── Step 6: Proposal Delivery Execution ──────────────────────────────
        delivery_resp = self.client.post(
            "/v1/delivery/execute",
            headers={
                "X-API-Key": self.manager_key,
                "X-Correlation-ID": corr_id,
            },
            json={
                "proposal_id": proposal_id,
                "assigned_to": "info@askforwrite.in",
                "idempotency_key": "sim-del-exec-001",
            },
        )
        self.assertEqual(delivery_resp.status_code, 200)
        del_data = delivery_resp.json()
        self.assertEqual(del_data["status"], "COMPLETED")
        self.assertIn("task_id", del_data)
        self.assertEqual(del_data["capability_result"]["readback_status"], "VERIFIED")


        # ── Step 7: Commercial Payment Capture & Automated Tenant Onboarding ─
        session = self.session_factory()
        try:
            event = WebhookEvent(
                id=f"evt_{uuid.uuid4().hex[:10]}",
                provider=PaymentProvider.RAZORPAY,
                event_type="payment.captured",
                raw_event_type="payment.captured",
                resource_type="payment",
                resource_id="pay_simulated_999",
                data={
                    "payload": {
                        "payment": {
                            "entity": {
                                "id": "pay_simulated_999",
                                "email": "ops.director@agrilogistics.in",
                                "amount": 399900,
                                "currency": "INR",
                                "notes": {
                                    "notes_company": company_name,
                                    "notes_package": "field_force",
                                },
                            }
                        }
                    }
                },
            )
            with patch("app.services.provisioning.get_email_dispatcher"):
                prov_result = auto_provision_tenant_on_payment(session, event)

            self.assertIsNotNone(prov_result)
            self.assertEqual(prov_result["status"], "provisioned")
            self.assertEqual(prov_result["package_key"], "field_force")

            org = session.query(OrganizationRecord).filter_by(id=prov_result["org_id"]).first()
            self.assertIsNotNone(org)
            self.assertEqual(org.tier, "modular_field_ops")

            invoice = session.query(InvoiceRecord).filter_by(org_id=org.id).first()
            self.assertIsNotNone(invoice)
            self.assertEqual(invoice.status, "paid")
            self.assertEqual(invoice.amount, 399900)
        finally:
            session.close()

        # ── Step 8: Cryptographic Trust Ledger Chain Verification ───────────
        verify_resp = self.client.get(
            "/v1/trust/verify",
            headers={"X-API-Key": self.manager_key},
        )
        self.assertEqual(verify_resp.status_code, 200)
        trust_status = verify_resp.json()
        self.assertTrue(trust_status["chain_valid"])
        self.assertGreater(trust_status["total_blocks"], 1)
        self.assertEqual(len(trust_status["errors"]), 0)

