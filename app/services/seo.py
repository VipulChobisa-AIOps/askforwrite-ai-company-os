"""SEO Content Automation Copilot integration."""

import hashlib
import json
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AuditLog, IdempotencyRecord, SeoDraftRecord, TaskRecord
from app.security.trust_chain import seal_task_to_block
from app.services.approvals import request_approval

CAPABILITY_NAME = "seo_blog_copilot"


class SeoConflict(Exception):
    """Raised when an SEO draft fails uniqueness or idempotency constraints."""


def execute_seo_draft(
    db: Session,
    target_network: str,
    keywords: list[str],
    idempotency_key: str,
    correlation_id: str,
    agent_id: str,
) -> dict:
    request_hash = hashlib.sha256(json.dumps({"network": target_network, "keywords": keywords}, sort_keys=True).encode()).hexdigest()

    existing = db.query(IdempotencyRecord).filter_by(
        capability_name=CAPABILITY_NAME,
        idempotency_key=idempotency_key,
    ).first()

    if existing:
        if existing.request_hash != request_hash:
            raise SeoConflict("Idempotency key reused with different request payload")
        return existing.response_payload

    task_id = str(uuid.uuid4())
    task = TaskRecord(
        id=task_id,
        correlation_id=correlation_id,
        objective=f"SEO Draft for {target_network}",
        status="COMPLETED",
    )
    db.add(task)

    # Simulate drafting content
    content_draft = f"Draft content for {target_network} targeting keywords: {', '.join(keywords)}..."
    
    draft = SeoDraftRecord(
        task_id=task_id,
        target_network=target_network,
        keywords=keywords,
        content=content_draft,
        status="DRAFT"
    )
    db.add(draft)
    db.flush()  # flush to get draft.id

    # Request Owner Approval for LIVE_PUBLISHED
    approval = request_approval(
        db=db,
        task_id=task_id,
        lead_id=None,
        action="live_publishing",
        detail={"seo_draft_id": draft.id, "network": target_network},
        idempotency_key=f"approval_seo_{draft.id}",
        requested_by=agent_id,
        correlation_id=correlation_id
    )

    draft.approval_id = approval["approval_id"]
    draft.status = "PENDING_APPROVAL"

    audit = AuditLog(
        task_id=task_id,
        correlation_id=correlation_id,
        agent_id=agent_id,
        capability_name=CAPABILITY_NAME,
        action="generate_draft",
        input_payload={"network": target_network, "keywords": keywords},
        output_payload={"status": draft.status, "approval_id": approval["approval_id"]},
        status="COMPLETED"
    )
    db.add(audit)

    result = {
        "status": draft.status,
        "draft_id": draft.id,
        "approval_id": approval["approval_id"]
    }

    idemp = IdempotencyRecord(
        capability_name=CAPABILITY_NAME,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        task_id=task_id,
        response_payload=result,
    )
    db.add(idemp)
    
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise SeoConflict("Idempotency conflict") from exc

    seal_task_to_block(
        db=db,
        task_id=task_id,
        capability_name=CAPABILITY_NAME,
        action="generate_draft",
        payload=result,
        sealed_by=agent_id,
    )

    return result
