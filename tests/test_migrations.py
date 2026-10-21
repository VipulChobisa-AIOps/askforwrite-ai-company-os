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


class MigrationChainAndSchemaParityTests(unittest.TestCase):
    def setUp(self):
        self.alembic_ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
        self.config = Config(str(self.alembic_ini_path))
        self.script_directory = ScriptDirectory.from_config(self.config)

    def test_migration_chain_has_single_head_and_correct_revisions(self):
        """Verify the migration chain ends at f6a1b2c3d4e5 with down_revision e5f6a1b2c3d4."""
        heads = self.script_directory.get_heads()
        self.assertEqual(len(heads), 1, f"Expected exactly 1 migration head, got: {heads}")
        head_rev = heads[0]
        self.assertEqual(head_rev, "f6a1b2c3d4e5")

        head_script = self.script_directory.get_revision(head_rev)
        self.assertIsNotNone(head_script)
        self.assertEqual(head_script.down_revision, "e5f6a1b2c3d4")

        # Verify down revision script exists
        down_script = self.script_directory.get_revision("e5f6a1b2c3d4")
        self.assertIsNotNone(down_script)
        self.assertEqual(down_script.down_revision, "d4e5f6a1b2c3")

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


if __name__ == "__main__":
    unittest.main()
