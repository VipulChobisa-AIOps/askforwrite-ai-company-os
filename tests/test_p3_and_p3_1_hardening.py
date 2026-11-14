"""Focused regression and hardening tests for P3 bugfixes and P3.1 verification gaps."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    ApprovalRequest,
    ExecutionEvidenceRecord,
    P3OperationalIncidentRecord,
    SeoDraftRecord,
    TaskRecord,
    WorkflowDefinitionRecord,
    WorkflowRunRecord,
)
from app.main import app
from app.services.connectors import build_connector_probe_adapter, verify_connector
from app.services.email_dispatcher import MockEmailDispatcher, SmtpEmailDispatcher, get_email_dispatcher
from app.services.p3_ops_compliance_cc import (
    export_customer_data_bundle,
    get_p3_customer_ops_control_centre,
)
from app.services.p3_support_improvements import add_ticket_message, create_support_ticket
from app.services.watchdog import get_connector_inventory
from app.services.wordpress_publisher import publish_seo_draft_to_wordpress

OWNER_KEY = "p31-hardening-owner-key-32-chars!"
MANAGER_KEY = "p31-hardening-mgr-key-32-chars!!"
JWT_SECRET = "p31-hardening-jwt-secret-32chars!"


@pytest.fixture()
def isolated_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ALLOW_LIVE_SIDE_EFFECTS", "false")
    monkeypatch.setenv("ENABLE_EXTERNAL_SIDE_EFFECTS", "false")
    monkeypatch.setenv("OWNER_API_KEY", OWNER_KEY)
    monkeypatch.setenv("MANAGER_API_KEY", MANAGER_KEY)
    monkeypatch.setenv("JWT_SECRET_KEY", JWT_SECRET)

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionCls = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    Base.metadata.create_all(bind=eng)
    db = SessionCls()

    def _override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    try:
        yield client, db
    finally:
        app.dependency_overrides.clear()
        db.close()
        eng.dispose()


def _create_tenant_and_headers(client: TestClient, email: str, company: str) -> dict[str, Any]:
    res = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "StrongPassword!123",
            "full_name": "Tenant Owner",
            "company_name": company,
        },
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()
    return {
        "org_id": data["org_id"],
        "user_id": data["user_id"],
        "token": data["access_token"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
    }


def test_ticket_internal_note_normalization_and_export_redaction(isolated_env) -> None:
    client, db = isolated_env
    t = _create_tenant_and_headers(client, "notes@acme.test", "Acme Notes")
    tkt = create_support_ticket(
        db,
        org_id=t["org_id"],
        subject="Connector issue",
        description="Needs diagnostic check",
    )
    add_ticket_message(
        db,
        ticket_id=tkt["ticket_id"],
        body="Public workaround step",
        visibility="customer_visible",
        sender_type="staff",
    )
    add_ticket_message(
        db,
        ticket_id=tkt["ticket_id"],
        body="SENSITIVE_STAFF_DIAGNOSTIC_ONLY",
        visibility="internal_only",
        sender_type="staff",
    )

    portal_res = client.get("/v1/me/support/tickets", headers=t["headers"])
    assert portal_res.status_code == 200
    assert "SENSITIVE_STAFF_DIAGNOSTIC_ONLY" not in portal_res.text
    assert "Public workaround step" in portal_res.text

    bundle = export_customer_data_bundle(db, org_id=t["org_id"], requested_by="tenant", customer_safe_only=True)
    dumped = json.dumps(bundle)
    assert "SENSITIVE_STAFF_DIAGNOSTIC_ONLY" not in dumped
    assert "Public workaround step" in dumped


def test_plan_change_forwards_credits_addons_and_cancel_renew(isolated_env) -> None:
    client, _db = isolated_env
    t = _create_tenant_and_headers(client, "plans@acme.test", "Acme Plans")
    hdrs = {"X-API-Key": OWNER_KEY}

    up = client.post(
        f"/v1/cs/subscriptions/{t['org_id']}/plan-change",
        headers=hdrs,
        json={
            "action": "upgrade",
            "new_sku_key": "growth",
            "billing_interval": "monthly",
            "currency": "INR",
            "credit_packs": 2,
            "integration_addons": ["seo_geo_copilot"],
            "customization_level": "enterprise_custom",
        },
    )
    assert up.status_code == 200, up.text
    sub = up.json()["plan_change"]["subscription"]
    assert sub["credit_packs_purchased"] == 2
    assert sub["customization_allowance"]["level"] == "enterprise_custom"
    assert sub["integration_addons"] == ["seo_geo_copilot"]

    can = client.post(
        f"/v1/cs/subscriptions/{t['org_id']}/plan-change",
        headers=hdrs,
        json={"action": "cancel", "new_sku_key": "growth", "billing_interval": "monthly", "currency": "INR"},
    )
    assert can.status_code == 200, can.text
    assert can.json()["subscription_event"]["event"]["event_type"] == "PLAN_CANCEL"


def test_failed_payments_case_insensitive_and_maintenance_sweep(isolated_env) -> None:
    client, db = isolated_env
    t = _create_tenant_and_headers(client, "ops@acme.test", "Acme Ops")
    hdrs = {"X-API-Key": MANAGER_KEY}

    # Lowercase payment_failed from payment-failure handler must be counted in control centre
    pf = client.post(
        f"/v1/cs/subscriptions/{t['org_id']}/payment-failure",
        headers={"X-API-Key": OWNER_KEY},
        json={"amount": 1999.0, "currency": "INR", "idempotency_key": f"pf-{uuid.uuid4()}"},
    )
    assert pf.status_code == 200, pf.text

    cc = get_p3_customer_ops_control_centre(db)
    assert cc["verified_customer_ops"]["revenue_and_unit_economics"]["failed_payments_count"] >= 1

    sweep_res = client.post(
        "/v1/cs/ops/run-maintenance",
        headers=hdrs,
        params={"org_id": t["org_id"], "stale_timeout_seconds": 60},
    )
    assert sweep_res.status_code == 200, sweep_res.text
    body = sweep_res.json()
    assert "grace_enforcement" in body and "stale_workflow_scan" in body and "health_alerts_generated" in body


def test_tenant_me_approvals_isolation_and_platform_owner_action_guard(isolated_env) -> None:
    client, db = isolated_env
    t_a = _create_tenant_and_headers(client, "org_a@acme.test", "Org Alpha")
    t_b = _create_tenant_and_headers(client, "org_b@acme.test", "Org Beta")

    task_wf = TaskRecord(id="task-wf-a", correlation_id="c1", objective="WF", status="HUMAN_APPROVAL_REQUIRED")
    task_ref = TaskRecord(id="task-ref-a", correlation_id="c2", objective="Refund", status="HUMAN_APPROVAL_REQUIRED")
    db.add_all([task_wf, task_ref])
    db.flush()

    wf_appr = ApprovalRequest(
        id="appr-wf-a",
        task_id="task-wf-a",
        action="workflow_hitl_gate",
        detail={"org_id": t_a["org_id"], "workflow_run_id": "run-a"},
        idempotency_key="appr-wf-a-key",
        request_hash="hash-wf-a",
        requested_by="system",
        status="PENDING",
    )
    refund_appr = ApprovalRequest(
        id="appr-refund-a",
        task_id="task-ref-a",
        action="subscription_pricing_or_refund_action",
        detail={"org_id": t_a["org_id"], "amount_inr": 500},
        idempotency_key="appr-refund-a-key",
        request_hash="hash-refund-a",
        requested_by="system",
        status="PENDING",
    )
    db.add_all([wf_appr, refund_appr])
    db.commit()

    # Org B must NOT see Org A approvals and cannot decide them (403)
    list_b = client.get("/v1/me/approvals", headers=t_b["headers"])
    assert list_b.status_code == 200
    assert list_b.json()["count"] == 0
    dec_b = client.post("/v1/me/approvals/appr-wf-a/decide", headers=t_b["headers"], json={"decision": "APPROVED"})
    assert dec_b.status_code == 403

    # Org A sees both, with requires_platform_owner marked honestly on platform action
    list_a = client.get("/v1/me/approvals", headers=t_a["headers"])
    assert list_a.status_code == 200
    items_a = {a["approval_id"]: a for a in list_a.json()["approvals"]}
    assert "appr-wf-a" in items_a and items_a["appr-wf-a"]["requires_platform_owner"] is False
    assert "appr-refund-a" in items_a and items_a["appr-refund-a"]["requires_platform_owner"] is True

    # Org A customer cannot approve platform-owner refund gate (403), but CAN approve its workflow gate (200)
    blocked_ref = client.post("/v1/me/approvals/appr-refund-a/decide", headers=t_a["headers"], json={"decision": "APPROVED"})
    assert blocked_ref.status_code == 403
    ok_wf = client.post("/v1/me/approvals/appr-wf-a/decide", headers=t_a["headers"], json={"decision": "APPROVED"})
    assert ok_wf.status_code == 200
    assert ok_wf.json()["status"] == "APPROVED"


def test_workflow_engine_automatic_cost_budget_enforcement(isolated_env) -> None:
    client, db = isolated_env
    t = _create_tenant_and_headers(client, "budget@acme.test", "Budget Co")
    # Upgrade tenant to growth so lead_discovery is entitled before budget check triggers
    up_res = client.post(
        f"/v1/cs/subscriptions/{t['org_id']}/plan-change",
        headers={"X-API-Key": OWNER_KEY},
        json={"action": "upgrade", "new_sku_key": "growth", "billing_interval": "monthly", "currency": "INR"},
    )
    assert up_res.status_code == 200, up_res.text
    # Set a tiny hard cap INR 1.0 so consuming >=1 workflow credit (INR 14.99 est) triggers COST_BUDGET_BREACH
    b_res = client.put(
        f"/v1/cs/unit-economics/{t['org_id']}/budget",
        headers={"X-API-Key": OWNER_KEY},
        json={"monthly_cost_limit_inr": 1.0, "hard_cap_enforced": True},
    )
    assert b_res.status_code == 200

    wf = WorkflowDefinitionRecord(
        id="wf-budget-1",
        org_id=t["org_id"],
        workflow_key="budget_test_wf",
        name="Budget Test WF",
        steps_json=[{"step_key": "step1", "step_type": "agent_step", "agent_id": "discovery_sdr_agent", "input_template": {"industry": "logistics"}}],
    )
    db.add(wf)
    db.commit()

    run_res = client.post(
        "/v1/workflows/runs",
        headers=t["headers"],
        json={"workflow_id": "wf-budget-1", "execution_mode": "SANDBOX", "input_payload": {"industry": "logistics"}},
    )
    assert run_res.status_code == 402, run_res.text

    run = db.query(WorkflowRunRecord).filter_by(workflow_id="wf-budget-1").first()
    assert run is not None
    assert run.status == "BLOCKED"
    inc = db.query(P3OperationalIncidentRecord).filter_by(org_id=t["org_id"], incident_type="COST_BUDGET_BREACH").first()
    assert inc is not None
    ev = db.query(ExecutionEvidenceRecord).filter_by(execution_id=f"wfrun-{run.id[:20]}").first()
    assert ev is not None and ev.status == "BLOCKED"


def test_solutions_service_route_separation_and_dynamic_alembic_preflight(isolated_env) -> None:
    client, _db = isolated_env

    # /services owned by service_pages.py (full service catalog) AND supports legacy solution slug aliases
    svc_hub = client.get("/services")
    assert svc_hub.status_code == 200
    assert "Verified Service &amp; Capability Directory" in svc_hub.text

    svc_item = client.get("/services/seo_blog_copilot")
    assert svc_item.status_code == 200
    svc_alias = client.get("/services/warehouse-automation")
    assert svc_alias.status_code == 200
    sol_item = client.get("/solutions/warehouse-automation")
    assert sol_item.status_code == 200

    preflight = client.get("/v1/ops/preflight", headers={"X-API-Key": MANAGER_KEY})
    assert preflight.status_code == 200
    pf = preflight.json()
    assert pf["database"]["alembic_revision"] != "f6a1b2c3d4e5"  # never fabricate legacy revision when unstamped
    assert len(pf["database"]["expected_heads"]) >= 1
    assert "gsc_oauth_configured" in pf["integrations"]


def test_connector_probe_adapters_and_watchdog_zero_key_inflation(isolated_env, monkeypatch: pytest.MonkeyPatch) -> None:
    _client, db = isolated_env

    # Even with env keys set, watchdog must NOT mark connectors LIVE_VERIFIED without an executed handshake
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-gemini-key")
    monkeypatch.setenv("SERPER_API_KEY", "fake-test-serper-key")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "fake-test-places-key")
    monkeypatch.setenv("SMTP_PASSWORD", "fake-test-smtp-pass")
    monkeypatch.setenv("WP_SITE_URL", "https://cms.askforwrite.example")
    monkeypatch.setenv("WP_USERNAME", "wp_editor")
    monkeypatch.setenv("WP_APP_PASSWORD", "fake-test-wp-pass")

    inv = get_connector_inventory(db)
    for c in inv["connectors"]:
        assert c["status"] != "LIVE_VERIFIED", f"{c['connector_id']} must not claim LIVE_VERIFIED from key presence alone!"

    # Injectable MockTransport HTTP probe works honestly for WordPress & Razorpay
    monkeypatch.setenv("ENABLE_EXTERNAL_SIDE_EFFECTS", "true")
    monkeypatch.setenv("ALLOW_LIVE_SIDE_EFFECTS", "true")
    monkeypatch.setenv("ALLOW_LIVE_IN_TEST", "true")

    wp_transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"id": 1, "name": "wp_editor"}))
    with httpx.Client(transport=wp_transport) as hc:
        res_wp = verify_connector(
            db,
            connector_id="wordpress_rest",
            org_id="__platform__",
            mode="PRODUCTION",
            probe_fn=build_connector_probe_adapter("wordpress_rest", http_client=hc),
        )
    assert res_wp["capability_state"] == "LIVE_VERIFIED"

    # Watchdog reflects persisted LIVE_VERIFIED state when verified
    inv_after = get_connector_inventory(db)
    wp_entry = next(c for c in inv_after["connectors"] if c["connector_id"] == "wordpress_rest")
    assert wp_entry["status"] == "LIVE_VERIFIED"

    # Failed 401 probe transitions to BLOCKED
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_123")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_secret_123")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "rzp_wh_123")
    fail_transport = httpx.MockTransport(lambda req: httpx.Response(401, json={"error": "Unauthorized"}))
    with httpx.Client(transport=fail_transport) as hc:
        res_rzp = verify_connector(
            db,
            connector_id="razorpay",
            org_id="__platform__",
            mode="PRODUCTION",
            probe_fn=build_connector_probe_adapter("razorpay", http_client=hc),
        )
    assert res_rzp["capability_state"] == "BLOCKED"
    assert "401" in (res_rzp["last_error"] or "")


def test_places_no_fake_domain_wordpress_injection_and_smtp_sandbox_sink(isolated_env, monkeypatch: pytest.MonkeyPatch) -> None:
    _client, db = isolated_env
    from app.agents.smb_search_source import _search_google_places_live

    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-places-key")

    def _places_handler(req: httpx.Request) -> httpx.Response:
        if "textsearch" in str(req.url):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"name": "Mystery Local Shop", "formatted_address": "Udaipur, RJ", "place_id": "pl-no-web"},
                        {"name": "Real Domain Traders", "formatted_address": "Jaipur, RJ", "place_id": "pl-real-web"},
                    ]
                },
            )
        if "details" in str(req.url):
            if "pl-real-web" in str(req.url):
                return httpx.Response(200, json={"result": {"website": "https://realtraders.in"}})
            return httpx.Response(200, json={"result": {}})
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(_places_handler)) as hc:
        places = _search_google_places_live("logistics in Rajasthan", limit=5, http_client=hc)

    assert len(places) == 2
    assert places[0]["website"] is None and places[0]["domain"] is None and places[0]["public_contact_channel"] is None
    assert places[1]["domain"] == "realtraders.in"

    # Email dispatcher respects SMTP_MODE=sandbox_sink even when provider=smtp
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ENABLE_EXTERNAL_SIDE_EFFECTS", "true")
    monkeypatch.setenv("OUTREACH_DISPATCH_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.hostinger.com")
    monkeypatch.setenv("SMTP_MODE", "sandbox_sink")
    assert isinstance(get_email_dispatcher(), MockEmailDispatcher)
    smtp_res = SmtpEmailDispatcher().send("buyer@example.com", "Test", "Body")
    assert smtp_res["simulated"] is True

    # WordPress publisher works with injected httpx.Client MockTransport
    draft = SeoDraftRecord(
        id=9001,
        task_id="task-wp-9001",
        target_network="askforwrite.in",
        keywords=["warehouse ai"],
        content="# Warehouse AI Guide\n\nDetailed operational guide.",
        status="APPROVED",
    )
    db.add(draft)
    db.commit()
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ENABLE_EXTERNAL_SIDE_EFFECTS", "true")
    monkeypatch.setenv("ALLOW_LIVE_SIDE_EFFECTS", "true")
    monkeypatch.setenv("ALLOW_LIVE_IN_TEST", "true")
    monkeypatch.setenv("WP_SITE_URL", "https://askforwrite.in")
    monkeypatch.setenv("WP_USERNAME", "editor")
    monkeypatch.setenv("WP_APP_PASSWORD", "app-pass")

    wp_mock = httpx.MockTransport(lambda req: httpx.Response(201, json={"id": 42, "link": "https://askforwrite.in/articles/warehouse-ai-guide"}))
    with httpx.Client(transport=wp_mock) as hc:
        pub = publish_seo_draft_to_wordpress(db, draft_id=9001, http_client=hc)
    assert pub["mode"] == "WORDPRESS_REST_LIVE"
    assert pub["post_id"] == 42


def test_dashboard_placeholder_removed_and_p3_mappings_fixed() -> None:
    repo = Path(__file__).resolve().parents[1]
    html_text = (repo / "app" / "dashboard" / "index.html").read_text(encoding="utf-8")
    js_text = (repo / "app" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")

    assert "INV-2026-001" not in html_text
    assert "onb.progress_pct" in js_text
    assert "d.original_requirement" in js_text
    assert "t.owner_role" in js_text
    assert "btn-portal-export-data" in html_text
    assert "btn-p3-run-maintenance" in html_text
    assert "p3-release-readiness-summary" in html_text
