"""Durable owner approval requests and decisions."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.policy import approval_required
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    LeadRecordRow,
    ProposalRecord,
    TaskRecord,
)


class ApprovalConflict(Exception):
    """Raised when an approval key or already-decided request conflicts."""


class ApprovalNotFound(Exception):
    """Raised when the referenced task or approval does not exist."""


def _request_hash(
    task_id: str,
    lead_id: str | None,
    proposal_id: str | None,
    action: str,
    detail: dict,
) -> str:
    request = json.dumps(
        {
            "task_id": task_id,
            "lead_id": lead_id,
            "proposal_id": proposal_id,
            "action": action,
            "detail": detail,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(request.encode("utf-8")).hexdigest()


def _approval_payload(approval: ApprovalRequest) -> dict[str, object]:
    return {
        "approval_id": approval.id,
        "task_id": approval.task_id,
        "lead_id": approval.lead_id,
        "proposal_id": approval.proposal_id,
        "action": approval.action,
        "status": approval.status,
        "external_action_performed": False,
    }


def request_approval(
    db: Session,
    task_id: str,
    lead_id: str | None,
    action: str,
    detail: dict,
    idempotency_key: str,
    requested_by: str,
    correlation_id: str,
    proposal_id: str | None = None,
    commit: bool = True,
) -> dict[str, object]:
    key = idempotency_key.strip()
    if not key:
        raise ValueError("idempotency_key must not be empty")
    if not approval_required(action):
        raise ValueError("action does not require owner approval")

    request_hash = _request_hash(task_id, lead_id, proposal_id, action, detail)
    existing = db.query(ApprovalRequest).filter_by(idempotency_key=key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise ApprovalConflict("Idempotency key was already used for another approval")
        return _approval_payload(existing)

    task = db.get(TaskRecord, task_id)
    if task is None:
        raise ApprovalNotFound("Task not found")

    if action == "external_sales_outreach":
        if lead_id is None:
            raise ValueError("lead_id is required for external sales outreach approval")
        lead = db.get(LeadRecordRow, lead_id)
        if lead is None or lead.task_id != task_id:
            raise ApprovalNotFound("Lead not found for this task")
        if lead.do_not_contact or lead.status == "DO_NOT_CONTACT":
            raise ValueError("do-not-contact leads cannot be approved for outreach")
        if lead.status not in {"DISCOVERED", "RESEARCHED", "QUALIFIED"}:
            raise ValueError(f"lead status {lead.status} cannot be approved for outreach")
    elif lead_id is not None and db.get(LeadRecordRow, lead_id) is None:
        raise ApprovalNotFound("Lead not found")

    if action == "proposal_delivery":
        # proposal_id is optional at request time; validation occurs later when the proposal exists.
        if proposal_id is not None:
            proposal = db.get(ProposalRecord, proposal_id)
            if proposal is None or proposal.task_id != task_id or proposal.lead_id != lead_id:
                raise ApprovalNotFound("Proposal not found for this task and lead")
            if proposal.status != "AWAITING_APPROVAL":
                raise ValueError("proposal must be awaiting approval")

    approval = ApprovalRequest(
        id=str(uuid4()),
        task_id=task_id,
        lead_id=lead_id,
        proposal_id=proposal_id,
        action=action,
        detail=detail,
        idempotency_key=key,
        request_hash=request_hash,
        status="PENDING",
        requested_by=requested_by,
    )
    db.add(approval)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(ApprovalRequest).filter_by(idempotency_key=key).first()
        if existing:
            if existing.request_hash != request_hash:
                raise ApprovalConflict("Idempotency key was already used for another approval")
            return _approval_payload(existing)
        raise

    db.add(AuditLog(
        task_id=task_id,
        correlation_id=correlation_id,
        agent_id=requested_by,
        capability_name="human_approval",
        action="approval_requested",
        input_payload={
            "approval_id": approval.id,
            "action": action,
            "lead_id": lead_id,
            "proposal_id": proposal_id,
        },
        output_payload={"status": "PENDING"},
        status="COMPLETED",
    ))
    if commit:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
    else:
        db.flush()
    return _approval_payload(approval)


def decide_approval(
    db: Session,
    approval_id: str,
    decision: str,
    decided_by: str,
    correlation_id: str,
    decision_note: str | None = None,
) -> dict[str, object]:
    approval = db.query(ApprovalRequest).filter_by(id=approval_id).with_for_update().first()
    if approval is None:
        raise ApprovalNotFound("Approval request not found")
    if decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("decision must be APPROVED or REJECTED")
    if approval.status != "PENDING":
        if approval.status == decision:
            return _approval_payload(approval)
        raise ApprovalConflict(f"Approval request is already {approval.status}")

    lead = db.get(LeadRecordRow, approval.lead_id) if approval.lead_id else None
    if approval.action == "external_sales_outreach" and lead is not None:
        if lead.do_not_contact or lead.status == "DO_NOT_CONTACT":
            raise ApprovalConflict("do-not-contact leads cannot be approved for outreach")
        lead.status = "APPROVED_FOR_OUTREACH" if decision == "APPROVED" else "REJECTED"
    if approval.action == "proposal_delivery" and approval.proposal_id:
        proposal = db.get(ProposalRecord, approval.proposal_id)
        if proposal is None or proposal.status != "AWAITING_APPROVAL":
            raise ApprovalConflict("proposal is no longer awaiting approval")
        proposal.status = decision
        proposal.decided_at = datetime.now(UTC)
        if lead is not None:
            lead.status = "PROPOSAL_APPROVED" if decision == "APPROVED" else "PROPOSAL_REJECTED"

    approval.status = decision
    approval.decided_by = decided_by
    approval.decision_note = decision_note
    approval.decided_at = datetime.now(UTC)
    db.add(AuditLog(
        task_id=approval.task_id,
        correlation_id=correlation_id,
        agent_id=decided_by,
        capability_name="human_approval",
        action="approval_decided",
        input_payload={
            "approval_id": approval.id,
            "action": approval.action,
            "proposal_id": approval.proposal_id,
        },
        output_payload={
            "decision": decision,
            "lead_id": approval.lead_id,
            "proposal_id": approval.proposal_id,
            "external_action_performed": False,
        },
        status="COMPLETED",
    ))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _approval_payload(approval)