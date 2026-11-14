"""P3 Support Ticketing, AI Support Assistant (HITL Sensitive Reply Gate) & Product Improvement Loop."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import (
    ApprovalRequest,
    AuditLog,
    P2CustomerEngagementRecord,
    P3CustomerAccountRecord,
    P3ImprovementItemRecord,
    P3OnboardingWorkflowRecord,
    P3ServiceDeliveryRecord,
    P3SupportTicketRecord,
    TaskRecord,
    WorkflowRunRecord,
)
from app.services.execution_guard import redact_secrets
from app.services.p3_customer_success import ensure_customer_account

TICKET_STATES = (
    "OPEN",
    "TRIAGED",
    "IN_PROGRESS",
    "WAITING_FOR_CUSTOMER",
    "ESCALATED",
    "RESOLVED",
    "CLOSED",
)

TICKET_PRIORITIES = ("LOW", "MEDIUM", "HIGH", "URGENT")

TICKET_CATEGORIES = (
    "onboarding",
    "delivery",
    "billing_renewal",
    "technical_connector",
    "account_access",
    "refund_dispute",
    "feature_request",
    "general",
)

ALLOWED_TICKET_TRANSITIONS: dict[str, set[str]] = {
    "OPEN": {"TRIAGED", "IN_PROGRESS", "WAITING_FOR_CUSTOMER", "ESCALATED", "RESOLVED", "CLOSED"},
    "TRIAGED": {"IN_PROGRESS", "WAITING_FOR_CUSTOMER", "ESCALATED", "RESOLVED", "CLOSED"},
    "IN_PROGRESS": {"WAITING_FOR_CUSTOMER", "ESCALATED", "RESOLVED", "CLOSED"},
    "WAITING_FOR_CUSTOMER": {"IN_PROGRESS", "ESCALATED", "RESOLVED", "CLOSED"},
    "ESCALATED": {"IN_PROGRESS", "WAITING_FOR_CUSTOMER", "RESOLVED", "CLOSED"},
    "RESOLVED": {"IN_PROGRESS", "CLOSED"},
    "CLOSED": {"OPEN"},
}

_SENSITIVE_REPLY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("refund_or_credit", re.compile(r"\b(refund|chargeback|reimburse|credit\s+back|full\s+waiver)\b", re.IGNORECASE)),
    ("commercial_promise_or_discount", re.compile(r"\b(\d+%\s*off|discount|guarantee\s+(ranking|#1|roi|traffic)|custom\s+pricing)\b", re.IGNORECASE)),
    ("legal_or_contract", re.compile(r"\b(legal|lawsuit|indemnif|liability|contract\s+amendment|termination\s+waiver|sla\s+penalty)\b", re.IGNORECASE)),
    ("sensitive_access_change", re.compile(r"\b(reset\s+owner|elevate\s+role|admin\s+access|bypass\s+auth|share\s+secret)\b", re.IGNORECASE)),
)


def _detect_sensitive_reply_flags(text: str, category: str = "") -> list[str]:
    flags = [name for name, rx in _SENSITIVE_REPLY_PATTERNS if rx.search(text or "")]
    if category in ("refund_dispute", "account_access") and category not in flags:
        flags.append(f"sensitive_category:{category}")
    return flags


def create_support_ticket(
    db: Session,
    *,
    org_id: str,
    subject: str,
    description: str,
    category: str = "general",
    priority: str = "MEDIUM",
    created_by_user_id: str | None = None,
    created_by_email: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    assigned_owner: str = "support_team",
) -> dict[str, Any]:
    """Create an organization-scoped customer support ticket with sanitized attachments."""
    ensure_customer_account(db, org_id=org_id, commit=False)
    clean_cat = category.strip().lower()
    if clean_cat not in TICKET_CATEGORIES:
        clean_cat = "general"
    clean_prio = priority.strip().upper()
    if clean_prio not in TICKET_PRIORITIES:
        clean_prio = "MEDIUM"

    safe_attachments = [redact_secrets(a) for a in (attachments or [])]
    ticket_num = f"AFW-{datetime.now(UTC).strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    now = datetime.now(UTC)

    ticket = P3SupportTicketRecord(
        ticket_number=ticket_num,
        org_id=org_id,
        created_by_user_id=created_by_user_id,
        created_by_email=created_by_email,
        category=clean_cat,
        priority=clean_prio,
        assigned_owner=assigned_owner.strip(),
        assigned_agent_id="cs_support_specialist_agent",
        status="OPEN",
        subject=str(redact_secrets(subject)).strip(),
        description=str(redact_secrets(description)).strip(),
        attachments_json=safe_attachments,
        internal_notes_json=[],
        messages_json=[
            {
                "message_id": f"msg-{uuid.uuid4().hex[:10]}",
                "visibility": "customer_visible",
                "sender_type": "customer",
                "sender": created_by_email or created_by_user_id or org_id,
                "body": str(redact_secrets(description)).strip(),
                "created_at": now.isoformat(),
            }
        ],
        created_at=now,
        updated_at=now,
    )
    db.add(ticket)
    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id=created_by_email or org_id,
            capability_name="p3_support",
            action="support_ticket_created",
            input_payload={"org_id": org_id, "ticket_number": ticket_num, "category": clean_cat, "priority": clean_prio},
            output_payload={"ticket_id": ticket.id, "status": "OPEN"},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(ticket)
    return serialize_support_ticket(ticket, include_internal=True)


def list_support_tickets(
    db: Session,
    *,
    org_id: str | None = None,
    status: str | None = None,
    include_internal: bool = False,
) -> list[dict[str, Any]]:
    q = db.query(P3SupportTicketRecord)
    if org_id:
        q = q.filter(P3SupportTicketRecord.org_id == org_id)
    if status:
        q = q.filter(P3SupportTicketRecord.status == status.strip().upper())
    rows = q.order_by(P3SupportTicketRecord.updated_at.desc()).all()
    return [serialize_support_ticket(r, include_internal=include_internal) for r in rows]


def transition_ticket_state(
    db: Session,
    *,
    ticket_id: str,
    target_state: str,
    assigned_owner: str | None = None,
    escalation_reason: str | None = None,
    internal_note: str | None = None,
    org_id_scope: str | None = None,
    actor: str = "support_team",
) -> dict[str, Any]:
    """Validate and update ticket status with SLA resolution tracking and strict org scoping."""
    ticket = db.get(P3SupportTicketRecord, ticket_id)
    if not ticket:
        raise ValueError(f"Support ticket '{ticket_id}' not found")
    if org_id_scope and ticket.org_id != org_id_scope:
        raise PermissionError("Cross-tenant support ticket access denied")

    clean_target = target_state.strip().upper()
    if clean_target not in TICKET_STATES:
        raise ValueError(f"Unsupported ticket state '{target_state}'")

    now = datetime.now(UTC)
    if clean_target != ticket.status:
        allowed = ALLOWED_TICKET_TRANSITIONS.get(ticket.status, set())
        if clean_target not in allowed:
            raise ValueError(f"Invalid ticket transition: {ticket.status} -> {clean_target}")
        ticket.status = clean_target

    if assigned_owner is not None:
        ticket.assigned_owner = assigned_owner.strip() or ticket.assigned_owner

    if clean_target == "ESCALATED":
        ticket.escalated_at = ticket.escalated_at or now
        ticket.escalation_reason = (escalation_reason or "Escalated for owner/specialist review").strip()
        if ticket.priority in ("LOW", "MEDIUM"):
            ticket.priority = "HIGH"

    if clean_target in ("RESOLVED", "CLOSED"):
        if not ticket.resolved_at:
            ticket.resolved_at = now
        created_utc = ticket.created_at if ticket.created_at.tzinfo else ticket.created_at.replace(tzinfo=UTC)
        ticket.resolution_seconds = max(0, int((now - created_utc).total_seconds()))

    if internal_note:
        notes = list(ticket.internal_notes_json or [])
        notes.append({"author": actor, "note": str(redact_secrets(internal_note)).strip(), "at": now.isoformat()})
        ticket.internal_notes_json = notes
        flag_modified(ticket, "internal_notes_json")

    ticket.updated_at = now
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return serialize_support_ticket(ticket, include_internal=org_id_scope is None)


def add_ticket_message(
    db: Session,
    *,
    ticket_id: str,
    body: str,
    visibility: str = "customer_visible",
    sender_type: str = "staff",
    sender: str = "support_team",
    approval_id: str | None = None,
    org_id_scope: str | None = None,
) -> dict[str, Any]:
    """Post an internal note or customer-visible reply with mandatory HITL gate on sensitive external promises."""
    ticket = db.get(P3SupportTicketRecord, ticket_id)
    if not ticket:
        raise ValueError(f"Support ticket '{ticket_id}' not found")
    if org_id_scope and ticket.org_id != org_id_scope:
        raise PermissionError("Cross-tenant support ticket access denied")

    clean_vis = visibility.strip().lower()
    if clean_vis == "internal_only":
        clean_vis = "internal_note"
    if clean_vis not in ("customer_visible", "internal_note"):
        raise ValueError("visibility must be 'customer_visible' or 'internal_note'")

    safe_body = str(redact_secrets(body)).strip()
    now = datetime.now(UTC)

    if clean_vis == "internal_note":
        notes = list(ticket.internal_notes_json or [])
        notes.append({"author": sender, "note": safe_body, "at": now.isoformat()})
        ticket.internal_notes_json = notes
        flag_modified(ticket, "internal_notes_json")
        ticket.updated_at = now
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        return {"status": "INTERNAL_NOTE_ADDED", "ticket": serialize_support_ticket(ticket, include_internal=True)}

    # External customer-visible staff reply check for sensitive commitments/refunds/legal/account changes
    if sender_type != "customer":
        sensitive_flags = _detect_sensitive_reply_flags(safe_body, ticket.category)
        if sensitive_flags:
            approved_ok = False
            if approval_id:
                appr = db.get(ApprovalRequest, approval_id)
                if appr and appr.status == "APPROVED" and appr.action == "support_sensitive_external_reply":
                    approved_ok = True
            if not approved_ok:
                # Queue HITL ApprovalRequest and block unapproved customer-visible send!
                task_id = str(uuid.uuid4())
                db.add(
                    TaskRecord(
                        id=task_id,
                        correlation_id=ticket.id,
                        objective=f"Approve sensitive support reply for {ticket.ticket_number}",
                        status="HUMAN_APPROVAL_REQUIRED",
                    )
                )
                db.flush()
                req_id = str(uuid.uuid4())
                req_hash = hashlib.sha256(f"{ticket.id}:{safe_body}".encode("utf-8")).hexdigest()
                appr = ApprovalRequest(
                    id=req_id,
                    task_id=task_id,
                    action="support_sensitive_external_reply",
                    detail={
                        "org_id": ticket.org_id,
                        "ticket_id": ticket.id,
                        "ticket_number": ticket.ticket_number,
                        "sensitive_flags": sensitive_flags,
                        "proposed_reply": safe_body[:600],
                    },
                    idempotency_key=f"p3-sup-reply:{ticket.id}:{req_id[:8]}",
                    request_hash=req_hash,
                    requested_by=sender,
                    status="PENDING",
                    decision_note=f"Sensitive support reply requires owner approval ({', '.join(sensitive_flags)})",
                )
                db.add(appr)
                db.commit()
                return {
                    "status": "APPROVAL_REQUIRED",
                    "customer_message_sent": False,
                    "approval_id": appr.id,
                    "sensitive_flags": sensitive_flags,
                    "reason": "External reply involves commercial commitments, refunds, legal, or sensitive access changes.",
                }

    msgs = list(ticket.messages_json or [])
    msgs.append(
        {
            "message_id": f"msg-{uuid.uuid4().hex[:10]}",
            "visibility": "customer_visible",
            "sender_type": sender_type,
            "sender": sender,
            "body": safe_body,
            "approval_id": approval_id,
            "created_at": now.isoformat(),
        }
    )
    ticket.messages_json = msgs
    flag_modified(ticket, "messages_json")

    if sender_type != "customer":
        if not ticket.first_response_at:
            ticket.first_response_at = now
        if ticket.status == "OPEN":
            ticket.status = "WAITING_FOR_CUSTOMER"
    else:
        if ticket.status == "WAITING_FOR_CUSTOMER":
            ticket.status = "IN_PROGRESS"

    acc = db.query(P3CustomerAccountRecord).filter_by(org_id=ticket.org_id).first()
    if acc and sender_type == "customer":
        acc.last_customer_engagement_at = now
        db.add(acc)

    ticket.updated_at = now
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return {
        "status": "POSTED",
        "customer_message_sent": True,
        "ticket": serialize_support_ticket(ticket, include_internal=org_id_scope is None),
    }


def submit_ticket_csat(
    db: Session,
    *,
    ticket_id: str,
    rating: int,
    comment: str | None = None,
    org_id_scope: str | None = None,
) -> dict[str, Any]:
    """Record customer satisfaction (1-5) rating & comments on a support ticket."""
    if rating < 1 or rating > 5:
        raise ValueError("CSAT rating must be between 1 and 5")
    ticket = db.get(P3SupportTicketRecord, ticket_id)
    if not ticket:
        raise ValueError(f"Support ticket '{ticket_id}' not found")
    if org_id_scope and ticket.org_id != org_id_scope:
        raise PermissionError("Cross-tenant support ticket access denied")

    now = datetime.now(UTC)
    ticket.csat_rating = int(rating)
    ticket.csat_comment = str(redact_secrets(comment or "")).strip() or None
    ticket.feedback_submitted_at = now
    ticket.updated_at = now
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return serialize_support_ticket(ticket, include_internal=org_id_scope is None)


def _retrieve_authorized_docs(query_text: str) -> list[dict[str, str]]:
    """Retrieve grounded excerpts from repository docs/ for AI Support Assistant troubleshooting."""
    docs_dir = Path(__file__).resolve().parent.parent.parent / "docs"
    if not docs_dir.exists():
        return []
    tokens = [t.lower() for t in re.findall(r"[a-zA-Z0-9_]{3,}", query_text or "")]
    matches: list[tuple[int, dict[str, str]]] = []
    for doc_file in sorted(docs_dir.glob("*.md")):
        try:
            text = doc_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        low = text.lower()
        hits = sum(1 for tok in tokens if tok in low)
        if hits > 0:
            snippet = " ".join(text.splitlines()[:6])[:320]
            matches.append((hits, {"doc": f"docs/{doc_file.name}", "snippet": snippet}))
    matches.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in matches[:3]]


def run_ai_support_assistant(
    db: Session,
    *,
    ticket_id: str,
    actor: str = "cs_support_specialist_agent",
) -> dict[str, Any]:
    """Classify support ticket, retrieve authorized docs, suggest troubleshooting & HITL-flagged response draft."""
    ticket = db.get(P3SupportTicketRecord, ticket_id)
    if not ticket:
        raise ValueError(f"Support ticket '{ticket_id}' not found")

    text = f"{ticket.subject} {ticket.description}".strip()
    low = text.lower()

    if any(k in low for k in ("refund", "chargeback", "cancel", "double charge")):
        suggested_cat = "refund_dispute"
        suggested_prio = "HIGH"
        steps = [
            "Inspect InvoiceRecord and P2/P3 subscription events for duplicate or disputed charge.",
            "Do NOT issue autonomous refunds or billing waivers without Owner HITL approval.",
        ]
    elif any(k in low for k in ("smtp", "wordpress", "connector", "api key", "token", "webhook", "gsc")):
        suggested_cat = "technical_connector"
        suggested_prio = "HIGH" if "error" in low or "fail" in low else "MEDIUM"
        steps = [
            "Check /v1/registry/connectors status and verification logs for non-sensitive diagnostics.",
            "Confirm connector state is LIVE_VERIFIED before re-running the failed delivery workflow.",
        ]
    elif any(k in low for k in ("onboard", "activation", "training", "setup", "checklist")):
        suggested_cat = "onboarding"
        suggested_prio = "MEDIUM"
        steps = [
            "Inspect Customer 360 -> Onboarding Workflow to identify incomplete readiness tasks or blockers.",
            "Verify customer training and handover checkpoint before manual activation confirmation.",
        ]
    elif any(k in low for k in ("article", "seo", "draft", "revision", "deliver")):
        suggested_cat = "delivery"
        suggested_prio = "MEDIUM"
        steps = [
            "Review P3ServiceDeliveryRecord output artifacts, QA checklist, and execution_evidence_id.",
            "Move ticket to IN_PROGRESS and coordinate revision with QA / Service Delivery agent.",
        ]
    elif any(k in low for k in ("permission", "role", "password", "login", "access")):
        suggested_cat = "account_access"
        suggested_prio = "HIGH"
        steps = [
            "Verify tenant organization membership and role boundaries without bypassing auth.",
            "Require owner approval for any role escalation or credential/permission change.",
        ]
    else:
        suggested_cat = ticket.category or "general"
        suggested_prio = ticket.priority or "MEDIUM"
        steps = ["Review ticket details, retrieve relevant documentation, and follow up within SLA."]

    doc_refs = _retrieve_authorized_docs(text)
    flags = _detect_sensitive_reply_flags(text, suggested_cat)
    requires_approval = bool(flags) or suggested_cat in ("refund_dispute", "account_access", "billing_renewal")

    doc_hint = f" (Reference: {doc_refs[0]['doc']})" if doc_refs else ""
    draft_response = (
        f"Hello {ticket.created_by_email or 'Partner'}, thank you for contacting AskforWrite Support regarding "
        f"ticket {ticket.ticket_number} ('{ticket.subject}'). We have triaged this under '{suggested_cat}' "
        f"and our next step is: {steps[0]}{doc_hint} No billing or access changes will occur without explicit confirmation."
    )

    triage_payload = {
        "suggested_category": suggested_cat,
        "suggested_priority": suggested_prio,
        "troubleshooting_steps": steps,
        "retrieved_docs": doc_refs,
        "suggested_response_draft": draft_response,
        "requires_human_approval": requires_approval,
        "sensitive_flags": flags,
        "triaged_by": actor,
        "triaged_at": datetime.now(UTC).isoformat(),
    }
    ticket.ai_triage_json = triage_payload
    if ticket.status == "OPEN":
        ticket.status = "TRIAGED"
    if ticket.category == "general" and suggested_cat != "general":
        ticket.category = suggested_cat
    if ticket.priority == "MEDIUM" and suggested_prio in ("HIGH", "URGENT"):
        ticket.priority = suggested_prio
    ticket.updated_at = datetime.now(UTC)
    flag_modified(ticket, "ai_triage_json")
    db.add(ticket)
    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=ticket.id,
            agent_id=actor,
            capability_name="p3_support_assistant",
            action="ai_ticket_triage",
            input_payload={"ticket_id": ticket.id, "org_id": ticket.org_id},
            output_payload={"suggested_category": suggested_cat, "requires_human_approval": requires_approval},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(ticket)
    return {"ticket": serialize_support_ticket(ticket, include_internal=True), "triage": triage_payload}


def synthesize_improvement_loop(db: Session, *, org_id: str | None = None) -> list[dict[str, Any]]:
    """Aggregate real recurring pain signals (tickets, failures, revisions, blockers, CSAT) into prioritized items."""
    clusters: dict[str, dict[str, Any]] = {}

    def _add_cluster(
        cluster_key: str,
        source_cat: str,
        title: str,
        summary: str,
        action: str,
        ref: str,
        impact: int = 3,
        val: int = 3,
        effort: int = 2,
        risk: str = "MEDIUM",
        item_org: str | None = None,
    ) -> None:
        c = clusters.setdefault(
            cluster_key,
            {
                "cluster_key": cluster_key,
                "org_id": item_org,
                "source_category": source_cat,
                "title": title,
                "problem_summary": summary,
                "recommended_action": action,
                "customer_impact": impact,
                "frequency_count": 0,
                "business_value": val,
                "dev_effort": effort,
                "risk_level": risk,
                "source_refs": [],
            },
        )
        c["frequency_count"] += 1
        if ref not in c["source_refs"]:
            c["source_refs"].append(ref)

    t_q = db.query(P3SupportTicketRecord)
    if org_id:
        t_q = t_q.filter_by(org_id=org_id)
    for t in t_q.all():
        if t.category == "feature_request":
            _add_cluster(
                f"feature_req:{t.category}:{t.subject[:40].lower()}",
                "FEATURE_REQUEST",
                f"Customer Feature Request: {t.subject[:120]}",
                t.description[:300],
                "Review customer request in founder roadmap backlog before scheduling implementation.",
                f"ticket:{t.ticket_number}",
                impact=3,
                val=4,
                effort=3,
                risk="LOW",
                item_org=t.org_id,
            )
        elif t.status == "ESCALATED" or t.priority in ("HIGH", "URGENT") or (t.csat_rating is not None and t.csat_rating <= 3):
            _add_cluster(
                f"ticket_cluster:{t.category}",
                "SUPPORT_TICKET" if (t.csat_rating is None or t.csat_rating > 3) else "CUSTOMER_FEEDBACK",
                f"Recurring support friction in '{t.category}'",
                f"Observed ticket {t.ticket_number}: {t.subject[:200]}",
                f"Improve documentation, guardrails, and diagnostics around '{t.category}'.",
                f"ticket:{t.ticket_number}",
                impact=4,
                val=4,
                effort=2,
                risk="MEDIUM",
                item_org=t.org_id,
            )

    w_q = db.query(WorkflowRunRecord).filter(WorkflowRunRecord.status.in_(("FAILED", "BLOCKED")))
    if org_id:
        w_q = w_q.filter_by(org_id=org_id)
    for w in w_q.all():
        _add_cluster(
            f"workflow_failure:{w.workflow_id}",
            "WORKFLOW_FAILURE",
            f"Workflow reliability gap for definition {w.workflow_id}",
            f"Workflow run {w.id} ended {w.status}: {(w.failure_reason or 'check step logs')[:200]}",
            "Harden retry backoff, timeout threshold, and pre-flight connector checks for this workflow.",
            f"workflow_run:{w.id}",
            impact=5,
            val=5,
            effort=3,
            risk="HIGH",
            item_org=w.org_id,
        )

    d_q = db.query(P3ServiceDeliveryRecord).filter(P3ServiceDeliveryRecord.quality_state.in_(("REVISION_REQUESTED", "BLOCKED")))
    if org_id:
        d_q = d_q.filter_by(org_id=org_id)
    for d in d_q.all():
        _add_cluster(
            f"delivery_revision:{d.service_id}",
            "SERVICE_REVISION",
            f"Quality/Revision pattern on service '{d.service_id}'",
            f"Delivery '{d.title}' required revision/blocked: {(d.revision_notes or d.quality_state)[:200]}",
            "Refine QA checklist criteria and template prompts for this deliverable type.",
            f"delivery:{d.id}",
            impact=4,
            val=4,
            effort=2,
            risk="MEDIUM",
            item_org=d.org_id,
        )

    o_q = db.query(P3OnboardingWorkflowRecord)
    if org_id:
        o_q = o_q.filter_by(org_id=org_id)
    for o in o_q.all():
        if o.blockers_json:
            _add_cluster(
                f"onboarding_blocker:{o.template_key}",
                "ONBOARDING_BLOCKER",
                f"Onboarding blockers in template '{o.template_key}'",
                f"Blocked onboarding steps: {o.blockers_json}",
                "Simplify customer onboarding collection form and connector walkthrough.",
                f"onboarding:{o.id}",
                impact=4,
                val=5,
                effort=2,
                risk="LOW",
                item_org=o.org_id,
            )

    p2_q = db.query(P2CustomerEngagementRecord)
    if org_id:
        p2_q = p2_q.filter_by(org_id=org_id)
    for eng in p2_q.all():
        fb = eng.customer_feedback_json or {}
        if fb.get("improvements_requested"):
            _add_cluster(
                f"pilot_feedback:{eng.sku_key}",
                "CUSTOMER_FEEDBACK",
                f"Customer improvement feedback for {eng.sku_key}",
                str(fb["improvements_requested"])[:250],
                "Review verified customer request in product triage before engineering release.",
                f"engagement:{eng.id}",
                impact=4,
                val=4,
                effort=3,
                risk="LOW",
                item_org=eng.org_id,
            )

    risk_penalty = {"LOW": 0.0, "MEDIUM": 0.5, "HIGH": 1.0}
    results: list[dict[str, Any]] = []
    now = datetime.now(UTC)

    for c_key, data in clusters.items():
        prio_score = round(
            ((data["customer_impact"] * 2.0) + (data["frequency_count"] * 1.5) + (data["business_value"] * 2.0))
            / max(1, int(data["dev_effort"]))
            - risk_penalty.get(data["risk_level"], 0.5),
            2,
        )
        rec = db.query(P3ImprovementItemRecord).filter_by(cluster_key=c_key).first()
        if rec is None:
            rec = P3ImprovementItemRecord(
                cluster_key=c_key,
                org_id=data["org_id"],
                source_category=data["source_category"],
                title=data["title"],
                problem_summary=data["problem_summary"],
                recommended_action=data["recommended_action"],
                customer_impact=data["customer_impact"],
                frequency_count=data["frequency_count"],
                business_value=data["business_value"],
                dev_effort=data["dev_effort"],
                risk_level=data["risk_level"],
                priority_score=prio_score,
                source_refs_json=data["source_refs"],
                status="OPEN",
                requires_release_approval=True,
                created_at=now,
                updated_at=now,
            )
            db.add(rec)
        else:
            rec.frequency_count = max(rec.frequency_count, data["frequency_count"])
            rec.priority_score = prio_score
            merged_refs = list(dict.fromkeys((rec.source_refs_json or []) + data["source_refs"]))
            rec.source_refs_json = merged_refs
            rec.updated_at = now
            flag_modified(rec, "source_refs_json")
            db.add(rec)
        db.flush()
        results.append(serialize_improvement_item(rec))

    if results:
        db.commit()
    results.sort(key=lambda x: x["priority_score"], reverse=True)
    return results


def serialize_support_ticket(t: P3SupportTicketRecord, *, include_internal: bool = False) -> dict[str, Any]:
    data = {
        "ticket_id": t.id,
        "ticket_number": t.ticket_number,
        "org_id": t.org_id,
        "created_by_user_id": t.created_by_user_id,
        "created_by_email": t.created_by_email,
        "category": t.category,
        "priority": t.priority,
        "assigned_owner": t.assigned_owner,
        "assigned_agent_id": t.assigned_agent_id,
        "status": t.status,
        "subject": t.subject,
        "description": t.description,
        "attachments": t.attachments_json or [],
        "messages": [m for m in (t.messages_json or []) if m.get("visibility") == "customer_visible"],
        "first_response_at": t.first_response_at.isoformat() if t.first_response_at else None,
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        "resolution_seconds": t.resolution_seconds,
        "escalated_at": t.escalated_at.isoformat() if t.escalated_at else None,
        "escalation_reason": t.escalation_reason if include_internal else None,
        "csat_rating": t.csat_rating,
        "csat_comment": t.csat_comment,
        "feedback_submitted_at": t.feedback_submitted_at.isoformat() if t.feedback_submitted_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }
    if include_internal:
        data["internal_notes"] = t.internal_notes_json or []
        data["ai_triage"] = t.ai_triage_json
    return data


def serialize_improvement_item(item: P3ImprovementItemRecord) -> dict[str, Any]:
    return {
        "improvement_id": item.id,
        "cluster_key": item.cluster_key,
        "org_id": item.org_id,
        "source_category": item.source_category,
        "title": item.title,
        "problem_summary": item.problem_summary,
        "recommended_action": item.recommended_action,
        "customer_impact": item.customer_impact,
        "frequency_count": item.frequency_count,
        "business_value": item.business_value,
        "dev_effort": item.dev_effort,
        "risk_level": item.risk_level,
        "priority_score": item.priority_score,
        "source_refs": item.source_refs_json or [],
        "status": item.status,
        "requires_release_approval": item.requires_release_approval,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }
