"""P4 Repeatable Growth & GTM Engine.

Provides evidence-grounded ICP management, provenance-verified market & competitor
intelligence, claim-checked multi-channel campaigns gated by Owner HITL approval,
and honest funnel analytics separating ACTUAL verified pipeline from SANDBOX runs.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import (
    ApprovalRequest,
    P4GrowthCampaignRecord,
    P4IcpProfileRecord,
    P4MarketIntelRecord,
    P4PipelineDealRecord,
    TaskRecord,
)
from app.security.trust_chain import seal_task_to_block
from app.services.execution_guard import (
    ExecutionBlockedError,
    is_external_side_effect_blocked,
    resolve_execution_mode,
    validate_external_url,
)
from app.services.growth_engine import generate_and_stage_blog, generate_omnichannel_social_campaign
from app.services.p2_outreach_pipeline import validate_outreach_integrity

INTEL_TYPES = ("MARKET_TREND", "COMPETITOR", "KEYWORD_GAP", "WIN_LOSS")
CONFIDENCE_LEVELS = ("VERIFIED_SOURCE", "OBSERVATION", "UNVERIFIED_HYPOTHESIS")
PIPELINE_STAGES = (
    "DISCOVERED",
    "QUALIFIED",
    "DISCOVERY_CALL",
    "PROPOSAL_SENT",
    "NEGOTIATION",
    "WON",
    "LOST",
)
ALLOWED_STAGE_TRANSITIONS: dict[str, set[str]] = {
    "DISCOVERED": {"QUALIFIED", "DISCOVERY_CALL", "LOST"},
    "QUALIFIED": {"DISCOVERY_CALL", "PROPOSAL_SENT", "LOST"},
    "DISCOVERY_CALL": {"PROPOSAL_SENT", "NEGOTIATION", "LOST"},
    "PROPOSAL_SENT": {"NEGOTIATION", "WON", "LOST"},
    "NEGOTIATION": {"PROPOSAL_SENT", "WON", "LOST"},
    "WON": set(),
    "LOST": {"QUALIFIED"},
}
LOST_REASONS = (
    "pricing",
    "timing",
    "competitor",
    "no_need",
    "unresponsive",
    "technical_fit",
    "other",
)

_EXTRA_UNVERIFIED_CLAIM_PATTERNS = (
    (re.compile(r"\bguaranteed\s+inclusion\b", re.IGNORECASE), "unverified AI citation guarantee"),
    (re.compile(r"\b100%\s+refund\b", re.IGNORECASE), "unauthorized 100% refund promise"),
    (re.compile(r"\b\+?\d{3,}%\b"), "unverified extreme percentage uplift claim"),
    (re.compile(r"\b(8x|10x)\s+(?:roi|faster|headcount|multiplier)\b", re.IGNORECASE), "unverified multiplier claim"),
    (re.compile(r"\b0\s+proxy\s+attendance\b", re.IGNORECASE), "absolute zero-fraud claim"),
    (re.compile(r"\bzero\s+customer\s+inquiry\s+drop-?off\b", re.IGNORECASE), "absolute zero drop-off guarantee"),
    (re.compile(r"\blive\s+in\s+under\s+5\s+minutes\b", re.IGNORECASE), "unverified setup SLA promise"),
)


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for v in value.values():
            out.extend(_flatten_strings(v))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_flatten_strings(item))
        return out
    return []


def check_gtm_copy_safety(payload: Any, *, subject: str = "GTM Campaign Asset") -> dict[str, Any]:
    """Validate campaign copy and collateral against exaggerated/unverified claims."""
    combined = "\n".join(_flatten_strings(payload))
    issues = list(validate_outreach_integrity(subject=subject, body_text=combined))
    for pattern, label in _EXTRA_UNVERIFIED_CLAIM_PATTERNS:
        if pattern.search(combined):
            issues.append(f"Rejected claim ({label})")
    deduped = list(dict.fromkeys(issues))
    return {"safe": len(deduped) == 0, "issues": deduped, "checked_chars": len(combined)}


def _serialize_icp(rec: P4IcpProfileRecord) -> dict[str, Any]:
    return {
        "icp_id": rec.id,
        "org_id": rec.org_id,
        "name": rec.name,
        "industry": rec.industry,
        "geography": rec.geography,
        "company_size_range": rec.company_size_range,
        "buyer_personas": list(rec.buyer_personas_json or []),
        "pain_points": list(rec.pain_points_json or []),
        "value_propositions": list(rec.value_propositions_json or []),
        "disqualifiers": list(rec.disqualifiers_json or []),
        "status": rec.status,
        "created_by": rec.created_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def create_icp_profile(
    db: Session,
    *,
    org_id: str | None,
    name: str,
    industry: str,
    geography: str = "India",
    company_size_range: str = "10-200",
    buyer_personas: list[str] | None = None,
    pain_points: list[str] | None = None,
    value_propositions: list[str] | None = None,
    disqualifiers: list[str] | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Create a tenant-scoped Ideal Customer Profile (ICP) with claim-safety validation."""
    safety = check_gtm_copy_safety(value_propositions or [], subject=name)
    if not safety["safe"]:
        raise ValueError(f"ICP value propositions failed safety gate: {'; '.join(safety['issues'])}")

    now = datetime.now(UTC)
    rec = P4IcpProfileRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=name.strip(),
        industry=industry.strip(),
        geography=geography.strip(),
        company_size_range=company_size_range.strip(),
        buyer_personas_json=[x.strip() for x in (buyer_personas or []) if x.strip()],
        pain_points_json=[x.strip() for x in (pain_points or []) if x.strip()],
        value_propositions_json=[x.strip() for x in (value_propositions or []) if x.strip()],
        disqualifiers_json=[x.strip() for x in (disqualifiers or []) if x.strip()],
        status="ACTIVE",
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_icp(rec)


