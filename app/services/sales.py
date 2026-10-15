"""Persistence workflow for Sales requirements and draft proposals."""

import hashlib
import json
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.sales import build_sales_draft
from app.db.models import (
    AuditLog,
    ConversationRecord,
    IdempotencyRecord,
    LeadRecordRow,
    ProposalRecord,
    RequirementRecord,
    ResearchRecord,
    TaskRecord,
)
from app.security.trust_chain import seal_task_to_block
from app.services.approvals import request_approval

CAPABILITY_NAME = "sales_requirement_capture"


class SalesConflict(Exception):
    """Raised when a Sales idempotency key conflicts with its original request."""


class SalesNotFound(Exception):
    """Raised when the referenced lead does not exist."""


def _request_hash(lead_id: str, channel: str, notes: str) -> str:
    request = json.dumps(
        {"lead_id": lead_id, "channel": channel, "notes": notes.strip()},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(request.encode("utf-8")).hexdigest()


def _sales_response(
    task_id: str,
    correlation_id: str,
    conversation_id: str,
    requirement_id: str,
    proposal_id: str | None,
    approval_id: str | None,
    priority: str,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "correlation_id": correlation_id,
        "status": "COMPLETED",
        "conversation_id": conversation_id,
        "requirement_id": requirement_id,
        "proposal_id": proposal_id,
        "approval_id": approval_id,
        "priority": priority,
        "proposal_status": "AWAITING_APPROVAL" if proposal_id else None,
        "proposal_delivery_approval_required": bool(proposal_id),
        "external_action_performed": False,
    }


def execute_sales_capture(
    db: Session,
    lead_id: str,
    conversation_notes: str,
    channel: str,
    idempotency_key: str,
    correlation_id: str,
    agent_id: str,
) -> dict[str, object]:
    key = idempotency_key.strip()
    notes = conversation_notes.strip()
    if not key:
        raise ValueError("idempotency_key must not be empty")
    if not notes:
        raise ValueError("conversation_notes must not be empty")

    existing = db.query(IdempotencyRecord).filter_by(
        capability_name=CAPABILITY_NAME,
        idempotency_key=key,
    ).first()
    request_hash = _request_hash(lead_id, channel, notes)
    if existing:
        if existing.request_hash != request_hash:
            raise SalesConflict("Idempotency key was already used for another Sales request")
        if existing.response_payload is None:
            raise SalesConflict("The original Sales request is still being processed")
        return existing.response_payload

    lead = db.get(LeadRecordRow, lead_id)
    if lead is None:
        raise SalesNotFound("Lead not found")
    if lead.do_not_contact or lead.status == "DO_NOT_CONTACT":
        raise ValueError("do-not-contact leads cannot enter the Sales workflow")
    if lead.status != "APPROVED_FOR_OUTREACH":
        raise ValueError("owner approval is required before Sales requirement capture")
    if db.query(ResearchRecord).filter_by(lead_id=lead_id).first() is None:
        raise ValueError("Research evidence is required before Sales requirement capture")

    task_id = str(uuid4())
    conversation_id = str(uuid4())
    requirement_id = str(uuid4())
    proposal_id = str(uuid4())
    idempotency = IdempotencyRecord(
        capability_name=CAPABILITY_NAME,
        idempotency_key=key,
        request_hash=request_hash,
        task_id=task_id,
    )
    db.add(idempotency)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(IdempotencyRecord).filter_by(
            capability_name=CAPABILITY_NAME,
            idempotency_key=key,
        ).first()
        if existing:
            if existing.request_hash != request_hash:
                raise SalesConflict("Idempotency key was already used for another Sales request")
            if existing.response_payload is None:
                raise SalesConflict("The original Sales request is still being processed")
            return existing.response_payload
        raise

    draft = build_sales_draft(
        company=lead.company,
        geography=lead.geography,
        notes=notes,
        lead_product_match=lead.product_match,
    )
    task = TaskRecord(
        id=task_id,
        correlation_id=correlation_id,
        objective=f"Capture requirements for {lead.company}",
        status="COMPLETED",
    )
    conversation = ConversationRecord(
        id=conversation_id,
        lead_id=lead_id,
        task_id=task_id,
        channel=channel,
        notes=notes,
    )
    requirement = RequirementRecord(
        id=requirement_id,
        lead_id=lead_id,
        conversation_id=conversation_id,
        task_id=task_id,
        customer_company=lead.company,
        stated_needs=draft.stated_needs,
        has_budget_signal=draft.has_budget_signal,
        has_timeline=draft.has_timeline,
        constraints=draft.constraints,
        product_match=draft.product_match,
        priority=draft.priority,
        status="QUALIFIED" if draft.stated_needs else "NEEDS_CLARIFICATION",
    )
    db.add_all([task, conversation, requirement])

    proposal: ProposalRecord | None = None
    if draft.stated_needs:
        proposal = ProposalRecord(
            id=proposal_id,
            task_id=task_id,
            requirement_id=requirement_id,
            lead_id=lead_id,
            title=draft.proposal_title,
            summary=draft.proposal_summary,
            scope=draft.proposal_scope,
            pricing_model="owner-defined",
            status="AWAITING_APPROVAL",
        )
        db.add(proposal)
        lead.status = "PROPOSAL_DRAFTED"
    else:
        lead.status = "REQUIREMENT_CAPTURED"

    db.add(AuditLog(
        task_id=task_id,
        correlation_id=correlation_id,
        agent_id=agent_id,
        capability_name=CAPABILITY_NAME,
        action="capture_requirement",
        input_payload={"lead_id": lead_id, "channel": channel},
        output_payload={
            "requirement_id": requirement_id,
            "priority": draft.priority,
            "proposal_drafted": proposal is not None,
        },
        status="COMPLETED",
    ))
    db.flush()

    approval_id = None
    if proposal is not None:
        approval_key = hashlib.sha256(f"proposal-delivery:{key}".encode()).hexdigest()
        approval = request_approval(
            db=db,
            task_id=task_id,
            lead_id=lead_id,
            proposal_id=proposal.id,
            action="proposal_delivery",
            detail={"proposal_id": proposal.id, "title": proposal.title},
            idempotency_key=approval_key,
            requested_by=agent_id,
            correlation_id=correlation_id,
            commit=False,
        )
        approval_id = str(approval["approval_id"])
        proposal.approval_id = approval_id

    response = _sales_response(
        task_id,
        correlation_id,
        conversation_id,
        requirement_id,
        proposal.id if proposal else None,
        approval_id,
        draft.priority,
    )
    task.result = response
    idempotency.response_payload = response
    seal_task_to_block(
        db=db,
        task_id=task_id,
        capability_name=CAPABILITY_NAME,
        action="capture_requirement",
        payload={
            "status": "COMPLETED",
            "lead_id": lead_id,
            "requirement_id": requirement_id,
            "proposal_id": proposal.id if proposal else None,
            "approval_id": approval_id,
            "correlation_id": correlation_id,
        },
        sealed_by=agent_id,
        commit=False,
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return response