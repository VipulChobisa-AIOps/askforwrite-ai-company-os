import asyncio
import os
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db, validate_database_configuration
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    ConversationRecord,
    DeliveryRecord,
    IdempotencyRecord,
    LeadRecordRow,
    ProposalRecord,
    RequirementRecord,
    ResearchRecord,
    TaskRecord,
    TrustBlock,
)
from app.main import app
from app.clients.field_force import get_field_force_client
from app.security.auth import APIPrincipal, get_current_principal


class DiscoveryApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

        def override_get_db():
            session = self.session_factory()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_principal] = lambda: APIPrincipal(
            subject="test-manager",
            role="manager",
        )
        self.transport = httpx.ASGITransport(app=app)

    def tearDown(self):
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def request(self, method, path, **kwargs):
        async def send_request():
            async with httpx.AsyncClient(
                transport=self.transport,
                base_url="http://test",
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send_request())

    @staticmethod
    def request_body(idempotency_key="discovery-001", objective="Find field force prospects"):
        return {
            "objective": objective,
            "limit": 10,
            "idempotency_key": idempotency_key,
        }

    def test_execute_persists_task_leads_audit_and_status(self):
        response = self.request(
            "POST",
            "/v1/discovery/execute",
            json=self.request_body(),
            headers={"X-Correlation-ID": "trace-001", "X-Agent-ID": "spoofed-agent"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["data_mode"], "offline_synthetic")
        self.assertEqual(payload["persistence"], "sqlite")
        self.assertFalse(payload["outreach_performed"])

        status = self.request("GET", f"/v1/discovery/status/{payload['task_id']}")
        leads = self.request("GET", "/v1/discovery/leads")
        audit = self.request("GET", f"/v1/discovery/audit/{payload['task_id']}")

        self.assertEqual(status.json()["status"], "COMPLETED")
        self.assertEqual(leads.json()["count"], 4)
        self.assertEqual(len(audit.json()["logs"]), 1)
        self.assertEqual(audit.json()["logs"][0]["correlation_id"], "trace-001")
        self.assertEqual(audit.json()["logs"][0]["agent_id"], "test-manager")

    def test_non_development_requires_a_valid_manager_key(self):
        environment = {
            "APP_ENV": "production",
            "MANAGER_API_KEY": "manager-test-key-with-at-least-32-characters",
            "OWNER_API_KEY": "owner-test-key-with-at-least-32-characters",
        }
        test_principal = app.dependency_overrides.pop(get_current_principal)
        try:
            with patch.dict(os.environ, environment, clear=False):
                missing_key = self.request(
                    "POST",
                    "/v1/discovery/execute",
                    json=self.request_body(),
                )
                invalid_key = self.request(
                    "POST",
                    "/v1/discovery/execute",
                    json=self.request_body(),
                    headers={"X-API-Key": "not-the-key"},
                )
                valid_key = self.request(
                    "POST",
                    "/v1/discovery/execute",
                    json=self.request_body(),
                    headers={"X-API-Key": environment["MANAGER_API_KEY"]},
                )
                audit = self.request(
                    "GET",
                    f"/v1/discovery/audit/{valid_key.json()['task_id']}",
                    headers={"X-API-Key": environment["MANAGER_API_KEY"]},
                )
        finally:
            app.dependency_overrides[get_current_principal] = test_principal

        self.assertEqual(missing_key.status_code, 401)
        self.assertEqual(invalid_key.status_code, 401)
        self.assertEqual(valid_key.status_code, 200)
        self.assertEqual(audit.json()["logs"][0]["agent_id"], "manager")

    def test_development_does_not_bypass_api_key_authentication(self):
        test_principal = app.dependency_overrides.pop(get_current_principal)
        environment = {
            "APP_ENV": "development",
            "MANAGER_API_KEY": "development-test-key-with-at-least-32-chars",
            "OWNER_API_KEY": "",
        }
        try:
            with patch.dict(os.environ, environment, clear=False):
                missing_key = self.request(
                    "POST",
                    "/v1/discovery/execute",
                    json=self.request_body(),
                )
                invalid_key = self.request(
                    "POST",
                    "/v1/discovery/execute",
                    json=self.request_body(),
                    headers={"X-API-Key": "incorrect"},
                )
                valid_key = self.request(
                    "POST",
                    "/v1/discovery/execute",
                    json=self.request_body(),
                    headers={"X-API-Key": environment["MANAGER_API_KEY"]},
                )
        finally:
            app.dependency_overrides[get_current_principal] = test_principal

        self.assertEqual(missing_key.status_code, 401)
        self.assertEqual(invalid_key.status_code, 401)
        self.assertEqual(valid_key.status_code, 200)

    def test_non_development_requires_postgresql(self):
        validate_database_configuration(
            "production",
            "postgresql+psycopg://user:password@localhost/company_os",
        )
        with self.assertRaisesRegex(ValueError, "require a PostgreSQL"):
            validate_database_configuration(
                "production",
                "sqlite:///./company_os.db",
            )

    def test_owner_approval_is_durable_gated_and_never_sends_outreach(self):
        discovery = self.request(
            "POST",
            "/v1/discovery/execute",
            json=self.request_body(idempotency_key="approval-flow-discovery"),
        )
        self.assertEqual(discovery.status_code, 200)
        result = discovery.json()
        task_id = result["task_id"]
        eligible_lead = next(
            lead for lead in result["leads"]
            if lead["company"] == "Rajasthan AgriLogistics Pvt Ltd"
        )
        blocked_lead = next(
            lead for lead in result["leads"]
            if lead["do_not_contact"]
        )

        blocked_request = self.request(
            "POST",
            "/v1/approvals",
            json={
                "task_id": task_id,
                "lead_id": blocked_lead["lead_id"],
                "action": "external_sales_outreach",
                "detail": {},
                "idempotency_key": "blocked-outreach-approval",
            },
        )
        self.assertEqual(blocked_request.status_code, 422)

        approval_body = {
            "task_id": task_id,
            "lead_id": eligible_lead["lead_id"],
            "action": "external_sales_outreach",
            "detail": {"company": eligible_lead["company"]},
            "idempotency_key": "eligible-outreach-approval",
        }
        approval = self.request("POST", "/v1/approvals", json=approval_body)
        replay = self.request("POST", "/v1/approvals", json=approval_body)
        manager_list = self.request("GET", "/v1/approvals")

        self.assertEqual(approval.status_code, 200)
        self.assertEqual(replay.json(), approval.json())
        self.assertEqual(approval.json()["status"], "PENDING")
        self.assertFalse(approval.json()["external_action_performed"])
        self.assertEqual(manager_list.status_code, 403)

        manager_principal = app.dependency_overrides[get_current_principal]
        app.dependency_overrides[get_current_principal] = lambda: APIPrincipal(
            subject="test-owner",
            role="owner",
        )
        try:
            pending = self.request("GET", "/v1/approvals")
            decision = self.request(
                "POST",
                f"/v1/approvals/{approval.json()['approval_id']}/decision",
                json={"decision": "APPROVED", "reason": "Approved by owner"},
            )
            decision_replay = self.request(
                "POST",
                f"/v1/approvals/{approval.json()['approval_id']}/decision",
                json={"decision": "APPROVED", "reason": "Retry"},
            )
            opposite_decision = self.request(
                "POST",
                f"/v1/approvals/{approval.json()['approval_id']}/decision",
                json={"decision": "REJECTED"},
            )
        finally:
            app.dependency_overrides[get_current_principal] = manager_principal

        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["count"], 1)
        self.assertEqual(decision.json()["status"], "APPROVED")
        self.assertFalse(decision.json()["external_action_performed"])
        self.assertEqual(decision_replay.status_code, 200)
        self.assertEqual(opposite_decision.status_code, 409)

        with self.session_factory() as session:
            stored_approval = session.query(ApprovalRequest).one()
            stored_lead = session.get(LeadRecordRow, eligible_lead["lead_id"])
            task_audit = session.query(AuditLog).filter_by(task_id=task_id).all()
            self.assertEqual(stored_approval.requested_by, "test-manager")
            self.assertEqual(stored_approval.decided_by, "test-owner")
            self.assertEqual(stored_lead.status, "APPROVED_FOR_OUTREACH")
            self.assertEqual(len(task_audit), 3)

    def test_research_persists_evidence_and_replays_by_key(self):
        discovery = self.request(
            "POST",
            "/v1/discovery/execute",
            json=self.request_body(idempotency_key="research-flow-discovery"),
        )
        eligible_lead = next(
            lead for lead in discovery.json()["leads"]
            if lead["company"] == "Rajasthan AgriLogistics Pvt Ltd"
        )
        path = f"/v1/research/leads/{eligible_lead['lead_id']}/execute"
        body = {"idempotency_key": "research-001"}

        first = self.request("POST", path, json=body)
        replay = self.request("POST", path, json=body)
        fetched = self.request("GET", f"/v1/research/leads/{eligible_lead['lead_id']}")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.json(), first.json())
        self.assertFalse(first.json()["external_research_performed"])
        self.assertTrue(first.json()["analysis"]["needs_human_verification"])
        self.assertIn("offline_synthetic", first.json()["analysis"]["data_modes"])
        self.assertEqual(fetched.json()["research_id"], first.json()["research_id"])
        with self.session_factory() as session:
            self.assertEqual(session.query(ResearchRecord).count(), 1)

    def test_manager_runs_discovery_research_and_requests_owner_approval(self):
        body = self.request_body(idempotency_key="manager-flow-001")
        first = self.request("POST", "/v1/manager/execute", json=body)
        replay = self.request("POST", "/v1/manager/execute", json=body)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "HUMAN_APPROVAL_REQUIRED")
        self.assertEqual(first.json()["qualified_lead_count"], 2)
        self.assertEqual(len(first.json()["research_ids"]), 2)
        self.assertEqual(len(first.json()["approval_ids"]), 2)
        self.assertFalse(first.json()["outreach_performed"])
        self.assertEqual(replay.json(), first.json())

        manager_status = self.request(
            "GET",
            f"/v1/manager/status/{first.json()['task_id']}",
        )
        self.assertEqual(manager_status.json()["status"], "HUMAN_APPROVAL_REQUIRED")
        with self.session_factory() as session:
            research = session.query(ResearchRecord).all()
            pending_approvals = session.query(ApprovalRequest).filter_by(status="PENDING").all()
            blocked_lead = session.query(LeadRecordRow).filter_by(
                status="DO_NOT_CONTACT",
            ).one()
            self.assertEqual(len(research), 2)
            self.assertEqual(len(pending_approvals), 2)
            self.assertTrue(blocked_lead.do_not_contact)

    def test_sales_captures_requirements_and_gates_proposal_delivery(self):
        manager = self.request(
            "POST",
            "/v1/manager/execute",
            json=self.request_body(idempotency_key="sales-flow-manager"),
        )
        self.assertEqual(manager.status_code, 200)
        discovery = self.request(
            "GET",
            f"/v1/discovery/status/{manager.json()['discovery_task_id']}",
        )
        lead_id = next(
            lead["lead_id"]
            for lead in discovery.json()["result"]["leads"]
            if lead["company"] == "Rajasthan AgriLogistics Pvt Ltd"
        )

        before_owner_approval = self.request(
            "POST",
            "/v1/sales/execute",
            json={
                "lead_id": lead_id,
                "conversation_notes": "They need GPS attendance.",
                "channel": "meeting_notes",
                "idempotency_key": "sales-not-yet-approved",
            },
        )
        self.assertEqual(before_owner_approval.status_code, 422)

        manager_principal = app.dependency_overrides[get_current_principal]
        app.dependency_overrides[get_current_principal] = lambda: APIPrincipal(
            subject="test-owner",
            role="owner",
        )
        try:
            outreach_decision = self.request(
                "POST",
                f"/v1/approvals/{manager.json()['approval_ids'][0]}/decision",
                json={"decision": "APPROVED", "reason": "Discuss requirements"},
            )
        finally:
            app.dependency_overrides[get_current_principal] = manager_principal
        self.assertEqual(outreach_decision.status_code, 200)

        notes = (
            "Operations needs GPS tracking and attendance for 40 field staff "
            "across 12 districts. Budget of 2 lakh INR; start next month."
        )
        sales_body = {
            "lead_id": lead_id,
            "conversation_notes": notes,
            "channel": "meeting_notes",
            "idempotency_key": "sales-capture-approved-001",
        }
        sales_result = self.request("POST", "/v1/sales/execute", json=sales_body)
        replay = self.request("POST", "/v1/sales/execute", json=sales_body)

        self.assertEqual(sales_result.status_code, 200)
        self.assertEqual(sales_result.json()["priority"], "HIGH")
        self.assertEqual(sales_result.json()["proposal_status"], "AWAITING_APPROVAL")
        self.assertTrue(sales_result.json()["proposal_delivery_approval_required"])
        self.assertFalse(sales_result.json()["external_action_performed"])
        self.assertEqual(replay.json(), sales_result.json())

        requirement = self.request(
            "GET",
            "/v1/sales/requirements?status=QUALIFIED",
        ).json()["requirements"][0]
        proposal = self.request(
            "GET",
            f"/v1/sales/proposals/{requirement['requirement_id']}",
        )
        self.assertEqual(proposal.json()["status"], "AWAITING_APPROVAL")
        self.assertFalse(proposal.json()["external_delivery_performed"])

        class FakeFieldForceClient:
            def __init__(self):
                self.calls = 0

            async def create_and_verify_task(
                self,
                *,
                title,
                description,
                assigned_to,
                due_date,
                idempotency_key,
                correlation_id,
            ):
                self.calls += 1
                return {
                    "task_id": "unolo-task-001",
                    "status": "Pending",
                    "assigned_to": assigned_to,
                    "title": title,
                    "correlation_id": correlation_id,
                    "verified": True,
                    "external_notification_sent": False,
                }

        fake_field_force = FakeFieldForceClient()
        app.dependency_overrides[get_field_force_client] = lambda: fake_field_force
        delivery_body = {
            "proposal_id": proposal.json()["proposal_id"],
            "assigned_to": "employee-7",
            "due_date": "2026-10-01T10:00:00Z",
            "idempotency_key": "delivery-after-proposal-approval",
        }
        try:
            blocked_delivery = self.request(
                "POST",
                "/v1/delivery/execute",
                json=delivery_body,
            )
        finally:
            app.dependency_overrides.pop(get_field_force_client, None)

        self.assertEqual(blocked_delivery.status_code, 403)
        self.assertEqual(fake_field_force.calls, 0)

        app.dependency_overrides[get_current_principal] = lambda: APIPrincipal(
            subject="test-owner",
            role="owner",
        )
        try:
            proposal_decision = self.request(
                "POST",
                f"/v1/approvals/{sales_result.json()['approval_id']}/decision",
                json={"decision": "APPROVED", "reason": "Scope approved"},
            )
        finally:
            app.dependency_overrides[get_current_principal] = manager_principal

        self.assertEqual(proposal_decision.status_code, 200)
        self.assertFalse(proposal_decision.json()["external_action_performed"])

        app.dependency_overrides[get_field_force_client] = lambda: fake_field_force
        try:
            delivery = self.request(
                "POST",
                "/v1/delivery/execute",
                json=delivery_body,
                headers={"X-Correlation-ID": "delivery-trace-001"},
            )
            delivery_replay = self.request(
                "POST",
                "/v1/delivery/execute",
                json=delivery_body,
                headers={"X-Correlation-ID": "delivery-trace-retry"},
            )
            delivery_status = self.request(
                "GET",
                f"/v1/delivery/status/{delivery.json()['task_id']}",
            )
        finally:
            app.dependency_overrides.pop(get_field_force_client, None)

        self.assertEqual(delivery.status_code, 200)
        self.assertEqual(delivery.json()["status"], "COMPLETED")
        self.assertTrue(delivery.json()["capability_result"]["verified"])
        self.assertFalse(delivery.json()["capability_result"]["external_notification_sent"])
        self.assertEqual(delivery_replay.json(), delivery.json())
        self.assertEqual(fake_field_force.calls, 1)
        self.assertEqual(delivery_status.json()["status"], "COMPLETED")
        self.assertEqual(len(delivery_status.json()["delivery_records"]), 1)
        with self.session_factory() as session:
            self.assertEqual(session.query(ConversationRecord).count(), 1)
            requirement_record = session.query(RequirementRecord).one()
            proposal_record = session.query(ProposalRecord).one()
            stored_lead = session.get(LeadRecordRow, lead_id)
            delivery_record = session.query(DeliveryRecord).one()
            self.assertEqual(requirement_record.status, "QUALIFIED")
            self.assertEqual(proposal_record.status, "APPROVED")
            self.assertEqual(stored_lead.status, "PROPOSAL_APPROVED")
            self.assertEqual(delivery_record.status, "DELIVERED")

    def test_repeated_request_replays_response_without_duplicate_records(self):
        first = self.request(
            "POST",
            "/v1/discovery/execute",
            json=self.request_body(),
            headers={"X-Correlation-ID": "trace-first"},
        )
        replay = self.request(
            "POST",
            "/v1/discovery/execute",
            json=self.request_body(),
            headers={"X-Correlation-ID": "trace-retry"},
        )

        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), first.json())
        with self.session_factory() as session:
            self.assertEqual(session.query(TaskRecord).count(), 1)
            self.assertEqual(session.query(LeadRecordRow).count(), 4)
            self.assertEqual(session.query(AuditLog).count(), 1)
            self.assertEqual(session.query(IdempotencyRecord).count(), 1)

    def test_reusing_key_for_different_request_returns_conflict(self):
        first = self.request(
            "POST",
            "/v1/discovery/execute",
            json=self.request_body(),
        )
        conflicting = self.request(
            "POST",
            "/v1/discovery/execute",
            json=self.request_body(objective="Find warehouse prospects"),
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(conflicting.status_code, 409)
        with self.session_factory() as session:
            self.assertEqual(session.query(TaskRecord).count(), 1)

    def test_audit_rows_cannot_be_updated_or_deleted_through_orm(self):
        response = self.request(
            "POST",
            "/v1/discovery/execute",
            json=self.request_body(),
        )
        self.assertEqual(response.status_code, 200)

        with self.session_factory() as session:
            audit = session.query(AuditLog).one()
            session.delete(audit)
            with self.assertRaisesRegex(ValueError, "append-only"):
                session.commit()
            session.rollback()
            self.assertEqual(session.query(func.count(AuditLog.id)).scalar(), 1)

    def test_project_status_returns_live_counts_and_fleet(self):
        response = self.request("GET", "/v1/project/status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["system"], "AskforWrite AI Company OS")
        self.assertEqual(payload["status"], "operational")
        self.assertIn("operating_model", payload)
        self.assertIn("counts", payload["operating_model"]["l4_data_layer"])
        self.assertEqual(payload["operating_model"]["l4_data_layer"]["counts"]["tasks"], 0)

        # Execute discovery and ensure count increments
        self.request("POST", "/v1/discovery/execute", json=self.request_body())
        updated = self.request("GET", "/v1/project/status").json()
        self.assertGreaterEqual(updated["operating_model"]["l4_data_layer"]["counts"]["tasks"], 1)
        self.assertGreaterEqual(updated["operating_model"]["l4_data_layer"]["counts"]["leads"], 1)

    def test_capabilities_endpoint_returns_registry(self):
        response = self.request("GET", "/v1/capabilities")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["standard"], "Master Document Section 7")
        cap_ids = [c["id"] for c in payload["capabilities"]]
        self.assertIn("customer_discovery", cap_ids)
        self.assertIn("research", cap_ids)
        self.assertIn("sales_capture", cap_ids)
        self.assertIn("delivery_field_force", cap_ids)
        self.assertIn("trust_ledger_audit", cap_ids)

    def test_end_to_end_prospect_lifecycle_with_signed_ledger(self):
        """Full multi-agent cycle: Discovery → Research → Owner Approval
        → Sales Capture → Proposal Approval → Delivery → Signed Ledger."""

        # ── PHASE 1: Manager orchestrates Discovery + Research + Approval ──
        manager = self.request(
            "POST",
            "/v1/manager/execute",
            json=self.request_body(idempotency_key="e2e-lifecycle-001"),
        )
        self.assertEqual(manager.status_code, 200)
        self.assertEqual(manager.json()["status"], "HUMAN_APPROVAL_REQUIRED")
        self.assertGreaterEqual(manager.json()["qualified_lead_count"], 1)

        # Resolve the eligible lead
        discovery = self.request(
            "GET",
            f"/v1/discovery/status/{manager.json()['discovery_task_id']}",
        )
        lead_id = next(
            lead["lead_id"]
            for lead in discovery.json()["result"]["leads"]
            if lead["company"] == "Rajasthan AgriLogistics Pvt Ltd"
        )

        # ── PHASE 2: Owner approves outreach ──
        manager_principal = app.dependency_overrides[get_current_principal]
        app.dependency_overrides[get_current_principal] = lambda: APIPrincipal(
            subject="test-owner",
            role="owner",
        )
        try:
            outreach_approval = self.request(
                "POST",
                f"/v1/approvals/{manager.json()['approval_ids'][0]}/decision",
                json={"decision": "APPROVED", "reason": "Proceed with outreach"},
            )
        finally:
            app.dependency_overrides[get_current_principal] = manager_principal
        self.assertEqual(outreach_approval.status_code, 200)
        self.assertEqual(outreach_approval.json()["status"], "APPROVED")

        # ── PHASE 3: Sales captures requirements and generates proposal ──
        notes = (
            "Rajasthan AgriLogistics needs GPS attendance tracking for 40 field "
            "staff across 12 districts. Budget 2L INR, start next month."
        )
        sales = self.request(
            "POST",
            "/v1/sales/execute",
            json={
                "lead_id": lead_id,
                "conversation_notes": notes,
                "channel": "meeting_notes",
                "idempotency_key": "e2e-sales-capture-001",
            },
        )
        self.assertEqual(sales.status_code, 200)
        self.assertEqual(sales.json()["priority"], "HIGH")
        self.assertEqual(sales.json()["proposal_status"], "AWAITING_APPROVAL")
        self.assertTrue(sales.json()["proposal_delivery_approval_required"])

        # ── PHASE 4: Owner approves proposal for delivery ──
        app.dependency_overrides[get_current_principal] = lambda: APIPrincipal(
            subject="test-owner",
            role="owner",
        )
        try:
            proposal_approval = self.request(
                "POST",
                f"/v1/approvals/{sales.json()['approval_id']}/decision",
                json={"decision": "APPROVED", "reason": "Scope and budget approved"},
            )
        finally:
            app.dependency_overrides[get_current_principal] = manager_principal
        self.assertEqual(proposal_approval.status_code, 200)

        # ── PHASE 5: Delivery to Field Force ──
        class FakeFieldForceClient:
            def __init__(self):
                self.calls = 0

            async def create_and_verify_task(
                self, *, title, description, assigned_to, due_date,
                idempotency_key, correlation_id,
            ):
                self.calls += 1
                return {
                    "task_id": "unolo-e2e-001",
                    "status": "Pending",
                    "assigned_to": assigned_to,
                    "title": title,
                    "correlation_id": correlation_id,
                    "verified": True,
                    "external_notification_sent": False,
                }

        fake_ff = FakeFieldForceClient()
        proposal = self.request(
            "GET",
            f"/v1/sales/requirements?status=QUALIFIED",
        ).json()["requirements"][0]
        proposal_record = self.request(
            "GET",
            f"/v1/sales/proposals/{proposal['requirement_id']}",
        )

        app.dependency_overrides[get_field_force_client] = lambda: fake_ff
        try:
            delivery = self.request(
                "POST",
                "/v1/delivery/execute",
                json={
                    "proposal_id": proposal_record.json()["proposal_id"],
                    "assigned_to": "employee-42",
                    "due_date": "2026-10-15T09:00:00Z",
                    "idempotency_key": "e2e-delivery-001",
                },
                headers={"X-Correlation-ID": "e2e-delivery-trace"},
            )
        finally:
            app.dependency_overrides.pop(get_field_force_client, None)

        self.assertEqual(delivery.status_code, 200)
        self.assertEqual(delivery.json()["status"], "COMPLETED")
        self.assertTrue(delivery.json()["capability_result"]["verified"])
        self.assertEqual(fake_ff.calls, 1)

        # ── PHASE 6: Verify cryptographic ledger integrity ──
        with self.session_factory() as session:
            blocks = session.query(TrustBlock).order_by(TrustBlock.index.asc()).all()
            # At minimum: genesis + discovery + manager + sales + delivery blocks
            self.assertGreaterEqual(len(blocks), 5)
            # Genesis block
            self.assertEqual(blocks[0].index, 0)
            self.assertEqual(blocks[0].capability_name, "genesis")
            # Verify consecutive hash chain linkage
            for i in range(1, len(blocks)):
                self.assertEqual(blocks[i].index, blocks[i - 1].index + 1)
                self.assertEqual(blocks[i].prev_hash, blocks[i - 1].block_hash)
            # Verify final block references the delivery task
            delivery_blocks = [
                b for b in blocks if b.capability_name == "field_force_task_creation"
            ]
            self.assertGreaterEqual(len(delivery_blocks), 1)

        # ── PHASE 7: Trust verification endpoint ──
        verify = self.request("GET", "/v1/trust/verify")
        self.assertEqual(verify.status_code, 200)
        self.assertTrue(verify.json()["chain_valid"])
        self.assertGreaterEqual(verify.json()["total_blocks"], 5)
        self.assertEqual(len(verify.json()["errors"]), 0)

        # ── PHASE 8: Project status reflects full lifecycle ──
        status = self.request("GET", "/v1/project/status").json()
        counts = status["operating_model"]["l4_data_layer"]["counts"]
        self.assertGreaterEqual(counts["tasks"], 1)
        self.assertGreaterEqual(counts["leads"], 1)
        self.assertGreaterEqual(counts["research_records"], 1)
        self.assertGreaterEqual(counts["requirements"], 1)
        self.assertGreaterEqual(counts["proposals"], 1)
        self.assertGreaterEqual(counts["delivery_records"], 1)
        self.assertGreaterEqual(counts["trust_blocks"], 5)
        self.assertGreaterEqual(counts["audit_logs"], 1)

    def test_trust_blocks_are_immutable_through_orm(self):
        """TrustBlocks cannot be updated or deleted through ORM."""
        self.request(
            "POST",
            "/v1/discovery/execute",
            json=self.request_body(idempotency_key="trust-immutability-test"),
        )
        with self.session_factory() as session:
            block = session.query(TrustBlock).filter(
                TrustBlock.index > 0
            ).first()
            self.assertIsNotNone(block)
            session.delete(block)
            with self.assertRaisesRegex(ValueError, "append-only"):
                session.commit()
            session.rollback()
            # Block still exists
            remaining = session.query(TrustBlock).filter(
                TrustBlock.index == block.index
            ).one()
            self.assertEqual(remaining.block_hash, block.block_hash)


if __name__ == "__main__":
    unittest.main()