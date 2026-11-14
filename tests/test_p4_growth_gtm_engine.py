"""P4 Repeatable Growth & GTM Engine test suite."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import migrations.versions.j0e5f6a7b8c9_add_p4_growth_gtm_tables as p4_migration
from app.db.database import Base, get_db
from app.main import app
from app.services.growth_engine import (
    generate_and_stage_blog,
    generate_creative_assets,
    generate_omnichannel_social_campaign,
    handle_inbound_sales_chat,
)
from app.services.previews import VERTICAL_BENCHMARKS, generate_trojan_horse_preview

OWNER_KEY = "p4-growth-owner-key-32-chars!!!!!"
MANAGER_KEY = "p4-growth-manager-key-32-chars!!!"
JWT_SECRET = "p4-growth-jwt-secret-32-chars!!!!"


@pytest.fixture()
def p4_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Session]:
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


def test_p4_alembic_migration_upgrade_and_downgrade_parity() -> None:
    """Verify j0e5f6a7b8c9 creates all 4 P4 tables cleanly and downgrades cleanly."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn)
        op = Operations(ctx)
        orig_op = p4_migration.op
        p4_migration.op = op
        try:
            p4_migration.upgrade()
            conn.commit()
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            assert {"p4_icp_profiles", "p4_market_intel_records", "p4_growth_campaigns", "p4_pipeline_deals"} <= tables
            icp_idx = {ix["name"] for ix in insp.get_indexes("p4_icp_profiles")}
            intel_idx = {ix["name"] for ix in insp.get_indexes("p4_market_intel_records")}
            camp_idx = {ix["name"] for ix in insp.get_indexes("p4_growth_campaigns")}
            deal_idx = {ix["name"] for ix in insp.get_indexes("p4_pipeline_deals")}
            assert "ix_p4_icp_org_status" in icp_idx
            assert "ix_p4_intel_org_type" in intel_idx
            assert "ix_p4_campaign_org_status" in camp_idx
            assert "ix_p4_deal_org_stage_origin" in deal_idx

            p4_migration.downgrade()
            conn.commit()
            remaining = set(inspect(conn).get_table_names())
            assert not ({"p4_icp_profiles", "p4_market_intel_records", "p4_growth_campaigns", "p4_pipeline_deals"} & remaining)
        finally:
            p4_migration.op = orig_op


def test_p4_unverified_marketing_claims_removed_from_growth_engine_and_previews(p4_client) -> None:
    """Ensure deprecated growth_engine and preview strings contain zero unverified guarantees/multipliers."""
    _, db = p4_client
    creatives = generate_creative_assets("Acme OS", "SME Founders")
    blog = generate_and_stage_blog("Acme OS", "SME Founders", ["ai workflow"])
    social = generate_omnichannel_social_campaign("Acme OS", "SME Founders", ["ai workflow"])
    closer = handle_inbound_sales_chat(
        db,
        session_id=f"sess-{uuid.uuid4().hex[:8]}",
        prospect_name="Riya",
        prospect_contact="riya@example.com",
        message="This seems expensive",
    )
    preview = generate_trojan_horse_preview(
        db,
        domain="acme-agency.in",
        company_name="Acme Agency",
        recommended_package="seo_blog_copilot",
    )

    corpus = " ".join([
        str(creatives),
        str(blog),
        str(social),
        str(closer),
        str(preview),
        str(VERTICAL_BENCHMARKS),
    ]).lower()
    for banned in ("+340%", "100% refund", "guaranteed inclusion", "99.4% within 3s", "0 proxy attendance", "10x roi", "8x roi"):
        assert banned not in corpus, f"Unverified marketing claim still present: {banned}"


