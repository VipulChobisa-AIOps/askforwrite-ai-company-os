"""P7 Controlled Autonomous Workforce FastAPI router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import (
    TENANT_MANAGER_ROLES,
    APIPrincipal,
    enforce_tenant_access,
    get_current_principal,
    require_owner,
    require_tenant_manager,
)
from app.services.p7_autonomy_workforce import (
    cancel_delegation_plan,
    compute_p7_overview,
    create_delegation_plan,
    execute_delegation_plan,
    list_agent_evaluations,
    list_autonomy_policies,
    purge_tenant_memory,
    read_tenant_memories,
    resume_autonomy_policy,
    run_agent_evaluation,
    upsert_autonomy_policy,
    write_tenant_memory,
)

router = APIRouter(prefix="/v1/p7/workforce", tags=["P7 Controlled Autonomous Workforce"])


def _resolve_scope_org(principal: APIPrincipal, requested_org_id: str | None) -> str | None:
    if principal.is_platform_operator:
        return requested_org_id
    if not principal.org_id:
        raise HTTPException(status_code=403, detail="Organization context is required")
    if requested_org_id:
        enforce_tenant_access(principal, requested_org_id)
        return requested_org_id
    return principal.org_id


class DagPlanCreateRequest(BaseModel):
    org_id: str | None = None
    name: str = Field(..., min_length=3, max_length=160)
    objective: str = Field(default="", max_length=1000)
    nodes: list[dict[str, Any]] = Field(..., min_length=1)
    max_depth: int = Field(default=4, ge=1, le=12)
    credit_budget: int = Field(default=20, ge=0, le=10000)
    execution_budget_limit: int = Field(default=100, ge=1, le=100000)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    approval_id: str | None = None


class DagPlanExecuteRequest(BaseModel):
    execution_mode: str = Field(default="SIMULATION", max_length=24)
    approval_id: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    resume: bool = False


class DagPlanCancelRequest(BaseModel):
    reason: str = Field(default="Cancelled by operator", max_length=240)


class DagPlanRecoverRequest(BaseModel):
    execution_mode: str = Field(default="SIMULATION", max_length=24)
    approval_id: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)


class MemoryWriteRequest(BaseModel):
    org_id: str | None = None
    namespace: str = Field(..., min_length=2, max_length=80)
    memory_key: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=8000)
    source_type: str = Field(default="USER_CONFIG", max_length=48)
    source_ref: str | None = Field(default=None, max_length=200)
    ttl_seconds: int | None = Field(default=None, gt=0)


class MemoryPurgeRequest(BaseModel):
    org_id: str | None = None
    memory_id: str | None = None
    namespace: str | None = None
    dpdp_reason: str = Field(default="dpdp_erasure_request", max_length=200)


class AutonomyPolicyUpsertRequest(BaseModel):
    org_id: str | None = None
    autonomy_level: str = Field(..., min_length=3, max_length=48)
    requires_hitl_for_external: bool = True
    max_daily_budget_credits: int = Field(default=100, gt=0)
    max_daily_execution_units: int = Field(default=500, gt=0)
    min_eval_threshold: float = Field(default=0.75, ge=0.5, le=1.0)
    approval_id: str | None = None


class AutonomyResumeRequest(BaseModel):
    org_id: str | None = None
    note: str = Field(default="Reviewed and resumed by owner", max_length=500)


class AgentEvalCreateRequest(BaseModel):
    org_id: str | None = None
    agent_id: str = Field(..., min_length=3, max_length=100)
    eval_suite_name: str = Field(..., min_length=3, max_length=120)
    quality_score: float = Field(..., ge=0.0, le=1.0)
    safety_score: float = Field(..., ge=0.0, le=1.0)
    threshold_score: float | None = Field(default=None, ge=0.5, le=1.0)
    metrics: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=1000)


@router.get("/overview")
def p7_workforce_overview(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    return compute_p7_overview(db, org_id=scope_org)


@router.post("/dag-plans")
def p7_create_dag_plan(
    body: DagPlanCreateRequest,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    try:
        return create_delegation_plan(
            db,
            org_id=scope_org,
            name=body.name,
            objective=body.objective,
            nodes=body.nodes,
            max_depth=body.max_depth,
            credit_budget=body.credit_budget,
            execution_budget_limit=body.execution_budget_limit,
            timeout_seconds=body.timeout_seconds,
            approval_id=body.approval_id,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/dag-plans/{plan_id}/execute")
def p7_execute_dag_plan(
    plan_id: str,
    body: DagPlanExecuteRequest,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, None)
    try:
        return execute_delegation_plan(
            db,
            plan_id=plan_id,
            org_id=scope_org,
            principal=principal,
            execution_mode=body.execution_mode,
            approval_id=body.approval_id,
            timeout_seconds=body.timeout_seconds,
            resume=body.resume,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/dag-plans/{plan_id}/cancel")
def p7_cancel_dag_plan(
    plan_id: str,
    body: DagPlanCancelRequest,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, None)
    try:
        return cancel_delegation_plan(
            db,
            plan_id=plan_id,
            org_id=scope_org,
            reason=body.reason,
            actor=principal.subject,
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/dag-plans/{plan_id}/recover")
def p7_recover_dag_plan(
    plan_id: str,
    body: DagPlanRecoverRequest,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, None)
    try:
        return execute_delegation_plan(
            db,
            plan_id=plan_id,
            org_id=scope_org,
            principal=principal,
            execution_mode=body.execution_mode,
            approval_id=body.approval_id,
            timeout_seconds=body.timeout_seconds,
            resume=True,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/memories")
def p7_write_memory(
    body: MemoryWriteRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    if not scope_org:
        raise HTTPException(status_code=422, detail="org_id is required for tenant-isolated memory storage")
    try:
        return write_tenant_memory(
            db,
            org_id=scope_org,
            namespace=body.namespace,
            memory_key=body.memory_key,
            content=body.content,
            source_type=body.source_type,
            source_ref=body.source_ref,
            ttl_seconds=body.ttl_seconds,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/memories")
def p7_read_memories(
    org_id: str | None = Query(default=None),
    namespace: str | None = Query(default=None),
    include_expired: bool = Query(default=False),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    if not scope_org:
        raise HTTPException(status_code=422, detail="org_id is required to read tenant-scoped memory")
    rows = read_tenant_memories(db, org_id=scope_org, namespace=namespace, include_expired=include_expired)
    return {"count": len(rows), "memories": rows}


@router.post("/memories/purge")
def p7_purge_memories(
    body: MemoryPurgeRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    if not scope_org:
        raise HTTPException(status_code=422, detail="org_id is required for DPDP memory purge")
    if not body.memory_id and not body.namespace:
        if not principal.is_platform_operator and principal.role not in TENANT_MANAGER_ROLES:
            raise HTTPException(
                status_code=403,
                detail="Organization-wide memory purge requires tenant manager or administrator privileges",
            )
    return purge_tenant_memory(
        db,
        org_id=scope_org,
        memory_id=body.memory_id,
        namespace=body.namespace,
        dpdp_reason=body.dpdp_reason,
        actor=principal.subject,
    )


@router.put("/autonomy-policies/{agent_id}")
def p7_upsert_autonomy_policy(
    agent_id: str,
    body: AutonomyPolicyUpsertRequest,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    try:
        return upsert_autonomy_policy(
            db,
            org_id=scope_org,
            agent_id=agent_id,
            autonomy_level=body.autonomy_level,
            requires_hitl_for_external=body.requires_hitl_for_external,
            max_daily_budget_credits=body.max_daily_budget_credits,
            max_daily_execution_units=body.max_daily_execution_units,
            min_eval_threshold=body.min_eval_threshold,
            approval_id=body.approval_id,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/autonomy-policies")
def p7_list_autonomy_policies(
    org_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    rows = list_autonomy_policies(db, org_id=scope_org)
    return {"count": len(rows), "policies": rows}


@router.post("/autonomy-policies/{agent_id}/resume")
def p7_resume_autonomy_policy(
    agent_id: str,
    body: AutonomyResumeRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    try:
        return resume_autonomy_policy(db, org_id=scope_org, agent_id=agent_id, note=body.note, actor=principal.subject)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/evals")
def p7_run_eval(
    body: AgentEvalCreateRequest,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, body.org_id)
    try:
        return run_agent_evaluation(
            db,
            org_id=scope_org,
            agent_id=body.agent_id,
            eval_suite_name=body.eval_suite_name,
            quality_score=body.quality_score,
            safety_score=body.safety_score,
            threshold_score=body.threshold_score,
            metrics=body.metrics,
            notes=body.notes,
            actor=principal.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/evals")
def p7_list_evals(
    org_id: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scope_org = _resolve_scope_org(principal, org_id)
    rows = list_agent_evaluations(db, org_id=scope_org, agent_id=agent_id)
    return {"count": len(rows), "evals": rows}
