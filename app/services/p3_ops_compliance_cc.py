"""P3 Multi-Tenant Ops Readiness, GDPR/DPDP Compliance, Founder Control Centre & 12-Step Acceptance."""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import (
    ApprovalRequest,
    AuditLog,
    BusinessProfileRecord,
    ConnectorStateRecord,
    ExecutionEvidenceRecord,
    InvoiceRecord,
    OrganizationRecord,
    P2ProspectDossierRecord,
    P3AcceptanceStepRecord,
    P3ComplianceRequestRecord,
    P3CustomerAccountRecord,
    P3GrowthOpportunityRecord,
    P3ImprovementItemRecord,
    P3OnboardingWorkflowRecord,
    P3OperationalIncidentRecord,
    P3ServiceDeliveryRecord,
    P3SubscriptionEventRecord,
    P3SupportTicketRecord,
    P3UnitEconomicsEntryRecord,
    TenantSubscriptionRecord,
    UserRecord,
    WorkflowDefinitionRecord,
    WorkflowRunRecord,
)
from app.services.execution_guard import redact_secrets
from app.services.p3_customer_success import ensure_customer_account
from app.services.p3_revenue_growth import get_subscription_reliability_summary

MAX_CONCURRENT_RUNS_PER_ORG = int(os.getenv("P3_MAX_CONCURRENT_RUNS_PER_ORG", "5"))
DEFAULT_WORKFLOW_TIMEOUT_SECONDS = int(os.getenv("P3_WORKFLOW_TIMEOUT_SECONDS", "900"))
DB_LATENCY_DEGRADED_MS = float(os.getenv("P3_DB_LATENCY_DEGRADED_MS", "500.0"))

P3_ACCEPTANCE_BLUEPRINT: tuple[tuple[int, str, str, str], ...] = (
    (
        1,
        "p3_step_01_customer_profile_created",
        "Customer Profile & Lifecycle Created",
        "Create real non-sandbox P3 customer account linked to organization, owner, package entitlements, and goals.",
    ),
    (
        2,
        "p3_step_02_onboarding_completed",
        "Onboarding Workflow & Training Completed",
        "Complete all required onboarding tasks, credentials, training, and blockers for purchased service SKU.",
    ),
    (
        3,
        "p3_step_03_connectors_authorized",
        "Required Connectors Authorized & Verified",
        "Verify organization-scoped connector configuration and credentials prior to service activation.",
    ),
    (
        4,
        "p3_step_04_workflow_executed",
        "Initial Service Workflow Executed",
        "Execute customer service workflow inside tenant concurrency and budget limits with ExecutionEvidence.",
    ),
    (
        5,
        "p3_step_05_deliverable_verified_accepted",
        "Deliverable QA Reviewed & Customer Accepted",
        "Complete QA checklist and record customer acceptance (or controlled revision loop) on real deliverables.",
    ),
    (
        6,
        "p3_step_06_health_score_evaluated",
        "Customer Health Score & Alerts Evaluated",
        "Compute multi-dimension Customer Health score with evidence freshness and trigger internal alerts if needed.",
    ),
    (
        7,
        "p3_step_07_support_ticket_resolved",
        "Support Ticket Triaged, Resolved & CSAT Captured",
        "Open org-scoped ticket, run AI triage (HITL-gated for sensitive replies), resolve, and record CSAT rating.",
    ),
    (
        8,
        "p3_step_08_renewal_or_payment_handled",
        "Renewal, Grace Period or Settlement Handled",
        "Verify idempotent subscription lifecycle event handling, upcoming renewal visibility, or grace/recovery flow.",
    ),
    (
        9,
        "p3_step_09_expansion_or_referral_reviewed",
        "Expansion or Referral Opportunity Reviewed via HITL",
        "Evaluate catalog-grounded upsell/referral opportunity and verify Owner HITL approval before sharing.",
    ),
    (
        10,
        "p3_step_10_unit_economics_verified",
        "Customer Unit Economics & Cost Budget Verified",
        "Verify ACTUAL/ALLOCATED/ESTIMATED delivery costs against verified revenue, margin, and monthly cost limit.",
    ),
    (
        11,
        "p3_step_11_privacy_export_tested",
        "Privacy Export & Offboarding Compliance Tested",
        "Run org-scoped redacted data portability export and verify legal-hold / HITL deletion safeguards.",
    ),
    (
        12,
        "p3_step_12_backup_restore_verified",
        "Multi-Tenant Ops Readiness & Backup Drill Verified",
        "Verify DB probe, DLQ recovery flow, concurrency guardrails, and documented backup/restore verification drill.",
    ),
)

VALID_ACCEPTANCE_STATUSES = ("NOT_TESTED", "SANDBOX_VERIFIED", "LIVE_VERIFIED")


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _is_sandbox_org(org: OrganizationRecord | None) -> bool:
    if not org:
        return False
    meta = org.metadata_json or {}
    return bool(meta.get("is_sandbox") or meta.get("synthetic") or str(org.slug or "").startswith("sandbox-"))


# ---------------------------------------------------------------------------
# 1. Section 12 — Multi-Tenant Operational Readiness & DLQ Recovery
# ---------------------------------------------------------------------------

def check_tenant_concurrency_guard(
    db: Session,
    *,
    org_id: str,
    limit: int | None = None,
) -> dict[str, Any]:
    """Return active workflow run concurrency count for an organization against limit."""
    cap = max(1, int(limit or MAX_CONCURRENT_RUNS_PER_ORG))
    active_runs = (
        db.query(WorkflowRunRecord)
        .filter(
            WorkflowRunRecord.org_id == org_id,
            WorkflowRunRecord.status.in_(("READY", "RUNNING")),
        )
        .count()
    )
    return {
        "org_id": org_id,
        "active_runs": active_runs,
        "max_concurrent_runs": cap,
        "allowed": active_runs < cap,
        "remaining": max(0, cap - active_runs),
    }


def enforce_tenant_concurrency_guard(
    db: Session,
    *,
    org_id: str,
    limit: int | None = None,
) -> dict[str, Any]:
    """Raise HTTP 429 and record an operational incident if tenant active runs hit limit."""
    status = check_tenant_concurrency_guard(db, org_id=org_id, limit=limit)
    if not status["allowed"]:
        db.add(
            P3OperationalIncidentRecord(
                org_id=org_id,
                incident_type="CONCURRENCY_LIMIT_HIT",
                severity="MEDIUM",
                status="OPEN",
                resource_ref=f"org:{org_id}",
                summary=(
                    f"Concurrent workflow limit reached ({status['active_runs']}/{status['max_concurrent_runs']}) "
                    f"for org '{org_id}'"
                ),
                details_json=status,
            )
        )
        db.flush()
        raise HTTPException(
            status_code=429,
            detail=(
                f"Concurrent workflow limit reached for organization '{org_id}' "
                f"({status['active_runs']}/{status['max_concurrent_runs']}). Try again when an active run finishes."
            ),
        )
    return status


