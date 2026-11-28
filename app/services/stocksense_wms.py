"""Phase 3 StockSense Persistent Multi-Tenant SME Warehouse Management & Double-Entry Stock Ledger Service.

Implements real physical warehouse floor operations:
1. Multi-tenant Warehouse -> Zone (Ambient/Cold-Chain/Hazmat/High-Value/Quarantine) -> Bin hierarchy.
2. Persistent double-entry StockBalance + immutable StockLedgerEntry audit trail.
3. Inbound GRN receiving with shortage/damage capture, directed velocity+zone slotting & QR bin labels.
4. Directed outbound Wave/Order Picking enforcing strict FEFO/FIFO + hard block on expired lots.
5. Atomic bin-to-bin transfers with zone safety validation.
6. Blind mobile Cycle Counting with variance valuation & ECDSA NIST P-256 stocktake certification.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    StockBalanceRecord,
    StockLedgerEntryRecord,
    WarehouseBinRecord,
    WarehouseClientRecord,
    WarehouseCycleCountRecord,
    WarehouseGrnRecord,
    WarehousePickWaveRecord,
    WarehouseRecord,
    WarehouseSkuRecord,
    WarehouseZoneRecord,
)
from app.schemas.wms import (
    BinTransferRequest,
    CycleCountApproveRequest,
    CycleCountSubmitRequest,
    GrnReceiveRequest,
    PickWaveCreateRequest,
    WarehouseBinCreate,
    WarehouseClientCreate,
    WarehouseCreate,
    WarehouseSkuCreate,
    WarehouseZoneCreate,
)
from app.security.trust_chain import seal_task_to_block
from app.services.field_evidence_storage import decode_base64_image, persist_evidence_bytes


def get_warehouse_scoped(db: Session, org_id: str | None, warehouse_id: str) -> WarehouseRecord:
    wh = db.get(WarehouseRecord, warehouse_id)
    if not wh:
        raise ValueError(f"Warehouse {warehouse_id} not found")
    if org_id is not None and wh.org_id != org_id:
        raise PermissionError("Warehouse belongs to another organization")
    return wh


# ── Facility, Zone, Bin, 3PL Client & SKU Master CRUD ─────────────────


def create_warehouse(db: Session, *, org_id: str | None, req: WarehouseCreate) -> WarehouseRecord:
    code = req.code.strip().upper()
    dup = (
        db.query(WarehouseRecord)
        .filter(WarehouseRecord.org_id == org_id, WarehouseRecord.code == code)
        .first()
    )
    if dup:
        raise ValueError(f"Warehouse code '{code}' already exists in this organization")
    wh = WarehouseRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        code=code,
        name=req.name.strip(),
        city=req.city.strip(),
        address=req.address,
        total_area_sqft=req.total_area_sqft,
        is_3pl_enabled=req.is_3pl_enabled,
    )
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


def list_warehouses(db: Session, *, org_id: str | None) -> list[WarehouseRecord]:
    q = db.query(WarehouseRecord).filter(WarehouseRecord.is_active.is_(True))
    if org_id is not None:
        q = q.filter(WarehouseRecord.org_id == org_id)
    return q.order_by(WarehouseRecord.created_at.desc()).all()


def create_zone(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    req: WarehouseZoneCreate,
) -> WarehouseZoneRecord:
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    code = req.code.strip().upper()
    dup = (
        db.query(WarehouseZoneRecord)
        .filter(WarehouseZoneRecord.warehouse_id == wh.id, WarehouseZoneRecord.code == code)
        .first()
    )
    if dup:
        raise ValueError(f"Zone code '{code}' already exists in warehouse {wh.code}")
    zone = WarehouseZoneRecord(
        id=str(uuid.uuid4()),
        org_id=wh.org_id,
        warehouse_id=wh.id,
        code=code,
        name=req.name.strip(),
        zone_type=req.zone_type.upper(),
        temperature_min_c=req.temperature_min_c,
        temperature_max_c=req.temperature_max_c,
    )
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return zone


def list_zones(db: Session, *, org_id: str | None, warehouse_id: str) -> list[WarehouseZoneRecord]:
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    return (
        db.query(WarehouseZoneRecord)
        .filter(WarehouseZoneRecord.warehouse_id == wh.id, WarehouseZoneRecord.is_active.is_(True))
        .order_by(WarehouseZoneRecord.code.asc())
        .all()
    )


def create_bin(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    req: WarehouseBinCreate,
) -> WarehouseBinRecord:
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    zone = db.get(WarehouseZoneRecord, req.zone_id)
    if not zone or zone.warehouse_id != wh.id:
        raise ValueError(f"Zone {req.zone_id} not found in warehouse {wh.code}")
    bin_code = req.bin_code.strip().upper()
    dup = (
        db.query(WarehouseBinRecord)
        .filter(WarehouseBinRecord.warehouse_id == wh.id, WarehouseBinRecord.bin_code == bin_code)
        .first()
    )
    if dup:
        raise ValueError(f"Bin '{bin_code}' already exists in warehouse {wh.code}")
    b = WarehouseBinRecord(
        id=str(uuid.uuid4()),
        org_id=wh.org_id,
        warehouse_id=wh.id,
        zone_id=zone.id,
        bin_code=bin_code,
        aisle=req.aisle.strip().upper(),
        rack=req.rack.strip().upper(),
        shelf=req.shelf.strip().upper(),
        velocity_tier=req.velocity_tier.upper(),
        distance_to_dispatch_m=req.distance_to_dispatch_m,
        max_weight_kg=req.max_weight_kg,
        max_volume_cbm=req.max_volume_cbm,
        max_pallet_slots=req.max_pallet_slots,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def list_bins(db: Session, *, org_id: str | None, warehouse_id: str) -> list[WarehouseBinRecord]:
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    return (
        db.query(WarehouseBinRecord)
        .filter(WarehouseBinRecord.warehouse_id == wh.id, WarehouseBinRecord.is_active.is_(True))
        .order_by(WarehouseBinRecord.aisle.asc(), WarehouseBinRecord.rack.asc(), WarehouseBinRecord.shelf.asc())
        .all()
    )


def create_3pl_client(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    req: WarehouseClientCreate,
) -> WarehouseClientRecord:
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    code = req.client_code.strip().upper()
    dup = (
        db.query(WarehouseClientRecord)
        .filter(WarehouseClientRecord.warehouse_id == wh.id, WarehouseClientRecord.client_code == code)
        .first()
    )
    if dup:
        raise ValueError(f"3PL client code '{code}' already exists in warehouse {wh.code}")
    client = WarehouseClientRecord(
        id=str(uuid.uuid4()),
        org_id=wh.org_id,
        warehouse_id=wh.id,
        client_code=code,
        client_name=req.client_name.strip(),
        contact_email=req.contact_email,
        gstin=req.gstin.strip().upper() if req.gstin else None,
        storage_rate_per_bin_day_inr=req.storage_rate_per_bin_day_inr,
        inbound_handling_rate_per_unit_inr=req.inbound_handling_rate_per_unit_inr,
        outbound_pick_rate_per_unit_inr=req.outbound_pick_rate_per_unit_inr,
        packing_rate_per_order_inr=req.packing_rate_per_order_inr,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def list_3pl_clients(db: Session, *, org_id: str | None, warehouse_id: str) -> list[WarehouseClientRecord]:
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    return (
        db.query(WarehouseClientRecord)
        .filter(WarehouseClientRecord.warehouse_id == wh.id, WarehouseClientRecord.is_active.is_(True))
        .order_by(WarehouseClientRecord.client_name.asc())
        .all()
    )


def create_sku(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    req: WarehouseSkuCreate,
) -> WarehouseSkuRecord:
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    if req.client_id:
        client = db.get(WarehouseClientRecord, req.client_id)
        if not client or client.warehouse_id != wh.id:
            raise ValueError(f"3PL client {req.client_id} not found in warehouse {wh.code}")
    sku_code = req.sku_code.strip().upper()
    dup = (
        db.query(WarehouseSkuRecord)
        .filter(WarehouseSkuRecord.warehouse_id == wh.id, WarehouseSkuRecord.sku_code == sku_code)
        .first()
    )
    if dup:
        raise ValueError(f"SKU '{sku_code}' already exists in warehouse {wh.code}")
    sku = WarehouseSkuRecord(
        id=str(uuid.uuid4()),
        org_id=wh.org_id,
        warehouse_id=wh.id,
        client_id=req.client_id,
        sku_code=sku_code,
        name=req.name.strip(),
        barcode=req.barcode.strip() if req.barcode else sku_code,
        category=req.category.strip(),
        required_zone_type=req.required_zone_type.upper(),
        velocity_tier=req.velocity_tier.upper(),
        unit_cost_inr=req.unit_cost_inr,
        unit_weight_kg=req.unit_weight_kg,
        requires_expiry_tracking=req.requires_expiry_tracking,
        lead_time_days=req.lead_time_days,
        reorder_point=req.reorder_point,
        eoq_qty=req.eoq_qty,
    )
    db.add(sku)
    db.commit()
    db.refresh(sku)
    return sku


def list_skus(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    barcode: str | None = None,
    client_id: str | None = None,
) -> list[WarehouseSkuRecord]:
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    q = db.query(WarehouseSkuRecord).filter(
        WarehouseSkuRecord.warehouse_id == wh.id,
        WarehouseSkuRecord.is_active.is_(True),
    )
    if barcode:
        q = q.filter((WarehouseSkuRecord.barcode == barcode.strip()) | (WarehouseSkuRecord.sku_code == barcode.strip().upper()))
    if client_id:
        q = q.filter(WarehouseSkuRecord.client_id == client_id)
    return q.order_by(WarehouseSkuRecord.sku_code.asc()).all()


# ── Internal Double-Entry Stock Balance & Ledger Helper ───────────────


def _get_or_create_balance(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    bin_id: str,
    sku: WarehouseSkuRecord,
    batch_no: str,
    expiry_date: str,
) -> StockBalanceRecord:
    bal = (
        db.query(StockBalanceRecord)
        .filter(
            StockBalanceRecord.warehouse_id == warehouse_id,
            StockBalanceRecord.bin_id == bin_id,
            StockBalanceRecord.sku_id == sku.id,
            StockBalanceRecord.batch_no == batch_no,
            StockBalanceRecord.expiry_date == expiry_date,
        )
        .first()
    )
    if bal is None:
        bal = StockBalanceRecord(
            id=str(uuid.uuid4()),
            org_id=org_id,
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            sku_id=sku.id,
            client_id=sku.client_id,
            batch_no=batch_no,
            expiry_date=expiry_date,
            qty_on_hand=0,
            qty_reserved=0,
            qty_damaged=0,
        )
        db.add(bal)
        db.flush()
    return bal


def post_stock_ledger_entry(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    client_id: str | None,
    sku_id: str,
    from_bin_id: str | None,
    to_bin_id: str | None,
    movement_type: str,
    batch_no: str,
    expiry_date: str,
    quantity_delta: int,
    balance_after: int,
    reference_type: str,
    reference_id: str | None,
    operator_id: str,
    notes: str | None = None,
    trust_block_hash: str | None = None,
) -> StockLedgerEntryRecord:
    entry = StockLedgerEntryRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        warehouse_id=warehouse_id,
        client_id=client_id,
        sku_id=sku_id,
        from_bin_id=from_bin_id,
        to_bin_id=to_bin_id,
        movement_type=movement_type,
        batch_no=batch_no,
        expiry_date=expiry_date,
        quantity_delta=quantity_delta,
        balance_after=balance_after,
        reference_type=reference_type,
        reference_id=reference_id,
        operator_id=operator_id,
        notes=notes,
        trust_block_hash=trust_block_hash,
    )
    db.add(entry)
    return entry


# ── Directed Slotting & Inbound GRN Putaway ───────────────────────────


def suggest_directed_putaway_bin(
    db: Session,
    *,
    warehouse_id: str,
    sku: WarehouseSkuRecord,
    quantity: int,
) -> WarehouseBinRecord:
    """Select optimal bin honoring strict zone safety (Cold-Chain/Hazmat/etc.) + ABC velocity proximity to dispatch."""
    matching_zones = (
        db.query(WarehouseZoneRecord)
        .filter(
            WarehouseZoneRecord.warehouse_id == warehouse_id,
            WarehouseZoneRecord.zone_type == sku.required_zone_type,
            WarehouseZoneRecord.is_active.is_(True),
        )
        .all()
    )
    zone_ids = [z.id for z in matching_zones]
    if not zone_ids:
        raise ValueError(
            f"No active '{sku.required_zone_type}' zone configured in warehouse for SKU {sku.sku_code}"
        )

    bins = (
        db.query(WarehouseBinRecord)
        .filter(
            WarehouseBinRecord.warehouse_id == warehouse_id,
            WarehouseBinRecord.zone_id.in_(zone_ids),
            WarehouseBinRecord.is_active.is_(True),
        )
        .all()
    )
    if not bins:
        raise ValueError(
            f"No active bins available inside '{sku.required_zone_type}' zone for SKU {sku.sku_code}"
        )

    added_weight = float(quantity) * float(sku.unit_weight_kg or 0.0)
    candidates: list[tuple[int, float, WarehouseBinRecord]] = []
    for b in bins:
        # Compute current weight stored in bin
        cur_rows = db.query(StockBalanceRecord).filter(StockBalanceRecord.bin_id == b.id, StockBalanceRecord.qty_on_hand > 0).all()
        cur_weight = 0.0
        for r in cur_rows:
            r_sku = db.get(WarehouseSkuRecord, r.sku_id)
            if r_sku:
                cur_weight += float(r.qty_on_hand) * float(r_sku.unit_weight_kg or 0.0)
        if cur_weight + added_weight > float(b.max_weight_kg):
            continue
        tier_penalty = 0 if b.velocity_tier == sku.velocity_tier else 1
        # Fast-moving A items prefer closest bin to dispatch; C items prefer farther bins to preserve front bays
        dist_score = float(b.distance_to_dispatch_m) if sku.velocity_tier in ("A", "B") else -float(b.distance_to_dispatch_m)
        candidates.append((tier_penalty, dist_score, b))

    if not candidates:
        raise ValueError(
            f"All '{sku.required_zone_type}' bins exceed max_weight_kg capacity for {quantity} units of {sku.sku_code}"
        )

    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def receive_grn_and_putaway(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    req: GrnReceiveRequest,
    operator_id: str,
) -> WarehouseGrnRecord:
    """Receive inbound PO/ASN, capture shortages/damage proof, direct-slot putaway, and emit QR bin labels."""
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    grn_id = str(uuid.uuid4())
    processed_lines: list[dict[str, Any]] = []
    discrepancies: list[dict[str, Any]] = []
    qr_labels: list[dict[str, Any]] = []

    quarantine_zone = (
        db.query(WarehouseZoneRecord)
        .filter(
            WarehouseZoneRecord.warehouse_id == wh.id,
            WarehouseZoneRecord.zone_type == "QUARANTINE",
            WarehouseZoneRecord.is_active.is_(True),
        )
        .first()
    )
    quarantine_bin = (
        db.query(WarehouseBinRecord)
        .filter(WarehouseBinRecord.zone_id == quarantine_zone.id, WarehouseBinRecord.is_active.is_(True))
        .first()
        if quarantine_zone
        else None
    )

    for line in req.lines:
        sku_code = line.sku_code.strip().upper()
        sku = (
            db.query(WarehouseSkuRecord)
            .filter(WarehouseSkuRecord.warehouse_id == wh.id, WarehouseSkuRecord.sku_code == sku_code)
            .first()
        )
        if not sku:
            raise ValueError(f"SKU '{sku_code}' not registered in warehouse {wh.code}")

        exp_str = (line.expiry_date or "").strip()
        if sku.requires_expiry_tracking and not exp_str:
            raise ValueError(f"SKU '{sku_code}' requires expiry_date (YYYY-MM-DD) for FEFO compliance")

        batch_no = (line.batch_no or "DEFAULT").strip().upper()
        photo_uri: str | None = None
        if line.discrepancy_photo_base64:
            img_bytes, mime = decode_base64_image(line.discrepancy_photo_base64)
            if img_bytes and mime:
                stored = persist_evidence_bytes(
                    org_id=wh.org_id,
                    category="wms_grn_discrepancies",
                    image_bytes=img_bytes,
                    mime_type=mime,
                )
                photo_uri = stored["storage_uri"]

        # Select or validate target bin for good received stock
        if line.target_bin_id:
            target_bin = db.get(WarehouseBinRecord, line.target_bin_id)
            if not target_bin or target_bin.warehouse_id != wh.id:
                raise ValueError(f"Target bin {line.target_bin_id} not found in warehouse {wh.code}")
            target_zone = db.get(WarehouseZoneRecord, target_bin.zone_id)
            if target_zone and target_zone.zone_type != sku.required_zone_type:
                raise ValueError(
                    f"Zone safety violation: SKU '{sku_code}' requires '{sku.required_zone_type}' zone, "
                    f"cannot putaway into '{target_zone.zone_type}' bin '{target_bin.bin_code}'"
                )
        else:
            target_bin = suggest_directed_putaway_bin(
                db,
                warehouse_id=wh.id,
                sku=sku,
                quantity=max(1, line.received_qty),
            )

        if line.received_qty > 0:
            bal = _get_or_create_balance(
                db,
                org_id=wh.org_id,
                warehouse_id=wh.id,
                bin_id=target_bin.id,
                sku=sku,
                batch_no=batch_no,
                expiry_date=exp_str,
            )
            bal.qty_on_hand += line.received_qty
            post_stock_ledger_entry(
                db,
                org_id=wh.org_id,
                warehouse_id=wh.id,
                client_id=sku.client_id or req.client_id,
                sku_id=sku.id,
                from_bin_id=None,
                to_bin_id=target_bin.id,
                movement_type="GRN_RECEIPT",
                batch_no=batch_no,
                expiry_date=exp_str,
                quantity_delta=line.received_qty,
                balance_after=bal.qty_on_hand,
                reference_type="PO",
                reference_id=req.po_number,
                operator_id=operator_id,
                notes=f"GRN {grn_id[:8]} from {req.supplier_name}",
            )

        if line.damaged_qty > 0:
            q_bin = quarantine_bin or target_bin
            q_bal = _get_or_create_balance(
                db,
                org_id=wh.org_id,
                warehouse_id=wh.id,
                bin_id=q_bin.id,
                sku=sku,
                batch_no=batch_no,
                expiry_date=exp_str,
            )
            q_bal.qty_damaged += line.damaged_qty
            post_stock_ledger_entry(
                db,
                org_id=wh.org_id,
                warehouse_id=wh.id,
                client_id=sku.client_id or req.client_id,
                sku_id=sku.id,
                from_bin_id=None,
                to_bin_id=q_bin.id,
                movement_type="DAMAGE_QUARANTINE",
                batch_no=batch_no,
                expiry_date=exp_str,
                quantity_delta=line.damaged_qty,
                balance_after=q_bal.qty_damaged,
                reference_type="PO",
                reference_id=req.po_number,
                operator_id=operator_id,
                notes=f"Damaged inbound qty quarantined (photo={photo_uri or 'none'})",
            )

        short_qty = max(0, line.expected_qty - line.received_qty - line.damaged_qty)
        if short_qty > 0 or line.damaged_qty > 0:
            discrepancies.append({
                "sku_code": sku_code,
                "expected_qty": line.expected_qty,
                "received_qty": line.received_qty,
                "damaged_qty": line.damaged_qty,
                "short_qty": short_qty,
                "photo_uri": photo_uri,
            })

        qr_payload = f"AFW-WMS|WH:{wh.code}|BIN:{target_bin.bin_code}|SKU:{sku_code}|BATCH:{batch_no}|EXP:{exp_str or 'NONE'}|QTY:{line.received_qty}"
        qr_labels.append({
            "sku_code": sku_code,
            "bin_code": target_bin.bin_code,
            "batch_no": batch_no,
            "expiry_date": exp_str or None,
            "qty": line.received_qty,
            "qr_code_payload": qr_payload,
        })
        processed_lines.append({
            "sku_id": sku.id,
            "sku_code": sku_code,
            "assigned_bin_id": target_bin.id,
            "assigned_bin_code": target_bin.bin_code,
            "expected_qty": line.expected_qty,
            "received_qty": line.received_qty,
            "damaged_qty": line.damaged_qty,
            "short_qty": short_qty,
            "batch_no": batch_no,
            "expiry_date": exp_str or None,
        })

    grn_status = "DISCREPANCY_FLAGGED" if discrepancies else "RECEIVED"
    trust_hash = None
    try:
        block = seal_task_to_block(
            db=db,
            task_id=grn_id,
            capability_name="stocksense_wms_grn",
            action="grn_received_and_slotted",
            payload={
                "grn_id": grn_id,
                "warehouse_code": wh.code,
                "po_number": req.po_number,
                "lines_count": len(processed_lines),
                "discrepancies_count": len(discrepancies),
                "status": grn_status,
            },
            sealed_by="AFW-STOCKSENSE-WMS",
            commit=False,
        )
        trust_hash = block.block_hash
    except Exception:
        pass

    grn = WarehouseGrnRecord(
        id=grn_id,
        org_id=wh.org_id,
        warehouse_id=wh.id,
        client_id=req.client_id,
        po_number=req.po_number.strip(),
        supplier_name=req.supplier_name.strip(),
        status=grn_status,
        lines_json=processed_lines,
        discrepancy_summary_json=discrepancies,
        qr_labels_json=qr_labels,
        received_by=operator_id,
        trust_block_hash=trust_hash,
    )
    db.add(grn)
    db.commit()
    db.refresh(grn)
    return grn


# ── Atomic Bin-to-Bin Transfer ────────────────────────────────────────


def transfer_bin_stock(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    req: BinTransferRequest,
    operator_id: str,
) -> dict[str, Any]:
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    if req.from_bin_id == req.to_bin_id:
        raise ValueError("Source and destination bins must be different")

    sku = (
        db.query(WarehouseSkuRecord)
        .filter(WarehouseSkuRecord.warehouse_id == wh.id, WarehouseSkuRecord.sku_code == req.sku_code.strip().upper())
        .first()
    )
    if not sku:
        raise ValueError(f"SKU '{req.sku_code}' not found in warehouse {wh.code}")

    src_bin = db.get(WarehouseBinRecord, req.from_bin_id)
    dst_bin = db.get(WarehouseBinRecord, req.to_bin_id)
    if not src_bin or src_bin.warehouse_id != wh.id or not dst_bin or dst_bin.warehouse_id != wh.id:
        raise ValueError("Source or destination bin not found in warehouse")

    dst_zone = db.get(WarehouseZoneRecord, dst_bin.zone_id)
    if dst_zone and dst_zone.zone_type not in (sku.required_zone_type, "QUARANTINE", "STAGING"):
        raise ValueError(
            f"Zone safety violation: SKU '{sku.sku_code}' requires '{sku.required_zone_type}' zone, "
            f"cannot transfer into '{dst_zone.zone_type}' bin '{dst_bin.bin_code}'"
        )

    batch_no = req.batch_no.strip().upper()
    exp_str = req.expiry_date.strip()
    src_bal = (
        db.query(StockBalanceRecord)
        .filter(
            StockBalanceRecord.warehouse_id == wh.id,
            StockBalanceRecord.bin_id == src_bin.id,
            StockBalanceRecord.sku_id == sku.id,
            StockBalanceRecord.batch_no == batch_no,
            StockBalanceRecord.expiry_date == exp_str,
        )
        .first()
    )
    available = (src_bal.qty_on_hand - src_bal.qty_reserved) if src_bal else 0
    if available < req.quantity:
        raise ValueError(
            f"Insufficient available stock in bin {src_bin.bin_code}: available={available}, requested={req.quantity}"
        )

    assert src_bal is not None
    src_bal.qty_on_hand -= req.quantity
    dst_bal = _get_or_create_balance(
        db,
        org_id=wh.org_id,
        warehouse_id=wh.id,
        bin_id=dst_bin.id,
        sku=sku,
        batch_no=batch_no,
        expiry_date=exp_str,
    )
    dst_bal.qty_on_hand += req.quantity

    xfer_id = f"XFER-{uuid.uuid4().hex[:10].upper()}"
    post_stock_ledger_entry(
        db,
        org_id=wh.org_id,
        warehouse_id=wh.id,
        client_id=sku.client_id,
        sku_id=sku.id,
        from_bin_id=src_bin.id,
        to_bin_id=dst_bin.id,
        movement_type="BIN_TRANSFER",
        batch_no=batch_no,
        expiry_date=exp_str,
        quantity_delta=-req.quantity,
        balance_after=src_bal.qty_on_hand,
        reference_type="TRANSFER",
        reference_id=xfer_id,
        operator_id=operator_id,
        notes=req.notes or f"Transfer out from {src_bin.bin_code} to {dst_bin.bin_code}",
    )
    post_stock_ledger_entry(
        db,
        org_id=wh.org_id,
        warehouse_id=wh.id,
        client_id=sku.client_id,
        sku_id=sku.id,
        from_bin_id=src_bin.id,
        to_bin_id=dst_bin.id,
        movement_type="BIN_TRANSFER",
        batch_no=batch_no,
        expiry_date=exp_str,
        quantity_delta=req.quantity,
        balance_after=dst_bal.qty_on_hand,
        reference_type="TRANSFER",
        reference_id=xfer_id,
        operator_id=operator_id,
        notes=req.notes or f"Transfer in from {src_bin.bin_code} to {dst_bin.bin_code}",
    )
    db.commit()
    return {
        "transfer_id": xfer_id,
        "sku_code": sku.sku_code,
        "from_bin_code": src_bin.bin_code,
        "to_bin_code": dst_bin.bin_code,
        "quantity": req.quantity,
        "source_balance_after": src_bal.qty_on_hand,
        "destination_balance_after": dst_bal.qty_on_hand,
    }


# ── Directed Wave/Order Picking (Strict FEFO / FIFO + Expired Lot Block) ─


def create_fefo_pick_wave(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    req: PickWaveCreateRequest,
    operator_id: str,
) -> WarehousePickWaveRecord:
    """Create aisle-sorted FEFO/FIFO picklist; automatically blocks expired lots from ever being picked."""
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    today_iso = datetime.now(UTC).strftime("%Y-%m-%d")

    pick_lines: list[dict[str, Any]] = []
    blocked_expired: list[dict[str, Any]] = []
    shortfalls: list[dict[str, Any]] = []

    for line in req.lines:
        sku_code = line.sku_code.strip().upper()
        sku = (
            db.query(WarehouseSkuRecord)
            .filter(WarehouseSkuRecord.warehouse_id == wh.id, WarehouseSkuRecord.sku_code == sku_code)
            .first()
        )
        if not sku:
            raise ValueError(f"SKU '{sku_code}' not registered in warehouse {wh.code}")

        balances = (
            db.query(StockBalanceRecord)
            .filter(
                StockBalanceRecord.warehouse_id == wh.id,
                StockBalanceRecord.sku_id == sku.id,
                StockBalanceRecord.qty_on_hand > 0,
            )
            .all()
        )

        eligible: list[tuple[str, str, str, str, StockBalanceRecord, WarehouseBinRecord]] = []
        for bal in balances:
            avail = bal.qty_on_hand - bal.qty_reserved
            if avail <= 0:
                continue
            b_obj = db.get(WarehouseBinRecord, bal.bin_id)
            if not b_obj:
                continue
            # Hard FEFO safety block on expired lots
            if bal.expiry_date and bal.expiry_date <= today_iso:
                blocked_expired.append({
                    "sku_code": sku_code,
                    "bin_code": b_obj.bin_code,
                    "batch_no": bal.batch_no,
                    "expiry_date": bal.expiry_date,
                    "qty_blocked": avail,
                    "reason": "EXPIRED_LOT_BLOCKED",
                })
                continue
            fefo_key = bal.expiry_date if bal.expiry_date else "9999-12-31"
            eligible.append((fefo_key, b_obj.aisle, b_obj.rack, b_obj.shelf, bal, b_obj))

        # Strict FEFO first (earliest valid expiry_date), then aisle-rack-shelf walk order
        eligible.sort(key=lambda t: (t[0], t[1], t[2], t[3]))

        remaining = int(line.requested_qty)
        for _fefo, _aisle, _rack, _shelf, bal, b_obj in eligible:
            if remaining <= 0:
                break
            avail = bal.qty_on_hand - bal.qty_reserved
            take = min(remaining, avail)
            bal.qty_reserved += take
            remaining -= take
            pick_lines.append({
                "sku_id": sku.id,
                "sku_code": sku_code,
                "barcode": sku.barcode,
                "bin_id": b_obj.id,
                "bin_code": b_obj.bin_code,
                "aisle": b_obj.aisle,
                "rack": b_obj.rack,
                "shelf": b_obj.shelf,
                "batch_no": bal.batch_no,
                "expiry_date": bal.expiry_date or None,
                "pick_qty": take,
            })

        if remaining > 0:
            shortfalls.append({
                "sku_code": sku_code,
                "requested_qty": line.requested_qty,
                "shortfall_qty": remaining,
            })

    # Sort final picklist by physical aisle -> rack -> shelf so floor pickers walk in one efficient pass
    pick_lines.sort(key=lambda x: (x["aisle"], x["rack"], x["shelf"], x["sku_code"]))
    wave_status = "PARTIAL_ALLOCATION" if shortfalls else "OPEN"

    wave = WarehousePickWaveRecord(
        id=str(uuid.uuid4()),
        org_id=wh.org_id,
        warehouse_id=wh.id,
        client_id=req.client_id,
        order_reference=req.order_reference.strip(),
        channel_source=req.channel_source.upper(),
        status=wave_status,
        pick_lines_json=pick_lines,
        blocked_expired_lots_json=blocked_expired,
        shortfalls_json=shortfalls,
    )
    db.add(wave)
    db.commit()
    db.refresh(wave)
    return wave


def dispatch_pick_wave(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    wave_id: str,
    operator_id: str,
) -> WarehousePickWaveRecord:
    """Confirm physical picking & dispatch, posting atomic PICK/DISPATCH ledger entries & ECDSA seal."""
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    wave = db.get(WarehousePickWaveRecord, wave_id)
    if not wave or wave.warehouse_id != wh.id:
        raise ValueError(f"Pick wave {wave_id} not found in warehouse {wh.code}")
    if wave.status == "DISPATCHED":
        raise ValueError("Pick wave is already dispatched")

    for line in wave.pick_lines_json or []:
        exp_str = line.get("expiry_date") or ""
        bal = (
            db.query(StockBalanceRecord)
            .filter(
                StockBalanceRecord.warehouse_id == wh.id,
                StockBalanceRecord.bin_id == line["bin_id"],
                StockBalanceRecord.sku_id == line["sku_id"],
                StockBalanceRecord.batch_no == line["batch_no"],
                StockBalanceRecord.expiry_date == exp_str,
            )
            .first()
        )
        if not bal:
            continue
        qty = int(line["pick_qty"])
        bal.qty_reserved = max(0, bal.qty_reserved - qty)
        bal.qty_on_hand = max(0, bal.qty_on_hand - qty)
        post_stock_ledger_entry(
            db,
            org_id=wh.org_id,
            warehouse_id=wh.id,
            client_id=bal.client_id or wave.client_id,
            sku_id=line["sku_id"],
            from_bin_id=line["bin_id"],
            to_bin_id=None,
            movement_type="DISPATCH",
            batch_no=line["batch_no"],
            expiry_date=exp_str,
            quantity_delta=-qty,
            balance_after=bal.qty_on_hand,
            reference_type="WAVE",
            reference_id=wave.order_reference,
            operator_id=operator_id,
            notes=f"FEFO wave {wave.id[:8]} dispatched ({wave.channel_source})",
        )

    now = datetime.now(UTC)
    trust_hash = None
    try:
        block = seal_task_to_block(
            db=db,
            task_id=wave.id,
            capability_name="stocksense_wms_dispatch",
            action="pick_wave_dispatched",
            payload={
                "wave_id": wave.id,
                "order_reference": wave.order_reference,
                "lines_dispatched": len(wave.pick_lines_json or []),
                "dispatched_by": operator_id,
                "dispatched_at": now.isoformat(),
            },
            sealed_by="AFW-STOCKSENSE-WMS",
            commit=False,
        )
        trust_hash = block.block_hash
    except Exception:
        pass

    wave.status = "DISPATCHED"
    wave.dispatched_by = operator_id
    wave.dispatched_at = now
    wave.trust_block_hash = trust_hash
    db.commit()
    db.refresh(wave)
    return wave


# ── Blind Cryptographic Cycle Counting & Stocktake Certification ───────


def submit_blind_cycle_count(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    req: CycleCountSubmitRequest,
    operator_id: str,
) -> WarehouseCycleCountRecord:
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    sku = (
        db.query(WarehouseSkuRecord)
        .filter(WarehouseSkuRecord.warehouse_id == wh.id, WarehouseSkuRecord.sku_code == req.sku_code.strip().upper())
        .first()
    )
    if not sku:
        raise ValueError(f"SKU '{req.sku_code}' not found in warehouse {wh.code}")
    bin_obj = db.get(WarehouseBinRecord, req.bin_id)
    if not bin_obj or bin_obj.warehouse_id != wh.id:
        raise ValueError(f"Bin {req.bin_id} not found in warehouse {wh.code}")

    batch_no = req.batch_no.strip().upper()
    exp_str = req.expiry_date.strip()
    bal = (
        db.query(StockBalanceRecord)
        .filter(
            StockBalanceRecord.warehouse_id == wh.id,
            StockBalanceRecord.bin_id == bin_obj.id,
            StockBalanceRecord.sku_id == sku.id,
            StockBalanceRecord.batch_no == batch_no,
            StockBalanceRecord.expiry_date == exp_str,
        )
        .first()
    )
    system_qty = int(bal.qty_on_hand) if bal else 0
    variance_qty = int(req.counted_qty) - system_qty
    variance_val = round(variance_qty * float(sku.unit_cost_inr), 2)

    rec = WarehouseCycleCountRecord(
        id=str(uuid.uuid4()),
        org_id=wh.org_id,
        warehouse_id=wh.id,
        bin_id=bin_obj.id,
        sku_id=sku.id,
        batch_no=batch_no,
        expiry_date=exp_str,
        system_qty=system_qty,
        counted_qty=int(req.counted_qty),
        variance_qty=variance_qty,
        variance_value_inr=variance_val,
        status="PENDING_APPROVAL",
        counted_by=operator_id,
        notes=req.notes,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def approve_cycle_count(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    count_id: str,
    req: CycleCountApproveRequest,
    approver_id: str,
) -> WarehouseCycleCountRecord:
    """Manager approves blind count variance -> posts CYCLE_COUNT_ADJUST ledger entry + ECDSA stocktake certificate."""
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    rec = db.get(WarehouseCycleCountRecord, count_id)
    if not rec or rec.warehouse_id != wh.id:
        raise ValueError(f"Cycle count {count_id} not found in warehouse {wh.code}")
    if rec.status != "PENDING_APPROVAL":
        raise ValueError(f"Cycle count is already {rec.status}")

    now = datetime.now(UTC)
    if req.decision == "REJECT":
        rec.status = "REJECTED"
        rec.approved_by = approver_id
        rec.approved_at = now
        if req.notes:
            rec.notes = req.notes
        db.commit()
        db.refresh(rec)
        return rec

    sku = db.get(WarehouseSkuRecord, rec.sku_id)
    assert sku is not None
    bal = _get_or_create_balance(
        db,
        org_id=wh.org_id,
        warehouse_id=wh.id,
        bin_id=rec.bin_id,
        sku=sku,
        batch_no=rec.batch_no,
        expiry_date=rec.expiry_date,
    )
    delta = rec.counted_qty - bal.qty_on_hand
    bal.qty_on_hand = rec.counted_qty

    trust_hash = None
    try:
        block = seal_task_to_block(
            db=db,
            task_id=rec.id,
            capability_name="stocksense_cycle_count_certificate",
            action="cycle_count_certified",
            payload={
                "cycle_count_id": rec.id,
                "warehouse_code": wh.code,
                "sku_code": sku.sku_code,
                "bin_id": rec.bin_id,
                "system_qty": rec.system_qty,
                "counted_qty": rec.counted_qty,
                "variance_qty": delta,
                "variance_value_inr": round(delta * float(sku.unit_cost_inr), 2),
                "approved_by": approver_id,
                "approved_at": now.isoformat(),
            },
            sealed_by="AFW-STOCKSENSE-CYCLE-AUDIT",
            commit=False,
        )
        trust_hash = block.block_hash
    except Exception:
        pass

    post_stock_ledger_entry(
        db,
        org_id=wh.org_id,
        warehouse_id=wh.id,
        client_id=sku.client_id,
        sku_id=sku.id,
        from_bin_id=rec.bin_id if delta < 0 else None,
        to_bin_id=rec.bin_id if delta >= 0 else None,
        movement_type="CYCLE_COUNT_ADJUST",
        batch_no=rec.batch_no,
        expiry_date=rec.expiry_date,
        quantity_delta=delta,
        balance_after=bal.qty_on_hand,
        reference_type="CYCLE_COUNT",
        reference_id=rec.id,
        operator_id=approver_id,
        notes=req.notes or rec.notes or "Approved cycle count variance adjustment",
        trust_block_hash=trust_hash,
    )

    rec.status = "APPROVED_ADJUSTED"
    rec.approved_by = approver_id
    rec.approved_at = now
    rec.trust_block_hash = trust_hash
    db.commit()
    db.refresh(rec)
    return rec


def get_warehouse_stock_summary(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    client_id: str | None = None,
) -> dict[str, Any]:
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    q = db.query(StockBalanceRecord).filter(StockBalanceRecord.warehouse_id == wh.id)
    if client_id:
        q = q.filter(StockBalanceRecord.client_id == client_id)
    balances = q.all()

    items: list[dict[str, Any]] = []
    total_units = 0
    total_value_inr = 0.0
    occupied_bins: set[str] = set()

    for b in balances:
        if b.qty_on_hand <= 0 and b.qty_damaged <= 0:
            continue
        sku = db.get(WarehouseSkuRecord, b.sku_id)
        bin_obj = db.get(WarehouseBinRecord, b.bin_id)
        if not sku or not bin_obj:
            continue
        if b.qty_on_hand > 0:
            occupied_bins.add(bin_obj.id)
        val = round(b.qty_on_hand * float(sku.unit_cost_inr), 2)
        total_units += b.qty_on_hand
        total_value_inr += val
        items.append({
            "sku_code": sku.sku_code,
            "sku_name": sku.name,
            "barcode": sku.barcode,
            "bin_code": bin_obj.bin_code,
            "batch_no": b.batch_no,
            "expiry_date": b.expiry_date or None,
            "qty_on_hand": b.qty_on_hand,
            "qty_reserved": b.qty_reserved,
            "qty_available": max(0, b.qty_on_hand - b.qty_reserved),
            "qty_damaged": b.qty_damaged,
            "unit_cost_inr": sku.unit_cost_inr,
            "valuation_inr": val,
        })

    return {
        "warehouse_id": wh.id,
        "warehouse_code": wh.code,
        "occupied_bins_count": len(occupied_bins),
        "total_units_on_hand": total_units,
        "total_valuation_inr": round(total_value_inr, 2),
        "balances": items,
    }


def list_stock_ledger(
    db: Session,
    *,
    org_id: str | None,
    warehouse_id: str,
    sku_code: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    wh = get_warehouse_scoped(db, org_id, warehouse_id)
    q = db.query(StockLedgerEntryRecord).filter(StockLedgerEntryRecord.warehouse_id == wh.id)
    if sku_code:
        sku = (
            db.query(WarehouseSkuRecord)
            .filter(WarehouseSkuRecord.warehouse_id == wh.id, WarehouseSkuRecord.sku_code == sku_code.strip().upper())
            .first()
        )
        if sku:
            q = q.filter(StockLedgerEntryRecord.sku_id == sku.id)
        else:
            return []
    entries = q.order_by(StockLedgerEntryRecord.created_at.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "sku_id": e.sku_id,
            "client_id": e.client_id,
            "from_bin_id": e.from_bin_id,
            "to_bin_id": e.to_bin_id,
            "movement_type": e.movement_type,
            "batch_no": e.batch_no,
            "expiry_date": e.expiry_date or None,
            "quantity_delta": e.quantity_delta,
            "balance_after": e.balance_after,
            "reference_type": e.reference_type,
            "reference_id": e.reference_id,
            "operator_id": e.operator_id,
            "notes": e.notes,
            "trust_block_hash": e.trust_block_hash,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]
