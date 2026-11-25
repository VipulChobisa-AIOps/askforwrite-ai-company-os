"""Autonomous IMAP Inbox Monitor for Bounces, Opt-Outs, and Prospect Replies.

Keeps AskforWrite's CRM and Owner HITL Approval Queue automatically synchronized:
1. Bounce Sync: Detects MailChannels / SMTP NDR bounce notices and honestly marks
   OutreachRecord.status = "BOUNCED" so bounced emails are never miscounted as delivered.
2. Auto Opt-Out: Immediately records DB suppression (do_not_contact=True) whenever a
   prospect replies with unsubscribe/opt-out intent.
3. Positive Reply Auto-Drafting: Detects genuine prospect replies, transitions their
   commercial pipeline to REPLIED, and automatically stages a HITL-gated Written Scope
   + ₹4,999 Managed SEO Content Pilot checkout reply in the Owner Approval Queue so the
   founder only needs to review and click Approve.
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import (
    AuditLog,
    LeadRecordRow,
    OutreachRecord,
    P2ProspectDossierRecord,
)
from app.services.suppression import add_db_suppression

logger = logging.getLogger(__name__)

_BOUNCE_SENDER_MARKERS = ("mailer-daemon", "postmaster", "bounce.", "mail delivery system")
_BOUNCE_SUBJECT_MARKERS = ("returned mail", "undelivered mail", "delivery status notification", "failure notice", "mail delivery failed")
_OPTOUT_KEYWORDS = ("unsubscribe", "opt out", "opt-out", "stop emailing", "remove me", "do not contact", "not interested")
_POSITIVE_KEYWORDS = ("send scope", "interested", "scope", "pricing", "price", "details", "call", "meet", "pilot", "proposal", "yes")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, enc in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


def _parse_email_datetime(raw_date: str | None) -> datetime | None:
    """Parse an RFC 2822 email Date header into timezone-aware UTC datetime, or None."""
    if not raw_date or not raw_date.strip():
        return None
    try:
        dt = parsedate_to_datetime(raw_date.strip())
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _extract_plain_text(msg: email.message.Message) -> str:
    chunks: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "message/delivery-status"):
                raw = part.get_payload(decode=True)
                if raw:
                    chunks.append(raw.decode("utf-8", errors="replace"))
    else:
        raw = msg.get_payload(decode=True)
        if raw:
            chunks.append(raw.decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def process_inbox_messages(
    db: Session,
    messages: list[dict[str, str]],
    *,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Deterministic processor for parsed inbox messages (testable offline and via live IMAP)."""
    corr_id = correlation_id or str(uuid.uuid4())
    now = datetime.now(UTC)

    outreach_rows = (
        db.query(OutreachRecord)
        .filter(OutreachRecord.status.in_(["SENT", "DISPATCHED", "APPROVED", "PENDING_APPROVAL", "BOUNCED"]))
        .all()
    )
    by_email: dict[str, list[OutreachRecord]] = {}
    for row in outreach_rows:
        em = (row.recipient_email or "").strip().lower()
        if em:
            by_email.setdefault(em, []).append(row)

    bounces_marked: list[dict[str, Any]] = []
    optouts_recorded: list[dict[str, Any]] = []
    replies_staged: list[dict[str, Any]] = []

    for msg in messages:
        sender_raw = (msg.get("from") or "").strip()
        sender_lower = sender_raw.lower()
        subject = (msg.get("subject") or "").strip()
        subject_lower = subject.lower()
        body = (msg.get("body") or "").strip()
        body_lower = body.lower()
        msg_uid = str(msg.get("uid") or uuid.uuid4().hex[:8])

        is_bounce = any(m in sender_lower for m in _BOUNCE_SENDER_MARKERS) or any(
            m in subject_lower for m in _BOUNCE_SUBJECT_MARKERS
        )

        if is_bounce:
            msg_dt = _parse_email_datetime(msg.get("date"))
            is_mailchannels_bounce = "mailchannels" in sender_lower or "mailchannels" in body_lower
            mentioned_emails = {m.lower() for m in _EMAIL_RE.findall(body)}
            matched_reason = "SMTP delivery bounce"
            for line in body.splitlines():
                if any(tok in line.lower() for tok in ("response:", "550", "554", "551", "diagnostic-code", "blocked")):
                    matched_reason = line.strip()[:240]
                    break
            for em in sorted(mentioned_emails):
                if em not in by_email:
                    continue
                for rec in by_email[em]:
                    if rec.status == "BOUNCED":
                        continue
                    # Ignore historical bounces that predate a newer re-dispatch of this record
                    if msg_dt is not None and rec.sent_at is not None:
                        rec_sent_utc = rec.sent_at.replace(tzinfo=UTC) if rec.sent_at.tzinfo is None else rec.sent_at.astimezone(UTC)
                        if msg_dt < rec_sent_utc:
                            continue
                    # Ignore legacy Hostinger/MailChannels SMTP NDRs when latest delivery succeeded via HTTPS API (Resend/Brevo)
                    rec_receipt = (rec.metadata_json or {}).get("dispatch_receipt") or {}
                    rec_provider = str(rec_receipt.get("provider") or "").strip().lower()
                    if is_mailchannels_bounce and rec_provider in ("resend", "brevo"):
                        continue
                    rec.status = "BOUNCED"
                    rec.error_message = matched_reason
                    meta = dict(rec.metadata_json or {})
                    meta["bounce_detected_at"] = now.isoformat()
                    meta["bounce_reason"] = matched_reason
                    meta["external_sent"] = False
                    rec.metadata_json = meta
                    flag_modified(rec, "metadata_json")
                    db.add(rec)

                    dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=rec.lead_id).first()
                    if dossier:
                        dossier.next_action = (
                            f"Email bounced ({matched_reason[:100]}). Re-queue via HTTPS provider (Resend/Brevo) or alternate contact."
                        )
                        dossier.updated_at = now
                        db.add(dossier)

                    bounces_marked.append({
                        "outreach_id": rec.id,
                        "recipient_email": em,
                        "reason": matched_reason,
                    })
            continue

        sender_emails = [m.lower() for m in _EMAIL_RE.findall(sender_lower)]
        sender_email = sender_emails[0] if sender_emails else ""
        if not sender_email or sender_email not in by_email:
            continue

        latest_outreach = sorted(by_email[sender_email], key=lambda r: r.created_at or now)[-1]
        lead = db.get(LeadRecordRow, latest_outreach.lead_id)
        dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=latest_outreach.lead_id).first()

        # 1. Opt-out / Unsubscribe detection (highest priority compliance guard)
        if any(kw in body_lower or kw in subject_lower for kw in _OPTOUT_KEYWORDS):
            add_db_suppression(
                db,
                sender_email,
                reason="imap_reply_unsubscribe",
                source="autonomous_inbox_sync",
            )
            if latest_outreach.lead_id:
                add_db_suppression(
                    db,
                    latest_outreach.lead_id,
                    reason="imap_reply_unsubscribe",
                    source="autonomous_inbox_sync",
                    identifier_type="lead_id",
                )
            if lead:
                lead.do_not_contact = True
                lead.status = "DO_NOT_CONTACT"
                db.add(lead)
            if dossier:
                dossier.pipeline_status = "DISQUALIFIED"
                dossier.next_action = "Opted out via email reply — permanently suppressed."
                dossier.updated_at = now
                db.add(dossier)
            optouts_recorded.append({
                "lead_id": latest_outreach.lead_id,
                "email": sender_email,
                "subject": subject[:120],
            })
            continue

        # 2. Genuine prospect reply -> update CRM + stage HITL-gated scope confirmation reply
        meta = dict(latest_outreach.metadata_json or {})
        processed_uids = list(meta.get("processed_reply_uids") or [])
        if msg_uid in processed_uids:
            continue
        processed_uids.append(msg_uid)
        meta["processed_reply_uids"] = processed_uids[-25:]
        meta["last_reply_at"] = now.isoformat()
        meta["last_reply_snippet"] = body[:300]
        latest_outreach.metadata_json = meta
        flag_modified(latest_outreach, "metadata_json")
        db.add(latest_outreach)

        is_positive = any(kw in body_lower or kw in subject_lower for kw in _POSITIVE_KEYWORDS)
        if lead:
            lead.status = "REPLIED"
            lead.last_checked = now
            db.add(lead)
        if dossier:
            dossier.pipeline_status = "REPLIED"
            dossier.next_action = (
                "Positive reply detected — review & approve staged Written Scope + ₹4,999 checkout reply in Approvals."
                if is_positive
                else "Prospect replied — review inbox snippet and approve follow-up response."
            )
            dossier.updated_at = now
            db.add(dossier)

        # Stage HITL-gated scope confirmation reply draft (Owner ONLY clicks Approve!)
        from app.services.p2_outreach_pipeline import prepare_p2_outreach

        company_name = (lead.company if lead else None) or sender_email.split("@")[-1]
        reply_subject = f"Re: {subject}" if subject and not subject_lower.startswith("re:") else (subject or f"Written Scope — 14-Day Managed SEO Pilot for {company_name}")
        reply_body = (
            f"Hi {company_name} team,\n\n"
            f"Thanks for getting back! Here is the 1-page written scope confirmation for the fixed-scope "
            f"14-Day Managed SEO & Content Pilot (Rs 4,999 one-time):\n\n"
            f"Included Deliverables (14-Day Window from Intake):\n"
            f"1. Technical SEO + GEO Baseline Audit (recorded before-state metrics)\n"
            f"2. Commercial Keyword & Topic Cluster Blueprint\n"
            f"3. 2 Human-Edited 1,500+ Word SEO/GEO Articles + Schema.org JSON-LD (up to 2 revision rounds)\n"
            f"4. WordPress Draft Delivery (live publish only after your explicit written approval) + Final Handoff Report\n\n"
            f"Exclusions: Paid backlinks, PPC/ads spend, custom WP plugin/theme engineering, or promises of fixed search-engine positions.\n\n"
            f"Next Step to Start:\n"
            f"1. Reply 'I accept the above scope for Rs 4,999'\n"
            f"2. Complete checkout here (Razorpay or zero-fee UPI DirectPay): "
            f"https://os.askforwrite.com/services/managed_seo_content_pilot\n\n"
            f"Once payment confirms, your client portal and Day 1-2 intake unlock immediately.\n\n"
            f"Best regards,\nVipul Chobisa\nAskforWrite AI Solutions | info@askforwrite.in"
        )
        try:
            staged = prepare_p2_outreach(
                db,
                lead_id=latest_outreach.lead_id,
                recipient_email=sender_email,
                recipient_name=f"{company_name} Team",
                channel="email",
                subject_override=reply_subject,
                body_override=reply_body,
                custom_notes=f"Auto-staged scope reply for prospect email UID {msg_uid}",
                allow_follow_up=True,
                idempotency_key=f"reply-scope-{latest_outreach.lead_id}-{msg_uid}",
                actor="autonomous_inbox_sync_agent",
                correlation_id=corr_id,
            )
            # Mark draft for 1-click auto-dispatch upon Owner approval
            staged_rec = db.get(OutreachRecord, staged.get("outreach_id"))
            if staged_rec:
                smeta = dict(staged_rec.metadata_json or {})
                smeta["auto_dispatch_on_approval"] = True
                staged_rec.metadata_json = smeta
                flag_modified(staged_rec, "metadata_json")
                db.add(staged_rec)
            if dossier:
                dossier.pipeline_status = "REPLIED"
                dossier.next_action = (
                    f"Positive reply detected — review & approve staged scope reply '{staged.get('outreach_id')}' in Approvals."
                )
                db.add(dossier)
            replies_staged.append({
                "lead_id": latest_outreach.lead_id,
                "email": sender_email,
                "positive_intent": is_positive,
                "staged_outreach_id": staged.get("outreach_id"),
                "approval_id": staged.get("approval_id"),
            })
        except Exception as exc:
            logger.warning("Could not stage auto-reply draft for %s: %s", sender_email, exc)
            replies_staged.append({
                "lead_id": latest_outreach.lead_id,
                "email": sender_email,
                "positive_intent": is_positive,
                "note": f"Reply recorded in CRM; draft skipped: {exc}",
            })

    if bounces_marked or optouts_recorded or replies_staged:
        db.add(
            AuditLog(
                task_id=str(uuid.uuid4()),
                correlation_id=corr_id,
                agent_id="autonomous_inbox_sync_agent",
                capability_name="autonomous_inbox_sync",
                action="sync_inbox_replies_and_bounces",
                input_payload={"messages_scanned": len(messages)},
                output_payload={
                    "bounces_marked": len(bounces_marked),
                    "optouts_recorded": len(optouts_recorded),
                    "replies_staged": len(replies_staged),
                },
                status="COMPLETED",
            )
        )
        db.commit()

    return {
        "status": "COMPLETED",
        "messages_scanned": len(messages),
        "bounces_marked_count": len(bounces_marked),
        "bounces_marked": bounces_marked,
        "optouts_recorded_count": len(optouts_recorded),
        "optouts_recorded": optouts_recorded,
        "replies_staged_count": len(replies_staged),
        "replies_staged": replies_staged,
    }


