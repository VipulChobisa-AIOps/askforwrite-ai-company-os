"""P5 Productization & Multi-Customer Scale FastAPI router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import APIPrincipal, enforce_tenant_access, require_owner, require_tenant_operator
from app.services.p5_productization import (
    compute_p5_scale_summary,
    create_operational_incident,
    create_or_update_template,
    evaluate_quota_event,
    get_tenant_policy,
    list_operational_incidents,
    list_p5_templates,
    list_provisioning_runs,
    list_quota_events,
    list_tenant_policies,
    retry_provisioning_run,
    seed_default_p5_templates,
    start_provisioning_run,
    transition_operational_incident,
    upsert_tenant_policy,
)

router = APIRouter(prefix="/v1/p5/scale", tags=["P5 Productization & Scale"])


def _resolve_scope_org(principal: APIPrincipal, requested_org_id: str | None) -> str | None:
    if principal.is_platform_operator:
        return requested_org_id
    if not principal.org_id:
        raise HTTPException(status_code=403, detail="Tenant organization scope is required")
    if requested_org_id:
        enforce_tenant_access(principal, requested_org_id)
        return requested_org_id
    return principal.org_id


class TemplateCreateRequest(BaseModel):
    template_key: str = Field(..., min_length=3, max_length=80)
    name: str = Field(..., min_length=3, max_length=160)
    description: str = Field(default="", max_length=1000)
    industry: str = Field(..., min_length=2, max_length=80)
    tier_id: str = Field(..., min_length=2, max_length=64)
    selected_modules: list[str] = Field(default_factory=list)
    catalog_service_ids: list[str] = Field(default_factory=list)
    default_agent_ids: list[str] = Field(default_factory=list)
    connector_requirements: list[str] = Field(default_factory=list)
    policy_overrides: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class ProvisioningStartRequest(BaseModel):
    template_key: str = Field(..., min_length=3, max_length=80)
    idempotency_key: str = Field(..., min_length=4, max_length=180)
    org_id: str | None = None
    company_name: str | None = Field(default=None, max_length=200)
    execution_mode: str = Field(default="SIMULATION", max_length=24)
    simulate_fail_at_step: str | None = Field(default=None, max_length=48)
    max_attempts: int = Field(default=3, ge=1, le=10)


class ProvisioningRetryRequest(BaseModel):
    org_id: str | None = None
    company_name: str | None = Field(default=None, max_length=200)


class TenantPolicyUpsertRequest(BaseModel):
    tier_id: str | None = Field(default=None, max_length=64)
    rate_limit_rpm: int | None = Field(default=None, gt=0)
    daily_agent_runs_cap: int | None = Field(default=None, gt=0)
    monthly_credit_budget: int | None = Field(default=None, gt=0)
    storage_quota_mb: int | None = Field(default=None, gt=0)
    sla_target_uptime_pct: float | None = Field(default=None, ge=50.0, le=100.0)
    sla_response_minutes: int | None = Field(default=None, gt=0)
    auto_throttle_on_breach: bool | None = None
    custom_limits: dict[str, Any] | None = None


class QuotaCheckRequest(BaseModel):
    org_id: str | None = None
    metric_type: str = Field(..., min_length=3, max_length=64)
    observed_value: float = Field(..., ge=0.0)
    details: dict[str, Any] = Field(default_factory=dict)


class IncidentCreateRequest(BaseModel):
    org_id: str | None = None
    title: str = Field(..., min_length=3, max_length=200)
    severity: str = Field(default="SEV3_MEDIUM", max_length=24)
    category: str = Field(default="SLA_DEGRADATION", max_length=48)
    root_cause: str | None = Field(default=None, max_length=2000)
    assigned_to: str | None = Field(default=None, max_length=120)


class IncidentTransitionRequest(BaseModel):
    target_status: str = Field(..., min_length=3, max_length=24)
    root_cause: str | None = Field(default=None, max_length=2000)
    mitigation_notes: str | None = Field(default=None, max_length=2000)
    assigned_to: str | None = Field(default=None, max_length=120)


@router.get("/overview")
def p5_scale_overview(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return P5 templates, provisioning FSM runs, tenant policies, quota events, and incidents."""
    scope_org = _resolve_scope_org(principal, org_id)
    return {
        "summary": compute_p5_scale_summary(db, org_id=scope_org),
        "templates": list_p5_templates(db, active_only=True),
        "provisioning_runs": list_provisioning_runs(db, org_id=scope_org, limit=50),
        "policies": list_tenant_policies(db, org_id=scope_org),
        "quota_events": list_quota_events(db, org_id=scope_org, limit=50),
        "incidents": list_operational_incidents(db, org_id=scope_org),
    }