def move_failed_run_to_dlq(
    db: Session,
    *,
    run: WorkflowRunRecord,
    reason: str,
    incident_type: str = "DEAD_LETTER_JOB",
    details: dict[str, Any] | None = None,
) -> P3OperationalIncidentRecord:
    """Record or update an open DLQ/timeout operational incident for a failed workflow run."""
    res_ref = f"workflow_run:{run.id}"
    existing = (
        db.query(P3OperationalIncidentRecord)
        .filter(
            P3OperationalIncidentRecord.resource_ref == res_ref,
            P3OperationalIncidentRecord.status == "OPEN",
        )
        .first()
    )
    payload = redact_secrets(
        {
            "workflow_id": run.workflow_id,
            "run_id": run.id,
            "execution_mode": run.execution_mode,
            "current_step_index": run.current_step_index,
            "total_steps": run.total_steps,
            "retry_count": run.retry_count,
            **(details or {}),
        }
    )
    if existing:
        existing.summary = reason
        existing.details_json = payload
        flag_modified(existing, "details_json")
        db.add(existing)
        return existing

    inc = P3OperationalIncidentRecord(
        org_id=run.org_id,
        incident_type=incident_type,
        severity="HIGH",
        status="OPEN",
        resource_ref=res_ref,
        summary=reason,
        details_json=payload,
        retry_attempts=0,
    )
    db.add(inc)
    db.flush()
    return inc


def scan_and_recover_stale_workflows(
    db: Session,
    *,
    timeout_seconds: int | None = None,
    org_id: str | None = None,
    auto_dlq: bool = True,
    actor: str = "ops_monitor",
) -> dict[str, Any]:
    """Detect timed-out RUNNING workflows, move to FAILED + DLQ cleanly, and audit without hanging."""
    now = datetime.now(UTC)
    limit_sec = max(10, int(timeout_seconds or DEFAULT_WORKFLOW_TIMEOUT_SECONDS))
    cutoff = now - timedelta(seconds=limit_sec)

    q = db.query(WorkflowRunRecord).filter(WorkflowRunRecord.status == "RUNNING")
    if org_id:
        q = q.filter(WorkflowRunRecord.org_id == org_id)
    candidates = q.all()

    timed_out_ids: list[str] = []
    incidents_created: list[str] = []
    for run in candidates:
        ref_dt = _utc(run.updated_at or run.started_at or run.created_at)
        if not ref_dt or ref_dt > cutoff:
            continue
        timed_out_ids.append(run.id)
        if auto_dlq:
            elapsed = round((now - ref_dt).total_seconds(), 1)
            msg = f"Workflow execution timed out after {elapsed}s (limit {limit_sec}s); routed to DLQ"
            run.status = "FAILED"
            run.failure_reason = msg
            run.completed_at = now
            db.add(run)
            inc = move_failed_run_to_dlq(
                db,
                run=run,
                reason=msg,
                incident_type="WORKFLOW_TIMEOUT",
                details={"elapsed_seconds": elapsed, "timeout_limit_seconds": limit_sec},
            )
            incidents_created.append(inc.id)
            db.add(
                AuditLog(
                    task_id=run.id,
                    correlation_id=run.org_id,
                    agent_id=actor,
                    capability_name="p3_ops_readiness",
                    action="workflow_timeout_dlq",
                    input_payload={"run_id": run.id, "timeout_limit_seconds": limit_sec},
                    output_payload={"incident_id": inc.id, "status": "FAILED"},
                    status="ok",
                )
            )

    db.commit()
    return {
        "checked_running_count": len(candidates),
        "timed_out_count": len(timed_out_ids),
        "timed_out_run_ids": timed_out_ids,
        "incidents_created": incidents_created,
        "timeout_seconds": limit_sec,
        "scanned_at": now.isoformat(),
    }


def retry_dlq_workflow_run(
    db: Session,
    *,
    incident_id: str,
    actor: str = "owner",
    org_id_scope: str | None = None,
) -> dict[str, Any]:
    """Safely re-queue a FAILED/timed-out workflow run from DLQ at its last checkpoint."""
    inc = db.get(P3OperationalIncidentRecord, incident_id)
    if not inc:
        raise ValueError(f"Operational incident '{incident_id}' not found")
    if org_id_scope and inc.org_id and inc.org_id != org_id_scope:
        raise PermissionError("Operational incident does not belong to your organization")
    if inc.incident_type not in ("DEAD_LETTER_JOB", "WORKFLOW_TIMEOUT"):
        raise ValueError(f"Incident '{incident_id}' of type '{inc.incident_type}' is not a DLQ workflow job")

    res_ref = inc.resource_ref or ""
    if not res_ref.startswith("workflow_run:"):
        raise ValueError("Incident missing workflow_run reference")
    run_id = res_ref.split("workflow_run:", 1)[1]
    run = db.get(WorkflowRunRecord, run_id)
    if not run:
        raise ValueError(f"Workflow run '{run_id}' not found")

    enforce_tenant_concurrency_guard(db, org_id=run.org_id)
    if run.status not in ("FAILED", "BLOCKED", "READY"):
        raise ValueError(f"Workflow run '{run_id}' is in status '{run.status}' and cannot be DLQ-requeued")

    now = datetime.now(UTC)
    run.status = "READY"
    run.retry_count = int(run.retry_count or 0) + 1
    run.failure_reason = None
    run.completed_at = None
    run.updated_at = now
    db.add(run)

    inc.retry_attempts = int(inc.retry_attempts or 0) + 1
    inc.status = "RECOVERED"
    inc.recovered_at = now
    det = dict(inc.details_json or {})
    det["recovered_by"] = actor
    det["requeued_to_status"] = "READY"
    inc.details_json = det
    flag_modified(inc, "details_json")
    db.add(inc)

    db.add(
        AuditLog(
            task_id=run.id,
            correlation_id=run.org_id,
            agent_id=actor,
            capability_name="p3_ops_readiness",
            action="dlq_workflow_requeued",
            input_payload={"incident_id": inc.id, "run_id": run.id},
            output_payload={"run_status": "READY", "retry_count": run.retry_count, "incident_status": "RECOVERED"},
            status="ok",
        )
    )
    db.commit()
    db.refresh(inc)
    return {
        "incident": serialize_operational_incident(inc),
        "workflow_run_id": run.id,
        "workflow_run_status": run.status,
        "retry_count": run.retry_count,
        "current_step_index": run.current_step_index,
    }