def sync_inbox_replies_and_bounces(
    db: Session,
    *,
    limit: int = 30,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Connect read-only to configured IMAP mailbox and process recent bounces/opt-outs/replies."""
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    ext_disabled = os.getenv("ENABLE_EXTERNAL_SIDE_EFFECTS", "").strip().lower() in ("0", "false", "no")
    if ext_disabled or app_env in ("staging", "simulation", "test"):
        return {
            "status": "SKIPPED_SIMULATION",
            "messages_scanned": 0,
            "bounces_marked_count": 0,
            "optouts_recorded_count": 0,
            "replies_staged_count": 0,
        }

    imap_host = (os.getenv("IMAP_HOST") or "imap.hostinger.com").strip()
    imap_port = int(os.getenv("IMAP_PORT", "993"))
    imap_user = (os.getenv("IMAP_USERNAME") or os.getenv("SMTP_USERNAME") or os.getenv("SMTP_USER") or "").strip()
    imap_pass = (os.getenv("IMAP_PASSWORD") or os.getenv("SMTP_PASSWORD") or "").strip()
    if not imap_user or not imap_pass:
        return {
            "status": "SKIPPED_UNCONFIGURED",
            "reason": "IMAP/SMTP mailbox credentials not configured.",
            "messages_scanned": 0,
            "bounces_marked_count": 0,
            "optouts_recorded_count": 0,
            "replies_staged_count": 0,
        }

    parsed_messages: list[dict[str, str]] = []
    try:
        conn = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=12)
        try:
            conn.login(imap_user, imap_pass)
            conn.select("INBOX", readonly=True)
            _, data = conn.search(None, "ALL")
            raw_ids = data[0].split() if data and data[0] else []
            for mid in raw_ids[-max(1, min(limit, 100)):]:
                _, msg_data = conn.fetch(mid, "(BODY.PEEK[])")
                if not msg_data or not msg_data[0] or not isinstance(msg_data[0], tuple):
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                parsed_messages.append({
                    "uid": mid.decode("utf-8", errors="ignore"),
                    "from": _decode_mime_header(msg.get("From")),
                    "subject": _decode_mime_header(msg.get("Subject")),
                    "date": _decode_mime_header(msg.get("Date")),
                    "body": _extract_plain_text(msg),
                })
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("IMAP inbox sync unavailable (%s:%s): %s", imap_host, imap_port, exc)
        return {
            "status": "IMAP_UNREACHABLE",
            "reason": str(exc),
            "messages_scanned": 0,
            "bounces_marked_count": 0,
            "optouts_recorded_count": 0,
            "replies_staged_count": 0,
        }

    return process_inbox_messages(db, parsed_messages, correlation_id=correlation_id)
