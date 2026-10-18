"""Unit tests for Milestone 2: Prospect Discovery, Real Sources, Quota Enforcement, and Lifecycle Management."""

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

from app.agents.sources import (
    extract_page_metadata,
)
from app.db.database import Base, get_db
from app.db.models import (
    LeadRecordRow,
    OrganizationRecord,
)
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


MANAGER_HEADERS = {"X-API-Key": TEST_MANAGER_KEY}
OWNER_HEADERS = {"X-API-Key": TEST_OWNER_KEY}


class LeadServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=test_engine)
        app.dependency_overrides.pop(get_db, None)

    def setUp(self):
        os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY
        os.environ["OWNER_API_KEY"] = TEST_OWNER_KEY
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.db = TestingSessionLocal()
        # Clean tables between tests
        self.db.query(LeadRecordRow).delete()
        self.db.query(OrganizationRecord).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_db, None)

    def test_extract_page_metadata(self):
        """Test HTML metadata extraction with title, description, headings, and emails."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Acme Robotics - Logistics Automation</title>
            <meta name="description" content="AI-driven fleet and warehouse management systems.">
            <meta name="keywords" content="robotics, warehouse, ai">
        </head>
        <body>
            <h1>Automate Your Supply Chain</h1>
            <h2>Warehouse Fleet Tracking</h2>
            <p>Contact our sales team at sales@acmerobotics.com or support@acmerobotics.com.</p>
            <a href="mailto:info@acmerobotics.com">Email Us</a>
            <a href="https://linkedin.com/company/acme-robotics">LinkedIn Profile</a>
        </body>
        </html>
        """
        parsed = extract_page_metadata(html)
        self.assertIn("Acme Robotics", parsed["title"])
        self.assertEqual(parsed["description"], "AI-driven fleet and warehouse management systems.")
        self.assertIn("Automate Your Supply Chain", parsed["headings"])
        self.assertIn("Warehouse Fleet Tracking", parsed["headings"])
        self.assertIn("sales@acmerobotics.com", parsed["emails"])
        self.assertIn("info@acmerobotics.com", parsed["emails"])
        self.assertEqual(parsed["social_links"].get("linkedin"), "https://linkedin.com/company/acme-robotics")

    def test_discover_leads_without_org(self):
        """Basic discovery without org_id succeeds with 200 and offline synthetic mode."""
        resp = self.client.post(
            "/v1/leads/discover",
            headers=MANAGER_HEADERS,
            json={
                "objective": "Identify warehouse logistics prospects",
                "limit": 5,
                "idempotency_key": "test-disc-no-org-001",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertIn("leads", data)
        self.assertGreater(len(data["leads"]), 0)

    def test_discover_leads_with_org_and_credit_deduction(self):
        """Discovery consumes credits from an organization's quota."""
        org = OrganizationRecord(
            name="Alpha Corp",
            slug="alpha-corp",
            tier="starter",
            lead_credits_limit=10,
            lead_credits_used=0,
            outreach_credits_limit=20,
            outreach_credits_used=0,
            is_active=True,
        )
        self.db.add(org)
        self.db.commit()

        resp = self.client.post(
            "/v1/leads/discover",
            headers=MANAGER_HEADERS,
            json={
                "objective": "Find field force supervisor candidates",
                "limit": 4,
                "idempotency_key": "test-disc-org-credits-001",
                "org_id": org.id,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(data["org_id"], org.id)
        self.assertGreater(data["new_leads_count"], 0)
        
        # Verify credits deducted
        self.db.refresh(org)
        self.assertEqual(org.lead_credits_used, data["new_leads_count"])
        self.assertEqual(data["credits_remaining"], org.lead_credits_limit - data["new_leads_count"])

    def test_discover_leads_deduplication(self):
        """Running discovery with existing leads updates signals but does NOT consume extra credits."""
        org = OrganizationRecord(
            name="Beta Logistics",
            slug="beta-logistics",
            tier="starter",
            lead_credits_limit=10,
            lead_credits_used=0,
            outreach_credits_limit=20,
            outreach_credits_used=0,
            is_active=True,
        )
        self.db.add(org)
        self.db.commit()

        # First discovery run
        resp1 = self.client.post(
            "/v1/leads/discover",
            headers=MANAGER_HEADERS,
            json={
                "objective": "Find field force supervisor candidates",
                "limit": 4,
                "idempotency_key": "test-disc-dedup-run-1",
                "org_id": org.id,
            },
        )
        self.assertEqual(resp1.status_code, 200)
        first_count = resp1.json()["new_leads_count"]
        self.assertGreater(first_count, 0)

        self.db.refresh(org)
        credits_after_first = org.lead_credits_used
        self.assertEqual(credits_after_first, first_count)

        # Second discovery run with different idempotency key but same candidate leads
        resp2 = self.client.post(
            "/v1/leads/discover",
            headers=MANAGER_HEADERS,
            json={
                "objective": "Find field force supervisor candidates",
                "limit": 4,
                "idempotency_key": "test-disc-dedup-run-2",
                "org_id": org.id,
            },
        )
        self.assertEqual(resp2.status_code, 200)
        # Should detect duplicates
        self.assertEqual(resp2.json()["new_leads_count"], 0)

        # Credits should NOT have increased
        self.db.refresh(org)
        self.assertEqual(org.lead_credits_used, credits_after_first)

    def test_discover_leads_quota_exceeded(self):
        """Organizations that reached lead limit receive HTTP 402 Payment Required."""
        org = OrganizationRecord(
            name="Exhausted Corp",
            slug="exhausted-corp",
            tier="free",
            lead_credits_limit=5,
            lead_credits_used=5,
            outreach_credits_limit=5,
            outreach_credits_used=0,
            is_active=True,
        )
        self.db.add(org)
        self.db.commit()

        resp = self.client.post(
            "/v1/leads/discover",
            headers=MANAGER_HEADERS,
            json={
                "objective": "Find new leads",
                "limit": 5,
                "idempotency_key": "test-quota-exceeded",
                "org_id": org.id,
            },
        )
        self.assertEqual(resp.status_code, 402)
        self.assertIn("quota reached", resp.json()["detail"].lower())

    def test_list_leads_with_filtering_and_search(self):
        """Test GET /v1/leads with filtering by org, status, min_fit, and search."""
        org = OrganizationRecord(
            name="Filter Corp",
            slug="filter-corp",
            tier="starter",
            lead_credits_limit=50,
            lead_credits_used=2,
            outreach_credits_limit=20,
            outreach_credits_used=0,
            is_active=True,
        )
        self.db.add(org)
        self.db.commit()

        lead1 = LeadRecordRow(
            id="lead-1",
            org_id=org.id,
            domain="acmelogistics.com",
            task_id="task-1",
            company="Acme Logistics",
            website="https://acmelogistics.com",
            industry="Freight",
            geography="India",
            observed_signals=["gps tracking required"],
            sources=[],
            fit_score=0.85,
            confidence=0.9,
            status="QUALIFIED",
            recommended_next_step="owner_review",
            do_not_contact=False,
        )
        lead2 = LeadRecordRow(
            id="lead-2",
            org_id=org.id,
            domain="zenretail.com",
            task_id="task-2",
            company="Zen Retail",
            website="https://zenretail.com",
            industry="Retail",
            geography="India",
            observed_signals=["pos checkout"],
            sources=[],
            fit_score=0.40,
            confidence=0.5,
            status="DISCOVERED",
            recommended_next_step="recheck",
            do_not_contact=False,
        )
        self.db.add_all([lead1, lead2])
        self.db.commit()

        # List all for org
        resp = self.client.get(f"/v1/leads?org_id={org.id}", headers=MANAGER_HEADERS)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["credits_remaining"], 48)

        # Filter by min_fit >= 0.50
        resp_fit = self.client.get(f"/v1/leads?org_id={org.id}&min_fit=0.50", headers=MANAGER_HEADERS)
        self.assertEqual(resp_fit.status_code, 200)
        self.assertEqual(resp_fit.json()["count"], 1)
        self.assertEqual(resp_fit.json()["leads"][0]["id"], "lead-1")

        # Search by company query
        resp_search = self.client.get("/v1/leads?search=zen", headers=MANAGER_HEADERS)
        self.assertEqual(resp_search.status_code, 200)
        self.assertEqual(resp_search.json()["count"], 1)
        self.assertEqual(resp_search.json()["leads"][0]["id"], "lead-2")

    def test_get_and_patch_lead_lifecycle(self):
        """Test retrieving lead and advancing lifecycle status and do_not_contact."""
        lead = LeadRecordRow(
            id="lead-lifecycle-test",
            task_id="task-lifecycle",
            company="Lifecycle Technologies",
            website="https://lifecycle.example.com",
            industry="SaaS",
            geography="Global",
            observed_signals=["cloud migrations"],
            sources=[],
            fit_score=0.75,
            confidence=0.8,
            status="DISCOVERED",
            recommended_next_step="research",
            do_not_contact=False,
        )
        self.db.add(lead)
        self.db.commit()

        # GET lead
        get_resp = self.client.get("/v1/leads/lead-lifecycle-test", headers=MANAGER_HEADERS)
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["company"], "Lifecycle Technologies")

        # PATCH to advance to QUALIFIED
        patch_resp = self.client.patch(
            "/v1/leads/lead-lifecycle-test",
            headers=MANAGER_HEADERS,
            json={
                "status": "QUALIFIED",
                "public_contact_channel": "cto@lifecycle.example.com",
            },
        )
        self.assertEqual(patch_resp.status_code, 200)
        self.assertEqual(patch_resp.json()["status"], "QUALIFIED")
        self.assertEqual(patch_resp.json()["public_contact_channel"], "cto@lifecycle.example.com")

        # PATCH do_not_contact to True
        patch_dnc = self.client.patch(
            "/v1/leads/lead-lifecycle-test",
            headers=MANAGER_HEADERS,
            json={"do_not_contact": True},
        )
        self.assertEqual(patch_dnc.status_code, 200)
        self.assertEqual(patch_dnc.json()["status"], "DO_NOT_CONTACT")
        self.assertTrue(patch_dnc.json()["do_not_contact"])

    @patch("app.api.v1.leads.fetch_and_enrich_website")
    def test_enrich_lead_endpoint(self, mock_fetch):
        """Test POST /v1/leads/enrich with mock web scraper."""
        mock_fetch.return_value = {
            "title": "Quantum Fleet Inc - Next-gen GPS Routing",
            "description": "Enterprise fleet and route tracking software.",
            "headings": ["Real-time Vehicle Tracking", "Automated Dispatch"],
            "emails": ["sales@quantumfleet.com"],
            "social_links": {"linkedin": "https://linkedin.com/company/quantum-fleet"},
        }

        org = OrganizationRecord(
            name="Enrichment Corp",
            slug="enrichment-corp",
            tier="starter",
            lead_credits_limit=20,
            lead_credits_used=0,
            outreach_credits_limit=10,
            outreach_credits_used=0,
            is_active=True,
        )
        self.db.add(org)
        self.db.commit()

        resp = self.client.post(
            "/v1/leads/enrich",
            headers=MANAGER_HEADERS,
            json={
                "website": "https://quantumfleet.com",
                "org_id": org.id,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertTrue(data["is_new"])
        self.assertEqual(data["domain"], "quantumfleet.com")
        self.assertEqual(data["lead"]["public_contact_channel"], "sales@quantumfleet.com")
        self.assertEqual(data["credits_remaining"], 19)

        # Check in DB
        self.db.refresh(org)
        self.assertEqual(org.lead_credits_used, 1)

    def test_delete_lead(self):
        """Test DELETE /v1/leads/{id}."""
        lead = LeadRecordRow(
            id="lead-to-delete",
            task_id="task-del",
            company="Delete Me Corp",
            website="https://deleteme.example.com",
            industry="Other",
            geography="Global",
            observed_signals=[],
            sources=[],
            fit_score=0.1,
            confidence=0.1,
            status="LOST",
            recommended_next_step="none",
            do_not_contact=True,
        )
        self.db.add(lead)
        self.db.commit()

        del_resp = self.client.delete("/v1/leads/lead-to-delete", headers=MANAGER_HEADERS)
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json()["deleted"])

        get_resp = self.client.get("/v1/leads/lead-to-delete", headers=MANAGER_HEADERS)
        self.assertEqual(get_resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