def list_icp_profiles(db: Session, *, org_id: str | None = None) -> list[dict[str, Any]]:
    """List ICP profiles scoped to org_id when provided."""
    q = db.query(P4IcpProfileRecord)
    if org_id is not None:
        q = q.filter(P4IcpProfileRecord.org_id == org_id)
    rows = q.order_by(P4IcpProfileRecord.created_at.desc()).all()
    return [_serialize_icp(r) for r in rows]


def score_prospect_against_icp(
    db: Session,
    *,
    icp_id: str,
    org_id: str | None,
    company_name: str,
    industry: str,
    geography: str,
    signals: list[str] | None = None,
) -> dict[str, Any]:
    """Score a prospective SME cleanly against a stored ICP definition."""
    icp = db.get(P4IcpProfileRecord, icp_id)
    if not icp or (org_id is not None and icp.org_id != org_id):
        raise ValueError(f"ICP profile '{icp_id}' not found")

    ind_match = icp.industry.lower() in industry.lower() or industry.lower() in icp.industry.lower()
    geo_match = icp.geography.lower() in geography.lower() or geography.lower() in icp.geography.lower()
    sig_text = " ".join(signals or []).lower()
    pain_hits = [p for p in (icp.pain_points_json or []) if any(tok in sig_text for tok in p.lower().split()[:2])]
    disq_hits = [d for d in (icp.disqualifiers_json or []) if d.lower() in sig_text or d.lower() in industry.lower()]

    score = 0.0
    if not disq_hits:
        score += 0.40 if ind_match else 0.10
        score += 0.25 if geo_match else 0.05
        if icp.pain_points_json:
            score += 0.35 * min(1.0, len(pain_hits) / max(1, min(len(icp.pain_points_json), 2)))
        else:
            score += 0.20

    score = round(min(1.0, max(0.0, score)), 2)
    return {
        "icp_id": icp.id,
        "company_name": company_name,
        "fit_score": score,
        "qualified": score >= 0.65 and not disq_hits,
        "criteria": {
            "industry_match": ind_match,
            "geography_match": geo_match,
            "pain_point_hits": pain_hits,
            "disqualifier_hits": disq_hits,
        },
    }


