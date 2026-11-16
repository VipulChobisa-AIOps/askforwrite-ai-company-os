"""Adversarial P7 autonomous workforce governance & three-control budget hardening tests."""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.llm_client import generate, get_last_llm_usage, reset_last_llm_usage, set_request_llm_context
from app.db.database import Base, get_db
from app.db.models import ApprovalRequest, ExecutionEvidenceRecord, OrganizationRecord, P7DelegationPlanRecord
from app.main import app
from app.services.execution_guard import set_emergency_stop

OWNER_KEY = "p7-sec-owner-key-32-characters!!"
MANAGER_KEY = "p7-sec-manager-key-32-chars!!!!!"
JWT_SECRET = "p7-sec-jwt-secret-32-characters!"


@pytest.fixture()
def p7_sec_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Session]:
    monkeypatch.setenv("OWNER_API_KEY", OWNER_KEY)
    monkeypatch.setenv("MANAGER_API_KEY", MANAGER_KEY)
    monkeypatch.setenv("JWT_SECRET_KEY", JWT_SECRET)

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    db = TestingSessionLocal()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client, db
    finally:
        app.dependency_overrides.clear()
        db.close()


def _signup_entitled_tenant(client: TestClient, db: Session, email: str, company: str) -> dict[str, Any]:
    res = client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "StrongPassword!123", "full_name": "Founder", "company_name": company},
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()
    org = db.get(OrganizationRecord, data["org_id"])
    org.tier = "enterprise"
    org.credits_balance = 50
    org.metadata_json = {"package_key": "enterprise", "entitled_capabilities": ["all_access"]}
    db.commit()
    return {"org_id": data["org_id"], "headers": {"Authorization": f"Bearer {data['access_token']}"}}


def _create_approval(db: Session, *, org_id: str | None, status_val: str = "APPROVED", key_suffix: str = "1") -> str:
    appr = ApprovalRequest(
        task_id=f"task-{key_suffix}",
        action="p7_dag_execution",
        detail={"org_id": org_id} if org_id is not None else {},
        idempotency_key=f"p7-appr-{key_suffix}",
        request_hash=hashlib.sha256(f"p7-appr-{key_suffix}".encode()).hexdigest(),
        status=status_val,
        requested_by="founder",
    )
    db.add(appr)
    db.commit()
    db.refresh(appr)
    return appr.id


def test_p7_three_control_budgets_and_llm_telemetry_metering(p7_sec_client) -> None:
    """Verify non-billable credit_cost=0 stays 0, execution_budget_units & provider_cost_inr meter independently."""
    client, db = p7_sec_client
    t1 = _signup_entitled_tenant(client, db, "p7cost1@example.in", "Three Control Co")

    # 1. Direct registry execution of non-billable P4 agent charges 0 customer credits & 1 execution unit
    direct = client.post(
        "/v1/registry/agents/gtm_strategist_agent/execute",
        headers=t1["headers"],
        json={"execution_mode": "SIMULATION", "input_payload": {}},
    )
    assert direct.status_code == 200, direct.text
    djson = direct.json()
    assert djson["credits_consumed"] == 0
    assert djson["execution_budget_units"] == 1
    assert djson["provider_cost_inr"] == 0.0
    assert djson["evidence"]["credits_consumed"] == 0
    assert djson["evidence"]["execution_budget_units"] == 1

    # 2. Billable P0 agent (research_analyst_agent) deducts real 1 customer credit while P4 stays 0
    dag_mixed = client.post(
        "/v1/p7/workforce/dag-plans",
        headers=t1["headers"],
        json={
            "name": "Mixed Billable & Non-Billable DAG",
            "credit_budget": 5,
            "execution_budget_limit": 5,
            "nodes": [
                {"node_id": "n_intel", "agent_id": "competitive_intel_agent", "depends_on": []},
                {"node_id": "n_res", "agent_id": "research_analyst_agent", "depends_on": ["n_intel"]},
            ],
        },
    )
    assert dag_mixed.status_code == 200, dag_mixed.text
    mixed_pid = dag_mixed.json()["plan_id"]
    exec_mixed = client.post(
        f"/v1/p7/workforce/dag-plans/{mixed_pid}/execute",
        headers=t1["headers"],
        json={"execution_mode": "SIMULATION"},
    )
    assert exec_mixed.status_code == 200, exec_mixed.text
    ex = exec_mixed.json()
    assert ex["credits_consumed"] == 1
    assert ex["execution_budget_units_used"] == 2

    # 3. LLM telemetry ContextVar meters token counts & INR cost cleanly when live model returns usage_metadata
    reset_last_llm_usage()
    set_request_llm_context("test-byok-key-for-metering", is_owner=True)

    fake_response = SimpleNamespace(
        text="Metered response output",
        usage_metadata=SimpleNamespace(prompt_token_count=400, candidates_token_count=600, total_token_count=1000),
    )
    fake_client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: fake_response))
    with patch("app.agents.llm_client.get_gemini_client_for_key", return_value=fake_client):
        text = generate("Summarize metering", model="gemini-2.5-flash")
    assert text == "Metered response output"
    usage = get_last_llm_usage()
    assert usage is not None
    assert usage["provider_tokens_total"] == 1000
    assert usage["provider_cost_inr"] > 0.0
    assert usage["provider_model"] == "gemini-2.5-flash"
    set_request_llm_context(None, is_owner=True)


