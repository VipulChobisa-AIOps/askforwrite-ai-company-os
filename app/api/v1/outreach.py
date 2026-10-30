"""Outreach API router: Drafting, Owner Approval Governance, and Delivery Dispatch."""

from __future__ import annotations

import logging
import uuid

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import AuditLog, LeadRecordRow, OutreachRecord
from app.schemas.outreach import (
    OutreachDispatchResponse,
    OutreachDraftRequest,
    OutreachDraftResponse,
    OutreachListResponse,
    OutreachResponse,
)
from app.security.auth import (
    APIPrincipal,
    enforce_tenant_access,
    require_manager,
    require_owner,
)
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
    if principal.org_id and payload.org_id and principal.org_id != payload.org_id:
        enforce_tenant_access(principal, payload.org_id)

    correlation_id = x_correlation_id or str(uuid.uuid4())
    try:
        draft = draft_outreach(
            db=db,
            lead_id=payload.lead_id,
            org_id=payload.org_id or principal.org_id,
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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=msg) from exc


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
    effective_org_id = org_id
    if principal.org_id:
        enforce_tenant_access(principal, org_id)
        effective_org_id = principal.org_id

    query = db.query(OutreachRecord)
    if effective_org_id:
        query = query.filter(OutreachRecord.org_id == effective_org_id)
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
    if principal.org_id:
        enforce_tenant_access(principal, record.org_id or "__platform__")
    return OutreachResponse.model_validate(record)


