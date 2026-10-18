"""Autonomous Daily Shift Scheduler & CEO Executive Briefing API Router.

Endpoints for:
- POST /v1/scheduler/run-shift: Trigger an autonomous AI employee shift
- GET  /v1/scheduler/briefing: Retrieve unified CEO Executive Briefing for Vipul (L0 Owner)
- GET  /v1/scheduler/status: Retrieve operational scheduler status and AI employee roster
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import APIPrincipal, require_manager
from app.services.shift_scheduler import (
    get_ceo_daily_briefing,
    get_scheduler_status,
    run_autonomous_shift,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/scheduler", tags=["Autonomous Shift Scheduler"])


class ShiftRunRequest(BaseModel):
    shift_type: str = Field(
        default="full_daily_cycle",
        description="Shift operational profile: full_daily_cycle, outbound_sdr_only, seo_publishing_only, watchdog_audit_only",
    )


@router.post("/run-shift", status_code=status.HTTP_200_OK)
def run_shift_endpoint(
    payload: ShiftRunRequest | None = None,
    shift_type: str | None = Query(default=None),
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Execute an autonomous AI employee shift (SDR Discovery + Trojan-Horse Previews + SEO Staging + Fulfillment + Watchdog)."""
    selected_shift_type = (payload.shift_type if payload else None) or shift_type or "full_daily_cycle"
    correlation_id = x_correlation_id or str(uuid.uuid4())

    try:
        return run_autonomous_shift(
            db=db,
            shift_type=selected_shift_type,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        logger.error(f"Error executing autonomous shift: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Autonomous shift execution failed: {exc}",
        ) from exc


@router.get("/briefing", status_code=status.HTTP_200_OK)
def get_briefing_endpoint(
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve the unified CEO Daily Executive Briefing for Vipul (L0 Owner)."""
    try:
        return get_ceo_daily_briefing(db=db)
    except Exception as exc:
        logger.error(f"Error compiling CEO briefing: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CEO briefing compilation failed: {exc}",
        ) from exc


@router.get("/status", status_code=status.HTTP_200_OK)
def get_scheduler_status_endpoint(
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve operational status, last shift execution, and AI employee roster."""
    try:
        return get_scheduler_status(db=db)
    except Exception as exc:
        logger.error(f"Error retrieving scheduler status: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scheduler status retrieval failed: {exc}",
        ) from exc
