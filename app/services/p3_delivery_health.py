"""P3 Service Delivery State Machine, Output vs Outcome Tracking & Explainable Customer Health Engine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import (
    AuditLog,
    ConnectorStateRecord,
    ExecutionEvidenceRecord,
    InvoiceRecord,
    OrganizationRecord,
    P2CustomerEngagementRecord,
    P3CustomerAccountRecord,
    P3OnboardingWorkflowRecord,
    P3ServiceDeliveryRecord,
    P3SubscriptionEventRecord,
    P3SupportTicketRecord,
    SupervisorAlertRecord,
    WorkflowRunRecord,
)
from app.services.p3_customer_success import ensure_customer_account

DELIVERY_QUALITY_STATES = (
    "NOT_STARTED",
    "IN_PROGRESS",
    "WAITING_FOR_INPUT",
    "WAITING_FOR_APPROVAL",
    "QUALITY_REVIEW",
    "DELIVERED",
    "REVISION_REQUESTED",
    "ACCEPTED",
    "BLOCKED",
)

ALLOWED_DELIVERY_TRANSITIONS: dict[str, set[str]] = {
    "NOT_STARTED": {"IN_PROGRESS", "WAITING_FOR_INPUT", "BLOCKED"},
    "IN_PROGRESS": {"WAITING_FOR_INPUT", "WAITING_FOR_APPROVAL", "QUALITY_REVIEW", "BLOCKED"},
    "WAITING_FOR_INPUT": {"IN_PROGRESS", "BLOCKED"},
    "WAITING_FOR_APPROVAL": {"IN_PROGRESS", "QUALITY_REVIEW", "BLOCKED"},
    "QUALITY_REVIEW": {"DELIVERED", "REVISION_REQUESTED", "IN_PROGRESS", "BLOCKED"},
    "DELIVERED": {"ACCEPTED", "REVISION_REQUESTED"},
    "REVISION_REQUESTED": {"IN_PROGRESS", "QUALITY_REVIEW", "BLOCKED"},
    "BLOCKED": {"IN_PROGRESS", "WAITING_FOR_INPUT", "WAITING_FOR_APPROVAL"},
    "ACCEPTED": set(),
}

HEALTH_STATES = ("HEALTHY", "NEEDS_ATTENTION", "AT_RISK", "INSUFFICIENT_DATA")


def create_service_delivery(
    db: Session,
    *,
    org_id: str,
    title: str,
    original_requirement: str,
    approved_scope: list[str] | None = None,
    sku_key: str = "managed_seo_content_pilot",
    service_id: str = "seo_blog_copilot",
    p2_engagement_id: str | None = None,
    workflow_run_id: str | None = None,
    assigned_owner: str = "owner",
    assigned_agent_id: str | None = "service_delivery_coordinator_agent",
    input_data: dict[str, Any] | None = None,
    source_evidence: list[dict[str, Any]] | None = None,
    due_days: int = 7,
    actor: str = "owner",
) -> dict[str, Any]:
    """Create a tracked P3 customer service delivery item linked to org, workflow, and scope."""
    ensure_customer_account(db, org_id=org_id, sku_key=sku_key, commit=False)
    if p2_engagement_id:
        eng = db.get(P2CustomerEngagementRecord, p2_engagement_id)
        if not eng:
            raise ValueError(f"Customer engagement '{p2_engagement_id}' not found")
        if eng.org_id != org_id:
            raise PermissionError("Access denied: p2_engagement_id belongs to a different organization")
    if workflow_run_id:
        wf_run = db.get(WorkflowRunRecord, workflow_run_id)
        if not wf_run:
            raise ValueError(f"Workflow run '{workflow_run_id}' not found")
        if wf_run.org_id != org_id:
            raise PermissionError("Access denied: workflow_run_id belongs to a different organization")
    now = datetime.now(UTC)

    delivery = P3ServiceDeliveryRecord(
        org_id=org_id,
        p2_engagement_id=p2_engagement_id,
        sku_key=sku_key,
        service_id=service_id,
        workflow_run_id=workflow_run_id,
        title=title.strip(),
        original_requirement=original_requirement.strip(),
        approved_scope_json=[str(s).strip() for s in (approved_scope or []) if str(s).strip()],
        assigned_owner=assigned_owner.strip(),
        assigned_agent_id=assigned_agent_id,
        input_data_json=dict(input_data or {}),
        source_evidence_json=list(source_evidence or []),
        execution_history_json=[
            {"event": "CREATED", "actor": actor, "at": now.isoformat(), "workflow_run_id": workflow_run_id}
        ],
        approval_checkpoints_json=[],
        output_artifacts_json={},
        quality_checks_json={"passed": False, "checks": [], "reviewed_by": None, "reviewed_at": None},
        quality_state="NOT_STARTED",
        output_metrics_json={
            "metric_class": "OUTPUT_DELIVERABLES",
            "content_completed": 0,
            "published_count": 0,
            "technical_issues_addressed": 0,
            "production_time_minutes": 0,
        },
        outcome_metrics_json={
            "metric_class": "BUSINESS_OUTCOMES",
            "gsc_connected": False,
            "organic_traffic": None,
            "impressions": None,
            "keyword_visibility": None,
            "customer_approved_outcomes": [],
            "attribution_evidence_level": "NONE",
            "claimed_askforwrite_caused": False,
            "attribution_note": "No verified Search Console / baseline attribution data recorded yet.",
        },
        due_date=now + timedelta(days=max(1, int(due_days))),
        created_at=now,
        updated_at=now,
    )
    db.add(delivery)
    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id=actor,
            capability_name="p3_service_delivery",
            action="service_delivery_created",
            input_payload={"org_id": org_id, "service_id": service_id, "title": title},
            output_payload={"delivery_id": delivery.id, "quality_state": "NOT_STARTED"},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(delivery)
    return serialize_service_delivery(delivery)


def transition_delivery_quality_state(
    db: Session,
    *,
    delivery_id: str,
    target_state: str,
    note: str | None = None,
    output_artifacts: dict[str, Any] | None = None,
    approval_checkpoint: dict[str, Any] | None = None,
    source_evidence_item: dict[str, Any] | None = None,
    org_id_scope: str | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Validate and execute a delivery quality state transition with mandatory evidence on DELIVERED."""
    delivery = db.get(P3ServiceDeliveryRecord, delivery_id)
    if not delivery:
        raise ValueError(f"Service delivery '{delivery_id}' not found")
    if org_id_scope and delivery.org_id != org_id_scope:
        raise PermissionError("Cross-tenant service delivery access denied")

    clean_target = target_state.strip().upper()
    if clean_target not in DELIVERY_QUALITY_STATES:
        raise ValueError(f"Unsupported delivery quality state '{target_state}'")

    current = delivery.quality_state
    now = datetime.now(UTC)

    if clean_target != current:
        allowed = ALLOWED_DELIVERY_TRANSITIONS.get(current, set())
        if clean_target not in allowed:
            raise ValueError(f"Invalid delivery quality state transition: {current} -> {clean_target}")

    if output_artifacts:
        merged_art = {**(delivery.output_artifacts_json or {}), **output_artifacts}
        delivery.output_artifacts_json = merged_art
        flag_modified(delivery, "output_artifacts_json")

    if source_evidence_item:
        ev = list(delivery.source_evidence_json or [])
        ev.append({**source_evidence_item, "recorded_at": now.isoformat()})
        delivery.source_evidence_json = ev
        flag_modified(delivery, "source_evidence_json")

    if approval_checkpoint:
        cps = list(delivery.approval_checkpoints_json or [])
        cps.append({**approval_checkpoint, "recorded_at": now.isoformat(), "recorded_by": actor})
        delivery.approval_checkpoints_json = cps
        flag_modified(delivery, "approval_checkpoints_json")

    if clean_target == "DELIVERED":
        qc = delivery.quality_checks_json or {}
        if not qc.get("passed"):
            raise ValueError("Cannot mark delivery DELIVERED before quality_checks pass (passed=True).")
        if not (delivery.output_artifacts_json or {}):
            raise ValueError("Cannot mark delivery DELIVERED without at least one output artifact URL or reference.")
        delivery.delivered_at = now

    if clean_target == "ACCEPTED":
        delivery.accepted_at = now

    if clean_target == "REVISION_REQUESTED":
        max_rev = int((delivery.input_data_json or {}).get("max_revisions") or 0)
        prior_revs = sum(
            1
            for ev in (delivery.execution_history_json or [])
            if isinstance(ev, dict) and str(ev.get("event") or "").endswith("_TO_REVISION_REQUESTED")
        )
        if max_rev > 0 and prior_revs >= max_rev:
            raise ValueError(
                f"Revision limit reached ({prior_revs}/{max_rev} included revision rounds used for this deliverable)."
            )
        if note:
            delivery.revision_notes = note.strip()

    hist = list(delivery.execution_history_json or [])
    hist.append(
        {
            "event": f"STATE_{current}_TO_{clean_target}",
            "note": note,
            "actor": actor,
            "at": now.isoformat(),
        }
    )
    delivery.execution_history_json = hist
    delivery.quality_state = clean_target
    delivery.updated_at = now
    flag_modified(delivery, "execution_history_json")

    acc = db.query(P3CustomerAccountRecord).filter_by(org_id=delivery.org_id).first()
    if acc:
        acc.last_customer_engagement_at = now
        acc.updated_at = now
        db.add(acc)

    db.add(delivery)
    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id=actor,
            capability_name="p3_service_delivery",
            action="delivery_state_transition",
            input_payload={"delivery_id": delivery_id, "org_id": delivery.org_id, "from": current, "to": clean_target},
            output_payload={"quality_state": clean_target},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(delivery)
    return serialize_service_delivery(delivery)


