"""P6 Multi-Industry SME Packs & India SEO Baseline test suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import migrations.versions.l2a7b8c9d0e1_add_p6_industry_packs_tables as p6_migration
from app.db.database import Base, get_db
from app.main import app
from app.services.billing_ledger import compose_modular_pricing

OWNER_KEY = "p6-packs-owner-key-32-chars!!!!!!"
MANAGER_KEY = "p6-packs-manager-key-32-chars!!!!"
JWT_SECRET = "p6-packs-jwt-secret-32-chars!!!!!"


@pytest.fixture()
def p6_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Session]:
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


def test_p6_alembic_migration_upgrade_and_downgrade_parity() -> None:
    """Verify l2a7b8c9d0e1 creates all 3 P6 tables and indexes cleanly and downgrades cleanly."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn)
        op = Operations(ctx)
        orig_op = p6_migration.op
        p6_migration.op = op
        try:
            p6_migration.upgrade()
            conn.commit()
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            expected = {"p6_industry_packs", "p6_tenant_pack_deployments", "p6_seo_baselines"}
            assert expected <= tables
            assert "ix_p6_pack_sector_readiness" in {ix["name"] for ix in insp.get_indexes("p6_industry_packs")}
            assert "ix_p6_dep_org_pack" in {ix["name"] for ix in insp.get_indexes("p6_tenant_pack_deployments")}
            assert "ix_p6_seo_org_vertical" in {ix["name"] for ix in insp.get_indexes("p6_seo_baselines")}

            p6_migration.downgrade()
            conn.commit()
            remaining = set(inspect(conn).get_table_names())
            assert not (expected & remaining)
        finally:
            p6_migration.op = orig_op


def test_p6_five_sme_packs_honest_readiness_and_catalog_pricing(p6_client) -> None:
    """Verify all 5 SME packs bind real catalog pricing and reject fabricated LIVE_VERIFIED claims."""
    client, _ = p6_client
    owner_hdrs = {"X-API-Key": OWNER_KEY}

    res = client.get("/v1/p6/packs/catalog", headers=owner_hdrs)
    assert res.status_code == 200, res.text
    packs = {p["pack_key"]: p for p in res.json()["packs"]}
    expected_keys = {
        "distribution_wholesale",
        "logistics_warehousing",
        "manufacturing",
        "retail_commerce",
        "professional_services",
    }
    assert expected_keys <= set(packs.keys())
    for key in expected_keys:
        p = packs[key]
        assert p["readiness_status"] in ("SANDBOX", "ROADMAP")
        assert p["verified_live_customers"] == 0
        expected_quote = compose_modular_pricing(
            base_plan_key=p["tier_id"],
            selected_modules=p["selected_modules"],
            currency="INR",
        )
        assert p["monthly_price_inr"] == expected_quote["total_recurring_price"]

    fake_live = client.post(
        "/v1/p6/packs/catalog",
        headers=owner_hdrs,
        json={
            "pack_key": "unverified_live_attempt",
            "name": "Fake Live Pack",
            "sector": "manufacturing",
            "tier_id": "operations",
            "selected_modules": ["inventory"],
            "catalog_service_ids": ["warehouse_automation"],
            "agent_ids": ["warehouse_stocksense_agent"],
            "analytics_capabilities": ["warehouse_stocksense"],
            "readiness_status": "LIVE_VERIFIED",
            "verified_live_customers": 0,
        },
    )
    assert fake_live.status_code == 422


def test_p6_vertical_pack_deployments_diagnostics_and_isolation(p6_client) -> None:
    """Verify deploying wholesale, logistics, and manufacturing packs executes live vertical analytics cleanly."""
    client, _ = p6_client
    t1 = _create_tenant(client, "t1@ind-p6.in", "Bharat Logistics & Agro")
    t2 = _create_tenant(client, "t2@other-p6.in", "Other Tenant")

    for pack_key, expected_mod in (
        ("distribution_wholesale", "warehouse_stocksense"),
        ("logistics_warehousing", "field_force_ops"),
        ("manufacturing", "digital_qa_benchmark"),
    ):
        dep = client.post(
            "/v1/p6/packs/deployments",
            headers=t1["headers"],
            json={"pack_key": pack_key, "execution_mode": "SIMULATION"},
        )
        assert dep.status_code == 200, dep.text
        dep_id = dep.json()["deployment_id"]
        assert dep.json()["readiness_label"] in ("SANDBOX", "ROADMAP")

        diag = client.post(f"/v1/p6/packs/deployments/{dep_id}/diagnostics", headers=t1["headers"], json={})
        assert diag.status_code == 200, diag.text
        body = diag.json()
        assert body["status"] == "SANDBOX_VALIDATED"
        assert body["last_analytics_output"]["data_classification"] == "SANDBOX_SIMULATION"
        assert expected_mod in body["last_analytics_output"]["modules_executed"]

    # Cross-tenant isolation: Tenant 2 cannot run diagnostics on Tenant 1's deployment
    t1_deps = client.get("/v1/p6/packs/overview", headers=t1["headers"]).json()["deployments"]
    blocked = client.post(
        f"/v1/p6/packs/deployments/{t1_deps[0]['deployment_id']}/diagnostics",
        headers=t2["headers"],
        json={},
    )
    assert blocked.status_code in (403, 404)


def test_p6_india_seo_baseline_agent_execution_and_ui_wiring(p6_client) -> None:
    """Verify catalog-grounded India SEO baselines reject bad SKUs/claims, execute agent, and verify UI."""
    client, _ = p6_client
    owner_hdrs = {"X-API-Key": OWNER_KEY}
    t1 = _create_tenant(client, "seo@agency-p6.in", "Bengaluru Agency")

    bad_sku = client.post(
        "/v1/p6/packs/seo-baselines",
        headers=t1["headers"],
        json={
            "city_or_cluster": "Bengaluru",
            "industry_vertical": "professional_services",
            "primary_catalog_sku": "invented_fake_sku",
        },
    )
    assert bad_sku.status_code == 422

    bad_claim = client.post(
        "/v1/p6/packs/seo-baselines",
        headers=t1["headers"],
        json={
            "city_or_cluster": "Mumbai",
            "industry_vertical": "retail_commerce",
            "primary_catalog_sku": "seo_blog_copilot",
            "target_keywords": ["10x roi guaranteed instant results"],
        },
    )
    assert bad_claim.status_code == 422

    ok_seo = client.post(
        "/v1/p6/packs/seo-baselines",
        headers=t1["headers"],
        json={
            "city_or_cluster": "Bengaluru",
            "industry_vertical": "professional_services",
            "primary_catalog_sku": "seo_blog_copilot",
            "business_name": "Bengaluru Agency",
        },
    )
    assert ok_seo.status_code == 200, ok_seo.text
    seo_data = ok_seo.json()
    assert seo_data["schema_markup"]["offers"]["price"] == 1999
    assert seo_data["baseline_status"] == "SANDBOX_DRAFT"

    ag = client.post(
        "/v1/registry/agents/industry_pack_architect_agent/execute",
        headers=owner_hdrs,
        json={"execution_mode": "SIMULATION", "input_payload": {}},
    )
    assert ag.status_code == 200, ag.text
    assert ag.json()["evidence"]["agent_id"] == "industry_pack_architect_agent"

    root = Path(__file__).resolve().parent.parent
    html_text = (root / "app" / "dashboard" / "index.html").read_text(encoding="utf-8")
    js_text = (root / "app" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
    assert "page-p6-packs" in html_text
    assert "nav-p6-packs" in html_text
    assert "p6LoadControlCentre" in js_text