def _serialize_intel(rec: P4MarketIntelRecord) -> dict[str, Any]:
    return {
        "intel_id": rec.id,
        "org_id": rec.org_id,
        "icp_id": rec.icp_id,
        "intel_type": rec.intel_type,
        "subject_name": rec.subject_name,
        "summary": rec.summary,
        "source_url": rec.source_url,
        "source_type": rec.source_type,
        "collected_at": rec.collected_at.isoformat() if rec.collected_at else None,
        "evidence_ref": rec.evidence_ref,
        "confidence_level": rec.confidence_level,
        "verified_facts": list(rec.verified_facts_json or []),
        "inferences": list(rec.inferences_json or []),
        "created_by": rec.created_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def record_market_intel(
    db: Session,
    *,
    org_id: str | None,
    icp_id: str | None = None,
    intel_type: str,
    subject_name: str,
    summary: str,
    source_url: str | None = None,
    source_type: str = "public_web",
    evidence_ref: str | None = None,
    collected_at: datetime | None = None,
    confidence_level: str = "OBSERVATION",
    verified_facts: list[str] | None = None,
    inferences: list[str] | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Store provenance-verified market, competitor, or keyword intelligence."""
    clean_type = intel_type.strip().upper()
    clean_conf = confidence_level.strip().upper()
    if clean_type not in INTEL_TYPES:
        raise ValueError(f"Unsupported intel_type '{intel_type}'; allowed: {INTEL_TYPES}")
    if clean_conf not in CONFIDENCE_LEVELS:
        raise ValueError(f"Unsupported confidence_level '{confidence_level}'; allowed: {CONFIDENCE_LEVELS}")

    if source_url:
        try:
            validate_external_url(source_url.strip())
        except ExecutionBlockedError as exc:
            raise ValueError(exc.reason) from exc

    if clean_conf == "VERIFIED_SOURCE" and (not source_url or not evidence_ref):
        raise ValueError("VERIFIED_SOURCE intelligence requires both source_url and evidence_ref provenance")

    if icp_id:
        icp = db.get(P4IcpProfileRecord, icp_id)
        if not icp or (org_id is not None and icp.org_id != org_id):
            raise ValueError(f"Referenced icp_id '{icp_id}' not found")

    now = datetime.now(UTC)
    rec = P4MarketIntelRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        icp_id=icp_id,
        intel_type=clean_type,
        subject_name=subject_name.strip(),
        summary=summary.strip(),
        source_url=source_url.strip() if source_url else None,
        source_type=source_type.strip(),
        collected_at=collected_at or (now if source_url else None),
        evidence_ref=evidence_ref.strip() if evidence_ref else None,
        confidence_level=clean_conf,
        verified_facts_json=list(verified_facts or []),
        inferences_json=list(inferences or []),
        metadata_json={},
        created_by=actor,
        created_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_intel(rec)


def list_market_intel(
    db: Session,
    *,
    org_id: str | None = None,
    intel_type: str | None = None,
) -> list[dict[str, Any]]:
    """List recorded market & competitor intelligence entries."""
    q = db.query(P4MarketIntelRecord)
    if org_id is not None:
        q = q.filter(P4MarketIntelRecord.org_id == org_id)
    if intel_type:
        q = q.filter(P4MarketIntelRecord.intel_type == intel_type.strip().upper())
    rows = q.order_by(P4MarketIntelRecord.created_at.desc()).all()
    return [_serialize_intel(r) for r in rows]


def _serialize_campaign(rec: P4GrowthCampaignRecord) -> dict[str, Any]:
    return {
        "campaign_id": rec.id,
        "org_id": rec.org_id,
        "icp_id": rec.icp_id,
        "name": rec.name,
        "objective": rec.objective,
        "channels": list(rec.channels_json or []),
        "status": rec.status,
        "execution_mode": rec.execution_mode,
        "approval_id": rec.approval_id,
        "variants": dict(rec.variants_json or {}),
        "budget_cap_inr": float(rec.budget_cap_inr or 0.0),
        "spend_inr": float(rec.spend_inr or 0.0),
        "safety_report": dict(rec.safety_report_json or {}),
        "created_by": rec.created_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def create_growth_campaign(
    db: Session,
    *,
    org_id: str | None,
    name: str,
    objective: str,
    product_name: str,
    target_audience: str,
    keywords: list[str],
    channels: list[str] | None = None,
    icp_id: str | None = None,
    budget_cap_inr: float = 0.0,
    custom_copy_overrides: dict[str, Any] | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Generate a claim-checked multi-channel GTM campaign and stage HITL approval."""
    if icp_id:
        icp = db.get(P4IcpProfileRecord, icp_id)
        if not icp or (org_id is not None and icp.org_id != org_id):
            raise ValueError(f"ICP profile '{icp_id}' not found")

    clean_channels = [c.strip().lower() for c in (channels or ["seo", "social", "email"]) if c.strip()]
    social = generate_omnichannel_social_campaign(
        product_name=product_name,
        target_audience=target_audience,
        keywords=keywords,
    )
    seo_draft = generate_and_stage_blog(
        product_name=product_name,
        target_audience=target_audience,
        keywords=keywords,
    )
    variants: dict[str, Any] = {
        "social": social,
        "seo_article": {
            "title": seo_draft["title"],
            "slug": seo_draft["slug"],
            "meta_description": seo_draft["meta_description"],
            "ai_editorial_synthesis": seo_draft["ai_editorial_synthesis"],
        },
        "email_template": {
            "subject": f"{product_name}: Structured AI workflow evaluation for {target_audience}",
            "body": (
                f"Hello,\n\nWe noticed your team evaluates {keywords[0] if keywords else product_name}. "
                f"AskforWrite AI Company OS enables sandbox testing with full 18-field execution evidence before "
                f"any production launch.\n\nReply if you would like a scoped walkthrough."
            ),
        },
    }
    if custom_copy_overrides:
        variants["custom_overrides"] = custom_copy_overrides

    safety = check_gtm_copy_safety(variants, subject=name)
    if not safety["safe"]:
        raise ValueError(f"Campaign copy rejected by integrity filter: {'; '.join(safety['issues'])}")

    now = datetime.now(UTC)
    campaign_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    db.add(
        TaskRecord(
            id=task_id,
            correlation_id=str(uuid.uuid4()),
            objective=f"P4 GTM Campaign HITL Review: {name}",
            status="PENDING_APPROVAL",
        )
    )
    db.flush()

    req_id = str(uuid.uuid4())
    req_hash = hashlib.sha256(f"{campaign_id}:{name}:{org_id}:{now.isoformat()}".encode("utf-8")).hexdigest()
    appr = ApprovalRequest(
        id=req_id,
        task_id=task_id,
        action="p4_gtm_campaign_launch",
        detail={
            "campaign_id": campaign_id,
            "org_id": org_id,
            "name": name,
            "channels": clean_channels,
            "budget_cap_inr": budget_cap_inr,
        },
        idempotency_key=f"p4-camp:{campaign_id}:{req_id[:8]}",
        request_hash=req_hash,
        requested_by=actor,
        status="PENDING",
        decision_note=f"HITL review required before campaign launch: {name}",
    )
    db.add(appr)
    db.flush()

    rec = P4GrowthCampaignRecord(
        id=campaign_id,
        org_id=org_id,
        icp_id=icp_id,
        name=name.strip(),
        objective=objective.strip(),
        channels_json=clean_channels,
        status="PENDING_APPROVAL",
        execution_mode="SIMULATION",
        approval_id=appr.id,
        variants_json=variants,
        budget_cap_inr=max(0.0, float(budget_cap_inr)),
        spend_inr=0.0,
        safety_report_json=safety,
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()

    seal_task_to_block(
        db=db,
        task_id=task_id,
        capability_name="p4_growth_gtm",
        action="stage_gtm_campaign",
        payload={"campaign_id": campaign_id, "approval_id": appr.id, "channels": clean_channels},
        sealed_by=actor,
    )
    db.refresh(rec)
    return _serialize_campaign(rec)


def execute_approved_campaign(
    db: Session,
    *,
    campaign_id: str,
    org_id: str | None,
    execution_mode: str = "SIMULATION",
    actor: str = "system",
) -> dict[str, Any]:
    """Execute a staged GTM campaign only if its Owner HITL approval is APPROVED."""
    rec = db.get(P4GrowthCampaignRecord, campaign_id)
    if not rec or (org_id is not None and rec.org_id != org_id):
        raise ValueError(f"Campaign '{campaign_id}' not found")

    if not rec.approval_id:
        raise PermissionError("Campaign lacks a HITL ApprovalRequest record")
    appr = db.get(ApprovalRequest, rec.approval_id)
    if not appr or appr.status != "APPROVED":
        current = appr.status if appr else "MISSING"
        raise PermissionError(f"Campaign cannot execute until HITL approval is APPROVED (current={current})")

    raw_mode = (execution_mode or "").strip().upper()
    normalized_mode = "PRODUCTION" if raw_mode == "LIVE" else raw_mode
    if raw_mode and normalized_mode not in ("SIMULATION", "SANDBOX", "PRODUCTION"):
        raise ValueError(f"Unsupported execution_mode '{execution_mode}'")
    clean_mode = resolve_execution_mode(normalized_mode or None)
    if clean_mode == "PRODUCTION" and is_external_side_effect_blocked():
        raise PermissionError("PRODUCTION/LIVE campaign dispatch blocked: ENABLE_EXTERNAL_SIDE_EFFECTS is disabled or test guard active")

    safety = check_gtm_copy_safety(rec.variants_json, subject=rec.name)
    if not safety["safe"]:
        raise ValueError(f"Campaign safety check failed: {'; '.join(safety['issues'])}")

    rec.execution_mode = clean_mode
    rec.status = "ACTIVE_LIVE" if clean_mode == "PRODUCTION" else "EXECUTING_SANDBOX"
    rec.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(rec)
    return _serialize_campaign(rec)


def list_campaigns(db: Session, *, org_id: str | None = None) -> list[dict[str, Any]]:
    """List P4 growth campaigns scoped cleanly to org_id when given."""
    q = db.query(P4GrowthCampaignRecord)
    if org_id is not None:
        q = q.filter(P4GrowthCampaignRecord.org_id == org_id)
    return [_serialize_campaign(r) for r in q.order_by(P4GrowthCampaignRecord.created_at.desc()).all()]


def _serialize_deal(rec: P4PipelineDealRecord) -> dict[str, Any]:
    return {
        "deal_id": rec.id,
        "org_id": rec.org_id,
        "lead_id": rec.lead_id,
        "campaign_id": rec.campaign_id,
        "icp_id": rec.icp_id,
        "company_name": rec.company_name,
        "contact_email": rec.contact_email,
        "stage": rec.stage,
        "deal_value_inr": float(rec.deal_value_inr or 0.0),
        "currency": rec.currency,
        "attribution_source": rec.attribution_source,
        "evidence_status": rec.evidence_status,
        "lost_reason": rec.lost_reason,
        "next_action": rec.next_action,
        "owner_actor": rec.owner_actor,
        "stage_history": list(rec.stage_history_json or []),
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
        "closed_at": rec.closed_at.isoformat() if rec.closed_at else None,
    }


def create_pipeline_deal(
    db: Session,
    *,
    org_id: str | None,
    company_name: str,
    contact_email: str | None = None,
    lead_id: str | None = None,
    campaign_id: str | None = None,
    icp_id: str | None = None,
    deal_value_inr: float = 0.0,
    currency: str = "INR",
    attribution_source: str = "ORGANIC_INBOUND",
    evidence_status: str = "SANDBOX",
    next_action: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Create a GTM pipeline deal explicitly tagged with ACTUAL or SANDBOX evidence_status."""
    clean_origin = evidence_status.strip().upper()
    if clean_origin not in ("ACTUAL", "SANDBOX"):
        raise ValueError("evidence_status must be ACTUAL or SANDBOX")

    now = datetime.now(UTC)
    rec = P4PipelineDealRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        lead_id=lead_id,
        campaign_id=campaign_id,
        icp_id=icp_id,
        company_name=company_name.strip(),
        contact_email=contact_email.strip() if contact_email else None,
        stage="DISCOVERED",
        deal_value_inr=max(0.0, float(deal_value_inr)),
        currency=currency.strip().upper(),
        attribution_source=attribution_source.strip().upper(),
        evidence_status=clean_origin,
        lost_reason=None,
        next_action=next_action,
        owner_actor=actor,
        stage_history_json=[{"from": None, "to": "DISCOVERED", "actor": actor, "at": now.isoformat()}],
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_deal(rec)


def transition_pipeline_deal(
    db: Session,
    *,
    deal_id: str,
    org_id: str | None,
    target_stage: str,
    lost_reason: str | None = None,
    note: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Advance or close a GTM pipeline deal, enforcing lost_reason for LOST transitions."""
    rec = db.get(P4PipelineDealRecord, deal_id)
    if not rec or (org_id is not None and rec.org_id != org_id):
        raise ValueError(f"Pipeline deal '{deal_id}' not found")

    clean_stage = target_stage.strip().upper()
    if clean_stage not in PIPELINE_STAGES:
        raise ValueError(f"Unsupported pipeline stage '{target_stage}'; allowed: {PIPELINE_STAGES}")

    allowed = ALLOWED_STAGE_TRANSITIONS.get(rec.stage, set())
    if clean_stage != rec.stage and clean_stage not in allowed:
        raise ValueError(f"Invalid stage transition {rec.stage} -> {clean_stage}")

    if clean_stage == "LOST":
        clean_reason = (lost_reason or "").strip().lower()
        if clean_reason not in LOST_REASONS:
            raise ValueError(f"Transitioning to LOST requires lost_reason in {LOST_REASONS}")
        rec.lost_reason = clean_reason

    now = datetime.now(UTC)
    hist = list(rec.stage_history_json or [])
    hist.append(
        {
            "from": rec.stage,
            "to": clean_stage,
            "note": note,
            "lost_reason": rec.lost_reason,
            "actor": actor,
            "at": now.isoformat(),
        }
    )
    rec.stage = clean_stage
    rec.stage_history_json = hist
    flag_modified(rec, "stage_history_json")
    rec.updated_at = now
    if clean_stage in ("WON", "LOST"):
        rec.closed_at = now
    db.commit()
    db.refresh(rec)
    return _serialize_deal(rec)


def list_pipeline_deals(db: Session, *, org_id: str | None = None, evidence_status: str | None = None) -> list[dict[str, Any]]:
    """List pipeline deals filtered cleanly by org_id and optional ACTUAL/SANDBOX origin."""
    q = db.query(P4PipelineDealRecord)
    if org_id is not None:
        q = q.filter(P4PipelineDealRecord.org_id == org_id)
    if evidence_status:
        q = q.filter(P4PipelineDealRecord.evidence_status == evidence_status.strip().upper())
    return [_serialize_deal(r) for r in q.order_by(P4PipelineDealRecord.updated_at.desc()).all()]


def _summarize_deal_cohort(deals: list[P4PipelineDealRecord]) -> dict[str, Any]:
    stage_counts = {s: 0 for s in PIPELINE_STAGES}
    lost_reasons: dict[str, int] = {}
    attribution: dict[str, int] = {}
    won_value_inr = 0.0
    open_pipeline_inr = 0.0

    for d in deals:
        stage_counts[d.stage] = stage_counts.get(d.stage, 0) + 1
        attribution[d.attribution_source] = attribution.get(d.attribution_source, 0) + 1
        if d.stage == "WON":
            won_value_inr += float(d.deal_value_inr or 0.0)
        elif d.stage == "LOST":
            key = d.lost_reason or "unspecified"
            lost_reasons[key] = lost_reasons.get(key, 0) + 1
        else:
            open_pipeline_inr += float(d.deal_value_inr or 0.0)

    closed = stage_counts["WON"] + stage_counts["LOST"]
    win_rate_pct = round((stage_counts["WON"] / closed) * 100.0, 2) if closed > 0 else None
    return {
        "total_deals": len(deals),
        "stage_counts": stage_counts,
        "won_deals": stage_counts["WON"],
        "lost_deals": stage_counts["LOST"],
        "win_rate_pct": win_rate_pct,
        "won_value_inr": round(won_value_inr, 2),
        "open_pipeline_inr": round(open_pipeline_inr, 2),
        "lost_reason_breakdown": lost_reasons,
        "attribution_breakdown": attribution,
    }


def compute_gtm_funnel_analytics(db: Session, *, org_id: str | None = None) -> dict[str, Any]:
    """Compute honest GTM funnel metrics separating ACTUAL deals from SANDBOX runs."""
    q = db.query(P4PipelineDealRecord)
    if org_id is not None:
        q = q.filter(P4PipelineDealRecord.org_id == org_id)
    deals = q.all()

    actual_deals = [d for d in deals if d.evidence_status == "ACTUAL"]
    sandbox_deals = [d for d in deals if d.evidence_status != "ACTUAL"]

    camp_q = db.query(P4GrowthCampaignRecord)
    intel_q = db.query(P4MarketIntelRecord)
    icp_q = db.query(P4IcpProfileRecord)
    if org_id is not None:
        camp_q = camp_q.filter(P4GrowthCampaignRecord.org_id == org_id)
        intel_q = intel_q.filter(P4MarketIntelRecord.org_id == org_id)
        icp_q = icp_q.filter(P4IcpProfileRecord.org_id == org_id)

    return {
        "analytics_integrity": "SEPARATED_ACTUAL_VS_SANDBOX",
        "org_id": org_id,
        "icp_count": icp_q.count(),
        "intel_count": intel_q.count(),
        "campaign_count": camp_q.count(),
        "actual_verified": _summarize_deal_cohort(actual_deals),
        "sandbox_and_simulation": _summarize_deal_cohort(sandbox_deals),
        "honest_note": "ACTUAL metrics exclude SANDBOX/SIMULATION pipeline entries; win_rate_pct is null when closed=0.",
    }
