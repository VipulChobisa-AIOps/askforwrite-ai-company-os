"""Deterministic Customer Discovery domain logic for the MVP."""

from dataclasses import asdict, dataclass
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from app.agents.sources import OfflineSignalProvider, SignalBundle, SourceProvider

RESEARCH_THRESHOLD = 0.30

PRODUCT_KEYWORDS = {
    "field_force_management": (
        "field", "supervisor", "attendance", "gps", "tracking",
        "geofence", "workforce", "sales rep",
    ),
    "warehouse_automation": ("warehouse", "inventory", "stock"),
    "marketing_suite": ("marketing", "content", "seo", "campaign"),
}


def normalize_domain(url_or_domain: str) -> str:
    """Normalize a URL or domain string into a clean hostname without www or ports."""
    if not url_or_domain:
        return ""
    val = url_or_domain.strip().lower()
    if not val.startswith(("http://", "https://")):
        val = "https://" + val
    parsed = urlsplit(val)
    host = parsed.netloc or parsed.path
    if ":" in host:
        host = host.split(":")[0]
    host = host.removeprefix("www.")
    return host.strip("/").strip()


@dataclass(frozen=True)
class LeadRecord:
    lead_id: str
    company: str
    website: str
    industry: str
    geography: str
    observed_signals: tuple[str, ...]
    sources: tuple[dict[str, str], ...]
    product_match: str | None
    fit_score: float
    confidence: float
    public_contact_channel: str | None
    recommended_next_step: str
    do_not_contact: bool
    status: str
    domain: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DiscoveryResult:
    objective: str
    data_mode: str
    leads: tuple[LeadRecord, ...]
    outreach_performed: bool = False
    persistence: str = "not_configured"

    def to_dict(self) -> dict[str, object]:
        return {
            "objective": self.objective,
            "data_mode": self.data_mode,
            "outreach_performed": self.outreach_performed,
            "persistence": self.persistence,
            "leads": [lead.to_dict() for lead in self.leads],
        }


def _score(signals: tuple[str, ...]) -> tuple[float, str | None]:
    text = " ".join(signals).casefold()
    best_product = None
    best_score = 0.0
    for product, keywords in PRODUCT_KEYWORDS.items():
        hits = sum(keyword in text for keyword in keywords)
        score = round(hits / len(keywords), 3)
        if score > best_score:
            best_product = product
            best_score = score
    return best_score, best_product


# ---------------------------------------------------------------------------
# Competitor & similar-operations block-list
# ---------------------------------------------------------------------------
# Rule: Never contact companies that SELL or BUILD field-operations software,
# GPS/workforce management SaaS, CRMs, or similar tools — only contact
# companies that are direct END-USERS / buyers of such capabilities.
# ---------------------------------------------------------------------------

COMPETITOR_DOMAINS: set[str] = {
    # Direct competitors (field-force / workforce management SaaS)
    "unolo.com",
    "fieldproxy.com",
    "beatroute.io",
    "trackmyteam.com",
    "liqvid.ai",
    "fieldax.com",
    "fieldy.io",
    "fieldaware.com",
    "fieldnation.com",
    "workwave.com",
    "servicemax.com",
    "clicksoftware.com",
    "skedulo.com",
    "commusoft.co.uk",
    "simpro.com",
    "loc8.com",
    "mobileforce.io",
    "zuper.co",
    "repsly.com",
    "badger-maps.com",
    "spotio.com",
    "salesdiary.in",
    "dista.ai",
    "eazy-erp.com",
    # CRM / sales automation SaaS (similar-ops)
    "leadsquared.com",
    "salesforce.com",
    "zoho.com",
    "hubspot.com",
    "pipedrive.com",
    "freshsales.com",
    "close.com",
    "freshworks.com",
    "insightly.com",
    "outreach.io",
    "salesloft.com",
    "apollo.io",
    "zoominfo.com",
    # Blocked by manual DNC flag
    "blocked-example.com",
}

