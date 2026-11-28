"""Comprehensive Phase 3 StockSense Persistent SME WMS & 3PL Operations Test Suite.

Verifies:
1. Multi-tenant Warehouse -> Zone (Ambient/Cold-Chain/Hazmat/Quarantine) -> Bin hierarchy & Directed Velocity Slotting.
2. Inbound GRN receiving with shortage/damage proof, zone safety enforcement & QR bin labels.
3. Directed FEFO/FIFO outbound wave picking with hard expired-lot blocking & immutable StockLedgerEntryRecord.
4. Atomic double-entry bin transfers & blind mobile cycle counting with ECDSA stocktake certification.
5. 3PL multi-client automated storage + inbound + outbound + packing monthly billing with GST & ECDSA seal.
6. Bulk CSV SKU & opening stock importer (dry-run validation + atomic commit), Shopify/ERP webhook & Tally XML export.
7. Holt double exponential smoothing MAE/MAPE metrics, PostgreSQL UAT persistence, cross-tenant isolation,
   Unified Mobile PWA barcode tab, and Alembic migration s9h4c5d6e7f8 upgrade/downgrade parity.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    InventoryUatRecord,
    OrganizationRecord,
    StockLedgerEntryRecord,
    UserRecord,
)
from app.main import app
from app.security.auth import APIPrincipal, get_current_principal
from app.security.trust_chain import ensure_genesis_block
from app.services.inventory_analytics import compute_reorder_recommendations


class Phase3StockSenseWmsTests(unittest.TestCase):
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

        self.org_a_id = f"wms-org-a-{uuid.uuid4().hex[:8]}"
        self.org_b_id = f"wms-org-b-{uuid.uuid4().hex[:8]}"
        self.mgr_a_id = f"wms-mgr-a-{uuid.uuid4().hex[:8]}"
        self.picker_a_id = f"wms-pick-a-{uuid.uuid4().hex[:8]}"
        self.mgr_b_id = f"wms-mgr-b-{uuid.uuid4().hex[:8]}"

        org_a = OrganizationRecord(
            id=self.org_a_id,
            name="Rajasthan ColdChain & 3PL Hub",
            slug=f"raj3pl-{uuid.uuid4().hex[:6]}",
            tier="operations",
            metadata_json={"entitled_capabilities": ["warehouse_automation", "inventory_analytics"]},
        )
        org_b = OrganizationRecord(
            id=self.org_b_id,
            name="Other Warehouse Corp",
            slug=f"otherwh-{uuid.uuid4().hex[:6]}",
            tier="operations",
            metadata_json={"entitled_capabilities": ["warehouse_automation", "inventory_analytics"]},
        )
        mgr_a = UserRecord(id=self.mgr_a_id, org_id=self.org_a_id, email=f"mgr-{uuid.uuid4().hex[:5]}@raj3pl.in", full_name="Vikram Rathore", role="manager")
        picker_a = UserRecord(id=self.picker_a_id, org_id=self.org_a_id, email=f"pick-{uuid.uuid4().hex[:5]}@raj3pl.in", full_name="Ajay Meena", role="member")
        mgr_b = UserRecord(id=self.mgr_b_id, org_id=self.org_b_id, email=f"mgrb-{uuid.uuid4().hex[:5]}@other.in", full_name="Rival Ops", role="manager")

        self.db.add_all([org_a, org_b, mgr_a, picker_a, mgr_b])
        self.db.commit()

        self.mgr_a = APIPrincipal(subject=mgr_a.email, user_id=self.mgr_a_id, role="manager", org_id=self.org_a_id)
        self.picker_a = APIPrincipal(subject=picker_a.email, user_id=self.picker_a_id, role="member", org_id=self.org_a_id)
        self.mgr_b = APIPrincipal(subject=mgr_b.email, user_id=self.mgr_b_id, role="manager", org_id=self.org_b_id)
        self.active_principal = self.mgr_a

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_principal] = lambda: self.active_principal
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.clear()

    def _seed_facility(self) -> dict[str, str]:
        wh = self.client.post(
            "/v1/wms/warehouses",
            json={"code": f"JPR-{uuid.uuid4().hex[:4]}", "name": "Jaipur Sitapura 3PL Hub", "city": "Jaipur", "total_area_sqft": 35000},
        )
        self.assertEqual(wh.status_code, 201, wh.text)
        wh_id = wh.json()["id"]

        z_amb = self.client.post(f"/v1/wms/warehouses/{wh_id}/zones", json={"code": "Z-AMB", "name": "Ambient Hall", "zone_type": "AMBIENT"}).json()["id"]
        z_cold = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/zones",
            json={"code": "Z-COLD", "name": "2-8C Cold Vault", "zone_type": "COLD_CHAIN", "temperature_min_c": 2.0, "temperature_max_c": 8.0},
        ).json()["id"]
        z_quar = self.client.post(f"/v1/wms/warehouses/{wh_id}/zones", json={"code": "Z-QUAR", "name": "Damage Quarantine", "zone_type": "QUARANTINE"}).json()["id"]

        b_amb_near = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/bins",
            json={"zone_id": z_amb, "bin_code": "A01-R01-S01-B01", "aisle": "A01", "rack": "R01", "shelf": "S01", "velocity_tier": "A", "distance_to_dispatch_m": 6.0},
        ).json()["id"]
        b_amb_far = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/bins",
            json={"zone_id": z_amb, "bin_code": "A04-R02-S03-B02", "aisle": "A04", "rack": "R02", "shelf": "S03", "velocity_tier": "C", "distance_to_dispatch_m": 45.0},
        ).json()["id"]
        b_cold_a = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/bins",
            json={"zone_id": z_cold, "bin_code": "C01-R01-S01-B01", "aisle": "C01", "rack": "R01", "shelf": "S01", "velocity_tier": "A", "distance_to_dispatch_m": 10.0},
        ).json()["id"]
        b_cold_b = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/bins",
            json={"zone_id": z_cold, "bin_code": "C02-R01-S01-B02", "aisle": "C02", "rack": "R01", "shelf": "S01", "velocity_tier": "B", "distance_to_dispatch_m": 25.0},
        ).json()["id"]
        b_quar = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/bins",
            json={"zone_id": z_quar, "bin_code": "Q01-R01-S01-B01", "aisle": "Q01", "rack": "R01", "shelf": "S01", "velocity_tier": "C", "distance_to_dispatch_m": 50.0},
        ).json()["id"]

        client_3pl = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/clients",
            json={
                "client_code": "MEDLIFE",
                "client_name": "MedLife Formulations Pvt Ltd",
                "contact_email": "ops@medlife.in",
                "gstin": "08AAACM1234F1Z2",
                "storage_rate_per_bin_day_inr": 40.0,
                "inbound_handling_rate_per_unit_inr": 2.5,
                "outbound_pick_rate_per_unit_inr": 4.0,
                "packing_rate_per_order_inr": 30.0,
            },
        ).json()["id"]

        return {
            "wh_id": wh_id,
            "b_amb_near": b_amb_near,
            "b_amb_far": b_amb_far,
            "b_cold_a": b_cold_a,
            "b_cold_b": b_cold_b,
            "b_quar": b_quar,
            "client_id": client_3pl,
        }

    # ── 1. Directed Slotting, Zone Safety & GRN Shortage/Damage ───────────

    def test_01_grn_directed_slotting_zone_safety_and_qr_labels(self):
        env = self._seed_facility()
        wh_id = env["wh_id"]

        sku = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/skus",
            json={
                "sku_code": "VAX-COLD-01",
                "name": "Insulin Cold-Chain Vial Pack",
                "barcode": "8901234567890",
                "client_id": env["client_id"],
                "required_zone_type": "COLD_CHAIN",
                "velocity_tier": "A",
                "unit_cost_inr": 850.0,
                "requires_expiry_tracking": True,
            },
        )
        self.assertEqual(sku.status_code, 201, sku.text)

        # Attempting to put COLD_CHAIN SKU into AMBIENT bin MUST fail with 422!
        bad_grn = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/grn",
            json={
                "po_number": "PO-BAD-ZONE",
                "supplier_name": "BioLab India",
                "lines": [{
                    "sku_code": "VAX-COLD-01",
                    "expected_qty": 20,
                    "received_qty": 20,
                    "batch_no": "B1",
                    "expiry_date": "2027-06-01",
                    "target_bin_id": env["b_amb_near"],
                }],
            },
        )
        self.assertEqual(bad_grn.status_code, 422)
        self.assertIn("Zone safety violation", bad_grn.text)

        # Auto-slotted GRN with shortage (5 short) and damage (3 damaged) -> routes good stock to C01-R01-S01-B01 (Class A Cold-Chain)!
        good_grn = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/grn",
            json={
                "po_number": "PO-2026-101",
                "supplier_name": "BioLab India",
                "client_id": env["client_id"],
                "lines": [{
                    "sku_code": "VAX-COLD-01",
                    "expected_qty": 100,
                    "received_qty": 92,
                    "damaged_qty": 3,
                    "batch_no": "BATCH-A1",
                    "expiry_date": "2027-06-30",
                }],
            },
        )
        self.assertEqual(good_grn.status_code, 201, good_grn.text)
        g = good_grn.json()
        self.assertEqual(g["status"], "DISCREPANCY_FLAGGED")
        self.assertEqual(g["lines"][0]["assigned_bin_code"], "C01-R01-S01-B01")
        self.assertEqual(g["discrepancies"][0]["short_qty"], 5)
        self.assertEqual(g["discrepancies"][0]["damaged_qty"], 3)
        self.assertIn("AFW-WMS|", g["qr_labels"][0]["qr_code_payload"])
        self.assertIsNotNone(g["trust_block_hash"])

    # ── 2. Strict FEFO Wave Picking + Expired Lot Hard Block + Immutable Ledger ──

    def test_02_fefo_wave_picking_blocks_expired_lots_and_immutable_ledger(self):
        env = self._seed_facility()
        wh_id = env["wh_id"]
        self.client.post(
            f"/v1/wms/warehouses/{wh_id}/skus",
            json={
                "sku_code": "PHARMA-FEFO",
                "name": "Amoxicillin Strips",
                "client_id": env["client_id"],
                "required_zone_type": "COLD_CHAIN",
                "velocity_tier": "A",
                "unit_cost_inr": 120.0,
                "requires_expiry_tracking": True,
            },
        )

        yesterday = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%d")
        soon = (datetime.now(UTC) + timedelta(days=15)).strftime("%Y-%m-%d")
        later = (datetime.now(UTC) + timedelta(days=180)).strftime("%Y-%m-%d")

        grn = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/grn",
            json={
                "po_number": "PO-FEFO-1",
                "supplier_name": "MedSupply",
                "client_id": env["client_id"],
                "lines": [
                    {"sku_code": "PHARMA-FEFO", "expected_qty": 30, "received_qty": 30, "batch_no": "B-EXPIRED", "expiry_date": yesterday, "target_bin_id": env["b_cold_a"]},
                    {"sku_code": "PHARMA-FEFO", "expected_qty": 20, "received_qty": 20, "batch_no": "B-SOON", "expiry_date": soon, "target_bin_id": env["b_cold_a"]},
                    {"sku_code": "PHARMA-FEFO", "expected_qty": 50, "received_qty": 50, "batch_no": "B-LATER", "expiry_date": later, "target_bin_id": env["b_cold_b"]},
                ],
            },
        )
        self.assertEqual(grn.status_code, 201, grn.text)

        # Pick 35 units -> MUST block B-EXPIRED, pick 20 from B-SOON first, and 15 from B-LATER!
        wave = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/waves",
            json={
                "order_reference": "ORD-FEFO-001",
                "client_id": env["client_id"],
                "lines": [{"sku_code": "PHARMA-FEFO", "requested_qty": 35}],
            },
        )
        self.assertEqual(wave.status_code, 201, wave.text)
        w = wave.json()
        self.assertEqual(w["status"], "OPEN")
        self.assertEqual(len(w["blocked_expired_lots"]), 1)
        self.assertEqual(w["blocked_expired_lots"][0]["batch_no"], "B-EXPIRED")
        self.assertEqual(w["blocked_expired_lots"][0]["reason"], "EXPIRED_LOT_BLOCKED")

        picked_by_batch = {ln["batch_no"]: ln["pick_qty"] for ln in w["pick_lines"]}
        self.assertEqual(picked_by_batch, {"B-SOON": 20, "B-LATER": 15})

        # Dispatch wave
        disp = self.client.post(f"/v1/wms/warehouses/{wh_id}/waves/{w['id']}/dispatch")
        self.assertEqual(disp.status_code, 200, disp.text)
        self.assertEqual(disp.json()["status"], "DISPATCHED")
        self.assertIsNotNone(disp.json()["trust_block_hash"])

        # StockLedgerEntryRecord MUST be cryptographically immutable against direct ORM tampering!
        entry = self.db.query(StockLedgerEntryRecord).filter_by(warehouse_id=wh_id).first()
        self.assertIsNotNone(entry)
        entry.quantity_delta = 9999
        with self.assertRaises(ValueError):
            self.db.commit()
        self.db.rollback()

    # ── 3. Bin Transfer, Blind Cycle Count + ECDSA Cert & 3PL Billing ─────

    def test_03_bin_transfer_cycle_count_certification_and_3pl_billing(self):
        env = self._seed_facility()
        wh_id = env["wh_id"]
        self.client.post(
            f"/v1/wms/warehouses/{wh_id}/skus",
            json={
                "sku_code": "SKU-3PL-BOX",
                "name": "Nutraceutical Carton",
                "client_id": env["client_id"],
                "required_zone_type": "AMBIENT",
                "velocity_tier": "A",
                "unit_cost_inr": 500.0,
            },
        )
        # Inbound 100 units into A01-R01-S01-B01
        self.client.post(
            f"/v1/wms/warehouses/{wh_id}/grn",
            json={
                "po_number": "PO-3PL-1",
                "supplier_name": "NutraVendor",
                "client_id": env["client_id"],
                "lines": [{"sku_code": "SKU-3PL-BOX", "expected_qty": 100, "received_qty": 100, "batch_no": "B100"}],
            },
        )
        # Transfer 40 units to A04-R02-S03-B02 (now 2 active bins occupied for client!)
        xfer = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/transfers",
            json={
                "sku_code": "SKU-3PL-BOX",
                "from_bin_id": env["b_amb_near"],
                "to_bin_id": env["b_amb_far"],
                "quantity": 40,
                "batch_no": "B100",
            },
        )
        self.assertEqual(xfer.status_code, 200, xfer.text)
        self.assertEqual(xfer.json()["source_balance_after"], 60)
        self.assertEqual(xfer.json()["destination_balance_after"], 40)

        # Dispatch 1 order of 10 units
        w = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/waves",
            json={"order_reference": "ORD-3PL-1", "client_id": env["client_id"], "lines": [{"sku_code": "SKU-3PL-BOX", "requested_qty": 10}]},
        ).json()
        self.client.post(f"/v1/wms/warehouses/{wh_id}/waves/{w['id']}/dispatch")

        # Picker submits blind cycle count on b_amb_near: physical=48 vs system=50 (variance=-2, -₹1000)
        self.active_principal = self.picker_a
        cc = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/cycle-counts",
            json={"bin_id": env["b_amb_near"], "sku_code": "SKU-3PL-BOX", "batch_no": "B100", "counted_qty": 48},
        )
        self.assertEqual(cc.status_code, 201, cc.text)
        self.assertEqual(cc.json()["variance_qty"], -2)
        self.assertEqual(cc.json()["variance_value_inr"], -1000.0)

        # Manager approves cycle count -> ECDSA stocktake certificate sealed!
        self.active_principal = self.mgr_a
        approved_cc = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/cycle-counts/{cc.json()['id']}/approve",
            json={"decision": "APPROVE", "notes": "Confirmed 2 damaged cartons during monthly stocktake"},
        )
        self.assertEqual(approved_cc.status_code, 200, approved_cc.text)
        self.assertEqual(approved_cc.json()["status"], "APPROVED_ADJUSTED")
        self.assertIsNotNone(approved_cc.json()["trust_block_hash"])

        # Automated 3PL monthly invoice: 2 active bins * 30d * ₹40 = ₹2,400 storage;
        # 100 inbound * ₹2.5 = ₹250; 10 outbound * ₹4 = ₹40; 1 order * ₹30 = ₹30 -> subtotal ₹2,720 + 18% GST ₹489.60 = ₹3,209.60!
        cur_month = datetime.now(UTC).strftime("%Y-%m")
        inv = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/3pl/invoices/generate",
            json={"client_id": env["client_id"], "billing_month": cur_month, "billing_days": 30, "gst_rate_pct": 18.0},
        )
        self.assertEqual(inv.status_code, 201, inv.text)
        d = inv.json()
        self.assertEqual(d["active_bins_billed"], 2)
        self.assertEqual(d["storage_charge_inr"], 2400.0)
        self.assertEqual(d["inbound_charge_inr"], 250.0)
        self.assertEqual(d["outbound_charge_inr"], 40.0)
        self.assertEqual(d["packing_charge_inr"], 30.0)
        self.assertEqual(d["subtotal_inr"], 2720.0)
        self.assertEqual(d["gst_inr"], 489.6)
        self.assertEqual(d["total_inr"], 3209.6)
        self.assertIsNotNone(d["trust_block_hash"])

        # Tally XML stock + cycle-count export
        tally = self.client.get(f"/v1/wms/warehouses/{wh_id}/exports/tally-stock-xml")
        self.assertEqual(tally.status_code, 200, tally.text)
        self.assertIn("<STOCKITEM", tally.text)
        self.assertIn("Stock Journal", tally.text)
        self.assertEqual(len(tally.headers.get("X-AFW-StockSense-Audit-SHA256", "")), 64)

        # Cross-tenant isolation: Org B blocked with 403!
        self.active_principal = self.mgr_b
        self.assertEqual(self.client.get(f"/v1/wms/warehouses/{wh_id}/stock").status_code, 403)
        self.assertEqual(self.client.get(f"/v1/wms/warehouses/{wh_id}/exports/tally-stock-xml").status_code, 403)

    # ── 4. Bulk CSV Import (Dry-Run + Commit) & Shopify Order Webhook ─────

    def test_04_bulk_csv_import_dry_run_commit_and_shopify_webhook(self):
        env = self._seed_facility()
        wh_id = env["wh_id"]

        bad_csv = (
            "sku_code,name,barcode,category,required_zone_type,velocity_tier,unit_cost_inr,bin_code,opening_qty\n"
            "SKU-BAD-1,Broken Row,111,Gen,AMBIENT,A,100,UNKNOWN-BIN,50\n"
        )
        dry = self.client.post(f"/v1/wms/warehouses/{wh_id}/import/csv", json={"csv_text": bad_csv, "dry_run": True})
        self.assertEqual(dry.status_code, 200)
        self.assertEqual(dry.json()["error_rows_count"], 1)

        good_csv = (
            "sku_code,name,barcode,category,required_zone_type,velocity_tier,unit_cost_inr,bin_code,opening_qty\n"
            "SKU-SHP-01,Organic Honey 500g,890999000111,FMCG,AMBIENT,A,320,A01-R01-S01-B01,75\n"
        )
        commit_res = self.client.post(f"/v1/wms/warehouses/{wh_id}/import/csv", json={"csv_text": good_csv, "dry_run": False})
        self.assertEqual(commit_res.status_code, 200, commit_res.text)
        self.assertEqual(commit_res.json()["skus_created"], 1)
        self.assertEqual(commit_res.json()["opening_units_posted"], 75)

        # Shopify channel order webhook -> auto-generates FEFO Pick Wave!
        hook = self.client.post(
            f"/v1/wms/warehouses/{wh_id}/channels/order-webhook",
            json={
                "channel_source": "SHOPIFY",
                "external_order_id": "SHP-99012",
                "items": [{"sku_code": "SKU-SHP-01", "requested_qty": 5}],
            },
        )
        self.assertEqual(hook.status_code, 201, hook.text)
        self.assertEqual(hook.json()["status"], "PICK_WAVE_GENERATED")
        self.assertEqual(hook.json()["pick_lines"][0]["bin_code"], "A01-R01-S01-B01")
        self.assertEqual(hook.json()["pick_lines"][0]["pick_qty"], 5)

    # ── 5. Holt Forecast MAE/MAPE, Postgres UAT, Mobile PWA WMS Tab & Migration Parity ──

    def test_05_holt_forecast_postgres_uat_mobile_wms_and_migration_parity(self):
        # 1. Holt double exponential smoothing on upward trend with real MAE/MAPE
        recs = compute_reorder_recommendations(
            items=[{
                "sku": "SKU-TREND-1",
                "name": "Trending Item",
                "category": "Industrial",
                "daily_demand": 15.0,
                "daily_demand_history": [10, 12, 14, 16, 18, 20],
                "lead_time_days": 5,
                "demand_std_dev": 2.0,
                "current_stock": 25,
                "order_cost": 200.0,
                "annual_demand": 5000,
                "holding_cost_annual": 40.0,
            }],
            forecast_alpha=0.4,
        )
        self.assertEqual(recs[0]["forecast_method"], "HOLT_DOUBLE_EXPONENTIAL_SMOOTHING")
        self.assertGreater(recs[0]["forecast_daily_demand"], 20.0)
        self.assertIsNotNone(recs[0]["forecast_mae"])
        self.assertIsNotNone(recs[0]["forecast_mape_pct"])

        # 2. UAT persists in PostgreSQL/SQLite InventoryUatRecord
        uat_resp = self.client.post(
            "/v1/inventory/uat",
            json={"operator_id": "floor-lead-01", "rating": 5, "notes": "FEFO wave picking verified on floor"},
        )
        self.assertEqual(uat_resp.status_code, 200, uat_resp.text)
        self.assertTrue(uat_resp.json()["entry"]["persisted_in_db"])
        self.assertGreaterEqual(self.db.query(InventoryUatRecord).count(), 1)

        # 3. Unified Mobile PWA serves StockSense Barcode Scanner tab
        html = self.client.get("/mobile/").text
        js = self.client.get("/mobile/mobile.js").text
        self.assertIn('id="tab-wms"', html)
        self.assertIn("BarcodeDetector", js)

        # 4. Alembic migration s9h4c5d6e7f8 upgrade/downgrade parity
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext
        import migrations.versions.s9h4c5d6e7f8_phase3_stocksense_wms_3pl as mig

        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with eng.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mig.upgrade()
            tables = set(sa_inspect(conn).get_table_names())
            self.assertTrue({
                "warehouses", "warehouse_zones", "warehouse_bins", "warehouse_clients",
                "warehouse_skus", "stock_balances", "stock_ledger_entries", "warehouse_grns",
                "warehouse_pick_waves", "warehouse_cycle_counts", "warehouse_3pl_invoices",
                "inventory_uat_records",
            }.issubset(tables))
            with Operations.context(ctx):
                mig.downgrade()
            self.assertEqual(len(sa_inspect(conn).get_table_names()), 0)


if __name__ == "__main__":
    unittest.main()
