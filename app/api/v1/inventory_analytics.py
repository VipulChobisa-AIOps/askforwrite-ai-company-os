"""API router for StockSense Warehouse Automation & Inventory Analytics."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.inventory_analytics import (
    DEFAULT_BENCHMARK_SKUS,
    INVENTORY_UAT_LOG,
    InventoryAnalyticsConflict,
    compute_reorder_recommendations,
    execute_inventory_audit,
    log_inventory_uat,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/inventory", tags=["inventory_analytics"])


class InventoryAuditRequest(BaseModel):
    items: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional custom SKU catalog list; defaults to StockSense benchmark catalog",
    )
    service_level_z: float = Field(
        default=1.65,
        description="Z-score for target customer service level (1.65 = 95%, 2.33 = 99%)",
        ge=1.0,
        le=3.0,
    )
    forecast_alpha: float = Field(
        default=0.3,
        description="Exponential smoothing alpha weight for demand forecasting",
        ge=0.01,
        le=1.0,
    )
    dead_stock_threshold_days: int = Field(
        default=90,
        description="Threshold of days without sale to classify as dead stock",
        ge=30,
        le=365,
    )


class InventoryUATRequest(BaseModel):
    operator_id: str = Field(default="warehouse-mgr-01")
    rating: int = Field(default=5, ge=1, le=5)
    notes: str = Field(default="", max_length=1000)
    discrepancy_reported: bool = Field(default=False)


@router.get("/status")
def get_inventory_status() -> dict[str, Any]:
    """Retrieve operational status for StockSense Warehouse Automation."""
    return {
        "status": "ONLINE",
        "engine": "StockSense v2.4 (Pareto ABC + Exponential Smoothing ROP/EOQ)",
        "benchmark_skus_available": len(DEFAULT_BENCHMARK_SKUS),
        "supported_features": [
            "pareto_abc_segmentation",
            "exponential_smoothing_forecast",
            "dynamic_reorder_point",
            "economic_order_quantity",
            "dead_stock_aging_detection",
            "cryptographic_trust_sealing",
        ],
    }


@router.post("/audit")
@router.post("/analyze")
def run_inventory_audit(
    payload: InventoryAuditRequest,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Execute an automated StockSense warehouse inventory audit with ABC analysis and TrustBlock sealing."""
    try:
        result = execute_inventory_audit(
            db=db,
            items=payload.items,
            service_level_z=payload.service_level_z,
            forecast_alpha=payload.forecast_alpha,
            dead_stock_threshold_days=payload.dead_stock_threshold_days,
            idempotency_key=x_idempotency_key,
            correlation_id=x_correlation_id,
        )
        return result
    except InventoryAnalyticsConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post("/reorder")
@router.post("/reorder-plan")
def get_reorder_recommendations(
    payload: InventoryAuditRequest,
) -> dict[str, Any]:
    """Calculate dynamic Reorder Points (ROP) and EOQ recommendations without database mutation."""
    items = payload.items or DEFAULT_BENCHMARK_SKUS
    reorders = compute_reorder_recommendations(
        items=items,
        service_level_z=payload.service_level_z,
        forecast_alpha=payload.forecast_alpha,
    )
    urgent = [r for r in reorders if r["reorder_needed"]]
    return {
        "total_evaluated": len(reorders),
        "urgent_reorders_count": len(urgent),
        "recommendations": reorders,
    }


@router.post("/uat")
def submit_inventory_uat(
    payload: InventoryUATRequest,
) -> dict[str, Any]:
    """Submit warehouse manager UAT survey feedback into operational ledger."""
    entry = log_inventory_uat(
        operator_id=payload.operator_id,
        rating=payload.rating,
        notes=payload.notes,
        discrepancy_reported=payload.discrepancy_reported,
    )
    return {
        "status": "RECORDED",
        "entry": entry["entry"],
        "total_logged": len(INVENTORY_UAT_LOG),
    }
