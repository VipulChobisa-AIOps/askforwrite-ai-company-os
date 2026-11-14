"""P2 Prospect Intelligence, 6-Criterion Lead Qualification, & Account Intelligence Brief Service.

Commercial target segment:
- Small and medium-sized digital marketing and SEO agencies in India.
- Verified entry offer: AskforWrite Managed SEO & Content Pilot (14-Day) (`managed_seo_content_pilot`, ₹4,999 / $59).
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.agents.discovery import COMPETITOR_COMPANY_KEYWORDS, COMPETITOR_DOMAINS, normalize_domain
from app.agents.llm_client import generate as llm_generate
from app.agents.llm_client import has_gemini_api_key
from app.agents.smb_search_source import is_valid_commercial_domain
from app.agents.sources import fetch_and_enrich_website
from app.db.models import (
    AuditLog,
    LeadRecordRow,
    P2ProspectDossierRecord,
    ResearchRecord,
    TaskRecord,
)
from app.services.catalog import CATALOG, get_modular_pricing_contract, get_package
from app.services.connectors import check_connector_execution_allowed
from app.services.evidence import record_execution_evidence
from app.services.execution_guard import resolve_execution_mode

P2_PIPELINE_STATUSES: tuple[str, ...] = (
    "NEW",
    "RESEARCHING",
    "QUALIFIED",
    "DISQUALIFIED",
    "APPROVAL_PENDING",
    "CONTACTED",
    "RESPONDED",
    "DISCOVERY",
    "PROPOSAL_PENDING",
    "WON",
    "LOST",
    "DO_NOT_CONTACT",
)

DEFAULT_QUALIFICATION_WEIGHTS: dict[str, int] = {
    "icp_fit": 25,
    "need_evidence": 20,
    "activity_website_quality": 15,
    "service_fit": 15,
    "contact_validity": 15,
    "evidence_freshness": 10,
}

DEFAULT_MIN_QUALIFICATION_SCORE = 60.0

_CORPORATE_SUFFIX_RE = re.compile(
    r"\b(pvt|private|ltd|limited|llp|inc|incorporated|corp|corporation|co|services|solutions|agency|digital|media)\b",
    re.IGNORECASE,
)

_SYNTHETIC_MARKERS = (
    "example.com",
    "example.org",
    "example.net",
    "example.in",
    ".example",
    ".test",
    ".invalid",
    ".local",
    "localhost",
    "127.0.0.1",
    "synthetic",
    "offline_synthetic",
    "fake_fixture",
    "dummy-agency",
    "mock-agency",
)


def normalize_company_identity(company_name: str) -> str:
    """Canonical company identity key for cross-source deduplication."""
    cleaned = _CORPORATE_SUFFIX_RE.sub("", company_name or "")
    cleaned = re.sub(r"[^a-z0-9]+", "", cleaned.lower())
    return cleaned or re.sub(r"[^a-z0-9]+", "", (company_name or "").lower())


def is_synthetic_fixture_prospect(
    *,
    domain: str | None = None,
    website: str | None = None,
    source_url: str | None = None,
    source_type: str | None = None,
    email: str | None = None,
) -> tuple[bool, str | None]:
    """Detect synthetic/test fixtures so they are rejected from the production prospect pipeline."""
    norm_dom = normalize_domain(domain or website or "")
    if not norm_dom or not is_valid_commercial_domain(norm_dom):
        return True, f"Invalid or synthetic commercial domain '{norm_dom or domain or website}'"

    haystack = " ".join(
        str(x or "").lower() for x in (norm_dom, website, source_url, source_type, email)
    )
    for marker in _SYNTHETIC_MARKERS:
        if marker in haystack:
            return True, f"Synthetic fixture marker '{marker}' rejected from production prospect pipeline"

    if (source_type or "").strip().lower() in ("synthetic", "offline_synthetic", "mock", "fixture"):
        return True, f"Synthetic source_type '{source_type}' cannot enter real prospect pipeline"

    if norm_dom in COMPETITOR_DOMAINS:
        return True, f"Competitor domain '{norm_dom}' excluded from commercial outreach pipeline"

    return False, None


def verify_pilot_offer_contract(sku_key: str = "managed_seo_content_pilot") -> dict[str, Any]:
    """Return verified live catalog contract for the pilot SKU so claims never drift from catalog."""
    pkg = get_package(sku_key)
    if not pkg:
        raise ValueError(f"Catalog SKU '{sku_key}' not found in central product catalog")
    contract = get_modular_pricing_contract(pkg.key)
    return {
        "sku_key": pkg.key,
        "name": pkg.name,
        "category": pkg.category,
        "billing_type": contract["billing_type"],
        "billing_interval": contract["billing_interval"],
        "renewal_policy": contract["renewal_policy"],
        "price_inr": pkg.price_inr,
        "price_usd": pkg.price_usd,
        "included_modules": contract["included_modules"],
        "entitled_capabilities": list(pkg.entitled_capabilities),
        "included_credits": contract["included_credits"],
        "deliverables": list(pkg.deliverables),
        "scope_notes": [
            "1 technical SEO/GEO audit report (PDF & Markdown)",
            "1 commercial keyword cluster & competitor gap map",
            "2 human-reviewed authoritative articles (1,500+ words each) with Schema.org JSON-LD",
            "WordPress draft staging or Markdown/HTML export within 14-day pilot window",
        ],
        "non_guarantees": [
            "No search ranking position guarantee (#1 ranking is not guaranteed)",
            "No guaranteed ROI or revenue multiple",
            "Automatic recurring renewal is disabled; conversion after 14 days requires explicit buyer consent",
        ],
    }


def _evaluate_india_agency_icp(
    *,
    business_category: str,
    location: str,
    services: list[str],
    visible_seo_activity: list[str],
    needs: list[str],
) -> tuple[bool, float, str]:
    corpus = " ".join([business_category, location, *services, *visible_seo_activity, *needs]).lower()
    is_india = bool(
        re.search(
            r"\b(india|bengaluru|bangalore|mumbai|delhi|ncr|noida|gurgaon|gurugram|hyderabad|pune|chennai|kolkata|ahmedabad|jaipur|udaipur|surat|kochi|indore)\b",
            location.lower(),
        )
    )
    is_agency = any(
        kw in corpus
        for kw in ("seo", "digital marketing", "content marketing", "performance marketing", "agency", "growth marketing")
    )
    if is_india and is_agency:
        return True, 1.0, "India-based digital marketing / SEO agency confirmed."
    if is_india or is_agency:
        return False, 0.55, "Partial ICP match (missing explicit India location or agency category)."
    return False, 0.2, "Outside primary target ICP (India SMB digital marketing / SEO agencies)."


def evaluate_qualification_score(
    *,
    company: str,
    business_category: str,
    location: str,
    website: str,
    source_url: str,
    collected_at: datetime,
    agency_profile: dict[str, Any],
    public_contacts: list[dict[str, Any]],
    research_claims: list[dict[str, Any]],
    weights: dict[str, int] | None = None,
    min_qualify_score: float = DEFAULT_MIN_QUALIFICATION_SCORE,
) -> dict[str, Any]:
    """Compute transparent 6-criterion qualification rubric with explicit evidence links."""
    w = {**DEFAULT_QUALIFICATION_WEIGHTS, **(weights or {})}
    total_weight = sum(w.values()) or 100

    services = [str(s) for s in agency_profile.get("actual_services", []) if s]
    needs = [str(s) for s in agency_profile.get("publicly_verifiable_needs", []) if s]
    activity = [str(s) for s in agency_profile.get("visible_seo_content_activity", []) if s]

    _, icp_ratio, icp_reason = _evaluate_india_agency_icp(
        business_category=business_category,
        location=location,
        services=services,
        visible_seo_activity=activity,
        needs=needs,
    )

    verified_claims = [c for c in research_claims if c.get("classification") == "VERIFIED_FACT"]
    need_ratio = min(1.0, (len(needs) * 0.4 + len(verified_claims) * 0.2)) if needs or verified_claims else 0.15
    need_reason = (
        f"{len(needs)} verifiable need signal(s) backed by {len(verified_claims)} cited fact(s)."
        if needs
        else "Limited public need signals observed; discovery call needed to confirm pain."
    )

    parsed_url = urlparse(website if "://" in website else f"https://{website}")
    has_https = parsed_url.scheme == "https"
    activity_ratio = min(1.0, (0.4 if has_https else 0.15) + min(0.6, len(activity) * 0.25 + len(services) * 0.1))
    activity_reason = (
        f"Active domain ({'HTTPS' if has_https else 'HTTP'}), {len(services)} declared services, "
        f"{len(activity)} visible SEO/content signals."
    )

    seo_fit_corpus = " ".join(services + needs + activity + [business_category]).lower()
    seo_fit_hits = sum(
        1
        for kw in ("seo", "content", "blog", "article", "audit", "schema", "organic", "copy", "wordpress")
        if kw in seo_fit_corpus
    )
    service_fit_ratio = min(1.0, 0.2 + seo_fit_hits * 0.2)
    service_fit_reason = (
        f"Matched {seo_fit_hits} SEO/content delivery signal(s) against 14-Day Managed SEO & Content Pilot."
    )

    verified_contacts = [c for c in public_contacts if c.get("verified") is True and "@" in str(c.get("value", ""))]
    unverified_contacts = [c for c in public_contacts if not c.get("verified") and c.get("value")]
    if verified_contacts:
        contact_ratio = 1.0
        contact_reason = f"Public contact verified ({verified_contacts[0].get('value')}) from source evidence."
    elif unverified_contacts:
        contact_ratio = 0.45
        contact_reason = "Only unverified/generic contact channel found; manual contact verification recommended."
    else:
        contact_ratio = 0.0
        contact_reason = "No public contact email or form available."

    now = datetime.now(UTC)
    collected_aware = collected_at if collected_at.tzinfo else collected_at.replace(tzinfo=UTC)
    age_days = max(0.0, (now - collected_aware).total_seconds() / 86400.0)
    if age_days <= 14:
        freshness_ratio = 1.0
    elif age_days <= 45:
        freshness_ratio = 0.7
    elif age_days <= 90:
        freshness_ratio = 0.4
    else:
        freshness_ratio = 0.15
    freshness_reason = f"Evidence collected {age_days:.1f} day(s) ago from {source_url}."

    criteria_ratios = {
        "icp_fit": (icp_ratio, icp_reason, [source_url]),
        "need_evidence": (need_ratio, need_reason, [c.get("source_url", source_url) for c in verified_claims[:3]]),
        "activity_website_quality": (activity_ratio, activity_reason, [website]),
        "service_fit": (service_fit_ratio, service_fit_reason, [source_url]),
        "contact_validity": (
            contact_ratio,
            contact_reason,
            [str(c.get("source_url", source_url)) for c in (verified_contacts or unverified_contacts)[:2]],
        ),
        "evidence_freshness": (freshness_ratio, freshness_reason, [source_url]),
    }

    criteria_breakdown: dict[str, Any] = {}
    weighted_sum = 0.0
    for key, (ratio, explanation, refs) in criteria_ratios.items():
        max_pts = float(w.get(key, 0))
        pts = round(max_pts * ratio, 2)
        weighted_sum += pts
        criteria_breakdown[key] = {
            "score": pts,
            "max_score": max_pts,
            "weight_percent": round((max_pts / total_weight) * 100.0, 1),
            "explanation": explanation,
            "supporting_evidence": [r for r in refs if r],
        }

    total_score = round((weighted_sum / total_weight) * 100.0, 2)
    disq_reasons: list[str] = []
    if icp_ratio < 0.4:
        disq_reasons.append("Outside target India digital marketing / SEO agency ICP")
    if contact_ratio == 0.0:
        disq_reasons.append("No usable public contact channel captured")
    if total_score < min_qualify_score:
        disq_reasons.append(f"Qualification score {total_score} below threshold {min_qualify_score}")

    is_qualified = len(disq_reasons) == 0 and total_score >= min_qualify_score
    fit_tier = "HIGH_FIT" if total_score >= 80 else ("MEDIUM_FIT" if is_qualified else "LOW_FIT")

    return {
        "total_score": total_score,
        "min_threshold": min_qualify_score,
        "recommended_status": "QUALIFIED" if is_qualified else "DISQUALIFIED",
        "fit_tier": fit_tier,
        "disqualification_reasons": disq_reasons,
        "criteria": criteria_breakdown,
        "evaluated_at": now.isoformat(),
        "score_nature": "CONFIGURABLE_RUBRIC_ESTIMATE_NOT_VERIFIED_FACT",
        "disclaimer": (
            f"Transparent rubric estimate for {company} based on currently recorded sources; "
            "scores guide human review and are not guarantees of buyer intent or budget."
        ),
    }


def _find_duplicate_prospect(
    db: Session,
    *,
    normalized_domain: str,
    normalized_company: str,
    org_id: str | None,
) -> tuple[P2ProspectDossierRecord | None, LeadRecordRow | None]:
    dossier = (
        db.query(P2ProspectDossierRecord)
        .filter(
            (P2ProspectDossierRecord.normalized_domain == normalized_domain)
            | (P2ProspectDossierRecord.normalized_company_key == normalized_company)
        )
        .first()
    )
    if dossier:
        lead = db.get(LeadRecordRow, dossier.lead_id)
        return dossier, lead

    lead_query = db.query(LeadRecordRow).filter(LeadRecordRow.domain == normalized_domain)
    if org_id:
        lead_query = lead_query.filter(LeadRecordRow.org_id == org_id)
    lead = lead_query.first()
    if lead:
        return None, lead

    all_dossiers = db.query(P2ProspectDossierRecord).all()
    for d in all_dossiers:
        if d.normalized_company_key == normalized_company and normalized_company:
            return d, db.get(LeadRecordRow, d.lead_id)
    return None, None


def ingest_real_prospect(
    db: Session,
    *,
    company: str,
    website: str,
    location: str,
    source_url: str,
    business_category: str = "Digital Marketing & SEO Agency",
    source_type: str = "manual_owner_curation",
    public_email: str | None = None,
    public_contact_verified: bool = False,
    contact_verification_method: str = "not_verified",
    actual_services: list[str] | None = None,
    target_customers: list[str] | None = None,
    visible_seo_content_activity: list[str] | None = None,
    publicly_verifiable_needs: list[str] | None = None,
    research_claims: list[dict[str, Any]] | None = None,
    inspect_live_website: bool = False,
    recommended_sku: str = "managed_seo_content_pilot",
    org_id: str | None = None,
    actor: str = "owner",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Ingest, deduplicate, research, and qualify one genuine prospect with strict evidence provenance."""
    clean_company = company.strip()
    if not clean_company:
        raise ValueError("Company name is required")
    if any(kw in clean_company.lower() for kw in COMPETITOR_COMPANY_KEYWORDS):
        raise ValueError(f"Prospect '{clean_company}' matches excluded competitor keywords")
    if not source_url or not source_url.strip().startswith(("http://", "https://")):
        raise ValueError("Valid source_url (http/https) is required for every real prospect claim")

    norm_domain = normalize_domain(website)
    norm_company = normalize_company_identity(clean_company)
    is_synth, synth_reason = is_synthetic_fixture_prospect(
        domain=norm_domain,
        website=website,
        source_url=source_url,
        source_type=source_type,
        email=public_email,
    )
    if is_synth:
        raise ValueError(synth_reason or "Synthetic fixtures cannot enter the P2 prospect pipeline")

    existing_dossier, existing_lead = _find_duplicate_prospect(
        db,
        normalized_domain=norm_domain,
        normalized_company=norm_company,
        org_id=org_id,
    )
    if existing_dossier or existing_lead:
        lead_id_existing = existing_lead.id if existing_lead else existing_dossier.lead_id
        return {
            "status": "DUPLICATE_SKIPPED",
            "deduplicated": True,
            "matched_on": "domain_or_normalized_company",
            "lead_id": lead_id_existing,
            "dossier_id": existing_dossier.id if existing_dossier else None,
            "domain": norm_domain,
            "normalized_company_key": norm_company,
        }

    collected_at = datetime.now(UTC)
    corr_id = correlation_id or str(uuid.uuid4())
    clean_website = website.strip()
    if not clean_website.startswith(("http://", "https://")):
        clean_website = f"https://{norm_domain}"

    scraped_meta: dict[str, Any] = {}
    if inspect_live_website:
        scraped_meta = fetch_and_enrich_website(clean_website, timeout=4.0)

    services = [s.strip() for s in (actual_services or []) if s and s.strip()]
    if not services and scraped_meta.get("title"):
        services.append(f"Declared web presence title: {scraped_meta['title'][:120]}")

    customers = [c.strip() for c in (target_customers or []) if c and c.strip()]
    activity = [a.strip() for a in (visible_seo_content_activity or []) if a and a.strip()]
    for h in scraped_meta.get("headings", [])[:3]:
        activity.append(f"Observed page heading: {h}")

    needs = [n.strip() for n in (publicly_verifiable_needs or []) if n and n.strip()]

    contacts: list[dict[str, Any]] = []
    if public_email and "@" in public_email:
        clean_mail = public_email.strip().lower()
        is_generic_synthetic = clean_mail == f"contact@{norm_domain}"
        contacts.append(
            {
                "channel": "email",
                "value": clean_mail,
                "verified": bool(public_contact_verified and not is_generic_synthetic),
                "verification_method": (
                    contact_verification_method
                    if public_contact_verified and not is_generic_synthetic
                    else "unverified_or_generic_mailbox"
                ),
                "source_url": source_url.strip(),
            }
        )
    for ext_email in scraped_meta.get("emails", [])[:2]:
        clean_ext = str(ext_email).strip().lower()
        if "@" in clean_ext and not any(c["value"] == clean_ext for c in contacts):
            contacts.append(
                {
                    "channel": "email",
                    "value": clean_ext,
                    "verified": True,
                    "verification_method": "extracted_from_public_website",
                    "source_url": clean_website,
                }
            )

    claims: list[dict[str, Any]] = []
    for idx, rc in enumerate(research_claims or []):
        stmt = str(rc.get("statement", "")).strip()
        if not stmt:
            continue
        classification = str(rc.get("classification", "VERIFIED_FACT")).upper()
        if classification not in ("VERIFIED_FACT", "REASONABLE_INFERENCE", "UNVERIFIED_ASSUMPTION"):
            classification = "UNVERIFIED_ASSUMPTION"
        claims.append(
            {
                "claim_id": f"clm-{idx + 1}",
                "category": str(rc.get("category", "business_observation")),
                "statement": stmt,
                "classification": classification,
                "source_url": str(rc.get("source_url") or source_url).strip(),
                "observed_at": collected_at.isoformat(),
                "confidence_note": str(rc.get("confidence_note") or "Recorded from source evidence"),
            }
        )

    if not claims:
        for idx, s in enumerate(services):
            claims.append(
                {
                    "claim_id": f"clm-svc-{idx + 1}",
                    "category": "actual_services",
                    "statement": s,
                    "classification": "VERIFIED_FACT",
                    "source_url": source_url.strip(),
                    "observed_at": collected_at.isoformat(),
                    "confidence_note": f"Observed via {source_type}",
                }
            )
        for idx, n in enumerate(needs):
            claims.append(
                {
                    "claim_id": f"clm-need-{idx + 1}",
                    "category": "business_need",
                    "statement": n,
                    "classification": "REASONABLE_INFERENCE",
                    "source_url": source_url.strip(),
                    "observed_at": collected_at.isoformat(),
                    "confidence_note": "Inferred operational need tied to public positioning; verify in discovery.",
                }
            )

    agency_profile = {
        "actual_services": services,
        "target_customers": customers,
        "visible_seo_content_activity": activity,
        "publicly_verifiable_needs": needs,
    }

    qual = evaluate_qualification_score(
        company=clean_company,
        business_category=business_category,
        location=location,
        website=clean_website,
        source_url=source_url.strip(),
        collected_at=collected_at,
        agency_profile=agency_profile,
        public_contacts=contacts,
        research_claims=claims,
    )

    sku = recommended_sku if get_package(recommended_sku) else "managed_seo_content_pilot"
    pkg = CATALOG[sku]
    primary_email = contacts[0]["value"] if contacts else None

    task_id = str(uuid.uuid4())
    lead_id = str(uuid.uuid4())
    initial_status = qual["recommended_status"]

    task = TaskRecord(
        id=task_id,
        correlation_id=corr_id,
        objective=f"P2 Prospect Intelligence: {clean_company} ({norm_domain})",
        status="COMPLETED",
        result={"lead_id": lead_id, "domain": norm_domain, "qualification_score": qual["total_score"]},
    )
    lead_row = LeadRecordRow(
        id=lead_id,
        org_id=org_id,
        domain=norm_domain,
        task_id=task_id,
        company=clean_company,
        website=clean_website,
        industry=business_category,
        geography=location,
        observed_signals=services + activity + needs,
        sources=[
            {
                "url": source_url.strip(),
                "source_type": source_type,
                "collected_at": collected_at.isoformat(),
                "verified_contact_present": any(c.get("verified") for c in contacts),
            }
        ],
        product_match=sku,
        fit_score=round(float(qual["total_score"]) / 100.0, 4),
        confidence=0.85 if any(c["classification"] == "VERIFIED_FACT" for c in claims) else 0.55,
        public_contact_channel=primary_email,
        recommended_next_step=(
            "generate_account_intelligence_brief" if initial_status == "QUALIFIED" else "review_disqualification_or_enrich"
        ),
        do_not_contact=False,
        status=initial_status,
        last_checked=collected_at,
    )
    dossier = P2ProspectDossierRecord(
        lead_id=lead_id,
        org_id=org_id,
        normalized_company_key=norm_company,
        normalized_domain=norm_domain,
        business_category=business_category,
        location=location,
        source_url=source_url.strip(),
        source_type=source_type,
        collected_at=collected_at,
        is_synthetic=False,
        public_contacts_json=contacts,
        agency_profile_json=agency_profile,
        research_claims_json=claims,
        qualification_breakdown_json=qual,
        qualification_score=float(qual["total_score"]),
        research_brief_json={},
        pipeline_status=initial_status,
        next_action=(
            "Generate Account Intelligence Brief & prepare HITL outreach"
            if initial_status == "QUALIFIED"
            else "Verify ICP fit or enrich public contact details before outreach"
        ),
        recommended_sku=sku,
        commercial_value_inr=float(pkg.price_inr),
        currency="INR",
        payment_status="NOT_INITIATED",
        activation_status="NOT_ACTIVATED",
    )

    research_rec = ResearchRecord(
        lead_id=lead_id,
        task_id=task_id,
        idempotency_key=f"p2-ingest-{lead_id}",
        source_hash=str(abs(hash(source_url.strip()))),
        synthesis=f"Source-backed agency profile captured for {clean_company} ({location}).",
        analysis={"claims_count": len(claims), "qualification_score": qual["total_score"]},
        sources=[{"url": source_url.strip(), "collected_at": collected_at.isoformat()}],
    )

    db.add_all([task, lead_row, dossier, research_rec])
    db.add(
        AuditLog(
            task_id=task_id,
            correlation_id=corr_id,
            agent_id=actor,
            capability_name="p2_prospect_intelligence",
            action="ingest_real_prospect",
            input_payload={"company": clean_company, "domain": norm_domain, "source_url": source_url.strip()},
            output_payload={
                "lead_id": lead_id,
                "pipeline_status": initial_status,
                "qualification_score": qual["total_score"],
            },
            status="COMPLETED",
        )
    )
    record_execution_evidence(
        db,
        tenant_id=org_id or "__platform__",
        agent_id="prospect_discovery_agent",
        connector_id=source_type if source_type in ("serper_search", "google_places") else "project_api",
        execution_mode=resolve_execution_mode(None),
        input_payload={"company": clean_company, "website": clean_website, "source_url": source_url.strip()},
        output_payload={"lead_id": lead_id, "pipeline_status": initial_status, "score": qual["total_score"]},
        uses_external_provider=inspect_live_website,
        status="COMPLETED",
        output_origin="HUMAN_ASSISTED" if source_type == "manual_owner_curation" else "LOCAL_DETERMINISTIC",
    )
    db.commit()
    db.refresh(dossier)
    return serialize_prospect_dossier(dossier, lead_row)


def run_configured_prospect_discovery(
    db: Session,
    *,
    query: str = "digital marketing SEO agency India",
    limit: int = 5,
    execution_mode: str | None = None,
    actor: str = "owner",
    org_id: str | None = None,
) -> dict[str, Any]:
    """Discover real prospects strictly via configured live sources; fail honestly when blocked."""
    mode = resolve_execution_mode(execution_mode)
    if mode != "PRODUCTION":
        return {
            "status": "BLOCKED",
            "execution_mode": mode,
            "reason": (
                "Live web discovery requires PRODUCTION mode with verified Serper or Google Places connector. "
                "Synthetic discovery fixtures are disabled for the P2 real revenue pipeline; use curated real prospect intake."
            ),
            "discovered": [],
        }

    serper_gate = check_connector_execution_allowed(db, "serper_search", execution_mode=mode, org_id=org_id)
    if not serper_gate["allowed"]:
        return {
            "status": "BLOCKED",
            "execution_mode": mode,
            "reason": serper_gate.get("reason") or "serper_search connector is not LIVE_VERIFIED",
            "discovered": [],
        }

    from app.agents.smb_search_source import _search_serper_live

    api_results = _search_serper_live(query, limit=limit)
    ingested: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for item in api_results:
        try:
            res = ingest_real_prospect(
                db,
                company=str(item.get("company") or item.get("domain") or "Unknown Agency"),
                website=str(item.get("website") or ""),
                location=str(item.get("geography") or "India"),
                source_url=str(item.get("website") or ""),
                source_type="serper_search",
                public_email=item.get("public_contact_channel"),
                public_contact_verified=bool(item.get("is_contact_verified", False)),
                actual_services=list(item.get("signals") or []),
                inspect_live_website=True,
                org_id=org_id,
                actor=actor,
            )
            ingested.append(res)
        except Exception as exc:
            rejected.append({"domain": str(item.get("domain", "")), "reason": str(exc)})

    return {
        "status": "COMPLETED",
        "execution_mode": mode,
        "discovered_count": len(ingested),
        "discovered": ingested,
        "rejected": rejected,
    }


