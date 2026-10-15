"""Tests for AskforWrite Autonomous Dispatch & Dynamic Route Optimizer."""

import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    FieldAttendanceRecord,
    FieldTaskRecord,
    OrganizationRecord,
    UserRecord,
)
from app.main import app
from app.security.auth import APIPrincipal, get_current_principal
from app.security.trust_chain import ensure_genesis_block


class FieldDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=cls.engine, expire_on_commit=False
        )
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        self.db = self.TestingSessionLocal()
        ensure_genesis_block(self.db)

        # Seed test org & users
        self.org_id = f"test-org-{uuid.uuid4().hex[:8]}"
        self.manager_id = f"manager-{uuid.uuid4().hex[:8]}"
        self.user1_id = f"exec-1-{uuid.uuid4().hex[:8]}"
        self.user2_id = f"exec-2-{uuid.uuid4().hex[:8]}"

        org = OrganizationRecord(
            id=self.org_id,
            name="Delhi Express Operations",
            slug=f"delhi-exp-{uuid.uuid4().hex[:6]}",
            tier="pro",
        )
        manager = UserRecord(
            id=self.manager_id,
            org_id=self.org_id,
            email=f"mgr-{uuid.uuid4().hex[:6]}@delhiexpress.in",
            full_name="Operations Manager",
            role="manager",
        )
        exec1 = UserRecord(
            id=self.user1_id,
            org_id=self.org_id,
            email=f"vikram-{uuid.uuid4().hex[:6]}@delhiexpress.in",
            full_name="Vikram Singh",
            role="member",
        )
        exec2 = UserRecord(
            id=self.user2_id,
            org_id=self.org_id,
            email=f"amit-{uuid.uuid4().hex[:6]}@delhiexpress.in",
            full_name="Amit Verma",
            role="member",
        )
        self.db.add_all([org, manager, exec1, exec2])
        self.db.commit()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_principal] = lambda: APIPrincipal(
            subject=self.manager_id,
            role="manager",
            org_id=self.org_id,
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.clear()

    def test_create_and_list_field_tasks(self):
        """Manager creates a client visit task and verifies it in task list."""
        resp = self.client.post(
            "/v1/field-force/tasks",
            json={
                "title": "Quarterly Store Inspection",
                "client_name": "Apollo Pharmacy CP Branch",
                "destination_lat": 28.6328,
                "destination_lon": 77.2197,
                "priority": "HIGH",
            },
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["client_name"], "Apollo Pharmacy CP Branch")
        self.assertEqual(data["status"], "PENDING")
        self.assertEqual(data["priority"], "HIGH")

        list_resp = self.client.get("/v1/field-force/tasks")
        self.assertEqual(list_resp.status_code, 200)
        tasks = list_resp.json()
        self.assertTrue(any(t["client_name"] == "Apollo Pharmacy CP Branch" for t in tasks))

    def test_autonomous_dispatch_matches_closest_available_executive(self):
        """AI matches Executive 2 who is 1km away over Executive 1 who is 30km away."""
        # Record location for Exec 1: Gurgaon (28.4595, 77.0266) - 30 km away
        loc1 = FieldAttendanceRecord(
            id=str(uuid.uuid4()),
            org_id=self.org_id,
            user_id=self.user1_id,
            event_type="CHECK_IN",
            latitude=28.4595,
            longitude=77.0266,
            accuracy_meters=10.0,
            device_fingerprint="hw-001",
            status="VERIFIED",
            idempotency_key=f"loc1-{uuid.uuid4().hex[:8]}",
        )
        # Record location for Exec 2: Connaught Place (28.6310, 77.2180) - 0.5 km away
        loc2 = FieldAttendanceRecord(
            id=str(uuid.uuid4()),
            org_id=self.org_id,
            user_id=self.user2_id,
            event_type="CHECK_IN",
            latitude=28.6310,
            longitude=77.2180,
            accuracy_meters=10.0,
            device_fingerprint="hw-002",
            status="VERIFIED",
            idempotency_key=f"loc2-{uuid.uuid4().hex[:8]}",
        )
        self.db.add_all([loc1, loc2])
        self.db.commit()

        # Create task at Connaught Place
        task_resp = self.client.post(
            "/v1/field-force/tasks",
            json={
                "title": "Urgent Medical Sample Pickup",
                "client_name": "Max Healthcare Clinic",
                "destination_lat": 28.6328,
                "destination_lon": 77.2197,
                "priority": "URGENT",
            },
        )
        task_id = task_resp.json()["id"]

        # Run Autonomous Dispatch
        dispatch_resp = self.client.post(f"/v1/field-force/tasks/{task_id}/auto-dispatch")
        self.assertEqual(dispatch_resp.status_code, 200)
        result = dispatch_resp.json()
        self.assertEqual(result["status"], "DISPATCHED")
        # Executive 2 was closest, should be matched!
        self.assertEqual(result["assigned_to"], self.user2_id)
        self.assertEqual(result["telemetry"]["matched_user_id"], self.user2_id)

    def test_dynamic_route_optimizer_sequences_multi_stop_visits(self):
        """Sequences 4 client visits in optimal TSP order and calculates fuel savings."""
        # Create 4 tasks assigned to Executive 1 in Delhi NCR
        stops = [
            ("Client A (South Delhi)", 28.5355, 77.2410, "NORMAL"),
            ("Client B (Urgent Noida Hub)", 28.5700, 77.3200, "URGENT"),
            ("Client C (Lajpat Nagar)", 28.5677, 77.2433, "HIGH"),
            ("Client D (Okhla Industrial Area)", 28.5284, 77.2796, "NORMAL"),
        ]
        created_task_ids = []
        for title, lat, lon, prio in stops:
            t = FieldTaskRecord(
                id=str(uuid.uuid4()),
                org_id=self.org_id,
                assigned_to_user_id=self.user1_id,
                title=title,
                client_name=title,
                destination_lat=lat,
                destination_lon=lon,
                priority=prio,
                status="PENDING",
            )
            self.db.add(t)
            created_task_ids.append(t.id)
        self.db.commit()

        # Run Route Optimizer starting at Connaught Place (28.6139, 77.2090)
        route_resp = self.client.post(
            "/v1/field-force/routes/optimize",
            json={
                "user_id": self.user1_id,
                "start_latitude": 28.6139,
                "start_longitude": 77.2090,
                "task_ids": created_task_ids,
            },
        )
        self.assertEqual(route_resp.status_code, 200)
        route = route_resp.json()
        self.assertEqual(route["total_stops"], 4)
        self.assertGreater(route["total_distance_km"], 0.0)
        self.assertGreater(route["estimated_total_minutes"], 0.0)
        self.assertGreaterEqual(route["estimated_fuel_savings_percent"], 10.0)

        # Check sequence indices are numbered 1 through 4
        seq_indices = [s["sequence_index"] for s in route["optimized_stops"]]
        self.assertEqual(seq_indices, [1, 2, 3, 4])

        # Verify DB records updated with route_sequence_index
        tasks_in_db = (
            self.db.query(FieldTaskRecord)
            .filter(FieldTaskRecord.id.in_(created_task_ids))
            .all()
        )
        for t in tasks_in_db:
            self.assertIsNotNone(t.route_sequence_index)


if __name__ == "__main__":
    unittest.main()
