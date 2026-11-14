"""Multi-step SME Workflow Engine with strict 8-state FSM, HITL pause/resume, schedules, budgets, retries, and idempotency."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalRequest,
    TaskRecord,
    WorkflowDefinitionRecord,
    WorkflowRunRecord,
)
from app.security.auth import APIPrincipal, enforce_tenant_access
from app.services.evidence import record_execution_evidence
from app.services.execution_guard import (
    ExecutionBlockedError,
    check_execution_allowed,
    redact_secrets,
    resolve_execution_mode,
)
from app.services.registry import AGENT_REGISTRY, execute_registered_agent

WORKFLOW_STATES = (
    "DRAFT",
    "READY",
    "RUNNING",
    "WAITING_APPROVAL",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "BLOCKED",
)

ALLOWED_FSM_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"READY", "RUNNING", "CANCELLED"},
    "READY": {"RUNNING", "BLOCKED", "CANCELLED"},
    "RUNNING": {"WAITING_APPROVAL", "COMPLETED", "FAILED", "BLOCKED", "CANCELLED"},
    "WAITING_APPROVAL": {"RUNNING", "BLOCKED", "CANCELLED"},
    "COMPLETED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
    "BLOCKED": set(),
}


def transition_run_state(run: WorkflowRunRecord, target_state: str) -> None:
    """Enforce explicit 8-state FSM transitions cleanly."""
    clean = target_state.strip().upper()
    if clean not in WORKFLOW_STATES:
        raise ValueError(f"Unknown workflow state '{target_state}'")
    if clean == run.status:
        return
    allowed = ALLOWED_FSM_TRANSITIONS.get(run.status, set())
    if clean not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid workflow state transition: {run.status} -> {clean}",
        )
    run.status = clean
    run.updated_at = datetime.now(UTC)


def serialize_definition(defn: WorkflowDefinitionRecord) -> dict[str, Any]:
    return {
        "workflow_id": defn.id,
        "org_id": defn.org_id,
        "workflow_key": defn.workflow_key,
        "name": defn.name,
        "description": defn.description,
        "version": defn.version,
        "is_active": defn.is_active,
        "trigger_type": defn.trigger_type,
        "schedule_cron": defn.schedule_cron,
        "max_credits_budget": defn.max_credits_budget,
        "timeout_seconds": defn.timeout_seconds,
        "max_retries": defn.max_retries,
        "execution_mode_default": defn.execution_mode_default,
        "steps": defn.steps_json,
        "created_by": defn.created_by,
        "created_at": defn.created_at.isoformat() if defn.created_at else None,
        "updated_at": defn.updated_at.isoformat() if defn.updated_at else None,
    }


def serialize_run(run: WorkflowRunRecord) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "workflow_id": run.workflow_id,
        "org_id": run.org_id,
        "idempotency_key": run.idempotency_key,
        "execution_mode": run.execution_mode,
        "status": run.status,
        "current_step_index": run.current_step_index,
        "total_steps": run.total_steps,
        "credits_budget": run.credits_budget,
        "credits_consumed": run.credits_consumed,
        "approval_id": run.approval_id,
        "input_payload": redact_secrets(run.input_payload),
        "step_results": redact_secrets(run.step_results_json),
        "output_summary": redact_secrets(run.output_summary),
        "failure_reason": run.failure_reason,
        "retry_count": run.retry_count,
        "started_by": run.started_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "cancelled_at": run.cancelled_at.isoformat() if run.cancelled_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def create_workflow_definition(
    db: Session,
    *,
    principal: APIPrincipal,
    name: str,
    steps: list[dict[str, Any]],
    workflow_key: str | None = None,
    description: str = "",
    version: str = "1.0.0",
    trigger_type: str = "manual",
    schedule_cron: str | None = None,
    max_credits_budget: int = 20,
    timeout_seconds: int = 120,
    max_retries: int = 1,
    execution_mode_default: str | None = None,
) -> dict[str, Any]:
    """Validate and persist a multi-step workflow definition for the tenant."""
    if not steps:
        raise HTTPException(status_code=422, detail="Workflow definition requires at least one step")

    normalized_steps: list[dict[str, Any]] = []
    for idx, step in enumerate(steps):
        s_type = str(step.get("step_type", "agent_step")).strip().lower()
        if s_type not in ("agent_step", "approval_gate", "condition"):
            raise HTTPException(status_code=422, detail=f"Unsupported step_type '{s_type}' at step {idx}")
        if s_type == "agent_step":
            ag_id = str(step.get("agent_id", "")).strip()
            if ag_id not in AGENT_REGISTRY:
                raise HTTPException(status_code=422, detail=f"Unknown agent_id '{ag_id}' at step {idx}")
        normalized_steps.append(
            {
                "step_index": idx,
                "step_key": str(step.get("step_key") or f"step_{idx + 1}"),
                "step_type": s_type,
                "agent_id": step.get("agent_id"),
                "action_label": step.get("action_label") or step.get("step_key") or f"Step {idx + 1}",
                "input_template": dict(step.get("input_template") or {}),
                "condition": step.get("condition"),
                "required": bool(step.get("required", True)),
                "approval_action": step.get("approval_action") or "workflow_hitl_gate",
            }
        )

    org_scope = principal.org_id or "__platform__"
    mode = resolve_execution_mode(execution_mode_default)
    defn = WorkflowDefinitionRecord(
        org_id=org_scope,
        workflow_key=(workflow_key or f"wf-{uuid.uuid4().hex[:8]}").strip(),
        name=name.strip(),
        description=description.strip(),
        version=version.strip(),
        is_active=True,
        trigger_type=trigger_type.strip().lower(),
        schedule_cron=schedule_cron,
        max_credits_budget=max(1, int(max_credits_budget)),
        timeout_seconds=max(5, int(timeout_seconds)),
        max_retries=max(0, min(int(max_retries), 5)),
        execution_mode_default=mode,
        steps_json=normalized_steps,
        created_by=principal.subject,
    )
    db.add(defn)
    db.commit()
    return serialize_definition(defn)


def _evaluate_condition(condition: dict[str, Any] | None, context: dict[str, Any]) -> bool:
    """Evaluate simple declarative branch conditions cleanly without arbitrary code eval."""
    if not condition:
        return True
    field = str(condition.get("field", "")).strip()
    val = context.get(field)
    if val is None and "." in field:
        cur: Any = context
        for part in field.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                cur = None
                break
        val = cur
    if "equals" in condition:
        return val == condition["equals"]
    if "not_equals" in condition:
        return val != condition["not_equals"]
    if "truthy" in condition:
        return bool(val) is bool(condition["truthy"])
    if "contains" in condition and isinstance(val, (str, list)):
        return condition["contains"] in val
    return bool(val)


def create_draft_run(
    db: Session,
    *,
    workflow_id: str,
    principal: APIPrincipal,
    input_payload: dict[str, Any] | None = None,
    execution_mode: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Create a WorkflowRunRecord in DRAFT state before preparing/starting."""
    defn = db.get(WorkflowDefinitionRecord, workflow_id)
    if not defn:
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    if principal.org_id:
        enforce_tenant_access(principal, defn.org_id)

    org_scope = principal.org_id or defn.org_id
    if idempotency_key:
        existing = db.query(WorkflowRunRecord).filter_by(org_id=org_scope, idempotency_key=idempotency_key).first()
        if existing:
            return serialize_run(existing)

    mode = resolve_execution_mode(execution_mode or defn.execution_mode_default)
    run = WorkflowRunRecord(
        workflow_id=defn.id,
        org_id=org_scope,
        idempotency_key=idempotency_key,
        execution_mode=mode,
        status="DRAFT",
        current_step_index=0,
        total_steps=len(defn.steps_json),
        credits_budget=defn.max_credits_budget,
        credits_consumed=0,
        input_payload=redact_secrets(input_payload or {}),
        step_results_json=[],
        started_by=principal.subject,
    )
    db.add(run)
    db.commit()
    return serialize_run(run)


