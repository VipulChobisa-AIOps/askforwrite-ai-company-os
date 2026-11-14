"""Durable 18-field Execution Evidence Framework with secret redaction and output-origin tracking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ExecutionEvidenceRecord
from app.services.execution_guard import redact_secrets

OUTPUT_ORIGINS = (
    "LIVE_PROVIDER_VERIFIED",
    "LOCAL_DETERMINISTIC",
    "SANDBOX_VERIFIED",
    "HUMAN_ASSISTED",
    "SIMULATED_SYNTHETIC",
    "BLOCKED",
)


def derive_output_origin(
    *,
    status: str,
    execution_mode: str,
    provider_request_id: str | None,
    fallback_used: bool,
    uses_external_provider: bool,
) -> str:
    """Compute honest output-origin label — NEVER label fallback or simulated results as live."""
    clean_status = (status or "").upper()
    clean_mode = (execution_mode or "SIMULATION").upper()
    if clean_status == "BLOCKED":
        return "BLOCKED"
    if clean_mode == "SIMULATION" or fallback_used:
        return "SIMULATED_SYNTHETIC"
    if clean_mode == "SANDBOX":
        return "SANDBOX_VERIFIED"
    if not uses_external_provider:
        return "LOCAL_DETERMINISTIC"
    if clean_mode == "PRODUCTION" and provider_request_id and not fallback_used:
        return "LIVE_PROVIDER_VERIFIED"
    return "SIMULATED_SYNTHETIC"


def record_execution_evidence(
    db: Session,
    *,
    execution_id: str | None = None,
    tenant_id: str,
    workflow_id: str | None = None,
    agent_id: str,
    connector_id: str | None = None,
    execution_mode: str,
    input_payload: dict[str, Any] | str | None = None,
    output_payload: dict[str, Any] | str | None = None,
    input_reference: str | None = None,
    output_reference: str | None = None,
    provider_request_id: str | None = None,
    fallback_used: bool = False,
    approval_id: str | None = None,
    status: str = "COMPLETED",
    failure_reason: str | None = None,
    credits_consumed: int = 0,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    evidence_reference: str | None = None,
    version: str = "1.0.0",
    uses_external_provider: bool = False,
    output_origin: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist an 18-field ExecutionEvidenceRecord with zero raw secret leakage."""
    exec_id = execution_id or f"exec-{uuid.uuid4().hex[:16]}"
    now = datetime.now(UTC)
    started = started_at or now
    completed = completed_at or now

    origin = output_origin or derive_output_origin(
        status=status,
        execution_mode=execution_mode,
        provider_request_id=provider_request_id,
        fallback_used=fallback_used,
        uses_external_provider=uses_external_provider,
    )

    in_ref = input_reference or f"evidence://inputs/{tenant_id}/{exec_id}"
    out_ref = output_reference or f"evidence://outputs/{tenant_id}/{exec_id}"
    ev_ref = evidence_reference or f"evidence://ledger/{tenant_id}/{exec_id}"

    safe_meta = redact_secrets(
        {
            "input_preview": input_payload if isinstance(input_payload, dict) else {"value": str(input_payload or "")[:300]},
            "output_preview": output_payload if isinstance(output_payload, dict) else {"value": str(output_payload or "")[:500]},
            **(metadata or {}),
        }
    )

    rec = db.get(ExecutionEvidenceRecord, exec_id)
    if rec is None:
        rec = ExecutionEvidenceRecord(
            execution_id=exec_id,
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            agent_id=agent_id,
            connector_id=connector_id,
            execution_mode=execution_mode.upper(),
            input_reference=in_ref,
            output_reference=out_ref,
            provider_request_id=provider_request_id,
            fallback_used=bool(fallback_used),
            approval_id=approval_id,
            status=status.upper(),
            failure_reason=failure_reason,
            credits_consumed=int(credits_consumed),
            started_at=started,
            completed_at=completed,
            evidence_reference=ev_ref,
            version=version,
            output_origin=origin,
            metadata_json=safe_meta,
        )
        db.add(rec)
    else:
        rec.status = status.upper()
        rec.completed_at = completed
        rec.failure_reason = failure_reason
        rec.credits_consumed = int(credits_consumed)
        rec.provider_request_id = provider_request_id or rec.provider_request_id
        rec.approval_id = approval_id or rec.approval_id
        rec.fallback_used = bool(fallback_used)
        rec.output_origin = origin
        rec.metadata_json = safe_meta

    db.flush()
    return serialize_evidence(rec)


def serialize_evidence(rec: ExecutionEvidenceRecord) -> dict[str, Any]:
    """Serialize all 18 required ExecutionEvidenceRecord attributes plus origin metadata."""
    return {
        "execution_id": rec.execution_id,
        "tenant_id": rec.tenant_id,
        "workflow_id": rec.workflow_id,
        "agent_id": rec.agent_id,
        "connector_id": rec.connector_id,
        "execution_mode": rec.execution_mode,
        "input_reference": rec.input_reference,
        "output_reference": rec.output_reference,
        "provider_request_id": rec.provider_request_id,
        "fallback_used": rec.fallback_used,
        "approval_id": rec.approval_id,
        "status": rec.status,
        "failure_reason": rec.failure_reason,
        "credits_consumed": rec.credits_consumed,
        "started_at": rec.started_at.isoformat() if rec.started_at else None,
        "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
        "evidence_reference": rec.evidence_reference,
        "version": rec.version,
        "output_origin": rec.output_origin,
        "metadata": redact_secrets(rec.metadata_json or {}),
    }


def list_execution_evidence(
    db: Session,
    *,
    tenant_id: str | None = None,
    agent_id: str | None = None,
    workflow_id: str | None = None,
    execution_mode: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query ExecutionEvidenceRecord ledger scoped cleanly by tenant and optional filters."""
    q = db.query(ExecutionEvidenceRecord)
    if tenant_id:
        q = q.filter(ExecutionEvidenceRecord.tenant_id == tenant_id)
    if agent_id:
        q = q.filter(ExecutionEvidenceRecord.agent_id == agent_id)
    if workflow_id:
        q = q.filter(ExecutionEvidenceRecord.workflow_id == workflow_id)
    if execution_mode:
        q = q.filter(ExecutionEvidenceRecord.execution_mode == execution_mode.upper())
    if status:
        q = q.filter(ExecutionEvidenceRecord.status == status.upper())
    rows = q.order_by(ExecutionEvidenceRecord.started_at.desc()).limit(max(1, min(limit, 200))).all()
    return [serialize_evidence(r) for r in rows]


def get_execution_evidence(
    db: Session,
    execution_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    """Retrieve a single ExecutionEvidenceRecord enforcing tenant isolation if tenant_id provided."""
    rec = db.get(ExecutionEvidenceRecord, execution_id)
    if not rec:
        return None
    if tenant_id and rec.tenant_id != tenant_id:
        return None
    return serialize_evidence(rec)