def test_p7_dependency_injection_memory_org_spoof_and_role_blocks(p7_sec_client) -> None:
    """Verify execution_id handoff, dependency+memory injection, role guards, and input_payload org_id spoofing rejection."""
    client, db = p7_sec_client
    t1 = _signup_entitled_tenant(client, db, "p7dep1@example.in", "Tenant Dep One")
    t2 = _signup_entitled_tenant(client, db, "p7dep2@example.in", "Tenant Dep Two")

    # Public self-registered user without company signup gets 'customer' role -> blocked from P7 operator mutations
    cust = client.post(
        "/v1/auth/register",
        json={
            "email": "p7cust@example.in",
            "password": "StrongPassword!123",
            "full_name": "Cust User",
            "company_name": "Cust Isolated Org",
        },
    )
    assert cust.status_code in (200, 201), cust.text
    cust_hdrs = {"Authorization": f"Bearer {cust.json()['access_token']}"}
    assert (
        client.post(
            "/v1/p7/workforce/dag-plans",
            headers=cust_hdrs,
            json={"name": "Cust Denied", "nodes": [{"node_id": "a", "agent_id": "gtm_strategist_agent"}]},
        ).status_code
        == 403
    )

    # Direct agent spoofed input_payload["org_id"] blocked
    spoof_direct = client.post(
        "/v1/registry/agents/gtm_strategist_agent/execute",
        headers=t1["headers"],
        json={"execution_mode": "SIMULATION", "input_payload": {"org_id": t2["org_id"]}},
    )
    assert spoof_direct.status_code == 403

    # Tenant 1 writes active memory; creates 2-node DAG -> both memory & dependency output injected cleanly
    mem = client.post(
        "/v1/p7/workforce/memories",
        headers=t1["headers"],
        json={"namespace": "gtm", "memory_key": "icp_focus", "content": "Focus on mid-market healthcare SaaS"},
    )
    assert mem.status_code == 200

    # DAG with spoofed org_id in node input_payload rejected on execution
    spoof_dag = client.post(
        "/v1/p7/workforce/dag-plans",
        headers=t1["headers"],
        json={
            "name": "Spoofed Node DAG",
            "nodes": [
                {"node_id": "s1", "agent_id": "competitive_intel_agent", "input_payload": {"org_id": t2["org_id"]}}
            ],
        },
    ).json()
    assert (
        client.post(
            f"/v1/p7/workforce/dag-plans/{spoof_dag['plan_id']}/execute",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION"},
        ).status_code
        == 403
    )

    # Tenant 2 cannot execute Tenant 1's DAG
    assert (
        client.post(
            f"/v1/p7/workforce/dag-plans/{spoof_dag['plan_id']}/execute",
            headers=t2["headers"],
            json={"execution_mode": "SIMULATION"},
        ).status_code
        == 404
    )

    # Clean 2-stage DAG injects tenant_memories + upstream dependency outputs & valid execution_id
    clean_dag = client.post(
        "/v1/p7/workforce/dag-plans",
        headers=t1["headers"],
        json={
            "name": "Clean Handoff DAG",
            "nodes": [
                {"node_id": "step_1", "agent_id": "competitive_intel_agent", "depends_on": []},
                {"node_id": "step_2", "agent_id": "gtm_strategist_agent", "depends_on": ["step_1"]},
            ],
        },
    ).json()
    run_res = client.post(
        f"/v1/p7/workforce/dag-plans/{clean_dag['plan_id']}/execute",
        headers=t1["headers"],
        json={"execution_mode": "SIMULATION"},
    )
    assert run_res.status_code == 200, run_res.text
    rj = run_res.json()
    assert len(rj["execution_results"]) == 2
    s2 = rj["execution_results"][1]
    assert s2["execution_id"] is not None
    assert s2["dependency_keys_injected"] == ["step_1"]
    ev2 = db.get(ExecutionEvidenceRecord, s2["execution_id"])
    assert ev2 is not None
    in_preview = (ev2.metadata_json or {}).get("input_preview", {})
    assert "step_1" in (in_preview.get("dependency_outputs") or {})
    assert any(m["memory_key"] == "icp_focus" for m in (in_preview.get("tenant_memories") or []))


