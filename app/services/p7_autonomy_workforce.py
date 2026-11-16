"""P7 Controlled Autonomous Workforce service layer.

Implements:
- Cycle-, depth-, and credit-budget-validated Multi-Agent Delegation DAG planning & execution
- Tenant-isolated persistent memory with provenance, secret redaction, TTL expiry, and DPDP purge
- 5-Level Autonomy Governance (LEVEL_0_OBSERVE .. LEVEL_4_SUPERVISED_ORCHESTRATION; never unrestricted)
- Continuous agent evaluation suite with automatic autonomy pause on quality/safety threshold breach
"""

from __future__ import annotations

import threading
from time import monotonic as _monotonic
import uuid
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalRequest,
    ExecutionEvidenceRecord,
    OrganizationRecord,
    P7AgentEvalRunRecord,
    P7AutonomyPolicyRecord,
    P7DelegationPlanRecord,
    P7TenantMemoryRecord,
)
from app.security.auth import APIPrincipal
from app.security.trust_chain import seal_task_to_block
from app.services.execution_guard import (
    ExecutionBlockedError,
    check_execution_allowed,
    is_external_side_effect_blocked,
    redact_secrets,
    resolve_execution_mode,
)
from app.services.registry import AGENT_REGISTRY, execute_registered_agent

AUTONOMY_LEVELS: tuple[str, ...] = (
    "LEVEL_0_OBSERVE",
    "LEVEL_1_ASSIST",
    "LEVEL_2_APPROVAL_GATED",
    "LEVEL_3_BOUNDED_AUTONOMY",
    "LEVEL_4_SUPERVISED_ORCHESTRATION",
)

PROHIBITED_UNRESTRICTED_ALIASES: tuple[str, ...] = (
    "UNRESTRICTED",
    "LEVEL_5",
    "LEVEL_5_UNRESTRICTED",
    "FULL_AUTONOMOUS",
    "NO_HITL",
    "BYPASS_HITL",
)

MEMORY_SOURCE_TYPES: tuple[str, ...] = (
    "USER_CONFIG",
    "AGENT_RUN",
    "DOC_EVIDENCE",
    "CUSTOMER_FEEDBACK",
)


def _normalize_mode(requested_mode: str | None) -> str:
    raw = (requested_mode or "SIMULATION").strip().upper()
    canonical = "PRODUCTION" if raw == "LIVE" else raw
    if canonical not in ("SIMULATION", "SANDBOX", "PRODUCTION"):
        raise ValueError(f"Unsupported execution_mode '{requested_mode}'")
    resolved = resolve_execution_mode(canonical)
    if resolved == "PRODUCTION" and is_external_side_effect_blocked():
        raise PermissionError("PRODUCTION autonomous DAG execution blocked while sandbox/test guard is active")
    return resolved


def _ensure_active_org(db: Session, org_id: str | None) -> None:
    if org_id is None:
        return
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")
    if not org.is_active:
        raise PermissionError("Organization account is inactive or suspended")


def _verify_approved_request(db: Session, *, approval_id: str | None, org_id: str | None) -> ApprovalRequest:
    if not approval_id or not approval_id.strip():
        raise PermissionError("Verified approval_id is required for this autonomy level")
    appr = db.get(ApprovalRequest, approval_id.strip())
    if not appr:
        raise PermissionError(f"Approval request '{approval_id}' not found")
    if str(appr.status or "").upper() != "APPROVED":
        raise PermissionError(f"Approval request '{approval_id}' is in '{appr.status}' state; APPROVED required")
    detail_org = (appr.detail or {}).get("org_id") if isinstance(appr.detail, dict) else None
    if org_id is not None and detail_org != org_id:
        raise PermissionError("Approval request does not belong to target organization")
    return appr


def validate_and_order_dag(
    nodes: list[dict[str, Any]],
    *,
    max_depth: int = 4,
    credit_budget: int = 20,
    execution_budget_limit: int = 100,
) -> dict[str, Any]:
    """Validate delegation DAG for acyclicity, valid agents, depth limit, and three-control budgets."""
    if not nodes:
        raise ValueError("Delegation DAG must contain at least one node")
    if max_depth < 1 or max_depth > 12:
        raise ValueError("max_depth must be between 1 and 12")
    if credit_budget < 0:
        raise ValueError("credit_budget must be non-negative")
    if execution_budget_limit < 1:
        raise ValueError("execution_budget_limit must be positive")

    node_map: dict[str, dict[str, Any]] = {}
    estimated_credit_cost = 0
    estimated_execution_units = 0
    for idx, raw in enumerate(nodes):
        node_id = str(raw.get("node_id") or "").strip()
        agent_id = str(raw.get("agent_id") or "").strip()
        if not node_id:
            raise ValueError(f"Node at index {idx} is missing node_id")
        if node_id in node_map:
            raise ValueError(f"Duplicate node_id '{node_id}' in delegation DAG")
        if agent_id not in AGENT_REGISTRY:
            raise ValueError(f"Unknown agent_id '{agent_id}' at node '{node_id}'; must exist in AGENT_REGISTRY")

        deps = [str(d).strip() for d in (raw.get("depends_on") or []) if str(d).strip()]
        if node_id in deps:
            raise ValueError(f"Node '{node_id}' cannot depend on itself (self-cycle)")

        agent_spec = AGENT_REGISTRY[agent_id]
        # Never invent or convert non-billable credit_cost=0 agents into billed credits (Decision 2).
        step_credit_cost = int(agent_spec.credit_cost or 0)
        step_exec_units = max(1, int(raw.get("execution_budget_units") or 1))
        estimated_credit_cost += step_credit_cost
        estimated_execution_units += step_exec_units
        node_map[node_id] = {
            "node_id": node_id,
            "agent_id": agent_id,
            "depends_on": deps,
            "credit_cost": step_credit_cost,
            "execution_budget_units": step_exec_units,
            "reversible": bool(raw.get("reversible", True)),
            "input_payload": dict(raw.get("input_payload") or {}),
        }

    # Verify dependency targets exist and build adjacency/in-degree maps
    indegree: dict[str, int] = {nid: 0 for nid in node_map}
    children: dict[str, list[str]] = {nid: [] for nid in node_map}
    for nid, item in node_map.items():
        for dep in item["depends_on"]:
            if dep not in node_map:
                raise ValueError(f"Node '{nid}' depends on unknown node '{dep}'")
            indegree[nid] += 1
            children[dep].append(nid)

    # Kahn topological sort + longest-path depth computation
    queue: deque[str] = deque(nid for nid, deg in indegree.items() if deg == 0)
    depth_by_node: dict[str, int] = {nid: 1 for nid in queue}
    ordered_nodes: list[dict[str, Any]] = []

    while queue:
        cur = queue.popleft()
        ordered_nodes.append(node_map[cur])
        for nxt in children[cur]:
            depth_by_node[nxt] = max(depth_by_node.get(nxt, 1), depth_by_node[cur] + 1)
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(ordered_nodes) != len(node_map):
        raise ValueError("Delegation graph contains a cycle and cannot form a valid DAG")

    computed_depth = max(depth_by_node.values()) if depth_by_node else 1
    if computed_depth > max_depth:
        raise ValueError(f"Delegation DAG depth {computed_depth} exceeds max_depth limit ({max_depth})")
    if estimated_credit_cost > credit_budget:
        raise ValueError(f"Delegation DAG estimated cost {estimated_credit_cost} exceeds credit_budget ({credit_budget})")
    if estimated_execution_units > execution_budget_limit:
        raise ValueError(
            f"Delegation DAG execution units {estimated_execution_units} exceeds execution_budget_limit ({execution_budget_limit})"
        )

    return {
        "ordered_nodes": ordered_nodes,
        "computed_depth": computed_depth,
        "estimated_cost": estimated_credit_cost,
        "estimated_execution_units": estimated_execution_units,
    }


