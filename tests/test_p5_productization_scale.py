"""P5 Productization & Multi-Customer Scale test suite."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import migrations.versions.k1f6a7b8c9d0_add_p5_productization_scale_tables as p5_migration
from app.db.database import Base, get_db
from app.db.models import CreditLedgerRecord, OrganizationRecord
from app.main import app
from app.services.billing_ledger import compose_modular_pricing

OWNER_KEY = "p5-scale-owner-key-32-chars!!!!!!"
MANAGER_KEY = "p5-scale-manager-key-32-chars!!!!"
JWT_SECRET = "p5-scale-jwt-secret-32-chars!!!!!"


@pytest.fixture()
def p5_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Session]:
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


def test_p5_alembic_migration_upgrade_and_downgrade_parity() -> None:
    """Verify k1f6a7b8c9d0 creates all 5 P5 tables and indexes and downgrades cleanly."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn)
        op = Operations(ctx)
        orig_op = p5_migration.op
        p5_migration.op = op
        try:
            p5_migration.upgrade()
            conn.commit()
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            expected_tables = {
                "p5_tenant_templates",
                "p5_provisioning_runs",
                "p5_tenant_policies",
                "p5_usage_quota_events",
                "p5_operational_incidents",
            }
            assert expected_tables <= tables
            assert "ix_p5_tpl_industry_active" in {ix["name"] for ix in insp.get_indexes("p5_tenant_templates")}
            assert "ix_p5_prov_org_state" in {ix["name"] for ix in insp.get_indexes("p5_provisioning_runs")}
            assert "ix_p5_usage_org_metric" in {ix["name"] for ix in insp.get_indexes("p5_usage_quota_events")}
            assert "ix_p5_incident_org_status" in {ix["name"] for ix in insp.get_indexes("p5_operational_incidents")}

            p5_migration.downgrade()
            conn.commit()
            remaining = set(inspect(conn).get_table_names())
            assert not (expected_tables & remaining)
        finally:
            p5_migration.op = orig_op


