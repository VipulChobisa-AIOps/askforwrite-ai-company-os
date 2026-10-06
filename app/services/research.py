"""Persistence service for source-grounded Research Agent outputs."""

import hashlib
import json
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.research import build_research
from app.db.models import AuditLog, LeadRecordRow, ResearchRecord


class ResearchConflict(Exception):
    """Raised when an idempotency key is reused for changed lead evidence."""


class ResearchNotFound(Exception):
    """Raised when a lead does not exist."""


def execute_research(
    db: Session,
    lead_id: str,
    idempotency_key: str,
    requested_by: str,
    correlation_id: str,
) -> dict[str, object]:
    key = idempotency_key.strip()
    if not key:
        raise ValueError("idempotency_key must not be empty")
    lead = db.get(LeadRecordRow, lead_id)
    if lead is None:
        raise ResearchNotFound("Lead not found")
    if lead.do_not_contact or lead.status == "DO_NOT_CONTACT":
        raise ValueError("do-not-contact leads cannot enter Research")

    draft = build_research(lead.company, lead.sources or [])
    source_hash = hashlib.sha256(
        json.dumps(draft.sources, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    existing = db.query(ResearchRecord).filter_by(
        lead_id=lead_id,
        idempotency_key=key,
    ).first()
    if existing:
        if existing.source_hash != source_hash:
            raise ResearchConflict("Idempotency key was already used for different evidence")
        return _research_payload(existing)

    record = ResearchRecord(
        id=str(uuid4()),
        lead_id=lead_id,
        task_id=lead.task_id,
        idempotency_key=key,
        source_hash=source_hash,
        synthesis=draft.synthesis,
        analysis=draft.analysis,
        sources=draft.sources,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(ResearchRecord).filter_by(
            lead_id=lead_id,
            idempotency_key=key,
        ).first()
        if existing:
            if existing.source_hash != source_hash:
                raise ResearchConflict("Idempotency key was already used for different evidence")
            return _research_payload(existing)
        raise

    if lead.status == "DISCOVERED":
        lead.status = "RESEARCHED"
    db.add(AuditLog(
        task_id=lead.task_id,
        correlation_id=correlation_id,
        agent_id=requested_by,
        capability_name="research_agent",
        action="synthesize_evidence",
        input_payload={"lead_id": lead_id, "source_hash": source_hash},
        output_payload={
            "research_id": record.id,
            "source_count": draft.analysis["source_count"],
            "signal_count": draft.analysis["signal_count"],
            "external_research_performed": False,
        },
        status="COMPLETED",
    ))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _research_payload(record)


def _research_payload(record: ResearchRecord) -> dict[str, object]:
    return {
        "research_id": record.id,
        "lead_id": record.lead_id,
        "task_id": record.task_id,
        "synthesis": record.synthesis,
        "analysis": record.analysis,
        "sources": record.sources,
        "external_research_performed": False,
    }