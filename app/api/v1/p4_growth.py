"""P4 Repeatable Growth & GTM Engine API router."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import (
    APIPrincipal,
    enforce_tenant_access,
    get_current_principal,
)
from app.services.p4_growth_gtm import (
    check_gtm_copy_safety,
    compute_gtm_funnel_analytics,
    create_growth_campaign,
    create_icp_profile,
    create_pipeline_deal,
    execute_approved_campaign,
    list_campaigns,
    list_icp_profiles,
    list_market_intel,
    list_pipeline_deals,
    record_market_intel,
    score_prospect_against_icp,
    transition_pipeline_deal,
)

router = APIRouter(prefix="/v1/p4/growth", tags=["p4-growth-gtm"])


def _resolve_scope_org(principal: APIPrincipal, requested_org_id: str | None) -> str | None:
    if principal.org_id:
        if requested_org_id and requested_org_id != principal.org_id:
            enforce_tenant_access(principal, requested_org_id)
        return principal.org_id
    return requested_org_id


class IcpCreateRequest(BaseModel):
    org_id: str | None = None
    name: str = Field(..., min_length=2, max_length=200)
    industry: str = Field(..., min_length=2, max_length=120)
    geography: str = Field(default="India", max_length=120)
    company_size_range: str = Field(default="10-200", max_length=80)
    buyer_personas: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    value_propositions: list[str] = Field(default_factory=list)
    disqualifiers: list[str] = Field(default_factory=list)


class IcpScoreRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    industry: str = Field(..., min_length=1, max_length=120)
    geography: str = Field(default="India", max_length=120)
    signals: list[str] = Field(default_factory=list)


class MarketIntelRequest(BaseModel):
    org_id: str | None = None
    icp_id: str | None = None
    intel_type: str = Field(..., min_length=3, max_length=48)
    subject_name: str = Field(..., min_length=2, max_length=200)
    summary: str = Field(..., min_length=5, max_length=2000)
    source_url: str | None = Field(default=None, max_length=500)
    source_type: str = Field(default="public_web", max_length=64)
    evidence_ref: str | None = Field(default=None, max_length=200)
    collected_at: datetime | None = None
    confidence_level: str = Field(default="OBSERVATION", max_length=48)
    verified_facts: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)


class CampaignCreateRequest(BaseModel):
    org_id: str | None = None
    icp_id: str | None = None
    name: str = Field(..., min_length=2, max_length=200)
    objective: str = Field(..., min_length=4, max_length=1000)
    product_name: str = Field(..., min_length=2, max_length=200)
    target_audience: str = Field(..., min_length=2, max_length=300)
    keywords: list[str] = Field(default_factory=lambda: ["B2B SME AI", "Workflow Automation"])
    channels: list[str] = Field(default_factory=lambda: ["seo", "social", "email"])
    budget_cap_inr: float = Field(default=0.0, ge=0.0)
    custom_copy_overrides: dict[str, Any] | None = None


class CampaignExecuteRequest(BaseModel):
    execution_mode: str = Field(default="SIMULATION", max_length=32)


class DealCreateRequest(BaseModel):
    org_id: str | None = None
    company_name: str = Field(..., min_length=2, max_length=200)
    contact_email: str | None = Field(default=None, max_length=200)
    lead_id: str | None = None
    campaign_id: str | None = None
    icp_id: str | None = None
    deal_value_inr: float = Field(default=0.0, ge=0.0)
    currency: str = Field(default="INR", max_length=10)
    attribution_source: str = Field(default="ORGANIC_INBOUND", max_length=64)
    evidence_status: str = Field(default="SANDBOX", max_length=32)
    next_action: str | None = Field(default=None, max_length=250)


class DealTransitionRequest(BaseModel):
    target_stage: str = Field(..., min_length=2, max_length=48)
    lost_reason: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)


class CopySafetyRequest(BaseModel):
    subject: str = Field(default="GTM Copy Check", max_length=200)
    payload: Any = Field(default_factory=dict)


@router.get("/overview")
def p4_growth_overview(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return P4 GTM analytics, ICPs, provenance intel, campaigns, and deals for UI hydration."""
    scope_org = _resolve_scope_org(principal, org_id)
    return {
        "analytics": compute_gtm_funnel_analytics(db, org_id=scope_org),
        "icps": list_icp_profiles(db, org_id=scope_org),
        "intel": list_market_intel(db, org_id=scope_org),
        "campaigns": list_campaigns(db, org_id=scope_org),
        "deals": list_pipeline_deals(db, org_id=scope_org),
    }