def probe_database_performance(db: Session) -> dict[str, Any]:
    """Measure live DB SELECT 1 and query latency plus engine dialect details."""
    now = datetime.now(UTC)
    t0 = time.perf_counter()
    db.execute(text("SELECT 1")).scalar()
    ping_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    t1 = time.perf_counter()
    org_count = db.query(OrganizationRecord).count()
    run_count = db.query(WorkflowRunRecord).count()
    query_ms = round((time.perf_counter() - t1) * 1000.0, 2)

    bind = db.get_bind()
    dialect = bind.dialect.name if bind is not None else "unknown"
    status = "DEGRADED" if max(ping_ms, query_ms) > DB_LATENCY_DEGRADED_MS else "HEALTHY"
    if status == "DEGRADED":
        db.add(
            P3OperationalIncidentRecord(
                org_id=None,
                incident_type="DB_PERFORMANCE_DEGRADED",
                severity="HIGH",
                status="OPEN",
                resource_ref=f"database:{dialect}",
                summary=f"Database latency degraded: ping={ping_ms}ms, query={query_ms}ms",
                details_json={"ping_latency_ms": ping_ms, "query_latency_ms": query_ms, "threshold_ms": DB_LATENCY_DEGRADED_MS},
            )
        )
        db.commit()

    return {
        "status": status,
        "dialect": dialect,
        "ping_latency_ms": ping_ms,
        "query_latency_ms": query_ms,
        "threshold_ms": DB_LATENCY_DEGRADED_MS,
        "observed_counts": {"organizations": org_count, "workflow_runs": run_count},
        "checked_at": now.isoformat(),
    }


def get_connector_health_matrix(db: Session, *, org_id: str | None = None) -> list[dict[str, Any]]:
    """Return sanitized per-tenant connector verification and readiness state."""
    q = db.query(ConnectorStateRecord)
    if org_id:
        q = q.filter(ConnectorStateRecord.org_id == org_id)
    rows = q.order_by(ConnectorStateRecord.org_id.asc(), ConnectorStateRecord.connector_id.asc()).all()
    return [
        {
            "org_id": r.org_id,
            "connector_id": r.connector_id,
            "provider": r.provider,
            "environment": r.environment,
            "connection_status": r.connection_status,
            "capability_state": r.capability_state,
            "last_verified_at": r.last_verified_at.isoformat() if r.last_verified_at else None,
            "last_error": r.last_error,
            "config_summary": redact_secrets(r.config_summary or {}),
        }
        for r in rows
    ]


