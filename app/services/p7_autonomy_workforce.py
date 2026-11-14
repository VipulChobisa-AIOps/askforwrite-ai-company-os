"""P7 Controlled Autonomous Workforce service layer.

Implements:
- Cycle-, depth-, and credit-budget-validated Multi-Agent Delegation DAG planning & execution
- Tenant-isolated persistent memory with provenance, secret redaction, TTL expiry, and DPDP purge
- 5-Level Autonomy Governance (LEVEL_0_OBSERVE .. LEVEL_4_SUPERVISED_ORCHESTRATION; never unrestricted)
- Continuous agent evaluation suite with automatic autonomy pause on quality/safety threshold breach
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    OrganizationRecord,
    P7AgentEvalRunRecord,
    P7AutonomyPolicyRecord,
    P7DelegationPlanRecord,
    P7TenantMemoryRecord,
)
from app.security.auth import APIPrincipal
from app.security.trust_chain import seal_task_to_block
from app.services.execution_guard import is_external_side_effect_blocked, redact_secrets, resolve_execution_mode
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


def validate_and_order_dag(
    nodes: list[dict[str, Any]],
    *,
    max_depth: int = 4,
    credit_budget: int = 20,
) -> dict[str, Any]:
    """Validate delegation DAG for acyclicity, valid agents, depth limit, and credit budget."""
    if not nodes:
        raise ValueError("Delegation DAG must contain at least one node")
    if max_depth < 1 or max_depth > 12:
        raise ValueError("max_depth must be between 1 and 12")
    if credit_budget < 1:
        raise ValueError("credit_budget must be positive")

    node_map: dict[str, dict[str, Any]] = {}
    estimated_cost = 0
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
        step_cost = max(1, int(raw.get("credit_cost") or agent_spec.credit_cost or 1))
        estimated_cost += step_cost
        node_map[node_id] = {
            "node_id": node_id,
            "agent_id": agent_id,
            "depends_on": deps,
            "credit_cost": step_cost,
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
    if estimated_cost > credit_budget:
        raise ValueError(f"Delegation DAG estimated cost {estimated_cost} exceeds credit_budget ({credit_budget})")

    return {
        "ordered_nodes": ordered_nodes,
        "computed_depth": computed_depth,
        "estimated_cost": estimated_cost,
    }


def _serialize_plan(rec: P7DelegationPlanRecord) -> dict[str, Any]:
    return {
        "plan_id": rec.id,
        "org_id": rec.org_id,
        "name": rec.name,
        "objective": rec.objective,
        "nodes": list(rec.nodes_json or []),
        "max_depth": int(rec.max_depth),
        "computed_depth": int(rec.computed_depth),
        "credit_budget": int(rec.credit_budget),
        "credits_consumed": int(rec.credits_consumed or 0),
        "status": rec.status,
        "execution_mode": rec.execution_mode,
        "execution_results": list(rec.execution_results_json or []),
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
    actor: str = "system",
) -> dict[str, Any]:
    """Validate and persist a cycle-, depth-, and budget-checked multi-agent delegation DAG."""
    validated = validate_and_order_dag(nodes, max_depth=max_depth, credit_budget=credit_budget)
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
        status="PLANNED",
        execution_mode="SIMULATION",
        execution_results_json=[],
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_plan(rec)


def _is_agent_paused_for_scope(db: Session, *, org_id: str | None, agent_id: str) -> tuple[bool, str | None]:
    candidates = [
        db.query(P7AutonomyPolicyRecord).filter_by(org_id=org_id, agent_id=agent_id).first() if org_id else None,
        db.query(P7AutonomyPolicyRecord).filter_by(org_id=None, agent_id=agent_id).first(),
    ]
    for pol in candidates:
        if pol and pol.is_paused:
            return True, pol.pause_reason or "Agent autonomy paused by governance/eval breach"
    return False, None


def execute_delegation_plan(
    db: Session,
    *,
    plan_id: str,
    org_id: str | None,
    principal: APIPrincipal,
    execution_mode: str = "SIMULATION",
) -> dict[str, Any]:
    """Execute a validated P7 delegation DAG through the unified AGENT_REGISTRY execution engine."""
    rec = db.get(P7DelegationPlanRecord, plan_id)
    if not rec or (org_id is not None and rec.org_id != org_id):
        raise ValueError(f"Delegation plan '{plan_id}' not found")

    mode = _normalize_mode(execution_mode)
    nodes = list(rec.nodes_json or [])

    # Check autonomy pause governance for every node before executing
    for node in nodes:
        paused, reason = _is_agent_paused_for_scope(db, org_id=rec.org_id, agent_id=node["agent_id"])
        if paused:
            raise PermissionError(f"DAG blocked: agent '{node['agent_id']}' is paused ({reason})")

    results: list[dict[str, Any]] = []
    consumed = 0
    for node in nodes:
        if consumed + int(node.get("credit_cost", 1)) > rec.credit_budget:
            rec.status = "BLOCKED"
            rec.credits_consumed = consumed
            rec.execution_results_json = results
            rec.updated_at = datetime.now(UTC)
            db.commit()
            raise PermissionError("Delegation execution halted: runtime credit_budget exhausted")

        payload = dict(node.get("input_payload") or {})
        if rec.org_id and "org_id" not in payload:
            payload["org_id"] = rec.org_id

        exec_res = execute_registered_agent(
            db,
            agent_id=node["agent_id"],
            principal=principal,
            input_payload=payload,
            execution_mode=mode,
            idempotency_key=f"p7dag:{rec.id}:{node['node_id']}:{uuid.uuid4().hex[:8]}",
            workflow_id=rec.id,
        )
        consumed += int(node.get("credit_cost", 1))
        results.append(
            {
                "node_id": node["node_id"],
                "agent_id": node["agent_id"],
                "status": exec_res.get("status", "COMPLETED"),
                "evidence_id": (exec_res.get("evidence") or {}).get("evidence_id"),
            }
        )

    rec.execution_mode = mode
    rec.credits_consumed = consumed
    rec.execution_results_json = results
    rec.status = "EXECUTED"
    rec.updated_at = datetime.now(UTC)
    seal_task_to_block(
        db=db,
        task_id=rec.id,
        capability_name="p7_autonomy_workforce",
        action="execute_delegation_dag",
        payload={"plan_id": rec.id, "node_count": len(nodes), "credits_consumed": consumed},
        sealed_by=principal.subject,
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
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")

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
    min_eval_threshold: float = 0.75,
    actor: str = "system",
) -> dict[str, Any]:
    """Configure bounded 5-level autonomy governance; permanently rejects unrestricted autonomy or HITL bypass."""
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
    if not (0.5 <= float(min_eval_threshold) <= 1.0):
        raise ValueError("min_eval_threshold must be between 0.5 and 1.0")
    if clean_level in ("LEVEL_3_BOUNDED_AUTONOMY", "LEVEL_4_SUPERVISED_ORCHESTRATION") and float(min_eval_threshold) < 0.80:
        raise ValueError(f"{clean_level} requires min_eval_threshold >= 0.80")

    now = datetime.now(UTC)
    rec = db.query(P7AutonomyPolicyRecord).filter_by(org_id=org_id, agent_id=agent_id).first()
    if rec:
        rec.autonomy_level = clean_level
        rec.requires_hitl_for_external = True
        rec.max_daily_budget_credits = int(max_daily_budget_credits)
        rec.min_eval_threshold = float(min_eval_threshold)
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
            is_paused=False,
            min_eval_threshold=float(min_eval_threshold),
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
