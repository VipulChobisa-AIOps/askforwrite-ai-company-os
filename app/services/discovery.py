"""Transactional persistence for the discovery capability with multi-tenant quota and deduplication."""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.discovery import normalize_domain, run_discovery
from app.agents.sources import SourceProvider
from app.db.models import AuditLog, IdempotencyRecord, LeadRecordRow, OrganizationRecord, TaskRecord
from app.security.trust_chain import seal_task_to_block

CAPABILITY_NAME = "customer_discovery"


class IdempotencyConflict(Exception):
    """Raised when a key is reused for a different request body."""


def _request_hash(objective: str, limit: int, org_id: str | None = None) -> str:
    payload: dict[str, object] = {"objective": objective.strip(), "limit": limit}
    if org_id:
        payload["org_id"] = org_id.strip()
    canonical_request = json.dumps(
        payload,
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
    org_id: str | None = None,
    provider: SourceProvider | None = None,
) -> dict[str, object]:
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise ValueError("idempotency_key must not be empty")

    normalized_objective = objective.strip()
    request_hash = _request_hash(normalized_objective, limit, org_id=org_id)
    existing = db.query(IdempotencyRecord).filter_by(
        capability_name=CAPABILITY_NAME,
        idempotency_key=normalized_key,
    ).first()
    if existing:
        return _replay_or_conflict(existing, request_hash)

    # Multi-tenant quota validation
    org: OrganizationRecord | None = None
    if org_id:
        org = db.get(OrganizationRecord, org_id)
        if not org:
            raise ValueError(f"Organization '{org_id}' not found")
        if not org.is_active:
            raise ValueError(f"Organization '{org.name}' is inactive")
        if org.lead_credits_used >= org.lead_credits_limit:
            raise ValueError(
                f"Lead discovery quota reached ({org.lead_credits_used}/{org.lead_credits_limit} credits used). "
                "Please upgrade your plan to discover more prospects."
            )

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
        result = run_discovery(normalized_objective, provider=provider, limit=limit)

        new_leads_count = 0
        persisted_leads_dicts = []

        for lead in result.leads:
            domain = lead.domain or normalize_domain(lead.website)
            
            # Deduplicate by org_id and domain if org_id is provided
            existing_lead = None
            if org_id and domain:
                existing_lead = db.query(LeadRecordRow).filter(
                    LeadRecordRow.org_id == org_id,
                    LeadRecordRow.domain == domain,
                ).first()

            if existing_lead:
                # Update existing lead without consuming extra credit
                existing_lead.observed_signals = list(lead.observed_signals)
                existing_lead.sources = [dict(s) for s in lead.sources]
                existing_lead.fit_score = lead.fit_score
                existing_lead.confidence = lead.confidence
                existing_lead.last_checked = datetime.now(UTC)
                db.add(existing_lead)
                persisted_leads_dicts.append({
                    **lead.to_dict(),
                    "lead_id": existing_lead.id,
                    "is_duplicate": True,
                })
            else:
                # If credit limit would be exceeded mid-batch, skip inserting more
                if org and (org.lead_credits_used + new_leads_count >= org.lead_credits_limit):
                    continue

                lead_row = LeadRecordRow(
                    id=lead.lead_id,
                    org_id=org_id,
                    domain=domain,
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
                )
                db.merge(lead_row)
                new_leads_count += 1
                persisted_leads_dicts.append({
                    **lead.to_dict(),
                    "is_duplicate": False,
                })

        # Charge credits for newly discovered leads
        if org and new_leads_count > 0:
            org.lead_credits_used += new_leads_count
            db.add(org)

        response: dict[str, object] = {
            "task_id": task_id,
            "correlation_id": correlation_id,
            "status": "COMPLETED",
            "objective": result.objective,
            "data_mode": result.data_mode,
            "outreach_performed": result.outreach_performed,
            "persistence": db.get_bind().dialect.name,
            "leads": persisted_leads_dicts,
            "new_leads_count": new_leads_count,
        }
        if org:
            response["org_id"] = org.id
            response["credits_used"] = org.lead_credits_used
            response["credits_limit"] = org.lead_credits_limit
            response["credits_remaining"] = max(0, org.lead_credits_limit - org.lead_credits_used)

        db.add(TaskRecord(
            id=task_id,
            correlation_id=correlation_id,
            objective=normalized_objective,
            status="COMPLETED",
            result=response,
        ))

        db.add(AuditLog(
            task_id=task_id,
            correlation_id=correlation_id,
            agent_id=agent_id,
            capability_name=CAPABILITY_NAME,
            action="execute",
            input_payload={"objective": normalized_objective, "limit": limit, "org_id": org_id},
            output_payload={
                "lead_count": len(persisted_leads_dicts),
                "new_leads_count": new_leads_count,
                "lead_ids": [lead["lead_id"] for lead in persisted_leads_dicts],
                "data_mode": result.data_mode,
                "outreach_performed": False,
                "org_id": org_id,
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
                "lead_count": len(persisted_leads_dicts),
                "new_leads_count": new_leads_count,
                "correlation_id": correlation_id,
                "data_mode": result.data_mode,
                "org_id": org_id,
            },
            sealed_by=agent_id or "discovery_agent",
            commit=False,
        )
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise