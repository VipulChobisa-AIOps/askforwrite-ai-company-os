"""Transactional persistence for the offline discovery capability."""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.discovery import run_discovery
from app.db.models import AuditLog, IdempotencyRecord, LeadRecordRow, TaskRecord
from app.security.trust_chain import seal_task_to_block

CAPABILITY_NAME = "customer_discovery"


class IdempotencyConflict(Exception):
    """Raised when a key is reused for a different request body."""


def _request_hash(objective: str, limit: int) -> str:
    canonical_request = json.dumps(
        {"objective": objective.strip(), "limit": limit},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()


def _replay_or_conflict(
    record: IdempotencyRecord,
    request_hash: str,
) -> dict[str, object]:
    if record.request_hash != request_hash:
        raise IdempotencyConflict("Idempotency key was already used for another request")
    if record.response_payload is None:
        raise IdempotencyConflict("The original request is still being processed")
    return record.response_payload


def execute_discovery(
    db: Session,
    objective: str,
    limit: int,
    idempotency_key: str,
    correlation_id: str,
    agent_id: str | None = None,
) -> dict[str, object]:
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise ValueError("idempotency_key must not be empty")

    normalized_objective = objective.strip()
    request_hash = _request_hash(normalized_objective, limit)
    existing = db.query(IdempotencyRecord).filter_by(
        capability_name=CAPABILITY_NAME,
        idempotency_key=normalized_key,
    ).first()
    if existing:
        return _replay_or_conflict(existing, request_hash)

    task_id = str(uuid.uuid4())
    idempotency_record = IdempotencyRecord(
        capability_name=CAPABILITY_NAME,
        idempotency_key=normalized_key,
        request_hash=request_hash,
        task_id=task_id,
    )
    db.add(idempotency_record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(IdempotencyRecord).filter_by(
            capability_name=CAPABILITY_NAME,
            idempotency_key=normalized_key,
        ).first()
        if existing:
            return _replay_or_conflict(existing, request_hash)
        raise

    try:
        result = run_discovery(normalized_objective, limit=limit)
        response: dict[str, object] = {
            "task_id": task_id,
            "correlation_id": correlation_id,
            "status": "COMPLETED",
            **result.to_dict(),
            "persistence": db.get_bind().dialect.name,
        }
        db.add(TaskRecord(
            id=task_id,
            correlation_id=correlation_id,
            objective=normalized_objective,
            status="COMPLETED",
            result=response,
        ))

        for lead in result.leads:
            db.merge(LeadRecordRow(
                id=lead.lead_id,
                task_id=task_id,
                company=lead.company,
                website=lead.website,
                industry=lead.industry,
                geography=lead.geography,
                observed_signals=list(lead.observed_signals),
                sources=[dict(source) for source in lead.sources],
                product_match=lead.product_match,
                fit_score=lead.fit_score,
                confidence=lead.confidence,
                public_contact_channel=lead.public_contact_channel,
                recommended_next_step=lead.recommended_next_step,
                do_not_contact=lead.do_not_contact,
                status=lead.status,
                last_checked=datetime.now(UTC),
            ))

        db.add(AuditLog(
            task_id=task_id,
            correlation_id=correlation_id,
            agent_id=agent_id,
            capability_name=CAPABILITY_NAME,
            action="execute",
            input_payload={"objective": normalized_objective, "limit": limit},
            output_payload={
                "lead_count": len(result.leads),
                "lead_ids": [lead.lead_id for lead in result.leads],
                "data_mode": result.data_mode,
                "outreach_performed": False,
            },
            status="COMPLETED",
        ))
        idempotency_record.response_payload = response
        seal_task_to_block(
            db=db,
            task_id=task_id,
            capability_name=CAPABILITY_NAME,
            action="execute",
            payload={
                "status": "COMPLETED",
                "lead_count": len(result.leads),
                "correlation_id": correlation_id,
                "data_mode": result.data_mode,
            },
            sealed_by=agent_id or "discovery_agent",
            commit=False,
        )
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise