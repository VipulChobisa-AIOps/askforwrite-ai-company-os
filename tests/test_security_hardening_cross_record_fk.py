"""Adversarial Phase E tests: P2/P4-P6 cross-record ownership, inactive-org guards, and DB-level FK enforcement."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    InvoiceRecord,
    LeadRecordRow,
    OrganizationRecord,
    P2CommercialProposalRecord,
    P4GrowthCampaignRecord,
    P4IcpProfileRecord,
    P4MarketIntelRecord,
    P4PipelineDealRecord,
    P8DeveloperProfileRecord,
    P8MarketplaceListingRecord,
    P8TenantInstallRecord,
    TaskRecord,
)
from app.main import app
from app.services.p2_customer_ops import create_customer_engagement_after_settlement

OWNER_KEY = "phase-e-owner-key-32-characters!"
MANAGER_KEY = "phase-e-manager-key-32-chars!!!!"
JWT_SECRET = "phase-e-jwt-secret-32-chars!!!!!"


@pytest.fixture()
def phase_e_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Session]:
    monkeypatch.setenv("OWNER_API_KEY", OWNER_KEY)
    monkeypatch.setenv("MANAGER_API_KEY", MANAGER_KEY)
    monkeypatch.setenv("JWT_SECRET_KEY", JWT_SECRET)

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _enable_sqlite_fks(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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
        json={
            "email": email,
            "password": "StrongPassword!123",
            "full_name": "Tenant Operator",
            "company_name": company,
        },
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()
    return {"org_id": data["org_id"], "headers": {"Authorization": f"Bearer {data['access_token']}"}}


def test_p4_cross_tenant_optional_references_blocked_403_and_missing_404(phase_e_client) -> None:
    """P4 intel, campaign, and deal endpoints reject cross-org optional FKs (403) and missing refs (404)."""
    client, db = phase_e_client
    t1 = _create_tenant(client, "t1p4@example.in", "Tenant One GTM")
    t2 = _create_tenant(client, "t2p4@example.in", "Tenant Two GTM")

    # Tenant 1 creates ICP, campaign, and lead
    icp1 = client.post(
        "/v1/p4/growth/icps",
        headers=t1["headers"],
        json={"name": "India Distribution ICP", "industry": "Wholesale Distribution"},
    )
    assert icp1.status_code == 200, icp1.text
    icp1_id = icp1.json()["icp_id"]

    camp1 = client.post(
        "/v1/p4/growth/campaigns",
        headers=t1["headers"],
        json={
            "icp_id": icp1_id,
            "name": "T1 Campaign",
            "objective": "Pipeline generation",
            "product_name": "AskforWrite AI Company OS",
            "target_audience": "B2B Wholesalers",
        },
    )
    assert camp1.status_code == 200, camp1.text
    camp1_id = camp1.json()["campaign_id"]

    t1_task = TaskRecord(id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()), objective="Lead 1", status="COMPLETED")
    db.add(t1_task)
    db.flush()
    lead1 = LeadRecordRow(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        domain="t1-buyer.in",
        task_id=t1_task.id,
        company="T1 Buyer Pvt Ltd",
        website="https://t1-buyer.in",
        industry="Wholesale",
        geography="India",
        status="DISCOVERED",
    )
    db.add(lead1)
    db.commit()

    # Tenant 2 cannot reference Tenant 1's icp_id in market intel or campaigns
    cross_intel = client.post(
        "/v1/p4/growth/intel",
        headers=t2["headers"],
        json={
            "icp_id": icp1_id,
            "intel_type": "MARKET_TREND",
            "subject_name": "Cross Probe",
            "summary": "Attempting to link Tenant 1 ICP into Tenant 2 intel",
        },
    )
    assert cross_intel.status_code == 403

    cross_camp = client.post(
        "/v1/p4/growth/campaigns",
        headers=t2["headers"],
        json={
            "icp_id": icp1_id,
            "name": "Cross Camp",
            "objective": "Cross tenant hijack",
            "product_name": "AskforWrite AI Company OS",
            "target_audience": "Distributors",
        },
    )
    assert cross_camp.status_code == 403

    # Tenant 2 cannot reference Tenant 1's lead_id, campaign_id, or icp_id when creating a deal
    for bad_ref in ({"lead_id": lead1.id}, {"campaign_id": camp1_id}, {"icp_id": icp1_id}):
        cross_deal = client.post(
            "/v1/p4/growth/deals",
            headers=t2["headers"],
            json={"company_name": "Cross Deal Corp", **bad_ref},
        )
        assert cross_deal.status_code == 403, f"Expected 403 for {bad_ref}, got {cross_deal.status_code}: {cross_deal.text}"

    # Nonexistent IDs fail cleanly with 404
    missing_deal = client.post(
        "/v1/p4/growth/deals",
        headers=t2["headers"],
        json={"company_name": "Missing Ref Corp", "icp_id": "nonexistent-icp-id"},
    )
    assert missing_deal.status_code == 404


def test_p2_customer_ops_cross_tenant_reference_validation(phase_e_client) -> None:
    """P2 customer engagement creation rejects cross-tenant lead, invoice, and proposal links."""
    client, db = phase_e_client
    t1 = _create_tenant(client, "t1p2@example.in", "Tenant One P2")
    t2 = _create_tenant(client, "t2p2@example.in", "Tenant Two P2")

    t1_task = TaskRecord(id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()), objective="P2 Lead", status="COMPLETED")
    db.add(t1_task)
    db.flush()
    t1_lead = LeadRecordRow(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        domain="t1p2.in",
        task_id=t1_task.id,
        company="T1 P2 Co",
        website="https://t1p2.in",
        industry="Retail",
        geography="India",
        status="DISCOVERED",
    )
    t1_inv = InvoiceRecord(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        customer_id="cust-1",
        provider="razorpay",
        provider_invoice_id="inv_t1_001",
        amount=499900,
        currency="INR",
        status="paid",
    )
    t1_prop = P2CommercialProposalRecord(
        id=str(uuid.uuid4()),
        lead_id=t1_lead.id,
        org_id=t1["org_id"],
        sku_key="managed_seo_content_pilot",
        title="T1 Pilot Proposal",
        customer_problem="Organic acquisition gap",
        scope_summary="Pilot scope",
        status="SHARED",
    )
    db.add_all([t1_lead, t1_inv, t1_prop])
    db.commit()

    with pytest.raises(PermissionError, match="lead_id"):
        create_customer_engagement_after_settlement(db, org_id=t2["org_id"], lead_id=t1_lead.id)

    with pytest.raises(PermissionError, match="invoice_id"):
        create_customer_engagement_after_settlement(db, org_id=t2["org_id"], invoice_id=t1_inv.id)

    with pytest.raises(PermissionError, match="proposal_id"):
        create_customer_engagement_after_settlement(db, org_id=t2["org_id"], proposal_id=t1_prop.id)


def test_p4_p5_p6_inactive_org_and_role_isolation(phase_e_client) -> None:
    """Deactivated orgs are blocked from P4/P5/P6 mutations and platform_admin/manager scope works."""
    client, db = phase_e_client
    t1 = _create_tenant(client, "t1p56@example.in", "Tenant P56")

    org = db.get(OrganizationRecord, t1["org_id"])
    assert org is not None
    org.is_active = False
    db.commit()

    # Inactive tenant rejected across P4, P5, P6
    assert (
        client.post(
            "/v1/p4/growth/icps",
            headers=t1["headers"],
            json={"name": "Blocked ICP", "industry": "Manufacturing"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/p5/scale/incidents",
            headers=t1["headers"],
            json={"title": "Blocked Incident"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/p6/packs/deployments",
            headers=t1["headers"],
            json={"pack_key": "distribution_wholesale"},
        ).status_code
        == 403
    )
    # Non-owner tenant cannot mutate platform template/catalog routes
    org.is_active = True
    db.commit()
    assert client.post("/v1/p5/scale/templates/seed", headers=t1["headers"]).status_code == 403
    assert (
        client.post(
            "/v1/p6/packs/catalog",
            headers=t1["headers"],
            json={"pack_key": "x", "name": "Unauth", "sector": "retail", "tier_id": "launch"},
        ).status_code
        == 403
    )
    # Platform manager allowed on scoped tenant read overviews via is_platform_operator
    mgr_hdrs = {"X-API-Key": MANAGER_KEY}
    assert client.get(f"/v1/p5/scale/overview?org_id={t1['org_id']}", headers=mgr_hdrs).status_code == 200
    assert client.get(f"/v1/p6/packs/overview?org_id={t1['org_id']}", headers=mgr_hdrs).status_code == 200


def test_db_level_foreign_key_constraints_enforced(phase_e_client) -> None:
    """SQLite/PostgreSQL FK constraints reject orphan writes, restrict active parents, and SET NULL on P4 ICP delete."""
    client, db = phase_e_client
    t1 = _create_tenant(client, "fk@example.in", "FK Constraint Org")

    # 1. Dangling FK on P4 deals rejected at DB constraint level
    orphan_deal = P4PipelineDealRecord(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        icp_id="missing-icp-fk",
        company_name="Orphan Deal",
    )
    db.add(orphan_deal)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # 2. Valid P4 ICP + child records; deleting ICP sets child FKs to NULL cleanly (ondelete=SET NULL)
    icp = P4IcpProfileRecord(id=str(uuid.uuid4()), org_id=t1["org_id"], name="FK ICP", industry="Logistics")
    db.add(icp)
    db.flush()
    intel = P4MarketIntelRecord(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        icp_id=icp.id,
        intel_type="MARKET_TREND",
        subject_name="Logistics Trend",
        summary="Growing regional fleet SaaS demand",
    )
    camp = P4GrowthCampaignRecord(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        icp_id=icp.id,
        name="FK Camp",
        objective="Grow logistics SMEs",
    )
    deal = P4PipelineDealRecord(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        icp_id=icp.id,
        campaign_id=camp.id,
        company_name="Valid Buyer",
    )
    db.add_all([intel, camp, deal])
    db.commit()

    db.delete(icp)
    db.commit()
    db.expire_all()
    assert db.get(P4MarketIntelRecord, intel.id).icp_id is None
    assert db.get(P4GrowthCampaignRecord, camp.id).icp_id is None
    assert db.get(P4PipelineDealRecord, deal.id).icp_id is None

    # 3. P8 RESTRICT FKs block deleting developer or listing while children exist
    dev = P8DeveloperProfileRecord(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        developer_name="FK Dev",
        contact_email="fkdev@example.in",
        legal_entity_name="FK Dev LLP",
    )
    db.add(dev)
    db.flush()
    listing = P8MarketplaceListingRecord(
        id=str(uuid.uuid4()),
        developer_id=dev.id,
        listing_slug="fk-plugin",
        name="FK Plugin",
        manifest_json={"name": "FK Plugin"},
        manifest_sha256="0" * 64,
        ecdsa_signature_hex="deadbeef",
        signing_public_key_pem="pem",
    )
    db.add(listing)
    db.flush()
    install = P8TenantInstallRecord(id=str(uuid.uuid4()), org_id=t1["org_id"], listing_id=listing.id)
    db.add(install)
    db.commit()

    db.delete(listing)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.delete(dev)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
