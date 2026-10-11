"""Unit tests for Milestone 3: Owner-Approved Customer Outreach and Dispatch."""

import os
import unittest
from datetime import UTC, datetime

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
from app.db.models import (
    ApprovalRequest,
    LeadRecordRow,
    OrganizationRecord,
    OutreachRecord,
)
from app.main import app
from app.services.email_dispatcher import MockEmailDispatcher, get_email_dispatcher

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


MANAGER_HEADERS = {"X-API-Key": TEST_MANAGER_KEY}
OWNER_HEADERS = {"X-API-Key": TEST_OWNER_KEY}


class OutreachServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=test_engine)

    def setUp(self):
        os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY
        os.environ["OWNER_API_KEY"] = TEST_OWNER_KEY
        os.environ["OUTREACH_DISPATCH_PROVIDER"] = "mock"
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.db = TestingSessionLocal()
        # Clean tables
        self.db.query(OutreachRecord).delete()
        self.db.query(ApprovalRequest).delete()
        self.db.query(LeadRecordRow).delete()
        self.db.query(OrganizationRecord).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_db, None)

    def test_draft_outreach_creates_pending_approval(self):
        """Manager can draft outreach; it creates a durable ApprovalRequest in PENDING_APPROVAL status."""
        org = OrganizationRecord(
            name="Logistics One",
            slug="logistics-one",
            tier="starter",
            lead_credits_limit=10,
            lead_credits_used=1,
            outreach_credits_limit=10,
            outreach_credits_used=0,
            is_active=True,
        )
        self.db.add(org)
        self.db.commit()

        lead = LeadRecordRow(
            id="lead-outreach-1",
            org_id=org.id,
            domain="rajasthanagri.com",
            task_id="task-lead-1",
            company="Rajasthan AgriLogistics",
            website="https://rajasthanagri.com",
            industry="Agriculture Logistics",
            geography="Rajasthan, India",
            observed_signals=["fleet expansion", "manual attendance issues"],
            sources=[],
            fit_score=0.8,
            confidence=0.85,
            public_contact_channel="director@rajasthanagri.com",
            recommended_next_step="owner_review",
            do_not_contact=False,
            status="QUALIFIED",
        )
        self.db.add(lead)
        self.db.commit()

        resp = self.client.post(
            "/v1/outreach/draft",
            headers=MANAGER_HEADERS,
            json={
                "lead_id": lead.id,
                "org_id": org.id,
                "recipient_name": "Rajesh Kumar",
                "custom_notes": "Offering field force GPS attendance trial.",
                "idempotency_key": "outreach-draft-001",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "PENDING_APPROVAL")
        self.assertEqual(data["recipient_email"], "director@rajasthanagri.com")
        self.assertIn("Rajasthan AgriLogistics", data["subject"])
        self.assertIn("Rajesh Kumar", data["body_text"])
        self.assertIsNotNone(data["approval_id"])

        # Verify ApprovalRequest in DB
        approval = self.db.get(ApprovalRequest, data["approval_id"])
        self.assertIsNotNone(approval)
        self.assertEqual(approval.status, "PENDING")
        self.assertEqual(approval.action, "external_sales_outreach")

    def test_draft_outreach_rejects_do_not_contact(self):
        """Cannot draft outreach for do-not-contact leads."""
        lead = LeadRecordRow(
            id="lead-dnc-1",
            domain="blockedcorp.com",
            task_id="task-dnc",
            company="Blocked Corp",
            website="https://blockedcorp.com",
            industry="Unknown",
            geography="Global",
            observed_signals=[],
            sources=[],
            fit_score=0.0,
            confidence=0.0,
            public_contact_channel="info@blockedcorp.com",
            recommended_next_step="none",
            do_not_contact=True,
            status="DO_NOT_CONTACT",
        )
        self.db.add(lead)
        self.db.commit()

        resp = self.client.post(
            "/v1/outreach/draft",
            headers=MANAGER_HEADERS,
            json={
                "lead_id": lead.id,
                "idempotency_key": "outreach-dnc-001",
            },
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn("do-not-contact", resp.json()["detail"].lower())

    def test_draft_outreach_quota_exceeded(self):
        """Returns 402 Payment Required when organization has exhausted outreach quota."""
        org = OrganizationRecord(
            name="Maxed Corp",
            slug="maxed-corp",
            tier="free",
            lead_credits_limit=10,
            lead_credits_used=5,
            outreach_credits_limit=2,
            outreach_credits_used=2,
            is_active=True,
        )
        self.db.add(org)
        self.db.commit()

        lead = LeadRecordRow(
            id="lead-quota-1",
            org_id=org.id,
            domain="example.com",
            task_id="task-q",
            company="Example Corp",
            website="https://example.com",
            industry="Tech",
            geography="Global",
            observed_signals=[],
            sources=[],
            fit_score=0.5,
            confidence=0.5,
            public_contact_channel="team@example.com",
            recommended_next_step="review",
            do_not_contact=False,
            status="QUALIFIED",
        )
        self.db.add(lead)
        self.db.commit()

        resp = self.client.post(
            "/v1/outreach/draft",
            headers=MANAGER_HEADERS,
            json={
                "lead_id": lead.id,
                "org_id": org.id,
                "idempotency_key": "outreach-quota-001",
            },
        )
        self.assertEqual(resp.status_code, 402)
        self.assertIn("quota reached", resp.json()["detail"].lower())

    def test_dispatch_requires_owner_principal(self):
        """Only the Owner principal can call the dispatch endpoint."""
        resp = self.client.post(
            "/v1/outreach/fake-id/dispatch",
            headers=MANAGER_HEADERS,  # Manager role, not Owner
        )
        self.assertEqual(resp.status_code, 403)

    def test_dispatch_blocked_without_owner_approval(self):
        """Owner attempting to dispatch before approval is granted receives 403."""
        lead = LeadRecordRow(
            id="lead-disp-1",
            domain="dispatch.com",
            task_id="task-disp",
            company="Dispatch Corp",
            website="https://dispatch.com",
            industry="Tech",
            geography="Global",
            observed_signals=[],
            sources=[],
            fit_score=0.5,
            confidence=0.5,
            public_contact_channel="contact@dispatch.com",
            recommended_next_step="review",
            do_not_contact=False,
            status="QUALIFIED",
        )
        self.db.add(lead)
        self.db.commit()

        # Draft outreach
        draft_resp = self.client.post(
            "/v1/outreach/draft",
            headers=MANAGER_HEADERS,
            json={
                "lead_id": lead.id,
                "idempotency_key": "outreach-need-appr-001",
            },
        )
        self.assertEqual(draft_resp.status_code, 200)
        outreach_id = draft_resp.json()["outreach_id"]

        # Attempt to dispatch as Owner while ApprovalRequest is still PENDING
        disp_resp = self.client.post(
            f"/v1/outreach/{outreach_id}/dispatch",
            headers=OWNER_HEADERS,
        )
        self.assertEqual(disp_resp.status_code, 403)
        self.assertIn("owner approval", disp_resp.json()["detail"].lower())

    def test_end_to_end_draft_approval_and_dispatch(self):
        """Complete workflow: Draft -> Owner Approves -> Owner Dispatches -> Lead status updated & Quota deducted."""
        org = OrganizationRecord(
            name="Workflow Corp",
            slug="workflow-corp",
            tier="starter",
            lead_credits_limit=20,
            lead_credits_used=0,
            outreach_credits_limit=10,
            outreach_credits_used=0,
            is_active=True,
        )
        self.db.add(org)
        self.db.commit()

        lead = LeadRecordRow(
            id="lead-e2e-1",
            org_id=org.id,
            domain="retailchain.com",
            task_id="task-e2e",
            company="Retail Chain Ltd",
            website="https://retailchain.com",
            industry="Retail Distribution",
            geography="Delhi, India",
            observed_signals=["30 new stores opening", "hiring sales supervisors"],
            sources=[],
            fit_score=0.9,
            confidence=0.95,
            public_contact_channel="ops@retailchain.com",
            recommended_next_step="owner_review",
            do_not_contact=False,
            status="QUALIFIED",
        )
        self.db.add(lead)
        self.db.commit()

        # Step 1: Manager drafts outreach
        draft_resp = self.client.post(
            "/v1/outreach/draft",
            headers=MANAGER_HEADERS,
            json={
                "lead_id": lead.id,
                "org_id": org.id,
                "recipient_name": "Vikram Singh",
                "custom_notes": "Case study on attendance automation for multi-store retail.",
                "idempotency_key": "outreach-e2e-001",
            },
        )
        self.assertEqual(draft_resp.status_code, 200)
        outreach_id = draft_resp.json()["outreach_id"]
        approval_id = draft_resp.json()["approval_id"]

        # Step 2: Owner reviews and APPROVES the durable request
        decision_resp = self.client.post(
            f"/v1/approvals/{approval_id}/decision",
            headers=OWNER_HEADERS,
            json={
                "decision": "APPROVED",
                "reason": "Personalized message grounded in verified store opening signals.",
            },
        )
        self.assertEqual(decision_resp.status_code, 200)
        self.assertEqual(decision_resp.json()["status"], "APPROVED")

        # Step 3: Owner dispatches the approved outreach
        disp_resp = self.client.post(
            f"/v1/outreach/{outreach_id}/dispatch",
            headers=OWNER_HEADERS,
        )
        self.assertEqual(disp_resp.status_code, 200)
        disp_data = disp_resp.json()
        self.assertEqual(disp_data["status"], "DISPATCHED")
        self.assertEqual(disp_data["lead_status"], "CONTACTED")
        self.assertEqual(disp_data["credits_remaining"], 9)

        # Step 4: Verify DB state
        self.db.refresh(lead)
        self.assertEqual(lead.status, "CONTACTED")

        self.db.refresh(org)
        self.assertEqual(org.outreach_credits_used, 1)

        outreach = self.db.get(OutreachRecord, outreach_id)
        self.assertEqual(outreach.status, "DISPATCHED")
        self.assertIsNotNone(outreach.sent_at)

    def test_list_outreach_records(self):
        """Test GET /v1/outreach filtering by organization and status."""
        outreach = OutreachRecord(
            id="outreach-list-test",
            org_id="org-list-1",
            lead_id="lead-list-1",
            task_id="task-list-1",
            recipient_email="test@example.com",
            subject="Test subject",
            body_text="Test body",
            channel="email",
            status="PENDING_APPROVAL",
            idempotency_key="key-list-1",
        )
        self.db.add(outreach)
        self.db.commit()

        resp = self.client.get("/v1/outreach?org_id=org-list-1", headers=MANAGER_HEADERS)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["records"][0]["id"], "outreach-list-test")

        get_one = self.client.get("/v1/outreach/outreach-list-test", headers=MANAGER_HEADERS)
        self.assertEqual(get_one.status_code, 200)
        self.assertEqual(get_one.json()["subject"], "Test subject")

    def test_mock_dispatcher_reports_simulated_and_blocks_in_production(self):
        """Verify MockEmailDispatcher reports simulated_delivered and raises error in APP_ENV=production."""
        mock_disp = MockEmailDispatcher()
        
        # In development, it returns honest simulated_delivered status
        os.environ["APP_ENV"] = "development"
        receipt = mock_disp.send("prospect@realcorp.com", "Test", "Body")
        self.assertEqual(receipt["status"], "simulated_delivered")
        self.assertTrue(receipt["simulated"])

        # In production, MockEmailDispatcher is strictly forbidden
        os.environ["APP_ENV"] = "production"
        with self.assertRaises(RuntimeError) as ctx:
            mock_disp.send("prospect@realcorp.com", "Test", "Body")
        self.assertIn("Mock email dispatcher is prohibited in production", str(ctx.exception))
        
        # Reset back to development for subsequent test isolation
        os.environ["APP_ENV"] = "development"


if __name__ == "__main__":
    unittest.main()

