"""P7 Controlled Autonomous Workforce test suite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import migrations.versions.m3b8c9d0e1f2_add_p7_autonomy_workforce_tables as p7_migration
from app.db.database import Base, get_db
from app.db.models import P7TenantMemoryRecord
from app.main import app

OWNER_KEY = "p7-workforce-owner-key-32-chars!"
MANAGER_KEY = "p7-workforce-mgr-key-32-chars!!!"
JWT_SECRET = "p7-workforce-jwt-secret-32-char!"


@pytest.fixture()
def p7_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Session]:
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


def _create_tenant(client: TestClient, email: str, company: str) -> dict[str, Any]:
    res = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "StrongPassword!123", "full_name": "Founder", "company_name": company},
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()
    return {"org_id": data["org_id"], "headers": {"Authorization": f"Bearer {data['access_token']}"}}


def test_p7_alembic_migration_upgrade_and_downgrade_parity() -> None:
    """Verify m3b8c9d0e1f2 creates all 4 P7 tables and indexes cleanly and downgrades cleanly."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn)
        op = Operations(ctx)
        orig_op = p7_migration.op
        p7_migration.op = op
        try:
            p7_migration.upgrade()
            conn.commit()
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            expected = {
                "p7_delegation_plans",
                "p7_tenant_memories",
                "p7_autonomy_policies",
                "p7_agent_eval_runs",
            }
            assert expected <= tables
            assert "ix_p7_dag_org_status" in {ix["name"] for ix in insp.get_indexes("p7_delegation_plans")}
            assert "ix_p7_mem_org_ns" in {ix["name"] for ix in insp.get_indexes("p7_tenant_memories")}
            assert "ix_p7_autonomy_org_agent" in {ix["name"] for ix in insp.get_indexes("p7_autonomy_policies")}
            assert "ix_p7_eval_org_agent" in {ix["name"] for ix in insp.get_indexes("p7_agent_eval_runs")}

            p7_migration.downgrade()
            conn.commit()
            remaining = set(inspect(conn).get_table_names())
            assert not (expected & remaining)
        finally:
            p7_migration.op = orig_op


def test_p7_delegation_dag_cycle_depth_budget_and_execution(p7_client) -> None:
    """Verify DAG validation blocks cycles, excess depth, and budget overruns while executing valid DAGs cleanly."""
    client, _ = p7_client
    owner_hdrs = {"X-API-Key": OWNER_KEY}

    # 1. Cycle detection
    cyc = client.post(
        "/v1/p7/workforce/dag-plans",
        headers=owner_hdrs,
        json={
            "name": "Cyclic Plan",
            "nodes": [
                {"node_id": "a", "agent_id": "gtm_strategist_agent", "depends_on": ["b"]},
                {"node_id": "b", "agent_id": "competitive_intel_agent", "depends_on": ["a"]},
            ],
        },
    )
    assert cyc.status_code == 422
    assert "cycle" in cyc.text.lower()

    # 2. Max depth breach
    deep = client.post(
        "/v1/p7/workforce/dag-plans",
        headers=owner_hdrs,
        json={
            "name": "Too Deep Plan",
            "max_depth": 2,
            "nodes": [
                {"node_id": "n1", "agent_id": "competitive_intel_agent", "depends_on": []},
                {"node_id": "n2", "agent_id": "gtm_strategist_agent", "depends_on": ["n1"]},
                {"node_id": "n3", "agent_id": "industry_pack_architect_agent", "depends_on": ["n2"]},
            ],
        },
    )
    assert deep.status_code == 422
    assert "depth" in deep.text.lower()

    # 3. Three-control budget breach: non-billable agents track execution_budget_limit separately (Decision 2)
    over_budget = client.post(
        "/v1/p7/workforce/dag-plans",
        headers=owner_hdrs,
        json={
            "name": "Over Execution Budget Plan",
            "credit_budget": 1,
            "execution_budget_limit": 1,
            "nodes": [
                {"node_id": "n1", "agent_id": "competitive_intel_agent", "depends_on": []},
                {"node_id": "n2", "agent_id": "gtm_strategist_agent", "depends_on": ["n1"]},
            ],
        },
    )
    assert over_budget.status_code == 422
    assert "budget" in over_budget.text.lower()

    # 4. Valid topological DAG planning + SIMULATION execution (and PRODUCTION block)
    ok_dag = client.post(
        "/v1/p7/workforce/dag-plans",
        headers=owner_hdrs,
        json={
            "name": "Valid Two-Stage GTM Intelligence DAG",
            "max_depth": 4,
            "credit_budget": 10,
            "nodes": [
                {"node_id": "step_gtm", "agent_id": "gtm_strategist_agent", "depends_on": ["step_intel"]},
                {"node_id": "step_intel", "agent_id": "competitive_intel_agent", "depends_on": []},
            ],
        },
    )
    assert ok_dag.status_code == 200, ok_dag.text
    plan = ok_dag.json()
    assert plan["computed_depth"] == 2
    assert [n["node_id"] for n in plan["nodes"]] == ["step_intel", "step_gtm"]

    prod_blocked = client.post(
        f"/v1/p7/workforce/dag-plans/{plan['plan_id']}/execute",
        headers=owner_hdrs,
        json={"execution_mode": "PRODUCTION"},
    )
    assert prod_blocked.status_code == 403

    sim_ok = client.post(
        f"/v1/p7/workforce/dag-plans/{plan['plan_id']}/execute",
        headers=owner_hdrs,
        json={"execution_mode": "SIMULATION"},
    )
    assert sim_ok.status_code == 200, sim_ok.text
    executed = sim_ok.json()
    assert executed["status"] == "EXECUTED"
    assert executed["credits_consumed"] == 0
    assert executed["execution_budget_units_used"] == 2
    assert len(executed["execution_results"]) == 2
    assert executed["execution_results"][0]["execution_id"] is not None
    assert executed["execution_results"][0]["evidence_id"] == executed["execution_results"][0]["execution_id"]


