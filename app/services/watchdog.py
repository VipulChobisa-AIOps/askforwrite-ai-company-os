"""Active Monitoring & Controlling Watchdog Agent (L1 Operational Supervisor).

Inspects live database state across tasks, approvals, field telemetry, credit quotas,
and cryptographic trust chain integrity. Generates, manages, and resolves SupervisorAlertRecords,
seals audit actions into immutable TrustBlocks, and computes operational control telemetry.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalRequest,
    AuditLog,
    FieldAttendanceRecord,
    OrderRecord,
    OrganizationRecord,
    SupervisorAlertRecord,
    TaskRecord,
    TrustBlock,
)
from app.security.trust_chain import seal_task_to_block, verify_chain

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "system_watchdog_controller"


class WatchdogAlertNotFound(Exception):
    """Raised when an alert record cannot be found by ID."""


def _serialize_alert(alert: SupervisorAlertRecord) -> dict[str, Any]:
    status_str = "RESOLVED" if alert.is_acknowledged else "OPEN"
    return {
        "id": alert.id,
        "alert_id": alert.id,
        "org_id": alert.org_id,
        "user_id": alert.user_id,
        "task_id": alert.task_id,
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "title": alert.title,
        "description": alert.description,
        "suggested_action": alert.suggested_action,
        "is_acknowledged": alert.is_acknowledged,
        "status": status_str,
        "acknowledged_by": alert.acknowledged_by,
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "metadata_json": alert.metadata_json or {},
    }


def calculate_system_health_score(
    active_alerts: list[SupervisorAlertRecord] | Any,
    task_completion_rate: float | None = None,
    approval_queue_depth: int | None = None,
    chain_valid: bool = True,
) -> int:
    """Compute overall operational health score (0-100).

    Accepts either (active_alerts_list, task_completion_rate, approval_queue_depth, chain_valid)
    or a SQLAlchemy Session directly to inspect live database state.
    """
    if hasattr(active_alerts, "query"):
        db_session = active_alerts
        live_alerts = db_session.query(SupervisorAlertRecord).filter_by(is_acknowledged=False).all()
        total_tasks = db_session.query(TaskRecord).count()
        completed_tasks = db_session.query(TaskRecord).filter_by(status="COMPLETED").count()
        comp_rate = (completed_tasks / total_tasks) if total_tasks > 0 else 1.0
        queue_depth = db_session.query(ApprovalRequest).filter_by(status="PENDING").count()
        chain_verif = verify_chain(db_session)
        is_chain_valid = chain_verif.get("chain_valid", chain_verif.get("valid", True))
        return calculate_system_health_score(
            active_alerts=live_alerts,
            task_completion_rate=comp_rate,
            approval_queue_depth=queue_depth,
            chain_valid=is_chain_valid,
        )

    alerts_list = list(active_alerts) if active_alerts else []
    rate = task_completion_rate if task_completion_rate is not None else 1.0
    queue = approval_queue_depth if approval_queue_depth is not None else 0

    score = 100
    if not chain_valid:
        score -= 40

    critical_count = sum(1 for a in alerts_list if a.severity == "CRITICAL")
    high_count = sum(1 for a in alerts_list if a.severity == "HIGH")
    medium_count = sum(1 for a in alerts_list if a.severity == "MEDIUM")

    score -= critical_count * 25
    score -= min(30, high_count * 10)
    score -= min(15, medium_count * 5)

    if rate < 0.8:
        score -= 10
    if queue > 10:
        score -= 10

    return max(0, min(100, score))


def run_system_watchdog_scan(
    db: Session,
    stale_minutes: int = 60,
    correlation_id: str | None = None,
    agent_id: str = "watchdog-agent-l1",
) -> dict[str, Any]:
    """Execute a comprehensive operational scan across the system."""
    corr_id = correlation_id or str(uuid.uuid4())
    scan_task_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=stale_minutes)

    created_alerts: list[SupervisorAlertRecord] = []

    # ── 1. STALLED_TASK: Stalled tasks, approvals, and unfulfilled orders ──────
    stalled_tasks = db.query(TaskRecord).filter(
        TaskRecord.status == "PENDING",
        TaskRecord.created_at < cutoff,
    ).all()
    for task in stalled_tasks:
        existing = db.query(SupervisorAlertRecord).filter_by(
            task_id=task.id,
            alert_type="STALLED_TASK",
            is_acknowledged=False,
        ).first()
        if not existing:
            alert = SupervisorAlertRecord(
                task_id=task.id,
                alert_type="STALLED_TASK",
                severity="HIGH",
                title=f"Stalled Task: {task.objective[:60]}",
                description=f"Task {task.id} has been in PENDING state for >{stale_minutes} minutes.",
                suggested_action="Review agent dispatch queue or cancel/restart task.",
                metadata_json={"task_id": task.id, "stale_since": task.created_at.isoformat()},
            )
            db.add(alert)
            created_alerts.append(alert)

    stalled_approvals = db.query(ApprovalRequest).filter(
        ApprovalRequest.status == "PENDING",
        ApprovalRequest.created_at < cutoff,
    ).all()
    for approval in stalled_approvals:
        existing = db.query(SupervisorAlertRecord).filter_by(
            task_id=approval.task_id or approval.id,
            alert_type="STALLED_TASK",
            is_acknowledged=False,
        ).first()
        if not existing:
            alert = SupervisorAlertRecord(
                task_id=approval.task_id or approval.id,
                alert_type="STALLED_TASK",
                severity="MEDIUM",
                title=f"Stalled Approval: {approval.action}",
                description=f"Approval request {approval.id} has been awaiting decision for >{stale_minutes} minutes.",
                suggested_action="Send reminder alert to L0 Owner for HITL approval.",
                metadata_json={"approval_id": approval.id, "action": approval.action},
            )
            db.add(alert)
            created_alerts.append(alert)

    unfulfilled_orders = db.query(OrderRecord).filter(
        OrderRecord.status == "CONFIRMED",
        OrderRecord.created_at < cutoff,
    ).all()
    for order in unfulfilled_orders:
        existing = db.query(SupervisorAlertRecord).filter(
            SupervisorAlertRecord.alert_type == "STALLED_TASK",
            SupervisorAlertRecord.title.contains(order.transaction_id),
            SupervisorAlertRecord.is_acknowledged.is_(False),
        ).first()
        if not existing:
            alert = SupervisorAlertRecord(
                task_id=order.task_id,
                alert_type="STALLED_TASK",
                severity="HIGH",
                title=f"Unfulfilled Order: {order.transaction_id}",
                description=f"Customer order {order.transaction_id} is confirmed but pending fulfillment for >{stale_minutes} minutes.",
                suggested_action="Trigger automated fulfillment via POST /v1/orders/{tx}/fulfill.",
                metadata_json={"transaction_id": order.transaction_id, "amount": order.amount, "customer_email": order.customer_email},
            )
            db.add(alert)
            created_alerts.append(alert)

    # ── 2. SPOOF_OR_GEOFENCE_BREACH: Mobile field presence breaches ───────────
    field_anomalies = db.query(FieldAttendanceRecord).filter(
        (FieldAttendanceRecord.is_mock_location_detected.is_(True))
        | (FieldAttendanceRecord.status == "SPOOF_REJECTED")
        | (FieldAttendanceRecord.status == "OUT_OF_BOUNDS")
    ).all()
    for rec in field_anomalies:
        existing = db.query(SupervisorAlertRecord).filter(
            SupervisorAlertRecord.alert_type == "SPOOF_OR_GEOFENCE_BREACH",
            SupervisorAlertRecord.user_id == rec.user_id,
            SupervisorAlertRecord.is_acknowledged.is_(False),
        ).first()
        if not existing:
            reason = "Mock Location Provider Detected" if rec.is_mock_location_detected else (rec.status or "Geofence Violation")
            alert = SupervisorAlertRecord(
                org_id=rec.org_id,
                user_id=rec.user_id,
                alert_type="SPOOF_OR_GEOFENCE_BREACH",
                severity="CRITICAL",
                title=f"Field Telemetry Breach: {reason} for User {rec.user_id}",
                description=(
                    f"Zero-trust check-in failure for user {rec.user_id} (attendance_id={rec.id}) at {rec.timestamp}: "
                    f"mock={rec.is_mock_location_detected}, status={rec.status}, notes={rec.verification_notes or 'None'}"
                ),
                suggested_action="Audit field personnel device integrity and quarantine unverified attendance record.",
                metadata_json={
                    "attendance_id": rec.id,
                    "latitude": rec.latitude,
                    "longitude": rec.longitude,
                    "accuracy_meters": rec.accuracy_meters,
                },
            )
            db.add(alert)
            created_alerts.append(alert)

    # ── 3. CREDIT_EXHAUSTION_RISK: Tenant credit exhaustion ───────────────────
    orgs = db.query(OrganizationRecord).filter(OrganizationRecord.is_active.is_(True)).all()
    for org in orgs:
        lead_exhausted = org.lead_credits_limit > 0 and org.lead_credits_used >= org.lead_credits_limit
        outreach_exhausted = org.outreach_credits_limit > 0 and org.outreach_credits_used >= org.outreach_credits_limit
        if lead_exhausted or outreach_exhausted:
            existing = db.query(SupervisorAlertRecord).filter_by(
                org_id=org.id,
                alert_type="CREDIT_EXHAUSTION_RISK",
                is_acknowledged=False,
            ).first()
            if not existing:
                alert = SupervisorAlertRecord(
                    org_id=org.id,
                    alert_type="CREDIT_EXHAUSTION_RISK",
                    severity="HIGH",
                    title=f"Credit Quota Exhaustion: {org.name}",
                    description=(
                        f"Organization '{org.name}' (org_id={org.id}, slug={org.slug}) has exhausted credit limits: "
                        f"Leads: {org.lead_credits_used}/{org.lead_credits_limit}, "
                        f"Outreach: {org.outreach_credits_used}/{org.outreach_credits_limit}."
                    ),
                    suggested_action="Prompt organization admin for package tier upgrade or credit add-on.",
                    metadata_json={
                        "org_id": org.id,
                        "tier": org.tier,
                        "lead_credits_used": org.lead_credits_used,
                        "lead_credits_limit": org.lead_credits_limit,
                        "outreach_credits_used": org.outreach_credits_used,
                        "outreach_credits_limit": org.outreach_credits_limit,
                    },
                )
                db.add(alert)
                created_alerts.append(alert)

    # ── 4. TRUST_CHAIN_INTEGRITY: Cryptographic chain verification ────────────
    chain_verif = verify_chain(db)
    chain_valid = chain_verif.get("chain_valid", chain_verif.get("valid", True))
    if not chain_valid:
        existing = db.query(SupervisorAlertRecord).filter_by(
            alert_type="TRUST_CHAIN_INTEGRITY",
            is_acknowledged=False,
        ).first()
        if not existing:
            alert = SupervisorAlertRecord(
                alert_type="TRUST_CHAIN_INTEGRITY",
                severity="CRITICAL",
                title="Trust Chain Cryptographic Hash Mismatch",
                description=(
                    f"Immutable audit ledger verification failed: block #{chain_verif.get('broken_index')} "
                    f"mismatch error: {chain_verif.get('error')}."
                ),
                suggested_action="Quarantine operations, inspect node keypair, and perform block re-attestation.",
                metadata_json=chain_verif,
            )
            db.add(alert)
            created_alerts.append(alert)

    # Commit generated alerts
    db.commit()

    # ── Audit & TrustBlock Sealing ────────────────────────────────────────────
    audit = AuditLog(
        task_id=scan_task_id,
        correlation_id=corr_id,
        agent_id=agent_id,
        capability_name=CAPABILITY_NAME,
        action="watchdog_scan",
        input_payload={"stale_minutes": stale_minutes},
        output_payload={
            "alerts_created": len(created_alerts),
            "chain_valid": chain_valid,
        },
        status="COMPLETED",
    )
    db.add(audit)

    block = seal_task_to_block(
        db=db,
        task_id=scan_task_id,
        capability_name=CAPABILITY_NAME,
        action="watchdog_scan",
        payload={
            "stale_minutes": stale_minutes,
            "alerts_created_count": len(created_alerts),
            "chain_valid": chain_valid,
        },
        sealed_by=agent_id,
    )

    # Fetch all active alerts and compute health score
    active_alerts = db.query(SupervisorAlertRecord).filter_by(is_acknowledged=False).all()
    total_tasks = db.query(TaskRecord).count()
    completed_tasks = db.query(TaskRecord).filter_by(status="COMPLETED").count()
    comp_rate = (completed_tasks / total_tasks) if total_tasks > 0 else 1.0
    pending_approvals = db.query(ApprovalRequest).filter_by(status="PENDING").count()

    health_score = calculate_system_health_score(
        active_alerts=active_alerts,
        task_completion_rate=comp_rate,
        approval_queue_depth=pending_approvals,
        chain_valid=chain_valid,
    )

    return {
        "status": "COMPLETED",
        "task_id": scan_task_id,
        "correlation_id": corr_id,
        "scan_timestamp": datetime.now(UTC).isoformat(),
        "alerts_created_count": len(created_alerts),
        "alerts_detected": len(created_alerts),
        "new_alerts_detected": len(created_alerts),
        "total_active_alerts_count": len(active_alerts),
        "health_score": health_score,
        "trust_block": {
            "index": block.index,
            "block_hash": block.block_hash,
            "prev_hash": block.prev_hash,
        },
        "newly_detected_alerts": [_serialize_alert(a) for a in created_alerts],
    }


def list_watchdog_alerts(
    db: Session,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query and filter SupervisorAlertRecords."""
    query = db.query(SupervisorAlertRecord)
    if status:
        stat_upper = status.strip().upper()
        if stat_upper in ("RESOLVED", "ACKNOWLEDGED"):
            query = query.filter(SupervisorAlertRecord.is_acknowledged.is_(True))
        elif stat_upper in ("OPEN", "PENDING", "ACTIVE"):
            query = query.filter(SupervisorAlertRecord.is_acknowledged.is_(False))

    if severity:
        query = query.filter(SupervisorAlertRecord.severity == severity.strip().upper())

    query = query.order_by(SupervisorAlertRecord.created_at.desc()).limit(limit)
    return [_serialize_alert(a) for a in query.all()]