def test_p7_autonomy_level_approval_daily_cap_estop_timeout_and_compensation(p7_sec_client) -> None:
    """Verify LEVEL_0/LEVEL_2 approval checks, daily caps, EmergencyStop, timeout, and reversible-only compensation."""
    client, db = p7_sec_client
    t1 = _signup_entitled_tenant(client, db, "p7gov1@example.in", "Governance Co")
    t2 = _signup_entitled_tenant(client, db, "p7gov2@example.in", "Other Org")

    # 1. LEVEL_0_OBSERVE blocks execution completely
    client.put(
        "/v1/p7/workforce/autonomy-policies/competitive_intel_agent",
        headers=t1["headers"],
        json={"autonomy_level": "LEVEL_0_OBSERVE"},
    )
    dag0 = client.post(
        "/v1/p7/workforce/dag-plans",
        headers=t1["headers"],
        json={"name": "Obs DAG", "nodes": [{"node_id": "a", "agent_id": "competitive_intel_agent"}]},
    ).json()
    assert (
        client.post(
            f"/v1/p7/workforce/dag-plans/{dag0['plan_id']}/execute",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION"},
        ).status_code
        == 403
    )

    # 2. LEVEL_2_APPROVAL_GATED requires same-org APPROVED ApprovalRequest
    client.put(
        "/v1/p7/workforce/autonomy-policies/competitive_intel_agent",
        headers=t1["headers"],
        json={"autonomy_level": "LEVEL_2_APPROVAL_GATED", "max_daily_execution_units": 1},
    )
    other_org_appr = _create_approval(db, org_id=t2["org_id"], status_val="APPROVED", key_suffix="other")
    pending_appr = _create_approval(db, org_id=t1["org_id"], status_val="PENDING", key_suffix="pend")
    valid_appr = _create_approval(db, org_id=t1["org_id"], status_val="APPROVED", key_suffix="ok")

    assert (
        client.post(
            f"/v1/p7/workforce/dag-plans/{dag0['plan_id']}/execute",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/p7/workforce/dag-plans/{dag0['plan_id']}/execute",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION", "approval_id": other_org_appr},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/p7/workforce/dag-plans/{dag0['plan_id']}/execute",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION", "approval_id": pending_appr},
        ).status_code
        == 403
    )
    ok_exec = client.post(
        f"/v1/p7/workforce/dag-plans/{dag0['plan_id']}/execute",
        headers=t1["headers"],
        json={"execution_mode": "SIMULATION", "approval_id": valid_appr},
    )
    assert ok_exec.status_code == 200, ok_exec.text

    # 3. Daily execution unit cap (max_daily_execution_units=1) blocks second run
    cap_block = client.post(
        f"/v1/p7/workforce/dag-plans/{dag0['plan_id']}/execute",
        headers=t1["headers"],
        json={"execution_mode": "SIMULATION", "approval_id": valid_appr},
    )
    assert cap_block.status_code == 403
    assert "daily" in cap_block.text.lower()

    # Raise daily cap and update to LEVEL_3, then test EmergencyStop block
    client.put(
        "/v1/p7/workforce/autonomy-policies/competitive_intel_agent",
        headers=t1["headers"],
        json={"autonomy_level": "LEVEL_3_BOUNDED_AUTONOMY", "min_eval_threshold": 0.80, "max_daily_execution_units": 50},
    )
    set_emergency_stop(
        db,
        scope_level="tenant",
        scope_target=t1["org_id"],
        state="EMERGENCY_STOPPED",
        reason="Adversarial drill stop",
        triggered_by="owner",
        org_id=t1["org_id"],
    )
    db.commit()
    assert (
        client.post(
            f"/v1/p7/workforce/dag-plans/{dag0['plan_id']}/execute",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION"},
        ).status_code
        == 403
    )
    set_emergency_stop(
        db,
        scope_level="tenant",
        scope_target=t1["org_id"],
        state="ACTIVE",
        reason="Clear drill stop",
        triggered_by="owner",
        org_id=t1["org_id"],
    )
    db.commit()

    # 4. Reversible-only compensation on node failure + durable per-node state
    comp_dag = client.post(
        "/v1/p7/workforce/dag-plans",
        headers=t1["headers"],
        json={
            "name": "Compensation Drill DAG",
            "nodes": [
                {"node_id": "rev_node", "agent_id": "competitive_intel_agent", "reversible": True, "depends_on": []},
                {"node_id": "irrev_node", "agent_id": "gtm_strategist_agent", "reversible": False, "depends_on": ["rev_node"]},
                {
                    "node_id": "fail_node",
                    "agent_id": "industry_pack_architect_agent",
                    "depends_on": ["irrev_node"],
                    "input_payload": {"__force_failure__": True},
                },
            ],
        },
    ).json()
    comp_res = client.post(
        f"/v1/p7/workforce/dag-plans/{comp_dag['plan_id']}/execute",
        headers=t1["headers"],
        json={"execution_mode": "SIMULATION"},
    )
    assert comp_res.status_code == 422
    comp_row = db.get(P7DelegationPlanRecord, comp_dag["plan_id"])
    assert comp_row.status == "FAILED"
    assert comp_row.node_states_json["rev_node"]["status"] == "COMPENSATED"
    assert comp_row.node_states_json["irrev_node"]["status"] == "COMPLETED"
    assert comp_row.node_states_json["irrev_node"]["compensation_action"] == "skipped_irreversible_side_effect"
    assert comp_row.node_states_json["fail_node"]["status"] == "FAILED"

    # 5. Timeout enforcement cancels before step execution -> HTTP 408 and TIMED_OUT durable state
    with patch("app.services.p7_autonomy_workforce._monotonic", side_effect=[100.0, 200.0, 200.0]):
        to_res = client.post(
            f"/v1/p7/workforce/dag-plans/{dag0['plan_id']}/execute",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION", "timeout_seconds": 1},
        )
    assert to_res.status_code == 408
    to_row = db.get(P7DelegationPlanRecord, dag0["plan_id"])
    assert to_row.status == "TIMED_OUT"