def prepare_run_ready(db: Session, *, run_id: str, principal: APIPrincipal) -> dict[str, Any]:
    """Transition DRAFT -> READY after verifying emergency stops and definition active status."""
    run = db.get(WorkflowRunRecord, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if principal.org_id:
        enforce_tenant_access(principal, run.org_id)

    try:
        check_execution_allowed(
            db,
            execution_id=run.id,
            org_id=None if run.org_id == "__platform__" else run.org_id,
            execution_mode=run.execution_mode,
        )
    except ExecutionBlockedError as exc:
        transition_run_state(run, "BLOCKED")
        run.failure_reason = exc.reason
        db.commit()
        raise HTTPException(status_code=403, detail=exc.reason) from exc

    transition_run_state(run, "READY")
    db.commit()
    return serialize_run(run)


def _execute_steps_from_current_index(
    db: Session,
    *,
    defn: WorkflowDefinitionRecord,
    run: WorkflowRunRecord,
    principal: APIPrincipal,
) -> dict[str, Any]:
    """Execute workflow steps sequentially from run.current_step_index respecting budgets, conditions, retries, HITL, and failure semantics."""
    steps = list(defn.steps_json)
    step_results: list[dict[str, Any]] = list(run.step_results_json or [])
    context: dict[str, Any] = dict(run.input_payload or {})
    for sr in step_results:
        if isinstance(sr, dict) and sr.get("step_key") and "result" in sr:
            context[sr["step_key"]] = sr["result"]

    while run.current_step_index < len(steps):
        idx = run.current_step_index
        step = steps[idx]
        s_key = step.get("step_key", f"step_{idx + 1}")
        s_type = step.get("step_type", "agent_step")
        s_required = bool(step.get("required", True))

        # Check timeout
        if run.started_at:
            started_utc = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=UTC)
            elapsed = (datetime.now(UTC) - started_utc).total_seconds()
            if elapsed > defn.timeout_seconds or context.get("__simulate_timeout__"):
                transition_run_state(run, "FAILED")
                run.failure_reason = f"Workflow timeout exceeded ({defn.timeout_seconds}s) at step '{s_key}'"
                run.completed_at = datetime.now(UTC)
                break

        # Re-check 4-level emergency stop before each step
        try:
            check_execution_allowed(
                db,
                execution_id=run.id,
                agent_id=step.get("agent_id"),
                org_id=None if run.org_id == "__platform__" else run.org_id,
                execution_mode=run.execution_mode,
            )
        except ExecutionBlockedError as exc:
            transition_run_state(run, "BLOCKED")
            run.failure_reason = exc.reason
            break

        # Evaluate step condition for conditional branching
        if not _evaluate_condition(step.get("condition"), context):
            step_results.append(
                {
                    "step_index": idx,
                    "step_key": s_key,
                    "step_type": s_type,
                    "status": "SKIPPED_CONDITION",
                    "credits_consumed": 0,
                }
            )
            run.step_results_json = step_results
            run.current_step_index += 1
            db.flush()
            continue

        if s_type == "condition":
            # Condition-only branch step passes when condition holds
            step_results.append(
                {
                    "step_index": idx,
                    "step_key": s_key,
                    "step_type": s_type,
                    "status": "PASSED",
                    "credits_consumed": 0,
                }
            )
            run.step_results_json = step_results
            run.current_step_index += 1
            db.flush()
            continue

        if s_type == "approval_gate":
            task_id = str(uuid.uuid4())
            db.add(
                TaskRecord(
                    id=task_id,
                    correlation_id=run.id,
                    objective=f"Workflow HITL Gate: {defn.name} / {s_key}",
                    status="HUMAN_APPROVAL_REQUIRED",
                )
            )
            db.flush()
            appr_action = str(step.get("approval_action") or "workflow_hitl_gate")
            idem_key = f"wf-appr:{run.id}:{str(s_key)[:80]}:{task_id[:8]}"
            req_hash = hashlib.sha256(f"{run.id}:{s_key}:{task_id}:{appr_action}".encode("utf-8")).hexdigest()
            appr = ApprovalRequest(
                id=str(uuid.uuid4()),
                task_id=task_id,
                action=appr_action,
                detail={
                    "workflow_run_id": run.id,
                    "step_key": str(s_key),
                    "approval_action": appr_action,
                },
                idempotency_key=idem_key,
                request_hash=req_hash,
                requested_by=principal.subject,
                status="PENDING",
                decision_note=f"Approval gate for workflow run {run.id} step {s_key}",
            )
            db.add(appr)
            db.flush()
            run.approval_id = appr.id
            step_results.append(
                {
                    "step_index": idx,
                    "step_key": s_key,
                    "step_type": "approval_gate",
                    "status": "WAITING_APPROVAL",
                    "approval_id": appr.id,
                    "credits_consumed": 0,
                }
            )
            run.step_results_json = step_results
            transition_run_state(run, "WAITING_APPROVAL")
            db.commit()
            return serialize_run(run)

        # Agent step
        agent_id = str(step.get("agent_id"))
        ag = AGENT_REGISTRY.get(agent_id)
        step_cost = ag.credit_cost if (ag and principal.org_id) else 0
        if run.credits_consumed + step_cost > run.credits_budget:
            transition_run_state(run, "BLOCKED")
            run.failure_reason = (
                f"Workflow credit budget exceeded before step '{s_key}' "
                f"({run.credits_consumed + step_cost} > budget {run.credits_budget})"
            )
            break

        merged_input = {**dict(step.get("input_template") or {}), **{k: v for k, v in context.items() if isinstance(k, str)}}
        # Support optional test/step failure hook specifically scoped to a step_key
        if isinstance(context.get("fail_step_key"), str) and context["fail_step_key"] == s_key:
            merged_input["__force_failure__"] = True
        else:
            merged_input.pop("__force_failure__", None)

        attempts = 0
        max_attempts = 1 + int(defn.max_retries)
        last_exc: Exception | None = None
        agent_res: dict[str, Any] | None = None
        while attempts < max_attempts:
            attempts += 1
            try:
                agent_res = execute_registered_agent(
                    db,
                    agent_id=agent_id,
                    principal=principal,
                    input_payload=merged_input,
                    execution_mode=run.execution_mode,
                    idempotency_key=f"wf:{run.id}:{idx}:{s_key}:try{attempts}",
                    workflow_id=run.workflow_id,
                )
                last_exc = None
                break
            except HTTPException as exc:
                last_exc = exc
                if attempts >= max_attempts:
                    break
            except Exception as exc:
                last_exc = exc
                if attempts >= max_attempts:
                    break

        run.retry_count += max(0, attempts - 1)

        if last_exc is not None:
            detail_msg = getattr(last_exc, "detail", str(last_exc))
            reason_str = detail_msg.get("message", str(detail_msg)) if isinstance(detail_msg, dict) else str(detail_msg)
            status_code = getattr(last_exc, "status_code", 500)
            target_fail_state = "BLOCKED" if status_code in (402, 403) else "FAILED"
            step_results.append(
                {
                    "step_index": idx,
                    "step_key": s_key,
                    "step_type": "agent_step",
                    "agent_id": agent_id,
                    "status": target_fail_state,
                    "error": reason_str,
                    "attempts": attempts,
                    "credits_consumed": 0,
                }
            )
            run.step_results_json = step_results
            if s_required:
                transition_run_state(run, target_fail_state)
                run.failure_reason = f"Required step '{s_key}' {target_fail_state.lower()}: {reason_str}"
                run.completed_at = datetime.now(UTC)
                break
            else:
                run.current_step_index += 1
                db.flush()
                continue

        # Step succeeded
        consumed = int(agent_res.get("credits_consumed", 0)) if agent_res else 0
        run.credits_consumed += consumed
        step_output = agent_res.get("result", {}) if agent_res else {}
        context[s_key] = step_output
        step_results.append(
            {
                "step_index": idx,
                "step_key": s_key,
                "step_type": "agent_step",
                "agent_id": agent_id,
                "execution_id": agent_res.get("execution_id") if agent_res else None,
                "output_origin": agent_res.get("output_origin") if agent_res else "SIMULATED_SYNTHETIC",
                "status": "COMPLETED",
                "attempts": attempts,
                "credits_consumed": consumed,
                "result": step_output,
            }
        )
        run.step_results_json = step_results
        run.current_step_index += 1
        db.flush()

    if run.status == "RUNNING" and run.current_step_index >= len(steps):
        # Double-check invariant: never mark COMPLETED if any required step failed or blocked
        has_bad = any(
            sr.get("status") in ("FAILED", "BLOCKED")
            for sr in step_results
            if isinstance(sr, dict)
        )
        if has_bad:
            transition_run_state(run, "FAILED")
            run.failure_reason = run.failure_reason or "One or more workflow steps failed"
        else:
            transition_run_state(run, "COMPLETED")
        run.completed_at = datetime.now(UTC)
        run.output_summary = {
            "completed_steps": len(step_results),
            "credits_consumed": run.credits_consumed,
            "final_context_keys": [sr.get("step_key") for sr in step_results if isinstance(sr, dict)],
        }

    # Record workflow summary evidence record (18 fields)
    record_execution_evidence(
        db,
        execution_id=f"wfrun-{run.id[:20]}",
        tenant_id=run.org_id,
        workflow_id=run.workflow_id,
        agent_id="workflow_orchestrator",
        connector_id="project_api",
        execution_mode=run.execution_mode,
        input_payload=run.input_payload,
        output_payload=run.output_summary or {"status": run.status, "step_results": len(step_results)},
        provider_request_id=f"wf-run-{run.id}",
        fallback_used=(run.execution_mode == "SIMULATION"),
        approval_id=run.approval_id,
        status=run.status if run.status in ("COMPLETED", "FAILED", "BLOCKED", "WAITING_APPROVAL", "CANCELLED") else "COMPLETED",
        failure_reason=run.failure_reason,
        credits_consumed=run.credits_consumed,
        started_at=run.started_at or run.created_at,
        completed_at=run.completed_at,
        version=defn.version,
    )
    db.commit()
    return serialize_run(run)