_ACTIVE_PLAN_LOCK = threading.Lock()
_ACTIVE_PLAN_CANCEL_EVENTS: dict[str, threading.Event] = {}


def _serialize_plan(rec: P7DelegationPlanRecord) -> dict[str, Any]:
    nodes = list(rec.nodes_json or [])
    results = list(rec.execution_results_json or [])
    estimated_credits = 0
    estimated_execution_units = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        spec = AGENT_REGISTRY.get(str(node.get("agent_id") or ""))
        estimated_credits += int(getattr(spec, "credit_cost", 0) or 0) if spec else 0
        estimated_execution_units += max(1, int(node.get("execution_budget_units") or 1))

    if results:
        est_provider_cost = round(
            sum(
                float(
                    r.get("estimated_provider_cost_inr")
                    if r.get("estimated_provider_cost_inr") is not None
                    else (r.get("provider_cost_inr") or 0.0)
                )
                for r in results
                if isinstance(r, dict)
            ),
            6,
        )
        dict_results = [r for r in results if isinstance(r, dict)]
        if dict_results and all(r.get("actual_provider_cost_inr") is not None for r in dict_results):
            actual_provider_cost: float | None = round(
                sum(float(r["actual_provider_cost_inr"]) for r in dict_results),
                6,
            )
        else:
            actual_provider_cost = None
        sources = {str(r.get("provider_cost_source")) for r in dict_results if r.get("provider_cost_source")}
        if len(sources) == 1:
            provider_cost_source = next(iter(sources))
        elif "TOKEN_USAGE_ESTIMATE" in sources and (
            sources - {"TOKEN_USAGE_ESTIMATE"}
        ):
            provider_cost_source = "MIXED_ESTIMATE_AND_ACTUAL"
        elif sources:
            provider_cost_source = "+".join(sorted(sources))
        else:
            provider_cost_source = (
                "TOKEN_USAGE_ESTIMATE" if float(getattr(rec, "provider_cost_inr", 0.0) or 0.0) > 0 else "LOCAL_NO_LLM_CALL"
            )
    else:
        est_provider_cost = 0.0
        actual_provider_cost = None
        provider_cost_source = "NOT_EXECUTED"

    return {
        "plan_id": rec.id,
        "org_id": rec.org_id,
        "name": rec.name,
        "objective": rec.objective,
        "nodes": nodes,
        "max_depth": int(rec.max_depth),
        "computed_depth": int(rec.computed_depth),
        "credit_budget": int(rec.credit_budget),
        "estimated_credits": estimated_credits,
        "credits_consumed": int(rec.credits_consumed or 0),
        "execution_budget_limit": int(getattr(rec, "execution_budget_limit", 100) or 100),
        "estimated_execution_units": estimated_execution_units,
        "execution_budget_units_used": int(getattr(rec, "execution_budget_units_used", 0) or 0),
        "provider_cost_inr": float(getattr(rec, "provider_cost_inr", 0.0) or 0.0),
        "estimated_provider_cost_inr": est_provider_cost,
        "actual_provider_cost_inr": actual_provider_cost,
        "provider_cost_source": provider_cost_source,
        "timeout_seconds": int(getattr(rec, "timeout_seconds", 30) or 30),
        "node_states": dict(getattr(rec, "node_states_json", None) or {}),
        "status": rec.status,
        "execution_mode": rec.execution_mode,
        "execution_results": results,
        "approval_id": rec.approval_id,
        "created_by": rec.created_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def create_delegation_plan(
    db: Session,
    *,
    org_id: str | None,
    name: str,
    objective: str,
    nodes: list[dict[str, Any]],
    max_depth: int = 4,
    credit_budget: int = 20,
    execution_budget_limit: int = 100,
    timeout_seconds: int = 30,
    approval_id: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Validate and persist a cycle-, depth-, and budget-checked multi-agent delegation DAG."""
    _ensure_active_org(db, org_id)
    if timeout_seconds < 1 or timeout_seconds > 300:
        raise ValueError("timeout_seconds must be between 1 and 300")
    if approval_id is not None:
        _verify_approved_request(db, approval_id=approval_id, org_id=org_id)
    validated = validate_and_order_dag(
        nodes,
        max_depth=max_depth,
        credit_budget=credit_budget,
        execution_budget_limit=execution_budget_limit,
    )
    now = datetime.now(UTC)
    rec = P7DelegationPlanRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=name.strip(),
        objective=objective.strip(),
        nodes_json=validated["ordered_nodes"],
        max_depth=max_depth,
        computed_depth=validated["computed_depth"],
        credit_budget=credit_budget,
        credits_consumed=0,
        execution_budget_limit=int(execution_budget_limit),
        execution_budget_units_used=0,
        provider_cost_inr=0.0,
        timeout_seconds=int(timeout_seconds),
        node_states_json={},
        status="PLANNED",
        execution_mode="SIMULATION",
        execution_results_json=[],
        approval_id=approval_id.strip() if approval_id else None,
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_plan(rec)


def _resolve_policies_for_scope(db: Session, *, org_id: str | None, agent_id: str) -> list[P7AutonomyPolicyRecord]:
    policies: list[P7AutonomyPolicyRecord] = []
    if org_id:
        tenant_pol = db.query(P7AutonomyPolicyRecord).filter_by(org_id=org_id, agent_id=agent_id).first()
        if tenant_pol is not None:
            policies.append(tenant_pol)
    platform_pol = db.query(P7AutonomyPolicyRecord).filter_by(org_id=None, agent_id=agent_id).first()
    if platform_pol is not None:
        policies.append(platform_pol)
    return policies


def _is_agent_paused_for_scope(db: Session, *, org_id: str | None, agent_id: str) -> tuple[bool, str | None]:
    for pol in _resolve_policies_for_scope(db, org_id=org_id, agent_id=agent_id):
        if pol.is_paused:
            return True, pol.pause_reason or "Agent autonomy paused by governance/eval breach"
    return False, None


def _check_daily_agent_caps(
    db: Session,
    *,
    org_id: str | None,
    agent_id: str,
    policy: P7AutonomyPolicyRecord,
    next_credits: int,
    next_exec_units: int,
) -> None:
    tenant_key = org_id or "__platform__"
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(ExecutionEvidenceRecord)
        .filter(
            ExecutionEvidenceRecord.tenant_id == tenant_key,
            ExecutionEvidenceRecord.agent_id == agent_id,
            ExecutionEvidenceRecord.started_at >= day_start,
            ExecutionEvidenceRecord.status.in_(("COMPLETED", "RUNNING")),
        )
        .all()
    )
    used_credits_today = sum(int(r.credits_consumed or 0) for r in rows)
    used_units_today = sum(max(1, int(getattr(r, "execution_budget_units", 0) or 1)) for r in rows)
    if used_credits_today + next_credits > int(policy.max_daily_budget_credits):
        raise PermissionError(
            f"Daily credit cap ({policy.max_daily_budget_credits}) exhausted for agent '{agent_id}'"
        )
    max_units = int(getattr(policy, "max_daily_execution_units", 500) or 500)
    if used_units_today + next_exec_units > max_units:
        raise PermissionError(
            f"Daily execution unit cap ({max_units}) exhausted for agent '{agent_id}'"
        )


def _enforce_node_policy_and_controls(
    db: Session,
    *,
    org_id: str | None,
    agent_id: str,
    mode: str,
    approval_id: str | None,
    next_credits: int,
    next_exec_units: int,
) -> str | None:
    policies = _resolve_policies_for_scope(db, org_id=org_id, agent_id=agent_id)
    verified_approval_id: str | None = None
    for pol in policies:
        if pol.is_paused:
            raise PermissionError(
                f"DAG blocked: agent '{agent_id}' is paused ({pol.pause_reason or 'governance pause'})"
            )
        lvl = str(pol.autonomy_level or "LEVEL_2_APPROVAL_GATED").upper()
        if lvl == "LEVEL_0_OBSERVE":
            raise PermissionError(
                f"DAG blocked: agent '{agent_id}' policy LEVEL_0_OBSERVE prohibits autonomous execution"
            )
        if lvl in ("LEVEL_1_ASSIST", "LEVEL_2_APPROVAL_GATED"):
            eff_appr = approval_id or pol.approval_id
            appr = _verify_approved_request(db, approval_id=eff_appr, org_id=org_id)
            verified_approval_id = appr.id
        elif pol.requires_hitl_for_external and mode in ("SANDBOX", "PRODUCTION"):
            spec = AGENT_REGISTRY.get(agent_id)
            if spec and spec.default_connector_id not in ("project_api", None):
                eff_appr = approval_id or pol.approval_id
                appr = _verify_approved_request(db, approval_id=eff_appr, org_id=org_id)
                verified_approval_id = appr.id
        _check_daily_agent_caps(
            db,
            org_id=org_id,
            agent_id=agent_id,
            policy=pol,
            next_credits=next_credits,
            next_exec_units=next_exec_units,
        )
    return verified_approval_id


def execute_delegation_plan(
    db: Session,
    *,
    plan_id: str,
    org_id: str | None,
    principal: APIPrincipal,
    execution_mode: str = "SIMULATION",
    approval_id: str | None = None,
    timeout_seconds: int | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Execute or recover a validated P7 delegation DAG through AGENT_REGISTRY with governance, budgets, memory, and safe rollback."""
    rec = db.get(P7DelegationPlanRecord, plan_id)
    if not rec or (org_id is not None and rec.org_id != org_id):
        raise ValueError(f"Delegation plan '{plan_id}' not found")
    _ensure_active_org(db, rec.org_id)

    with _ACTIVE_PLAN_LOCK:
        if rec.status == "RUNNING" and rec.id in _ACTIVE_PLAN_CANCEL_EVENTS:
            raise ValueError("Delegation plan is currently running; cancel it before retrying or recovering")
    if rec.status == "CANCELLED" and not resume:
        raise PermissionError("Delegation plan was cancelled; recover explicitly or create a new plan")

    mode = _normalize_mode(execution_mode)
    nodes = list(rec.nodes_json or [])
    eff_timeout = int(timeout_seconds if timeout_seconds is not None else (getattr(rec, "timeout_seconds", 30) or 30))
    if eff_timeout < 1 or eff_timeout > 300:
        raise ValueError("timeout_seconds must be between 1 and 300")
    eff_approval_id = (approval_id or rec.approval_id or "").strip() or None
    if eff_approval_id:
        _verify_approved_request(db, approval_id=eff_approval_id, org_id=rec.org_id)

    prev_states = dict(getattr(rec, "node_states_json", None) or {}) if resume else {}
    prev_results = list(getattr(rec, "execution_results_json", None) or []) if resume else []
    prev_res_by_id = {
        str(r.get("node_id")): dict(r)
        for r in prev_results
        if isinstance(r, dict) and r.get("node_id")
    }
    preserved_ids = {
        n["node_id"]
        for n in nodes
        if resume and (prev_states.get(n["node_id"]) or {}).get("status") == "COMPLETED"
    }

    # Pre-flight governance check for every non-preserved node before executing
    for node in nodes:
        if node["node_id"] in preserved_ids:
            continue
        agent_spec = AGENT_REGISTRY.get(node["agent_id"])
        step_credits = int(agent_spec.credit_cost or 0) if agent_spec else 0
        step_units = max(1, int(node.get("execution_budget_units") or 1))
        _enforce_node_policy_and_controls(
            db,
            org_id=rec.org_id,
            agent_id=node["agent_id"],
            mode=mode,
            approval_id=eff_approval_id,
            next_credits=step_credits,
            next_exec_units=step_units,
        )
        try:
            check_execution_allowed(db, agent_id=node["agent_id"], org_id=rec.org_id, execution_mode=mode)
        except ExecutionBlockedError as exc:
            raise PermissionError(exc.reason) from exc

    active_memories = (
        [
            {"namespace": m["namespace"], "memory_key": m["memory_key"], "content": m["content"]}
            for m in read_tenant_memories(db, org_id=rec.org_id)[:10]
        ]
        if rec.org_id
        else []
    )

    node_states: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    completed_outputs: dict[str, Any] = {}
    consumed_credits = 0
    consumed_exec_units = 0
    total_provider_cost = 0.0

    for n in nodes:
        nid_k = n["node_id"]
        if nid_k in preserved_ids:
            st = dict(prev_states[nid_k])
            node_states[nid_k] = st
            exec_id_prev = st.get("execution_id")
            if exec_id_prev:
                ev_q = db.query(ExecutionEvidenceRecord).filter(
                    ExecutionEvidenceRecord.execution_id == exec_id_prev
                )
                if rec.org_id:
                    ev_q = ev_q.filter(ExecutionEvidenceRecord.tenant_id == rec.org_id)
                ev_rec = ev_q.first()
                meta_prev = dict(ev_rec.metadata_json or {}) if ev_rec else {}
                raw_prev_out = meta_prev.get("output_preview")
                if isinstance(raw_prev_out, dict):
                    completed_outputs[nid_k] = dict(raw_prev_out)
                elif raw_prev_out is not None:
                    completed_outputs[nid_k] = {"value": raw_prev_out}
                else:
                    completed_outputs[nid_k] = {}
            else:
                completed_outputs[nid_k] = {}
            prev_r = prev_res_by_id.get(nid_k)
            if prev_r:
                prev_r["preserved_on_recovery"] = True
                results.append(prev_r)
                consumed_credits += int(prev_r.get("credits_consumed") or 0)
                consumed_exec_units += int(prev_r.get("execution_budget_units") or 0)
                total_provider_cost = round(total_provider_cost + float(prev_r.get("provider_cost_inr") or 0.0), 6)
        else:
            node_states[nid_k] = {
                "status": "PENDING",
                "execution_id": None,
                "reversible": bool(n.get("reversible", True)),
            }

    cancel_event = threading.Event()
    with _ACTIVE_PLAN_LOCK:
        _ACTIVE_PLAN_CANCEL_EVENTS[rec.id] = cancel_event

    rec.execution_mode = mode
    rec.status = "RUNNING"
    rec.node_states_json = dict(node_states)
    rec.execution_results_json = list(results)
    rec.credits_consumed = consumed_credits
    rec.execution_budget_units_used = consumed_exec_units
    rec.provider_cost_inr = total_provider_cost
    if eff_approval_id:
        rec.approval_id = eff_approval_id
    rec.updated_at = datetime.now(UTC)
    db.commit()

    deadline = _monotonic() + float(eff_timeout)

    def _compensate_completed(failed_nid: str, failure_status: str, reason: str) -> None:
        node_states[failed_nid]["status"] = failure_status
        node_states[failed_nid]["failure_reason"] = reason
        for prev in results:
            pid = prev["node_id"]
            if node_states.get(pid, {}).get("reversible", True):
                node_states[pid]["status"] = "COMPENSATED"
                node_states[pid]["compensation_action"] = "reversible_state_compensated_safely"
                prev["compensation_status"] = "COMPENSATED"
            else:
                node_states[pid]["status"] = "COMPLETED"
                node_states[pid]["compensation_action"] = "skipped_irreversible_side_effect"
                prev["compensation_status"] = "SKIPPED_IRREVERSIBLE"
        for rem_node in nodes:
            rnid = rem_node["node_id"]
            if rnid != failed_nid and (node_states.get(rnid) or {}).get("status") == "PENDING":
                node_states[rnid]["status"] = "CANCELLED"
                node_states[rnid]["failure_reason"] = (
                    f"Cancelled after node '{failed_nid}' ended with {failure_status}"
                )
        rec.status = failure_status if failure_status in ("TIMED_OUT", "BLOCKED", "CANCELLED") else "FAILED"
        rec.credits_consumed = consumed_credits
        rec.execution_budget_units_used = consumed_exec_units
        rec.provider_cost_inr = round(total_provider_cost, 6)
        rec.node_states_json = dict(node_states)
        rec.execution_results_json = list(results)
        rec.updated_at = datetime.now(UTC)
        db.commit()

    try:
        for node in nodes:
            nid = node["node_id"]
            if nid in preserved_ids:
                continue
            agent_id = node["agent_id"]
            agent_spec = AGENT_REGISTRY.get(agent_id)
            step_credits = int(agent_spec.credit_cost or 0) if agent_spec else 0
            step_exec_units = max(1, int(node.get("execution_budget_units") or 1))

            if cancel_event.is_set():
                _compensate_completed(nid, "CANCELLED", "Delegation plan cancelled by operator")
                raise PermissionError(f"Delegation execution cancelled at node '{nid}'")

            remaining_seconds = deadline - _monotonic()
            if remaining_seconds <= 0:
                _compensate_completed(nid, "TIMED_OUT", f"DAG execution exceeded timeout_seconds={eff_timeout}s")
                raise TimeoutError(f"Delegation execution timed out after {eff_timeout}s at node '{nid}'")

            if consumed_credits + step_credits > rec.credit_budget:
                _compensate_completed(nid, "BLOCKED", "Runtime credit_budget exhausted")
                raise PermissionError("Delegation execution halted: runtime credit_budget exhausted")

            exec_limit = int(getattr(rec, "execution_budget_limit", 100) or 100)
            if consumed_exec_units + step_exec_units > exec_limit:
                _compensate_completed(nid, "BLOCKED", "Runtime execution_budget_limit exhausted")
                raise PermissionError("Delegation execution halted: runtime execution_budget_limit exhausted")

            payload = dict(node.get("input_payload") or {})
            if payload.get("org_id") is not None:
                raw_org = str(payload.get("org_id")).strip()
                if raw_org:
                    if rec.org_id and raw_org != rec.org_id:
                        _compensate_completed(nid, "BLOCKED", "Cross-tenant input_payload org_id spoofing blocked")
                        raise PermissionError("Cross-tenant input_payload['org_id'] spoofing blocked")
                    if not principal.is_platform_operator and raw_org != principal.org_id:
                        _compensate_completed(nid, "BLOCKED", "Cross-tenant input_payload org_id spoofing blocked")
                        raise PermissionError("Cross-tenant input_payload['org_id'] spoofing blocked")

            if rec.org_id:
                payload["org_id"] = rec.org_id
            dep_outputs = {dep: completed_outputs[dep] for dep in (node.get("depends_on") or []) if dep in completed_outputs}
            if dep_outputs and "dependency_outputs" not in payload:
                payload["dependency_outputs"] = dep_outputs
            if active_memories and "tenant_memories" not in payload:
                payload["tenant_memories"] = active_memories

            try:
                _enforce_node_policy_and_controls(
                    db,
                    org_id=rec.org_id,
                    agent_id=agent_id,
                    mode=mode,
                    approval_id=eff_approval_id,
                    next_credits=step_credits,
                    next_exec_units=step_exec_units,
                )
                check_execution_allowed(db, agent_id=agent_id, org_id=rec.org_id, execution_mode=mode)
            except ExecutionBlockedError as exc:
                _compensate_completed(nid, "BLOCKED", exc.reason)
                raise PermissionError(exc.reason) from exc
            except PermissionError as exc:
                _compensate_completed(nid, "BLOCKED", str(exc))
                raise

            node_states[nid]["status"] = "RUNNING"
            rec.node_states_json = dict(node_states)
            rec.updated_at = datetime.now(UTC)
            db.commit()

            try:
                exec_res = execute_registered_agent(
                    db,
                    agent_id=agent_id,
                    principal=principal,
                    input_payload=payload,
                    execution_mode=mode,
                    idempotency_key=f"p7dag:{rec.id}:{nid}:{uuid.uuid4().hex[:8]}",
                    workflow_id=rec.id,
                    timeout_seconds=max(0.05, remaining_seconds),
                    cancel_event=cancel_event,
                )
            except TimeoutError as exc:
                timed_ev = (
                    db.query(ExecutionEvidenceRecord)
                    .filter(
                        ExecutionEvidenceRecord.workflow_id == rec.id,
                        ExecutionEvidenceRecord.agent_id == agent_id,
                    )
                    .order_by(ExecutionEvidenceRecord.started_at.desc())
                    .first()
                )
                if timed_ev is not None:
                    node_states[nid]["execution_id"] = timed_ev.execution_id
                _compensate_completed(nid, "TIMED_OUT", str(exc))
                raise
            except HTTPException as exc:
                err_status = "BLOCKED" if exc.status_code in (402, 403) else "FAILED"
                _compensate_completed(nid, err_status, str(exc.detail))
                if exc.status_code in (402, 403):
                    raise PermissionError(str(exc.detail)) from exc
                raise RuntimeError(f"DAG node '{nid}' failed: {exc.detail}") from exc
            except PermissionError as exc:
                err_status = "CANCELLED" if (cancel_event.is_set() or "cancel" in str(exc).lower()) else "BLOCKED"
                _compensate_completed(nid, err_status, str(exc))
                raise
            except Exception as exc:
                _compensate_completed(nid, "FAILED", str(exc))
                raise

            if cancel_event.is_set():
                exec_id_cancel = exec_res.get("execution_id") or (exec_res.get("evidence") or {}).get("execution_id")
                node_states[nid]["execution_id"] = exec_id_cancel
                _compensate_completed(nid, "CANCELLED", f"Delegation execution cancelled during node '{nid}'")
                raise PermissionError(f"Delegation execution cancelled during node '{nid}'")

            if _monotonic() > deadline:
                exec_id_late = exec_res.get("execution_id") or (exec_res.get("evidence") or {}).get("execution_id")
                node_states[nid]["execution_id"] = exec_id_late
                _compensate_completed(nid, "TIMED_OUT", f"DAG execution exceeded timeout_seconds={eff_timeout}s")
                raise TimeoutError(f"Delegation execution timed out after {eff_timeout}s during node '{nid}'")

            exec_id = exec_res.get("execution_id") or (exec_res.get("evidence") or {}).get("execution_id")
            actual_credits = int(exec_res.get("credits_consumed") or 0)
            actual_units = int(exec_res.get("execution_budget_units") or step_exec_units)
            step_provider_cost = float(exec_res.get("provider_cost_inr") or 0.0)

            consumed_credits += actual_credits
            consumed_exec_units += actual_units
            total_provider_cost = round(total_provider_cost + step_provider_cost, 6)
            completed_outputs[nid] = exec_res.get("result", {})
            node_states[nid] = {
                "status": "COMPLETED",
                "execution_id": exec_id,
                "reversible": bool(node.get("reversible", True)),
            }
            results.append(
                {
                    "node_id": nid,
                    "agent_id": agent_id,
                    "status": exec_res.get("status", "COMPLETED"),
                    "execution_id": exec_id,
                    "evidence_id": exec_id,
                    "credits_consumed": actual_credits,
                    "execution_budget_units": actual_units,
                    "provider_cost_inr": step_provider_cost,
                    "estimated_provider_cost_inr": exec_res.get("estimated_provider_cost_inr"),
                    "actual_provider_cost_inr": exec_res.get("actual_provider_cost_inr"),
                    "provider_cost_source": exec_res.get("provider_cost_source"),
                    "dependency_keys_injected": sorted(list(dep_outputs.keys())),
                }
            )
            rec.credits_consumed = consumed_credits
            rec.execution_budget_units_used = consumed_exec_units
            rec.provider_cost_inr = total_provider_cost
            rec.node_states_json = dict(node_states)
            rec.execution_results_json = list(results)
            rec.updated_at = datetime.now(UTC)
            db.commit()

        rec.execution_mode = mode
        rec.credits_consumed = consumed_credits
        rec.execution_budget_units_used = consumed_exec_units
        rec.provider_cost_inr = total_provider_cost
        rec.node_states_json = dict(node_states)
        rec.execution_results_json = results
        rec.status = "EXECUTED"
        rec.updated_at = datetime.now(UTC)
        seal_task_to_block(
            db=db,
            task_id=rec.id,
            capability_name="p7_autonomy_workforce",
            action="execute_delegation_dag",
            payload={
                "plan_id": rec.id,
                "node_count": len(nodes),
                "credits_consumed": consumed_credits,
                "execution_budget_units_used": consumed_exec_units,
                "provider_cost_inr": total_provider_cost,
                "resumed": resume,
            },
            sealed_by=principal.subject,
        )
        db.commit()
        db.refresh(rec)
        return _serialize_plan(rec)
    finally:
        with _ACTIVE_PLAN_LOCK:
            if _ACTIVE_PLAN_CANCEL_EVENTS.get(rec.id) is cancel_event:
                _ACTIVE_PLAN_CANCEL_EVENTS.pop(rec.id, None)


def cancel_delegation_plan(
    db: Session,
    *,
    plan_id: str,
    org_id: str | None,
    reason: str = "Cancelled by operator",
    actor: str = "operator",
) -> dict[str, Any]:
    """Cancel a queued, running, or failed P7 delegation plan and compensate completed reversible nodes."""
    rec = db.get(P7DelegationPlanRecord, plan_id)
    if not rec or (org_id is not None and rec.org_id != org_id):
        raise ValueError(f"Delegation plan '{plan_id}' not found")
    _ensure_active_org(db, rec.org_id)

    with _ACTIVE_PLAN_LOCK:
        active_ev = _ACTIVE_PLAN_CANCEL_EVENTS.get(rec.id)
        if active_ev is not None:
            active_ev.set()

    if rec.status == "EXECUTED":
        raise ValueError("Completed delegation plan cannot be cancelled")
    if rec.status == "CANCELLED":
        return _serialize_plan(rec)

    nodes = list(rec.nodes_json or [])
    node_states: dict[str, dict[str, Any]] = dict(getattr(rec, "node_states_json", None) or {})
    if not node_states:
        node_states = {
            n["node_id"]: {
                "status": "PENDING",
                "execution_id": None,
                "reversible": bool(n.get("reversible", True)),
            }
            for n in nodes
            if isinstance(n, dict) and n.get("node_id")
        }
    results: list[dict[str, Any]] = [dict(r) for r in (rec.execution_results_json or []) if isinstance(r, dict)]
    for prev in results:
        pid = prev.get("node_id")
        if pid and (node_states.get(pid) or {}).get("status") == "COMPLETED":
            if node_states[pid].get("reversible", True):
                node_states[pid]["status"] = "COMPENSATED"
                node_states[pid]["compensation_action"] = "reversible_state_compensated_on_cancel"
                prev["compensation_status"] = "COMPENSATED"
            else:
                node_states[pid]["compensation_action"] = "skipped_irreversible_side_effect"
                prev["compensation_status"] = "SKIPPED_IRREVERSIBLE"

    for nid, st in node_states.items():
        if st.get("status") in ("PENDING", "RUNNING"):
            st["status"] = "CANCELLED"
            st["failure_reason"] = reason

    rec.status = "CANCELLED"
    rec.node_states_json = node_states
    rec.execution_results_json = results
    rec.updated_at = datetime.now(UTC)
    seal_task_to_block(
        db=db,
        task_id=rec.id,
        capability_name="p7_autonomy_workforce",
        action="cancel_delegation_dag",
        payload={"plan_id": rec.id, "reason": reason},
        sealed_by=actor,
    )
    db.commit()
    db.refresh(rec)
    return _serialize_plan(rec)


def list_delegation_plans(db: Session, *, org_id: str | None = None) -> list[dict[str, Any]]:
    """List delegation DAG plans."""
    q = db.query(P7DelegationPlanRecord)
    if org_id is not None:
        q = q.filter(P7DelegationPlanRecord.org_id == org_id)
    return [_serialize_plan(r) for r in q.order_by(P7DelegationPlanRecord.created_at.desc()).all()]


def _serialize_memory(rec: P7TenantMemoryRecord) -> dict[str, Any]:
    return {
        "memory_id": rec.id,
        "org_id": rec.org_id,
        "namespace": rec.namespace,
        "memory_key": rec.memory_key,
        "content": rec.content,
        "source_type": rec.source_type,
        "source_ref": rec.source_ref,
        "ttl_seconds": rec.ttl_seconds,
        "expires_at": rec.expires_at.isoformat() if rec.expires_at else None,
        "is_deleted": bool(rec.is_deleted),
        "created_by": rec.created_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def write_tenant_memory(
    db: Session,
    *,
    org_id: str,
    namespace: str,
    memory_key: str,
    content: str,
    source_type: str = "USER_CONFIG",
    source_ref: str | None = None,
    ttl_seconds: int | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Store strictly org-isolated agent memory with secret redaction, provenance, and optional TTL."""
    if not org_id or not org_id.strip():
        raise ValueError("org_id is required for tenant memory storage")
    _ensure_active_org(db, org_id)

    clean_src = source_type.strip().upper()
    if clean_src not in MEMORY_SOURCE_TYPES:
        raise ValueError(f"Unsupported source_type '{source_type}'; allowed: {MEMORY_SOURCE_TYPES}")
    if ttl_seconds is not None and int(ttl_seconds) <= 0:
        raise ValueError("ttl_seconds must be a positive integer when specified")

    sanitized_content = str(redact_secrets(content.strip()))
    now = datetime.now(UTC)
    expires_at = (now + timedelta(seconds=int(ttl_seconds))) if ttl_seconds else None

    rec = P7TenantMemoryRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        namespace=namespace.strip().lower(),
        memory_key=memory_key.strip(),
        content=sanitized_content,
        source_type=clean_src,
        source_ref=source_ref.strip() if source_ref else None,
        ttl_seconds=int(ttl_seconds) if ttl_seconds else None,
        expires_at=expires_at,
        is_deleted=False,
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_memory(rec)


def read_tenant_memories(
    db: Session,
    *,
    org_id: str,
    namespace: str | None = None,
    include_expired: bool = False,
) -> list[dict[str, Any]]:
    """Read active non-expired memories strictly scoped to org_id."""
    q = db.query(P7TenantMemoryRecord).filter(
        P7TenantMemoryRecord.org_id == org_id,
        P7TenantMemoryRecord.is_deleted.is_(False),
    )
    if namespace:
        q = q.filter(P7TenantMemoryRecord.namespace == namespace.strip().lower())
    rows = q.order_by(P7TenantMemoryRecord.created_at.desc()).all()
    if include_expired:
        return [_serialize_memory(r) for r in rows]

    now = datetime.now(UTC)
    active: list[dict[str, Any]] = []
    for r in rows:
        exp = r.expires_at
        if exp is not None:
            exp_utc = exp.replace(tzinfo=UTC) if exp.tzinfo is None else exp
            if exp_utc <= now:
                continue
        active.append(_serialize_memory(r))
    return active


def purge_tenant_memory(
    db: Session,
    *,
    org_id: str,
    memory_id: str | None = None,
    namespace: str | None = None,
    dpdp_reason: str = "dpdp_erasure_request",
    actor: str = "system",
) -> dict[str, Any]:
    """Erase and redact tenant memory entries cleanly under DPDP compliance."""
    q = db.query(P7TenantMemoryRecord).filter(
        P7TenantMemoryRecord.org_id == org_id,
        P7TenantMemoryRecord.is_deleted.is_(False),
    )
    if memory_id:
        q = q.filter(P7TenantMemoryRecord.id == memory_id)
    if namespace:
        q = q.filter(P7TenantMemoryRecord.namespace == namespace.strip().lower())

    rows = q.all()
    now = datetime.now(UTC)
    for r in rows:
        r.is_deleted = True
        r.deleted_at = now
        r.content = "[PURGED_BY_DPDP_REQUEST]"
        r.source_ref = None
        r.updated_at = now

    if rows:
        seal_task_to_block(
            db=db,
            task_id=f"dpdp-{uuid.uuid4().hex[:12]}",
            capability_name="p7_autonomy_workforce",
            action="dpdp_memory_purge",
            payload={"org_id": org_id, "purged_count": len(rows), "reason": dpdp_reason},
            sealed_by=actor,
        )
    db.commit()
    return {"org_id": org_id, "purged_count": len(rows), "reason": dpdp_reason}


def _serialize_autonomy_policy(rec: P7AutonomyPolicyRecord) -> dict[str, Any]:
    return {
        "policy_id": rec.id,
        "org_id": rec.org_id,
        "agent_id": rec.agent_id,
        "autonomy_level": rec.autonomy_level,
        "requires_hitl_for_external": bool(rec.requires_hitl_for_external),
        "max_daily_budget_credits": int(rec.max_daily_budget_credits),
        "max_daily_execution_units": int(getattr(rec, "max_daily_execution_units", 500) or 500),
        "is_paused": bool(rec.is_paused),
        "pause_reason": rec.pause_reason,
        "min_eval_threshold": float(rec.min_eval_threshold),
        "approval_id": rec.approval_id,
        "updated_by": rec.updated_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def upsert_autonomy_policy(
    db: Session,
    *,
    org_id: str | None,
    agent_id: str,
    autonomy_level: str,
    requires_hitl_for_external: bool = True,
    max_daily_budget_credits: int = 100,
    max_daily_execution_units: int = 500,
    min_eval_threshold: float = 0.75,
    approval_id: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Configure bounded 5-level autonomy governance; permanently rejects unrestricted autonomy or HITL bypass."""
    _ensure_active_org(db, org_id)
    if agent_id not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent_id '{agent_id}'; must exist in AGENT_REGISTRY")

    clean_level = autonomy_level.strip().upper()
    if any(alias in clean_level for alias in PROHIBITED_UNRESTRICTED_ALIASES) or clean_level not in AUTONOMY_LEVELS:
        raise ValueError(
            f"Rejected autonomy_level '{autonomy_level}': unrestricted autonomy is prohibited; allowed levels: {AUTONOMY_LEVELS}"
        )
    if not requires_hitl_for_external:
        raise ValueError("requires_hitl_for_external cannot be disabled; external side effects always require HITL")
    if max_daily_budget_credits <= 0:
        raise ValueError("max_daily_budget_credits must be positive")
    if max_daily_execution_units <= 0:
        raise ValueError("max_daily_execution_units must be positive")
    if not (0.5 <= float(min_eval_threshold) <= 1.0):
        raise ValueError("min_eval_threshold must be between 0.5 and 1.0")
    if clean_level in ("LEVEL_3_BOUNDED_AUTONOMY", "LEVEL_4_SUPERVISED_ORCHESTRATION") and float(min_eval_threshold) < 0.80:
        raise ValueError(f"{clean_level} requires min_eval_threshold >= 0.80")
    if approval_id is not None:
        _verify_approved_request(db, approval_id=approval_id, org_id=org_id)

    now = datetime.now(UTC)
    rec = db.query(P7AutonomyPolicyRecord).filter_by(org_id=org_id, agent_id=agent_id).first()
    if rec:
        rec.autonomy_level = clean_level
        rec.requires_hitl_for_external = True
        rec.max_daily_budget_credits = int(max_daily_budget_credits)
        rec.max_daily_execution_units = int(max_daily_execution_units)
        rec.min_eval_threshold = float(min_eval_threshold)
        if approval_id is not None:
            rec.approval_id = approval_id.strip() or None
        rec.updated_by = actor
        rec.updated_at = now
    else:
        rec = P7AutonomyPolicyRecord(
            id=str(uuid.uuid4()),
            org_id=org_id,
            agent_id=agent_id,
            autonomy_level=clean_level,
            requires_hitl_for_external=True,
            max_daily_budget_credits=int(max_daily_budget_credits),
            max_daily_execution_units=int(max_daily_execution_units),
            is_paused=False,
            min_eval_threshold=float(min_eval_threshold),
            approval_id=approval_id.strip() if approval_id else None,
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
        db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_autonomy_policy(rec)


def resume_autonomy_policy(
    db: Session,
    *,
    org_id: str | None,
    agent_id: str,
    note: str = "Manually reviewed and resumed by owner",
    actor: str = "system",
) -> dict[str, Any]:
    """Resume a paused agent autonomy policy after human review."""
    rec = db.query(P7AutonomyPolicyRecord).filter_by(org_id=org_id, agent_id=agent_id).first()
    if not rec:
        raise ValueError(f"Autonomy policy for agent '{agent_id}' not found")
    rec.is_paused = False
    rec.pause_reason = None
    rec.updated_by = actor
    rec.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(rec)
    res = _serialize_autonomy_policy(rec)
    res["resume_note"] = note
    return res


def list_autonomy_policies(db: Session, *, org_id: str | None = None) -> list[dict[str, Any]]:
    """List P7 autonomy governance policies."""
    q = db.query(P7AutonomyPolicyRecord)
    if org_id is not None:
        q = q.filter(P7AutonomyPolicyRecord.org_id == org_id)
    return [_serialize_autonomy_policy(r) for r in q.order_by(P7AutonomyPolicyRecord.updated_at.desc()).all()]


def _serialize_eval(rec: P7AgentEvalRunRecord) -> dict[str, Any]:
    return {
        "eval_id": rec.id,
        "org_id": rec.org_id,
        "agent_id": rec.agent_id,
        "eval_suite_name": rec.eval_suite_name,
        "quality_score": float(rec.quality_score),
        "safety_score": float(rec.safety_score),
        "threshold_score": float(rec.threshold_score),
        "passed": bool(rec.passed),
        "auto_paused_triggered": bool(rec.auto_paused_triggered),
        "metrics": dict(rec.metrics_json or {}),
        "notes": rec.notes,
        "evaluated_by": rec.evaluated_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def run_agent_evaluation(
    db: Session,
    *,
    org_id: str | None,
    agent_id: str,
    eval_suite_name: str,
    quality_score: float,
    safety_score: float,
    threshold_score: float | None = None,
    metrics: dict[str, Any] | None = None,
    notes: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Record a continuous agent evaluation run and auto-pause autonomy if scores breach threshold."""
    _ensure_active_org(db, org_id)
    if agent_id not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent_id '{agent_id}'; must exist in AGENT_REGISTRY")
    if not (0.0 <= float(quality_score) <= 1.0) or not (0.0 <= float(safety_score) <= 1.0):
        raise ValueError("quality_score and safety_score must be between 0.0 and 1.0")

    policy = db.query(P7AutonomyPolicyRecord).filter_by(org_id=org_id, agent_id=agent_id).first()
    eff_threshold = float(threshold_score if threshold_score is not None else (policy.min_eval_threshold if policy else 0.75))
    passed = float(quality_score) >= eff_threshold and float(safety_score) >= eff_threshold
    auto_paused = False
    now = datetime.now(UTC)

    if not passed:
        auto_paused = True
        reason = (
            f"Auto-paused by continuous eval '{eval_suite_name}': "
            f"quality={quality_score:.2f}, safety={safety_score:.2f} < threshold={eff_threshold:.2f}"
        )
        if policy:
            policy.is_paused = True
            policy.pause_reason = reason
            policy.updated_by = actor
            policy.updated_at = now
        else:
            policy = P7AutonomyPolicyRecord(
                id=str(uuid.uuid4()),
                org_id=org_id,
                agent_id=agent_id,
                autonomy_level="LEVEL_2_APPROVAL_GATED",
                requires_hitl_for_external=True,
                max_daily_budget_credits=100,
                is_paused=True,
                pause_reason=reason,
                min_eval_threshold=eff_threshold,
                updated_by=actor,
                created_at=now,
                updated_at=now,
            )
            db.add(policy)

    eval_rec = P7AgentEvalRunRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        agent_id=agent_id,
        eval_suite_name=eval_suite_name.strip(),
        quality_score=float(quality_score),
        safety_score=float(safety_score),
        threshold_score=eff_threshold,
        passed=passed,
        auto_paused_triggered=auto_paused,
        metrics_json=dict(metrics or {}),
        notes=notes.strip() if notes else None,
        evaluated_by=actor,
        created_at=now,
    )
    db.add(eval_rec)
    db.commit()
    db.refresh(eval_rec)
    return _serialize_eval(eval_rec)


def list_agent_evaluations(db: Session, *, org_id: str | None = None, agent_id: str | None = None) -> list[dict[str, Any]]:
    """List continuous agent evaluation runs."""
    q = db.query(P7AgentEvalRunRecord)
    if org_id is not None:
        q = q.filter(P7AgentEvalRunRecord.org_id == org_id)
    if agent_id:
        q = q.filter(P7AgentEvalRunRecord.agent_id == agent_id)
    return [_serialize_eval(r) for r in q.order_by(P7AgentEvalRunRecord.created_at.desc()).all()]


def compute_p7_overview(db: Session, *, org_id: str | None = None) -> dict[str, Any]:
    """Return P7 DAGs, policies, evals, and tenant memory summary cleanly."""
    plans = list_delegation_plans(db, org_id=org_id)
    policies = list_autonomy_policies(db, org_id=org_id)
    evals = list_agent_evaluations(db, org_id=org_id)
    mem_count = (
        len(read_tenant_memories(db, org_id=org_id))
        if org_id
        else db.query(P7TenantMemoryRecord).filter(P7TenantMemoryRecord.is_deleted.is_(False)).count()
    )
    return {
        "summary": {
            "dag_plan_count": len(plans),
            "executed_dag_count": sum(1 for p in plans if p["status"] == "EXECUTED"),
            "active_memory_count": mem_count,
            "autonomy_policy_count": len(policies),
            "paused_agent_count": sum(1 for p in policies if p["is_paused"]),
            "eval_run_count": len(evals),
            "failed_eval_count": sum(1 for e in evals if not e["passed"]),
        },
        "dag_plans": plans,
        "autonomy_policies": policies,
        "eval_runs": evals,
        "memories": read_tenant_memories(db, org_id=org_id) if org_id else [],
    }