def resolve_watchdog_alert(
    db: Session,
    alert_id: str,
    resolved_by: str = "owner",
    resolution_notes: str = "",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Resolve/acknowledge an alert with AuditLog and cryptographic TrustBlock sealing."""
    alert = db.query(SupervisorAlertRecord).filter_by(id=alert_id).first()
    if not alert:
        raise WatchdogAlertNotFound(f"Supervisor alert '{alert_id}' not found")

    alert.is_acknowledged = True
    alert.acknowledged_by = resolved_by
    alert.acknowledged_at = datetime.now(UTC)

    meta = alert.metadata_json or {}
    meta["status"] = "RESOLVED"
    meta["resolution_notes"] = resolution_notes
    meta["resolved_at"] = alert.acknowledged_at.isoformat()
    alert.metadata_json = meta

    corr_id = correlation_id or str(uuid.uuid4())
    audit = AuditLog(
        task_id=alert.task_id or alert.id,
        correlation_id=corr_id,
        agent_id=resolved_by,
        capability_name=CAPABILITY_NAME,
        action="watchdog_alert_resolved",
        input_payload={"alert_id": alert_id, "resolution_notes": resolution_notes},
        output_payload={"status": "RESOLVED", "resolved_by": resolved_by},
        status="COMPLETED",
    )
    db.add(audit)

    block = seal_task_to_block(
        db=db,
        task_id=alert.task_id or alert.id,
        capability_name=CAPABILITY_NAME,
        action="watchdog_alert_resolved",
        payload={
            "alert_id": alert_id,
            "resolved_by": resolved_by,
            "resolution_notes": resolution_notes,
        },
        sealed_by=resolved_by,
    )

    db.commit()

    res = _serialize_alert(alert)
    res["alert_id"] = alert.id
    res["block_hash"] = block.block_hash
    res["trust_block"] = {
        "index": block.index,
        "block_hash": block.block_hash,
    }
    return res


def get_system_control_telemetry(db: Session) -> dict[str, Any]:
    """Compile real-time operational controlling telemetry for L0 Owner cockpit."""
    total_tasks = db.query(TaskRecord).count()
    completed_tasks = db.query(TaskRecord).filter_by(status="COMPLETED").count()
    failed_tasks = db.query(TaskRecord).filter(TaskRecord.status.in_(("FAILED", "REJECTED"))).count()
    pending_tasks = db.query(TaskRecord).filter_by(status="PENDING").count()
    comp_rate = (completed_tasks / total_tasks * 100.0) if total_tasks > 0 else 100.0

    total_approvals = db.query(ApprovalRequest).count()
    pending_approvals = db.query(ApprovalRequest).filter_by(status="PENDING").count()
    approved_count = db.query(ApprovalRequest).filter_by(status="APPROVED").count()
    rejected_count = db.query(ApprovalRequest).filter_by(status="REJECTED").count()

    active_alerts = db.query(SupervisorAlertRecord).filter_by(is_acknowledged=False).all()
    by_severity = {
        "CRITICAL": sum(1 for a in active_alerts if a.severity == "CRITICAL"),
        "HIGH": sum(1 for a in active_alerts if a.severity == "HIGH"),
        "MEDIUM": sum(1 for a in active_alerts if a.severity == "MEDIUM"),
        "LOW": sum(1 for a in active_alerts if a.severity == "LOW"),
        "INFO": sum(1 for a in active_alerts if a.severity == "INFO"),
    }

    total_orders = db.query(OrderRecord).count()
    fulfilled_orders = db.query(OrderRecord).filter_by(status="FULFILLED").count()
    confirmed_orders = db.query(OrderRecord).filter_by(status="CONFIRMED").count()
    order_fulfill_rate = (fulfilled_orders / total_orders * 100.0) if total_orders > 0 else 100.0

    chain_verif = verify_chain(db)
    chain_valid = chain_verif.get("chain_valid", chain_verif.get("valid", True))

    health_score = calculate_system_health_score(
        active_alerts=active_alerts,
        task_completion_rate=(comp_rate / 100.0),
        approval_queue_depth=pending_approvals,
        chain_valid=chain_valid,
    )

    if health_score >= 85:
        op_status = "HEALTHY"
    elif health_score >= 60:
        op_status = "DEGRADED"
    else:
        op_status = "CRITICAL"

    tip_block = db.query(TrustBlock).order_by(TrustBlock.index.desc()).first()

    return {
        "health_score": health_score,
        "operational_status": op_status,
        "active_alerts_count": len(active_alerts),
        "active_alerts_total": len(active_alerts),
        "alerts_by_severity": by_severity,
        "operational_metrics": {
            "task_completion_rate": round(comp_rate / 100.0, 3),
            "pending_approval_queue_depth": pending_approvals,
            "order_fulfillment_rate": round(order_fulfill_rate / 100.0, 3),
        },
        "task_metrics": {
            "total": total_tasks,
            "completed": completed_tasks,
            "pending": pending_tasks,
            "failed": failed_tasks,
            "completion_rate_pct": round(comp_rate, 1),
        },
        "approval_metrics": {
            "total": total_approvals,
            "pending": pending_approvals,
            "approved": approved_count,
            "rejected": rejected_count,
            "queue_depth": pending_approvals,
        },
        "order_metrics": {
            "total": total_orders,
            "confirmed_pending_fulfillment": confirmed_orders,
            "fulfilled": fulfilled_orders,
            "fulfillment_rate_pct": round(order_fulfill_rate, 1),
        },
        "trust_chain": {
            "valid": chain_valid,
            "blocks_count": tip_block.index + 1 if tip_block else 0,
            "head_hash": tip_block.block_hash if tip_block else None,
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
