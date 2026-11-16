"""Outreach API router: Drafting, Owner Approval Governance, and Delivery Dispatch."""

from __future__ import annotations

import hashlib
import hmac
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
    TENANT_MANAGER_ROLES,
    APIPrincipal,
    _get_signing_secret,
    enforce_tenant_access,
    get_current_principal,
    require_owner,
    require_tenant_manager,
)
from app.services.approvals import ApprovalConflict, ApprovalNotFound
from app.services.outreach import dispatch_outreach, draft_outreach

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/outreach", tags=["outreach"])


@router.post("/draft", response_model=OutreachDraftResponse, status_code=status.HTTP_200_OK)
def draft_outreach_endpoint(
    payload: OutreachDraftRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
) -> OutreachDraftResponse:
    """Draft personalized customer outreach and generate a durable owner approval request."""
    if principal.org_id and payload.org_id is not None:
        enforce_tenant_access(principal, payload.org_id)
    lead_row = db.get(LeadRecordRow, payload.lead_id)
    if lead_row and principal.org_id:
        enforce_tenant_access(principal, lead_row.org_id or "__platform__")

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
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
) -> OutreachListResponse:
    """List outreach messages filtered by organization, lead, or delivery status."""
    effective_org_id = org_id
    if principal.org_id:
        if org_id is not None:
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
    principal: APIPrincipal = Depends(require_tenant_manager),
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
    unsubscribe_token: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default="Recipient requested opt-out", max_length=500)


