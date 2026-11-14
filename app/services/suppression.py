"""Suppression and opt-out registry for consent and compliance-aware outreach.

Prevents contacting domains, role-based mailboxes, or recipients that have opted out,
unsubscribed, or requested suppression under statutory compliance standards.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# System-level suppressed email prefixes (role-based, compliance, unmonitored)
SUPPRESSED_PREFIXES: tuple[str, ...] = (
    "abuse@",
    "postmaster@",
    "spam@",
    "unsubscribe@",
    "privacy@",
    "legal@",
    "noc@",
    "hostmaster@",
    "mailer-daemon@",
)

# Registry of suppressed / opted-out domains and specific email addresses
_SUPPRESSED_EMAILS: set[str] = set()
_SUPPRESSED_DOMAINS: set[str] = {
    "donotcontact.org",
    "optout.net",
    "suppressed-lead.com",
    "optout-sample.com",
}


def add_to_suppression_list(identifier: str) -> None:
    """Add an email or domain to the persistent suppression registry."""
    if not identifier:
        return
    cleaned = identifier.strip().lower()
    if "@" in cleaned:
        _SUPPRESSED_EMAILS.add(cleaned)
    else:
        # Strip protocol if domain passed as URL
        if "://" in cleaned:
            cleaned = urlsplit(cleaned).hostname or cleaned
        _SUPPRESSED_DOMAINS.add(cleaned.removeprefix("www."))
    logger.info("Identifier '%s' added to suppression list", cleaned)


def is_suppressed(email_or_domain: str | None) -> bool:
    """Check if an email address, domain, or website is on the suppression list."""
    if not email_or_domain:
        return False
    val = email_or_domain.strip().lower()

    if "@" in val:
        if any(val.startswith(prefix) for prefix in SUPPRESSED_PREFIXES):
            return True
        if val in _SUPPRESSED_EMAILS:
            return True
        domain = val.split("@", 1)[1].removeprefix("www.")
        return domain in _SUPPRESSED_DOMAINS or any(domain.endswith(f".{sd}") for sd in _SUPPRESSED_DOMAINS)

    # Domain / URL check
    if "://" in val:
        val = urlsplit(val).hostname or val
    val = val.removeprefix("www.").rstrip("/")
    if val in _SUPPRESSED_DOMAINS or any(val.endswith(f".{sd}") for sd in _SUPPRESSED_DOMAINS):
        return True

    return False


def _normalize_identifier(identifier: str) -> tuple[str, str]:
    cleaned = identifier.strip().lower()
    if "@" in cleaned:
        return "email", cleaned
    if "://" in cleaned:
        cleaned = urlsplit(cleaned).hostname or cleaned
    cleaned = cleaned.removeprefix("www.").rstrip("/")
    return "domain", cleaned


def add_db_suppression(
    db,
    identifier: str,
    *,
    reason: str = "Opt-out requested",
    source: str = "unsubscribe_endpoint",
    identifier_type: str | None = None,
) -> dict[str, object]:
    """Persist an email, domain, or lead_id into p2_suppression_entries AND memory registry."""
    from app.db.models import P2SuppressionEntryRecord

    inferred_type, norm_val = _normalize_identifier(identifier)
    id_type = identifier_type or inferred_type
    if id_type != "lead_id":
        add_to_suppression_list(norm_val)

    existing = db.query(P2SuppressionEntryRecord).filter_by(identifier_value=norm_val).first()
    if existing:
        existing.is_active = True
        existing.reason = reason[:300]
        existing.source = source[:64]
        db.add(existing)
        return {"id": existing.id, "identifier": norm_val, "identifier_type": existing.identifier_type, "active": True}

    rec = P2SuppressionEntryRecord(
        identifier_type=id_type,
        identifier_value=norm_val,
        reason=reason[:300],
        source=source[:64],
        is_active=True,
    )
    db.add(rec)
    db.flush()
    return {"id": rec.id, "identifier": norm_val, "identifier_type": id_type, "active": True}


def is_db_suppressed(db, email_or_domain: str | None, *, lead_id: str | None = None) -> tuple[bool, str | None]:
    """Check DB-backed suppression table + in-memory compliance lists."""
    from app.db.models import LeadRecordRow, P2SuppressionEntryRecord

    if lead_id:
        lead = db.get(LeadRecordRow, lead_id)
        if lead and (lead.do_not_contact or lead.status == "DO_NOT_CONTACT"):
            return True, "lead_marked_do_not_contact"
        entry = db.query(P2SuppressionEntryRecord).filter_by(
            identifier_value=lead_id.strip().lower(), is_active=True
        ).first()
        if entry:
            return True, entry.reason

    if not email_or_domain:
        return False, None

    if is_suppressed(email_or_domain):
        return True, "system_compliance_or_memory_suppression"

    _, norm_val = _normalize_identifier(email_or_domain)
    candidates = [norm_val]
    if "@" in norm_val:
        candidates.append(norm_val.split("@", 1)[1].removeprefix("www."))

    for cand in candidates:
        row = db.query(P2SuppressionEntryRecord).filter_by(
            identifier_value=cand, is_active=True
        ).first()
        if row:
            return True, row.reason
    return False, None