def test_p4_icp_scoring_and_cross_tenant_isolation(p4_client) -> None:
    """ICPs must score prospects transparently and enforce strict tenant isolation."""
    client, _ = p4_client
    t_a = _create_tenant(client, "icp-a@acme.test", "Alpha Logistics")
    t_b = _create_tenant(client, "icp-b@beta.test", "Beta Retail")

    # Reject exaggerated claim inside ICP value propositions
    bad_icp = client.post(
        "/v1/p4/growth/icps",
        headers=t_a["headers"],
        json={
            "name": "Bad ICP",
            "industry": "Logistics",
            "value_propositions": ["Guaranteed 10x ROI and 100% refund"],
        },
    )
    assert bad_icp.status_code == 422

    ok_icp = client.post(
        "/v1/p4/growth/icps",
        headers=t_a["headers"],
        json={
            "name": "India Distribution SMEs",
            "industry": "Wholesale Distribution",
            "geography": "India",
            "pain_points": ["manual stockouts", "slow invoicing"],
            "disqualifiers": ["gambling"],
        },
    )
    assert ok_icp.status_code == 200, ok_icp.text
    icp_id = ok_icp.json()["icp_id"]

    score_res = client.post(
        f"/v1/p4/growth/icps/{icp_id}/score",
        headers=t_a["headers"],
        json={
            "company_name": "Jaipur Traders",
            "industry": "Wholesale Distribution",
            "geography": "Jaipur, India",
            "signals": ["facing manual stockouts each quarter"],
        },
    )
    assert score_res.status_code == 200
    assert score_res.json()["qualified"] is True
    assert score_res.json()["fit_score"] >= 0.65

    # Cross-tenant score or listing blocked
    cross_list = client.get("/v1/p4/growth/icps", headers=t_b["headers"])
    assert cross_list.status_code == 200
    assert cross_list.json()["count"] == 0
    cross_score = client.post(
        f"/v1/p4/growth/icps/{icp_id}/score",
        headers=t_b["headers"],
        json={"company_name": "Other", "industry": "Retail", "geography": "India"},
    )
    assert cross_score.status_code == 404


