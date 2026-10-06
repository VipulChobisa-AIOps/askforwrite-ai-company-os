"""Manager workflow coordinating discovery, research, and owner gates."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.discovery import RESEARCH_THRESHOLD
from app.db.models import AuditLog, IdempotencyRecord, TaskRecord
from app.services.approvals import request_approval
from app.services.discovery import execute_discovery
from app.services.research import execute_research
from app.security.trust_chain import seal_task_to_block

CAPABILITY_NAME = "manager_workflow"


class ManagerConflict(Exception):
    """Raised when a manager idempotency key conflicts with its original task."""


def _request_hash(objective: str, limit: int) -> str:
    request = json.dumps(
        {"objective": objective.strip(), "limit": limit},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(request.encode("utf-8")).hexdigest()


def _cached_response(record: IdempotencyRecord, request_hash: str) -> dict[str, object]:
    if record.request_hash != request_hash:
        raise ManagerConflict("Idempotency key was already used for another task")
    if record.response_payload is None:
        raise ManagerConflict("The original Manager task is still running")
    return record.response_payload


def _audit_transition(
    db: Session,
    task: TaskRecord,
    status: str,
    correlation_id: str,
    manager_id: str,
    detail: dict[str, object],
) -> None:
    task.status = status
    task.updated_at = datetime.now(UTC)
    db.add(AuditLog(
        task_id=task.id,
        correlation_id=correlation_id,
        agent_id=manager_id,
        capability_name=CAPABILITY_NAME,
        action=f"manager_{status.casefold()}",
        input_payload={"objective": task.objective},
        output_payload=detail,
        status=status,
    ))
    db.commit()


def execute_manager_workflow(
    db: Session,
    objective: str,
    limit: int,
    idempotency_key: str,
    correlation_id: str,
    manager_id: str,
) -> dict[str, object]:
    key = idempotency_key.strip()
    normalized_objective = objective.strip()
    if not key:
        raise ValueError("idempotency_key must not be empty")
    if not normalized_objective:
        raise ValueError("objective must not be empty")

    request_hash = _request_hash(normalized_objective, limit)
    existing = db.query(IdempotencyRecord).filter_by(
        capability_name=CAPABILITY_NAME,
        idempotency_key=key,
    ).first()
    if existing:
        return _cached_response(existing, request_hash)

    task_id = str(uuid4())
    manager_task = TaskRecord(
        id=task_id,
        correlation_id=correlation_id,
        objective=normalized_objective,
        status="PLANNING",
    )
    idempotency = IdempotencyRecord(
        capability_name=CAPABILITY_NAME,
        idempotency_key=key,
        request_hash=request_hash,
        task_id=task_id,
    )
    db.add_all([manager_task, idempotency])
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(IdempotencyRecord).filter_by(
            capability_name=CAPABILITY_NAME,
            idempotency_key=key,
        ).first()
        if existing:
            return _cached_response(existing, request_hash)
        raise

    db.add(AuditLog(
        task_id=task_id,
        correlation_id=correlation_id,
        agent_id=manager_id,
        capability_name=CAPABILITY_NAME,
        action="manager_plan_created",
        input_payload={"objective": normalized_objective},
        output_payload={
            "steps": ["discover", "research_qualified_leads", "request_owner_approval"],
        },
        status="PLANNING",
    ))
    db.commit()
    _audit_transition(db, manager_task, "EXECUTING", correlation_id, manager_id, {
        "stage": "discovery_and_research",
    })

    try:
        child_key = hashlib.sha256(f"manager-discovery:{key}".encode("utf-8")).hexdigest()
        discovery = execute_discovery(
            db=db,
            objective=normalized_objective,
            limit=limit,
            idempotency_key=child_key,
            correlation_id=correlation_id,
            agent_id=manager_id,
        )
        qualified_leads = [
            lead for lead in discovery["leads"]
            if not lead["do_not_contact"] and lead["fit_score"] >= RESEARCH_THRESHOLD
        ]
        research_ids: list[str] = []
        approval_ids: list[str] = []
        for lead in qualified_leads:
            lead_id = str(lead["lead_id"])
            suffix = hashlib.sha256(f"{key}:{lead_id}".encode("utf-8")).hexdigest()
            research = execute_research(
                db=db,
                lead_id=lead_id,
                idempotency_key=f"{suffix}:research",
                requested_by="research_agent",
                correlation_id=correlation_id,
            )
            research_ids.append(str(research["research_id"]))
            approval = request_approval(
                db=db,
                task_id=str(discovery["task_id"]),
                lead_id=lead_id,
                action="external_sales_outreach",
                detail={
                    "company": lead["company"],
                    "fit_score": lead["fit_score"],
                    "product_match": lead["product_match"],
                    "research_id": research["research_id"],
                },
                idempotency_key=f"{suffix}:approval",
                requested_by=manager_id,
                correlation_id=correlation_id,
            )
            approval_ids.append(str(approval["approval_id"]))

        self_status = "HUMAN_APPROVAL_REQUIRED" if approval_ids else "COMPLETED"
        response: dict[str, object] = {
            "task_id": task_id,
            "correlation_id": correlation_id,
            "status": self_status,
            "discovery_task_id": discovery["task_id"],
            "qualified_lead_count": len(qualified_leads),
            "research_ids": research_ids,
            "approval_ids": approval_ids,
            "outreach_performed": False,
        }
        manager_task.result = response
        idempotency.response_payload = response
        _audit_transition(db, manager_task, "VERIFYING", correlation_id, manager_id, {
            "qualified_lead_count": len(qualified_leads),
            "research_count": len(research_ids),
            "approval_count": len(approval_ids),
        })
        manager_task.result = response
        idempotency.response_payload = response
        _audit_transition(db, manager_task, self_status, correlation_id, manager_id, {
            "outreach_performed": False,
            "approval_ids": approval_ids,
        })
        seal_task_to_block(
            db=db,
            task_id=task_id,
            capability_name=CAPABILITY_NAME,
            action=self_status,
            payload={
                "status": self_status,
                "qualified_lead_count": len(qualified_leads),
                "research_count": len(research_ids),
                "approval_count": len(approval_ids),
                "correlation_id": correlation_id,
            },
            sealed_by=manager_id,
            commit=True,
        )
        return response
    except Exception as error:
        db.rollback()
        manager_task = db.get(TaskRecord, task_id)
        idempotency = db.query(IdempotencyRecord).filter_by(
            capability_name=CAPABILITY_NAME,
            idempotency_key=key,
        ).first()
        failure: dict[str, object] = {
            "task_id": task_id,
            "correlation_id": correlation_id,
            "status": "FAILED",
            "error_type": type(error).__name__,
            "outreach_performed": False,
        }
        if manager_task is not None:
            manager_task.result = failure
            _audit_transition(db, manager_task, "FAILED", correlation_id, manager_id, {
                "error_type": type(error).__name__,
            })
        if idempotency is not None:
            idempotency.response_payload = failure
            db.commit()
        return failure