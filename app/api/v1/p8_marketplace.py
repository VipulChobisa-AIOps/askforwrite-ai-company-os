"""P8 Marketplace Ecosystem & Master Roadmap Scorecard FastAPI routers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import APIPrincipal, enforce_tenant_access, get_current_principal, require_owner
from app.services.p8_marketplace import (
    compute_master_roadmap_scorecard,
    compute_p8_overview,
    create_marketplace_listing,
    install_marketplace_listing,
    list_developers,
    list_marketplace_listings,
    list_marketplace_reviews,
    list_revenue_share_ledger,
    list_tenant_installs,
    moderate_marketplace_review,
    record_marketplace_revenue_share,
    register_developer_profile,
    review_marketplace_listing,
    submit_marketplace_review,
    verify_developer_kyb,
    verify_listing_signature,
)

router = APIRouter(prefix="/v1/p8/marketplace", tags=["P8 Marketplace Ecosystem"])
ops_scorecard_router = APIRouter(prefix="/v1/ops", tags=["Roadmap Scorecard"])


def _resolve_scope_org(principal: APIPrincipal, requested_org_id: str | None) -> str | None:
    if principal.role == "owner" and not principal.org_id:
        return requested_org_id
    if requested_org_id:
        enforce_tenant_access(principal, requested_org_id)
        return requested_org_id
    return principal.org_id


class DeveloperRegisterRequest(BaseModel):
    org_id: str | None = None
    developer_name: str = Field(..., min_length=2, max_length=160)
    contact_email: str = Field(..., min_length=4, max_length=160)
    legal_entity_name: str = Field(..., min_length=2, max_length=200)
    tax_or_gst_id: str | None = Field(default=None, max_length=64)
    payout_account: str | None = Field(default=None, max_length=120)


class DeveloperKybDecisionRequest(BaseModel):
    kyb_status: str = Field(..., min_length=3, max_length=32)
    kyb_notes: str | None = Field(default=None, max_length=1000)


class ListingCreateRequest(BaseModel):
    developer_id: str = Field(..., min_length=3, max_length=36)
    listing_slug: str = Field(..., min_length=3, max_length=100)
    name: str = Field(..., min_length=3, max_length=160)
    package_type: str = Field(default="AGENT_PLUGIN", max_length=48)
    description: str = Field(default="", max_length=2000)
    version: str = Field(default="1.0.0", max_length=32)
    requested_permissions: list[str] = Field(default_factory=lambda: ["read_metrics"])
    endpoint_url: str | None = Field(default=None, max_length=500)
    price_inr_monthly: int = Field(default=0, ge=0)
    commission_bps: int = Field(default=1500, ge=500, le=3000)


class ListingReviewDecisionRequest(BaseModel):
    security_review_status: str = Field(..., min_length=3, max_length=32)
    publish: bool = False
    review_notes: str | None = Field(default=None, max_length=1000)


class InstallCreateRequest(BaseModel):
    org_id: str | None = None
    listing_id: str = Field(..., min_length=3, max_length=36)
    granted_permissions: list[str] | None = None
    secrets_payload: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class MarketplaceReviewCreateRequest(BaseModel):
    org_id: str | None = None
    listing_id: str = Field(..., min_length=3, max_length=36)
    rating: int = Field(..., ge=1, le=5)
    comment: str = Field(..., min_length=2, max_length=2000)


class MarketplaceReviewModerationRequest(BaseModel):
    abuse_flagged: bool = True
    moderation_status: str = Field(default="FLAGGED_UNDER_REVIEW", max_length=32)
    abuse_reason: str | None = Field(default=None, max_length=500)


class RevenueShareCreateRequest(BaseModel):
    org_id: str | None = None
    install_id: str = Field(..., min_length=3, max_length=36)
    gross_amount_inr: float = Field(..., gt=0.0)
    evidence_status: str = Field(default="SANDBOX", max_length=24)


@router.get("/overview")
def p8_marketplace_overview(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    return compute_p8_overview(db, org_id=scope_org)


@router.post("/developers")
def p8_register_developer(
    body: DeveloperRegisterRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    return register_developer_profile(
        db,
        org_id=scope_org,
        developer_name=body.developer_name,
        contact_email=body.contact_email,
        legal_entity_name=body.legal_entity_name,
        tax_or_gst_id=body.tax_or_gst_id,
        payout_account=body.payout_account,
        actor=principal.subject,
    )


@router.get("/developers")
def p8_list_developers(
    kyb_status: str | None = Query(default=None),
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = list_developers(db, kyb_status=kyb_status)
    return {"count": len(rows), "developers": rows}


@router.post("/developers/{developer_id}/kyb")
def p8_verify_kyb(
    developer_id: str,
    body: DeveloperKybDecisionRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return verify_developer_kyb(
            db,
            developer_id=developer_id,
            kyb_status=body.kyb_status,
            kyb_notes=body.kyb_notes,
            actor=principal.subject,
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/listings")
def p8_create_listing(
    body: ListingCreateRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return create_marketplace_listing(
            db,
            developer_id=body.developer_id,
            listing_slug=body.listing_slug,
            name=body.name,
            package_type=body.package_type,
            description=body.description,
            version=body.version,
            requested_permissions=body.requested_permissions,
            endpoint_url=body.endpoint_url,
            price_inr_monthly=body.price_inr_monthly,
            commission_bps=body.commission_bps,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/listings")
def p8_list_listings(
    published_only: bool = Query(default=False),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = list_marketplace_listings(db, published_only=published_only)
    return {"count": len(rows), "listings": rows}


@router.get("/listings/{listing_id}/verify-signature")
def p8_verify_listing_signature(
    listing_id: str,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return verify_listing_signature(db, listing_id=listing_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/listings/{listing_id}/review")
def p8_review_listing(
    listing_id: str,
    body: ListingReviewDecisionRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return review_marketplace_listing(
            db,
            listing_id=listing_id,
            security_review_status=body.security_review_status,
            publish=body.publish,
            review_notes=body.review_notes,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/installs")
def p8_install_listing(
    body: InstallCreateRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    if not scope_org:
        raise HTTPException(status_code=422, detail="org_id is required to install a marketplace package")
    try:
        return install_marketplace_listing(
            db,
            org_id=scope_org,
            listing_id=body.listing_id,
            granted_permissions=body.granted_permissions,
            secrets_payload=body.secrets_payload,
            config=body.config,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/installs")
def p8_list_installs(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    rows = list_tenant_installs(db, org_id=scope_org)
    return {"count": len(rows), "installs": rows}


@router.post("/reviews")
def p8_submit_review(
    body: MarketplaceReviewCreateRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    if not scope_org:
        raise HTTPException(status_code=422, detail="org_id is required for verified installer reviews")
    try:
        return submit_marketplace_review(
            db,
            org_id=scope_org,
            listing_id=body.listing_id,
            rating=body.rating,
            comment=body.comment,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/reviews")
def p8_list_reviews(
    listing_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = list_marketplace_reviews(db, listing_id=listing_id)
    return {"count": len(rows), "reviews": rows}


@router.post("/reviews/{review_id}/moderate")
def p8_moderate_review(
    review_id: str,
    body: MarketplaceReviewModerationRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return moderate_marketplace_review(
            db,
            review_id=review_id,
            abuse_flagged=body.abuse_flagged,
            moderation_status=body.moderation_status,
            abuse_reason=body.abuse_reason,
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/revenue-share")
def p8_record_revenue_share(
    body: RevenueShareCreateRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    try:
        return record_marketplace_revenue_share(
            db,
            install_id=body.install_id,
            org_id=scope_org,
            gross_amount_inr=body.gross_amount_inr,
            evidence_status=body.evidence_status,
            actor=principal.subject,
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/revenue-share")
def p8_list_revenue_share(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    return list_revenue_share_ledger(db, org_id=scope_org)


@ops_scorecard_router.get("/roadmap-scorecard")
def get_master_roadmap_scorecard(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return authoritative P0-P8 roadmap scorecard preserving P3.1 production cutover blockers."""
    return compute_master_roadmap_scorecard(db)
