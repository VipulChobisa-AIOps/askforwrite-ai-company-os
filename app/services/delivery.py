"""Owner-approved delivery through the selected Field Force capability."""

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clients.field_force import (
    FieldForceClient,
    FieldForceExecutionError,
    FieldForceNotConfigured,
    get_field_force_client,
)
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    DeliveryRecord,
    IdempotencyRecord,
    LeadRecordRow,
    ProposalRecord,
    TaskRecord,
)
from app.security.trust_chain import seal_task_to_block

CAPABILITY_NAME = "field_force_task_creation"


class DeliveryNotFound(Exception):
    """Raised when an approved proposal cannot be found."""


class DeliveryConflict(Exception):
    """Raised when the delivery key conflicts with a prior request."""


class DeliveryNotApproved(Exception):
    """Raised until an owner-approved proposal exists."""


def _request_hash(
    proposal_id: str,
    title: str,
    description: str | None,
    assigned_to: str,
    due_date: str | None,
) -> str:
    request = json.dumps({
        "proposal_id": proposal_id,
        "title": title,
        "description": description,
        "assigned_to": assigned_to,
        "due_date": due_date,
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(request.encode("utf-8")).hexdigest()


async def execute_delivery(
    db: Session,
    proposal_id: str,
    assigned_to: str,
    due_date: str | None,
    idempotency_key: str,
    correlation_id: str,
    manager_id: str,
    client: FieldForceClient | None = None,
) -> dict[str, Any]:
    key = idempotency_key.strip()
    if not key:
        raise ValueError("idempotency_key must not be empty")
    proposal = db.get(ProposalRecord, proposal_id)
    if proposal is None:
        raise DeliveryNotFound("Proposal not found")
    request_hash = _request_hash(
        proposal_id,
        proposal.title,
        proposal.summary,
        assigned_to,
        due_date,
    )
    existing = db.query(IdempotencyRecord).filter_by(
        capability_name=CAPABILITY_NAME,
        idempotency_key=key,
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise DeliveryConflict("Idempotency key was already used for another delivery")
        if existing.response_payload is None:
            raise DeliveryConflict("The original delivery is still processing")
        return existing.response_payload

    approval = db.get(ApprovalRequest, proposal.approval_id) if proposal.approval_id else None
    if (
        proposal.status != "APPROVED"
        or approval is None
        or approval.action != "proposal_delivery"
        or approval.status != "APPROVED"
        or not approval.decided_by
    ):
        raise DeliveryNotApproved("An owner-approved proposal delivery gate is required")
    lead = db.get(LeadRecordRow, proposal.lead_id)
    if lead is None or lead.do_not_contact or lead.status != "PROPOSAL_APPROVED":
        raise DeliveryNotApproved("The lead is not in an approved delivery state")

    title = proposal.title
    description = proposal.summary

    task_id = str(uuid.uuid4())
    delivery_task = TaskRecord(
        id=task_id,
        correlation_id=correlation_id,
        objective=f"Deliver approved proposal {proposal_id} via Field Force Management",
        status="EXECUTING",
        result={
            "proposal_id": proposal_id,
            "title": title,
            "description": description,
            "assigned_to": assigned_to,
            "due_date": due_date,
        },
    )
    idempotency = IdempotencyRecord(
        capability_name=CAPABILITY_NAME,
        idempotency_key=key,
        request_hash=request_hash,
        task_id=task_id,
    )
    db.add_all([delivery_task, idempotency])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(IdempotencyRecord).filter_by(
            capability_name=CAPABILITY_NAME,
            idempotency_key=key,
        ).first()
        if existing and existing.request_hash == request_hash and existing.response_payload:
            return existing.response_payload
        if existing and existing.request_hash != request_hash:
            raise DeliveryConflict("Idempotency key was already used for another delivery")
        raise

    field_force_client = client or get_field_force_client()
    try:
        capability_result = await field_force_client.create_and_verify_task(
            title=title,
            description=description,
            assigned_to=assigned_to,
            due_date=due_date,
            idempotency_key=key,
            correlation_id=correlation_id,
        )
        response: dict[str, Any] = {
            "task_id": task_id,
            "correlation_id": correlation_id,
            "status": "COMPLETED",
            "proposal_id": proposal_id,
            "capability": CAPABILITY_NAME,
            "capability_result": capability_result,
        }
        delivery_task.status = "COMPLETED"
        delivery_task.result = response
        idempotency.response_payload = response
        db.add(DeliveryRecord(
            task_id=task_id,
            proposal_id=proposal_id,
            customer_company=lead.company,
            summary=f"Verified Field Force task {capability_result['task_id']} created.",
            evidence=capability_result,
            status="DELIVERED",
        ))
        db.add(AuditLog(
            task_id=task_id,
            correlation_id=correlation_id,
            agent_id=manager_id,
            capability_name=CAPABILITY_NAME,
            action="execute_and_verify",
            input_payload={
                "proposal_id": proposal_id,
                "assigned_to": assigned_to,
                "title": title,
            },
            output_payload=capability_result,
            status="COMPLETED",
        ))
        seal_task_to_block(
            db=db,
            task_id=task_id,
            capability_name=CAPABILITY_NAME,
            action="execute_and_verify",
            payload={
                "status": "DELIVERED",
                "proposal_id": proposal_id,
                "assigned_to": assigned_to,
                "correlation_id": correlation_id,
            },
            sealed_by=manager_id,
            commit=False,
        )
        db.commit()
        return response
    except (FieldForceNotConfigured, FieldForceExecutionError) as error:
        db.rollback()
        delivery_task = db.get(TaskRecord, task_id)
        idempotency = db.query(IdempotencyRecord).filter_by(
            capability_name=CAPABILITY_NAME,
            idempotency_key=key,
        ).first()
        failure = {
            "task_id": task_id,
            "correlation_id": correlation_id,
            "status": "FAILED",
            "proposal_id": proposal_id,
            "capability": CAPABILITY_NAME,
            "error": str(error),
            "external_action_result": "unknown_or_rejected",
        }
        if delivery_task is not None:
            delivery_task.status = "FAILED"
            delivery_task.result = failure
            db.add(AuditLog(
                task_id=task_id,
                correlation_id=correlation_id,
                agent_id=manager_id,
                capability_name=CAPABILITY_NAME,
                action="execute_and_verify",
                input_payload={"proposal_id": proposal_id, "assigned_to": assigned_to},
                output_payload={"error_type": type(error).__name__},
                status="FAILED",
            ))
        if idempotency is not None:
            idempotency.response_payload = failure
        db.commit()
        return failure