def test_p5_consume_credits_reconciled_with_immutable_ledger_and_idempotency(p5_client) -> None:
    """Verify /consume-credits writes immutable CreditLedgerRecord entries, enforces idempotency, and blocks overdrafts."""
    client, db = p5_client
    owner_hdrs = {"X-API-Key": OWNER_KEY}

    org = OrganizationRecord(
        id="p5-credit-org-1",
        name="Ledger Test SME",
        slug="ledger-test-sme",
        tier="launch",
        is_active=True,
        lead_credits_limit=10,
        lead_credits_used=0,
        outreach_credits_limit=5,
        outreach_credits_used=0,
    )
    db.add(org)
    db.commit()

    r1 = client.post(
        "/v1/accounts/orgs/p5-credit-org-1/consume-credits",
        headers=owner_hdrs,
        json={"credit_type": "lead", "amount": 4, "idempotency_key": "batch-1", "reason": "lead_enrichment"},
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["consumed"] == 4
    assert b1["credits_remaining"] == 6
    assert b1["ledger_entry_id"] is not None

    # Idempotent replay must NOT double debit
    r2 = client.post(
        "/v1/accounts/orgs/p5-credit-org-1/consume-credits",
        headers=owner_hdrs,
        json={"credit_type": "lead", "amount": 4, "idempotency_key": "batch-1", "reason": "lead_enrichment"},
    )
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["ledger_entry_id"] == b1["ledger_entry_id"]
    assert b2["credits_remaining"] == 6

    # Conflicting amount with same idempotency_key must fail 409
    r_conflict = client.post(
        "/v1/accounts/orgs/p5-credit-org-1/consume-credits",
        headers=owner_hdrs,
        json={"credit_type": "lead", "amount": 2, "idempotency_key": "batch-1"},
    )
    assert r_conflict.status_code == 409

    # Overdraft must fail 402 and leave used unchanged
    r_over = client.post(
        "/v1/accounts/orgs/p5-credit-org-1/consume-credits",
        headers=owner_hdrs,
        json={"credit_type": "lead", "amount": 7},
    )
    assert r_over.status_code == 402

    ledger_rows = db.query(CreditLedgerRecord).filter_by(org_id="p5-credit-org-1").all()
    assert len(ledger_rows) == 1
    assert ledger_rows[0].entry_type == "DEBIT"
    assert ledger_rows[0].credit_pool == "lead_credits"
    assert ledger_rows[0].delta == -4
    assert ledger_rows[0].balance_after == 6

    db.expire_all()
    refreshed_org = db.query(OrganizationRecord).filter_by(id="p5-credit-org-1").first()
    assert refreshed_org.lead_credits_used == 4


def test_p5_catalog_bound_templates_and_invalid_sku_rejection(p5_client) -> None:
    """Verify P5 templates match live CATALOG/MODULAR_SME_TIERS pricing and reject fake SKUs."""
    client, _ = p5_client
    owner_hdrs = {"X-API-Key": OWNER_KEY}

    tpls_res = client.get("/v1/p5/scale/templates", headers=owner_hdrs)
    assert tpls_res.status_code == 200, tpls_res.text
    tpls = {t["template_key"]: t for t in tpls_res.json()["templates"]}
    assert "india_agency_starter" in tpls

    starter = tpls["india_agency_starter"]
    expected_quote = compose_modular_pricing(
        base_plan_key=starter["tier_id"],
        selected_modules=starter["selected_modules"],
        currency="INR",
    )
    assert starter["monthly_price_inr"] == expected_quote["total_recurring_price"]

    bad_tpl = client.post(
        "/v1/p5/scale/templates",
        headers=owner_hdrs,
        json={
            "template_key": "invalid_fake_pack",
            "name": "Fake Pack",
            "industry": "retail",
            "tier_id": "launch",
            "selected_modules": ["seo"],
            "catalog_service_ids": ["nonexistent_catalog_sku"],
        },
    )
    assert bad_tpl.status_code == 422


def test_p5_idempotent_provisioning_fsm_and_failure_recovery(p5_client) -> None:
    """Verify 9-state provisioning FSM idempotency, PRODUCTION guard, failure capture, and retry recovery."""
    client, db = p5_client
    owner_hdrs = {"X-API-Key": OWNER_KEY}

    prod_blocked = client.post(
        "/v1/p5/scale/provisioning",
        headers=owner_hdrs,
        json={
            "template_key": "india_agency_starter",
            "idempotency_key": f"prod-prov-{uuid.uuid4().hex[:8]}",
            "company_name": "Prod Blocked Co",
            "execution_mode": "PRODUCTION",
        },
    )
    assert prod_blocked.status_code == 403

    # Inject simulated step failure -> FAILED with partial steps preserved -> retry recovers to ACTIVE
    idem_key = f"fail-recover-{uuid.uuid4().hex[:8]}"
    fail_res = client.post(
        "/v1/p5/scale/provisioning",
        headers=owner_hdrs,
        json={
            "template_key": "india_agency_starter",
            "idempotency_key": idem_key,
            "company_name": "Recoverable SME Pvt Ltd",
            "execution_mode": "SIMULATION",
            "simulate_fail_at_step": "CONNECTORS_STAGED",
        },
    )
    assert fail_res.status_code == 200, fail_res.text
    failed_run = fail_res.json()
    assert failed_run["state"] == "FAILED"
    assert failed_run["failed_step"] == "CONNECTORS_STAGED"
    assert failed_run["completed_steps"] == ["ORG_CREATED", "SUBSCRIPTION_BOUND", "TEMPLATES_APPLIED"]
    created_org_id = failed_run["org_id"]
    assert created_org_id

    # Idempotent replay of same key does NOT create duplicate org
    replay_res = client.post(
        "/v1/p5/scale/provisioning",
        headers=owner_hdrs,
        json={
            "template_key": "india_agency_starter",
            "idempotency_key": idem_key,
            "company_name": "Recoverable SME Pvt Ltd",
            "execution_mode": "SIMULATION",
        },
    )
    assert replay_res.status_code == 200
    assert replay_res.json()["idempotent_replay"] is True
    assert replay_res.json()["run_id"] == failed_run["run_id"]

    # Retry resumes from CONNECTORS_STAGED and completes all 5 steps -> ACTIVE
    retry_res = client.post(
        f"/v1/p5/scale/provisioning/{failed_run['run_id']}/retry",
        headers=owner_hdrs,
        json={},
    )
    assert retry_res.status_code == 200, retry_res.text
    recovered = retry_res.json()
    assert recovered["state"] == "ACTIVE"
    assert recovered["attempt_count"] == 2
    assert recovered["completed_steps"] == [
        "ORG_CREATED",
        "SUBSCRIPTION_BOUND",
        "TEMPLATES_APPLIED",
        "CONNECTORS_STAGED",
        "HEALTH_CHECKED",
    ]
    assert recovered["config_snapshot"]["health_status"] == "HEALTHY"


def test_p5_tenant_policy_quota_throttling_incidents_and_isolation(p5_client) -> None:
    """Verify tenant policy enforcement, quota auto-throttle, SLA incidents, and strict tenant isolation."""
    client, _ = p5_client
    owner_hdrs = {"X-API-Key": OWNER_KEY}

    t1 = _create_tenant(client, "t1@alpha-p5.in", "Alpha P5")
    t2 = _create_tenant(client, "t2@beta-p5.in", "Beta P5")

    up_pol = client.put(
        f"/v1/p5/scale/policies/{t1['org_id']}",
        headers=t1["headers"],
        json={"rate_limit_rpm": 50, "auto_throttle_on_breach": True, "sla_response_minutes": 120},
    )
    assert up_pol.status_code == 200, up_pol.text
    assert up_pol.json()["rate_limit_rpm"] == 50

    ok_eval = client.post(
        "/v1/p5/scale/quota-check",
        headers=t1["headers"],
        json={"metric_type": "rate_limit_rpm", "observed_value": 42},
    )
    assert ok_eval.status_code == 200
    assert ok_eval.json()["breached"] is False
    assert ok_eval.json()["action_taken"] == "ALLOWED"

    breach_eval = client.post(
        "/v1/p5/scale/quota-check",
        headers=t1["headers"],
        json={"metric_type": "rate_limit_rpm", "observed_value": 65},
    )
    assert breach_eval.status_code == 200
    assert breach_eval.json()["breached"] is True
    assert breach_eval.json()["action_taken"] == "THROTTLED"

    inc = client.post(
        "/v1/p5/scale/incidents",
        headers=t1["headers"],
        json={"title": "API Latency Spike", "severity": "SEV1_CRITICAL", "category": "SLA_DEGRADATION"},
    )
    assert inc.status_code == 200, inc.text
    inc_id = inc.json()["incident_id"]
    assert inc.json()["status"] == "OPEN"
    assert inc.json()["sla_due_at"] is not None

    # Cross-tenant isolation: Tenant 2 cannot read Tenant 1 policy or transition Tenant 1 incident
    cross_pol = client.get(f"/v1/p5/scale/policies/{t1['org_id']}", headers=t2["headers"])
    assert cross_pol.status_code == 403

    cross_inc = client.post(
        f"/v1/p5/scale/incidents/{inc_id}/transition",
        headers=t2["headers"],
        json={"target_status": "RESOLVED"},
    )
    assert cross_inc.status_code in (403, 404)

    mit = client.post(
        f"/v1/p5/scale/incidents/{inc_id}/transition",
        headers=t1["headers"],
        json={"target_status": "MITIGATING", "mitigation_notes": "Scaled worker pool"},
    )
    assert mit.status_code == 200
    res = client.post(
        f"/v1/p5/scale/incidents/{inc_id}/transition",
        headers=t1["headers"],
        json={"target_status": "RESOLVED", "root_cause": "Transient burst"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "RESOLVED"
    assert res.json()["resolved_at"] is not None

    # Execute both P5 registered agents via unified registry + check UI wiring
    for aid in ("tenant_provisioning_agent", "sla_operations_agent"):
        r = client.post(f"/v1/registry/agents/{aid}/execute", headers=owner_hdrs, json={"execution_mode": "SIMULATION", "input_payload": {}})
        assert r.status_code == 200, f"{aid} failed: {r.text}"
        assert r.json()["evidence"]["agent_id"] == aid

    root = Path(__file__).resolve().parent.parent
    html_text = (root / "app" / "dashboard" / "index.html").read_text(encoding="utf-8")
    js_text = (root / "app" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
    assert "page-p5-scale" in html_text
    assert "nav-p5-scale" in html_text
    assert "p5LoadControlCentre" in js_text
