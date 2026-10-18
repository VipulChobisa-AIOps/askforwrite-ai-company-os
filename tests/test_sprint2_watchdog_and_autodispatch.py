"""Comprehensive Test Suite for Sprint 2:
1. Active Monitoring & Controlling Watchdog Agent (stalled tasks, spoof detection, credit exhaustion, trust chain)
2. Alert listing, resolution with Merkle TrustBlock sealing, and telemetry
3. Auto-dispatch of downstream actions (Outreach dispatch & SEO draft publishing) on HITL approval
4. Command Center UI verification for Warehouse StockSense AI and Watchdog Controller
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
import unittest
import uuid
import os

from fastapi.testclient import TestClient

from app.db.database import Base, SessionLocal, engine, get_db
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    FieldAttendanceRecord,
    LeadRecordRow,
    OrderRecord,
    OrganizationRecord,
    OutreachRecord,
    SeoDraftRecord,
    SupervisorAlertRecord,
    TaskRecord,
    TrustBlock,
)
from app.main import app
from app.services.approvals import decide_approval, request_approval
from app.services.watchdog import (
    calculate_system_health_score,
    get_system_control_telemetry,
    list_watchdog_alerts,
    resolve_watchdog_alert,
    run_system_watchdog_scan,
)


class Sprint2WatchdogAndAutoDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.manager_key = "test-manager-key-sprint2-watchdog-32ch"
        os.environ["MANAGER_API_KEY"] = cls.manager_key
        cls.client = TestClient(app)
        cls.headers = {
            "X-API-Key": cls.manager_key,
            "X-Correlation-ID": "test-sprint2-corr-001",
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

    def test_watchdog_scan_detects_stalled_tasks_and_approvals(self):
        """Watchdog scan must flag PENDING tasks and approvals older than stale_minutes."""
        stale_time = datetime.now(UTC) - timedelta(minutes=120)

        stalled_task = TaskRecord(
            id=f"stalled-task-{uuid.uuid4().hex[:8]}",
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
            objective="Stalled delivery task",
            status="PENDING",
            created_at=stale_time,
        )
        self.db.add(stalled_task)

        stalled_approval = ApprovalRequest(
            id=f"stalled-appr-{uuid.uuid4().hex[:8]}",
            task_id=stalled_task.id,
            action="external_sales_outreach",
            detail={"note": "Stalled approval request"},
            idempotency_key=f"idemp-{uuid.uuid4().hex[:8]}",
            request_hash=f"hash-{uuid.uuid4().hex[:8]}",
            status="PENDING",
            requested_by="sales_agent",
            created_at=stale_time,
        )
        self.db.add(stalled_approval)

        stalled_order = OrderRecord(
            id=f"stalled-order-{uuid.uuid4().hex[:8]}",
            transaction_id=f"tx-{uuid.uuid4().hex[:8]}",
            customer_email="lagging@corp.example.com",
            amount=50000.0,
            currency="INR",
            status="CONFIRMED",
            created_at=stale_time,
        )
        self.db.add(stalled_order)
        self.db.commit()

        scan_result = run_system_watchdog_scan(self.db, stale_minutes=30)
        self.assertIn("alerts_detected", scan_result)
        self.assertIn("health_score", scan_result)

        alerts = self.db.query(SupervisorAlertRecord).filter_by(alert_type="STALLED_TASK").all()
        self.assertTrue(len(alerts) >= 2)
        flagged_descs = [a.description for a in alerts]
        self.assertTrue(any(stalled_task.id in d for d in flagged_descs))
        self.assertTrue(any(stalled_approval.id in d for d in flagged_descs))

    def test_watchdog_scan_detects_gps_spoof_and_geofence_breach(self):
        """Watchdog scan must flag mock GPS telemetry as CRITICAL alerts."""
        user_id = f"field-user-spoof-{uuid.uuid4().hex[:8]}"
        mock_att = FieldAttendanceRecord(
            id=f"spoof-att-{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            event_type="CHECK_IN",
            device_fingerprint="fp-mock-01",
            idempotency_key=f"idemp-{uuid.uuid4().hex[:8]}",
            latitude=26.9124,
            longitude=75.7873,
            accuracy_meters=5.0,
            is_mock_location_detected=True,
            status="SPOOF_REJECTED",
        )
        self.db.add(mock_att)
        self.db.commit()

        scan_result = run_system_watchdog_scan(self.db)
        self.assertGreaterEqual(scan_result["alerts_detected"], 1)

        spoof_alerts = (
            self.db.query(SupervisorAlertRecord)
            .filter_by(alert_type="SPOOF_OR_GEOFENCE_BREACH")
            .all()
        )
        self.assertTrue(len(spoof_alerts) >= 1)
        target = next(
            (
                a
                for a in spoof_alerts
                if mock_att.id in a.description
                or (a.metadata_json and a.metadata_json.get("attendance_id") == mock_att.id)
            ),
            None,
        )
        self.assertIsNotNone(target)
        self.assertEqual(target.severity, "CRITICAL")
        self.assertFalse(target.is_acknowledged)

    def test_watchdog_scan_detects_credit_exhaustion_risk(self):
        """Watchdog scan must detect organizations at or above quota limit."""
        org_id = f"org-quota-{uuid.uuid4().hex[:8]}"
        org = OrganizationRecord(
            id=org_id,
            name="Depleted Credits Enterprise",
            slug=f"org-slug-{uuid.uuid4().hex[:8]}",
            lead_credits_quota=100,
            lead_credits_used=100,
            outreach_credits_quota=500,
            outreach_credits_used=200,
            tier="growth",
        )
        self.db.add(org)
        self.db.commit()

        scan_result = run_system_watchdog_scan(self.db)
        self.assertGreaterEqual(scan_result["alerts_detected"], 1)

        quota_alerts = (
            self.db.query(SupervisorAlertRecord)
            .filter_by(alert_type="CREDIT_EXHAUSTION_RISK")
            .all()
        )
        self.assertTrue(any(a.org_id == org_id or org_id in a.description for a in quota_alerts))

    def test_resolve_watchdog_alert_seals_trust_block(self):
        """Resolving a watchdog alert must update status, log AuditLog, and seal a TrustBlock."""
        alert = SupervisorAlertRecord(
            id=f"alt-{uuid.uuid4().hex[:8]}",
            alert_type="STALLED_TASK",
            severity="HIGH",
            title="Stalled Task Detected",
            description="Task stalled-123 is pending",
            suggested_action="Restart task",
            is_acknowledged=False,
        )
        self.db.add(alert)
        self.db.commit()

        initial_blocks = self.db.query(TrustBlock).count()
        res = resolve_watchdog_alert(
            self.db,
            alert_id=alert.id,
            resolved_by="owner",
            resolution_notes="Manually cleared and unblocked",
        )

        self.assertEqual(res["status"], "RESOLVED")
        self.assertEqual(res["alert_id"], alert.id)
        self.assertIsNotNone(res["block_hash"])

        self.db.refresh(alert)
        self.assertTrue(alert.is_acknowledged)
        self.assertEqual(alert.acknowledged_by, "owner")
        self.assertIsNotNone(alert.acknowledged_at)

        new_blocks = self.db.query(TrustBlock).count()
        self.assertEqual(new_blocks, initial_blocks + 1)

        # Test list_watchdog_alerts service
        all_alerts = list_watchdog_alerts(self.db)
        self.assertGreaterEqual(len(all_alerts), 1)
        resolved_alerts = list_watchdog_alerts(self.db, status="RESOLVED")
        self.assertTrue(any(a["id"] == alert.id for a in resolved_alerts))

        audit = (
            self.db.query(AuditLog)
            .filter_by(action="watchdog_alert_resolved", task_id=alert.task_id or alert.id)
            .first()
        )
        self.assertIsNotNone(audit)

    def test_get_system_control_telemetry(self):
        """Telemetry must return composite health score and operational metrics."""
        health = calculate_system_health_score(self.db)
        self.assertGreaterEqual(health, 0)
        self.assertLessEqual(health, 100)

        telemetry = get_system_control_telemetry(self.db)
        self.assertIn("health_score", telemetry)
        self.assertIn("active_alerts_total", telemetry)
        self.assertIn("operational_metrics", telemetry)
        self.assertGreaterEqual(telemetry["health_score"], 0)
        self.assertLessEqual(telemetry["health_score"], 100)
        self.assertIn("task_completion_rate", telemetry["operational_metrics"])
        self.assertIn("pending_approval_queue_depth", telemetry["operational_metrics"])

    def test_auto_dispatch_outreach_on_approval(self):
        """When an approval is APPROVED, any linked OutreachRecord must be auto-dispatched."""
        task = TaskRecord(
            id=f"task-outreach-{uuid.uuid4().hex[:8]}",
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
            objective="Cold Outreach Campaign",
            status="PENDING",
        )
        self.db.add(task)

        lead = LeadRecordRow(
            id=f"lead-outreach-{uuid.uuid4().hex[:8]}",
            task_id=task.id,
            company="Prospective Tech",
            website="https://prospect.example.com",
            domain=f"prospect-{uuid.uuid4().hex[:6]}.example.com",
            industry="Software",
            geography="India",
            status="QUALIFIED",
            fit_score=0.85,
            confidence=0.9,
            public_contact_channel="founder@prospect.example.com",
            recommended_next_step="owner_review",
            do_not_contact=False,
        )
        self.db.add(lead)
        self.db.commit()

        approval_res = request_approval(
            db=self.db,
            task_id=task.id,
            lead_id=lead.id,
            action="external_sales_outreach",
            detail={"pitch_id": "pitch-01"},
            idempotency_key=f"idemp-{uuid.uuid4().hex[:8]}",
            requested_by="sales_agent",
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
        )
        appr_id = str(approval_res["approval_id"])

        outreach = OutreachRecord(
            id=f"outreach-{uuid.uuid4().hex[:8]}",
            lead_id=lead.id,
            task_id=task.id,
            recipient_email="founder@prospect.example.com",
            subject="Introducing AI Company OS",
            body_text="Hello, we can automate your operations.",
            channel="email",
            status="PENDING_APPROVAL",
            approval_id=appr_id,
            idempotency_key=f"idemp-{uuid.uuid4().hex[:8]}",
        )
        self.db.add(outreach)
        self.db.commit()

        # Decide approval as APPROVED
        decision_res = decide_approval(
            db=self.db,
            approval_id=appr_id,
            decision="APPROVED",
            decided_by="owner",
            reason="Campaign copy approved for dispatch",
        )

        self.assertEqual(decision_res["status"], "APPROVED")
        self.assertEqual(decision_res.get("auto_executed_action"), "outreach_dispatched")

        # Verify OutreachRecord was processed
        self.db.refresh(outreach)
        self.assertIn(outreach.status, ["DISPATCHED", "FAILED_TO_SEND", "SENT", "FAILED"])

        # Verify TaskRecord is marked completed
        self.db.refresh(task)
        self.assertEqual(task.status, "COMPLETED")

    def test_auto_publish_seo_draft_on_approval(self):
        """When live_publishing approval is APPROVED, linked SeoDraftRecord must become PUBLISHED."""
        task = TaskRecord(
            id=f"task-seo-{uuid.uuid4().hex[:8]}",
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
            objective="Publish SEO Blog Article",
            status="PENDING",
        )
        self.db.add(task)

        seo_draft = SeoDraftRecord(
            id=f"seo-{uuid.uuid4().hex[:8]}",
            task_id=task.id,
            target_network="askforwrite.in",
            keywords=["ai company os", "warehouse automation"],
            content="# Autonomous AI Operations\nPublished via Copilot.",
            status="DRAFT",
        )
        self.db.add(seo_draft)
        self.db.commit()

        approval_res = request_approval(
            db=self.db,
            task_id=task.id,
            lead_id=None,
            action="live_publishing",
            detail={"seo_draft_id": seo_draft.id},
            idempotency_key=f"idemp-{uuid.uuid4().hex[:8]}",
            requested_by="seo_copilot",
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
        )
        appr_id = str(approval_res["approval_id"])
        seo_draft.approval_id = appr_id
        self.db.commit()

        decision_res = decide_approval(
            db=self.db,
            approval_id=appr_id,
            decision="APPROVED",
            decided_by="owner",
            reason="SEO copy quality verified",
        )

        self.assertEqual(decision_res["status"], "APPROVED")
        self.assertEqual(decision_res.get("auto_executed_action"), "seo_draft_published")

        self.db.refresh(seo_draft)
        self.assertEqual(seo_draft.status, "PUBLISHED")
        self.assertIsNotNone(seo_draft.decided_at)

    def test_watchdog_http_endpoints(self):
        """Test FastAPI HTTP endpoints for Watchdog scanning, alerts, resolve, and telemetry."""
        # 1. Trigger scan
        scan_resp = self.client.post("/v1/watchdog/scan", headers=self.headers)
        self.assertEqual(scan_resp.status_code, 200)
        data = scan_resp.json()
        self.assertIn("health_score", data)
        self.assertIn("scan_timestamp", data)
        self.assertIn("new_alerts_detected", data)

        # 2. Get alerts
        alerts_resp = self.client.get("/v1/watchdog/alerts", headers=self.headers)
        self.assertEqual(alerts_resp.status_code, 200)
        alerts_data = alerts_resp.json()
        self.assertIn("alerts", alerts_data)

        # Create alert to resolve via API
        test_alert = SupervisorAlertRecord(
            id=f"api-alt-{uuid.uuid4().hex[:8]}",
            alert_type="STALLED_TASK",
            severity="MEDIUM",
            title="Test API Alert",
            description="Testing alert resolution endpoint",
            is_acknowledged=False,
        )
        self.db.add(test_alert)
        self.db.commit()

        # 3. Resolve alert
        resolve_resp = self.client.post(
            f"/v1/watchdog/alerts/{test_alert.id}/resolve",
            headers=self.headers,
            json={"resolved_by": "owner", "resolution_notes": "API test resolve"},
        )
        self.assertEqual(resolve_resp.status_code, 200)
        res_data = resolve_resp.json()
        self.assertEqual(res_data["status"], "RESOLVED")
        self.assertIn("block_hash", res_data)

        # 4. Get telemetry
        telem_resp = self.client.get("/v1/watchdog/telemetry", headers=self.headers)
        self.assertEqual(telem_resp.status_code, 200)
        t_data = telem_resp.json()
        self.assertIn("health_score", t_data)
        self.assertIn("active_alerts_total", t_data)
        self.assertIn("operational_metrics", t_data)

    def test_dashboard_ui_elements_exist(self):
        """Verify dashboard index.html and dashboard.js contain required StockSense and Watchdog wiring."""
        dashboard_dir = Path(__file__).resolve().parent.parent / "app" / "dashboard"
        index_html = (dashboard_dir / "index.html").read_text(encoding="utf-8")
        dashboard_js = (dashboard_dir / "dashboard.js").read_text(encoding="utf-8")

        # Inventory UI requirements
        self.assertIn('data-page="inventory"', index_html)
        self.assertIn('id="nav-inventory"', index_html)
        self.assertIn('id="page-inventory"', index_html)
        self.assertIn('id="btn-run-inventory-audit"', index_html)
        self.assertIn('id="inventory-abc-xyz-table"', index_html)
        self.assertIn('id="inventory-reorder-table"', index_html)
        self.assertIn('id="inventory-deadstock-list"', index_html)
        self.assertIn('id="btn-submit-inventory-uat"', index_html)

        # Watchdog UI requirements
        self.assertIn('id="btn-watchdog-scan"', index_html)
        self.assertIn('id="watchdog-health-score"', index_html)
        self.assertIn('id="watchdog-alerts-list"', index_html)
        self.assertIn('id="field-alerts-list"', index_html)

        # JS wiring
        self.assertIn("fetchWatchdogData", dashboard_js)
        self.assertIn("renderWatchdogTelemetry", dashboard_js)
        self.assertIn("renderWatchdogAlerts", dashboard_js)
        self.assertIn("initInventoryPage", dashboard_js)
        self.assertIn("runInventoryAudit", dashboard_js)
        self.assertIn("/v1/inventory/analyze", dashboard_js)
        self.assertIn("/v1/watchdog/telemetry", dashboard_js)
        self.assertIn("/v1/watchdog/alerts", dashboard_js)


if __name__ == "__main__":
    unittest.main()