@router.get("/templates")
def p5_list_templates(
    industry: str | None = Query(default=None),
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = list_p5_templates(db, industry=industry, active_only=True)
    return {"count": len(rows), "templates": rows}


@router.post("/templates/seed")
def p5_seed_templates(
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    seeded = seed_default_p5_templates(db, actor=principal.subject)
    return {"count": len(seeded), "templates": seeded}


@router.post("/templates")
def p5_create_template(
    body: TemplateCreateRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return create_or_update_template(
            db,
            template_key=body.template_key,
            name=body.name,
            description=body.description,
            industry=body.industry,
            tier_id=body.tier_id,
            selected_modules=body.selected_modules,
            catalog_service_ids=body.catalog_service_ids,
            default_agent_ids=body.default_agent_ids,
            connector_requirements=body.connector_requirements,
            policy_overrides=body.policy_overrides,
            is_active=body.is_active,
            actor=principal.subject,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/provisioning")
def p5_start_provisioning(
    body: ProvisioningStartRequest,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    if scope_org is None and not principal.is_platform_operator:
        raise HTTPException(status_code=403, detail="Tenant principals can only provision their own organization")
    try:
        return start_provisioning_run(
            db,
            template_key=body.template_key,
            idempotency_key=body.idempotency_key,
            org_id=scope_org,
            company_name=body.company_name,
            execution_mode=body.execution_mode,
            simulate_fail_at_step=body.simulate_fail_at_step,
            max_attempts=body.max_attempts,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc).lower()
        code = 409 if "idempotency_key already registered" in msg else (404 if "not found" in msg else 422)
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/provisioning")
def p5_list_provisioning(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    rows = list_provisioning_runs(db, org_id=scope_org)
    return {"count": len(rows), "runs": rows}


@router.post("/provisioning/{run_id}/retry")
def p5_retry_provisioning(
    run_id: str,
    body: ProvisioningRetryRequest,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    try:
        return retry_provisioning_run(
            db,
            run_id=run_id,
            org_id=scope_org,
            company_name=body.company_name,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/policies/{org_id}")
def p5_get_policy(
    org_id: str,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    enforce_tenant_access(principal, org_id)
    try:
        return get_tenant_policy(db, org_id=org_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/policies/{org_id}")
def p5_upsert_policy(
    org_id: str,
    body: TenantPolicyUpsertRequest,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    enforce_tenant_access(principal, org_id)
    try:
        return upsert_tenant_policy(
            db,
            org_id=org_id,
            tier_id=body.tier_id,
            rate_limit_rpm=body.rate_limit_rpm,
            daily_agent_runs_cap=body.daily_agent_runs_cap,
            monthly_credit_budget=body.monthly_credit_budget,
            storage_quota_mb=body.storage_quota_mb,
            sla_target_uptime_pct=body.sla_target_uptime_pct,
            sla_response_minutes=body.sla_response_minutes,
            auto_throttle_on_breach=body.auto_throttle_on_breach,
            custom_limits=body.custom_limits,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/quota-check")
def p5_quota_check(
    body: QuotaCheckRequest,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    if not scope_org:
        raise HTTPException(status_code=422, detail="org_id is required for quota evaluation")
    try:
        return evaluate_quota_event(
            db,
            org_id=scope_org,
            metric_type=body.metric_type,
            observed_value=body.observed_value,
            details=body.details,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/incidents")
def p5_list_incidents(
    org_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    rows = list_operational_incidents(db, org_id=scope_org, status=status)
    return {"count": len(rows), "incidents": rows}


@router.post("/incidents")
def p5_create_incident(
    body: IncidentCreateRequest,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    try:
        return create_operational_incident(
            db,
            org_id=scope_org,
            title=body.title,
            severity=body.severity,
            category=body.category,
            root_cause=body.root_cause,
            assigned_to=body.assigned_to,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/incidents/{incident_id}/transition")
def p5_transition_incident(
    incident_id: str,
    body: IncidentTransitionRequest,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, None)
    try:
        return transition_operational_incident(
            db,
            incident_id=incident_id,
            org_id=scope_org,
            target_status=body.target_status,
            root_cause=body.root_cause,
            mitigation_notes=body.mitigation_notes,
            assigned_to=body.assigned_to,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