def test_p7_tenant_memory_isolation_secret_redaction_ttl_and_dpdp_purge(p7_client) -> None:
    """Verify strict tenant isolation, secret redaction, TTL filtering, and DPDP erasure on P7 memory."""
    client, db = p7_client
    t1 = _create_tenant(client, "mem1@p7.in", "Tenant One Memory")
    t2 = _create_tenant(client, "mem2@p7.in", "Tenant Two Memory")

    m1 = client.post(
        "/v1/p7/workforce/memories",
        headers=t1["headers"],
        json={
            "namespace": "brand_voice",
            "memory_key": "tone_and_key",
            "content": "Prefer concise tone; do not use secret AIzaSyFakeKeyValue1234567890",
            "source_type": "USER_CONFIG",
            "ttl_seconds": 3600,
        },
    )
    assert m1.status_code == 200, m1.text
    mem_id = m1.json()["memory_id"]
    assert "[REDACTED_SECRET]" in m1.json()["content"]
    assert "AIzaSyFakeKeyValue" not in m1.json()["content"]

    # Cross-tenant leak block: Tenant 2 sees 0 memories of Tenant 1 and gets 403 querying Tenant 1's org_id
    t2_list = client.get("/v1/p7/workforce/memories", headers=t2["headers"]).json()
    assert t2_list["count"] == 0
    cross_read = client.get(f"/v1/p7/workforce/memories?org_id={t1['org_id']}", headers=t2["headers"])
    assert cross_read.status_code == 403

    # Simulate TTL expiration cleanly
    m_exp = client.post(
        "/v1/p7/workforce/memories",
        headers=t1["headers"],
        json={"namespace": "ephemeral", "memory_key": "short_ttl", "content": "Expired note", "ttl_seconds": 60},
    ).json()
    exp_row = db.get(P7TenantMemoryRecord, m_exp["memory_id"])
    exp_row.expires_at = datetime.now(UTC) - timedelta(seconds=10)
    db.commit()

    active_mems = client.get("/v1/p7/workforce/memories", headers=t1["headers"]).json()["memories"]
    assert all(m["memory_id"] != m_exp["memory_id"] for m in active_mems)
    assert any(m["memory_id"] == mem_id for m in active_mems)

    # DPDP purge permanently redacts & soft-deletes
    purge = client.post(
        "/v1/p7/workforce/memories/purge",
        headers=t1["headers"],
        json={"memory_id": mem_id, "dpdp_reason": "customer_dpdp_request"},
    )
    assert purge.status_code == 200
    assert purge.json()["purged_count"] == 1
    purged_row = db.get(P7TenantMemoryRecord, mem_id)
    assert purged_row.is_deleted is True
    assert purged_row.content == "[PURGED_BY_DPDP_REQUEST]"