def submit_delivery_quality_check(
    db: Session,
    *,
    delivery_id: str,
    passed: bool,
    checks: list[dict[str, Any]] | dict[str, Any],
    reviewer: str = "qa_review_agent",
    output_artifacts: dict[str, Any] | None = None,
    org_id_scope: str | None = None,
) -> dict[str, Any]:
    """Record explicit QA verification checklist on a delivery record."""
    delivery = db.get(P3ServiceDeliveryRecord, delivery_id)
    if not delivery:
        raise ValueError(f"Service delivery '{delivery_id}' not found")
    if org_id_scope and delivery.org_id != org_id_scope:
        raise PermissionError("Cross-tenant service delivery access denied")

    now = datetime.now(UTC)
    if output_artifacts:
        delivery.output_artifacts_json = {**(delivery.output_artifacts_json or {}), **output_artifacts}
        flag_modified(delivery, "output_artifacts_json")

    delivery.quality_checks_json = {
        "passed": bool(passed),
        "checks": checks,
        "reviewed_by": reviewer,
        "reviewed_at": now.isoformat(),
    }
    flag_modified(delivery, "quality_checks_json")

    if delivery.quality_state in ("NOT_STARTED", "IN_PROGRESS", "WAITING_FOR_APPROVAL", "QUALITY_REVIEW", "REVISION_REQUESTED"):
        delivery.quality_state = "QUALITY_REVIEW" if passed else "REVISION_REQUESTED"
    delivery.updated_at = now
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return serialize_service_delivery(delivery)


