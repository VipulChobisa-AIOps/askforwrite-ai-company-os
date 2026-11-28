"""Phase 3 StockSense Persistent Multi-Tenant SME WMS & 3PL Operations API Router.

Mounted at `/v1/wms`. Enforces `warehouse_automation` entitlement and strict `org_id` isolation
on every facility, zone, bin, SKU, GRN, FEFO pick wave, bin transfer, cycle count, 3PL invoice,
CSV import, and Tally XML / Channel webhook route.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.wms import (
    BinTransferRequest,
    ChannelOrderWebhookRequest,
    CsvImportRequest,
    CycleCountApproveRequest,
    CycleCountSubmitRequest,
    GrnReceiveRequest,
    PickWaveCreateRequest,
    ThreePlInvoiceGenerateRequest,
    WarehouseBinCreate,
    WarehouseBinResponse,
    WarehouseClientCreate,
    WarehouseClientResponse,
    WarehouseCreate,
    WarehouseResponse,
    WarehouseSkuCreate,
    WarehouseSkuResponse,
    WarehouseZoneCreate,
    WarehouseZoneResponse,
)
from app.security.auth import (
    APIPrincipal,
    check_tenant_entitlement,
    require_tenant_manager,
    require_tenant_member,
)
from app.services.stocksense_3pl_erp import (
    export_tally_stock_xml,
    generate_3pl_client_invoice,
    import_skus_and_opening_stock_csv,
    ingest_channel_order_webhook,
)
from app.services.stocksense_wms import (
    approve_cycle_count,
    create_3pl_client,
    create_bin,
    create_fefo_pick_wave,
    create_sku,
    create_warehouse,
    create_zone,
    dispatch_pick_wave,
    get_warehouse_stock_summary,
    list_3pl_clients,
    list_bins,
    list_skus,
    list_stock_ledger,
    list_warehouses,
    list_zones,
    receive_grn_and_putaway,
    submit_blind_cycle_count,
    transfer_bin_stock,
)

router = APIRouter(prefix="/v1/wms", tags=["stocksense_wms_3pl"])


def _handle_wms_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ValueError):
        msg = str(exc)
        code = status.HTTP_404_NOT_FOUND if "not found" in msg.lower() else status.HTTP_422_UNPROCESSABLE_CONTENT
        return HTTPException(status_code=code, detail=msg)
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# ── Warehouses, Zones, Bins, 3PL Clients & SKUs ───────────────────────


@router.post("/warehouses", response_model=WarehouseResponse, status_code=status.HTTP_201_CREATED)
def create_warehouse_endpoint(
    payload: WarehouseCreate,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
):
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return create_warehouse(db, org_id=principal.org_id, req=payload)
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.get("/warehouses", response_model=list[WarehouseResponse])
def list_warehouses_endpoint(
    principal: APIPrincipal = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    check_tenant_entitlement(principal, "warehouse_automation", db)
    return list_warehouses(db, org_id=principal.org_id)


@router.post("/warehouses/{warehouse_id}/zones", response_model=WarehouseZoneResponse, status_code=status.HTTP_201_CREATED)
def create_zone_endpoint(
    warehouse_id: str,
    payload: WarehouseZoneCreate,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
):
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return create_zone(db, org_id=principal.org_id, warehouse_id=warehouse_id, req=payload)
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.get("/warehouses/{warehouse_id}/zones", response_model=list[WarehouseZoneResponse])
def list_zones_endpoint(
    warehouse_id: str,
    principal: APIPrincipal = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return list_zones(db, org_id=principal.org_id, warehouse_id=warehouse_id)
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.post("/warehouses/{warehouse_id}/bins", response_model=WarehouseBinResponse, status_code=status.HTTP_201_CREATED)
def create_bin_endpoint(
    warehouse_id: str,
    payload: WarehouseBinCreate,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
):
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return create_bin(db, org_id=principal.org_id, warehouse_id=warehouse_id, req=payload)
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.get("/warehouses/{warehouse_id}/bins", response_model=list[WarehouseBinResponse])
def list_bins_endpoint(
    warehouse_id: str,
    principal: APIPrincipal = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return list_bins(db, org_id=principal.org_id, warehouse_id=warehouse_id)
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.post("/warehouses/{warehouse_id}/clients", response_model=WarehouseClientResponse, status_code=status.HTTP_201_CREATED)
def create_3pl_client_endpoint(
    warehouse_id: str,
    payload: WarehouseClientCreate,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
):
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return create_3pl_client(db, org_id=principal.org_id, warehouse_id=warehouse_id, req=payload)
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.get("/warehouses/{warehouse_id}/clients", response_model=list[WarehouseClientResponse])
def list_3pl_clients_endpoint(
    warehouse_id: str,
    principal: APIPrincipal = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return list_3pl_clients(db, org_id=principal.org_id, warehouse_id=warehouse_id)
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.post("/warehouses/{warehouse_id}/skus", response_model=WarehouseSkuResponse, status_code=status.HTTP_201_CREATED)
def create_sku_endpoint(
    warehouse_id: str,
    payload: WarehouseSkuCreate,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
):
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return create_sku(db, org_id=principal.org_id, warehouse_id=warehouse_id, req=payload)
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.get("/warehouses/{warehouse_id}/skus", response_model=list[WarehouseSkuResponse])
def list_skus_endpoint(
    warehouse_id: str,
    barcode: str | None = Query(None, description="Lookup SKU by scanned EAN/UPC/QR barcode or SKU code"),
    client_id: str | None = Query(None),
    principal: APIPrincipal = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return list_skus(db, org_id=principal.org_id, warehouse_id=warehouse_id, barcode=barcode, client_id=client_id)
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


# ── Floor Operations: GRN, Directed Slotting, Bin Transfer, FEFO Pick, Cycle Count ──


@router.post("/warehouses/{warehouse_id}/grn", status_code=status.HTTP_201_CREATED)
def receive_grn_endpoint(
    warehouse_id: str,
    payload: GrnReceiveRequest,
    principal: APIPrincipal = Depends(require_tenant_member),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Receive PO/ASN with shortage/damage proof, auto-slotted bin putaway, QR bin labels & double-entry ledger."""
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        grn = receive_grn_and_putaway(
            db,
            org_id=principal.org_id,
            warehouse_id=warehouse_id,
            req=payload,
            operator_id=principal.subject,
        )
        return {
            "id": grn.id,
            "po_number": grn.po_number,
            "supplier_name": grn.supplier_name,
            "status": grn.status,
            "lines": grn.lines_json,
            "discrepancies": grn.discrepancy_summary_json,
            "qr_labels": grn.qr_labels_json,
            "trust_block_hash": grn.trust_block_hash,
        }
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.post("/warehouses/{warehouse_id}/transfers")
def transfer_stock_endpoint(
    warehouse_id: str,
    payload: BinTransferRequest,
    principal: APIPrincipal = Depends(require_tenant_member),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Atomic double-entry bin-to-bin transfer with zone safety check."""
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return transfer_bin_stock(
            db,
            org_id=principal.org_id,
            warehouse_id=warehouse_id,
            req=payload,
            operator_id=principal.subject,
        )
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.post("/warehouses/{warehouse_id}/waves", status_code=status.HTTP_201_CREATED)
def create_pick_wave_endpoint(
    warehouse_id: str,
    payload: PickWaveCreateRequest,
    principal: APIPrincipal = Depends(require_tenant_member),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate aisle-sorted FEFO/FIFO picklist; automatically blocks expired lots."""
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        wave = create_fefo_pick_wave(
            db,
            org_id=principal.org_id,
            warehouse_id=warehouse_id,
            req=payload,
            operator_id=principal.subject,
        )
        return {
            "id": wave.id,
            "order_reference": wave.order_reference,
            "channel_source": wave.channel_source,
            "status": wave.status,
            "pick_lines": wave.pick_lines_json,
            "blocked_expired_lots": wave.blocked_expired_lots_json,
            "shortfalls": wave.shortfalls_json,
        }
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.post("/warehouses/{warehouse_id}/waves/{wave_id}/dispatch")
def dispatch_pick_wave_endpoint(
    warehouse_id: str,
    wave_id: str,
    principal: APIPrincipal = Depends(require_tenant_member),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Confirm pick & dispatch wave, posting immutable DISPATCH ledger entries and ECDSA seal."""
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        wave = dispatch_pick_wave(
            db,
            org_id=principal.org_id,
            warehouse_id=warehouse_id,
            wave_id=wave_id,
            operator_id=principal.subject,
        )
        return {
            "id": wave.id,
            "order_reference": wave.order_reference,
            "status": wave.status,
            "dispatched_by": wave.dispatched_by,
            "dispatched_at": wave.dispatched_at.isoformat() if wave.dispatched_at else None,
            "trust_block_hash": wave.trust_block_hash,
        }
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.post("/warehouses/{warehouse_id}/cycle-counts", status_code=status.HTTP_201_CREATED)
def submit_cycle_count_endpoint(
    warehouse_id: str,
    payload: CycleCountSubmitRequest,
    principal: APIPrincipal = Depends(require_tenant_member),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Submit blind mobile bin stocktake count for variance review."""
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        cc = submit_blind_cycle_count(
            db,
            org_id=principal.org_id,
            warehouse_id=warehouse_id,
            req=payload,
            operator_id=principal.subject,
        )
        return {
            "id": cc.id,
            "bin_id": cc.bin_id,
            "sku_id": cc.sku_id,
            "system_qty": cc.system_qty,
            "counted_qty": cc.counted_qty,
            "variance_qty": cc.variance_qty,
            "variance_value_inr": cc.variance_value_inr,
            "status": cc.status,
        }
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.post("/warehouses/{warehouse_id}/cycle-counts/{count_id}/approve")
def approve_cycle_count_endpoint(
    warehouse_id: str,
    count_id: str,
    payload: CycleCountApproveRequest,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Manager approves blind cycle count variance, adjusts stock ledger & issues ECDSA stocktake certificate."""
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        cc = approve_cycle_count(
            db,
            org_id=principal.org_id,
            warehouse_id=warehouse_id,
            count_id=count_id,
            req=payload,
            approver_id=principal.subject,
        )
        return {
            "id": cc.id,
            "status": cc.status,
            "variance_qty": cc.variance_qty,
            "variance_value_inr": cc.variance_value_inr,
            "approved_by": cc.approved_by,
            "trust_block_hash": cc.trust_block_hash,
        }
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.get("/warehouses/{warehouse_id}/stock")
def warehouse_stock_summary_endpoint(
    warehouse_id: str,
    client_id: str | None = Query(None),
    principal: APIPrincipal = Depends(require_tenant_member),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return get_warehouse_stock_summary(db, org_id=principal.org_id, warehouse_id=warehouse_id, client_id=client_id)
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.get("/warehouses/{warehouse_id}/ledger")
def warehouse_stock_ledger_endpoint(
    warehouse_id: str,
    sku_code: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    principal: APIPrincipal = Depends(require_tenant_member),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return list_stock_ledger(db, org_id=principal.org_id, warehouse_id=warehouse_id, sku_code=sku_code, limit=limit)
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


# ── 3PL Client Billing, Bulk CSV Import & ERP / E-Commerce Channel Sync ──


@router.post("/warehouses/{warehouse_id}/3pl/invoices/generate", status_code=status.HTTP_201_CREATED)
def generate_3pl_invoice_endpoint(
    warehouse_id: str,
    payload: ThreePlInvoiceGenerateRequest,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Auto-generate monthly 3PL client storage + inbound handling + outbound pick/pack invoice with GST & ECDSA seal."""
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        inv = generate_3pl_client_invoice(
            db,
            org_id=principal.org_id,
            warehouse_id=warehouse_id,
            req=payload,
            generated_by=principal.subject,
        )
        return {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "billing_month": inv.billing_month,
            "active_bins_billed": inv.active_bins_billed,
            "billing_days": inv.billing_days,
            "inbound_units_billed": inv.inbound_units_billed,
            "outbound_units_billed": inv.outbound_units_billed,
            "orders_packed_billed": inv.orders_packed_billed,
            "storage_charge_inr": inv.storage_charge_inr,
            "inbound_charge_inr": inv.inbound_charge_inr,
            "outbound_charge_inr": inv.outbound_charge_inr,
            "packing_charge_inr": inv.packing_charge_inr,
            "subtotal_inr": inv.subtotal_inr,
            "gst_inr": inv.gst_inr,
            "total_inr": inv.total_inr,
            "line_items": inv.line_items_json,
            "audit_sha256": inv.audit_sha256,
            "trust_block_hash": inv.trust_block_hash,
        }
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.post("/warehouses/{warehouse_id}/import/csv")
def import_csv_endpoint(
    warehouse_id: str,
    payload: CsvImportRequest,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Bulk CSV SKU & opening stock importer with atomic dry_run validation."""
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return import_skus_and_opening_stock_csv(
            db,
            org_id=principal.org_id,
            warehouse_id=warehouse_id,
            req=payload,
            operator_id=principal.subject,
        )
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.post("/warehouses/{warehouse_id}/channels/order-webhook", status_code=status.HTTP_201_CREATED)
def channel_order_webhook_endpoint(
    warehouse_id: str,
    payload: ChannelOrderWebhookRequest,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Ingest Shopify / WooCommerce / Zoho / Tally order into a FEFO-enforced Pick Wave."""
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        return ingest_channel_order_webhook(
            db,
            org_id=principal.org_id,
            warehouse_id=warehouse_id,
            req=payload,
            operator_id=principal.subject,
        )
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc


@router.get("/warehouses/{warehouse_id}/exports/tally-stock-xml")
def export_tally_stock_xml_endpoint(
    warehouse_id: str,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
):
    """Export warehouse stock balances and certified cycle-count journals in Tally XML format."""
    check_tenant_entitlement(principal, "warehouse_automation", db)
    try:
        res = export_tally_stock_xml(db, org_id=principal.org_id, warehouse_id=warehouse_id)
        return Response(
            content=res["content"],
            media_type=res["media_type"],
            headers={
                "Content-Disposition": f'attachment; filename="{res["filename"]}"',
                "X-AFW-StockSense-Audit-SHA256": res["audit_sha256"],
                "X-AFW-Total-Valuation-INR": f"{res['total_valuation_inr']:.2f}",
            },
        )
    except Exception as exc:
        raise _handle_wms_errors(exc) from exc
