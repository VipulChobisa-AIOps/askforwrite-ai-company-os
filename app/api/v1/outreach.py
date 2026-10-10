"""Outreach API router: Drafting, Owner Approval Governance, and Delivery Dispatch."""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import OutreachRecord
from app.schemas.outreach import (
    OutreachDispatchResponse,
    OutreachDraftRequest,
    OutreachDraftResponse,
    OutreachListResponse,
    OutreachResponse,
)
from app.security.auth import APIPrincipal, require_manager, require_owner
from app.services.approvals import ApprovalConflict, ApprovalNotFound
from app.services.outreach import dispatch_outreach, draft_outreach

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/outreach", tags=["outreach"])


@router.post("/draft", response_model=OutreachDraftResponse, status_code=status.HTTP_200_OK)
def draft_outreach_endpoint(
    payload: OutreachDraftRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> OutreachDraftResponse:
    """Draft personalized customer outreach and generate a durable owner approval request."""
    correlation_id = x_correlation_id or str(uuid.uuid4())
    try:
        draft = draft_outreach(
            db=db,
            lead_id=payload.lead_id,
            org_id=payload.org_id,
            recipient_email=payload.recipient_email,
            recipient_name=payload.recipient_name,
            custom_notes=payload.custom_notes,
            channel=payload.channel,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            requested_by=principal.subject,
        )
        return OutreachDraftResponse(**draft)
    except ApprovalConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        if "quota" in msg.lower() or "limit" in msg.lower():
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=msg) from exc
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg) from exc


@router.get("", response_model=OutreachListResponse)
def list_outreach_records(
    org_id: str | None = None,
    lead_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> OutreachListResponse:
    """List outreach messages filtered by organization, lead, or delivery status."""
    query = db.query(OutreachRecord)
    if org_id:
        query = query.filter(OutreachRecord.org_id == org_id)
    if lead_id:
        query = query.filter(OutreachRecord.lead_id == lead_id)
    if status_filter:
        query = query.filter(OutreachRecord.status == status_filter)

    total = query.count()
    records = query.order_by(OutreachRecord.created_at.desc()).offset(offset).limit(limit).all()

    return OutreachListResponse(
        count=len(records),
        total=total,
        records=[OutreachResponse.model_validate(r) for r in records],
    )


@router.get("/{outreach_id}", response_model=OutreachResponse)
def get_outreach_record(
    outreach_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> OutreachResponse:
    """Retrieve details of a single outreach message record."""
    record = db.get(OutreachRecord, outreach_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outreach record not found")
    return OutreachResponse.model_validate(record)


@router.post("/{outreach_id}/dispatch", response_model=OutreachDispatchResponse, status_code=status.HTTP_200_OK)
def dispatch_outreach_endpoint(
    outreach_id: str,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> OutreachDispatchResponse:
    """Dispatch an owner-approved outreach message. Only the Owner can authorize dispatch."""
    correlation_id = x_correlation_id or str(uuid.uuid4())
    try:
        result = dispatch_outreach(
            db=db,
            outreach_id=outreach_id,
            correlation_id=correlation_id,
            dispatched_by=principal.subject,
        )
        return OutreachDispatchResponse(**result)
    except ValueError as exc:
        msg = str(exc)
        if "quota" in msg.lower():
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=msg) from exc
        if "approval" in msg.lower():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg) from exc
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