def test_p7_genuine_blocking_timeout_partial_persistence_cancel_and_recovery(
    p7_sec_client,
    tmp_path: Path,
) -> None:
    """Verify real wall-clock timeout interruption, irreversible partial persistence, cancel, and DAG recovery."""
    client, db = p7_sec_client
    t1 = _signup_entitled_tenant(client, db, "p7blocking@example.in", "Blocking Timeout Co")

    # Part A: Genuine blocking worker thread exceeds timeout_seconds=1 and interrupts before full sleep completes
    plan = client.post(
        "/v1/p7/workforce/dag-plans",
        headers=t1["headers"],
        json={
            "name": "Blocking Timeout & Recovery DAG",
            "max_depth": 5,
            "timeout_seconds": 1,
            "nodes": [
                {"node_id": "n_irrev", "agent_id": "competitive_intel_agent", "reversible": False, "depends_on": []},
                {"node_id": "n_rev", "agent_id": "gtm_strategist_agent", "reversible": True, "depends_on": ["n_irrev"]},
                {"node_id": "n_slow", "agent_id": "autonomy_orchestrator_agent", "reversible": True, "depends_on": ["n_rev"]},
                {"node_id": "n_after", "agent_id": "industry_pack_architect_agent", "reversible": True, "depends_on": ["n_slow"]},
            ],
        },
    ).json()

    call_counts: dict[str, int] = {}
    slow_unblock = threading.Event()
    fail_slow_once = {"pending": True}

    def blocking_dispatch(worker_db, *, agent, tenant_id, actor, exec_mode, input_payload):
        call_counts[agent.agent_id] = call_counts.get(agent.agent_id, 0) + 1
        if agent.agent_id == "autonomy_orchestrator_agent" and fail_slow_once["pending"]:
            fail_slow_once["pending"] = False
            slow_unblock.wait(timeout=3.5)
        return {
            "output": {"agent_id": agent.agent_id, "call_no": call_counts[agent.agent_id]},
            "fallback_used": False,
            "uses_external_provider": False,
        }

    t0 = time.monotonic()
    with patch("app.services.registry._dispatch_domain_agent", side_effect=blocking_dispatch):
        to_res = client.post(
            f"/v1/p7/workforce/dag-plans/{plan['plan_id']}/execute",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION", "timeout_seconds": 1},
        )
    elapsed = time.monotonic() - t0
    slow_unblock.set()

    assert to_res.status_code == 408, to_res.text
    # Interrupted at ~1s timeout rather than waiting the full 3.5s block
    assert elapsed < 2.2, f"Expected early timeout interruption <2.2s, took {elapsed:.2f}s"

    db.expire_all()
    timed_row = db.get(P7DelegationPlanRecord, plan["plan_id"])
    assert timed_row.status == "TIMED_OUT"
    assert timed_row.node_states_json["n_irrev"]["status"] == "COMPLETED"
    assert timed_row.node_states_json["n_irrev"]["compensation_action"] == "skipped_irreversible_side_effect"
    assert timed_row.node_states_json["n_irrev"]["execution_id"]
    assert timed_row.node_states_json["n_rev"]["status"] == "COMPENSATED"
    assert timed_row.node_states_json["n_slow"]["status"] == "TIMED_OUT"
    assert timed_row.node_states_json["n_slow"]["execution_id"]
    assert timed_row.node_states_json["n_after"]["status"] == "CANCELLED"
    assert call_counts["competitive_intel_agent"] == 1
    assert call_counts.get("industry_pack_architect_agent", 0) == 0

    timed_ev = db.get(ExecutionEvidenceRecord, timed_row.node_states_json["n_slow"]["execution_id"])
    assert timed_ev is not None and timed_ev.status == "TIMED_OUT"

    # Recover via /recover: preserves irreversible COMPLETED step without re-executing, re-runs compensated & remaining steps
    with patch("app.services.registry._dispatch_domain_agent", side_effect=blocking_dispatch):
        rec_res = client.post(
            f"/v1/p7/workforce/dag-plans/{plan['plan_id']}/recover",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION", "timeout_seconds": 10},
        )
    assert rec_res.status_code == 200, rec_res.text
    rec_json = rec_res.json()
    assert rec_json["status"] == "EXECUTED"
    assert call_counts["competitive_intel_agent"] == 1  # NOT re-executed
    assert call_counts["gtm_strategist_agent"] == 2  # compensated step re-ran
    assert call_counts["industry_pack_architect_agent"] == 1
    assert all(rec_json["node_states"][nid]["status"] == "COMPLETED" for nid in ("n_irrev", "n_rev", "n_slow", "n_after"))
    preserved_entry = next(r for r in rec_json["execution_results"] if r["node_id"] == "n_irrev")
    assert preserved_entry.get("preserved_on_recovery") is True

    # Part B: Mid-execution cancellation across concurrent sessions on a file-backed SQLite DB
    cancel_db_path = tmp_path / "p7_cancel.db"
    cancel_eng = create_engine(
        f"sqlite:///{cancel_db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(bind=cancel_eng)
    CancelSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cancel_eng, expire_on_commit=False)

    def override_cancel_db():
        s = CancelSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_cancel_db
    try:
        cancel_client = TestClient(app)
        with CancelSessionLocal() as s:
            t_cancel = _signup_entitled_tenant(cancel_client, s, "p7cancel@example.in", "Cancel Co")

        cancel_plan = cancel_client.post(
            "/v1/p7/workforce/dag-plans",
            headers=t_cancel["headers"],
            json={
                "name": "Mid-Run Cancel DAG",
                "timeout_seconds": 15,
                "nodes": [
                    {"node_id": "c_fast", "agent_id": "competitive_intel_agent", "reversible": False, "depends_on": []},
                    {"node_id": "c_wait", "agent_id": "gtm_strategist_agent", "reversible": True, "depends_on": ["c_fast"]},
                    {"node_id": "c_tail", "agent_id": "autonomy_orchestrator_agent", "reversible": True, "depends_on": ["c_wait"]},
                ],
            },
        ).json()

        worker_started = threading.Event()
        worker_release = threading.Event()
        exec_outcome: dict[str, Any] = {}

        def cancelable_dispatch(worker_db, *, agent, tenant_id, actor, exec_mode, input_payload):
            if agent.agent_id == "gtm_strategist_agent":
                worker_started.set()
                worker_release.wait(timeout=3.0)
            return {"output": {"ok": agent.agent_id}, "fallback_used": False, "uses_external_provider": False}

        with patch("app.services.registry._dispatch_domain_agent", side_effect=cancelable_dispatch):
            t_exec = threading.Thread(
                target=lambda: exec_outcome.update(
                    {
                        "resp": cancel_client.post(
                            f"/v1/p7/workforce/dag-plans/{cancel_plan['plan_id']}/execute",
                            headers=t_cancel["headers"],
                            json={"execution_mode": "SIMULATION", "timeout_seconds": 15},
                        )
                    }
                ),
                daemon=True,
            )
            t_exec.start()
            assert worker_started.wait(timeout=2.0), "Blocking DAG node did not start in time"
            c_resp = cancel_client.post(
                f"/v1/p7/workforce/dag-plans/{cancel_plan['plan_id']}/cancel",
                headers=t_cancel["headers"],
                json={"reason": "Operator emergency cancel drill"},
            )
            assert c_resp.status_code == 200, c_resp.text
            assert c_resp.json()["status"] == "CANCELLED"
            t_exec.join(timeout=2.5)
            worker_release.set()

        assert not t_exec.is_alive(), "Executing thread did not abort promptly on cancel"
        assert exec_outcome["resp"].status_code == 403

        # Cancelled plan cannot blindly re-run via /execute without explicit /recover
        re_exec = cancel_client.post(
            f"/v1/p7/workforce/dag-plans/{cancel_plan['plan_id']}/execute",
            headers=t_cancel["headers"],
            json={"execution_mode": "SIMULATION"},
        )
        assert re_exec.status_code == 403
    finally:
        cancel_eng.dispose()
        # Restore p7_sec_client fixture override
        def _restore_db():
            try:
                yield db
            finally:
                pass
        app.dependency_overrides[get_db] = _restore_db