def record_delivery_metrics_and_outcomes(
    db: Session,
    *,
    delivery_id: str,
    output_metrics: dict[str, Any] | None = None,
    outcome_metrics: dict[str, Any] | None = None,
    org_id_scope: str | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Record output metrics separately from business outcome metrics with strict causal attribution guard."""
    delivery = db.get(P3ServiceDeliveryRecord, delivery_id)
    if not delivery:
        raise ValueError(f"Service delivery '{delivery_id}' not found")
    if org_id_scope and delivery.org_id != org_id_scope:
        raise PermissionError("Cross-tenant service delivery access denied")

    now = datetime.now(UTC)
    if output_metrics:
        current_out = dict(delivery.output_metrics_json or {})
        current_out.update(output_metrics)
        current_out["metric_class"] = "OUTPUT_DELIVERABLES"
        current_out["updated_at"] = now.isoformat()
        delivery.output_metrics_json = current_out
        flag_modified(delivery, "output_metrics_json")

    if outcome_metrics:
        current_res = dict(delivery.outcome_metrics_json or {})
        merged = {**current_res, **outcome_metrics}
        gsc_connected = bool(merged.get("gsc_connected", False))
        evidence_level = str(merged.get("attribution_evidence_level") or "NONE").upper()
        claimed_caused = bool(merged.get("claimed_askforwrite_caused", False))
        evidence_refs = merged.get("attribution_evidence_refs") or []

        if claimed_caused and not (gsc_connected and evidence_level == "GSC_VERIFIED_WITH_BASELINE" and evidence_refs):
            raise ValueError(
                "Honesty guard: Cannot claim SEO ranking, traffic, lead, or revenue uplift was caused by AskforWrite "
                "unless gsc_connected=True, attribution_evidence_level='GSC_VERIFIED_WITH_BASELINE', and evidence refs exist."
            )

        if (merged.get("organic_traffic") is not None or merged.get("impressions") is not None) and not gsc_connected:
            merged["attribution_evidence_level"] = (
                "CUSTOMER_REPORTED" if evidence_level == "NONE" else evidence_level
            )
            merged["attribution_note"] = (
                merged.get("attribution_note")
                or "Search Console not connected; values are unattributed/customer-reported."
            )

        merged["metric_class"] = "BUSINESS_OUTCOMES"
        merged["updated_at"] = now.isoformat()
        delivery.outcome_metrics_json = merged
        flag_modified(delivery, "outcome_metrics_json")

    delivery.updated_at = now
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return serialize_service_delivery(delivery)


def compute_customer_health(
    db: Session,
    *,
    org_id: str,
    save_snapshot: bool = True,
) -> dict[str, Any]:
    """Compute explainable Customer Health Score with weighted dimensions, data freshness & missing gaps."""
    account = ensure_customer_account(db, org_id=org_id, commit=False)
    org = db.get(OrganizationRecord, org_id)
    now = datetime.now(UTC)

    dimensions: list[dict[str, Any]] = []
    missing_dimensions: list[str] = []

    def _add_dim(key: str, weight: float, score: float | None, evidence: str, updated_at: datetime | None) -> None:
        if score is None:
            missing_dimensions.append(key)
            dimensions.append(
                {
                    "dimension": key,
                    "weight": weight,
                    "score": None,
                    "status": "MISSING_DATA",
                    "evidence": evidence,
                    "freshness_at": updated_at.isoformat() if updated_at else None,
                }
            )
        else:
            bounded = max(0.0, min(100.0, round(score, 1)))
            dimensions.append(
                {
                    "dimension": key,
                    "weight": weight,
                    "score": bounded,
                    "status": "SCORED",
                    "evidence": evidence,
                    "freshness_at": updated_at.isoformat() if updated_at else now.isoformat(),
                }
            )

    # 1. Onboarding Completion (15%)
    onboardings = db.query(P3OnboardingWorkflowRecord).filter_by(org_id=org_id).all()
    if onboardings:
        latest_ob = max(onboardings, key=lambda o: o.updated_at)
        ob_score = float(latest_ob.progress_pct or 0.0)
        if latest_ob.blockers_json:
            ob_score = max(0.0, ob_score - (15.0 * len(latest_ob.blockers_json)))
        _add_dim(
            "onboarding_completion",
            0.15,
            ob_score,
            f"Onboarding progress {latest_ob.progress_pct}%, blockers={len(latest_ob.blockers_json or [])}, status={latest_ob.status}",
            latest_ob.updated_at,
        )
    else:
        _add_dim("onboarding_completion", 0.15, None, "No onboarding workflow started", None)

    # 2. Product Adoption & Usage (15%)
    wf_runs = db.query(WorkflowRunRecord).filter_by(org_id=org_id).all()
    ev_rows = db.query(ExecutionEvidenceRecord).filter_by(tenant_id=org_id).all()
    if wf_runs or ev_rows or (org and org.lead_credits_used > 0):
        total_runs = len(wf_runs) + len(ev_rows)
        adoption = min(100.0, 40.0 + total_runs * 15.0)
        latest_act = max(
            [r.updated_at for r in wf_runs] + [e.started_at for e in ev_rows],
            default=org.updated_at if org else now,
        )
        _add_dim(
            "product_adoption_usage",
            0.15,
            adoption,
            f"{len(wf_runs)} workflow run(s), {len(ev_rows)} execution evidence record(s)",
            latest_act,
        )
    else:
        _add_dim("product_adoption_usage", 0.15, None, "No recorded workflow runs or execution usage", None)

    # 3. Service Delivery Success & Timeliness (20%)
    deliveries = db.query(P3ServiceDeliveryRecord).filter_by(org_id=org_id).all()
    if deliveries:
        good = sum(1 for d in deliveries if d.quality_state in ("DELIVERED", "ACCEPTED"))
        revisions = sum(1 for d in deliveries if d.quality_state == "REVISION_REQUESTED")
        blocked = sum(1 for d in deliveries if d.quality_state == "BLOCKED")
        overdue = sum(
            1
            for d in deliveries
            if d.due_date
            and (d.due_date if d.due_date.tzinfo else d.due_date.replace(tzinfo=UTC)) < now
            and d.quality_state not in ("DELIVERED", "ACCEPTED")
        )
        del_score = 100.0 if good == len(deliveries) else max(0.0, 80.0 - revisions * 15.0 - blocked * 30.0 - overdue * 25.0)
        latest_del = max(d.updated_at for d in deliveries)
        _add_dim(
            "service_delivery_success",
            0.20,
            del_score,
            f"deliveries={len(deliveries)}, accepted_or_delivered={good}, blocked={blocked}, overdue={overdue}",
            latest_del,
        )
    else:
        _add_dim("service_delivery_success", 0.20, None, "No service delivery records tracked yet", None)

    # 4. Workflow Reliability (10%)
    if wf_runs:
        failed = sum(1 for r in wf_runs if r.status in ("FAILED", "BLOCKED"))
        fail_rate = failed / len(wf_runs)
        wf_score = max(0.0, (1.0 - fail_rate) * 100.0)
        _add_dim(
            "workflow_reliability",
            0.10,
            wf_score,
            f"total_runs={len(wf_runs)}, failed_or_blocked={failed}",
            max(r.updated_at for r in wf_runs),
        )
    else:
        _add_dim("workflow_reliability", 0.10, None, "No workflow execution history yet", None)

    # 5. Support Requests & Unresolved Issues (15%)
    tickets = db.query(P3SupportTicketRecord).filter_by(org_id=org_id).all()
    if tickets:
        unresolved = [t for t in tickets if t.status not in ("RESOLVED", "CLOSED")]
        escalated = sum(1 for t in unresolved if t.status == "ESCALATED" or t.priority == "URGENT")
        sup_score = max(0.0, 100.0 - len(unresolved) * 15.0 - escalated * 25.0)
        _add_dim(
            "support_responsiveness",
            0.15,
            sup_score,
            f"total_tickets={len(tickets)}, unresolved={len(unresolved)}, escalated_or_urgent={escalated}",
            max(t.updated_at for t in tickets),
        )
    else:
        _add_dim("support_responsiveness", 0.15, None, "No support tickets submitted yet", None)

    # 6. Payment Reliability (15%)
    invoices = db.query(InvoiceRecord).filter_by(org_id=org_id).all()
    sub_events = (
        db.query(P3SubscriptionEventRecord)
        .filter_by(org_id=org_id)
        .order_by(P3SubscriptionEventRecord.created_at.desc())
        .all()
    )
    if invoices or sub_events:
        latest_sub_state = sub_events[0].subscription_state if sub_events else "ACTIVE"
        failed_inv = sum(1 for i in invoices if i.status in ("failed", "refunded"))
        pay_score = 100.0
        if latest_sub_state in ("PAST_DUE", "PAUSED"):
            pay_score -= 45.0
        elif latest_sub_state in ("CANCELLED", "EXPIRED", "REFUNDED"):
            pay_score = 10.0
        pay_score = max(0.0, pay_score - failed_inv * 25.0)
        latest_pay_at = max(
            [i.updated_at for i in invoices] + [e.created_at for e in sub_events],
        )
        _add_dim(
            "payment_reliability",
            0.15,
            pay_score,
            f"subscription_state={latest_sub_state}, invoices={len(invoices)}, failed_or_refunded={failed_inv}",
            latest_pay_at,
        )
    else:
        _add_dim("payment_reliability", 0.15, None, "No payment or subscription records yet", None)

    # 7. Customer Feedback / CSAT (10%)
    csat_scores = [float(t.csat_rating) for t in tickets if t.csat_rating is not None]
    p2_engs = db.query(P2CustomerEngagementRecord).filter_by(org_id=org_id).all()
    for eng in p2_engs:
        if eng.customer_feedback_json and eng.customer_feedback_json.get("rating") is not None:
            csat_scores.append(float(eng.customer_feedback_json["rating"]))
    if csat_scores:
        avg_rating = sum(csat_scores) / len(csat_scores)
        fb_score = (avg_rating / 5.0) * 100.0
        _add_dim(
            "customer_feedback",
            0.10,
            fb_score,
            f"avg_rating={round(avg_rating, 2)}/5 from {len(csat_scores)} rating(s)",
            now,
        )
    else:
        _add_dim("customer_feedback", 0.10, None, "No CSAT or pilot rating recorded yet", None)

    scored_dims = [d for d in dimensions if d["score"] is not None]
    total_scored_weight = sum(d["weight"] for d in scored_dims)

    # Require minimum 3 real scored dimensions before publishing a non-insufficient health score
    if len(scored_dims) < 3 or total_scored_weight <= 0:
        health_state = "INSUFFICIENT_DATA"
        overall_score: float | None = None
        freshness = "EMPTY" if not scored_dims else "PARTIAL"
    else:
        overall_score = round(
            sum(float(d["score"]) * float(d["weight"]) for d in scored_dims) / total_scored_weight,
            1,
        )
        # Check freshness staleness (> 14 days old)
        fresh_dates: list[datetime] = []
        for d in scored_dims:
            if d["freshness_at"]:
                dt = datetime.fromisoformat(d["freshness_at"])
                fresh_dates.append(dt if dt.tzinfo else dt.replace(tzinfo=UTC))
        newest = max(fresh_dates) if fresh_dates else now
        freshness = "STALE" if (now - newest) > timedelta(days=14) else "FRESH"

        latest_sub_state = sub_events[0].subscription_state if sub_events else ""
        if overall_score < 50.0 or latest_sub_state in ("PAST_DUE", "EXPIRED", "REFUNDED"):
            health_state = "AT_RISK"
        elif overall_score < 75.0 or freshness == "STALE":
            health_state = "NEEDS_ATTENTION"
        else:
            health_state = "HEALTHY"

    result = {
        "org_id": org_id,
        "health_state": health_state,
        "overall_score": overall_score,
        "scored_dimensions_count": len(scored_dims),
        "available_dimensions": [d["dimension"] for d in scored_dims],
        "missing_dimensions": missing_dimensions,
        "data_freshness": freshness,
        "breakdown": dimensions,
        "evaluated_at": now.isoformat(),
    }

    if save_snapshot:
        account.health_snapshot_json = result
        account.updated_at = now
        flag_modified(account, "health_snapshot_json")
        db.add(account)
        db.commit()

    return result


def generate_internal_health_alerts(db: Session, *, org_id: str) -> list[dict[str, Any]]:
    """Detect real operational risk signals & create internal SupervisorAlertRecords (zero auto external sends)."""
    account = ensure_customer_account(db, org_id=org_id, commit=False)
    now = datetime.now(UTC)
    alerts_to_create: list[tuple[str, str, str, str, str]] = []

    # 1. Onboarding stalls / overdue / blockers
    for ob in db.query(P3OnboardingWorkflowRecord).filter_by(org_id=org_id).all():
        if ob.status != "ACTIVATED":
            if ob.blockers_json:
                alerts_to_create.append(
                    (
                        "ONBOARDING_STALLED",
                        "HIGH",
                        f"Onboarding blocked for org {org_id}",
                        f"Onboarding blockers detected: {ob.blockers_json}",
                        "Resolve blocker tasks in Customer 360 -> Onboarding Checklist and notify assigned owner.",
                    )
                )
            else:
                overdue_tasks = [
                    t.get("task_key")
                    for t in (ob.tasks_json or [])
                    if not t.get("completed")
                    and t.get("deadline_at")
                    and datetime.fromisoformat(t["deadline_at"]) < now
                ]
                if overdue_tasks:
                    alerts_to_create.append(
                        (
                            "ONBOARDING_STALLED",
                            "MEDIUM",
                            f"Onboarding overdue tasks for org {org_id}",
                            f"Overdue onboarding tasks: {overdue_tasks}",
                            "Review onboarding task deadlines and schedule a customer kickoff follow-up.",
                        )
                    )

    # 2. Critical connector failures
    for conn in db.query(ConnectorStateRecord).filter_by(org_id=org_id).all():
        if conn.connection_status in ("ERROR", "BLOCKED", "INVALID"):
            alerts_to_create.append(
                (
                    "CONNECTOR_FAILURE",
                    "HIGH",
                    f"Critical connector {conn.connector_id} failed for org {org_id}",
                    f"Connector {conn.connector_id} status={conn.connection_status}: {conn.last_error or 'verification failed'}",
                    "Re-verify connector credentials in Connected Tools before running scheduled workflows.",
                )
            )

    # 3. Repeated workflow failures (>= 2 failures)
    failed_runs = (
        db.query(WorkflowRunRecord)
        .filter(WorkflowRunRecord.org_id == org_id, WorkflowRunRecord.status.in_(("FAILED", "BLOCKED")))
        .count()
    )
    if failed_runs >= 2:
        alerts_to_create.append(
            (
                "REPEATED_WORKFLOW_FAILURES",
                "HIGH",
                f"Repeated workflow failures ({failed_runs}) for org {org_id}",
                f"{failed_runs} workflow runs ended FAILED/BLOCKED for organization {org_id}.",
                "Inspect dead-letter workflow incidents, verify connector quotas, and retry from Ops Readiness.",
            )
        )

    # 4. Missed delivery deadlines
    overdue_deliveries = [
        d.title
        for d in db.query(P3ServiceDeliveryRecord).filter_by(org_id=org_id).all()
        if d.due_date
        and (d.due_date if d.due_date.tzinfo else d.due_date.replace(tzinfo=UTC)) < now
        and d.quality_state not in ("DELIVERED", "ACCEPTED")
    ]
    if overdue_deliveries:
        alerts_to_create.append(
            (
                "DELIVERY_DEADLINE_MISSED",
                "HIGH",
                f"Delivery deadline missed for org {org_id}",
                f"Overdue service deliveries: {overdue_deliveries}",
                "Prioritize QA review and human handover for overdue deliverables.",
            )
        )

    # 5. Unresolved support tickets
    open_tickets = (
        db.query(P3SupportTicketRecord)
        .filter(
            P3SupportTicketRecord.org_id == org_id,
            P3SupportTicketRecord.status.notin_(("RESOLVED", "CLOSED")),
        )
        .all()
    )
    urgent_or_aged = [
        t.ticket_number
        for t in open_tickets
        if t.priority in ("HIGH", "URGENT") or t.status == "ESCALATED"
        or (now - (t.created_at if t.created_at.tzinfo else t.created_at.replace(tzinfo=UTC))) > timedelta(hours=24)
    ]
    if urgent_or_aged:
        alerts_to_create.append(
            (
                "UNRESOLVED_SUPPORT_TICKET",
                "HIGH",
                f"Unresolved support requests ({len(urgent_or_aged)}) for org {org_id}",
                f"Open urgent/aged support tickets: {urgent_or_aged}",
                "Run AI Support Triage and review/approve external response in Support Desk.",
            )
        )

    # 6. Subscription payment failures
    latest_sub_evt = (
        db.query(P3SubscriptionEventRecord)
        .filter_by(org_id=org_id)
        .order_by(P3SubscriptionEventRecord.created_at.desc())
        .first()
    )
    if latest_sub_evt and latest_sub_evt.subscription_state == "PAST_DUE":
        alerts_to_create.append(
            (
                "SUBSCRIPTION_PAYMENT_FAILED",
                "CRITICAL",
                f"Subscription payment past due for org {org_id}",
                f"Subscription in PAST_DUE state (grace_until={latest_sub_evt.grace_until}).",
                "Coordinate verified payment recovery before grace window expires.",
            )
        )

    # 7. Renewal approaching without sufficient recent engagement
    if account.renewal_date:
        ren_dt = account.renewal_date if account.renewal_date.tzinfo else account.renewal_date.replace(tzinfo=UTC)
        last_eng = account.last_customer_engagement_at
        eng_dt = (last_eng if last_eng.tzinfo else last_eng.replace(tzinfo=UTC)) if last_eng else None
        if timedelta(days=0) <= (ren_dt - now) <= timedelta(days=14):
            if not eng_dt or (now - eng_dt) > timedelta(days=10):
                alerts_to_create.append(
                    (
                        "RENEWAL_LOW_ENGAGEMENT",
                        "MEDIUM",
                        f"Approaching renewal with low engagement for org {org_id}",
                        f"Renewal due {ren_dt.date().isoformat()} with stale recent customer engagement.",
                        "Schedule founder check-in and share verified delivery summary.",
                    )
                )

    created_alerts: list[dict[str, Any]] = []
    existing_open = {
        a.alert_type
        for a in db.query(SupervisorAlertRecord).filter_by(org_id=org_id, is_acknowledged=False).all()
    }
    for a_type, sev, title, desc, next_step in alerts_to_create:
        if a_type in existing_open:
            continue
        alert = SupervisorAlertRecord(
            org_id=org_id,
            alert_type=a_type,
            severity=sev,
            title=title,
            description=desc,
            suggested_action=next_step,
            is_acknowledged=False,
            metadata_json={"internal_only": True, "auto_external_communication_sent": False},
        )
        db.add(alert)
        db.flush()
        created_alerts.append(
            {
                "alert_id": alert.id,
                "org_id": org_id,
                "alert_type": a_type,
                "severity": sev,
                "title": title,
                "description": desc,
                "suggested_action": next_step,
                "auto_external_communication_sent": False,
            }
        )
    if created_alerts:
        db.commit()
    return created_alerts


def list_service_deliveries(
    db: Session,
    *,
    org_id: str | None = None,
    quality_state: str | None = None,
) -> list[dict[str, Any]]:
    """List service deliveries optionally filtered by organization and quality state."""
    q = db.query(P3ServiceDeliveryRecord)
    if org_id:
        q = q.filter(P3ServiceDeliveryRecord.org_id == org_id)
    if quality_state:
        q = q.filter(P3ServiceDeliveryRecord.quality_state == quality_state.strip().upper())
    rows = q.order_by(P3ServiceDeliveryRecord.created_at.desc()).all()
    return [serialize_service_delivery(d) for d in rows]


def serialize_service_delivery(d: P3ServiceDeliveryRecord) -> dict[str, Any]:
    return {
        "delivery_id": d.id,
        "org_id": d.org_id,
        "p2_engagement_id": d.p2_engagement_id,
        "sku_key": d.sku_key,
        "service_id": d.service_id,
        "workflow_run_id": d.workflow_run_id,
        "title": d.title,
        "original_requirement": d.original_requirement,
        "approved_scope": d.approved_scope_json or [],
        "assigned_owner": d.assigned_owner,
        "assigned_agent_id": d.assigned_agent_id,
        "input_data": d.input_data_json or {},
        "source_evidence": d.source_evidence_json or [],
        "execution_history": d.execution_history_json or [],
        "approval_checkpoints": d.approval_checkpoints_json or [],
        "output_artifacts": d.output_artifacts_json or {},
        "quality_checks": d.quality_checks_json or {},
        "quality_state": d.quality_state,
        "output_metrics": d.output_metrics_json or {},
        "outcome_metrics": d.outcome_metrics_json or {},
        "revision_notes": d.revision_notes,
        "due_date": d.due_date.isoformat() if d.due_date else None,
        "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
        "accepted_at": d.accepted_at.isoformat() if d.accepted_at else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }
