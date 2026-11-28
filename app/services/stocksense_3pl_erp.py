"""Phase 3 StockSense 3PL Multi-Client Billing Engine, Bulk CSV Importer & ERP/Channel Bridge.

Implements:
1. Automated Monthly 3PL Client Storage (bin-days), Inbound Handling, Outbound Pick & Order Pack Billing + GST + ECDSA Seal.
2. Bulk CSV SKU & Opening Stock Importer with atomic Dry-Run validation before write.
3. E-Commerce / ERP Channel Order Webhook Bridge (Shopify / WooCommerce / Tally / Zoho -> FEFO Pick Wave).
4. Tally XML Stock Valuation & Cycle-Count Adjustment Export with SHA-256 audit digest.
"""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
import xml.sax.saxutils as xml_utils
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    StockBalanceRecord,
    StockLedgerEntryRecord,
    Warehouse3plInvoiceRecord,
    WarehouseBinRecord,
    WarehouseClientRecord,
    WarehouseCycleCountRecord,
    WarehousePickWaveRecord,
    WarehouseSkuRecord,
    WarehouseZoneRecord,
)
from app.schemas.wms import (
    ChannelOrderWebhookRequest,
    CsvImportRequest,
    PickWaveCreateRequest,
    ThreePlInvoiceGenerateRequest,
)
from app.security.trust_chain import seal_task_to_block
from app.services.stocksense_wms import (
    _get_or_create_balance,
    create_fefo_pick_wave,
    get_warehouse_scoped,
    get_warehouse_stock_summary,
    post_stock_ledger_entry,
)

_VALID_ZONES = {"AMBIENT", "COLD_CHAIN", "HAZMAT", "HIGH_VALUE"}
_VALID_TIERS = {"A", "B", "C"}


# ── 1. 3PL Multi-Client Automated Storage & Handling Billing ──────────


