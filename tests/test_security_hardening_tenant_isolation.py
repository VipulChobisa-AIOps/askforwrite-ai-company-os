"""Adversarial multi-tenant isolation & fail-closed JWT/mobile bridge regression tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    ExecutionEvidenceRecord,
    FieldTaskRecord,
    GeofenceDefinition,
    LeadRecordRow,
    OrganizationRecord,
    OutreachRecord,
    P3GrowthOpportunityRecord,
    PreviewRecord,
    UserRecord,
    WorkflowDefinitionRecord,
    WorkflowRunRecord,
)
from app.main import app
from app.security.auth import create_access_token, hash_password

OWNER_KEY = "iso-owner-key-32-chars-minimum!!"
MANAGER_KEY = "iso-mgr-key-32-chars-minimum!!!!"
JWT_SECRET = "iso-jwt-secret-32-chars-minimum!"


@pytest.fixture()
def iso_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
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


def _signup_tenant_admin(client: TestClient, email: str, company: str) -> dict[str, Any]:
    res = client.post(
        "/v1/auth/signup",
        json={
            "company_name": company,
            "email": email,
            "password": "StrongPassword!123",
            "full_name": f"{company} Founder",
            "package_key": "growth_all_in_one",
            "payment_provider": "afw_directpay",
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["access_token"]
    return {
        "org_id": data["org_id"],
        "user_id": data["user_id"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
    }


def _seed_user_and_login(
    client: TestClient,
    db: Session,
    *,
    org_id: str,
    email: str,
    role: str,
    full_name: str = "Scoped User",
) -> tuple[UserRecord, dict[str, str]]:
    user = UserRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        email=email,
        full_name=full_name,
        role=role,
        password_hash=hash_password("StrongPassword!123"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    login_res = client.post("/v1/auth/login", json={"email": email, "password": "StrongPassword!123"})
    assert login_res.status_code == 200, login_res.text
    return user, {"Authorization": f"Bearer {login_res.json()['access_token']}"}


def test_cross_tenant_leads_outreach_previews_and_funnel_isolation(iso_client) -> None:
    client, db = iso_client
    t1 = _signup_tenant_admin(client, "lead-a@orga.in", "Org Alpha")
    t2 = _signup_tenant_admin(client, "lead-b@orgb.in", "Org Beta")

    lead_a = LeadRecordRow(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        domain="target-a.in",
        task_id=str(uuid.uuid4()),
        company="Target Alpha Pvt Ltd",
        website="https://target-a.in",
        industry="Manufacturing",
        geography="Pune, India",
        observed_signals=["slow_seo"],
        sources=[{"type": "manual"}],
        status="DISCOVERED",
    )
    outreach_a = OutreachRecord(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        lead_id=lead_a.id,
        task_id=lead_a.task_id,
        recipient_email="ceo@target-a.in",
        subject="SEO improvement brief",
        body_text="Hello from Org Alpha.",
        channel="email",
        status="PENDING_APPROVAL",
        idempotency_key=f"outreach-{uuid.uuid4().hex}",
    )
    preview_a = PreviewRecord(
        id=str(uuid.uuid4()),
        preview_token=f"tok_{uuid.uuid4().hex[:12]}",
        lead_id=lead_a.id,
        company_name="Target Alpha Pvt Ltd",
        domain="target-a.in",
        recommended_package="growth_all_in_one",
        custom_audit={"score": 70},
        sample_deliverable={},
        benchmarks={},
        payment_links={},
    )
    db.add_all([lead_a, outreach_a, preview_a])
    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id="lead_agent",
            capability_name="lead_discovery",
            action="create_lead",
            input_payload={"org_id": t1["org_id"], "secret": "alpha-only"},
            output_payload={"lead_id": lead_a.id},
            status="COMPLETED",
        )
    )
    db.commit()

    # Cross-tenant leads GET/PATCH/DELETE/enrich/query blocked with 403
    assert client.get(f"/v1/leads?org_id={t1['org_id']}", headers=t2["headers"]).status_code == 403
    assert client.get(f"/v1/leads/{lead_a.id}", headers=t2["headers"]).status_code == 403
    assert client.patch(f"/v1/leads/{lead_a.id}", headers=t2["headers"], json={"status": "QUALIFIED"}).status_code == 403
    assert client.delete(f"/v1/leads/{lead_a.id}", headers=t2["headers"]).status_code == 403
    assert (
        client.post(
            "/v1/leads/enrich",
            headers=t2["headers"],
            json={"lead_id": lead_a.id, "org_id": t2["org_id"]},
        ).status_code
        == 403
    )

    # Tenant B default lead listing sees zero Tenant A leads
    t2_leads = client.get("/v1/leads", headers=t2["headers"])
    assert t2_leads.status_code == 200, t2_leads.text
    assert all(row["org_id"] != t1["org_id"] for row in t2_leads.json()["leads"])

    # Cross-tenant outreach GET/draft/reply blocked with 403
    assert client.get(f"/v1/outreach?org_id={t1['org_id']}", headers=t2["headers"]).status_code == 403
    assert client.get(f"/v1/outreach/{outreach_a.id}", headers=t2["headers"]).status_code == 403
    assert (
        client.post(
            "/v1/outreach/draft",
            headers=t2["headers"],
            json={"lead_id": lead_a.id, "idempotency_key": f"cross-{uuid.uuid4().hex}"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/outreach/{outreach_a.id}/record-reply",
            headers=t2["headers"],
            json={"reply_text": "Interested in pricing", "intent": "interested"},
        ).status_code
        == 403
    )

    # Cross-tenant preview generation against Tenant A's lead blocked
    assert (
        client.post(
            "/v1/previews/generate",
            headers=t2["headers"],
            json={"company_name": "Target Alpha Pvt Ltd", "domain": "target-a.in", "lead_id": lead_a.id},
        ).status_code
        == 403
    )

    # Audit summary & revenue funnel must isolate Tenant B from Tenant A data
    assert client.get(f"/v1/audit/summary?org_id={t1['org_id']}", headers=t2["headers"]).status_code == 403
    audit_b = client.get("/v1/audit/summary", headers=t2["headers"])
    assert audit_b.status_code == 200, audit_b.text
    assert "alpha-only" not in str(audit_b.json())

    funnel_b = client.get("/v1/revenue/funnel", headers=t2["headers"])
    assert funnel_b.status_code == 200, funnel_b.text
    funnel_data = funnel_b.json()
    assert funnel_data.get("leads_total", funnel_data.get("total_leads", 0)) == 0
    assert funnel_data.get("previews_generated", funnel_data.get("previews_total", 0)) == 0


def test_inactive_user_and_inactive_org_fail_closed_on_jwt_and_mobile(iso_client) -> None:
    client, db = iso_client
    t1 = _signup_tenant_admin(client, "active-a@orga.in", "Active Co")
    assert client.get("/v1/leads", headers=t1["headers"]).status_code == 200
    assert client.get("/v1/mobile/tasks/assigned", headers=t1["headers"]).status_code == 200

    # Deactivating user invalidates existing Bearer JWT everywhere
    user = db.get(UserRecord, t1["user_id"])
    user.is_active = False
    db.commit()
    assert client.get("/v1/leads", headers=t1["headers"]).status_code in (401, 403)
    assert client.get("/v1/mobile/tasks/assigned", headers=t1["headers"]).status_code in (401, 403)

    # Reactivate user, then deactivate organization -> still blocked
    user.is_active = True
    org = db.get(OrganizationRecord, t1["org_id"])
    org.is_active = False
    db.commit()
    assert client.get("/v1/leads", headers=t1["headers"]).status_code in (401, 403)
    assert client.get("/v1/mobile/tasks/assigned", headers=t1["headers"]).status_code in (401, 403)


def test_mobile_bridge_and_field_force_role_and_tenant_isolation(iso_client) -> None:
    client, db = iso_client
    t1 = _signup_tenant_admin(client, "mob-a@orga.in", "Mob Alpha")
    t2 = _signup_tenant_admin(client, "mob-b@orgb.in", "Mob Beta")

    # 1. Forged/nonexistent user JWT rejected on mobile bridge (no virtual user fallback)
    ghost_tok = create_access_token(
        user_id="nonexistent-user-id",
        email="ghost@orga.in",
        role="member",
        org_id=t1["org_id"],
    )
    assert client.get("/v1/mobile/tasks/assigned", headers={"Authorization": f"Bearer {ghost_tok}"}).status_code == 401

    # 2. Tenant customer role rejected from mobile bridge & field force operational routes
    _, cust_hdrs = _seed_user_and_login(
        client,
        db,
        org_id=t1["org_id"],
        email="cust@orga.in",
        role="customer",
        full_name="Customer Only",
    )
    assert client.get("/v1/mobile/tasks/assigned", headers=cust_hdrs).status_code == 403
    assert client.get("/v1/field-force/geofences", headers=cust_hdrs).status_code == 403
    assert client.get("/v1/field-force/tasks", headers=cust_hdrs).status_code == 403
    assert (
        client.post(
            "/v1/field-force/geofences",
            headers=cust_hdrs,
            json={"name": "Cust Hub", "latitude": 12.9, "longitude": 77.5},
        ).status_code
        == 403
    )

    # 3. Platform API key accessing mobile bridge does NOT impersonate a tenant DB user
    mgr_mob = client.post(
        "/v1/mobile/device/register",
        headers={"x-api-key": MANAGER_KEY},
        json={"device_id": "ops-device-1", "platform": "android"},
    )
    assert mgr_mob.status_code == 200, mgr_mob.text
    assert mgr_mob.json()["user_id"] == "platform-manager"
    assert mgr_mob.json()["org_id"] is None

    # 4. Cross-tenant geofence_id & task_id blocked in mobile bridge
    gf_a = GeofenceDefinition(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        name="Alpha Plant",
        latitude=18.5204,
        longitude=73.8567,
        radius_meters=200.0,
    )
    task_a = FieldTaskRecord(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        assigned_to_user_id=t1["user_id"],
        title="Inspect Alpha Pump",
        client_name="Alpha Client",
        destination_lat=18.5204,
        destination_lon=73.8567,
        status="ASSIGNED",
    )
    db.add_all([gf_a, task_a])
    db.commit()

    cross_checkin = client.post(
        "/v1/mobile/attendance/check-in",
        headers=t2["headers"],
        json={
            "latitude": 18.5204,
            "longitude": 73.8567,
            "accuracy_meters": 5.0,
            "geofence_id": gf_a.id,
        },
    )
    assert cross_checkin.status_code == 403

    cross_visit = client.post(
        "/v1/mobile/visits/submit",
        headers=t2["headers"],
        json={
            "client_id": "Alpha Client",
            "task_id": task_a.id,
            "latitude": 18.5204,
            "longitude": 73.8567,
        },
    )
    assert cross_visit.status_code == 403


def test_customer_success_and_platform_route_isolation(iso_client) -> None:
    client, db = iso_client
    owner_hdrs = {"x-api-key": OWNER_KEY}
    t1 = _signup_tenant_admin(client, "cs-a@orga.in", "CS Alpha")
    t2 = _signup_tenant_admin(client, "cs-b@orgb.in", "CS Beta")

    # Owner ensures CS accounts for Org A and Org B
    assert (
        client.post(
            f"/v1/cs/customers/{t1['org_id']}/ensure",
            headers=owner_hdrs,
            json={"human_owner": "ops_owner", "sku_key": "growth_all_in_one"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/v1/cs/customers/{t2['org_id']}/ensure",
            headers=owner_hdrs,
            json={"human_owner": "ops_owner", "sku_key": "growth_all_in_one"},
        ).status_code
        == 200
    )

    # Platform-only endpoints reject tenant_admin JWTs with 403
    platform_only_calls = [
        ("GET", "/v1/cs/control-centre", None),
        ("GET", "/v1/cs/customers", None),
        ("POST", f"/v1/cs/customers/{t1['org_id']}/ensure", {"human_owner": "self"}),
        ("POST", f"/v1/cs/customers/{t1['org_id']}/lifecycle", {"target_state": "ACTIVE", "reason": "bypass"}),
        ("PATCH", f"/v1/cs/customers/{t1['org_id']}/profile", {"human_owner": "self"}),
        ("POST", f"/v1/cs/customers/{t1['org_id']}/health/alerts", None),
        ("POST", "/v1/cs/subscriptions/enforce-grace", None),
        ("GET", "/v1/cs/ops/readiness", None),
        ("GET", "/v1/cs/acceptance", None),
        ("GET", "/v1/webhooks/events", None),
        ("POST", "/v1/neon/functions/health/invoke", {"payload": {}}),
        ("GET", "/v1/ops/preflight", None),
        ("GET", "/v1/ops/roadmap-scorecard", None),
    ]
    for method, path, payload in platform_only_calls:
        resp = client.request(method, path, headers=t1["headers"], json=payload)
        assert resp.status_code == 403, f"Expected 403 for tenant on {method} {path}, got {resp.status_code}: {resp.text}"

    # Tenant A creates delivery & support ticket in Org A
    deliv_a = client.post(
        "/v1/cs/deliveries",
        headers=t1["headers"],
        json={
            "org_id": t1["org_id"],
            "title": "Alpha SEO Audit",
            "original_requirement": "Audit core commercial pages cleanly.",
            "approved_scope": ["technical audit"],
        },
    )
    assert deliv_a.status_code == 200, deliv_a.text
    deliv_id = deliv_a.json()["delivery_id"]

    ticket_a = client.post(
        "/v1/cs/support/tickets",
        headers=t1["headers"],
        json={
            "org_id": t1["org_id"],
            "subject": "Alpha onboarding question",
            "description": "Need clarification on DNS verification.",
        },
    )
    assert ticket_a.status_code == 200, ticket_a.text
    ticket_id = ticket_a.json()["ticket_id"]

    # Tenant A cannot post internal_note on own ticket
    internal_msg = client.post(
        f"/v1/cs/support/tickets/{ticket_id}/messages",
        headers=t1["headers"],
        json={"body": "Secret internal triage", "visibility": "internal_note"},
    )
    assert internal_msg.status_code == 403

    # Owner posts internal note -> Tenant A listing must exclude internal note
    owner_internal = client.post(
        f"/v1/cs/support/tickets/{ticket_id}/messages",
        headers=owner_hdrs,
        json={"body": "Owner-only internal note", "visibility": "internal_only"},
    )
    assert owner_internal.status_code == 200, owner_internal.text
    t1_tickets = client.get("/v1/cs/support/tickets", headers=t1["headers"]).json()
    assert "Owner-only internal note" not in str(t1_tickets)

    # Seed Org A workflow_run, execution_evidence & growth opportunity for cross-tenant FK & share checks
    wf_def_a = WorkflowDefinitionRecord(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        workflow_key=f"wf-{uuid.uuid4().hex[:8]}",
        name="Alpha WF",
        steps_json=[{"step_key": "s1"}],
        is_active=True,
    )
    db.add(wf_def_a)
    db.flush()
    wf_run_a = WorkflowRunRecord(
        id=str(uuid.uuid4()),
        workflow_id=wf_def_a.id,
        org_id=t1["org_id"],
        execution_mode="SIMULATION",
        status="RUNNING",
        credits_budget=10,
    )
    ev_a = ExecutionEvidenceRecord(
        execution_id=f"exec-{uuid.uuid4().hex[:12]}",
        tenant_id=t1["org_id"],
        agent_id="seo_content_agent",
        execution_mode="SIMULATION",
        input_reference="in",
        output_reference="out",
        status="COMPLETED",
        started_at=datetime.now(UTC),
        evidence_reference="ref://ev",
        output_origin="SIMULATED_SYNTHETIC",
    )
    opp_a = P3GrowthOpportunityRecord(
        id=str(uuid.uuid4()),
        org_id=t1["org_id"],
        opportunity_type="UPSELL",
        title="Expand Seats",
        status="IDENTIFIED",
    )
    appr_a = ApprovalRequest(
        id=str(uuid.uuid4()),
        task_id=opp_a.id,
        action="share_growth",
        detail={"org_id": t1["org_id"]},
        idempotency_key=f"appr-{uuid.uuid4().hex}",
        request_hash="hash",
        status="APPROVED",
        requested_by="owner",
    )
    db.add_all([wf_run_a, ev_a, opp_a, appr_a])
    db.commit()

    # Tenant B cross-tenant CS calls rejected with 403
    assert client.get(f"/v1/cs/customers/{t1['org_id']}", headers=t2["headers"]).status_code == 403
    assert client.get(f"/v1/cs/customers/{t1['org_id']}/onboarding", headers=t2["headers"]).status_code == 403
    assert client.get(f"/v1/cs/deliveries?org_id={t1['org_id']}", headers=t2["headers"]).status_code == 403
    assert (
        client.post(
            f"/v1/cs/deliveries/{deliv_id}/transition",
            headers=t2["headers"],
            json={"target_state": "IN_PROGRESS", "note": "cross tenant"},
        ).status_code
        == 403
    )
    assert client.get(f"/v1/cs/customers/{t1['org_id']}/health", headers=t2["headers"]).status_code == 403
    assert client.get(f"/v1/cs/support/tickets?org_id={t1['org_id']}", headers=t2["headers"]).status_code == 403
    assert (
        client.post(
            f"/v1/cs/support/tickets/{ticket_id}/transition",
            headers=t2["headers"],
            json={"target_state": "IN_PROGRESS", "reason": "hijack"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/cs/support/tickets/{ticket_id}/ai-assist",
            headers=t2["headers"],
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/cs/support/tickets/{ticket_id}/csat",
            headers=t2["headers"],
            json={"rating": 1, "comment": "spam"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/cs/growth/opportunities/{opp_a.id}/share",
            headers=t2["headers"],
            json={"approval_id": appr_a.id},
        ).status_code
        == 403
    )
    assert client.post(f"/v1/cs/compliance/{t1['org_id']}/export", headers=t2["headers"]).status_code == 403

    # Tenant B cannot link Org A's delivery_id / workflow_run_id / execution_id in Org B cost recording
    for bad_link in (
        {"delivery_id": deliv_id},
        {"workflow_run_id": wf_run_a.id},
        {"execution_id": ev_a.execution_id},
    ):
        res = client.post(
            f"/v1/cs/unit-economics/{t2['org_id']}/costs",
            headers=t2["headers"],
            json={
                "cost_category": "LLM_INFERENCE",
                "cost_type_label": "ACTUAL",
                "amount_inr": 10.0,
                **bad_link,
            },
        )
        assert res.status_code == 403, f"Expected 403 for cross-tenant link {bad_link}, got {res.status_code}: {res.text}"
