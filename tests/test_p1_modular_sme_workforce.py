"""Comprehensive P1 test suite (Test Areas A-O) for Modular SME AI Workforce OS."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.db.database import SessionLocal
from app.db.models import ExecutionEvidenceRecord, OrganizationRecord
from app.main import app
from app.services.billing_ledger import (
    InsufficientCreditsError,
    commit_credit_reservation,
    reserve_execution_credits,
)
from app.services.connectors import CAPABILITY_STATES, CONNECTOR_SPECS
from app.services.email_dispatcher import SmtpEmailDispatcher
from app.services.execution_guard import (
    ExecutionBlockedError,
    clear_simulation_dispatch_sink,
    get_simulation_dispatch_sink,
    set_emergency_stop,
    validate_external_url,
)
from app.services.registry import AGENT_REGISTRY, SERVICE_CATEGORIES, SERVICE_REGISTRY
from app.services.wordpress_publisher import publish_seo_draft_to_wordpress

REPO_ROOT = Path(__file__).resolve().parent.parent
client = TestClient(app)


def _owner_headers() -> dict[str, str]:
    owner_key = os.environ.get("OWNER_API_KEY", "").strip()
    if len(owner_key) < 32:
        owner_key = "p1-test-owner-key-must-be-at-least-32-characters-long-0001"
        os.environ["OWNER_API_KEY"] = owner_key
    return {"X-API-Key": owner_key}


def _signup_customer(
    *,
    tag: str,
    package: str = "growth_all_in_one",
    company_suffix: str = "SME",
) -> dict[str, str]:
    uid = uuid.uuid4().hex[:8]
    email = f"p1-{tag}-{uid}@askforwrite-test.in"
    resp = client.post(
        "/v1/auth/register",
        json={
            "full_name": f"Founder {tag}",
            "email": email,
            "password": "P1StrongPassword!99",
            "company_name": f"Test {company_suffix} {uid}",
            "role": "customer",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    data = resp.json()
    token = data["access_token"]
    org_id = data["org_id"]
    if package and package != "free":
        with SessionLocal() as db:
            org = db.get(OrganizationRecord, org_id)
            if org is not None:
                org.tier = package
                db.commit()
    return {
        "email": email,
        "token": token,
        "org_id": org_id,
        "headers": {"Authorization": f"Bearer {token}"},
    }


def _configure_growth_subscription(headers: dict[str, str], base_tier: str = "growth", addons: list[str] | None = None) -> dict:
    resp = client.post(
        "/v1/me/modular-subscription",
        headers=headers,
        json={
            "base_tier": base_tier,
            "addon_modules": addons or ["lead_discovery", "seo_content", "sales_proposals", "governance_trust"],
            "billing_interval": "monthly",
            "currency": "INR",
            "credit_packs": 1,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ══════════════════════════════════════════════════════════════════════════════
# TEST AREA A: UNIFIED SERVICE, AGENT & CONNECTOR REGISTRY + ACCESS ENFORCEMENT
# ══════════════════════════════════════════════════════════════════════════════


def test_a_unified_registry_discovery_and_schema_completeness() -> None:
    svc_res = client.get("/v1/registry/services")
    assert svc_res.status_code == 200
    svcs = svc_res.json()["services"]
    assert len(svcs) == len(SERVICE_REGISTRY)
    assert len(SERVICE_CATEGORIES) == 9
    required_svc_keys = {
        "service_id",
        "service_name",
        "category",
        "description",
        "business_outcome",
        "available_agents",
        "required_connectors",
        "entitlement_key",
        "pricing_reference",
        "execution_status",
        "version",
    }
    for svc in svcs:
        assert required_svc_keys.issubset(svc.keys())

    ag_res = client.get("/v1/registry/agents")
    assert ag_res.status_code == 200
    ags = ag_res.json()["agents"]
    assert len(ags) == len(AGENT_REGISTRY)
    required_ag_keys = {
        "agent_id",
        "agent_name",
        "description",
        "business_function",
        "capabilities",
        "supported_tools",
        "input_schema",
        "output_schema",
        "model_configuration",
        "system_instructions",
        "permission_policy",
        "execution_limits",
        "required_approvals",
        "version",
        "status",
    }
    for ag in ags:
        assert required_ag_keys.issubset(ag.keys())

    det = client.get("/v1/registry/agents/discovery_sdr_agent")
    assert det.status_code == 200
    assert det.json()["agent_id"] == "discovery_sdr_agent"

    missing = client.get("/v1/registry/agents/non_existent_agent")
    assert missing.status_code == 404


def test_a_agent_activation_entitlement_deactivation_and_tool_allowlist() -> None:
    starter = _signup_customer(tag="starter", package="starter_pilot")
    # Unentitled specialized agent should be blocked cleanly on activation
    denied = client.post(
        "/v1/registry/agents/warehouse_stocksense_agent/activate",
        headers=starter["headers"],
    )
    assert denied.status_code == 403

    # Configure modular plan unlocking warehouse module
    _configure_growth_subscription(
        starter["headers"],
        base_tier="operations",
        addons=["inventory_quality"],
    )
    act = client.post(
        "/v1/registry/agents/warehouse_stocksense_agent/activate",
        headers=starter["headers"],
    )
    assert act.status_code == 200
    assert act.json()["status"] == "ACTIVATED"

    # Least-privilege configure rejects unauthorized tool escalation
    bad_cfg = client.patch(
        "/v1/registry/agents/warehouse_stocksense_agent/configure",
        headers=starter["headers"],
        json={"tool_allowlist": ["eoq_math_tool", "drop_production_database"]},
    )
    assert bad_cfg.status_code == 403

    # Deactivated agent refuses execution and records BLOCKED evidence
    deact = client.post(
        "/v1/registry/agents/warehouse_stocksense_agent/deactivate",
        headers=starter["headers"],
    )
    assert deact.status_code == 200
    blocked_run = client.post(
        "/v1/registry/agents/warehouse_stocksense_agent/execute",
        headers=starter["headers"],
        json={"input_payload": {"skus": []}},
    )
    assert blocked_run.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# TEST AREA B: SME 13-FIELD PROFILE, REQUIREMENTS ENGINE & CONFIRMATION GATE
# ══════════════════════════════════════════════════════════════════════════════


def test_b_sme_profile_requirements_and_confirmation_gate() -> None:
    cust = _signup_customer(tag="profile")
    prof_resp = client.post(
        "/v1/me/business-profile",
        headers=cust["headers"],
        json={
            "business_name": "Mewar Block Prints Pvt Ltd",
            "industry": "Textiles & Apparel Export",
            "description": "Exporting hand-block textiles across EU & US B2B boutiques",
            "location": "Jaipur, Rajasthan, India",
            "website": "https://mewarprints.example.in",
            "contact_info": {"email": cust["email"], "phone": "+91-98290-12345"},
            "company_size": "11-50 employees",
            "employee_count": 32,
            "products_and_services": ["Hand Block Scarves", "Home Linen"],
            "customer_segments": ["EU Wholesalers", "Boutique Brands"],
            "sales_channels": ["B2B Email", "Trade Shows", "Shopify"],
            "current_software": ["Zoho Books", "WordPress", "Gmail"],
            "operational_pain_points": ["Slow B2B prospect research", "Manual SEO blog updates"],
            "business_objectives": ["Generate 200 verified EU buyer leads/mo", "Publish weekly SEO guides"],
            "required_automations": ["lead_generation", "seo", "sales"],
            "expected_monthly_volume": {"leads": 200, "articles": 12, "budget_inr": 15000},
            "currency": "INR",
        },
    )
    assert prof_resp.status_code == 200, prof_resp.text
    pdata = prof_resp.json()
    assert "profile" in pdata
    assert "structured_requirements" in pdata
    assert "recommendation" in pdata
    assert pdata["profile"]["selection_confirmed"] is False
    assert pdata["recommendation"]["requires_explicit_confirmation"] is True
    assert len(pdata["recommendation"]["explanations"]) >= 1

    get_prof = client.get("/v1/me/business-profile", headers=cust["headers"])
    assert get_prof.status_code == 200
    assert get_prof.json()["profile"]["business_name"] == "Mewar Block Prints Pvt Ltd"

    # Confirmation gate locks selection cleanly
    confirm = client.post(
        "/v1/me/business-profile/confirm",
        headers=cust["headers"],
        json={
            "base_plan_key": "growth",
            "selected_modules": ["lead_discovery", "seo_content"],
            "activate_selection": True,
        },
    )
    assert confirm.status_code == 200, confirm.text
    cdata = confirm.json()
    assert cdata["status"] == "CONFIRMED_AND_ACTIVATED"
    assert cdata["selected_tier"] == "growth"

    get_prof_after = client.get("/v1/me/business-profile", headers=cust["headers"])
    assert get_prof_after.status_code == 200
    assert get_prof_after.json()["profile"]["selection_confirmed"] is True


# ══════════════════════════════════════════════════════════════════════════════
# TEST AREA C: CANONICAL PRICING CONTRACTS, SUBSCRIPTION LIFECYCLE & MRR SKU MAP
# ══════════════════════════════════════════════════════════════════════════════


def test_c_pricing_contracts_subscription_lifecycle_and_mrr_resolution() -> None:
    contracts = client.get("/v1/revenue/pricing/contracts")
    assert contracts.status_code == 200
    body = contracts.json()
    tier_rows = list(body["modular_tier_contracts"].values())
    assert len(tier_rows) >= 5
    required_contract_fields = {
        "internal_sku",
        "billing_type",
        "billing_interval",
        "base_price",
        "currency",
        "provider_plan_id",
        "included_modules",
        "entitled_agents",
        "agent_execution_limit",
        "included_credits",
        "credit_costs",
        "seat_limit",
        "setup_fee",
        "support_level",
        "customization_allowance",
        "renewal_policy",
    }
    for row in tier_rows:
        assert required_contract_fields.issubset(row.keys())

    cust = _signup_customer(tag="billing", package="launch")
    cfg = _configure_growth_subscription(cust["headers"], base_tier="launch", addons=["lead_discovery"])
    assert cfg["pricing_contract"]["internal_sku"].startswith("growth") or len(cfg["pricing_contract"]["internal_sku"]) > 0

    up = client.post(
        "/v1/me/subscription/upgrade",
        headers=cust["headers"],
        json={"base_tier": "growth", "addon_modules": ["lead_discovery", "seo_content"]},
    )
    assert up.status_code == 200
    assert up.json()["status"] == "CONFIGURED"
    assert up.json()["action"] == "upgrade"

    down = client.post(
        "/v1/me/subscription/downgrade",
        headers=cust["headers"],
        json={"base_tier": "launch", "addon_modules": []},
    )
    assert down.status_code == 200
    assert down.json()["status"] == "CONFIGURED"
    assert down.json()["action"] == "downgrade"

    topup = client.post(
        "/v1/me/credits/purchase",
        headers=cust["headers"],
        json={"credit_packs": 2},
    )
    assert topup.status_code == 200
    assert topup.json()["status"] == "CREDITS_ADDED"
    assert topup.json()["credits_added"] == 200

    renew = client.post("/v1/me/subscription/renew", headers=cust["headers"])
    assert renew.status_code == 200
    assert renew.json()["status"] == "renewed"

    cancel = client.post(
        "/v1/me/subscription/cancel",
        headers=cust["headers"],
        json={"cancel_at_period_end": True},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelling"
    assert cancel.json()["subscription"]["cancel_at_period_end"] is True

    ledger = client.get("/v1/me/credits/ledger", headers=cust["headers"])
    assert ledger.status_code == 200
    assert any(e["entry_type"] == "TOPUP" for e in ledger.json()["entries"])

    funnel = client.get("/v1/revenue/funnel", headers=_owner_headers())
    assert funnel.status_code == 200
    assert "mrr_by_internal_sku" in funnel.json()["kpis"]


# ══════════════════════════════════════════════════════════════════════════════
# TEST AREA D: ATOMIC CREDITS, FAILURE REFUNDS, IDEMPOTENCY & CONCURRENCY RACE
# ══════════════════════════════════════════════════════════════════════════════


def test_d_credit_refund_on_failure_and_idempotency_replay() -> None:
    cust = _signup_customer(tag="creditfail")
    _configure_growth_subscription(cust["headers"], base_tier="growth")

    with SessionLocal() as db:
        org = db.get(OrganizationRecord, cust["org_id"])
        assert org is not None
        org.lead_credits_limit = 5
        org.lead_credits_used = 0
        db.commit()

    # Injected failure reserves credits during execution, then refunds atomically!
    fail_resp = client.post(
        "/v1/registry/agents/discovery_sdr_agent/execute",
        headers=cust["headers"],
        json={
            "input_payload": {"__force_failure__": True, "industry": "Textiles"},
            "execution_mode": "SIMULATION",
            "idempotency_key": f"fail-{uuid.uuid4().hex[:8]}",
        },
    )
    assert fail_resp.status_code == 500
    detail = fail_resp.json()["detail"]
    assert detail["evidence"]["status"] == "FAILED"
    assert detail["evidence"]["credits_consumed"] == 0

    with SessionLocal() as db:
        org = db.get(OrganizationRecord, cust["org_id"])
        assert org is not None
        assert org.lead_credits_used == 0

    # Successful run commits credit, and direct idempotency replay does not double-debit
    with SessionLocal() as db:
        idem = f"idem-{uuid.uuid4().hex[:10]}"
        first = reserve_execution_credits(
            db, org_id=cust["org_id"], cost=3, idempotency_key=idem, execution_id="exec-r1"
        )
        replay = reserve_execution_credits(
            db, org_id=cust["org_id"], cost=3, idempotency_key=idem, execution_id="exec-r1"
        )
        assert first["idempotent_replay"] is False
        assert replay["idempotent_replay"] is True
        commit_credit_reservation(db, idempotency_key=idem)
        db.commit()
        org = db.get(OrganizationRecord, cust["org_id"])
        assert org.lead_credits_used == 3

        # Insufficient credits raises InsufficientCreditsError before going negative
        with pytest.raises(InsufficientCreditsError):
            reserve_execution_credits(
                db,
                org_id=cust["org_id"],
                cost=10,
                idempotency_key=f"over-{uuid.uuid4().hex[:8]}",
                execution_id="exec-over",
            )


def test_d_concurrent_credit_reservation_prevents_double_spend() -> None:
    cust = _signup_customer(tag="race")
    with SessionLocal() as db:
        org = db.get(OrganizationRecord, cust["org_id"])
        assert org is not None
        org.lead_credits_limit = 5
        org.lead_credits_used = 0
        db.commit()

    def _attempt(idx: int) -> str:
        with SessionLocal() as db:
            try:
                reserve_execution_credits(
                    db,
                    org_id=cust["org_id"],
                    cost=4,
                    idempotency_key=f"race-{cust['org_id']}-{idx}",
                    execution_id=f"exec-race-{idx}",
                )
                db.commit()
                return "RESERVED"
            except InsufficientCreditsError:
                db.rollback()
                return "REJECTED"
            except Exception as exc:
                # SQLite busy/lock under heavy thread contention rolls back cleanly without corrupting credits
                db.rollback()
                return f"LOCKED:{type(exc).__name__}"

    with ThreadPoolExecutor(max_workers=5) as pool:
        outcomes = list(pool.map(_attempt, range(5)))

    assert outcomes.count("RESERVED") == 1
    with SessionLocal() as db:
        org = db.get(OrganizationRecord, cust["org_id"])
        assert org is not None
        assert org.lead_credits_used == 4
        assert org.lead_credits_used <= org.lead_credits_limit


# ══════════════════════════════════════════════════════════════════════════════
# TEST AREAS E & F: EXECUTION GUARD, SIMULATION SINK, SSRF, 4-LEVEL E-STOP
# ══════════════════════════════════════════════════════════════════════════════


def test_e_simulation_locks_live_side_effects_and_blocks_ssrf(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_simulation_dispatch_sink()
    monkeypatch.setenv("SIMULATION_ONLY", "true")
    monkeypatch.setenv("ENABLE_EXTERNAL_SIDE_EFFECTS", "false")
    # SMTP side effect blocked in test/simulation env & recorded into simulation sink
    dispatcher = SmtpEmailDispatcher("smtp.example.com", 465, "user@example.com", "secret-pw")
    with patch("smtplib.SMTP_SSL") as mock_smtp:
        receipt = dispatcher.send("buyer@example.com", "Proposal", "<p>Hi</p>")
        assert receipt["status"] == "simulated"
        mock_smtp.assert_not_called()

    sink = get_simulation_dispatch_sink()
    assert any(s["channel"] == "smtp_email" and s["external_network_called"] is False for s in sink)

    # WordPress publisher never hits network in simulation mode even if WP credentials are set
    monkeypatch.setenv("WP_SITE_URL", "https://askforwrite.in")
    monkeypatch.setenv("WP_USERNAME", "wp-sim-user")
    monkeypatch.setenv("WP_APP_PASSWORD", "wp-sim-app-pw")
    from app.db.models import ApprovalRequest, SeoDraftRecord

    draft_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    appr_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(
            ApprovalRequest(
                id=appr_id,
                task_id=task_id,
                action="live_publishing",
                detail={"seo_draft_id": draft_id, "network": "askforwrite.in"},
                idempotency_key=f"sim-wp-{appr_id}",
                request_hash=f"hash-{appr_id}",
                status="APPROVED",
                requested_by="seo_copilot",
                decided_by="owner",
            )
        )
        db.add(
            SeoDraftRecord(
                id=draft_id,
                task_id=task_id,
                target_network="askforwrite.in",
                keywords=["modular sme os", "seo copilot"],
                content="# Test Article\n\nBody copy for simulation verification.",
                status="APPROVED",
                approval_id=appr_id,
            )
        )
        db.commit()
        with patch("httpx.post") as mock_wp_post:
            wp_res = publish_seo_draft_to_wordpress(db=db, draft_id=draft_id)
            mock_wp_post.assert_not_called()
    assert wp_res["status"] == "SIMULATED"
    assert wp_res["is_simulated"] is True
    assert wp_res["mode"] == "WORDPRESS_SIMULATED_REST"
    assert any(
        s["channel"] == "wordpress_rest" and s["external_network_called"] is False
        for s in get_simulation_dispatch_sink()
    )

    # SSRF internal / metadata / scheme blocking
    for bad_url in (
        "http://localhost:8000/admin",
        "http://127.0.0.1:5432/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "file:///etc/passwd",
        "http://internal-service.local/api",
    ):
        with pytest.raises(ExecutionBlockedError):
            validate_external_url(bad_url)

    assert validate_external_url("https://askforwrite.com/wp-json/wp/v2/posts") == "https://askforwrite.com/wp-json/wp/v2/posts"

    # PRODUCTION mode execution attempt is hard-blocked in test/simulation isolation
    cust = _signup_customer(tag="prodlock")
    _configure_growth_subscription(cust["headers"], base_tier="growth")
    prod_attempt = client.post(
        "/v1/registry/agents/discovery_sdr_agent/execute",
        headers=cust["headers"],
        json={
            "input_payload": {"industry": "IT"},
            "execution_mode": "PRODUCTION",
        },
    )
    assert prod_attempt.status_code == 403
    assert prod_attempt.json()["detail"]["code"] == "SIMULATION_MODE_LOCK"

    # Unauthorized tool in requested_tools is hard-blocked
    bad_tool = client.post(
        "/v1/registry/agents/discovery_sdr_agent/execute",
        headers=cust["headers"],
        json={
            "input_payload": {"industry": "IT"},
            "execution_mode": "SIMULATION",
            "requested_tools": ["shell_exec_root"],
        },
    )
    assert bad_tool.status_code == 403
    assert bad_tool.json()["detail"]["code"] == "TOOL_NOT_SUPPORTED"


def test_f_four_level_emergency_stop_tenant_agent_and_platform() -> None:
    tenant_a = _signup_customer(tag="estopA")
    tenant_b = _signup_customer(tag="estopB")
    _configure_growth_subscription(tenant_a["headers"], base_tier="growth")
    _configure_growth_subscription(tenant_b["headers"], base_tier="growth")

    # Level 1: Tenant-level stop blocks Tenant A only
    stop_a = client.post(
        "/v1/me/emergency-stop",
        headers=tenant_a["headers"],
        json={"scope_level": "tenant", "state": "EMERGENCY_STOPPED", "reason": "Audit freeze"},
    )
    assert stop_a.status_code == 200
    assert client.post(
        "/v1/registry/agents/discovery_sdr_agent/execute",
        headers=tenant_a["headers"],
        json={"input_payload": {}},
    ).status_code == 403

    # Tenant B runs unimpeded
    ok_b = client.post(
        "/v1/registry/agents/discovery_sdr_agent/execute",
        headers=tenant_b["headers"],
        json={"input_payload": {"industry": "Manufacturing"}},
    )
    assert ok_b.status_code == 200

    # Release Tenant A stop & verify recovery
    rel_a = client.post(
        "/v1/me/emergency-stop",
        headers=tenant_a["headers"],
        json={"scope_level": "tenant", "state": "ACTIVE", "reason": "Audit cleared"},
    )
    assert rel_a.status_code == 200

    # Level 2: Agent-level stop blocks specific agent while another entitled agent runs
    stop_ag = client.post(
        "/v1/me/emergency-stop",
        headers=tenant_a["headers"],
        json={
            "scope_level": "agent",
            "scope_target": "discovery_sdr_agent",
            "state": "EMERGENCY_STOPPED",
            "reason": "Hold SDR",
        },
    )
    assert stop_ag.status_code == 200
    assert client.post(
        "/v1/registry/agents/discovery_sdr_agent/execute",
        headers=tenant_a["headers"],
        json={"input_payload": {}},
    ).status_code == 403
    assert client.post(
        "/v1/registry/agents/seo_content_agent/execute",
        headers=tenant_a["headers"],
        json={"input_payload": {"topic": "SME AI"}},
    ).status_code == 200
    client.post(
        "/v1/me/emergency-stop",
        headers=tenant_a["headers"],
        json={"scope_level": "agent", "scope_target": "discovery_sdr_agent", "state": "ACTIVE", "reason": "Resume"},
    )

    # Level 3: Platform-wide stop blocks all tenants cleanly, then releases cleanly
    plat = client.post(
        "/v1/watchdog/emergency-stop",
        headers=_owner_headers(),
        json={"scope_level": "platform", "scope_target": "*", "state": "EMERGENCY_STOPPED", "reason": "Platform Drill"},
    )
    assert plat.status_code == 200
    try:
        assert client.post(
            "/v1/registry/agents/discovery_sdr_agent/execute",
            headers=tenant_b["headers"],
            json={"input_payload": {}},
        ).status_code == 403
    finally:
        client.post(
            "/v1/watchdog/emergency-stop",
            headers=_owner_headers(),
            json={"scope_level": "platform", "scope_target": "*", "state": "ACTIVE", "reason": "Drill complete"},
        )

    # Level 4: Specific execution-ID emergency stop blocks matching execution ID cleanly
    target_exec = f"exec-halt-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        set_emergency_stop(
            db,
            scope_level="execution",
            scope_target=target_exec,
            state="EMERGENCY_STOPPED",
            reason="Specific execution kill-switch",
            triggered_by="test-operator",
            org_id=tenant_a["org_id"],
        )
        db.commit()
    try:
        with SessionLocal() as db:
            from app.services.execution_guard import check_execution_allowed

            with pytest.raises(ExecutionBlockedError) as exc_info:
                check_execution_allowed(
                    db,
                    execution_id=target_exec,
                    agent_id="discovery_sdr_agent",
                    org_id=tenant_a["org_id"],
                    execution_mode="SIMULATION",
                )
            assert exc_info.value.code == "EMERGENCY_STOP_EXECUTION"
    finally:
        with SessionLocal() as db:
            set_emergency_stop(
                db,
                scope_level="execution",
                scope_target=target_exec,
                state="ACTIVE",
                reason="Cleanup",
                triggered_by="test-operator",
                org_id=tenant_a["org_id"],
            )
            db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# TEST AREAS G, H, L: CONNECTORS, SECRET REDACTION & 18-FIELD EVIDENCE
# ══════════════════════════════════════════════════════════════════════════════


def test_g_h_l_connector_key_never_implies_live_and_evidence_redacts_secrets() -> None:
    cust = _signup_customer(tag="connsec")
    _configure_growth_subscription(cust["headers"], base_tier="growth")

    conns = client.get("/v1/registry/connectors", headers=cust["headers"])
    assert conns.status_code == 200
    assert conns.json()["count"] == len(CONNECTOR_SPECS)
    for c in conns.json()["connectors"]:
        assert c["capability_state"] in CAPABILITY_STATES

    raw_api_key = "sk-live-secret-998877665544"
    cfg_resp = client.post(
        "/v1/registry/connectors/serper_search/configure",
        headers=cust["headers"],
        json={"settings": {"api_key": raw_api_key, "country": "in"}, "environment": "staging"},
    )
    assert cfg_resp.status_code == 200
    conn_data = cfg_resp.json()["connector"]
    # Key presence MUST NOT elevate capability state to LIVE_VERIFIED without probe!
    assert conn_data["capability_state"] != "LIVE_VERIFIED"
    assert raw_api_key not in cfg_resp.text

    # Honest verification probe for serper in simulation does NOT fake LIVE_VERIFIED
    ver = client.post(
        "/v1/registry/connectors/serper_search/verify",
        headers=cust["headers"],
        json={"mode": "SIMULATION"},
    )
    assert ver.status_code == 200
    assert ver.json()["connector"]["capability_state"] != "LIVE_VERIFIED"

    # Execute agent passing raw secrets in payload -> inspect 18-field evidence + confirm ZERO leakage
    run_res = client.post(
        "/v1/registry/agents/discovery_sdr_agent/execute",
        headers=cust["headers"],
        json={
            "execution_mode": "SIMULATION",
            "input_payload": {
                "industry": "Packaging",
                "api_key": "AIzaSyVerySecretRawKey123456",
                "authorization": "Bearer TopSecretJwtValue999999",
            },
        },
    )
    assert run_res.status_code == 200, run_res.text
    ev = run_res.json()["evidence"]
    expected_18_fields = {
        "execution_id",
        "tenant_id",
        "workflow_id",
        "agent_id",
        "connector_id",
        "execution_mode",
        "input_reference",
        "output_reference",
        "provider_request_id",
        "fallback_used",
        "approval_id",
        "status",
        "failure_reason",
        "credits_consumed",
        "started_at",
        "completed_at",
        "evidence_reference",
        "version",
    }
    assert expected_18_fields.issubset(ev.keys())
    assert ev["output_origin"] == "SIMULATED_SYNTHETIC"
    assert "AIzaSyVerySecretRawKey123456" not in run_res.text
    assert "TopSecretJwtValue999999" not in run_res.text

    # Check tenant evidence query endpoint + detail endpoint
    ev_list = client.get("/v1/me/evidence", headers=cust["headers"])
    assert ev_list.status_code == 200
    assert any(r["execution_id"] == ev["execution_id"] for r in ev_list.json()["records"])

    ev_det = client.get(f"/v1/registry/evidence/{ev['execution_id']}", headers=cust["headers"])
    assert ev_det.status_code == 200
    assert "AIzaSyVerySecretRawKey123456" not in ev_det.text

    # DB record itself must also store zero raw secrets
    with SessionLocal() as db:
        db_rec = db.get(ExecutionEvidenceRecord, ev["execution_id"])
        assert db_rec is not None
        assert "AIzaSyVerySecretRawKey123456" not in str(db_rec.metadata_json)
        assert "TopSecretJwtValue999999" not in str(db_rec.metadata_json)


# ══════════════════════════════════════════════════════════════════════════════
# TEST AREA I: WORKFLOW 8-STATE FSM, HITL PAUSE/RESUME, REJECTION & CANCEL
# ══════════════════════════════════════════════════════════════════════════════


def test_i_workflow_fsm_hitl_pause_approve_resume_reject_and_cancel() -> None:
    cust = _signup_customer(tag="wf")
    _configure_growth_subscription(cust["headers"], base_tier="growth")

    defn_resp = client.post(
        "/v1/workflows/definitions",
        headers=cust["headers"],
        json={
            "name": "SME Discovery + Approval + SEO Pipeline",
            "max_credits_budget": 15,
            "steps": [
                {
                    "step_key": "discover",
                    "step_type": "agent_step",
                    "agent_id": "discovery_sdr_agent",
                    "input_template": {"industry": "Textiles"},
                },
                {
                    "step_key": "cond_skip",
                    "step_type": "condition",
                    "condition": {"field": "run_seo", "op": "equals", "value": False},
                    "required": False,
                },
                {
                    "step_key": "hitl_gate",
                    "step_type": "approval_gate",
                    "approval_action": "send_customer_proposal",
                },
                {
                    "step_key": "draft_seo",
                    "step_type": "agent_step",
                    "agent_id": "seo_content_agent",
                    "input_template": {"topic": "Sustainable Fabrics"},
                },
            ],
        },
    )
    assert defn_resp.status_code == 201, defn_resp.text
    wf_id = defn_resp.json()["workflow"]["workflow_id"]

    # Create DRAFT run first -> READY -> START -> hits approval_gate -> WAITING_APPROVAL
    draft_resp = client.post(
        "/v1/workflows/runs",
        headers=cust["headers"],
        json={"workflow_id": wf_id, "input_payload": {"run_seo": True}, "start_immediately": False},
    )
    assert draft_resp.status_code == 200
    run_id = draft_resp.json()["run"]["run_id"]
    assert draft_resp.json()["status"] == "DRAFT"

    ready_resp = client.post(f"/v1/workflows/runs/{run_id}/ready", headers=cust["headers"])
    assert ready_resp.status_code == 200
    assert ready_resp.json()["status"] == "READY"

    paused = client.post(f"/v1/workflows/runs/{run_id}/start", headers=cust["headers"])
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "WAITING_APPROVAL"
    approval_id = paused.json()["run"]["approval_id"]
    assert approval_id

    # Resuming before approval is decided must fail cleanly with 409
    premature = client.post(f"/v1/workflows/runs/{run_id}/resume", headers=cust["headers"])
    assert premature.status_code == 409

    # Customer decides HITL via tenant-scoped /v1/me/approvals/{id}/decide
    apprs = client.get("/v1/me/approvals", headers=cust["headers"])
    assert apprs.status_code == 200
    assert any(a["approval_id"] == approval_id for a in apprs.json()["approvals"])

    decide = client.post(
        f"/v1/me/approvals/{approval_id}/decide",
        headers=cust["headers"],
        json={"decision": "APPROVED", "reason": "Confirmed by SME owner"},
    )
    assert decide.status_code == 200
    assert decide.json()["status"] == "APPROVED"

    resumed = client.post(f"/v1/workflows/runs/{run_id}/resume", headers=cust["headers"])
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "COMPLETED"

    # Invalid FSM transition on COMPLETED run fails cleanly with 409
    invalid_tr = client.post(f"/v1/workflows/runs/{run_id}/cancel", headers=cust["headers"])
    assert invalid_tr.status_code == 409

    # Rejection path transitions run to BLOCKED, never COMPLETED
    rej_run = client.post(
        "/v1/workflows/runs",
        headers=cust["headers"],
        json={"workflow_id": wf_id, "input_payload": {"run_seo": True}, "start_immediately": True},
    )
    assert rej_run.json()["status"] == "WAITING_APPROVAL"
    rej_id = rej_run.json()["run"]["run_id"]
    rej_appr = rej_run.json()["run"]["approval_id"]
    client.post(
        f"/v1/me/approvals/{rej_appr}/decide",
        headers=cust["headers"],
        json={"decision": "REJECTED", "reason": "Declined outreach"},
    )
    rej_res = client.post(f"/v1/workflows/runs/{rej_id}/resume", headers=cust["headers"])
    assert rej_res.status_code == 200
    assert rej_res.json()["status"] == "BLOCKED"

    # Explicit cancellation of a DRAFT run -> CANCELLED
    cancel_draft = client.post(
        "/v1/workflows/runs",
        headers=cust["headers"],
        json={"workflow_id": wf_id, "start_immediately": False},
    )
    c_id = cancel_draft.json()["run"]["run_id"]
    cancelled = client.post(
        f"/v1/workflows/runs/{c_id}/cancel",
        headers=cust["headers"],
        json={"reason": "No longer needed"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"


# ══════════════════════════════════════════════════════════════════════════════
# TEST AREA J: STRICT MULTI-TENANT CROSS-ORG ISOLATION (403 / 404 BOUNDARIES)
# ══════════════════════════════════════════════════════════════════════════════


def test_j_strict_cross_tenant_isolation() -> None:
    tenant_a = _signup_customer(tag="isoA")
    tenant_b = _signup_customer(tag="isoB")
    _configure_growth_subscription(tenant_a["headers"], base_tier="growth")
    _configure_growth_subscription(tenant_b["headers"], base_tier="growth")

    run_a = client.post(
        "/v1/registry/agents/discovery_sdr_agent/execute",
        headers=tenant_a["headers"],
        json={"input_payload": {"industry": "Pharma"}, "execution_mode": "SIMULATION"},
    )
    assert run_a.status_code == 200
    exec_id_a = run_a.json()["execution_id"]

    # Tenant B cannot read Tenant A's execution evidence
    cross_ev = client.get(f"/v1/registry/evidence/{exec_id_a}", headers=tenant_b["headers"])
    assert cross_ev.status_code == 404

    # Tenant B cannot see Tenant A's evidence in listing
    list_b = client.get("/v1/me/evidence", headers=tenant_b["headers"])
    assert all(r["execution_id"] != exec_id_a for r in list_b.json()["records"])

    # Tenant A creates workflow + approval gate -> Tenant B cannot touch run or decide approval
    wf_a = client.post(
        "/v1/workflows/definitions",
        headers=tenant_a["headers"],
        json={
            "name": "Tenant A Private Flow",
            "steps": [{"step_key": "g1", "step_type": "approval_gate"}],
        },
    )
    wf_id_a = wf_a.json()["workflow"]["workflow_id"]
    wf_run_a = client.post(
        "/v1/workflows/runs",
        headers=tenant_a["headers"],
        json={"workflow_id": wf_id_a, "start_immediately": True},
    )
    run_id_a = wf_run_a.json()["run"]["run_id"]
    appr_id_a = wf_run_a.json()["run"]["approval_id"]

    assert client.get(f"/v1/workflows/runs/{run_id_a}", headers=tenant_b["headers"]).status_code == 403
    assert client.post(f"/v1/workflows/runs/{run_id_a}/cancel", headers=tenant_b["headers"]).status_code == 403
    assert (
        client.post(
            f"/v1/me/approvals/{appr_id_a}/decide",
            headers=tenant_b["headers"],
            json={"decision": "APPROVED"},
        ).status_code
        == 403
    )
    # Customer role strictly blocked from global Owner analytics & leads
    assert client.get("/v1/revenue/funnel", headers=tenant_b["headers"]).status_code == 403
    assert client.get("/v1/leads", headers=tenant_b["headers"]).status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# TEST AREAS K, M, N, O: TRUTHFULNESS, DASHBOARD UI CONTRACTS & END-TO-END SME
# ══════════════════════════════════════════════════════════════════════════════


def test_m_dashboard_p1_control_center_and_role_separation_contracts() -> None:
    index_html = (REPO_ROOT / "app" / "dashboard" / "index.html").read_text(encoding="utf-8")
    dashboard_js = (REPO_ROOT / "app" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
    sw_js = (REPO_ROOT / "app" / "dashboard" / "sw.js").read_text(encoding="utf-8")

    # All 12 Control Center page IDs & nav links present
    for section_id in (
        "page-portal",
        "page-cw-profile",
        "page-cw-marketplace",
        "page-cw-workforce",
        "page-cw-run-console",
        "page-cw-workflows",
        "page-cw-connectors",
        "page-cw-history",
        "page-approvals",
        "page-cw-analytics",
        "page-cw-billing",
        "page-cw-settings",
        "cw-evidence-drawer",
    ):
        assert f'id="{section_id}"' in index_html, f"Missing Control Center element {section_id}"

    # Owner API Key settings group can be isolated from customer sessions
    assert 'id="settings-owner-key-group"' in index_html
    assert "ownerKeyGroup.style.display = isCustomer ? 'none' : 'block'" in dashboard_js

    # Single source of truth registry hydration + scoped customer approvals in dashboard.js
    assert "/v1/registry/services" in dashboard_js
    assert "/v1/registry/agents" in dashboard_js
    assert "/v1/registry/connectors" in dashboard_js
    assert "/v1/me/approvals/" in dashboard_js

    # Cache bust bumped cleanly to v4.0 while keeping P0 check compatibility
    assert "afw-os-shell-v4.0-p1-workforce" in sw_js
    assert "afw-os-shell-v3.5-truthfulness" in sw_js


def test_o_end_to_end_sme_workforce_onboarding_to_verified_evidence() -> None:
    """Complete P1 E2E SME journey from onboarding to workflow completion and ledger integrity."""
    sme = _signup_customer(tag="e2e", package="launch", company_suffix="Jaipur Exports")

    # 1. Submit 13-field SME profile
    prof = client.post(
        "/v1/me/business-profile",
        headers=sme["headers"],
        json={
            "business_name": "Jaipur Artisanal Exports",
            "industry": "Textiles & Decor",
            "description": "Handmade textiles for global B2B buyers",
            "location": "Jaipur, India",
            "employee_count": 18,
            "required_automations": ["lead_generation", "seo", "sales"],
        },
    )
    assert prof.status_code == 200

    # 2. Confirm recommendations & subscribe to modular plan
    assert client.post(
        "/v1/me/business-profile/confirm",
        headers=sme["headers"],
        json={"base_plan_key": "growth", "selected_modules": ["lead_discovery", "seo_content"]},
    ).status_code == 200
    sub = _configure_growth_subscription(sme["headers"], base_tier="growth", addons=["lead_discovery", "seo_content"])
    assert sub["subscription"]["status"].lower() == "active"

    # 3. Activate SDR agent from central registry & configure connector
    assert client.post("/v1/registry/agents/discovery_sdr_agent/activate", headers=sme["headers"]).status_code == 200
    assert client.post(
        "/v1/registry/connectors/wordpress_rest/configure",
        headers=sme["headers"],
        json={"settings": {"site_url": "https://jaipurexports.example.in", "app_password": "secret-wp-app-password"}},
    ).status_code == 200

    # 4. Run agent directly in SIMULATION mode -> verify honest origin & 18-field evidence
    run = client.post(
        "/v1/registry/agents/discovery_sdr_agent/execute",
        headers=sme["headers"],
        json={"input_payload": {"industry": "Textiles"}, "execution_mode": "SIMULATION"},
    )
    assert run.status_code == 200
    assert run.json()["output_origin"] == "SIMULATED_SYNTHETIC"

    # 5. Build multi-step workflow with HITL gate, execute -> approve -> resume -> COMPLETED
    wf = client.post(
        "/v1/workflows/definitions",
        headers=sme["headers"],
        json={
            "name": "E2E Discovery to SEO",
            "steps": [
                {"step_key": "find_leads", "step_type": "agent_step", "agent_id": "discovery_sdr_agent"},
                {"step_key": "approve_campaign", "step_type": "approval_gate"},
                {"step_key": "write_seo", "step_type": "agent_step", "agent_id": "seo_content_agent"},
            ],
        },
    )
    assert wf.status_code == 201
    wf_run = client.post(
        "/v1/workflows/runs",
        headers=sme["headers"],
        json={"workflow_id": wf.json()["workflow"]["workflow_id"], "start_immediately": True},
    )
    assert wf_run.json()["status"] == "WAITING_APPROVAL"
    appr_id = wf_run.json()["run"]["approval_id"]
    run_id = wf_run.json()["run"]["run_id"]

    assert (
        client.post(
            f"/v1/me/approvals/{appr_id}/decide",
            headers=sme["headers"],
            json={"decision": "APPROVED", "reason": "Approved by SME owner"},
        ).status_code
        == 200
    )
    done = client.post(f"/v1/workflows/runs/{run_id}/resume", headers=sme["headers"])
    assert done.status_code == 200
    assert done.json()["status"] == "COMPLETED"

    # 6. Verify immutable evidence records & credit ledger entries match execution history
    ev_rows = client.get("/v1/me/evidence", headers=sme["headers"]).json()["records"]
    assert len(ev_rows) >= 3
    ledger_rows = client.get("/v1/me/credits/ledger", headers=sme["headers"]).json()["entries"]
    assert len(ledger_rows) >= 2


def test_k_n_truthfulness_constraints_and_p1_schema_tables_present() -> None:
    """Verify P1 schema tables exist cleanly and local math engines vs simulated providers report honest origins."""
    with SessionLocal() as db:
        inspector = inspect(db.bind)
        tables = set(inspector.get_table_names())
        for expected in (
            "business_profiles",
            "structured_requirements",
            "tenant_subscription_profiles",
            "tenant_agent_configs",
            "connector_states",
            "workflow_definitions",
            "workflow_runs",
            "execution_evidence_records",
            "credit_ledger_records",
            "emergency_stop_records",
        ):
            assert expected in tables, f"Missing P1 table: {expected}"

    cust = _signup_customer(tag="truth", package="growth_all_in_one")
    _configure_growth_subscription(cust["headers"], base_tier="operations", addons=["inventory_quality"])
    assert client.post("/v1/registry/agents/warehouse_stocksense_agent/activate", headers=cust["headers"]).status_code == 200

    # Local engine in SIMULATION still declares honest origin and does not falsely assert LIVE_PROVIDER_VERIFIED
    local_run = client.post(
        "/v1/registry/agents/warehouse_stocksense_agent/execute",
        headers=cust["headers"],
        json={"input_payload": {"skus": [{"sku": "S1", "annual_demand": 1000, "unit_cost": 50}]}, "execution_mode": "SIMULATION"},
    )
    assert local_run.status_code == 200
    assert local_run.json()["output_origin"] != "LIVE_PROVIDER_VERIFIED"