def test_p7_concurrent_credit_and_execution_budget_enforcement(tmp_path: Path) -> None:
    """Verify per-tenant lock prevents overspending credits or max_daily_execution_units under concurrent threads."""
    from app.db.models import P7AutonomyPolicyRecord
    from app.security.auth import APIPrincipal
    from app.services.registry import execute_registered_agent

    db_file = tmp_path / "p7_concurrent.db"
    eng = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(bind=eng)
    ConcSession = sessionmaker(autocommit=False, autoflush=False, bind=eng, expire_on_commit=False)

    org_id = str(uuid.uuid4())
    principal = APIPrincipal(
        subject="conc-admin@acme.in",
        role="tenant_admin",
        org_id=org_id,
        user_id=None,
        tier="enterprise",
    )

    try:
        with ConcSession() as setup_db:
            setup_db.add(
                OrganizationRecord(
                    id=org_id,
                    name="Concurrency Co",
                    slug=f"conc-{uuid.uuid4().hex[:6]}",
                    tier="enterprise",
                    is_active=True,
                    lead_credits_limit=3,
                    lead_credits_used=0,
                    metadata_json={"package_key": "enterprise", "entitled_capabilities": ["all_access"]},
                )
            )
            setup_db.add_all(
                [
                    P7AutonomyPolicyRecord(
                        org_id=org_id,
                        agent_id="research_analyst_agent",
                        autonomy_level="LEVEL_3_BOUNDED_AUTONOMY",
                        requires_hitl_for_external=False,
                        max_daily_budget_credits=100,
                        max_daily_execution_units=100,
                        min_eval_threshold=0.0,
                    ),
                    P7AutonomyPolicyRecord(
                        org_id=org_id,
                        agent_id="competitive_intel_agent",
                        autonomy_level="LEVEL_3_BOUNDED_AUTONOMY",
                        requires_hitl_for_external=False,
                        max_daily_budget_credits=100,
                        max_daily_execution_units=2,
                        min_eval_threshold=0.0,
                    ),
                ]
            )
            setup_db.commit()

        def quick_dispatch(worker_db, *, agent, tenant_id, actor, exec_mode, input_payload):
            time.sleep(0.03)
            return {"output": {"agent": agent.agent_id, "ok": True}, "fallback_used": False, "uses_external_provider": False}

        # Part A: 6 concurrent billable agent runs against lead_credits_limit=3 -> strictly 3 succeed, 3 hit 402
        barrier_a = threading.Barrier(6)

        def run_credit_worker(idx: int) -> tuple[str, Any]:
            barrier_a.wait(timeout=5.0)
            with ConcSession() as wdb:
                try:
                    res = execute_registered_agent(
                        wdb,
                        agent_id="research_analyst_agent",
                        principal=principal,
                        input_payload={"topic": f"topic-{idx}"},
                        execution_mode="SIMULATION",
                        idempotency_key=f"conc-cred-{idx}-{uuid.uuid4().hex[:6]}",
                    )
                    return ("OK", res["credits_consumed"])
                except Exception as exc:
                    return ("ERR", getattr(exc, "status_code", type(exc).__name__))

        with patch("app.services.registry._dispatch_domain_agent", side_effect=quick_dispatch):
            with ThreadPoolExecutor(max_workers=6) as pool:
                outcomes_a = list(pool.map(run_credit_worker, range(6)))

        assert [o[0] for o in outcomes_a].count("OK") == 3, outcomes_a
        assert outcomes_a.count(("ERR", 402)) == 3, outcomes_a

        with ConcSession() as verify_db:
            org_after = verify_db.get(OrganizationRecord, org_id)
            assert org_after.lead_credits_used == 3

        # Part B: 5 concurrent non-billable P7 runs against max_daily_execution_units=2 -> strictly 2 succeed, 3 hit 403
        barrier_b = threading.Barrier(5)

        def run_unit_worker(idx: int) -> tuple[str, Any]:
            barrier_b.wait(timeout=5.0)
            with ConcSession() as wdb:
                try:
                    res = execute_registered_agent(
                        wdb,
                        agent_id="competitive_intel_agent",
                        principal=principal,
                        input_payload={"target": f"comp-{idx}"},
                        execution_mode="SIMULATION",
                        idempotency_key=f"conc-unit-{idx}-{uuid.uuid4().hex[:6]}",
                    )
                    return ("OK", res["execution_budget_units"])
                except Exception as exc:
                    return ("ERR", getattr(exc, "status_code", type(exc).__name__))

        with patch("app.services.registry._dispatch_domain_agent", side_effect=quick_dispatch):
            with ThreadPoolExecutor(max_workers=5) as pool:
                outcomes_b = list(pool.map(run_unit_worker, range(5)))

        assert [o[0] for o in outcomes_b].count("OK") == 2, outcomes_b
        assert outcomes_b.count(("ERR", 403)) == 3, outcomes_b

        with ConcSession() as verify_db:
            completed_ev = (
                verify_db.query(ExecutionEvidenceRecord)
                .filter(
                    ExecutionEvidenceRecord.tenant_id == org_id,
                    ExecutionEvidenceRecord.agent_id == "competitive_intel_agent",
                    ExecutionEvidenceRecord.status == "COMPLETED",
                )
                .all()
            )
            assert len(completed_ev) == 2
            assert sum(int(ev.execution_budget_units or 0) for ev in completed_ev) == 2
    finally:
        eng.dispose()