def create_unsubscribe_token(
    *,
    email: str | None = None,
    domain: str | None = None,
    lead_id: str | None = None,
) -> str:
    """Create a deterministic HMAC-SHA256 proof token authorizing a recipient opt-out."""
    canonical = "|".join([
        (email or "").strip().lower(),
        (domain or "").strip().lower(),
        (lead_id or "").strip(),
    ])
    return hmac.new(
        _get_signing_secret().encode("utf-8"),
        f"afw-unsubscribe:{canonical}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class OutreachReplyRequest(BaseModel):
    reply_text: str = Field(min_length=2, max_length=5000, description="Prospect reply message or sales notes")
    intent: Literal["interested", "objection", "question", "unsubscribe"] = "interested"
    channel: Literal["email_notes", "call_notes", "meeting_notes", "internal_notes"] = "email_notes"


@router.post("/unsubscribe", status_code=status.HTTP_200_OK)
def unsubscribe_prospect_endpoint(
    payload: OutreachUnsubscribeRequest,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_gemini_api_key: str | None = Header(default=None, alias="X-Gemini-Api-Key"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Authenticated tenant-scoped opt-out or signed recipient unsubscribe link handler."""
    if not (payload.email or payload.domain or payload.lead_id):
        raise HTTPException(status_code=400, detail="Provide at least one of email, domain, or lead_id to unsubscribe")

    principal: APIPrincipal | None = None
    verified_recipient_token = False
    if authorization or x_api_key:
        principal = get_current_principal(
            x_api_key=x_api_key,
            authorization=authorization,
            x_gemini_api_key=x_gemini_api_key,
            db=db,
        )
        if not (principal.is_platform_operator or (principal.org_id and principal.role in TENANT_MANAGER_ROLES)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant administrator or platform manager role required to suppress outreach",
            )
    elif payload.unsubscribe_token and payload.unsubscribe_token.strip():
        expected = create_unsubscribe_token(
            email=payload.email,
            domain=payload.domain,
            lead_id=payload.lead_id,
        )
        if not hmac.compare_digest(expected, payload.unsubscribe_token.strip()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid unsubscribe token",
            )
        verified_recipient_token = True
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication or valid unsubscribe_token is required",
        )

    tenant_org_scope: str | None = (
        None if (principal is None or principal.is_platform_operator) else principal.org_id
    )
    allow_global_suppression = verified_recipient_token or (
        principal is not None and principal.is_platform_operator
    )

    suppressed_leads: list[str] = []
    cancelled_outreach: list[str] = []

    if payload.lead_id:
        lead = db.get(LeadRecordRow, payload.lead_id)
        if lead:
            if tenant_org_scope is not None:
                enforce_tenant_access(principal, lead.org_id or "__platform__")
            lead.do_not_contact = True
            lead.status = "DO_NOT_CONTACT"
            suppressed_leads.append(lead.id)

    if payload.domain:
        clean_dom = payload.domain.strip().lower()
        dom_q = db.query(LeadRecordRow).filter(LeadRecordRow.domain == clean_dom)
        if tenant_org_scope is not None:
            dom_q = dom_q.filter(LeadRecordRow.org_id == tenant_org_scope)
        for lead in dom_q.all():
            lead.do_not_contact = True
            lead.status = "DO_NOT_CONTACT"
            if lead.id not in suppressed_leads:
                suppressed_leads.append(lead.id)

    if payload.email:
        clean_email = payload.email.strip().lower()
        email_q = db.query(LeadRecordRow).filter(LeadRecordRow.public_contact_channel == clean_email)
        out_q = db.query(OutreachRecord).filter(OutreachRecord.recipient_email == clean_email)
        if tenant_org_scope is not None:
            email_q = email_q.filter(LeadRecordRow.org_id == tenant_org_scope)
            out_q = out_q.filter(OutreachRecord.org_id == tenant_org_scope)
        for lead in email_q.all():
            lead.do_not_contact = True
            lead.status = "DO_NOT_CONTACT"
            if lead.id not in suppressed_leads:
                suppressed_leads.append(lead.id)
        for out in out_q.all():
            if out.status in ("DRAFT", "PENDING_APPROVAL"):
                out.status = "SUPPRESSED_OPT_OUT"
                cancelled_outreach.append(out.id)

    for lid in suppressed_leads:
        out_lid_q = db.query(OutreachRecord).filter(OutreachRecord.lead_id == lid)
        if tenant_org_scope is not None:
            out_lid_q = out_lid_q.filter(OutreachRecord.org_id == tenant_org_scope)
        for out in out_lid_q.all():
            if out.status in ("DRAFT", "PENDING_APPROVAL") and out.id not in cancelled_outreach:
                out.status = "SUPPRESSED_OPT_OUT"
                cancelled_outreach.append(out.id)

    # Persist into DB-backed suppression table (global only for platform operator or verified recipient token)
    from app.db.models import P2ProspectDossierRecord
    from app.services.suppression import add_db_suppression

    if allow_global_suppression and payload.email:
        add_db_suppression(db, payload.email, reason=payload.reason or "Recipient opted out", source="unsubscribe_endpoint")
    if allow_global_suppression and payload.domain:
        add_db_suppression(db, payload.domain, reason=payload.reason or "Domain opted out", source="unsubscribe_endpoint")
    for lid in suppressed_leads:
        add_db_suppression(db, lid, reason=payload.reason or "Lead opted out", source="unsubscribe_endpoint", identifier_type="lead_id")
        dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=lid).first()
        if dossier:
            dossier.pipeline_status = "DO_NOT_CONTACT"
            dossier.next_action = "Opted out via unsubscribe endpoint"
            db.add(dossier)

    task_id = str(uuid.uuid4())
    db.add(
        AuditLog(
            task_id=task_id,
            correlation_id=task_id,
            agent_id=principal.subject if principal else "recipient_unsubscribe_token",
            capability_name="outreach_opt_out",
            action="prospect_unsubscribed",
            input_payload={
                "email": payload.email,
                "domain": payload.domain,
                "lead_id": payload.lead_id,
                "org_scope": tenant_org_scope,
            },
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
    principal: APIPrincipal = Depends(require_tenant_manager),
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

    if record.status not in ("SENT", "DISPATCHED", "REPLIED", "SIMULATED_SENT"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot record prospect reply for outreach in status '{record.status}'; outreach must be SENT or DISPATCHED first.",
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
