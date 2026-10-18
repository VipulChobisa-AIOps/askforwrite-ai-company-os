"""Owner-approved customer outreach service with credit gating and cryptographic ledger sealing."""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agents.discovery import COMPETITOR_COMPANY_KEYWORDS, COMPETITOR_DOMAINS
from app.agents.revenue_agent import generate_commercial_pitch
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    LeadRecordRow,
    OrganizationRecord,
    OutreachRecord,
    TaskRecord,
)
from app.security.trust_chain import seal_task_to_block
from app.services.approvals import request_approval
from app.services.email_dispatcher import EmailDispatcher, get_email_dispatcher

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "sales_outreach"


def sanitize_outreach_content(text: str) -> str:
    """Enforce owner direct engagement directives:
    - Never use 'field force' in outbound messaging.
    - Transform into direct engagement branding ('AskforWrite Operations Engine').
    """
    if not text:
        return text
    pattern = re.compile(r"\bfield[\s_-]*force\b", re.IGNORECASE)
    return pattern.sub("AskforWrite Operations Engine", text)


def generate_personalized_message(
    company: str,
    industry: str,
    signals: list[str],
    recipient_name: str | None = None,
    custom_notes: str | None = None,
) -> tuple[str, str]:
    """Generate tailored subject line and email body grounded in lead signals."""
    greeting = f"Hi {recipient_name.strip()}," if recipient_name and recipient_name.strip() else f"Hello {company.strip()} Team,"
    
    signal_highlights = ""
    if signals:
        top_signals = signals[:2]
        signal_highlights = f"\n\nWe noticed recent developments at {company}, including: " + "; ".join(top_signals) + "."

    notes_addition = f"\n\nNote: {custom_notes.strip()}" if custom_notes and custom_notes.strip() else ""

    subject = f"Optimizing operations & automated workflows for {company}"
    body = (
        f"{greeting}"
        f"{signal_highlights}"
        f"\n\nOur AskforWrite Company OS platform helps leaders in the {industry} space streamline on-ground operations coordination, "
        f"workforce management, and automated operational reporting with verifiable data pipelines."
        f"{notes_addition}"
        f"\n\nWould you be open to a brief 10-minute exploratory conversation next week?"
        f"\n\nBest regards,"
        f"\nVipul Choubisa\n"
        f"AskforWrite AI Solutions"
    )
    return sanitize_outreach_content(subject), sanitize_outreach_content(body)



