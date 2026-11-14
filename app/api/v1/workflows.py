"""Workflow Builder, 8-state FSM, HITL Pause/Resume, and Schedule API router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import WorkflowDefinitionRecord, WorkflowRunRecord
from app.security.auth import APIPrincipal, enforce_tenant_access, get_current_principal, require_tenant_operator
from app.services.workflow_engine import (
    cancel_workflow_run,
    create_draft_run,
    create_workflow_definition,
    prepare_run_ready,
    resume_workflow_run,
    serialize_definition,
    serialize_run,
    start_workflow_run,
)

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


class WorkflowStepInput(BaseModel):
    step_key: str = Field(min_length=1, max_length=100)
    step_type: str = Field(default="agent_step", max_length=32)
    agent_id: str | None = Field(default=None, max_length=100)
    action_label: str | None = Field(default=None, max_length=200)
    input_template: dict[str, Any] = Field(default_factory=dict)
    condition: dict[str, Any] | None = Field(default=None)
    required: bool = Field(default=True)
    approval_action: str | None = Field(default="workflow_hitl_gate", max_length=100)


class CreateWorkflowDefinitionRequest(BaseModel):
    name: str = Field(min_length=2, max_length=250)
    workflow_key: str | None = Field(default=None, max_length=100)
    description: str = Field(default="", max_length=1000)
    version: str = Field(default="1.0.0", max_length=32)
    trigger_type: str = Field(default="manual", max_length=32)
    schedule_cron: str | None = Field(default=None, max_length=100)
    max_credits_budget: int = Field(default=20, ge=1, le=500)
    timeout_seconds: int = Field(default=120, ge=5, le=3600)
    max_retries: int = Field(default=1, ge=0, le=5)
    execution_mode_default: str | None = Field(default=None, max_length=32)
    steps: list[WorkflowStepInput] = Field(min_length=1)


class CreateWorkflowRunRequest(BaseModel):
    workflow_id: str = Field(min_length=1, max_length=36)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    execution_mode: str | None = Field(default=None, max_length=32)
    idempotency_key: str | None = Field(default=None, max_length=200)
    start_immediately: bool = Field(default=True)


class CancelWorkflowRunRequest(BaseModel):
    reason: str = Field(default="Cancelled by operator", max_length=500)


@router.post("/definitions", status_code=201)
def create_workflow_definition_endpoint(
    body: CreateWorkflowDefinitionRequest,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a tenant-scoped multi-step workflow definition."""
    defn = create_workflow_definition(
        db,
        principal=principal,
        name=body.name,
        workflow_key=body.workflow_key,
        description=body.description,
        version=body.version,
        trigger_type=body.trigger_type,
        schedule_cron=body.schedule_cron,
        max_credits_budget=body.max_credits_budget,
        timeout_seconds=body.timeout_seconds,
        max_retries=body.max_retries,
        execution_mode_default=body.execution_mode_default,
        steps=[s.model_dump() for s in body.steps],
    )
    return {"status": "CREATED", "workflow": defn}


@router.get("/definitions")
def list_workflow_definitions_endpoint(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List persisted workflow definitions visible to the caller's organization."""
    q = db.query(WorkflowDefinitionRecord)
    if principal.org_id:
        q = q.filter(WorkflowDefinitionRecord.org_id == principal.org_id)
    rows = q.order_by(WorkflowDefinitionRecord.created_at.desc()).all()
    return {"count": len(rows), "workflows": [serialize_definition(r) for r in rows]}


@router.post("/runs")
def create_or_start_workflow_run_endpoint(
    body: CreateWorkflowRunRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a DRAFT run or execute it through READY -> RUNNING immediately."""
    if not body.start_immediately:
        run = create_draft_run(
            db,
            workflow_id=body.workflow_id,
            principal=principal,
            input_payload=body.input_payload,
            execution_mode=body.execution_mode,
            idempotency_key=body.idempotency_key,
        )
        return {"status": run["status"], "run": run}

    run = start_workflow_run(
        db,
        workflow_id=body.workflow_id,
        principal=principal,
        input_payload=body.input_payload,
        execution_mode=body.execution_mode,
        idempotency_key=body.idempotency_key,
    )
    return {"status": run["status"], "run": run}


@router.post("/runs/{run_id}/ready")
def mark_run_ready_endpoint(
    run_id: str,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Transition a DRAFT workflow run to READY."""
    run = prepare_run_ready(db, run_id=run_id, principal=principal)
    return {"status": run["status"], "run": run}


@router.post("/runs/{run_id}/start")
def start_existing_run_endpoint(
    run_id: str,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start a previously created DRAFT or READY workflow run."""
    run = db.get(WorkflowRunRecord, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    res = start_workflow_run(
        db,
        workflow_id=run.workflow_id,
        principal=principal,
        run_id=run.id,
        idempotency_key=run.idempotency_key,
    )
    return {"status": res["status"], "run": res}


@router.get("/runs")
def list_workflow_runs_endpoint(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List tenant-scoped workflow execution runs."""
    q = db.query(WorkflowRunRecord)
    if principal.org_id:
        q = q.filter(WorkflowRunRecord.org_id == principal.org_id)
    if status:
        q = q.filter(WorkflowRunRecord.status == status.upper())
    rows = q.order_by(WorkflowRunRecord.created_at.desc()).limit(limit).all()
    return {"count": len(rows), "runs": [serialize_run(r) for r in rows]}


@router.get("/runs/{run_id}")
def get_workflow_run_endpoint(
    run_id: str,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get full state, step results, and budget metrics for a workflow run."""
    run = db.get(WorkflowRunRecord, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if principal.org_id:
        enforce_tenant_access(principal, run.org_id)
    return {"run": serialize_run(run)}


@router.post("/runs/{run_id}/resume")
def resume_workflow_run_endpoint(
    run_id: str,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Resume a WAITING_APPROVAL workflow run once its ApprovalRequest has been decided."""
    run = resume_workflow_run(db, run_id=run_id, principal=principal)
    return {"status": run["status"], "run": run}


@router.post("/runs/{run_id}/cancel")
def cancel_workflow_run_endpoint(
    run_id: str,
    body: CancelWorkflowRunRequest | None = None,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Cancel an in-flight or waiting workflow run cleanly."""
    run = cancel_workflow_run(
        db,
        run_id=run_id,
        principal=principal,
        reason=body.reason if body else "Cancelled by operator",
    )
    return {"status": run["status"], "run": run}