def generate_account_intelligence_brief(
    db: Session,
    *,
    lead_id: str,
    execution_mode: str | None = None,
    actor: str = "account_intelligence_agent",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Generate an account-specific research brief strictly separating Verified Facts, Inferences, & Assumptions."""
    lead = db.get(LeadRecordRow, lead_id)
    dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=lead_id).first()
    if not lead or not dossier:
        raise ValueError(f"P2 prospect dossier not found for lead '{lead_id}'")
    if lead.do_not_contact or dossier.pipeline_status == "DO_NOT_CONTACT":
        raise ValueError("Cannot generate research brief for DO_NOT_CONTACT prospect")

    mode = resolve_execution_mode(execution_mode)
    offer = verify_pilot_offer_contract(dossier.recommended_sku)
    profile = dossier.agency_profile_json or {}
    claims = dossier.research_claims_json or []

    verified_facts: list[dict[str, Any]] = []
    reasonable_inferences: list[dict[str, Any]] = []
    unverified_assumptions: list[dict[str, Any]] = []

    for clm in claims:
        entry = {
            "statement": clm.get("statement"),
            "source_url": clm.get("source_url") or dossier.source_url,
            "observed_at": clm.get("observed_at") or (dossier.collected_at.isoformat() if dossier.collected_at else None),
        }
        kind = str(clm.get("classification", "UNVERIFIED_ASSUMPTION")).upper()
        if kind == "VERIFIED_FACT":
            verified_facts.append(entry)
        elif kind == "REASONABLE_INFERENCE":
            reasonable_inferences.append(entry)
        else:
            unverified_assumptions.append(entry)

    # Ensure explicit baseline verified fact from collection record
    if not verified_facts:
        verified_facts.append(
            {
                "statement": (
                    f"{lead.company} operates {lead.website} in {dossier.location} under category "
                    f"'{dossier.business_category}'."
                ),
                "source_url": dossier.source_url,
                "observed_at": dossier.collected_at.isoformat() if dossier.collected_at else None,
            }
        )

    # Always state what remains unverified so assumptions are never disguised as facts
    if not any(c.get("verified") for c in (dossier.public_contacts_json or [])):
        unverified_assumptions.append(
            {
                "statement": "Decision-maker direct inbox and preferred buying authority are not yet confirmed.",
                "source_url": dossier.source_url,
                "verification_needed": "Confirm active buyer email and owner/founder role before proposal commitment.",
            }
        )
    unverified_assumptions.append(
        {
            "statement": (
                "Whether the agency currently faces internal content delivery capacity bottlenecks or uses external "
                "freelancers is not publicly disclosed."
            ),
            "source_url": dossier.source_url,
            "verification_needed": "Validate during 10-minute discovery call.",
        }
    )

    services = profile.get("actual_services") or []
    needs = profile.get("publicly_verifiable_needs") or []
    if not reasonable_inferences and services:
        reasonable_inferences.append(
            {
                "statement": (
                    f"Because {lead.company} lists services including {', '.join(services[:3])}, a repeatable "
                    f"14-day pilot for structured SEO/GEO audits and WordPress draft delivery could reduce manual turnaround."
                ),
                "source_url": dossier.source_url,
            }
        )

    deterministic_overview = (
        f"{lead.company} ({dossier.normalized_domain}) is based in {dossier.location} focusing on "
        f"{dossier.business_category}. Observed public offerings: "
        f"{', '.join(services[:4]) if services else 'Requires discovery confirmation'}."
    )
    fallback_used = True
    llm_summary = deterministic_overview
    if mode == "PRODUCTION" and has_gemini_api_key() and os.getenv("ALLOW_LIVE_IN_TEST", "") != "0":
        prompt = (
            f"Write a concise 3-sentence factual account overview for Indian agency {lead.company} ({lead.website}) "
            f"strictly from these verified observations only: {verified_facts}. Do not invent metrics or claims."
        )
        generated = llm_generate(prompt, fallback_text=deterministic_overview)
        if generated and generated != deterministic_overview:
            llm_summary = generated
            fallback_used = False

    brief: dict[str, Any] = {
        "lead_id": lead_id,
        "company": lead.company,
        "domain": dossier.normalized_domain,
        "company_overview": llm_summary,
        "relevant_business_observations": [f.get("statement") for f in verified_facts],
        "evidence_backed_opportunity": (
            "; ".join(needs[:3])
            if needs
            else "Potential operational leverage via standardized technical SEO/GEO audits, keyword clustering, and review-gated content production."
        ),
        "potential_service_recommendation": {
            "sku_key": offer["sku_key"],
            "name": offer["name"],
            "price_inr": offer["price_inr"],
            "price_usd": offer["price_usd"],
            "billing_type": offer["billing_type"],
            "scope_summary": offer["scope_notes"],
            "constraints": offer["non_guarantees"],
        },
        "suggested_discovery_questions": [
            f"How does {lead.company} currently handle recurring technical SEO audits and client content brief creation across accounts?",
            "Which part of your SEO/content workflow creates the biggest bottleneck between strategy sign-off and CMS draft delivery?",
            "If you tested a bounded 14-day pilot (1 audit, 1 keyword cluster, 2 human-reviewed articles on WordPress/Markdown), what criteria would make it worthwhile?",
        ],
        "suggested_first_contact_approach": (
            f"Short, low-friction founder note referencing verified service positioning from {dossier.source_url}, "
            "offering a factual walk-through of the ₹4,999 14-day Managed SEO & Content Pilot without exaggerated claims or false urgency."
        ),
        "verified_facts": verified_facts,
        "reasonable_inferences": reasonable_inferences,
        "unverified_assumptions": unverified_assumptions,
        "execution_mode": mode,
        "fallback_used": fallback_used,
        "output_origin": "LOCAL_DETERMINISTIC" if fallback_used else "LIVE_PROVIDER_VERIFIED",
        "generated_at": datetime.now(UTC).isoformat(),
    }

    dossier.research_brief_json = brief
    if dossier.pipeline_status == "NEW":
        dossier.pipeline_status = "RESEARCHING"
    dossier.updated_at = datetime.now(UTC)
    db.add(dossier)

    corr_id = correlation_id or str(uuid.uuid4())
    record_execution_evidence(
        db,
        tenant_id=dossier.org_id or "__platform__",
        agent_id="account_intelligence_agent",
        connector_id="gemini_api" if not fallback_used else "project_api",
        execution_mode=mode,
        input_payload={"lead_id": lead_id, "claims_count": len(claims)},
        output_payload={"verified_facts": len(verified_facts), "inferences": len(reasonable_inferences)},
        fallback_used=fallback_used,
        uses_external_provider=not fallback_used,
        status="COMPLETED",
        output_origin="LOCAL_DETERMINISTIC" if fallback_used else "LIVE_PROVIDER_VERIFIED",
    )
    db.add(
        AuditLog(
            task_id=lead.task_id,
            correlation_id=corr_id,
            agent_id=actor,
            capability_name="account_intelligence_brief",
            action="generate_brief",
            input_payload={"lead_id": lead_id},
            output_payload={"verified_facts_count": len(verified_facts), "fallback_used": fallback_used},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(dossier)
    return brief


def serialize_prospect_dossier(
    dossier: P2ProspectDossierRecord,
    lead: LeadRecordRow | None = None,
) -> dict[str, Any]:
    """Serialize P2 Prospect Dossier + Lead view."""
    return {
        "dossier_id": dossier.id,
        "lead_id": dossier.lead_id,
        "org_id": dossier.org_id,
        "company": lead.company if lead else dossier.normalized_domain,
        "website": lead.website if lead else f"https://{dossier.normalized_domain}",
        "domain": dossier.normalized_domain,
        "normalized_company_key": dossier.normalized_company_key,
        "business_category": dossier.business_category,
        "location": dossier.location,
        "source_url": dossier.source_url,
        "source_type": dossier.source_type,
        "collected_at": dossier.collected_at.isoformat() if dossier.collected_at else None,
        "is_synthetic": dossier.is_synthetic,
        "do_not_contact": bool(lead.do_not_contact) if lead else False,
        "public_contacts": dossier.public_contacts_json or [],
        "agency_profile": dossier.agency_profile_json or {},
        "research_claims": dossier.research_claims_json or [],
        "qualification_score": dossier.qualification_score,
        "qualification_breakdown": dossier.qualification_breakdown_json or {},
        "research_brief": dossier.research_brief_json or {},
        "pipeline_status": dossier.pipeline_status,
        "next_action": dossier.next_action,
        "follow_up_at": dossier.follow_up_at.isoformat() if dossier.follow_up_at else None,
        "discovery_notes": dossier.discovery_notes,
        "response_history": dossier.response_history_json or [],
        "recommended_sku": dossier.recommended_sku,
        "commercial_value_inr": dossier.commercial_value_inr,
        "currency": dossier.currency,
        "payment_status": dossier.payment_status,
        "activation_status": dossier.activation_status,
        "activated_org_id": dossier.activated_org_id,
        "owner_notes": dossier.owner_notes,
        "created_at": dossier.created_at.isoformat() if dossier.created_at else None,
        "updated_at": dossier.updated_at.isoformat() if dossier.updated_at else None,
    }