def draft_outreach(
    db: Session,
    lead_id: str,
    org_id: str | None,
    recipient_email: str | None,
    recipient_name: str | None,
    custom_notes: str | None,
    channel: str,
    idempotency_key: str,
    correlation_id: str,
    requested_by: str,
) -> dict[str, object]:
    """Create a personalized outreach draft and submit a durable approval request."""
    lead = db.get(LeadRecordRow, lead_id)
    if not lead:
        raise ValueError(f"Lead '{lead_id}' not found")
    if lead.do_not_contact or lead.status == "DO_NOT_CONTACT":
        raise ValueError("Cannot draft outreach for do-not-contact leads")

    target_email = (recipient_email or lead.public_contact_channel or "").strip()
    if not target_email or "@" not in target_email:
        raise ValueError("A valid recipient email is required to draft outreach")

    # Safety: Prevent demo leads and fake .example domains from entering real outreach
    app_env = os.getenv("APP_ENV", "development").lower()
    lead_domain = (lead.domain or "").lower()
    lead_email_domain = target_email.split("@")[-1].lower() if "@" in target_email else ""
    if lead_domain.endswith(".example.com") or lead_email_domain.endswith(".example.com"):
        if app_env == "production":
            raise ValueError(
                f"Outreach to synthetic / demo domain '{lead_domain or lead_email_domain}' is strictly prohibited in production."
            )

    # Safety: Prohibit outreach to competitors or firms in similar operations
    target_domain = lead_email_domain or lead_domain
    if target_domain in COMPETITOR_DOMAINS or any(cd in target_domain for cd in COMPETITOR_DOMAINS):
        raise ValueError(f"Outreach to competitor or similar-operations firm '{target_domain}' is strictly prohibited.")
    company_lower = lead.company.lower()
    if any(kw in company_lower for kw in COMPETITOR_COMPANY_KEYWORDS):
        raise ValueError(f"Outreach to competitor firm '{lead.company}' is strictly prohibited.")

    # Check organizational credit limit
    org: OrganizationRecord | None = None
    if org_id:
        org = db.get(OrganizationRecord, org_id)
        if not org:
            raise ValueError(f"Organization '{org_id}' not found")
        if not org.is_active:
            raise ValueError(f"Organization '{org.name}' is inactive")
        if org.outreach_credits_used >= org.outreach_credits_limit:
            raise ValueError(
                f"Outreach credit quota reached ({org.outreach_credits_used}/{org.outreach_credits_limit} credits used). "
                "Please upgrade your subscription to send more messages."
            )

    # Check if duplicate idempotency key exists
    existing = db.query(OutreachRecord).filter_by(idempotency_key=idempotency_key).first()
    if existing:
        return {
            "outreach_id": existing.id,
            "lead_id": existing.lead_id,
            "status": existing.status,
            "subject": existing.subject,
            "recipient_email": existing.recipient_email,
            "approval_id": existing.approval_id,
        }

    commercial = generate_commercial_pitch(
        company=lead.company,
        website=lead.website,
        industry=lead.industry,
        signals=lead.observed_signals or [],
        geography=lead.geography or "India",
        recipient_name=recipient_name,
        custom_notes=custom_notes,
    )
    subject = sanitize_outreach_content(str(commercial["subject"]))
    body = sanitize_outreach_content(str(commercial["body_text"]))
    payment_link = commercial["payment_link"]
    package_key = commercial["package_key"]


    outreach_id = str(uuid.uuid4())
    task_id = lead.task_id or str(uuid.uuid4())
    if not lead.task_id:
        lead.task_id = task_id
        db.add(lead)

    task = db.get(TaskRecord, task_id)
    if not task:
        task = TaskRecord(
            id=task_id,
            correlation_id=correlation_id,
            objective=f"Commercial outreach campaign for {lead.company}",
            status="IN_PROGRESS",
        )
        db.add(task)
        db.flush()

    # Request Owner approval via the durable HITL framework
    approval_resp = request_approval(
        db=db,
        task_id=task_id,
        lead_id=lead_id,
        action="external_sales_outreach",
        detail={
            "outreach_id": outreach_id,
            "recipient_email": target_email,
            "recipient_name": recipient_name,
            "subject": subject,
            "channel": channel,
            "org_id": org_id,
            "payment_link": payment_link,
            "package_key": package_key,
            "custom_notes": custom_notes,
        },
        idempotency_key=f"appr-outreach-{idempotency_key}",
        requested_by=requested_by,
        correlation_id=correlation_id,
        commit=False,
    )
    approval_id = str(approval_resp["approval_id"])

    outreach = OutreachRecord(
        id=outreach_id,
        org_id=org_id,
        lead_id=lead_id,
        task_id=task_id,
        recipient_email=target_email,
        recipient_name=recipient_name,
        subject=subject,
        body_text=body,
        channel=channel,
        status="PENDING_APPROVAL",
        approval_id=approval_id,
        idempotency_key=idempotency_key,
        metadata_json={
            "custom_notes": custom_notes,
            "correlation_id": correlation_id,
            "requested_by": requested_by,
            "payment_link": payment_link,
            "package_key": package_key,
            "provider": commercial["provider"],
            "price_str": commercial["price_str"],
        },
    )
    db.add(outreach)

    db.add(
        AuditLog(
            task_id=task_id,
            correlation_id=correlation_id,
            agent_id=requested_by,
            capability_name=CAPABILITY_NAME,
            action="draft_outreach",
            input_payload={"lead_id": lead_id, "recipient_email": target_email, "org_id": org_id},
            output_payload={
                "outreach_id": outreach_id,
                "approval_id": approval_id,
                "status": "PENDING_APPROVAL",
                "payment_link": payment_link,
                "package_key": package_key,
            },
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(outreach)

    return {
        "outreach_id": outreach.id,
        "org_id": outreach.org_id,
        "lead_id": outreach.lead_id,
        "recipient_email": outreach.recipient_email,
        "recipient_name": outreach.recipient_name,
        "subject": outreach.subject,
        "body_text": outreach.body_text,
        "channel": outreach.channel,
        "status": outreach.status,
        "approval_id": outreach.approval_id,
        "payment_link": payment_link,
        "package_key": package_key,
        "credits_remaining": (org.outreach_credits_limit - org.outreach_credits_used) if org else None,
    }


def dispatch_outreach(
    db: Session,
    outreach_id: str,
    correlation_id: str,
    dispatched_by: str,
    dispatcher: EmailDispatcher | None = None,
) -> dict[str, object]:
    """Verify owner approval and dispatch the outbound outreach message."""
    outreach = db.get(OutreachRecord, outreach_id)
    if not outreach:
        raise ValueError(f"Outreach record '{outreach_id}' not found")

    if outreach.status == "DISPATCHED":
        lead = db.get(LeadRecordRow, outreach.lead_id) if outreach.lead_id else None
        org = db.get(OrganizationRecord, outreach.org_id) if outreach.org_id else None
        return {
            "outreach_id": outreach.id,
            "status": "DISPATCHED",
            "message": "Outreach message already dispatched",
            "sent_at": outreach.sent_at.isoformat() if outreach.sent_at else None,
            "recipient_email": outreach.recipient_email,
            "receipt": None,
            "lead_status": lead.status if lead else "CONTACTED",
            "credits_remaining": (org.outreach_credits_limit - org.outreach_credits_used) if org else None,
        }

    # Verify Owner Approval status
    if not outreach.approval_id:
        raise ValueError("Outreach has no linked owner approval request")

    approval = db.get(ApprovalRequest, outreach.approval_id)
    if not approval:
        raise ValueError(f"Approval request '{outreach.approval_id}' not found")

    if approval.status != "APPROVED":
        raise ValueError(
            f"Outreach cannot be dispatched without Owner approval (current approval status: {approval.status})"
        )

    # Verify and deduct organization outreach quota
    org: OrganizationRecord | None = None
    if outreach.org_id:
        org = db.get(OrganizationRecord, outreach.org_id)
        if org:
            if org.outreach_credits_used >= org.outreach_credits_limit:
                raise ValueError(
                    f"Outreach quota reached ({org.outreach_credits_used}/{org.outreach_credits_limit} credits used)"
                )

    # Dispatch message via provider
    active_dispatcher = dispatcher or get_email_dispatcher()
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
        raise RuntimeError(f"Message dispatch failed: {exc}") from exc

    now = datetime.now(UTC)
    outreach.status = "DISPATCHED"
    outreach.sent_at = now
    db.add(outreach)

    # Deduct 1 outreach credit
    if org:
        org.outreach_credits_used += 1
        db.add(org)

    # Advance Lead status to CONTACTED
    lead = db.get(LeadRecordRow, outreach.lead_id)
    if lead:
        lead.status = "CONTACTED"
        lead.last_checked = now
        db.add(lead)

    db.add(
        AuditLog(
            task_id=outreach.task_id,
            correlation_id=correlation_id,
            agent_id=dispatched_by,
            capability_name=CAPABILITY_NAME,
            action="dispatch_outreach",
            input_payload={"outreach_id": outreach_id, "recipient_email": outreach.recipient_email},
            output_payload={"status": "DISPATCHED", "receipt": receipt},
            status="COMPLETED",
        )
    )

    seal_task_to_block(
        db=db,
        task_id=outreach.task_id,
        capability_name=CAPABILITY_NAME,
        action="dispatch_outreach",
        payload={
            "outreach_id": outreach_id,
            "status": "DISPATCHED",
            "recipient_email": outreach.recipient_email,
            "dispatched_by": dispatched_by,
        },
        sealed_by=dispatched_by,
        commit=False,
    )
    db.commit()
    db.refresh(outreach)

    return {
        "outreach_id": outreach.id,
        "status": outreach.status,
        "sent_at": outreach.sent_at.isoformat() if outreach.sent_at else None,
        "recipient_email": outreach.recipient_email,
        "receipt": receipt,
        "lead_status": lead.status if lead else None,
        "credits_remaining": (org.outreach_credits_limit - org.outreach_credits_used) if org else None,
    }