@router.post("/icps")
def p4_create_icp(
    body: IcpCreateRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    try:
        return create_icp_profile(
            db,
            org_id=scope_org,
            name=body.name,
            industry=body.industry,
            geography=body.geography,
            company_size_range=body.company_size_range,
            buyer_personas=body.buyer_personas,
            pain_points=body.pain_points,
            value_propositions=body.value_propositions,
            disqualifiers=body.disqualifiers,
            actor=principal.subject,
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/icps")
def p4_list_icps(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    rows = list_icp_profiles(db, org_id=scope_org)
    return {"count": len(rows), "icps": rows}


@router.post("/icps/{icp_id}/score")
def p4_score_icp(
    icp_id: str,
    body: IcpScoreRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return score_prospect_against_icp(
            db,
            icp_id=icp_id,
            org_id=principal.org_id,
            company_name=body.company_name,
            industry=body.industry,
            geography=body.geography,
            signals=body.signals,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/intel")
def p4_create_intel(
    body: MarketIntelRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    try:
        return record_market_intel(
            db,
            org_id=scope_org,
            icp_id=body.icp_id,
            intel_type=body.intel_type,
            subject_name=body.subject_name,
            summary=body.summary,
            source_url=body.source_url,
            source_type=body.source_type,
            evidence_ref=body.evidence_ref,
            collected_at=body.collected_at,
            confidence_level=body.confidence_level,
            verified_facts=body.verified_facts,
            inferences=body.inferences,
            actor=principal.subject,
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/intel")
def p4_list_intel(
    org_id: str | None = Query(default=None),
    intel_type: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    rows = list_market_intel(db, org_id=scope_org, intel_type=intel_type)
    return {"count": len(rows), "intel": rows}


@router.post("/campaigns")
def p4_create_campaign(
    body: CampaignCreateRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    try:
        return create_growth_campaign(
            db,
            org_id=scope_org,
            icp_id=body.icp_id,
            name=body.name,
            objective=body.objective,
            product_name=body.product_name,
            target_audience=body.target_audience,
            keywords=body.keywords,
            channels=body.channels,
            budget_cap_inr=body.budget_cap_inr,
            custom_copy_overrides=body.custom_copy_overrides,
            actor=principal.subject,
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/campaigns")
def p4_list_campaigns(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    rows = list_campaigns(db, org_id=scope_org)
    return {"count": len(rows), "campaigns": rows}


@router.post("/campaigns/{campaign_id}/execute")
def p4_execute_campaign(
    campaign_id: str,
    body: CampaignExecuteRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return execute_approved_campaign(
            db,
            campaign_id=campaign_id,
            org_id=principal.org_id,
            execution_mode=body.execution_mode,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/deals")
def p4_create_deal(
    body: DealCreateRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    try:
        return create_pipeline_deal(
            db,
            org_id=scope_org,
            company_name=body.company_name,
            contact_email=body.contact_email,
            lead_id=body.lead_id,
            campaign_id=body.campaign_id,
            icp_id=body.icp_id,
            deal_value_inr=body.deal_value_inr,
            currency=body.currency,
            attribution_source=body.attribution_source,
            evidence_status=body.evidence_status,
            next_action=body.next_action,
            actor=principal.subject,
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/deals")
def p4_list_deals(
    org_id: str | None = Query(default=None),
    evidence_status: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    rows = list_pipeline_deals(db, org_id=scope_org, evidence_status=evidence_status)
    return {"count": len(rows), "deals": rows}


@router.post("/deals/{deal_id}/transition")
def p4_transition_deal(
    deal_id: str,
    body: DealTransitionRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return transition_pipeline_deal(
            db,
            deal_id=deal_id,
            org_id=principal.org_id,
            target_stage=body.target_stage,
            lost_reason=body.lost_reason,
            note=body.note,
            actor=principal.subject,
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/analytics")
def p4_funnel_analytics(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    return compute_gtm_funnel_analytics(db, org_id=scope_org)


@router.post("/copy-safety-check")
def p4_copy_safety_check(
    body: CopySafetyRequest,
    _principal: APIPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    return check_gtm_copy_safety(body.payload, subject=body.subject)
