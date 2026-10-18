"""API router for System Monitoring & Controlling Watchdog Agent."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.watchdog import (
    WatchdogAlertNotFound,
    get_system_control_telemetry,
    list_watchdog_alerts,
    resolve_watchdog_alert,
    run_system_watchdog_scan,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/watchdog", tags=["watchdog"])


class WatchdogScanRequest(BaseModel):
    stale_minutes: int = Field(
        default=60,
        ge=1,
        le=10080,
        description="Threshold in minutes to classify pending tasks/approvals/orders as stalled",
    )


class ResolveAlertRequest(BaseModel):
    resolved_by: str = Field(default="owner", max_length=100)
    resolution_notes: str = Field(default="", max_length=1000)


@router.post("/scan")
def trigger_system_watchdog_scan(
    payload: WatchdogScanRequest | None = None,
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Execute real-time supervisory scan across tasks, approvals, field presence, and ledger integrity."""
    stale_mins = payload.stale_minutes if payload else 60
    return run_system_watchdog_scan(
        db=db,
        stale_minutes=stale_mins,
        correlation_id=x_correlation_id,
    )


@router.get("/alerts")
def get_watchdog_alerts(
    status_filter: str | None = Query(default=None, alias="status", description="Filter by status (OPEN, RESOLVED)"),
    severity: str | None = Query(default=None, description="Filter by severity (CRITICAL, HIGH, MEDIUM, LOW)"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve operational alerts flagged by the Watchdog and Supervisor Co-Pilot."""
    alerts = list_watchdog_alerts(db=db, status=status_filter, severity=severity, limit=limit)
    return {
        "count": len(alerts),
        "alerts": alerts,
    }


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(
    alert_id: str,
    payload: ResolveAlertRequest | None = None,
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Resolve an operational alert and cryptographically seal the resolution action."""
    resolved_by = payload.resolved_by if payload else "owner"
    notes = payload.resolution_notes if payload else ""
    try:
        res = resolve_watchdog_alert(
            db=db,
            alert_id=alert_id,
            resolved_by=resolved_by,
            resolution_notes=notes,
            correlation_id=x_correlation_id,
        )
        return {
            "status": "RESOLVED",
            "alert": res,
            "block_hash": res.get("block_hash"),
        }
    except WatchdogAlertNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/telemetry")
def get_watchdog_telemetry(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Compile real-time operational control telemetry for L0 Owner cockpit."""
    return get_system_control_telemetry(db=db)