def test_p7_provider_cost_actual_vs_estimated_provenance(p7_sec_client) -> None:
    """Explicitly distinguish token-estimated costs (actual=None) from provider-reported and zero-fallback costs."""
    from app.agents.llm_client import _record_llm_usage

    client, db = p7_sec_client
    t1 = _signup_entitled_tenant(client, db, "p7costsrc@example.in", "Cost Provenance Co")

    # 1. Estimate-only LLM response (no actual_cost_inr reported) -> actual_provider_cost_inr MUST be None
    def est_dispatch(worker_db, *, agent, tenant_id, actor, exec_mode, input_payload):
        _record_llm_usage(model_name="gemini-2.5-flash", tokens_total=2000, used_fallback=False, actual_cost_inr=None)
        return {"output": {"kind": "estimate"}, "fallback_used": False, "uses_external_provider": True}

    with patch("app.services.registry._dispatch_domain_agent", side_effect=est_dispatch):
        r_est = client.post(
            "/v1/registry/agents/competitive_intel_agent/execute",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION", "input_payload": {}},
        )
    assert r_est.status_code == 200, r_est.text
    j_est = r_est.json()
    assert j_est["provider_cost_source"] == "TOKEN_USAGE_ESTIMATE"
    assert j_est["estimated_provider_cost_inr"] > 0.0
    assert j_est["actual_provider_cost_inr"] is None
    assert j_est["evidence"]["actual_provider_cost_inr"] is None

    # 2. Live provider-reported actual_cost_inr -> actual_provider_cost_inr equals reported figure
    def actual_dispatch(worker_db, *, agent, tenant_id, actor, exec_mode, input_payload):
        _record_llm_usage(model_name="gemini-2.5-flash", tokens_total=1500, used_fallback=False, actual_cost_inr=0.425)
        return {"output": {"kind": "actual"}, "fallback_used": False, "uses_external_provider": True}

    with patch("app.services.registry._dispatch_domain_agent", side_effect=actual_dispatch):
        r_act = client.post(
            "/v1/registry/agents/competitive_intel_agent/execute",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION", "input_payload": {}},
        )
    assert r_act.status_code == 200, r_act.text
    j_act = r_act.json()
    assert j_act["provider_cost_source"] == "LIVE_PROVIDER_REPORTED"
    assert j_act["actual_provider_cost_inr"] == 0.425
    assert j_act["estimated_provider_cost_inr"] == 0.425
    assert j_act["evidence"]["actual_provider_cost_inr"] == 0.425

    # 3. Deterministic fallback / local path -> zero actual cost
    def fb_dispatch(worker_db, *, agent, tenant_id, actor, exec_mode, input_payload):
        _record_llm_usage(model_name="gemini-2.5-flash", tokens_total=0, used_fallback=True)
        return {"output": {"kind": "fallback"}, "fallback_used": True, "uses_external_provider": False}

    with patch("app.services.registry._dispatch_domain_agent", side_effect=fb_dispatch):
        r_fb = client.post(
            "/v1/registry/agents/competitive_intel_agent/execute",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION", "input_payload": {}},
        )
    assert r_fb.status_code == 200, r_fb.text
    j_fb = r_fb.json()
    assert j_fb["provider_cost_source"] == "DETERMINISTIC_FALLBACK_ZERO"
    assert j_fb["actual_provider_cost_inr"] == 0.0
    assert j_fb["estimated_provider_cost_inr"] == 0.0

    # 4. Mixed DAG plan preserves MIXED_ESTIMATE_AND_ACTUAL and actual_provider_cost_inr=None when any step is estimated
    mix_dag = client.post(
        "/v1/p7/workforce/dag-plans",
        headers=t1["headers"],
        json={
            "name": "Mixed Provenance DAG",
            "nodes": [
                {"node_id": "step_actual", "agent_id": "competitive_intel_agent", "depends_on": []},
                {"node_id": "step_est", "agent_id": "gtm_strategist_agent", "depends_on": ["step_actual"]},
            ],
        },
    ).json()

    def dag_cost_dispatch(worker_db, *, agent, tenant_id, actor, exec_mode, input_payload):
        if agent.agent_id == "competitive_intel_agent":
            _record_llm_usage(model_name="gemini-2.5-flash", tokens_total=500, used_fallback=False, actual_cost_inr=0.15)
        else:
            _record_llm_usage(model_name="gemini-2.5-flash", tokens_total=1000, used_fallback=False, actual_cost_inr=None)
        return {"output": {"agent": agent.agent_id}, "fallback_used": False, "uses_external_provider": True}

    with patch("app.services.registry._dispatch_domain_agent", side_effect=dag_cost_dispatch):
        dag_res = client.post(
            f"/v1/p7/workforce/dag-plans/{mix_dag['plan_id']}/execute",
            headers=t1["headers"],
            json={"execution_mode": "SIMULATION"},
        )
    assert dag_res.status_code == 200, dag_res.text
    d_json = dag_res.json()
    assert d_json["estimated_credits"] == 0
    assert d_json["estimated_execution_units"] == 2
    assert d_json["provider_cost_source"] == "MIXED_ESTIMATE_AND_ACTUAL"
    assert d_json["estimated_provider_cost_inr"] > 0.15
    assert d_json["actual_provider_cost_inr"] is None
