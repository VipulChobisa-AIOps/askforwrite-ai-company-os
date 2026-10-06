"""Deterministic Customer Discovery domain logic for the MVP."""

from dataclasses import asdict, dataclass
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from app.agents.sources import OfflineSignalProvider, SignalBundle, SourceProvider

RESEARCH_THRESHOLD = 0.30

PRODUCT_KEYWORDS = {
    "field_force_management": (
        "field", "supervisor", "attendance", "gps", "tracking",
        "geofence", "workforce", "sales force",
    ),
    "warehouse_automation": ("warehouse", "inventory", "stock"),
    "marketing_suite": ("marketing", "content", "seo", "campaign"),
}


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


def _is_do_not_contact(candidate: SignalBundle) -> bool:
    hostname = (urlsplit(candidate.website).hostname or "").casefold().rstrip(".")
    return candidate.do_not_contact or hostname == "blocked-example.com"


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