@router.post("/{outreach_id}/dispatch", response_model=OutreachDispatchResponse, status_code=status.HTTP_200_OK)
def dispatch_outreach_endpoint(
    outreach_id: str,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> OutreachDispatchResponse:
    """Dispatch an owner-approved outreach message. Only the Owner can authorize dispatch."""
    record = db.get(OutreachRecord, outreach_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outreach record not found")
    if record.org_id:
        enforce_tenant_access(principal, record.org_id)

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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=msg) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


class OutreachUnsubscribeRequest(BaseModel):
    email: str | None = Field(default=None, max_length=250)
    domain: str | None = Field(default=None, max_length=250)
    lead_id: str | None = Field(default=None, max_length=36)
    reason: str | None = Field(default="Recipient requested opt-out", max_length=500)


class OutreachReplyRequest(BaseModel):
    reply_text: str = Field(min_length=2, max_length=5000, description="Prospect reply message or sales notes")
    intent: Literal["interested", "objection", "question", "unsubscribe"] = "interested"
    channel: Literal["email_notes", "call_notes", "meeting_notes", "internal_notes"] = "email_notes"


@router.post("/unsubscribe", status_code=status.HTTP_200_OK)
def unsubscribe_prospect_endpoint(
    payload: OutreachUnsubscribeRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Public/self-serve and operator opt-out endpoint setting do_not_contact=True and suppressing outreach."""
    if not (payload.email or payload.domain or payload.lead_id):
        raise HTTPException(status_code=400, detail="Provide at least one of email, domain, or lead_id to unsubscribe")

    suppressed_leads: list[str] = []
    cancelled_outreach: list[str] = []

    if payload.lead_id:
        lead = db.get(LeadRecordRow, payload.lead_id)
        if lead:
            lead.do_not_contact = True
            lead.status = "DO_NOT_CONTACT"
            suppressed_leads.append(lead.id)

    if payload.domain:
        clean_dom = payload.domain.strip().lower()
        for lead in db.query(LeadRecordRow).filter(LeadRecordRow.domain == clean_dom).all():
            lead.do_not_contact = True
            lead.status = "DO_NOT_CONTACT"
            if lead.id not in suppressed_leads:
                suppressed_leads.append(lead.id)

    if payload.email:
        clean_email = payload.email.strip().lower()
        for lead in db.query(LeadRecordRow).filter(LeadRecordRow.public_contact_channel == clean_email).all():
            lead.do_not_contact = True
            lead.status = "DO_NOT_CONTACT"
            if lead.id not in suppressed_leads:
                suppressed_leads.append(lead.id)
        for out in db.query(OutreachRecord).filter(OutreachRecord.recipient_email == clean_email).all():
            if out.status in ("DRAFT", "PENDING_APPROVAL"):
                out.status = "SUPPRESSED_OPT_OUT"
                cancelled_outreach.append(out.id)

    for lid in suppressed_leads:
        for out in db.query(OutreachRecord).filter(OutreachRecord.lead_id == lid).all():
            if out.status in ("DRAFT", "PENDING_APPROVAL") and out.id not in cancelled_outreach:
                out.status = "SUPPRESSED_OPT_OUT"
                cancelled_outreach.append(out.id)

    task_id = str(uuid.uuid4())
    db.add(
        AuditLog(
            task_id=task_id,
            correlation_id=task_id,
            agent_id="outreach_opt_out",
            capability_name="outreach_dispatch",
            action="prospect_unsubscribed",
            input_payload=payload.model_dump(),
            output_payload={
                "suppressed_leads": suppressed_leads,
                "cancelled_outreach": cancelled_outreach,
            },
            status="COMPLETED",
        )
    )
    db.commit()

    return {
        "status": "UNSUBSCRIBED",
        "suppressed_leads_count": len(suppressed_leads),
        "suppressed_leads": suppressed_leads,
        "cancelled_outreach_count": len(cancelled_outreach),
    }


@router.post("/{outreach_id}/record-reply", status_code=status.HTTP_200_OK)
def record_outreach_reply_endpoint(
    outreach_id: str,
    payload: OutreachReplyRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record a prospect's reply to an outreach message, advance sales stage, and generate a qualified proposal."""
    record = db.get(OutreachRecord, outreach_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outreach record not found")
    if principal.org_id:
        enforce_tenant_access(principal, record.org_id or "__platform__")

    lead = db.get(LeadRecordRow, record.lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated lead not found")

    correlation_id = x_correlation_id or str(uuid.uuid4())

    if payload.intent == "unsubscribe":
        lead.do_not_contact = True
        lead.status = "DO_NOT_CONTACT"
        record.status = "UNSUBSCRIBED"
        db.commit()
        return {
            "status": "DO_NOT_CONTACT",
            "outreach_id": record.id,
            "lead_id": lead.id,
            "lead_status": lead.status,
        }

    if record.status not in ("SENT", "REPLIED"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot record prospect reply for outreach in status '{record.status}'; outreach must be SENT first.",
        )

    record.status = "REPLIED"
    lead.status = "QUALIFIED"
    lead.last_checked = datetime.now(UTC)
    db.flush()

    from app.services.catalog import build_payment_link
    from app.services.sales import SalesConflict, execute_sales_capture

    try:
        sales_result = execute_sales_capture(
            db=db,
            lead_id=lead.id,
            conversation_notes=payload.reply_text,
            channel=payload.channel,
            idempotency_key=f"reply-sales-{outreach_id}-{hash(payload.reply_text) & 0xFFFFFFFF:x}",
            correlation_id=correlation_id,
            agent_id=principal.subject,
        )
    except SalesConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        sales_result = {
            "status": "QUALIFIED",
            "conversation_notes": payload.reply_text,
            "note": str(exc),
        }

    pkg_key = (
        getattr(record, "package_key", None)
        or (record.metadata_json or {}).get("package_key")
        or lead.product_match
        or "company_os_starter"
    )
    checkout_url = build_payment_link(
        package_key=pkg_key,
        customer_email=record.recipient_email,
        company=lead.company,
        provider="afw_directpay",
    )

    return {
        "status": "QUALIFIED_AND_PROPOSAL_DRAFTED",
        "outreach_id": record.id,
        "lead_id": lead.id,
        "lead_status": lead.status,
        "intent": payload.intent,
        "package_key": pkg_key,
        "checkout_url": checkout_url,
        "sales_capture": sales_result,
    }