def record_backup_verification_drill(
    db: Session,
    *,
    verified_by: str,
    target_scope: str,
    restore_tested: bool,
    recovery_point_objective_minutes: int | None = None,
    recovery_time_seconds: float | None = None,
    evidence_ref: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Log an operator-executed backup & restore verification drill (never fabricated)."""
    now = datetime.now(UTC)
    status = "RECOVERED" if restore_tested else "OPEN"
    inc = P3OperationalIncidentRecord(
        org_id=None,
        incident_type="BACKUP_DRILL",
        severity="LOW" if restore_tested else "HIGH",
        status=status,
        resource_ref=f"backup_scope:{target_scope[:120]}",
        summary=(
            f"Backup & restore drill verified for '{target_scope}'"
            if restore_tested
            else f"Backup drill recorded WITHOUT successful restore verification for '{target_scope}'"
        ),
        details_json={
            "verified_by": verified_by,
            "target_scope": target_scope,
            "restore_tested": bool(restore_tested),
            "rpo_minutes": recovery_point_objective_minutes,
            "rto_seconds": recovery_time_seconds,
            "evidence_ref": evidence_ref,
            "notes": notes,
        },
        recovered_at=now if restore_tested else None,
    )
    db.add(inc)
    db.flush()
    db.add(
        AuditLog(
            task_id=inc.id,
            correlation_id="platform_ops",
            agent_id=verified_by,
            capability_name="p3_ops_readiness",
            action="backup_restore_drill_recorded",
            input_payload={"target_scope": target_scope, "restore_tested": restore_tested},
            output_payload={"incident_id": inc.id, "status": status},
            status="ok",
        )
    )
    db.commit()
    db.refresh(inc)
    return serialize_operational_incident(inc)


def get_operational_readiness_summary(db: Session, *, org_id: str | None = None) -> dict[str, Any]:
    """Summarize DB health, tenant workflow concurrency, DLQ/timeout incidents, connectors, and latest backup drill."""
    db_probe = probe_database_performance(db)
    connectors = get_connector_health_matrix(db, org_id=org_id)

    active_q = db.query(WorkflowRunRecord).filter(WorkflowRunRecord.status.in_(("READY", "RUNNING")))
    if org_id:
        active_q = active_q.filter(WorkflowRunRecord.org_id == org_id)
    active_runs = active_q.all()
    by_org: dict[str, int] = {}
    for r in active_runs:
        by_org[r.org_id] = by_org.get(r.org_id, 0) + 1

    inc_q = db.query(P3OperationalIncidentRecord)
    if org_id:
        inc_q = inc_q.filter((P3OperationalIncidentRecord.org_id == org_id) | (P3OperationalIncidentRecord.org_id.is_(None)))
    incidents = inc_q.order_by(P3OperationalIncidentRecord.created_at.desc()).limit(50).all()

    open_dlq = [i for i in incidents if i.incident_type in ("DEAD_LETTER_JOB", "WORKFLOW_TIMEOUT") and i.status == "OPEN"]
    backup_drills = [i for i in incidents if i.incident_type == "BACKUP_DRILL"]
    latest_drill = serialize_operational_incident(backup_drills[0]) if backup_drills else None

    return {
        "database_health": db_probe,
        "concurrency_limits": {
            "max_concurrent_runs_per_org": MAX_CONCURRENT_RUNS_PER_ORG,
            "workflow_timeout_seconds": DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
            "active_runs_total": len(active_runs),
            "active_runs_by_org": by_org,
        },
        "dlq_summary": {
            "open_dlq_count": len(open_dlq),
            "open_items": [serialize_operational_incident(i) for i in open_dlq],
        },
        "connector_health_matrix": connectors,
        "latest_backup_drill": latest_drill,
        "recent_incidents": [serialize_operational_incident(i) for i in incidents[:20]],
    }


def serialize_operational_incident(inc: P3OperationalIncidentRecord) -> dict[str, Any]:
    return {
        "id": inc.id,
        "org_id": inc.org_id,
        "incident_type": inc.incident_type,
        "severity": inc.severity,
        "status": inc.status,
        "resource_ref": inc.resource_ref,
        "summary": inc.summary,
        "details": inc.details_json or {},
        "retry_attempts": inc.retry_attempts,
        "recovered_at": inc.recovered_at.isoformat() if inc.recovered_at else None,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
    }


# ---------------------------------------------------------------------------
# 2. Section 14 — Security, Privacy & GDPR/DPDP Compliance
# ---------------------------------------------------------------------------

def update_consent_and_retention(
    db: Session,
    *,
    org_id: str,
    consent_preferences: dict[str, Any] | None = None,
    retention_policy: dict[str, Any] | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Update organization consent tracking, retention window, and legal-hold flags."""
    acc = ensure_customer_account(db, org_id=org_id, commit=False)
    now = datetime.now(UTC)

    if consent_preferences is not None:
        consent = dict(acc.consent_preferences_json or {})
        consent.update(consent_preferences)
        consent["updated_at"] = now.isoformat()
        consent["updated_by"] = actor
        acc.consent_preferences_json = consent
        flag_modified(acc, "consent_preferences_json")

    if retention_policy is not None:
        retention = dict(acc.retention_policy_json or {})
        retention.update(retention_policy)
        retention["updated_at"] = now.isoformat()
        retention["updated_by"] = actor
        acc.retention_policy_json = retention
        flag_modified(acc, "retention_policy_json")

    acc.updated_at = now
    db.add(acc)
    db.add(
        AuditLog(
            task_id=acc.id,
            correlation_id=org_id,
            agent_id=actor,
            capability_name="p3_compliance",
            action="consent_retention_updated",
            input_payload={"consent_keys": list((consent_preferences or {}).keys()), "retention_keys": list((retention_policy or {}).keys())},
            output_payload={"legal_hold": bool((acc.retention_policy_json or {}).get("legal_hold"))},
            status="ok",
        )
    )
    db.commit()
    db.refresh(acc)
    return {
        "org_id": org_id,
        "consent_preferences": acc.consent_preferences_json or {},
        "retention_policy": acc.retention_policy_json or {},
        "updated_at": now.isoformat(),
    }


def export_customer_data_bundle(
    db: Session,
    *,
    org_id: str,
    requested_by: str,
    scope: str = "full_organization_export",
    reason: str = "Customer DPDP/GDPR data portability export",
    customer_safe_only: bool = False,
) -> dict[str, Any]:
    """Export strictly organization-scoped data with mandatory secret/credential redaction and audit trail."""
    org = db.get(OrganizationRecord, org_id)
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")
    now = datetime.now(UTC)

    users = db.query(UserRecord).filter_by(org_id=org_id).all()
    profiles = db.query(BusinessProfileRecord).filter_by(org_id=org_id).all()
    acc = db.query(P3CustomerAccountRecord).filter_by(org_id=org_id).first()
    onboardings = db.query(P3OnboardingWorkflowRecord).filter_by(org_id=org_id).all()
    deliveries = db.query(P3ServiceDeliveryRecord).filter_by(org_id=org_id).all()
    tickets = db.query(P3SupportTicketRecord).filter_by(org_id=org_id).all()
    subs = db.query(TenantSubscriptionRecord).filter_by(org_id=org_id).all()
    invoices = db.query(InvoiceRecord).filter_by(org_id=org_id).all()
    sub_events = db.query(P3SubscriptionEventRecord).filter_by(org_id=org_id).all()
    wf_defs = db.query(WorkflowDefinitionRecord).filter_by(org_id=org_id).all()
    wf_runs = db.query(WorkflowRunRecord).filter_by(org_id=org_id).all()
    evidences = db.query(ExecutionEvidenceRecord).filter_by(tenant_id=org_id).all()

    raw_bundle = {
        "exported_at": now.isoformat(),
        "org_id": org_id,
        "scope": scope,
        "organization": {"id": org.id, "name": org.name, "slug": org.slug, "tier": org.tier, "is_active": org.is_active},
        "users": [
            {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active}
            for u in users
        ],
        "business_profiles": [
            {"id": p.id, "company_name": p.company_name, "website": p.website_url, "industry": p.industry}
            for p in profiles
        ],
        "customer_account": {
            "lifecycle_state": acc.lifecycle_state if acc else None,
            "business_goals": acc.business_goals_json if acc else [],
            "consent_preferences": acc.consent_preferences_json if acc else {},
            "retention_policy": acc.retention_policy_json if acc else {},
        },
        "onboarding_workflows": [{"id": w.id, "sku_key": w.sku_key, "status": w.status, "progress_pct": w.progress_pct} for w in onboardings],
        "service_deliveries": [
            {"id": d.id, "title": d.title, "quality_state": d.quality_state, "output_artifacts": d.output_artifacts_json, "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None}
            for d in deliveries
        ],
        "support_tickets": [
            {
                "ticket_number": t.ticket_number,
                "subject": t.subject,
                "status": t.status,
                "messages": (
                    [
                        m
                        for m in (t.messages_json or [])
                        if (m.get("visibility") or "").lower() not in ("internal_only", "internal_note")
                    ]
                    if customer_safe_only
                    else (t.messages_json or [])
                ),
                **({} if customer_safe_only else {"internal_notes": t.internal_notes_json or []}),
                "csat_rating": t.csat_rating,
            }
            for t in tickets
        ],
        "subscriptions": [{"id": s.id, "internal_sku": s.internal_sku, "status": s.status, "currency": s.currency} for s in subs],
        "invoices": [{"id": i.id, "amount": i.amount, "currency": i.currency, "status": i.status} for i in invoices],
        "subscription_events": [{"event_type": e.event_type, "subscription_state": e.subscription_state, "amount": e.amount} for e in sub_events],
        "workflow_definitions": [{"id": d.id, "name": d.name, "service_id": d.service_id} for d in wf_defs],
        "workflow_runs": [{"id": r.id, "status": r.status, "execution_mode": r.execution_mode} for r in wf_runs],
        "execution_evidences": [{"execution_id": ev.execution_id, "output_origin": ev.output_origin, "status": ev.status} for ev in evidences],
    }
    redacted_bundle = redact_secrets(raw_bundle)

    manifest = {
        "record_counts": {
            "users": len(users),
            "business_profiles": len(profiles),
            "onboarding_workflows": len(onboardings),
            "service_deliveries": len(deliveries),
            "support_tickets": len(tickets),
            "subscriptions": len(subs),
            "invoices": len(invoices),
            "workflow_runs": len(wf_runs),
            "execution_evidences": len(evidences),
        },
        "redacted_fields": ["password_hash", "api_keys", "tokens", "connector_secrets", "internal_notes" if customer_safe_only else "connector_secrets"],
    }
    req = P3ComplianceRequestRecord(
        org_id=org_id,
        request_type="DATA_EXPORT",
        status="COMPLETED",
        requested_by=requested_by,
        reason=reason,
        export_manifest_json=manifest,
        completed_at=now,
    )
    db.add(req)
    db.flush()
    db.add(
        AuditLog(
            task_id=req.id,
            correlation_id=org_id,
            agent_id=requested_by,
            capability_name="p3_compliance",
            action="customer_data_exported",
            input_payload={"scope": scope, "customer_safe_only": customer_safe_only},
            output_payload=manifest,
            status="ok",
        )
    )
    db.commit()
    db.refresh(req)
    return {
        "compliance_request": serialize_compliance_request(req),
        "bundle": redacted_bundle,
    }


def request_customer_deletion_or_offboarding(
    db: Session,
    *,
    org_id: str,
    request_type: str = "ACCOUNT_OFFBOARDING",
    requested_by: str,
    reason: str,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Enforce legal-hold / dispute blocks and mandatory Owner HITL before offboarding or PII deletion."""
    req_type = request_type.strip().upper()
    if req_type not in ("DATA_DELETION", "ACCOUNT_OFFBOARDING"):
        raise ValueError("request_type must be DATA_DELETION or ACCOUNT_OFFBOARDING")

    org = db.get(OrganizationRecord, org_id)
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")
    acc = ensure_customer_account(db, org_id=org_id, commit=False)
    retention = acc.retention_policy_json or {}

    # Check Legal Hold & Open Billing/Refund Disputes before allowing deletion
    blockers: list[str] = []
    if retention.get("legal_hold"):
        blockers.append("Organization is under an active LEGAL HOLD")
    if retention.get("open_dispute"):
        blockers.append("Organization has an unresolved billing or legal dispute flag")
    open_disputes = (
        db.query(P3SupportTicketRecord)
        .filter(
            P3SupportTicketRecord.org_id == org_id,
            P3SupportTicketRecord.category == "refund_dispute",
            P3SupportTicketRecord.status.notin_(("RESOLVED", "CLOSED")),
        )
        .count()
    )
    if open_disputes > 0:
        blockers.append(f"{open_disputes} open refund_dispute support ticket(s) must be resolved first")

    now = datetime.now(UTC)
    if blockers:
        rec = P3ComplianceRequestRecord(
            org_id=org_id,
            request_type=req_type,
            status="BLOCKED_LEGAL_HOLD",
            requested_by=requested_by,
            reason=reason,
            offboarding_checklist_json={"blocked": True, "blockers": blockers},
        )
        db.add(rec)
        db.flush()
        db.add(
            AuditLog(
                task_id=rec.id,
                correlation_id=org_id,
                agent_id=requested_by,
                capability_name="p3_compliance",
                action="deletion_blocked_by_legal_hold_or_dispute",
                input_payload={"request_type": req_type},
                output_payload={"blockers": blockers},
                status="blocked",
            )
        )
        db.commit()
        db.refresh(rec)
        return {
            "executed": False,
            "blocked": True,
            "blockers": blockers,
            "compliance_request": serialize_compliance_request(rec),
        }

    if not approval_id:
        idem = f"p3-compliance-{org_id}-{req_type.lower()}-{uuid.uuid4().hex[:8]}"
        appr = ApprovalRequest(
            task_id=acc.id,
            action="customer_offboarding_and_deletion",
            detail={"org_id": org_id, "request_type": req_type, "reason": reason, "requested_by": requested_by},
            idempotency_key=idem,
            request_hash=f"{org_id}:{req_type}",
            status="PENDING",
            requested_by=requested_by,
        )
        db.add(appr)
        db.flush()
        rec = P3ComplianceRequestRecord(
            org_id=org_id,
            request_type=req_type,
            status="AWAITING_OWNER_APPROVAL",
            approval_id=appr.id,
            requested_by=requested_by,
            reason=reason,
        )
        db.add(rec)
        db.flush()
        db.commit()
        db.refresh(rec)
        return {
            "executed": False,
            "requires_approval": True,
            "approval_id": appr.id,
            "approval_status": "PENDING",
            "compliance_request": serialize_compliance_request(rec),
        }

    appr = db.get(ApprovalRequest, approval_id)
    if not appr or appr.status != "APPROVED":
        raise PermissionError("Customer deletion/offboarding requires an APPROVED Owner ApprovalRequest")
    if appr.action not in ("customer_offboarding_and_deletion", "data_deletion"):
        raise PermissionError("ApprovalRequest action does not authorize customer offboarding/deletion")

    # Execute offboarding and/or pseudonymized PII deletion while preserving immutable audit/invoice history
    users = db.query(UserRecord).filter_by(org_id=org_id).all()
    for u in users:
        u.is_active = False
        if req_type == "DATA_DELETION":
            u.email = f"deleted-{u.id[:8]}@redacted.invalid"
            u.full_name = "REDACTED USER"
        db.add(u)

    connectors = db.query(ConnectorStateRecord).filter_by(org_id=org_id).all()
    for c in connectors:
        c.connection_status = "REVOKED"
        c.capability_state = "REVOKED"
        c.config_summary = {"revoked_at": now.isoformat(), "revoked_by": requested_by}
        flag_modified(c, "config_summary")
        db.add(c)

    subs = db.query(TenantSubscriptionRecord).filter_by(org_id=org_id).all()
    for s in subs:
        s.status = "cancelled"
        s.cancel_at_period_end = False
        db.add(s)

    acc.lifecycle_state = "CLOSED"
    if req_type == "DATA_DELETION":
        acc.primary_contact_email = f"deleted-{org_id[:8]}@redacted.invalid"
        acc.primary_contact_name = "REDACTED"
    acc.updated_at = now
    db.add(acc)

    org.is_active = False
    org.updated_at = now
    db.add(org)

    checklist = {
        "access_revoked_users": len(users),
        "connectors_revoked": len(connectors),
        "subscriptions_cancelled": len(subs),
        "pii_redacted": req_type == "DATA_DELETION",
        "financial_and_audit_records_preserved": True,
        "completed_at": now.isoformat(),
    }
    rec = P3ComplianceRequestRecord(
        org_id=org_id,
        request_type=req_type,
        status="COMPLETED",
        approval_id=appr.id,
        requested_by=requested_by,
        reason=reason,
        offboarding_checklist_json=checklist,
        completed_at=now,
    )
    db.add(rec)
    db.flush()
    db.add(
        AuditLog(
            task_id=rec.id,
            correlation_id=org_id,
            agent_id=appr.decided_by or requested_by,
            capability_name="p3_compliance",
            action=f"{req_type.lower()}_executed",
            input_payload={"approval_id": appr.id},
            output_payload=checklist,
            status="ok",
        )
    )
    db.commit()
    db.refresh(rec)
    return {
        "executed": True,
        "blocked": False,
        "compliance_request": serialize_compliance_request(rec),
    }


def serialize_compliance_request(req: P3ComplianceRequestRecord) -> dict[str, Any]:
    return {
        "id": req.id,
        "org_id": req.org_id,
        "request_type": req.request_type,
        "status": req.status,
        "approval_id": req.approval_id,
        "requested_by": req.requested_by,
        "reason": req.reason,
        "export_manifest": req.export_manifest_json,
        "offboarding_checklist": req.offboarding_checklist_json,
        "completed_at": req.completed_at.isoformat() if req.completed_at else None,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


# ---------------------------------------------------------------------------
# 3. Section 9 — Founder Control Centre: Customer Operations
# ---------------------------------------------------------------------------

def get_p3_customer_ops_control_centre(
    db: Session,
    *,
    period_days: int = 30,
) -> dict[str, Any]:
    """Build Founder Customer Operations Control Centre separating verified live KPIs from simulation data."""
    now = datetime.now(UTC)
    days = max(1, min(365, int(period_days)))
    period_start = now - timedelta(days=days)

    all_orgs = db.query(OrganizationRecord).all()
    sandbox_org_ids = {o.id for o in all_orgs if _is_sandbox_org(o)}

    # Acquisition (non-synthetic P2 prospects)
    all_prospects = db.query(P2ProspectDossierRecord).all()
    live_prospects = [p for p in all_prospects if not p.is_synthetic]
    synthetic_prospects = [p for p in all_prospects if p.is_synthetic]
    qualified_prospects = [p for p in live_prospects if p.pipeline_status in ("QUALIFIED", "APPROVAL_PENDING", "CONTACTED", "RESPONDED", "DISCOVERY", "PROPOSAL_PENDING", "WON")]
    won_prospects = [p for p in live_prospects if p.pipeline_status == "WON"]
    acq_conversion = (
        round((len(won_prospects) / len(qualified_prospects)) * 100.0, 2)
        if qualified_prospects
        else "INSUFFICIENT_DATA"
    )

    # Customer Accounts & Activation
    all_accounts = db.query(P3CustomerAccountRecord).all()
    live_accounts = [a for a in all_accounts if a.org_id not in sandbox_org_ids]
    sandbox_accounts = [a for a in all_accounts if a.org_id in sandbox_org_ids]

    lifecycle_counts: dict[str, int] = {}
    activation_hours: list[float] = []
    for a in live_accounts:
        lifecycle_counts[a.lifecycle_state] = lifecycle_counts.get(a.lifecycle_state, 0) + 1
        if a.activated_at and a.created_at:
            c_dt = _utc(a.created_at)
            a_dt = _utc(a.activated_at)
            if c_dt and a_dt and a_dt >= c_dt:
                activation_hours.append((a_dt - c_dt).total_seconds() / 3600.0)

    activated_count = sum(1 for a in live_accounts if a.lifecycle_state in ("ACTIVE", "AT_RISK", "SUSPENDED") and a.activated_at)
    activation_rate_pct = round((activated_count / len(live_accounts)) * 100.0, 2) if live_accounts else 0.0
    avg_activation_hours = round(sum(activation_hours) / len(activation_hours), 2) if activation_hours else "INSUFFICIENT_DATA"

    live_onboardings = [w for w in db.query(P3OnboardingWorkflowRecord).all() if w.org_id not in sandbox_org_ids]
    blocker_counts: dict[str, int] = {}
    for w in live_onboardings:
        for blk in (w.blockers_json or []):
            blocker_counts[str(blk)] = blocker_counts.get(str(blk), 0) + 1

    # Delivery & Quality
    all_deliveries = db.query(P3ServiceDeliveryRecord).all()
    live_deliveries = [d for d in all_deliveries if d.org_id not in sandbox_org_ids]
    quality_counts: dict[str, int] = {}
    overdue_count = 0
    qa_passed = 0
    qa_total = 0
    revision_count = 0
    for d in live_deliveries:
        quality_counts[d.quality_state] = quality_counts.get(d.quality_state, 0) + 1
        due = _utc(d.due_date)
        if due and due < now and d.quality_state not in ("DELIVERED", "ACCEPTED"):
            overdue_count += 1
        if d.quality_state == "REVISION_REQUESTED":
            revision_count += 1
        if d.quality_checks_json and "passed" in d.quality_checks_json:
            qa_total += 1
            if d.quality_checks_json.get("passed"):
                qa_passed += 1
    qa_pass_rate = round((qa_passed / qa_total) * 100.0, 2) if qa_total else "INSUFFICIENT_DATA"
    revision_rate = round((revision_count / len(live_deliveries)) * 100.0, 2) if live_deliveries else 0.0

    # Revenue, MRR, One-Time, ARR, Expansion, Refunds, Receivables
    all_invoices = db.query(InvoiceRecord).all()
    live_invoices = [i for i in all_invoices if i.org_id not in sandbox_org_ids]
    verified_one_time_inr = 0.0
    verified_expansion_inr = 0.0
    verified_refunds_inr = 0.0
    outstanding_receivables_inr = 0.0
    for inv in live_invoices:
        if (inv.currency or "INR").upper() != "INR":
            continue
        amt = float(inv.amount or 0) / 100.0
        meta = inv.metadata_json or {}
        if inv.status == "paid":
            if meta.get("billing_category") == "EXPANSION_PURCHASE":
                verified_expansion_inr += amt
            elif meta.get("billing_type") != "recurring":
                verified_one_time_inr += amt
        elif inv.status == "refunded":
            verified_refunds_inr += amt
        elif inv.status in ("open", "past_due", "unpaid"):
            outstanding_receivables_inr += amt

    # Verified Recurring MRR ONLY from provider-confirmed RECURRING_SUBSCRIPTION events/subscriptions
    sub_events = [e for e in db.query(P3SubscriptionEventRecord).all() if e.org_id not in sandbox_org_ids]
    latest_sub_by_org: dict[str, P3SubscriptionEventRecord] = {}
    for ev in sorted(sub_events, key=lambda x: x.created_at or now):
        latest_sub_by_org[ev.org_id] = ev

    verified_recurring_mrr_inr = 0.0
    failed_payments_count = 0
    for ev in sub_events:
        if (ev.event_type or "").strip().lower() == "payment_failed":
            failed_payments_count += 1
    for ev in latest_sub_by_org.values():
        if (
            ev.is_provider_confirmed
            and ev.billing_category == "RECURRING_SUBSCRIPTION"
            and ev.subscription_state in ("ACTIVE", "TRIALING")
            and (ev.currency or "INR").upper() == "INR"
        ):
            monthly = float(ev.amount or 0.0) / 12.0 if ev.billing_interval == "annual" else float(ev.amount or 0.0)
            verified_recurring_mrr_inr += monthly

    verified_recurring_mrr_inr = round(verified_recurring_mrr_inr, 2)
    verified_arr_inr: float | str = round(verified_recurring_mrr_inr * 12.0, 2) if verified_recurring_mrr_inr > 0 else "INSUFFICIENT_DATA"

    rel_summary = get_subscription_reliability_summary(db, days_ahead=days)
    live_renewals = [r for r in rel_summary["upcoming_renewals"] if r["org_id"] not in sandbox_org_ids]

    # Expansion
    all_opps = [o for o in db.query(P3GrowthOpportunityRecord).all() if o.org_id not in sandbox_org_ids]
    opp_status_counts: dict[str, int] = {}
    for o in all_opps:
        opp_status_counts[o.status] = opp_status_counts.get(o.status, 0) + 1

    # Support & CSAT
    live_tickets = [t for t in db.query(P3SupportTicketRecord).all() if t.org_id not in sandbox_org_ids]
    open_tickets = [t for t in live_tickets if t.status not in ("RESOLVED", "CLOSED")]
    escalated_tickets = [t for t in live_tickets if t.status == "ESCALATED"]
    res_secs = [float(t.resolution_seconds) for t in live_tickets if t.resolution_seconds is not None]
    csat_ratings = [float(t.csat_rating) for t in live_tickets if t.csat_rating is not None]
    avg_res_secs = round(sum(res_secs) / len(res_secs), 1) if res_secs else "INSUFFICIENT_DATA"
    avg_csat = round(sum(csat_ratings) / len(csat_ratings), 2) if csat_ratings else "INSUFFICIENT_DATA"

    # Unit Economics Rollup (strictly separating ACTUAL / ALLOCATED / ESTIMATED)
    live_cost_entries = [e for e in db.query(P3UnitEconomicsEntryRecord).all() if e.org_id not in sandbox_org_ids]
    cost_totals = {"ACTUAL": 0.0, "ALLOCATED": 0.0, "ESTIMATED": 0.0}
    for ce in live_cost_entries:
        lbl = ce.cost_type_label
        cost_totals[lbl] = round(cost_totals.get(lbl, 0.0) + float(ce.amount_inr or 0.0), 2)

    # Simulation & Sandbox Isolation Bucket (NEVER merged into live KPIs)
    sim_runs = db.query(WorkflowRunRecord).filter(WorkflowRunRecord.execution_mode == "SIMULATION").count()
    sim_evidences = db.query(ExecutionEvidenceRecord).filter(ExecutionEvidenceRecord.output_origin == "SIMULATED_SYNTHETIC").count()

    # Open Improvements & Health Summary
    open_improvements = db.query(P3ImprovementItemRecord).filter(P3ImprovementItemRecord.status == "OPEN").count()

    return {
        "reporting_period": {
            "period_days": days,
            "start_at": period_start.isoformat(),
            "end_at": now.isoformat(),
        },
        "data_freshness": "REALTIME_DB_QUERY",
        "evaluated_at": now.isoformat(),
        "calculation_method": {
            "verified_recurring_mrr_inr": "Sum of provider-confirmed RECURRING_SUBSCRIPTION active subscriptions normalized monthly; excludes manual pilot proofs and one-time fees.",
            "verified_arr_inr": "verified_recurring_mrr_inr * 12 when verified recurring MRR > 0; never annualizes one-time pilots.",
            "activation_rate_pct": "Activated non-sandbox P3 customers / Total non-sandbox P3 customers * 100.",
            "health_and_csat": "Computed only from non-sandbox database records; returns INSUFFICIENT_DATA when denominator or ratings are zero.",
        },
        "verified_customer_ops": {
            "acquisition": {
                "real_prospects_total": len(live_prospects),
                "qualified_prospects": len(qualified_prospects),
                "won_customers": len(won_prospects),
                "qualified_to_won_pct": acq_conversion,
            },
            "activation": {
                "total_customers": len(live_accounts),
                "lifecycle_breakdown": lifecycle_counts,
                "activated_customers": activated_count,
                "activation_rate_pct": activation_rate_pct,
                "avg_hours_to_activation": avg_activation_hours,
                "top_onboarding_blockers": blocker_counts,
            },
            "delivery": {
                "total_deliveries": len(live_deliveries),
                "quality_state_breakdown": quality_counts,
                "overdue_deliveries": overdue_count,
                "revision_rate_pct": revision_rate,
                "qa_pass_rate_pct": qa_pass_rate,
            },
            "retention_and_subscriptions": {
                "active_customers": lifecycle_counts.get("ACTIVE", 0),
                "at_risk_customers": lifecycle_counts.get("AT_RISK", 0),
                "suspended_customers": lifecycle_counts.get("SUSPENDED", 0),
                "churned_customers": lifecycle_counts.get("CHURNED", 0),
                "upcoming_renewals_count": len(live_renewals),
                "upcoming_renewals": live_renewals,
                "expansion_opportunities": opp_status_counts,
            },
            "revenue_and_unit_economics": {
                "verified_recurring_mrr_inr": verified_recurring_mrr_inr,
                "verified_arr_inr": verified_arr_inr,
                "verified_one_time_revenue_inr": round(verified_one_time_inr, 2),
                "verified_expansion_revenue_inr": round(verified_expansion_inr, 2),
                "verified_refunds_inr": round(verified_refunds_inr, 2),
                "failed_payments_count": failed_payments_count,
                "outstanding_receivables_inr": round(outstanding_receivables_inr, 2),
                "costs_by_label_inr": cost_totals,
                "historical_cac_ltv_status": "INSUFFICIENT_DATA",
            },
            "support_and_improvements": {
                "total_tickets": len(live_tickets),
                "open_tickets": len(open_tickets),
                "escalated_tickets": len(escalated_tickets),
                "avg_resolution_seconds": avg_res_secs,
                "avg_csat_out_of_5": avg_csat,
                "open_improvement_items": open_improvements,
            },
        },
        "simulation_and_test_metrics": {
            "exclusion_policy": "EXCLUDED_FROM_LIVE_BUSINESS_KPIS",
            "synthetic_prospects_count": len(synthetic_prospects),
            "sandbox_customer_accounts_count": len(sandbox_accounts),
            "simulation_workflow_runs_count": sim_runs,
            "simulated_execution_evidences_count": sim_evidences,
        },
    }


# ---------------------------------------------------------------------------
# 4. Section 16 — P3 12-Step Real-World Acceptance Checklist
# ---------------------------------------------------------------------------

def seed_and_get_p3_acceptance_checklist(db: Session) -> list[dict[str, Any]]:
    """Ensure all 12 P3 real-world acceptance steps exist with default NOT_TESTED status and return them."""
    existing = {r.step_number: r for r in db.query(P3AcceptanceStepRecord).all()}
    changed = False
    for num, key, title, desc in P3_ACCEPTANCE_BLUEPRINT:
        if num not in existing:
            rec = P3AcceptanceStepRecord(
                step_number=num,
                step_key=key,
                title=title,
                description=desc,
                verification_status="NOT_TESTED",
            )
            db.add(rec)
            changed = True
    if changed:
        db.commit()

    rows = db.query(P3AcceptanceStepRecord).order_by(P3AcceptanceStepRecord.step_number.asc()).all()
    return [serialize_p3_acceptance_step(r) for r in rows]


def update_p3_acceptance_step(
    db: Session,
    *,
    step_number: int,
    verification_status: str,
    evidence_summary: str,
    evidence_ref: str | None = None,
    verified_by: str = "owner",
) -> dict[str, Any]:
    """Update a P3 acceptance step strictly as NOT_TESTED, SANDBOX_VERIFIED, or LIVE_VERIFIED."""
    seed_and_get_p3_acceptance_checklist(db)
    status = verification_status.strip().upper()
    if status not in VALID_ACCEPTANCE_STATUSES:
        raise ValueError(f"verification_status must be one of {VALID_ACCEPTANCE_STATUSES}")
    rec = db.get(P3AcceptanceStepRecord, step_number)
    if not rec:
        raise ValueError(f"Acceptance step {step_number} not found")

    now = datetime.now(UTC)
    rec.verification_status = status
    rec.evidence_summary = evidence_summary.strip()
    rec.evidence_ref = evidence_ref
    rec.verified_by = verified_by
    rec.verified_at = now if status != "NOT_TESTED" else None
    rec.updated_at = now
    db.add(rec)
    db.add(
        AuditLog(
            task_id=rec.step_key,
            correlation_id="p3_acceptance",
            agent_id=verified_by,
            capability_name="p3_acceptance_checklist",
            action="acceptance_step_updated",
            input_payload={"step_number": step_number, "verification_status": status},
            output_payload={"evidence_ref": evidence_ref},
            status="ok",
        )
    )
    db.commit()
    db.refresh(rec)
    return serialize_p3_acceptance_step(rec)


def run_scheduled_p3_maintenance(
    db: Session,
    *,
    org_id: str | None = None,
    stale_timeout_seconds: int | None = None,
    timeout_seconds: int | None = None,
    actor: str = "scheduler",
) -> dict[str, Any]:
    """Run periodic CS maintenance: stale workflow timeout DLQ scan, grace expiry enforcement, and health alerts."""
    from app.services.p3_delivery_health import generate_internal_health_alerts
    from app.services.p3_revenue_growth import enforce_grace_period_expirations

    eff_timeout = stale_timeout_seconds if stale_timeout_seconds is not None else timeout_seconds
    timeout_scan = scan_and_recover_stale_workflows(
        db,
        timeout_seconds=eff_timeout,
        org_id=org_id,
        actor=actor,
    )
    grace_res = enforce_grace_period_expirations(db, org_id=org_id)
    acct_q = db.query(P3CustomerAccountRecord).filter(
        P3CustomerAccountRecord.lifecycle_state.in_(("ONBOARDING", "ACTIVATION_PENDING", "ACTIVE", "AT_RISK"))
    )
    if org_id:
        acct_q = acct_q.filter(P3CustomerAccountRecord.org_id == org_id)
    accounts = acct_q.all()
    alerts_generated = 0
    for acc in accounts:
        res = generate_internal_health_alerts(db, org_id=acc.org_id)
        if isinstance(res, list):
            alerts_generated += len(res)
        elif isinstance(res, dict):
            alerts_generated += int(res.get("count", 0))
    return {
        "status": "MAINTENANCE_COMPLETED",
        "org_id": org_id,
        "executed_at": datetime.now(UTC).isoformat(),
        "actor": actor,
        "stale_workflow_scan": timeout_scan,
        "grace_enforcement": grace_res,
        "health_alerts_accounts_scanned": len(accounts),
        "health_alerts_generated": alerts_generated,
    }


def serialize_p3_acceptance_step(rec: P3AcceptanceStepRecord) -> dict[str, Any]:
    return {
        "step_number": rec.step_number,
        "step_key": rec.step_key,
        "title": rec.title,
        "description": rec.description,
        "verification_status": rec.verification_status,
        "evidence_summary": rec.evidence_summary,
        "evidence_ref": rec.evidence_ref,
        "verified_by": rec.verified_by,
        "verified_at": rec.verified_at.isoformat() if rec.verified_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }
