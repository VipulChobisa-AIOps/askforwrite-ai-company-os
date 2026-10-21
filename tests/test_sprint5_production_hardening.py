"""Test Suite for Sprint 5: Final Production Hardening.

Covers:
1. US-5.1: Alembic migration file structure, revision chain, and upgrade/downgrade schema parity.
2. US-5.2: Autonomous Shift Scheduler Outbound SDR loop staging Trojan-Horse outreach drafts,
   embedding /v1/previews/{token}/html, populating HITL queue, and auto-dispatching on approval.
3. US-5.3: Active tenant validation, quota enforcement (429), and credit accounting on POST /v1/me/use-service.
"""

from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

import migrations.versions.e5f6a1b2c3d4_add_watchdog_preview_and_shift_tables as sprint5_migration
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.db.database import Base, SessionLocal, engine, get_db
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    OrganizationRecord,
    OutreachRecord,
    UserRecord,
)
from app.main import app
from app.security.auth import create_access_token, hash_password
from app.services.approvals import decide_approval
from app.services.shift_scheduler import run_autonomous_shift


class Sprint5ProductionHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.manager_key = "test-manager-key-sprint5-hardening-32ch"
        cls.owner_key = "test-owner-key-sprint5-hardening-32ch"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        os.environ["OWNER_API_KEY"] = cls.owner_key
        os.environ["APP_ENV"] = "development"
        cls.client = TestClient(app)
        cls.manager_headers = {
            "X-API-Key": cls.manager_key,
            "X-Correlation-ID": "test-sprint5-corr-001",
        }

    def setUp(self):
        self.db = SessionLocal()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_db, None)

    # ── US-5.1: Alembic Migration & Schema Parity Tests ───────────────────────

    def test_migration_file_structure_and_revision_chain(self):
        """Verify migration e5f6a1b2c3d4 exists and extends d4e5f6a1b2c3 in a single linear head."""
        alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
        config = Config(str(alembic_ini))
        script_dir = ScriptDirectory.from_config(config)

        heads = script_dir.get_heads()
        self.assertEqual(len(heads), 1)
        self.assertIn(heads[0], ["e5f6a1b2c3d4", "f6a1b2c3d4e5"])

        rev = script_dir.get_revision("e5f6a1b2c3d4")
        self.assertIsNotNone(rev)
        self.assertEqual(rev.down_revision, "d4e5f6a1b2c3")

        # Verify down revision exists
        down_rev = script_dir.get_revision("d4e5f6a1b2c3")
        self.assertIsNotNone(down_rev)
        self.assertEqual(down_rev.down_revision, "c3d4e5f6a1b2")

    def test_migration_upgrade_and_downgrade_tables_and_indexes(self):
        """Verify upgrade() and downgrade() execute cleanly against SQLite and match ORM models."""
        test_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        with test_engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)

            orig_op = sprint5_migration.op
            sprint5_migration.op = op
            try:
                # 1. Upgrade
                sprint5_migration.upgrade()
                conn.commit()

                inspector = inspect(conn)
                tables = inspector.get_table_names()
                self.assertIn("supervisor_alert_records", tables)
                self.assertIn("preview_records", tables)
                self.assertIn("shift_records", tables)

                # Verify supervisor_alert_records
                alert_indexes = {ix["name"] for ix in inspector.get_indexes("supervisor_alert_records")}
                self.assertIn("ix_alert_org_acknowledged", alert_indexes)
                self.assertIn("ix_alert_user_severity", alert_indexes)

                # Verify preview_records
                preview_indexes = {ix["name"] for ix in inspector.get_indexes("preview_records")}
                self.assertIn("ix_preview_token", preview_indexes)
                self.assertIn("ix_preview_domain", preview_indexes)

                # Verify shift_records
                shift_indexes = {ix["name"] for ix in inspector.get_indexes("shift_records")}
                self.assertIn("ix_shift_id", shift_indexes)
                self.assertIn("ix_shift_status", shift_indexes)

                # 2. Downgrade
                sprint5_migration.downgrade()
                conn.commit()

                inspector_after = inspect(conn)
                tables_after = inspector_after.get_table_names()
                self.assertNotIn("supervisor_alert_records", tables_after)
                self.assertNotIn("preview_records", tables_after)
                self.assertNotIn("shift_records", tables_after)
            finally:
                sprint5_migration.op = orig_op

    # ── US-5.2: Shift-to-Outreach Trojan-Horse Staging & Auto-Dispatch ──────────

    def test_shift_stages_trojan_horse_outreach_drafts_and_auto_dispatches(self):
        """run_autonomous_shift stages Trojan-Horse outreach drafts in HITL queue, and owner approval auto-dispatches."""
        self.db.query(OutreachRecord).delete()
        self.db.query(ApprovalRequest).delete()
        self.db.commit()

        shift_corr_id = f"test-sprint5-shift-{uuid.uuid4().hex[:8]}"

        shift_res = run_autonomous_shift(
            db=self.db,
            shift_type="full_daily_cycle",
            correlation_id=shift_corr_id,
        )

        self.assertEqual(shift_res["status"], "COMPLETED")
        self.assertIn("outbound_sdr", shift_res["steps"])
        sdr_step = shift_res["steps"]["outbound_sdr"]
        self.assertEqual(sdr_step["status"], "COMPLETED")
        self.assertGreaterEqual(sdr_step["leads_discovered_count"], 1)
        self.assertGreaterEqual(sdr_step["previews_generated_count"], 1)

        # Verify outreach drafts staged in shift results
        self.assertIn("outreach_drafts_staged_count", sdr_step)
        self.assertGreaterEqual(sdr_step["outreach_drafts_staged_count"], 1)
        self.assertIn("outreach_drafts", sdr_step)
        drafts = sdr_step["outreach_drafts"]
        self.assertGreaterEqual(len(drafts), 1)

        first_draft = drafts[0]
        self.assertIn("outreach_id", first_draft)
        self.assertIn("approval_id", first_draft)
        self.assertIn("preview_token", first_draft)

        outreach_id = first_draft["outreach_id"]
        approval_id = first_draft["approval_id"]
        preview_token = first_draft["preview_token"]
        expected_preview_link = f"/v1/previews/{preview_token}/html"

        # 1. Verify OutreachRecord in DB
        outreach_rec = self.db.get(OutreachRecord, outreach_id)
        self.assertIsNotNone(outreach_rec)
        self.assertEqual(outreach_rec.status, "PENDING_APPROVAL")
        self.assertIn(expected_preview_link, outreach_rec.body_text)
        self.assertIn(expected_preview_link, str(outreach_rec.metadata_json))

        # 2. Verify ApprovalRequest in DB
        approval_req = self.db.get(ApprovalRequest, approval_id)
        self.assertIsNotNone(approval_req)
        self.assertEqual(approval_req.status, "PENDING")
        self.assertEqual(approval_req.action, "external_sales_outreach")
        self.assertIn(expected_preview_link, str(approval_req.detail))

        # 3. Simulate L0 Owner Approving the Outreach Request
        decision_res = decide_approval(
            db=self.db,
            approval_id=approval_id,
            decision="APPROVED",
            decided_by="owner@askforwrite.com",
            decision_note="Approved Trojan-Horse proof preview outbound shift draft",
        )
        self.assertEqual(decision_res["status"], "APPROVED")
        self.assertTrue(decision_res["external_action_performed"])
        self.assertEqual(decision_res["auto_executed_action"], "outreach_dispatched")

        # 4. Verify that OutreachRecord is now DISPATCHED
        self.db.refresh(outreach_rec)
        self.assertEqual(outreach_rec.status, "DISPATCHED")

    # ── US-5.3: Tenant Inactivity & Quota Accounting Tests ───────────────────

    def test_customer_portal_use_service_credit_accounting_and_audit(self):
        """Active tenant use-service increments lead_credits_used, creates AuditLog, and returns credits_remaining."""
        org_id = f"org-sp5-{uuid.uuid4().hex[:6]}"
        user_id = f"usr-sp5-{uuid.uuid4().hex[:6]}"
        email = f"sp5-{uuid.uuid4().hex[:6]}@example.com"

        org = OrganizationRecord(
            id=org_id,
            name="Sprint 5 Active Tenant",
            slug=f"slug-{uuid.uuid4().hex[:6]}",
            tier="professional",
            lead_credits_limit=10,
            lead_credits_used=3,
            is_active=True,
            metadata_json={"package_key": "warehouse_automation"},
        )
        user = UserRecord(
            id=user_id,
            org_id=org_id,
            email=email,
            full_name="Active Tenant Admin",
            role="owner",
            password_hash=hash_password("Pass12345!"),
            is_active=True,
        )
        self.db.add(org)
        self.db.add(user)
        self.db.commit()

        token = create_access_token(user_id=user_id, email=email, role="owner", org_id=org_id)
        headers = {"Authorization": f"Bearer {token}"}

        resp = self.client.post(
            "/v1/me/use-service",
            headers=headers,
            json={
                "service_key": "warehouse_automation",
                "payload": {"service_level_z": 1.65},
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(data["service_key"], "warehouse_automation")
        self.assertIn("result", data)
        self.assertIn("credits_remaining", data)
        # Started at 3 used out of 10 limit -> now 4 used -> 6 remaining
        self.assertEqual(data["credits_remaining"], 6)

        self.db.refresh(org)
        self.assertEqual(org.lead_credits_used, 4)

        # Verify AuditLog created
        audit = (
            self.db.query(AuditLog)
            .filter_by(capability_name="customer_portal", action="use_service")
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.input_payload.get("service_key"), "warehouse_automation")
        self.assertEqual(audit.input_payload.get("org_id"), org_id)

    def test_customer_portal_use_service_quota_exhausted_returns_429(self):
        """When lead_credits_used >= lead_credits_limit, endpoint raises 429 Too Many Requests."""
        org_id = f"org-sp5-exhausted-{uuid.uuid4().hex[:6]}"
        user_id = f"usr-sp5-exhausted-{uuid.uuid4().hex[:6]}"
        email = f"sp5-exhausted-{uuid.uuid4().hex[:6]}@example.com"

        org = OrganizationRecord(
            id=org_id,
            name="Sprint 5 Quota Exhausted Tenant",
            slug=f"slug-{uuid.uuid4().hex[:6]}",
            tier="starter",
            lead_credits_limit=5,
            lead_credits_used=5,  # Quota exhausted
            is_active=True,
            metadata_json={"package_key": "mango_quality_analytics"},
        )
        user = UserRecord(
            id=user_id,
            org_id=org_id,
            email=email,
            full_name="Exhausted Tenant Admin",
            role="owner",
            password_hash=hash_password("Pass12345!"),
            is_active=True,
        )
        self.db.add(org)
        self.db.add(user)
        self.db.commit()

        token = create_access_token(user_id=user_id, email=email, role="owner", org_id=org_id)
        headers = {"Authorization": f"Bearer {token}"}

        resp = self.client.post(
            "/v1/me/use-service",
            headers=headers,
            json={
                "service_key": "mango_quality_analytics",
                "payload": {"variety": "Alphonso"},
            },
        )
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["detail"], "Monthly service credit quota exhausted. Please upgrade your plan.")

    def test_customer_portal_use_service_inactive_org_returns_403(self):
        """When org.is_active is False, endpoint raises 403 Forbidden."""
        org_id = f"org-sp5-inactive-{uuid.uuid4().hex[:6]}"
        user_id = f"usr-sp5-inactive-{uuid.uuid4().hex[:6]}"
        email = f"sp5-inactive-{uuid.uuid4().hex[:6]}@example.com"

        org = OrganizationRecord(
            id=org_id,
            name="Sprint 5 Inactive Tenant",
            slug=f"slug-{uuid.uuid4().hex[:6]}",
            tier="starter",
            lead_credits_limit=50,
            lead_credits_used=0,
            is_active=False,  # Inactive
            metadata_json={"package_key": "company_os_starter"},
        )
        user = UserRecord(
            id=user_id,
            org_id=org_id,
            email=email,
            full_name="Inactive Tenant Admin",
            role="owner",
            password_hash=hash_password("Pass12345!"),
            is_active=True,
        )
        self.db.add(org)
        self.db.add(user)
        self.db.commit()

        token = create_access_token(user_id=user_id, email=email, role="owner", org_id=org_id)
        headers = {"Authorization": f"Bearer {token}"}

        resp = self.client.post(
            "/v1/me/use-service",
            headers=headers,
            json={
                "service_key": "bike_rebalance_analytics",
                "payload": {"hour_of_day": 10},
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "Organization subscription is inactive")


if __name__ == "__main__":
    unittest.main()