def generate_3pl_client_invoice(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    req: ThreePlInvoiceGenerateRequest,
    generated_by: str,
) -> Warehouse3plInvoiceRecord:
    """Auto-calculate monthly 3PL storage (active bins * days) + inbound GRN + outbound pick/pack + GST."""
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    client = db.get(WarehouseClientRecord, req.client_id)
    if not client or client.warehouse_id != wh.id:
        raise ValueError(f"3PL client {req.client_id} not found in warehouse {wh.code}")

    # 1. Active occupied bins for this 3PL client
    client_balances = (
        db.query(StockBalanceRecord)
        .filter(
            StockBalanceRecord.warehouse_id == wh.id,
            StockBalanceRecord.client_id == client.id,
            StockBalanceRecord.qty_on_hand > 0,
        )
        .all()
    )
    active_bins = len({b.bin_id for b in client_balances})

    # 2. Inbound & Outbound ledger units during billing_month (YYYY-MM)
    ledger_rows = (
        db.query(StockLedgerEntryRecord)
        .filter(
            StockLedgerEntryRecord.warehouse_id == wh.id,
            StockLedgerEntryRecord.client_id == client.id,
        )
        .all()
    )
    inbound_units = 0
    outbound_units = 0
    for row in ledger_rows:
        row_month = row.created_at.strftime("%Y-%m") if row.created_at else req.billing_month
        if row_month != req.billing_month:
            continue
        if row.movement_type == "GRN_RECEIPT" and row.quantity_delta > 0:
            inbound_units += int(row.quantity_delta)
        elif row.movement_type in ("DISPATCH", "PICK") and row.quantity_delta < 0:
            outbound_units += abs(int(row.quantity_delta))

    # 3. Dispatched orders/waves packed during billing_month
    waves = (
        db.query(WarehousePickWaveRecord)
        .filter(
            WarehousePickWaveRecord.warehouse_id == wh.id,
            WarehousePickWaveRecord.client_id == client.id,
            WarehousePickWaveRecord.status == "DISPATCHED",
        )
        .all()
    )
    orders_packed = sum(
        1
        for w in waves
        if (w.dispatched_at or w.created_at).strftime("%Y-%m") == req.billing_month
    )

    storage_charge = round(active_bins * req.billing_days * float(client.storage_rate_per_bin_day_inr), 2)
    inbound_charge = round(inbound_units * float(client.inbound_handling_rate_per_unit_inr), 2)
    outbound_charge = round(outbound_units * float(client.outbound_pick_rate_per_unit_inr), 2)
    packing_charge = round(orders_packed * float(client.packing_rate_per_order_inr), 2)

    subtotal = round(storage_charge + inbound_charge + outbound_charge + packing_charge, 2)
    gst_inr = round(subtotal * (float(req.gst_rate_pct) / 100.0), 2)
    total_inr = round(subtotal + gst_inr, 2)

    inv_num = f"3PL-{wh.code}-{client.client_code}-{req.billing_month.replace('-', '')}-{uuid.uuid4().hex[:4].upper()}"
    line_items = [
        {
            "description": f"Bin Storage Occupancy ({active_bins} active bins x {req.billing_days} days @ ₹{client.storage_rate_per_bin_day_inr}/bin-day)",
            "quantity": active_bins * req.billing_days,
            "rate_inr": client.storage_rate_per_bin_day_inr,
            "amount_inr": storage_charge,
        },
        {
            "description": f"Inbound GRN Receiving & Putaway ({inbound_units} units @ ₹{client.inbound_handling_rate_per_unit_inr}/unit)",
            "quantity": inbound_units,
            "rate_inr": client.inbound_handling_rate_per_unit_inr,
            "amount_inr": inbound_charge,
        },
        {
            "description": f"Outbound FEFO Picking & Dispatch ({outbound_units} units @ ₹{client.outbound_pick_rate_per_unit_inr}/unit)",
            "quantity": outbound_units,
            "rate_inr": client.outbound_pick_rate_per_unit_inr,
            "amount_inr": outbound_charge,
        },
        {
            "description": f"Order Packing & Label Fulfillment ({orders_packed} orders @ ₹{client.packing_rate_per_order_inr}/order)",
            "quantity": orders_packed,
            "rate_inr": client.packing_rate_per_order_inr,
            "amount_inr": packing_charge,
        },
    ]

    audit_payload = f"{inv_num}|{wh.id}|{client.id}|{req.billing_month}|{subtotal:.2f}|{gst_inr:.2f}|{total_inr:.2f}"
    audit_sha256 = hashlib.sha256(audit_payload.encode("utf-8")).hexdigest()

    inv_id = str(uuid.uuid4())
    trust_hash = None
    try:
        block = seal_task_to_block(
            db=db,
            task_id=inv_id,
            capability_name="stocksense_3pl_billing",
            action="3pl_monthly_invoice_generated",
            payload={
                "invoice_number": inv_num,
                "client_code": client.client_code,
                "billing_month": req.billing_month,
                "subtotal_inr": subtotal,
                "gst_inr": gst_inr,
                "total_inr": total_inr,
                "audit_sha256": audit_sha256,
                "generated_by": generated_by,
            },
            sealed_by="AFW-STOCKSENSE-3PL-BILLING",
            commit=False,
        )
        trust_hash = block.block_hash
    except Exception:
        pass

    invoice = Warehouse3plInvoiceRecord(
        id=inv_id,
        org_id=wh.org_id,
        warehouse_id=wh.id,
        client_id=client.id,
        invoice_number=inv_num,
        billing_month=req.billing_month,
        active_bins_billed=active_bins,
        billing_days=req.billing_days,
        inbound_units_billed=inbound_units,
        outbound_units_billed=outbound_units,
        orders_packed_billed=orders_packed,
        storage_charge_inr=storage_charge,
        inbound_charge_inr=inbound_charge,
        outbound_charge_inr=outbound_charge,
        packing_charge_inr=packing_charge,
        subtotal_inr=subtotal,
        gst_inr=gst_inr,
        total_inr=total_inr,
        line_items_json=line_items,
        audit_sha256=audit_sha256,
        trust_block_hash=trust_hash,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


# ── 2. Bulk CSV SKU & Opening Stock Importer (Dry-Run + Atomic Commit) ─


def import_skus_and_opening_stock_csv(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    req: CsvImportRequest,
    operator_id: str,
) -> dict[str, Any]:
    """Validate (dry_run=True) or atomically import SKUs + opening balances from SME Excel/CSV sheets."""
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    reader = csv.DictReader(io.StringIO(req.csv_text.strip()))
    if not reader.fieldnames:
        raise ValueError("CSV must contain a header row")

    bins_by_code = {
        b.bin_code.upper(): b
        for b in db.query(WarehouseBinRecord).filter(WarehouseBinRecord.warehouse_id == wh.id).all()
    }
    zones_by_id = {
        z.id: z
        for z in db.query(WarehouseZoneRecord).filter(WarehouseZoneRecord.warehouse_id == wh.id).all()
    }

    valid_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for row_num, raw in enumerate(reader, start=2):
        sku_code = (raw.get("sku_code") or "").strip().upper()
        name = (raw.get("name") or "").strip()
        row_errs: list[str] = []

        if not sku_code or not name:
            row_errs.append("Missing required sku_code or name")

        zone_type = (raw.get("required_zone_type") or "AMBIENT").strip().upper()
        if zone_type not in _VALID_ZONES:
            row_errs.append(f"Invalid required_zone_type '{zone_type}'")

        velocity = (raw.get("velocity_tier") or "B").strip().upper()
        if velocity not in _VALID_TIERS:
            row_errs.append(f"Invalid velocity_tier '{velocity}'")

        try:
            unit_cost = float(raw.get("unit_cost_inr") or 100.0)
            if unit_cost <= 0:
                row_errs.append("unit_cost_inr must be > 0")
        except ValueError:
            unit_cost = 0.0
            row_errs.append("Invalid numeric unit_cost_inr")

        try:
            opening_qty = int(raw.get("opening_qty") or 0)
            if opening_qty < 0:
                row_errs.append("opening_qty cannot be negative")
        except ValueError:
            opening_qty = 0
            row_errs.append("Invalid integer opening_qty")

        bin_code = (raw.get("bin_code") or "").strip().upper()
        target_bin = bins_by_code.get(bin_code) if bin_code else None
        if opening_qty > 0:
            if not target_bin:
                row_errs.append(f"Unknown bin_code '{bin_code}' for opening_qty={opening_qty}")
            else:
                z = zones_by_id.get(target_bin.zone_id)
                if z and z.zone_type != zone_type:
                    row_errs.append(f"Bin '{bin_code}' is in zone '{z.zone_type}', incompatible with SKU zone '{zone_type}'")

        requires_exp = str(raw.get("requires_expiry_tracking") or "").strip().lower() in ("true", "1", "yes")
        exp_date = (raw.get("expiry_date") or "").strip()
        if requires_exp and opening_qty > 0 and not exp_date:
            row_errs.append("expiry_date required for expiry-tracked SKU with opening_qty > 0")

        if row_errs:
            errors.append({"row": row_num, "sku_code": sku_code, "errors": row_errs})
        else:
            valid_rows.append({
                "sku_code": sku_code,
                "name": name,
                "barcode": (raw.get("barcode") or sku_code).strip(),
                "category": (raw.get("category") or "General").strip(),
                "required_zone_type": zone_type,
                "velocity_tier": velocity,
                "unit_cost_inr": unit_cost,
                "requires_expiry_tracking": requires_exp,
                "bin_id": target_bin.id if target_bin else None,
                "bin_code": bin_code or None,
                "opening_qty": opening_qty,
                "batch_no": (raw.get("batch_no") or "OPENING").strip().upper(),
                "expiry_date": exp_date,
            })

    if req.dry_run:
        return {
            "mode": "DRY_RUN",
            "warehouse_code": wh.code,
            "total_rows": len(valid_rows) + len(errors),
            "valid_rows_count": len(valid_rows),
            "error_rows_count": len(errors),
            "errors": errors,
            "preview": valid_rows[:20],
        }

    if errors:
        raise ValueError(f"CSV import aborted: {len(errors)} validation error(s). Run dry_run=true to inspect.")

    imported_skus = 0
    opening_units_posted = 0
    batch_ref = f"CSV-{uuid.uuid4().hex[:8].upper()}"

    for r in valid_rows:
        sku = (
            db.query(WarehouseSkuRecord)
            .filter(WarehouseSkuRecord.warehouse_id == wh.id, WarehouseSkuRecord.sku_code == r["sku_code"])
            .first()
        )
        if sku is None:
            sku = WarehouseSkuRecord(
                id=str(uuid.uuid4()),
                org_id=wh.org_id,
                warehouse_id=wh.id,
                client_id=req.client_id,
                sku_code=r["sku_code"],
                name=r["name"],
                barcode=r["barcode"],
                category=r["category"],
                required_zone_type=r["required_zone_type"],
                velocity_tier=r["velocity_tier"],
                unit_cost_inr=r["unit_cost_inr"],
                requires_expiry_tracking=r["requires_expiry_tracking"],
            )
            db.add(sku)
            db.flush()
            imported_skus += 1

        if r["opening_qty"] > 0 and r["bin_id"]:
            bal = _get_or_create_balance(
                db,
                org_id=wh.org_id,
                warehouse_id=wh.id,
                bin_id=r["bin_id"],
                sku=sku,
                batch_no=r["batch_no"],
                expiry_date=r["expiry_date"],
            )
            bal.qty_on_hand += r["opening_qty"]
            opening_units_posted += r["opening_qty"]
            post_stock_ledger_entry(
                db,
                org_id=wh.org_id,
                warehouse_id=wh.id,
                client_id=sku.client_id or req.client_id,
                sku_id=sku.id,
                from_bin_id=None,
                to_bin_id=r["bin_id"],
                movement_type="OPENING_BALANCE",
                batch_no=r["batch_no"],
                expiry_date=r["expiry_date"],
                quantity_delta=r["opening_qty"],
                balance_after=bal.qty_on_hand,
                reference_type="CSV_IMPORT",
                reference_id=batch_ref,
                operator_id=operator_id,
                notes=f"Bulk CSV opening balance import ({batch_ref})",
            )

    db.commit()
    return {
        "mode": "COMMITTED",
        "batch_ref": batch_ref,
        "warehouse_code": wh.code,
        "skus_created": imported_skus,
        "rows_processed": len(valid_rows),
        "opening_units_posted": opening_units_posted,
    }


# ── 3. E-Commerce & ERP Channel Order Webhook -> FEFO Pick Wave ───────


def ingest_channel_order_webhook(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    req: ChannelOrderWebhookRequest,
    operator_id: str,
) -> dict[str, Any]:
    """Convert Shopify / WooCommerce / Zoho / Tally order payload directly into a FEFO-enforced Pick Wave."""
    wave = create_fefo_pick_wave(
        db,
        org_id=org_id,
        warehouse_id=warehouse_id,
        req=PickWaveCreateRequest(
            order_reference=f"{req.channel_source}-{req.external_order_id}",
            channel_source=req.channel_source,
            client_id=req.client_id,
            lines=req.items,
        ),
        operator_id=operator_id,
    )
    return {
        "status": "PICK_WAVE_GENERATED",
        "wave_id": wave.id,
        "order_reference": wave.order_reference,
        "channel_source": wave.channel_source,
        "wave_status": wave.status,
        "pick_lines": wave.pick_lines_json,
        "blocked_expired_lots": wave.blocked_expired_lots_json,
        "shortfalls": wave.shortfalls_json,
    }


# ── 4. Tally XML Stock Valuation & Cycle-Count Export ─────────────────


def export_tally_stock_xml(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
) -> dict[str, Any]:
    """Export current stock balances and approved cycle-count adjustments in Tally XML format with SHA-256 digest."""
    summary = get_warehouse_stock_summary(db, org_id=org_id, warehouse_id=warehouse_id)
    approved_counts = (
        db.query(WarehouseCycleCountRecord)
        .filter(
            WarehouseCycleCountRecord.warehouse_id == warehouse_id,
            WarehouseCycleCountRecord.status == "APPROVED_ADJUSTED",
        )
        .order_by(WarehouseCycleCountRecord.approved_at.desc())
        .limit(100)
        .all()
    )

    today_tally = datetime.now(UTC).strftime("%Y%m%d")
    canonical = f"{summary['warehouse_code']}|{summary['total_units_on_hand']}|{summary['total_valuation_inr']:.2f}|{len(approved_counts)}"
    audit_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    item_nodes: list[str] = []
    for row in summary["balances"]:
        sku_esc = xml_utils.escape(f"{row['sku_code']} - {row['sku_name']}")
        godown_esc = xml_utils.escape(f"{summary['warehouse_code']} / {row['bin_code']}")
        item_nodes.append(
            f"""    <TALLYMESSAGE xmlns:UDF="TallyUDF">
      <STOCKITEM NAME="{sku_esc}" ACTION="Alter">
        <NAME>{sku_esc}</NAME>
        <OPENINGBALANCE>{row['qty_on_hand']} Nos</OPENINGBALANCE>
        <OPENINGVALUE>-{row['valuation_inr']:.2f}</OPENINGVALUE>
        <BATCHALLOCATIONS.LIST>
          <GODOWNNAME>{godown_esc}</GODOWNNAME>
          <BATCHNAME>{xml_utils.escape(row['batch_no'])}</BATCHNAME>
          <OPENINGBALANCE>{row['qty_on_hand']} Nos</OPENINGBALANCE>
        </BATCHALLOCATIONS.LIST>
      </STOCKITEM>
    </TALLYMESSAGE>"""
        )

    for cc in approved_counts:
        sku_obj = db.get(WarehouseSkuRecord, cc.sku_id)
        sku_label = xml_utils.escape(sku_obj.sku_code if sku_obj else cc.sku_id)
        narr = xml_utils.escape(
            f"StockSense Certified Cycle Count {cc.id[:8]} ({sku_label}, var={cc.variance_qty}) | ECDSA:{(cc.trust_block_hash or '')[:16]}"
        )
        item_nodes.append(
            f"""    <TALLYMESSAGE xmlns:UDF="TallyUDF">
      <VOUCHER VCHTYPE="Stock Journal" ACTION="Create">
        <DATE>{today_tally}</DATE>
        <VOUCHERTYPENAME>Stock Journal</VOUCHERTYPENAME>
        <NARRATION>{narr}</NARRATION>
      </VOUCHER>
    </TALLYMESSAGE>"""
        )

    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<ENVELOPE>\n"
        "  <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>\n"
        "  <BODY>\n"
        "    <IMPORTDATA>\n"
        "      <REQUESTDESC><REPORTNAME>All Masters</REPORTNAME></REQUESTDESC>\n"
        "      <REQUESTDATA>\n"
        + "\n".join(item_nodes)
        + "\n      </REQUESTDATA>\n"
        "    </IMPORTDATA>\n"
        "  </BODY>\n"
        f"  <!-- AFW-STOCKSENSE-AUDIT-SHA256: {audit_sha256} -->\n"
        "</ENVELOPE>\n"
    )
    return {
        "content": xml_content,
        "media_type": "application/xml",
        "filename": f"stocksense_tally_{summary['warehouse_code'].lower()}_{today_tally}.xml",
        "audit_sha256": audit_sha256,
        "total_units": summary["total_units_on_hand"],
        "total_valuation_inr": summary["total_valuation_inr"],
    }
