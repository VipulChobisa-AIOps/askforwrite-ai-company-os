"""P6 Multi-Industry SME Packs & India SEO Baseline FastAPI router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import APIPrincipal, enforce_tenant_access, require_owner, require_tenant_operator
from app.services.p6_industry_packs import (
    compute_p6_overview,
    create_india_seo_baseline,
    deploy_industry_pack_for_tenant,
    list_india_seo_baselines,
    list_industry_packs,
    run_pack_diagnostics,
    upsert_industry_pack,
)

router = APIRouter(prefix="/v1/p6/packs", tags=["P6 Multi-Industry SME Packs"])


def _resolve_scope_org(principal: APIPrincipal, requested_org_id: str | None) -> str | None:
    if principal.is_platform_operator:
        return requested_org_id
    if not principal.org_id:
        raise HTTPException(status_code=403, detail="Tenant organization scope is required")
    if requested_org_id:
        enforce_tenant_access(principal, requested_org_id)
        return requested_org_id
    return principal.org_id


class IndustryPackUpsertRequest(BaseModel):
    pack_key: str = Field(..., min_length=3, max_length=80)
    name: str = Field(..., min_length=3, max_length=160)
    sector: str = Field(..., min_length=2, max_length=80)
    description: str = Field(default="", max_length=1000)
    tier_id: str = Field(..., min_length=2, max_length=64)
    selected_modules: list[str] = Field(default_factory=list)
    catalog_service_ids: list[str] = Field(default_factory=list)
    agent_ids: list[str] = Field(default_factory=list)
    analytics_capabilities: list[str] = Field(default_factory=list)
    kpi_definitions: list[str] = Field(default_factory=list)
    default_config: dict[str, Any] = Field(default_factory=dict)
    readiness_status: str = Field(default="SANDBOX", max_length=32)
    verified_live_customers: int = Field(default=0, ge=0)
    is_active: bool = True


class DeployPackRequest(BaseModel):
    org_id: str | None = None
    pack_key: str = Field(..., min_length=3, max_length=80)
    configuration: dict[str, Any] = Field(default_factory=dict)
    execution_mode: str = Field(default="SIMULATION", max_length=24)


class DiagnosticsRequest(BaseModel):
    sample_inventory_items: list[dict[str, Any]] | None = None
    hour_of_day: int = Field(default=9, ge=0, le=23)
    quality_preset: str = Field(default="ripe", max_length=32)


class SeoBaselineRequest(BaseModel):
    org_id: str | None = None
    city_or_cluster: str = Field(..., min_length=2, max_length=120)
    industry_vertical: str = Field(..., min_length=2, max_length=80)
    primary_catalog_sku: str = Field(..., min_length=2, max_length=80)
    target_keywords: list[str] = Field(default_factory=list)
    business_name: str = Field(default="AskforWrite Client SME", max_length=160)


@router.get("/overview")
def p6_packs_overview(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return P6 industry pack catalog, tenant deployments, and India SEO baselines."""
    scope_org = _resolve_scope_org(principal, org_id)
    return compute_p6_overview(db, org_id=scope_org)


@router.get("/catalog")
def p6_list_catalog(
    sector: str | None = Query(default=None),
    readiness_status: str | None = Query(default=None),
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = list_industry_packs(db, sector=sector, readiness_status=readiness_status)
    return {"count": len(rows), "packs": rows}


@router.post("/catalog")
def p6_upsert_catalog(
    body: IndustryPackUpsertRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return upsert_industry_pack(
            db,
            pack_key=body.pack_key,
            name=body.name,
            sector=body.sector,
            description=body.description,
            tier_id=body.tier_id,
            selected_modules=body.selected_modules,
            catalog_service_ids=body.catalog_service_ids,
            agent_ids=body.agent_ids,
            analytics_capabilities=body.analytics_capabilities,
            kpi_definitions=body.kpi_definitions,
            default_config=body.default_config,
            readiness_status=body.readiness_status,
            verified_live_customers=body.verified_live_customers,
            is_active=body.is_active,
            actor=principal.subject,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/deployments")
def p6_deploy_pack(
    body: DeployPackRequest,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    if not scope_org:
        raise HTTPException(status_code=422, detail="org_id is required to deploy an industry pack")
    try:
        return deploy_industry_pack_for_tenant(
            db,
            org_id=scope_org,
            pack_key=body.pack_key,
            configuration=body.configuration,
            execution_mode=body.execution_mode,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/deployments/{deployment_id}/diagnostics")
def p6_run_diagnostics(
    deployment_id: str,
    body: DiagnosticsRequest,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, None)
    try:
        return run_pack_diagnostics(
            db,
            deployment_id=deployment_id,
            org_id=scope_org,
            sample_inventory_items=body.sample_inventory_items,
            hour_of_day=body.hour_of_day,
            quality_preset=body.quality_preset,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/seo-baselines")
def p6_create_seo_baseline(
    body: SeoBaselineRequest,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    try:
        return create_india_seo_baseline(
            db,
            org_id=scope_org,
            city_or_cluster=body.city_or_cluster,
            industry_vertical=body.industry_vertical,
            primary_catalog_sku=body.primary_catalog_sku,
            target_keywords=body.target_keywords,
            business_name=body.business_name,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/seo-baselines")
def p6_list_seo_baselines(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    rows = list_india_seo_baselines(db, org_id=scope_org)
    return {"count": len(rows), "seo_baselines": rows}