def test_p7_autonomy_levels_eval_auto_pause_and_ui_wiring(p7_client) -> None:
    """Verify bounded 5-level autonomy blocks unrestricted bypasses, auto-pauses on eval fail, and UI/agents work."""
    client, _ = p7_client
    owner_hdrs = {"X-API-Key": OWNER_KEY}

    bad_level = client.put(
        "/v1/p7/workforce/autonomy-policies/gtm_strategist_agent",
        headers=owner_hdrs,
        json={"autonomy_level": "LEVEL_5_UNRESTRICTED"},
    )
    assert bad_level.status_code == 422

    bad_hitl = client.put(
        "/v1/p7/workforce/autonomy-policies/gtm_strategist_agent",
        headers=owner_hdrs,
        json={"autonomy_level": "LEVEL_2_APPROVAL_GATED", "requires_hitl_for_external": False},
    )
    assert bad_hitl.status_code == 422

    ok_pol = client.put(
        "/v1/p7/workforce/autonomy-policies/gtm_strategist_agent",
        headers=owner_hdrs,
        json={"autonomy_level": "LEVEL_4_SUPERVISED_ORCHESTRATION", "requires_hitl_for_external": True, "min_eval_threshold": 0.85},
    )
    assert ok_pol.status_code == 200, ok_pol.text

    # Stage a DAG using gtm_strategist_agent, then trigger an eval breach -> DAG must be blocked until Owner resumes
    plan = client.post(
        "/v1/p7/workforce/dag-plans",
        headers=owner_hdrs,
        json={"name": "Autonomy Guarded DAG", "nodes": [{"node_id": "g1", "agent_id": "gtm_strategist_agent"}]},
    ).json()

    fail_eval = client.post(
        "/v1/p7/workforce/evals",
        headers=owner_hdrs,
        json={
            "agent_id": "gtm_strategist_agent",
            "eval_suite_name": "claim_safety_regression",
            "quality_score": 0.55,
            "safety_score": 0.90,
        },
    )
    assert fail_eval.status_code == 200
    assert fail_eval.json()["passed"] is False
    assert fail_eval.json()["auto_paused_triggered"] is True

    blocked_dag = client.post(
        f"/v1/p7/workforce/dag-plans/{plan['plan_id']}/execute",
        headers=owner_hdrs,
        json={"execution_mode": "SIMULATION"},
    )
    assert blocked_dag.status_code == 403

    resumed = client.post(
        "/v1/p7/workforce/autonomy-policies/gtm_strategist_agent/resume",
        headers=owner_hdrs,
        json={"note": "Prompt guard re-verified"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["is_paused"] is False

    unblocked_dag = client.post(
        f"/v1/p7/workforce/dag-plans/{plan['plan_id']}/execute",
        headers=owner_hdrs,
        json={"execution_mode": "SIMULATION"},
    )
    assert unblocked_dag.status_code == 200
    assert unblocked_dag.json()["status"] == "EXECUTED"

    # Execute P7 registered agents + check UI wiring
    for aid in ("autonomy_orchestrator_agent", "eval_governance_agent"):
        r = client.post(f"/v1/registry/agents/{aid}/execute", headers=owner_hdrs, json={"execution_mode": "SIMULATION", "input_payload": {}})
        assert r.status_code == 200, f"{aid} failed: {r.text}"
        assert r.json()["evidence"]["agent_id"] == aid

    root = Path(__file__).resolve().parent.parent
    html_text = (root / "app" / "dashboard" / "index.html").read_text(encoding="utf-8")
    js_text = (root / "app" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
    assert "page-p7-autonomy" in html_text
    assert "nav-p7-autonomy" in html_text
    assert "p7LoadControlCentre" in js_text
