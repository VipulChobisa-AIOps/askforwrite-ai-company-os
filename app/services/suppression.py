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