# Company name fragments indicating a competitor or similar-ops software vendor.
# Checked case-insensitively against the company name string.
COMPETITOR_COMPANY_KEYWORDS: tuple[str, ...] = (
    "unolo", "leadsquared", "fieldproxy", "beatroute", "repsly",
    "spotio", "badger maps", "salesdiary", "dista", "mobileforce",
    "zuper", "skedulo", "servicemax", "workwave", "fieldaware",
    "fieldax", "fieldy", "fieldnation",
)

# Industry strings that identify companies SELLING similar software (not end-users).
# If a prospect's industry contains any of these phrases, they are blocked.
SIMILAR_OPERATION_INDUSTRY_SIGNALS: tuple[str, ...] = (
    "field force software",
    "field service software",
    "field service management",
    "workforce management software",
    "gps tracking software",
    "gps tracking saas",
    "crm software",
    "crm saas",
    "sales force automation software",
    "sales automation software",
    "field operations software",
    "attendance management software",
    "hr tech saas",
    "hrtech",
    "sales enablement software",
)


def _is_do_not_contact(candidate: SignalBundle) -> bool:
    """Return True if this candidate must never be contacted.

    Blocks:
    1. Leads flagged do_not_contact in the data source.
    2. Any domain present in COMPETITOR_DOMAINS.
    3. Any company name containing a known competitor fragment.
    4. Any company whose industry signals they are a SaaS/software vendor
       operating in the same space (field-ops, CRM, workforce mgmt, GPS).
    """
    if candidate.do_not_contact:
        return True

    # Domain check
    hostname = (urlsplit(candidate.website).hostname or "").casefold().rstrip(".")
    if any(hostname == c or hostname.endswith(f".{c}") for c in COMPETITOR_DOMAINS):
        return True

    # Company name keyword check
    company_lower = (candidate.company or "").casefold()
    if any(kw in company_lower for kw in COMPETITOR_COMPANY_KEYWORDS):
        return True

    # Industry signals — block software/SaaS vendors in similar operations
    industry_lower = (candidate.industry or "").casefold()
    if any(sig in industry_lower for sig in SIMILAR_OPERATION_INDUSTRY_SIGNALS):
        return True

    return False


def _to_lead(candidate: SignalBundle, data_mode: str) -> LeadRecord:
    fit_score, product_match = _score(candidate.signals)
    do_not_contact = _is_do_not_contact(candidate)
    source = {
        "url": candidate.website,
        "title": candidate.company,
        "snippet": "; ".join(candidate.signals),
        "data_mode": data_mode,
    }
    lead_id = str(uuid5(NAMESPACE_URL, candidate.website.casefold()))
    next_step = (
        "do_not_contact_review"
        if do_not_contact
        else "owner_review_required_before_contact"
        if fit_score >= RESEARCH_THRESHOLD
        else "recheck_signals"
    )
    return LeadRecord(
        lead_id=lead_id,
        company=candidate.company,
        website=candidate.website,
        domain=normalize_domain(candidate.website),
        industry=candidate.industry,
        geography=candidate.geography,
        observed_signals=candidate.signals,
        sources=(source,),
        product_match=product_match,
        fit_score=fit_score,
        confidence=min(1.0, round(len(candidate.signals) / 4.0, 2)),
        public_contact_channel=candidate.public_contact_channel,
        recommended_next_step=next_step,
        do_not_contact=do_not_contact,
        status="DO_NOT_CONTACT" if do_not_contact else "DISCOVERED",
    )


def run_discovery(
    objective: str,
    provider: SourceProvider | None = None,
    limit: int = 10,
) -> DiscoveryResult:
    """Qualify candidates without performing outreach or claiming persistence."""
    normalized_objective = objective.strip()
    if not normalized_objective:
        raise ValueError("objective must not be empty")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")

    source_provider = provider or OfflineSignalProvider()
    candidates = source_provider.search(normalized_objective, limit=limit)
    leads = tuple(
        _to_lead(candidate, source_provider.data_mode)
        for candidate in candidates
    )
    return DiscoveryResult(
        objective=normalized_objective,
        data_mode=source_provider.data_mode,
        leads=leads,
    )