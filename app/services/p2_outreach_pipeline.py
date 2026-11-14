"""P2 Outreach Preparation Agent & 12-Stage Sales Pipeline Service.

Enforces:
- Non-fabricated outreach generation grounded in source-backed claims & verified catalog SKU
- Persistent suppression / opt-out checks
- Per-lead and daily rate limits + duplicate outreach protection
- Mandatory Owner HITL approval gate before any outbound send
- Strict separation between LIVE delivery and SIMULATED dispatch receipts
- Complete 12-status commercial pipeline transitions with discovery & response logging
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.agents.discovery import COMPETITOR_COMPANY_KEYWORDS, COMPETITOR_DOMAINS
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    ConversationRecord,
    LeadRecordRow,
    OrganizationRecord,
    OutreachRecord,
    P2CommercialProposalRecord,
    P2CustomerEngagementRecord,
    P2ProspectDossierRecord,
    TaskRecord,
)
from app.security.trust_chain import seal_task_to_block
from app.services.approvals import request_approval
from app.services.email_dispatcher import EmailDispatcher, get_email_dispatcher
from app.services.evidence import record_execution_evidence
from app.services.execution_guard import resolve_execution_mode
from app.services.p2_prospect_intel import (
    P2_PIPELINE_STATUSES,
    is_synthetic_fixture_prospect,
    serialize_prospect_dossier,
    verify_pilot_offer_contract,
)
from app.services.suppression import add_db_suppression, is_db_suppressed

# Patterns explicitly forbidden per P2 Commercial Rule §2 & §3D
_FORBIDDEN_CLAIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bas we (spoke|discussed|chatted)\b", "Invented previous conversation reference"),
    (r"\bfollowing up on our (last|previous) (call|chat|meeting)\b", "Invented prior relationship"),
    (
        r"\bguarante(e|ed|es|ing)\b.{0,35}(#1|first page|top\s*\d+|google\s+ranking|rankings?|traffic|roi|revenue|returns|double|triple|10x|increase)\b",
        "Unsupported performance or ROI guarantee",
    ),
    (r"\b(#1|first[- ]page)\s+(google\s+)?ranking\s+guarante(e|ed)\b", "Unsupported ranking guarantee"),
    (r"\b(last\s+\d+\s+spots?\s+left|offer expires\s+(today|tonight)|expires today|urgent 24-hour)\b", "False urgency"),
    (r"\b(special|exclusive|limited[- ]time)\s+\d+%\s+(discount|off)\b|\b\d+%\s+off\b", "Unapproved invented discount"),
    (r"\bcase study with\b", "Potentially unverified case study claim"),
)


def validate_outreach_integrity(subject: str, body_text: str) -> list[str]:
    """Check outreach draft for prohibited fabricated claims, relationships, discounts, or false urgency."""
    combined = f"{subject}\n{body_text}"
    violations: list[str] = []
    for pattern, label in _FORBIDDEN_CLAIM_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            violations.append(f"{label} (matched '{pattern}')")
    return violations


def _build_truthful_agency_outreach(
    *,
    dossier: P2ProspectDossierRecord,
    lead: LeadRecordRow,
    recipient_name: str | None,
    custom_notes: str | None,
    sender_name: str = "Vipul Chobisa",
) -> tuple[str, str]:
    """Generate concise, honest outreach grounded strictly in verified dossier claims and catalog SKU."""
    offer = verify_pilot_offer_contract(dossier.recommended_sku)
    greeting = f"Hi {recipient_name.strip()}," if recipient_name and recipient_name.strip() else f"Hello {lead.company} Team,"

    claims = [c for c in (dossier.research_claims_json or []) if c.get("classification") == "VERIFIED_FACT"]
    services = (dossier.agency_profile_json or {}).get("actual_services") or []
    observation = ""
    if claims:
        observation = f"While reviewing your website ({lead.website}), I noted your focus on: {claims[0].get('statement')}."
    elif services:
        observation = f"While reviewing {lead.website}, I noted your agency offerings around {', '.join(services[:2])}."
    else:
        observation = f"I reviewed {lead.company}'s digital marketing presence at {lead.website}."

    notes_block = f"\n\nContext note: {custom_notes.strip()}" if custom_notes and custom_notes.strip() else ""

    subject = f"14-day SEO & content delivery pilot option for {lead.company}"
    body = (
        f"{greeting}\n\n"
        f"{observation}\n\n"
        f"I am reaching out because AskforWrite builds AI-assisted workflows for digital marketing and SEO teams "
        f"that want faster research, technical SEO/GEO audits, and review-gated WordPress draft production without "
        f"losing human editorial control.\n\n"
        f"If relevant to your delivery queue, we offer a fixed-scope 14-day {offer['name']} at ₹{offer['price_inr']:,} "
        f"(one-time pilot, manual renewal decision only after 14 days):\n"
        f"- 1 technical SEO & GEO audit report for a target domain\n"
        f"- 1 commercial keyword cluster map\n"
        f"- 2 human-reviewed articles (1,500+ words each) with Schema.org JSON-LD markup, staged as drafts\n"
        f"{notes_block}\n\n"
        f"No long-term lock-in and no exaggerated traffic claims—just concrete deliverables your team can review directly.\n\n"
        f"Would you be open to a brief 15-minute call this week to see if this fits one of your client accounts?\n\n"
        f"Best regards,\n"
        f"{sender_name}\n"
        f"AskforWrite AI Company OS (askforwrite.in)\n"
        f"---\n"
        f"If you prefer not to receive emails from us, reply to opt out and we will suppress {lead.domain or lead.company} immediately."
    )
    return subject, body


def prepare_p2_outreach(
    db: Session,
    *,
    lead_id: str,
    recipient_email: str | None = None,
    recipient_name: str | None = None,
    channel: str = "email",
    subject_override: str | None = None,
    body_override: str | None = None,
    custom_notes: str | None = None,
    allow_follow_up: bool = False,
    idempotency_key: str | None = None,
    actor: str = "outreach_preparation_agent",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Prepare compliant personalized outreach behind Owner HITL Approval + suppression & rate-limit guards."""
    lead = db.get(LeadRecordRow, lead_id)
    dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=lead_id).first()
    if not lead or not dossier:
        raise ValueError(f"P2 prospect dossier not found for lead '{lead_id}'")

    if lead.do_not_contact or lead.status == "DO_NOT_CONTACT" or dossier.pipeline_status == "DO_NOT_CONTACT":
        raise ValueError("Outreach blocked: prospect is marked DO_NOT_CONTACT")
    if dossier.pipeline_status == "DISQUALIFIED":
        raise ValueError("Outreach blocked: prospect is DISQUALIFIED and has not passed ICP qualification")
    if dossier.is_synthetic:
        raise ValueError("Outreach blocked: synthetic fixtures cannot enter production outreach")

    verified_contacts = [c for c in (dossier.public_contacts_json or []) if c.get("value")]
    target_email = (recipient_email or lead.public_contact_channel or (verified_contacts[0]["value"] if verified_contacts else "")).strip().lower()
    if not target_email or "@" not in target_email:
        raise ValueError("A valid public recipient email is required before preparing outreach")

    is_synth, synth_reason = is_synthetic_fixture_prospect(
        domain=dossier.normalized_domain,
        website=lead.website,
        source_url=dossier.source_url,
        email=target_email,
    )
    if is_synth:
        raise ValueError(synth_reason or "Synthetic domain rejected from outreach")

    email_domain = target_email.split("@", 1)[1].lower()
    if email_domain in COMPETITOR_DOMAINS or any(kw in lead.company.lower() for kw in COMPETITOR_COMPANY_KEYWORDS):
        raise ValueError("Outreach blocked: target matches competitor blocklist")

    suppressed, supp_reason = is_db_suppressed(db, target_email, lead_id=lead_id)
    if suppressed:
        raise ValueError(f"Outreach blocked by suppression registry: {supp_reason}")
    suppressed_dom, supp_dom_reason = is_db_suppressed(db, dossier.normalized_domain)
    if suppressed_dom:
        raise ValueError(f"Outreach blocked by domain suppression registry: {supp_dom_reason}")

    # Idempotency check
    idem_key = (idempotency_key or f"p2-outreach-{lead_id}-{uuid.uuid4().hex[:10]}").strip()
    existing_idem = db.query(OutreachRecord).filter_by(idempotency_key=idem_key).first()
    if existing_idem:
        return {
            "outreach_id": existing_idem.id,
            "lead_id": existing_idem.lead_id,
            "status": existing_idem.status,
            "approval_id": existing_idem.approval_id,
            "recipient_email": existing_idem.recipient_email,
            "subject": existing_idem.subject,
            "idempotent_replay": True,
        }

    # Duplicate protection: reject parallel unapproved/pending outreach drafts for same lead
    pending_existing = (
        db.query(OutreachRecord)
        .filter(
            OutreachRecord.lead_id == lead_id,
            OutreachRecord.status.in_(("DRAFT", "PENDING_APPROVAL")),
        )
        .first()
    )
    if pending_existing:
        raise ValueError(
            f"Duplicate outreach prevented: outreach '{pending_existing.id}' is already in status '{pending_existing.status}' awaiting owner decision."
        )

    # Rate limits (per-lead 7d and global daily cap)
    now = datetime.now(UTC)
    max_per_lead_7d = int(os.getenv("P2_OUTREACH_MAX_PER_LEAD_7D", "2"))
    max_daily_total = int(os.getenv("P2_OUTREACH_MAX_DAILY", "25"))

    recent_for_lead = (
        db.query(OutreachRecord)
        .filter(
            OutreachRecord.lead_id == lead_id,
            OutreachRecord.created_at >= now - timedelta(days=7),
            OutreachRecord.status.notin_(("SUPPRESSED_OPT_OUT", "FAILED", "CANCELLED")),
        )
        .count()
    )
    if recent_for_lead > 0 and not allow_follow_up:
        raise ValueError(
            "Duplicate protection: this lead already received an outreach draft/send within the last 7 days (pass allow_follow_up=true only for intentional follow-ups)."
        )
    if recent_for_lead >= max_per_lead_7d:
        raise ValueError(f"Per-lead weekly rate limit reached ({recent_for_lead}/{max_per_lead_7d} in 7 days).")

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = db.query(OutreachRecord).filter(OutreachRecord.created_at >= today_start).count()
    if today_count >= max_daily_total:
        raise ValueError(f"Daily outreach rate limit reached ({today_count}/{max_daily_total} drafts today).")

    default_subject, default_body = _build_truthful_agency_outreach(
        dossier=dossier,
        lead=lead,
        recipient_name=recipient_name,
        custom_notes=custom_notes,
    )
    subject = (subject_override or default_subject).strip()
    body = (body_override or default_body).strip()

    violations = validate_outreach_integrity(subject, body)
    if violations:
        raise ValueError("Outreach draft rejected by commercial honesty guard: " + "; ".join(violations))

    corr_id = correlation_id or str(uuid.uuid4())
    task_id = lead.task_id or str(uuid.uuid4())
    if not db.get(TaskRecord, task_id):
        db.add(
            TaskRecord(
                id=task_id,
                correlation_id=corr_id,
                objective=f"P2 Outreach approval for {lead.company}",
                status="IN_PROGRESS",
            )
        )
        db.flush()

    contact_verified = any(
        str(c.get("value", "")).lower() == target_email and bool(c.get("verified"))
        for c in (dossier.public_contacts_json or [])
    )

    outreach_id = str(uuid.uuid4())
    approval_resp = request_approval(
        db=db,
        task_id=task_id,
        lead_id=lead_id,
        action="external_sales_outreach",
        detail={
            "p2_commercial": True,
            "outreach_id": outreach_id,
            "company": lead.company,
            "recipient_email": target_email,
            "recipient_name": recipient_name,
            "subject": subject,
            "channel": channel,
            "sku_key": dossier.recommended_sku,
            "is_contact_verified": contact_verified,
            "approval_policy": "VERIFIED_CONTACT_HITL" if contact_verified else "UNVERIFIED_CONTACT_STRICT_HITL",
            "source_url": dossier.source_url,
        },
        idempotency_key=f"appr-p2-outreach-{idem_key}",
        requested_by=actor,
        correlation_id=corr_id,
        commit=False,
    )
    approval_id = str(approval_resp["approval_id"])

    outreach = OutreachRecord(
        id=outreach_id,
        org_id=dossier.org_id,
        lead_id=lead_id,
        task_id=task_id,
        recipient_email=target_email,
        recipient_name=recipient_name,
        subject=subject,
        body_text=body,
        channel=channel,
        status="PENDING_APPROVAL",
        approval_id=approval_id,
        idempotency_key=idem_key,
        metadata_json={
            "p2_commercial": True,
            "sku_key": dossier.recommended_sku,
            "source_url": dossier.source_url,
            "contact_verified": contact_verified,
            "external_sent": False,
        },
    )
    db.add(outreach)

    dossier.pipeline_status = "APPROVAL_PENDING"
    dossier.next_action = f"Owner review & approval of outreach '{subject[:60]}'"
    dossier.updated_at = now
    db.add(dossier)

    record_execution_evidence(
        db,
        tenant_id=dossier.org_id or "__platform__",
        agent_id="outreach_preparation_agent",
        connector_id="project_api",
        execution_mode=resolve_execution_mode(None),
        input_payload={"lead_id": lead_id, "recipient_email": target_email, "channel": channel},
        output_payload={"outreach_id": outreach_id, "approval_id": approval_id, "status": "PENDING_APPROVAL"},
        approval_id=approval_id,
        uses_external_provider=False,
        status="COMPLETED",
        output_origin="HUMAN_ASSISTED",
    )
    db.add(
        AuditLog(
            task_id=task_id,
            correlation_id=corr_id,
            agent_id=actor,
            capability_name="p2_outreach",
            action="prepare_outreach_draft",
            input_payload={"lead_id": lead_id, "recipient_email": target_email},
            output_payload={"outreach_id": outreach_id, "approval_id": approval_id, "status": "PENDING_APPROVAL"},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(outreach)

    return {
        "outreach_id": outreach.id,
        "lead_id": lead_id,
        "status": outreach.status,
        "pipeline_status": dossier.pipeline_status,
        "approval_id": approval_id,
        "recipient_email": target_email,
        "contact_verified": contact_verified,
        "subject": subject,
        "body_text": body,
        "channel": channel,
        "external_sent": False,
    }


def dispatch_p2_outreach(
    db: Session,
    *,
    outreach_id: str,
    dispatched_by: str = "owner",
    correlation_id: str | None = None,
    dispatcher: EmailDispatcher | None = None,
) -> dict[str, Any]:
    """Dispatch owner-approved outreach, separating LIVE delivery from SIMULATED dispatch receipts."""
    outreach = db.get(OutreachRecord, outreach_id)
    if not outreach:
        raise ValueError(f"Outreach record '{outreach_id}' not found")

    if outreach.status in ("SENT", "DISPATCHED"):
        return {
            "outreach_id": outreach.id,
            "status": outreach.status,
            "already_dispatched": True,
            "external_sent": True,
            "sent_at": outreach.sent_at.isoformat() if outreach.sent_at else None,
        }

    if outreach.status == "SUPPRESSED_OPT_OUT":
        raise ValueError("Outreach was cancelled due to recipient opt-out / suppression")

    suppressed, reason = is_db_suppressed(db, outreach.recipient_email, lead_id=outreach.lead_id)
    if suppressed:
        raise ValueError(f"Cannot dispatch outreach: suppressed ({reason})")

    if not outreach.approval_id:
        raise ValueError("Outreach has no linked Owner ApprovalRequest")
    approval = db.get(ApprovalRequest, outreach.approval_id)
    if not approval or approval.status != "APPROVED":
        cur_state = approval.status if approval else "MISSING"
        raise ValueError(f"Outreach blocked: Owner Approval required before send (status: {cur_state})")

    if outreach.org_id:
        org = db.get(OrganizationRecord, outreach.org_id)
        if org and org.outreach_credits_used >= org.outreach_credits_limit:
            raise ValueError("Organization outreach credit limit reached")

    corr_id = correlation_id or str(uuid.uuid4())
    active_dispatcher = dispatcher or get_email_dispatcher()
    mode = resolve_execution_mode(None)

    try:
        receipt = active_dispatcher.send(
            recipient_email=outreach.recipient_email,
            subject=outreach.subject,
            body_text=outreach.body_text,
        )
    except Exception as exc:
        outreach.status = "FAILED"
        outreach.error_message = str(exc)
        db.add(outreach)
        db.commit()
        raise RuntimeError(f"Email dispatch failed cleanly without faking success: {exc}") from exc

    now = datetime.now(UTC)
    receipt_mode = str((receipt or {}).get("mode", "")).upper()
    receipt_status = str((receipt or {}).get("status", "")).lower()
    is_simulated = receipt_mode == "SIMULATED" or "simulated" in receipt_status or mode == "SIMULATION"

    meta = dict(outreach.metadata_json or {})
    meta["dispatch_receipt"] = receipt
    meta["delivery_mode"] = "SIMULATED" if is_simulated else "LIVE"
    meta["external_sent"] = not is_simulated
    outreach.metadata_json = meta
    flag_modified(outreach, "metadata_json")

    dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=outreach.lead_id).first()
    lead = db.get(LeadRecordRow, outreach.lead_id)

    if is_simulated:
        # Honest boundary: simulated send is clearly separated from live prospect delivery
        outreach.status = "SIMULATED_SENT"
        outreach.sent_at = now
        if dossier and dossier.pipeline_status in ("APPROVAL_PENDING", "QUALIFIED"):
            dossier.next_action = "Outreach ran in SIMULATION only; verify live SMTP connector before live send"
            dossier.updated_at = now
            db.add(dossier)
        origin = "SIMULATED_SYNTHETIC"
    else:
        outreach.status = "SENT"
        outreach.sent_at = now
        if lead:
            lead.status = "CONTACTED"
            lead.last_checked = now
            db.add(lead)
        if dossier:
            dossier.pipeline_status = "CONTACTED"
            dossier.next_action = "Monitor inbox for prospect reply or schedule follow-up in 4 business days"
            dossier.follow_up_at = now + timedelta(days=4)
            dossier.updated_at = now
            db.add(dossier)
        origin = "LIVE_PROVIDER_VERIFIED"

    db.add(outreach)

    record_execution_evidence(
        db,
        tenant_id=outreach.org_id or "__platform__",
        agent_id="outreach_preparation_agent",
        connector_id="hostinger_smtp",
        execution_mode="SIMULATION" if is_simulated else "PRODUCTION",
        input_payload={"outreach_id": outreach_id, "recipient_email": outreach.recipient_email},
        output_payload={"status": outreach.status, "external_sent": not is_simulated, "receipt": receipt},
        provider_request_id=str((receipt or {}).get("message_id") or "") or None,
        approval_id=outreach.approval_id,
        fallback_used=is_simulated,
        uses_external_provider=not is_simulated,
        status="COMPLETED",
        output_origin=origin,
    )
    seal_task_to_block(
        db=db,
        task_id=outreach.task_id,
        capability_name="p2_outreach",
        action="dispatch_outreach",
        payload={
            "outreach_id": outreach.id,
            "status": outreach.status,
            "external_sent": not is_simulated,
            "dispatched_by": dispatched_by,
        },
        sealed_by=dispatched_by,
        commit=False,
    )
    db.commit()
    db.refresh(outreach)

    return {
        "outreach_id": outreach.id,
        "lead_id": outreach.lead_id,
        "status": outreach.status,
        "pipeline_status": dossier.pipeline_status if dossier else None,
        "external_sent": not is_simulated,
        "delivery_mode": "SIMULATED" if is_simulated else "LIVE",
        "sent_at": outreach.sent_at.isoformat() if outreach.sent_at else None,
        "receipt": receipt,
    }


def transition_pipeline_status(
    db: Session,
    *,
    lead_id: str,
    target_status: str,
    next_action: str | None = None,
    follow_up_at: datetime | None = None,
    discovery_notes: str | None = None,
    owner_notes: str | None = None,
    actor: str = "owner",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Audit-logged transition across all 12 P2 commercial pipeline statuses."""
    clean_status = target_status.strip().upper()
    if clean_status not in P2_PIPELINE_STATUSES:
        raise ValueError(f"Unsupported pipeline status '{target_status}'. Allowed: {', '.join(P2_PIPELINE_STATUSES)}")

    lead = db.get(LeadRecordRow, lead_id)
    dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=lead_id).first()
    if not lead or not dossier:
        raise ValueError(f"P2 prospect dossier not found for lead '{lead_id}'")

    previous_status = dossier.pipeline_status
    dossier.pipeline_status = clean_status
    if next_action is not None:
        dossier.next_action = next_action.strip() or None
    if follow_up_at is not None:
        dossier.follow_up_at = follow_up_at
    if discovery_notes is not None:
        dossier.discovery_notes = discovery_notes.strip()
    if owner_notes is not None:
        dossier.owner_notes = owner_notes.strip()
    dossier.updated_at = datetime.now(UTC)

    if clean_status == "DO_NOT_CONTACT":
        lead.do_not_contact = True
        lead.status = "DO_NOT_CONTACT"
        if lead.public_contact_channel:
            add_db_suppression(db, lead.public_contact_channel, reason="Pipeline marked DO_NOT_CONTACT", source="owner_dnc")
        add_db_suppression(db, dossier.normalized_domain, reason="Pipeline marked DO_NOT_CONTACT", source="owner_dnc")
        for out in db.query(OutreachRecord).filter(
            OutreachRecord.lead_id == lead_id,
            OutreachRecord.status.in_(("DRAFT", "PENDING_APPROVAL")),
        ).all():
            out.status = "SUPPRESSED_OPT_OUT"
    else:
        lead.status = clean_status

    db.add(dossier)
    db.add(lead)
    db.add(
        AuditLog(
            task_id=lead.task_id,
            correlation_id=correlation_id or str(uuid.uuid4()),
            agent_id=actor,
            capability_name="p2_sales_pipeline",
            action="transition_status",
            input_payload={"lead_id": lead_id, "from": previous_status, "to": clean_status},
            output_payload={"pipeline_status": clean_status, "next_action": dossier.next_action},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(dossier)
    return serialize_prospect_dossier(dossier, lead)


def log_prospect_response(
    db: Session,
    *,
    lead_id: str,
    summary: str,
    source: str = "email_reply",
    channel: str = "email",
    sentiment: str = "interested",
    next_action: str | None = None,
    follow_up_at: datetime | None = None,
    discovery_notes: str | None = None,
    actor: str = "owner",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Record a genuine prospect response with source provenance & update sales pipeline."""
    lead = db.get(LeadRecordRow, lead_id)
    dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=lead_id).first()
    if not lead or not dossier:
        raise ValueError(f"P2 prospect dossier not found for lead '{lead_id}'")

    now = datetime.now(UTC)
    history = list(dossier.response_history_json or [])
    history.append(
        {
            "response_id": str(uuid.uuid4()),
            "logged_at": now.isoformat(),
            "source": source,
            "channel": channel,
            "sentiment": sentiment,
            "summary": summary.strip(),
            "logged_by": actor,
        }
    )
    dossier.response_history_json = history
    flag_modified(dossier, "response_history_json")

    db.add(
        ConversationRecord(
            id=str(uuid.uuid4()),
            lead_id=lead_id,
            task_id=lead.task_id,
            channel=channel,
            notes=f"[{sentiment}] ({source}) {summary.strip()}",
        )
    )

    clean_sentiment = sentiment.strip().lower()
    if clean_sentiment in ("unsubscribe", "opt_out", "do_not_contact"):
        db.flush()
        return transition_pipeline_status(
            db,
            lead_id=lead_id,
            target_status="DO_NOT_CONTACT",
            next_action="Suppressed per prospect opt-out",
            actor=actor,
            correlation_id=correlation_id,
        )

    target_status = "DISCOVERY" if discovery_notes else ("LOST" if clean_sentiment == "not_interested" else "RESPONDED")
    if discovery_notes:
        dossier.discovery_notes = (
            f"{dossier.discovery_notes}\n\n{discovery_notes.strip()}".strip()
            if dossier.discovery_notes
            else discovery_notes.strip()
        )
    dossier.pipeline_status = target_status
    dossier.next_action = next_action or (
        "Schedule discovery call or prepare structured pilot proposal"
        if target_status == "RESPONDED"
        else ("Prepare structured proposal for Manage SEO & Content Pilot" if target_status == "DISCOVERY" else "Closed-lost logged")
    )
    if follow_up_at:
        dossier.follow_up_at = follow_up_at
    dossier.updated_at = now
    lead.status = target_status

    db.add(dossier)
    db.add(lead)
    db.add(
        AuditLog(
            task_id=lead.task_id,
            correlation_id=correlation_id or str(uuid.uuid4()),
            agent_id=actor,
            capability_name="p2_sales_pipeline",
            action="log_prospect_response",
            input_payload={"lead_id": lead_id, "source": source, "sentiment": sentiment},
            output_payload={"pipeline_status": target_status, "responses_count": len(history)},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(dossier)
    return serialize_prospect_dossier(dossier, lead)


def list_unified_pipeline(
    db: Session,
    *,
    status_filter: str | None = None,
    include_synthetic: bool = False,
) -> list[dict[str, Any]]:
    """Build unified deal pipeline combining prospect intelligence, outreach, proposal, payment, & activation."""
    query = db.query(P2ProspectDossierRecord).order_by(P2ProspectDossierRecord.updated_at.desc())
    if status_filter:
        query = query.filter(P2ProspectDossierRecord.pipeline_status == status_filter.strip().upper())
    if not include_synthetic:
        query = query.filter(P2ProspectDossierRecord.is_synthetic.is_(False))

    dossiers = query.all()
    rows: list[dict[str, Any]] = []
    for d in dossiers:
        lead = db.get(LeadRecordRow, d.lead_id)
        outreach_rows = (
            db.query(OutreachRecord)
            .filter_by(lead_id=d.lead_id)
            .order_by(OutreachRecord.created_at.desc())
            .all()
        )
        proposals = (
            db.query(P2CommercialProposalRecord)
            .filter_by(lead_id=d.lead_id)
            .order_by(P2CommercialProposalRecord.created_at.desc())
            .all()
        )
        engagement = (
            db.query(P2CustomerEngagementRecord)
            .filter_by(lead_id=d.lead_id)
            .order_by(P2CustomerEngagementRecord.created_at.desc())
            .first()
        )
        latest_outreach = outreach_rows[0] if outreach_rows else None
        latest_proposal = proposals[0] if proposals else None

        item = serialize_prospect_dossier(d, lead)
        item["outreach_history_count"] = len(outreach_rows)
        item["latest_outreach"] = (
            {
                "outreach_id": latest_outreach.id,
                "status": latest_outreach.status,
                "approval_id": latest_outreach.approval_id,
                "recipient_email": latest_outreach.recipient_email,
                "subject": latest_outreach.subject,
                "external_sent": bool((latest_outreach.metadata_json or {}).get("external_sent", False)),
                "sent_at": latest_outreach.sent_at.isoformat() if latest_outreach.sent_at else None,
            }
            if latest_outreach
            else None
        )
        item["latest_proposal"] = (
            {
                "proposal_id": latest_proposal.id,
                "sku_key": latest_proposal.sku_key,
                "status": latest_proposal.status,
                "approval_id": latest_proposal.approval_id,
                "checkout_url": latest_proposal.checkout_url,
                "shared_at": latest_proposal.shared_at.isoformat() if latest_proposal.shared_at else None,
                "total_amount": (latest_proposal.pricing_json or {}).get("total_amount"),
                "currency": (latest_proposal.pricing_json or {}).get("currency"),
            }
            if latest_proposal
            else None
        )
        item["customer_engagement"] = (
            {
                "engagement_id": engagement.id,
                "org_id": engagement.org_id,
                "status": engagement.status,
                "workflow_run_id": engagement.workflow_run_id,
            }
            if engagement
            else None
        )
        rows.append(item)
    return rows
