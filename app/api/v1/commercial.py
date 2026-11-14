"""P2 Commercial Acquisition & Revenue Engine API Router (/v1/commercial/*)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
    LeadRecordRow,
    P2CommercialProposalRecord,
    P2CustomerEngagementRecord,
    P2PaymentReconciliationRecord,
    P2ProspectDossierRecord,
)
from app.security.auth import APIPrincipal, require_manager, require_owner
from app.services.p2_customer_ops import (
    complete_engagement_delivery,
    execute_pilot_delivery,
    get_founder_control_centre,
    record_customer_feedback_and_renewal,
    seed_and_get_acceptance_checklist,
    serialize_engagement,
    submit_onboarding_inputs,
    update_acceptance_step,
)
from app.services.p2_outreach_pipeline import (
    dispatch_p2_outreach,
    list_unified_pipeline,
    log_prospect_response,
    prepare_p2_outreach,
    transition_pipeline_status,
)
from app.services.p2_prospect_intel import (
    DEFAULT_MIN_QUALIFICATION_SCORE,
    evaluate_qualification_score,
    generate_account_intelligence_brief,
    ingest_real_prospect,
    run_configured_prospect_discovery,
    serialize_prospect_dossier,
    verify_pilot_offer_contract,
)
from app.services.p2_proposal_settlement import (
    create_structured_proposal,
    initiate_proposal_checkout,
    retry_reconciliation_entry,
    serialize_p2_proposal,
    share_approved_proposal,
)

router = APIRouter(prefix="/v1/commercial", tags=["P2 Commercial Revenue Engine"])


# ── Pydantic Request Schemas ─────────────────────────────────────────────────


class ResearchClaimInput(BaseModel):
    category: str = Field(default="business_observation", max_length=80)
    statement: str = Field(min_length=3, max_length=1000)
    classification: Literal["VERIFIED_FACT", "REASONABLE_INFERENCE", "UNVERIFIED_ASSUMPTION"] = "VERIFIED_FACT"
    source_url: str | None = Field(default=None, max_length=2048)
    confidence_note: str | None = Field(default=None, max_length=300)


class ProspectIngestRequest(BaseModel):
    company: str = Field(min_length=2, max_length=250)
    website: str = Field(min_length=4, max_length=2048)
    location: str = Field(default="India", min_length=2, max_length=250)
    source_url: str = Field(min_length=8, max_length=2048)
    business_category: str = Field(default="Digital Marketing & SEO Agency", max_length=150)
    source_type: str = Field(default="manual_owner_curation", max_length=64)
    public_email: str | None = Field(default=None, max_length=250)
    public_contact_verified: bool = False
    contact_verification_method: str = Field(default="not_verified", max_length=100)
    actual_services: list[str] = Field(default_factory=list)
    target_customers: list[str] = Field(default_factory=list)
    visible_seo_content_activity: list[str] = Field(default_factory=list)
    publicly_verifiable_needs: list[str] = Field(default_factory=list)
    research_claims: list[ResearchClaimInput] = Field(default_factory=list)
    inspect_live_website: bool = False
    recommended_sku: str = Field(default="managed_seo_content_pilot", max_length=100)
    org_id: str | None = Field(default=None, max_length=64)


class ProspectDiscoverRequest(BaseModel):
    query: str = Field(default="digital marketing SEO agency India", min_length=3, max_length=200)
    limit: int = Field(default=5, ge=1, le=20)
    execution_mode: str | None = Field(default=None, max_length=32)


class RequalifyRequest(BaseModel):
    weights: dict[str, int] | None = None
    min_qualify_score: float = Field(default=DEFAULT_MIN_QUALIFICATION_SCORE, ge=0.0, le=100.0)


class BriefRequest(BaseModel):
    execution_mode: str | None = Field(default=None, max_length=32)


class P2OutreachPrepareRequest(BaseModel):
    lead_id: str = Field(min_length=1, max_length=64)
    recipient_email: str | None = Field(default=None, max_length=250)
    recipient_name: str | None = Field(default=None, max_length=150)
    channel: str = Field(default="email", max_length=40)
    subject_override: str | None = Field(default=None, max_length=300)
    body_override: str | None = Field(default=None, max_length=8000)
    custom_notes: str | None = Field(default=None, max_length=1000)
    allow_follow_up: bool = False
    idempotency_key: str | None = Field(default=None, max_length=150)


class PipelineTransitionRequest(BaseModel):
    target_status: str = Field(min_length=2, max_length=32)
    next_action: str | None = Field(default=None, max_length=300)
    follow_up_at: datetime | None = None
    discovery_notes: str | None = Field(default=None, max_length=5000)
    owner_notes: str | None = Field(default=None, max_length=5000)


class LogResponseRequest(BaseModel):
    summary: str = Field(min_length=2, max_length=4000)
    source: str = Field(default="email_reply", max_length=80)
    channel: str = Field(default="email", max_length=40)
    sentiment: Literal["interested", "objection", "question", "not_interested", "unsubscribe"] = "interested"
    next_action: str | None = Field(default=None, max_length=300)
    follow_up_at: datetime | None = None
    discovery_notes: str | None = Field(default=None, max_length=5000)


class StructuredProposalRequest(BaseModel):
    lead_id: str = Field(min_length=1, max_length=64)
    sku_key: str = Field(default="managed_seo_content_pilot", max_length=100)
    currency: Literal["INR", "USD"] = "INR"
    tax_rate_percent: float = Field(default=0.0, ge=0.0, le=28.0)
    custom_problem_statement: str | None = Field(default=None, max_length=2000)
    custom_scope_notes: str | None = Field(default=None, max_length=2000)


class ShareProposalRequest(BaseModel):
    channel: str = Field(default="email_and_portal_link", max_length=64)


class CheckoutFromProposalRequest(BaseModel):
    provider: Literal["afw_directpay", "razorpay", "paypal"] = "afw_directpay"
    customer_email: str | None = Field(default=None, max_length=250)
    customer_name: str | None = Field(default=None, max_length=150)
    preferred_rail: Literal["upi_direct", "web3_usdc", "bank_wire_direct"] = "upi_direct"


class OnboardingInputsRequest(BaseModel):
    target_domain: str = Field(min_length=3, max_length=250)
    cms_delivery_mode: Literal["wordpress_rest", "markdown_html_export", "google_doc_export"] = "markdown_html_export"
    priority_topics: list[str] = Field(min_length=1, max_length=10)
    target_geography: str = Field(default="India", max_length=120)
    brand_tone_notes: str | None = Field(default=None, max_length=1000)
    wordpress_site_url: str | None = Field(default=None, max_length=500)


class DeliveryRunRequest(BaseModel):
    execution_mode: str | None = Field(default=None, max_length=32)


class DeliveryCompleteRequest(BaseModel):
    delivery_channel_proof: str = Field(min_length=3, max_length=500)
    client_acceptance_note: str | None = Field(default=None, max_length=1000)


class FeedbackRenewalRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comments: str = Field(min_length=2, max_length=3000)
    improvements_requested: str | None = Field(default=None, max_length=2000)
    interested_in_renewal: bool = True


class AcceptanceStepUpdateRequest(BaseModel):
    verification_status: Literal["NOT_TESTED", "SANDBOX_VERIFIED", "LIVE_VERIFIED"]
    evidence_summary: str | None = Field(default=None, max_length=2000)
    evidence_ref: str | None = Field(default=None, max_length=500)


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/offer/{sku_key}")
def get_verified_offer_contract(
    sku_key: str = "managed_seo_content_pilot",
    _principal: APIPrincipal = Depends(require_manager),
) -> dict[str, Any]:
    """Verify catalog offer pricing, billing type, scope, entitlements, and non-guarantees."""
    try:
        return verify_pilot_offer_contract(sku_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/prospects/ingest")
def ingest_prospect_endpoint(
    payload: ProspectIngestRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Ingest, deduplicate, and qualify a genuine agency prospect with source provenance."""
    try:
        return ingest_real_prospect(
            db,
            company=payload.company,
            website=payload.website,
            location=payload.location,
            source_url=payload.source_url,
            business_category=payload.business_category,
            source_type=payload.source_type,
            public_email=payload.public_email,
            public_contact_verified=payload.public_contact_verified,
            contact_verification_method=payload.contact_verification_method,
            actual_services=payload.actual_services,
            target_customers=payload.target_customers,
            visible_seo_content_activity=payload.visible_seo_content_activity,
            publicly_verifiable_needs=payload.publicly_verifiable_needs,
            research_claims=[c.model_dump() for c in payload.research_claims],
            inspect_live_website=payload.inspect_live_website,
            recommended_sku=payload.recommended_sku,
            org_id=payload.org_id or principal.org_id,
            actor=principal.subject,
            correlation_id=x_correlation_id or str(uuid.uuid4()),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/prospects/discover")
def discover_prospects_endpoint(
    payload: ProspectDiscoverRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Run configured live web discovery cleanly; returns honest BLOCKED state if synthetic/unverified."""
    return run_configured_prospect_discovery(
        db,
        query=payload.query,
        limit=payload.limit,
        execution_mode=payload.execution_mode,
        actor=principal.subject,
        org_id=principal.org_id,
    )


@router.get("/prospects")
def list_prospects_endpoint(
    pipeline_status: str | None = None,
    include_synthetic: bool = False,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List P2 commercial prospects and qualification dossiers."""
    query = db.query(P2ProspectDossierRecord).order_by(P2ProspectDossierRecord.qualification_score.desc())
    if pipeline_status:
        query = query.filter(P2ProspectDossierRecord.pipeline_status == pipeline_status.strip().upper())
    if not include_synthetic:
        query = query.filter(P2ProspectDossierRecord.is_synthetic.is_(False))
    rows = query.all()
    items = [serialize_prospect_dossier(d, db.get(LeadRecordRow, d.lead_id)) for d in rows]
    return {"count": len(items), "prospects": items}


@router.post("/prospects/{lead_id}/requalify")
def requalify_prospect_endpoint(
    lead_id: str,
    payload: RequalifyRequest,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recompute transparent 6-criterion qualification breakdown with configurable criteria weights."""
    lead = db.get(LeadRecordRow, lead_id)
    dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=lead_id).first()
    if not lead or not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="P2 prospect dossier not found")

    qual = evaluate_qualification_score(
        company=lead.company,
        business_category=dossier.business_category,
        location=dossier.location,
        website=lead.website,
        source_url=dossier.source_url,
        collected_at=dossier.collected_at,
        agency_profile=dossier.agency_profile_json or {},
        public_contacts=dossier.public_contacts_json or [],
        research_claims=dossier.research_claims_json or [],
        weights=payload.weights,
        min_qualify_score=payload.min_qualify_score,
    )
    dossier.qualification_breakdown_json = qual
    dossier.qualification_score = float(qual["total_score"])
    if dossier.pipeline_status in ("NEW", "RESEARCHING", "QUALIFIED", "DISQUALIFIED"):
        dossier.pipeline_status = qual["recommended_status"]
        lead.status = qual["recommended_status"]
    lead.fit_score = round(dossier.qualification_score / 100.0, 4)
    db.add_all([dossier, lead])
    db.commit()
    db.refresh(dossier)
    return serialize_prospect_dossier(dossier, lead)


@router.post("/prospects/{lead_id}/brief")
def generate_brief_endpoint(
    lead_id: str,
    payload: BriefRequest | None = None,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate Account Intelligence Brief separating Verified Facts, Reasonable Inferences, & Assumptions."""
    try:
        return generate_account_intelligence_brief(
            db,
            lead_id=lead_id,
            execution_mode=payload.execution_mode if payload else None,
            actor=principal.subject,
            correlation_id=x_correlation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/outreach/prepare")
def prepare_outreach_endpoint(
    payload: P2OutreachPrepareRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Prepare claim-validated outreach gated by Owner HITL approval, suppression, and rate limits."""
    try:
        return prepare_p2_outreach(
            db,
            lead_id=payload.lead_id,
            recipient_email=payload.recipient_email,
            recipient_name=payload.recipient_name,
            channel=payload.channel,
            subject_override=payload.subject_override,
            body_override=payload.body_override,
            custom_notes=payload.custom_notes,
            allow_follow_up=payload.allow_follow_up,
            idempotency_key=payload.idempotency_key,
            actor=principal.subject,
            correlation_id=x_correlation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/outreach/{outreach_id}/dispatch")
def dispatch_outreach_p2_endpoint(
    outreach_id: str,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Owner-authorized outbound send keeping LIVE vs SIMULATED delivery strictly separated."""
    try:
        return dispatch_p2_outreach(
            db,
            outreach_id=outreach_id,
            dispatched_by=principal.subject,
            correlation_id=x_correlation_id,
        )
    except ValueError as exc:
        msg = str(exc)
        code = status.HTTP_403_FORBIDDEN if "approval" in msg.lower() else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(status_code=code, detail=msg) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/pipeline")
def get_pipeline_endpoint(
    pipeline_status: str | None = Query(default=None, alias="status"),
    include_synthetic: bool = False,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve unified 12-stage deal pipeline."""
    items = list_unified_pipeline(db, status_filter=pipeline_status, include_synthetic=include_synthetic)
    return {"count": len(items), "pipeline": items}


@router.post("/pipeline/{lead_id}/transition")
def transition_pipeline_endpoint(
    lead_id: str,
    payload: PipelineTransitionRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Audited pipeline stage transition across the 12 P2 deal statuses."""
    try:
        return transition_pipeline_status(
            db,
            lead_id=lead_id,
            target_status=payload.target_status,
            next_action=payload.next_action,
            follow_up_at=payload.follow_up_at,
            discovery_notes=payload.discovery_notes,
            owner_notes=payload.owner_notes,
            actor=principal.subject,
            correlation_id=x_correlation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/pipeline/{lead_id}/responses")
def log_response_endpoint(
    lead_id: str,
    payload: LogResponseRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Log prospect reply & discovery notes with source provenance."""
    try:
        return log_prospect_response(
            db,
            lead_id=lead_id,
            summary=payload.summary,
            source=payload.source,
            channel=payload.channel,
            sentiment=payload.sentiment,
            next_action=payload.next_action,
            follow_up_at=payload.follow_up_at,
            discovery_notes=payload.discovery_notes,
            actor=principal.subject,
            correlation_id=x_correlation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/proposals")
def create_proposal_endpoint(
    payload: StructuredProposalRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create catalog-verified multi-clause commercial proposal gated by Owner approval."""
    try:
        return create_structured_proposal(
            db,
            lead_id=payload.lead_id,
            sku_key=payload.sku_key,
            currency=payload.currency,
            tax_rate_percent=payload.tax_rate_percent,
            custom_problem_statement=payload.custom_problem_statement,
            custom_scope_notes=payload.custom_scope_notes,
            actor=principal.subject,
            correlation_id=x_correlation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/proposals")
def list_proposals_endpoint(
    lead_id: str | None = None,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List structured P2 commercial proposals."""
    q = db.query(P2CommercialProposalRecord).order_by(P2CommercialProposalRecord.created_at.desc())
    if lead_id:
        q = q.filter(P2CommercialProposalRecord.lead_id == lead_id)
    rows = q.all()
    return {"count": len(rows), "proposals": [serialize_p2_proposal(r) for r in rows]}


@router.post("/proposals/{proposal_id}/share")
def share_proposal_endpoint(
    proposal_id: str,
    payload: ShareProposalRequest | None = None,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Share Owner-approved proposal with prospect and attach verified checkout URL."""
    try:
        return share_approved_proposal(
            db,
            proposal_id=proposal_id,
            channel=payload.channel if payload else "email_and_portal_link",
            actor=principal.subject,
            correlation_id=x_correlation_id,
        )
    except ValueError as exc:
        msg = str(exc)
        code = status.HTTP_403_FORBIDDEN if "approval" in msg.lower() else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(status_code=code, detail=msg) from exc


@router.post("/proposals/{proposal_id}/checkout")
def checkout_from_proposal_endpoint(
    proposal_id: str,
    payload: CheckoutFromProposalRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate verified checkout link for approved proposal (never marks PAID or WON prematurely)."""
    try:
        return initiate_proposal_checkout(
            db,
            proposal_id=proposal_id,
            provider=payload.provider,
            customer_email=payload.customer_email,
            customer_name=payload.customer_name,
            preferred_rail=payload.preferred_rail,
            actor=principal.subject,
        )
    except ValueError as exc:
        msg = str(exc)
        code = status.HTTP_403_FORBIDDEN if "approval" in msg.lower() else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(status_code=code, detail=msg) from exc


@router.get("/reconciliation")
def list_reconciliation_queue_endpoint(
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Inspect payment-to-activation reconciliation queue & retry state."""
    rows = db.query(P2PaymentReconciliationRecord).order_by(P2PaymentReconciliationRecord.created_at.desc()).all()
    items = [
        {
            "reconciliation_id": r.id,
            "proposal_id": r.proposal_id,
            "lead_id": r.lead_id,
            "org_id": r.org_id,
            "provider": r.provider,
            "checkout_reference": r.checkout_reference,
            "provider_event_id": r.provider_event_id,
            "expected_sku": r.expected_sku,
            "expected_amount": r.expected_amount,
            "received_amount": r.received_amount,
            "currency": r.currency,
            "verification_state": r.verification_state,
            "retry_count": r.retry_count,
            "last_error": r.last_error,
            "activated_org_id": r.activated_org_id,
            "invoice_id": r.invoice_id,
            "activation_id": r.activation_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"count": len(items), "reconciliations": items}


@router.post("/reconciliation/{reconciliation_id}/retry")
def retry_reconciliation_endpoint(
    reconciliation_id: str,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retry reconciliation for a pending payment queue entry."""
    try:
        return retry_reconciliation_entry(db, reconciliation_id=reconciliation_id, actor=principal.subject)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/engagements")
def list_engagements_endpoint(
    org_id: str | None = None,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List paid customer engagements, onboarding checklists, and delivery records."""
    q = db.query(P2CustomerEngagementRecord).order_by(P2CustomerEngagementRecord.created_at.desc())
    if org_id:
        q = q.filter(P2CustomerEngagementRecord.org_id == org_id)
    rows = q.all()
    return {"count": len(rows), "engagements": [serialize_engagement(r) for r in rows]}


@router.post("/engagements/{engagement_id}/onboarding")
def submit_onboarding_endpoint(
    engagement_id: str,
    payload: OnboardingInputsRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Submit required onboarding business inputs for an activated paid customer."""
    try:
        return submit_onboarding_inputs(
            db,
            engagement_id=engagement_id,
            target_domain=payload.target_domain,
            cms_delivery_mode=payload.cms_delivery_mode,
            priority_topics=payload.priority_topics,
            target_geography=payload.target_geography,
            brand_tone_notes=payload.brand_tone_notes,
            wordpress_site_url=payload.wordpress_site_url,
            actor=principal.subject,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/engagements/{engagement_id}/deliver")
def execute_delivery_endpoint(
    engagement_id: str,
    payload: DeliveryRunRequest | None = None,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Execute multi-step P1 workflow for pilot deliverables (audit, keyword cluster, 2 Schema articles)."""
    try:
        return execute_pilot_delivery(
            db,
            engagement_id=engagement_id,
            execution_mode=payload.execution_mode if payload else None,
            actor=principal.subject,
            correlation_id=x_correlation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/engagements/{engagement_id}/complete-delivery")
def complete_delivery_endpoint(
    engagement_id: str,
    payload: DeliveryCompleteRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Confirm client review & complete pilot delivery milestone."""
    try:
        return complete_engagement_delivery(
            db,
            engagement_id=engagement_id,
            delivery_channel_proof=payload.delivery_channel_proof,
            client_acceptance_note=payload.client_acceptance_note,
            actor=principal.subject,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/engagements/{engagement_id}/feedback-renewal")
def feedback_and_renewal_endpoint(
    engagement_id: str,
    payload: FeedbackRenewalRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Capture genuine customer feedback & generate evidence-backed renewal recommendation."""
    try:
        return record_customer_feedback_and_renewal(
            db,
            engagement_id=engagement_id,
            rating=payload.rating,
            comments=payload.comments,
            improvements_requested=payload.improvements_requested,
            interested_in_renewal=payload.interested_in_renewal,
            actor=principal.subject,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/control-centre")
def get_control_centre_endpoint(
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Founder Control Centre: real verified KPIs strictly separated from simulation/test metrics."""
    return get_founder_control_centre(db)


@router.get("/acceptance-checklist")
def get_acceptance_checklist_endpoint(
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve all 12 P2 real-world pilot verification steps with honest NOT_TESTED / SANDBOX_VERIFIED / LIVE_VERIFIED states."""
    steps = seed_and_get_acceptance_checklist(db)
    summary = {
        "NOT_TESTED": sum(1 for s in steps if s["verification_status"] == "NOT_TESTED"),
        "SANDBOX_VERIFIED": sum(1 for s in steps if s["verification_status"] == "SANDBOX_VERIFIED"),
        "LIVE_VERIFIED": sum(1 for s in steps if s["verification_status"] == "LIVE_VERIFIED"),
    }
    return {"total_steps": len(steps), "summary": summary, "steps": steps}


@router.post("/acceptance-checklist/{step_number}")
def update_acceptance_step_endpoint(
    step_number: int,
    payload: AcceptanceStepUpdateRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record Owner verification evidence for a real-world 12-step pilot run item."""
    try:
        return update_acceptance_step(
            db,
            step_number=step_number,
            verification_status=payload.verification_status,
            evidence_summary=payload.evidence_summary,
            evidence_ref=payload.evidence_ref,
            verified_by=principal.subject,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