def test_p4_market_intel_provenance_and_ssrf_guard(p4_client) -> None:
    """VERIFIED_SOURCE intel requires HTTPS source_url + evidence_ref and rejects loopback SSRF URLs."""
    client, _ = p4_client
    owner_hdrs = {"X-API-Key": OWNER_KEY}

    # Missing provenance fails 422
    no_prov = client.post(
        "/v1/p4/growth/intel",
        headers=owner_hdrs,
        json={
            "intel_type": "COMPETITOR",
            "subject_name": "Rival SaaS",
            "summary": "Claims unlimited seats",
            "confidence_level": "VERIFIED_SOURCE",
        },
    )
    assert no_prov.status_code == 422

    # Loopback SSRF URL fails 422
    ssrf_intel = client.post(
        "/v1/p4/growth/intel",
        headers=owner_hdrs,
        json={
            "intel_type": "COMPETITOR",
            "subject_name": "Local Probe",
            "summary": "Attempt loopback",
            "source_url": "http://127.0.0.1:8000/internal",
            "evidence_ref": "ev-1",
            "confidence_level": "VERIFIED_SOURCE",
        },
    )
    assert ssrf_intel.status_code == 422

    # Valid provenance accepted
    ok = client.post(
        "/v1/p4/growth/intel",
        headers=owner_hdrs,
        json={
            "intel_type": "COMPETITOR",
            "subject_name": "AgencyTool Inc",
            "summary": "Public pricing page shows ₹14,999/mo starter plan",
            "source_url": "https://example.com/pricing",
            "evidence_ref": "capture-2026-11-14",
            "confidence_level": "VERIFIED_SOURCE",
            "verified_facts": ["Listed INR 14,999 starter tier on public page"],
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["confidence_level"] == "VERIFIED_SOURCE"


def test_p4_campaign_hitl_gate_and_actual_vs_sandbox_funnel_analytics(p4_client) -> None:
    """Campaign execution is blocked until Owner HITL approval; analytics never mixes SANDBOX into ACTUAL."""
    client, _ = p4_client
    owner_hdrs = {"X-API-Key": OWNER_KEY}

    # Unsafe copy override blocked cleanly
    bad_camp = client.post(
        "/v1/p4/growth/campaigns",
        headers=owner_hdrs,
        json={
            "name": "Hype Campaign",
            "objective": "Test filter",
            "product_name": "Growth OS",
            "target_audience": "SMEs",
            "custom_copy_overrides": {"cta": "Guaranteed inclusion and 100% refund"},
        },
    )
    assert bad_camp.status_code == 422

    camp = client.post(
        "/v1/p4/growth/campaigns",
        headers=owner_hdrs,
        json={
            "name": "Q4 India Agency GTM",
            "objective": "Stage compliant SEO & LinkedIn outbound sequence",
            "product_name": "SEO Blog Copilot",
            "target_audience": "Digital Agencies in Bengaluru",
            "keywords": ["b2b seo copilot", "wordpress draft automation"],
        },
    )
    assert camp.status_code == 200, camp.text
    camp_id = camp.json()["campaign_id"]
    approval_id = camp.json()["approval_id"]
    assert camp.json()["status"] == "PENDING_APPROVAL"

    # Cannot execute while ApprovalRequest is PENDING
    blocked = client.post(f"/v1/p4/growth/campaigns/{camp_id}/execute", headers=owner_hdrs, json={"execution_mode": "SIMULATION"})
    assert blocked.status_code == 403

    # Approve via standard HITL approval endpoint -> SIMULATION execution succeeds; LIVE remains blocked in test guard
    dec = client.post(
        f"/v1/approvals/{approval_id}/decision",
        headers=owner_hdrs,
        json={"decision": "APPROVED", "reason": "Copy reviewed by owner"},
    )
    assert dec.status_code == 200, dec.text

    live_blocked = client.post(f"/v1/p4/growth/campaigns/{camp_id}/execute", headers=owner_hdrs, json={"execution_mode": "LIVE"})
    assert live_blocked.status_code == 403

    sim_ok = client.post(f"/v1/p4/growth/campaigns/{camp_id}/execute", headers=owner_hdrs, json={"execution_mode": "SIMULATION"})
    assert sim_ok.status_code == 200, sim_ok.text
    assert sim_ok.json()["status"] == "EXECUTING_SANDBOX"

    # Pipeline Deals: LOST requires lost_reason; SANDBOX WON never pollutes ACTUAL metrics
    d_sbx = client.post(
        "/v1/p4/growth/deals",
        headers=owner_hdrs,
        json={"company_name": "Synthetic Deal Co", "deal_value_inr": 50000, "evidence_status": "SANDBOX", "campaign_id": camp_id},
    ).json()
    client.post(f"/v1/p4/growth/deals/{d_sbx['deal_id']}/transition", headers=owner_hdrs, json={"target_stage": "QUALIFIED"})
    client.post(f"/v1/p4/growth/deals/{d_sbx['deal_id']}/transition", headers=owner_hdrs, json={"target_stage": "PROPOSAL_SENT"})
    client.post(f"/v1/p4/growth/deals/{d_sbx['deal_id']}/transition", headers=owner_hdrs, json={"target_stage": "WON"})

    d_act = client.post(
        "/v1/p4/growth/deals",
        headers=owner_hdrs,
        json={"company_name": "Real Prospect Co", "deal_value_inr": 19999, "evidence_status": "ACTUAL"},
    ).json()
    bad_lost = client.post(f"/v1/p4/growth/deals/{d_act['deal_id']}/transition", headers=owner_hdrs, json={"target_stage": "LOST"})
    assert bad_lost.status_code == 422
    ok_lost = client.post(
        f"/v1/p4/growth/deals/{d_act['deal_id']}/transition",
        headers=owner_hdrs,
        json={"target_stage": "LOST", "lost_reason": "timing"},
    )
    assert ok_lost.status_code == 200

    analytics = client.get("/v1/p4/growth/analytics", headers=owner_hdrs).json()
    assert analytics["analytics_integrity"] == "SEPARATED_ACTUAL_VS_SANDBOX"
    assert analytics["actual_verified"]["won_deals"] == 0
    assert analytics["actual_verified"]["won_value_inr"] == 0.0
    assert analytics["actual_verified"]["lost_reason_breakdown"]["timing"] == 1
    assert analytics["sandbox_and_simulation"]["won_deals"] == 1
    assert analytics["sandbox_and_simulation"]["won_value_inr"] == 50000.0


def test_p4_agents_registered_and_executable_and_ui_wired(p4_client) -> None:
    """Verify gtm_strategist_agent & competitive_intel_agent execute via registry and dashboard contains P4 UI."""
    client, _ = p4_client
    owner_hdrs = {"X-API-Key": OWNER_KEY}

    for aid in ("gtm_strategist_agent", "competitive_intel_agent"):
        r = client.post(f"/v1/registry/agents/{aid}/execute", headers=owner_hdrs, json={"execution_mode": "SIMULATION", "input_payload": {}})
        assert r.status_code == 200, f"{aid} failed: {r.text}"
        assert r.json()["evidence"]["agent_id"] == aid

    ov = client.get("/v1/p4/growth/overview", headers=owner_hdrs)
    assert ov.status_code == 200
    assert "analytics" in ov.json()

    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    html_text = (root / "app" / "dashboard" / "index.html").read_text(encoding="utf-8")
    js_text = (root / "app" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
    assert "page-p4-growth" in html_text
    assert "nav-p4-growth" in html_text
    assert "p4LoadControlCentre" in js_text