def start_workflow_run(
    db: Session,
    *,
    workflow_id: str,
    principal: APIPrincipal,
    input_payload: dict[str, Any] | None = None,
    execution_mode: str | None = None,
    idempotency_key: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Start (or idempotently replay) a persisted workflow run through READY -> RUNNING."""
    defn = db.get(WorkflowDefinitionRecord, workflow_id)
    if not defn:
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    if principal.org_id:
        enforce_tenant_access(principal, defn.org_id)

    org_scope = principal.org_id or defn.org_id
    if idempotency_key:
        existing = db.query(WorkflowRunRecord).filter_by(org_id=org_scope, idempotency_key=idempotency_key).first()
        if existing:
            return serialize_run(existing)

    if run_id:
        run = db.get(WorkflowRunRecord, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Workflow run not found")
        if run.workflow_id != workflow_id:
            raise HTTPException(status_code=422, detail="run_id does not belong to workflow_id")
    else:
        mode = resolve_execution_mode(execution_mode or defn.execution_mode_default)
        run = WorkflowRunRecord(
            workflow_id=defn.id,
            org_id=org_scope,
            idempotency_key=idempotency_key,
            execution_mode=mode,
            status="DRAFT",
            current_step_index=0,
            total_steps=len(defn.steps_json),
            credits_budget=defn.max_credits_budget,
            credits_consumed=0,
            input_payload=redact_secrets(input_payload or {}),
            step_results_json=[],
            started_by=principal.subject,
        )
        db.add(run)
        db.flush()

    if run.status == "DRAFT":
        transition_run_state(run, "READY")
    transition_run_state(run, "RUNNING")
    if run.started_at is None:
        run.started_at = datetime.now(UTC)
    db.flush()

    return _execute_steps_from_current_index(db, defn=defn, run=run, principal=principal)


def resume_workflow_run(
    db: Session,
    *,
    run_id: str,
    principal: APIPrincipal,
) -> dict[str, Any]:
    """Resume a workflow paused in WAITING_APPROVAL only after its HITL ApprovalRequest is APPROVED."""
    run = db.get(WorkflowRunRecord, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if principal.org_id:
        enforce_tenant_access(principal, run.org_id)
    if run.status != "WAITING_APPROVAL":
        raise HTTPException(status_code=409, detail=f"Workflow run is in state '{run.status}', not WAITING_APPROVAL")

    appr = db.get(ApprovalRequest, run.approval_id) if run.approval_id else None
    if not appr:
        transition_run_state(run, "BLOCKED")
        run.failure_reason = "Missing HITL approval record for WAITING_APPROVAL run"
        db.commit()
        raise HTTPException(status_code=409, detail=run.failure_reason)

    if appr.status == "PENDING":
        raise HTTPException(status_code=409, detail=f"Approval '{appr.id}' is still PENDING; cannot resume")

    if appr.status != "APPROVED":
        transition_run_state(run, "BLOCKED")
        run.failure_reason = f"HITL approval '{appr.id}' was {appr.status}"
        run.completed_at = datetime.now(UTC)
        step_results = list(run.step_results_json or [])
        if step_results:
            step_results[-1]["status"] = "REJECTED"
            run.step_results_json = step_results
        db.commit()
        return serialize_run(run)

    # Mark gate approved and advance past approval gate step
    step_results = list(run.step_results_json or [])
    if step_results and step_results[-1].get("step_type") == "approval_gate":
        step_results[-1]["status"] = "APPROVED"
        step_results[-1]["decided_by"] = appr.decided_by
        run.step_results_json = step_results
    run.current_step_index += 1
    transition_run_state(run, "RUNNING")
    db.flush()

    defn = db.get(WorkflowDefinitionRecord, run.workflow_id)
    if not defn:
        raise HTTPException(status_code=404, detail="Workflow definition missing")
    return _execute_steps_from_current_index(db, defn=defn, run=run, principal=principal)


def cancel_workflow_run(
    db: Session,
    *,
    run_id: str,
    principal: APIPrincipal,
    reason: str = "Cancelled by operator",
) -> dict[str, Any]:
    """Cancel a DRAFT, READY, RUNNING, or WAITING_APPROVAL workflow cleanly."""
    run = db.get(WorkflowRunRecord, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if principal.org_id:
        enforce_tenant_access(principal, run.org_id)

    transition_run_state(run, "CANCELLED")
    now = datetime.now(UTC)
    run.cancelled_at = now
    run.completed_at = now
    run.failure_reason = reason
    db.commit()
    return serialize_run(run)
