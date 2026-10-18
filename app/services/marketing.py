"""Node Marketing Suite integration."""

import hashlib
import json
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    IdempotencyRecord,
    MarketingCampaignRecord,
    TaskRecord,
)
from app.security.trust_chain import seal_task_to_block
from app.services.approvals import request_approval

CAPABILITY_NAME = "marketing_campaign_suite"


class MarketingConflict(Exception):
    """Raised when a marketing campaign fails uniqueness or idempotency constraints."""


def execute_marketing_campaign(
    db: Session,
    campaign_type: str,
    target_audience: str,
    idempotency_key: str,
    correlation_id: str,
    agent_id: str,
) -> dict:
    request_hash = hashlib.sha256(json.dumps({"type": campaign_type, "audience": target_audience}, sort_keys=True).encode()).hexdigest()

    existing = db.query(IdempotencyRecord).filter_by(
        capability_name=CAPABILITY_NAME,
        idempotency_key=idempotency_key,
    ).first()

    if existing:
        if existing.request_hash != request_hash:
            raise MarketingConflict("Idempotency key reused with different request payload")
        return existing.response_payload

    task_id = str(uuid.uuid4())
    task = TaskRecord(
        id=task_id,
        correlation_id=correlation_id,
        objective=f"Marketing Campaign: {campaign_type}",
        status="COMPLETED",
    )
    db.add(task)

    # Generate ad copy via LLM with deterministic fallback
    from app.agents.llm_client import generate

    ad_copy = {
        "instagram": generate(
            prompt=f"Generate an engaging Instagram caption for campaign '{campaign_type}' targeting {target_audience}",
            system_instruction="You are an expert B2B social media growth copywriter.",
            fallback_text=f"Insta ad for {target_audience}",
        ),
        "facebook": generate(
            prompt=f"Generate a high-converting Facebook post for campaign '{campaign_type}' targeting {target_audience}",
            system_instruction="You are an expert B2B social media growth copywriter.",
            fallback_text=f"FB ad for {target_audience}",
        ),
        "twitter": generate(
            prompt=f"Generate a viral Twitter/X post for campaign '{campaign_type}' targeting {target_audience}",
            system_instruction="You are an expert B2B social media growth copywriter.",
            fallback_text=f"Tweet for {target_audience}",
        ),
        "linkedin": generate(
            prompt=f"Generate a professional LinkedIn article excerpt for campaign '{campaign_type}' targeting {target_audience}",
            system_instruction="You are an expert B2B social media growth copywriter.",
            fallback_text=f"LinkedIn post for {target_audience}",
        ),
    }
    
    campaign = MarketingCampaignRecord(
        task_id=task_id,
        campaign_type=campaign_type,
        target_audience=target_audience,
        ad_copy=ad_copy,
        status="DRAFT"
    )
    db.add(campaign)
    db.flush()  # flush to get campaign.id

    # Request Owner Approval for Dispatch
    approval = request_approval(
        db=db,
        task_id=task_id,
        lead_id=None,
        action="external_messaging",
        detail={"campaign_id": campaign.id, "type": campaign_type},
        idempotency_key=f"approval_marketing_{campaign.id}",
        requested_by=agent_id,
        correlation_id=correlation_id
    )

    campaign.approval_id = approval["approval_id"]
    campaign.status = "PENDING_APPROVAL"

    audit = AuditLog(
        task_id=task_id,
        correlation_id=correlation_id,
        agent_id=agent_id,
        capability_name=CAPABILITY_NAME,
        action="generate_campaign",
        input_payload={"type": campaign_type, "audience": target_audience},
        output_payload={"status": campaign.status, "approval_id": approval["approval_id"]},
        status="COMPLETED"
    )
    db.add(audit)

    result = {
        "status": campaign.status,
        "campaign_id": campaign.id,
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
        raise MarketingConflict("Idempotency conflict") from exc

    seal_task_to_block(
        db=db,
        task_id=task_id,
        capability_name=CAPABILITY_NAME,
        action="generate_campaign",
        payload=result,
        sealed_by=agent_id,
    )

    return result
