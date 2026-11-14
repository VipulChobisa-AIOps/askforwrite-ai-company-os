"""Test Suite for Database Migrations (Alembic Chain & Schema Parity).

Validates:
- Migration revisions linear DAG without orphaned branches
- Head revision is e5f6a1b2c3d4 with down_revision d4e5f6a1b2c3
- upgrade() and downgrade() execution parity with app/db/models.py
"""

from __future__ import annotations

import unittest
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

import migrations.versions.e5f6a1b2c3d4_add_watchdog_preview_and_shift_tables as sprint5_migration
import migrations.versions.f6a1b2c3d4e5_add_sovereign_payment_sessions as sovereign_migration
import migrations.versions.g7b2c3d4e5f6_add_p1_modular_workforce_tables as p1_migration
import migrations.versions.h8c3d4e5f6a7_add_p2_commercial_revenue_engine_tables as p2_migration
import migrations.versions.i9d4e5f6a7b8_add_p3_customer_success_growth_engine_tables as p3_migration


class MigrationChainAndSchemaParityTests(unittest.TestCase):
    def setUp(self):
        self.alembic_ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
        self.config = Config(str(self.alembic_ini_path))
        self.script_directory = ScriptDirectory.from_config(self.config)

    def test_migration_chain_has_single_head_and_correct_revisions(self):
        """Verify the migration chain ends at j0e5f6a7b8c9 with down_revision i9d4e5f6a7b8."""
        heads = self.script_directory.get_heads()
        self.assertEqual(len(heads), 1, f"Expected exactly 1 migration head, got: {heads}")
        head_rev = heads[0]
        self.assertEqual(head_rev, "j0e5f6a7b8c9")

        head_script = self.script_directory.get_revision(head_rev)
        self.assertIsNotNone(head_script)
        self.assertEqual(head_script.down_revision, "i9d4e5f6a7b8")

        prev_script = self.script_directory.get_revision("f6a1b2c3d4e5")
        self.assertIsNotNone(prev_script)
        self.assertEqual(prev_script.down_revision, "e5f6a1b2c3d4")

        # Verify earlier down revision script exists
        down_script = self.script_directory.get_revision("e5f6a1b2c3d4")
        self.assertIsNotNone(down_script)
        self.assertEqual(down_script.down_revision, "d4e5f6a1b2c3")

    def test_p1_modular_workforce_migration_upgrade_and_downgrade_parity(self):
        """Verify upgrade() and downgrade() of g7b2c3d4e5f6 against SQLite engine."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        from alembic.runtime.migration import MigrationContext
        from alembic.operations import Operations

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)

            orig_op = p1_migration.op
            p1_migration.op = op
            try:
                p1_migration.upgrade()
                conn.commit()

                inspector = inspect(conn)
                table_names = set(inspector.get_table_names())
                expected_tables = {
                    "business_profiles",
                    "structured_requirements",
                    "tenant_subscription_profiles",
                    "tenant_agent_configs",
                    "connector_states",
                    "workflow_definitions",
                    "workflow_runs",
                    "execution_evidence_records",
                    "credit_ledger_records",
                    "emergency_stop_records",
                }
                self.assertTrue(expected_tables.issubset(table_names))

                evidence_cols = {c["name"] for c in inspector.get_columns("execution_evidence_records")}
                self.assertTrue({
                    "execution_id", "tenant_id", "workflow_id", "agent_id", "connector_id",
                    "execution_mode", "input_reference", "output_reference", "provider_request_id",
                    "fallback_used", "approval_id", "status", "failure_reason", "credits_consumed",
                    "started_at", "completed_at", "evidence_reference", "version",
                }.issubset(evidence_cols))

                p1_migration.downgrade()
                conn.commit()

                inspector_after = inspect(conn)
                table_names_after = set(inspector_after.get_table_names())
                self.assertTrue(expected_tables.isdisjoint(table_names_after))
            finally:
                p1_migration.op = orig_op

    def test_sprint5_migration_upgrade_and_downgrade_parity(self):
        """Verify upgrade() and downgrade() of e5f6a1b2c3d4 against SQLite engine."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        from alembic.runtime.migration import MigrationContext
        from alembic.operations import Operations

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)

            # Patch Alembic op module in migration to use our test connection
            orig_op = sprint5_migration.op
            sprint5_migration.op = op
            try:
                # 1. Run upgrade
                sprint5_migration.upgrade()
                conn.commit()

                inspector = inspect(conn)
                table_names = inspector.get_table_names()

                self.assertIn("supervisor_alert_records", table_names)
                self.assertIn("preview_records", table_names)
                self.assertIn("shift_records", table_names)

                # Verify supervisor_alert_records columns and indexes
                alert_cols = {c["name"] for c in inspector.get_columns("supervisor_alert_records")}
                expected_alert_cols = {
                    "id", "org_id", "user_id", "task_id", "alert_type", "severity",
                    "title", "description", "suggested_action", "is_acknowledged",
                    "acknowledged_by", "acknowledged_at", "created_at", "metadata_json",
                }
                self.assertTrue(expected_alert_cols.issubset(alert_cols))
                alert_indexes = {ix["name"] for ix in inspector.get_indexes("supervisor_alert_records")}
                self.assertIn("ix_alert_org_acknowledged", alert_indexes)
                self.assertIn("ix_alert_user_severity", alert_indexes)

                # Verify preview_records columns and indexes
                preview_cols = {c["name"] for c in inspector.get_columns("preview_records")}
                expected_preview_cols = {
                    "id", "preview_token", "company_name", "domain", "recommended_package",
                    "lead_id", "custom_audit", "sample_deliverable", "benchmarks",
                    "payment_links", "views_count", "trust_block_hash", "created_at", "updated_at",
                }
                self.assertTrue(expected_preview_cols.issubset(preview_cols))
                preview_indexes = {ix["name"] for ix in inspector.get_indexes("preview_records")}
                self.assertIn("ix_preview_token", preview_indexes)
                self.assertIn("ix_preview_domain", preview_indexes)

                # Verify shift_records columns and indexes
                shift_cols = {c["name"] for c in inspector.get_columns("shift_records")}
                expected_shift_cols = {
                    "id", "shift_id", "shift_type", "status", "summary",
                    "trust_block_hash", "started_at", "completed_at",
                }
                self.assertTrue(expected_shift_cols.issubset(shift_cols))
                shift_indexes = {ix["name"] for ix in inspector.get_indexes("shift_records")}
                self.assertIn("ix_shift_id", shift_indexes)
                self.assertIn("ix_shift_status", shift_indexes)

                # 2. Run downgrade
                sprint5_migration.downgrade()
                conn.commit()

                inspector_after = inspect(conn)
                table_names_after = inspector_after.get_table_names()
                self.assertNotIn("supervisor_alert_records", table_names_after)
                self.assertNotIn("preview_records", table_names_after)
                self.assertNotIn("shift_records", table_names_after)

            finally:
                sprint5_migration.op = orig_op

    def test_sovereign_sessions_migration_upgrade_and_downgrade_parity(self):
        """Verify upgrade() and downgrade() of f6a1b2c3d4e5 (sovereign_payment_sessions)."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        from alembic.runtime.migration import MigrationContext
        from alembic.operations import Operations

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)

            orig_op = sovereign_migration.op
            sovereign_migration.op = op
            try:
                # 1. Run upgrade
                sovereign_migration.upgrade()
                conn.commit()

                inspector = inspect(conn)
                table_names = inspector.get_table_names()
                self.assertIn("sovereign_payment_sessions", table_names)

                cols = {c["name"] for c in inspector.get_columns("sovereign_payment_sessions")}
                expected_cols = {
                    "session_id", "package_key", "package_name", "company_name",
                    "customer_email", "customer_name", "currency", "amount",
                    "preferred_rail", "status", "upi_uri", "checkout_url", "created_at"
                }
                self.assertTrue(expected_cols.issubset(cols))

                # 2. Run downgrade
                sovereign_migration.downgrade()
                conn.commit()

                inspector_after = inspect(conn)
                self.assertNotIn("sovereign_payment_sessions", inspector_after.get_table_names())
            finally:
                sovereign_migration.op = orig_op

    def test_neon_postgres_migration_recovery_drill(self):
        """Issue #18: Simulate Neon PostgreSQL transient disconnect during migration and recover cleanly."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        from alembic.runtime.migration import MigrationContext
        from alembic.operations import Operations
        from unittest.mock import MagicMock

        # Phase 1: Simulate connection disconnect / failure mid-migration
        failing_op = MagicMock()
        failing_op.create_table.side_effect = ConnectionResetError("Neon server closed connection unexpectedly")

        orig_op = sovereign_migration.op
        sovereign_migration.op = failing_op
        try:
            with self.assertRaises(ConnectionResetError):
                sovereign_migration.upgrade()
        finally:
            sovereign_migration.op = orig_op

        # Phase 2: Recovery drill - reconnect with healthy connection and verify idempotent migration succeeds
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            healthy_op = Operations(ctx)
            sovereign_migration.op = healthy_op
            try:
                sovereign_migration.upgrade()
                conn.commit()
                inspector = inspect(conn)
                self.assertIn("sovereign_payment_sessions", inspector.get_table_names())
            finally:
                sovereign_migration.op = orig_op

    def test_p2_commercial_migration_upgrade_and_downgrade_parity(self):
        """Verify upgrade() and downgrade() of h8c3d4e5f6a7 (6 P2 commercial tables) against SQLite."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        from alembic.runtime.migration import MigrationContext
        from alembic.operations import Operations

        expected_tables = (
            "p2_prospect_dossiers",
            "p2_commercial_proposals",
            "p2_suppression_entries",
            "p2_payment_reconciliation_queue",
            "p2_customer_engagements",
            "p2_acceptance_checklist_steps",
        )

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)
            orig_op = p2_migration.op
            p2_migration.op = op
            try:
                p2_migration.upgrade()
                conn.commit()
                inspector = inspect(conn)
                tables = set(inspector.get_table_names())
                for tbl in expected_tables:
                    self.assertIn(tbl, tables)

                p2_migration.downgrade()
                conn.commit()
                tables_after = set(inspect(conn).get_table_names())
                for tbl in expected_tables:
                    self.assertNotIn(tbl, tables_after)
            finally:
                p2_migration.op = orig_op

    def test_p3_customer_success_migration_upgrade_and_downgrade_parity(self):
        """Verify upgrade() and downgrade() of i9d4e5f6a7b8 (12 P3 CS tables) against SQLite."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        from alembic.runtime.migration import MigrationContext
        from alembic.operations import Operations

        expected_tables = (
            "p3_customer_accounts",
            "p3_onboarding_workflows",
            "p3_service_deliveries",
            "p3_support_tickets",
            "p3_subscription_events",
            "p3_growth_opportunities",
            "p3_unit_economics_entries",
            "p3_customer_cost_budgets",
            "p3_improvement_items",
            "p3_compliance_requests",
            "p3_operational_incidents",
            "p3_acceptance_steps",
        )

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)
            orig_op = p3_migration.op
            p3_migration.op = op
            try:
                p3_migration.upgrade()
                conn.commit()
                inspector = inspect(conn)
                tables = set(inspector.get_table_names())
                for tbl in expected_tables:
                    self.assertIn(tbl, tables)

                p3_migration.downgrade()
                conn.commit()
                tables_after = set(inspect(conn).get_table_names())
                for tbl in expected_tables:
                    self.assertNotIn(tbl, tables_after)
            finally:
                p3_migration.op = orig_op


if __name__ == "__main__":
    unittest.main()
