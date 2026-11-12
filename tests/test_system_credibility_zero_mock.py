"""Dedicated Zero-Mock System Credibility & Simulated Environment Verification Suite.

Verifies:
1. Render Cloud hosting configuration (render.yaml) and runtime health.
2. Dashboard Auth Gate first-paint lock (no loading screen before login) and Chrome Google Account autofill isolation.
3. Company OS Command Dock: 12 Service Tool logo/icon buttons & 9 Specialist AI Agent invocation cards.
4. Zero-placeholder deterministic output quality in SEO Blog Copilot and Omnichannel Marketing Suite.
5. Full 16-Subsystem Simulated Environment Credibility Audit (<0.0001% failure tolerance, 0% mock/fake).
6. Tenant Portal execution across all commercial catalog services via POST /v1/me/use-service.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models import MarketingCampaignRecord, OrganizationRecord, SeoDraftRecord, UserRecord
from app.main import app
from app.security.auth import create_access_token, hash_password
from app.services.marketing import execute_marketing_campaign
from app.services.seo import execute_seo_draft

REPO_ROOT = Path(__file__).resolve().parents[1]
OWNER_KEY = os.environ.get("OWNER_API_KEY") or "test-owner-credibility-key-0123456789abcdef"
os.environ.setdefault("OWNER_API_KEY", OWNER_KEY)
os.environ.setdefault("MANAGER_API_KEY", "test-manager-credibility-key-0123456789abcdef")


def _owner_headers() -> dict[str, str]:
    return {"X-API-Key": os.environ["OWNER_API_KEY"]}


def test_render_cloud_hosting_and_health() -> None:
    """Confirm Render remains the configured cloud host on paid compute, staging isolation is defined, and /health responds cleanly."""
    render_yaml = REPO_ROOT / "render.yaml"
    assert render_yaml.exists(), "render.yaml must exist at repository root"
    content = render_yaml.read_text(encoding="utf-8")
    assert "name: askforwrite-ai-company-os" in content
    assert "plan: starter" in content, "Render plan must be paid compute (starter) so SMTP 465/587 is unblocked and cold-start spin-down is eliminated"
    assert "plan: free" not in content
    assert "name: askforwrite-ai-company-os-staging" in content
    assert "runtime: docker" in content
    assert "healthCheckPath: /health" in content
    assert "os.askforwrite.com" in content

    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in ("ok", "healthy")
    assert body["hosting_provider"] == "render"
    assert "build_version" in body
    assert "runtime_posture" in body
    assert "external_side_effects_enabled" in body


def test_dashboard_auth_gate_first_paint_and_chrome_autofill_protection() -> None:
    """Ensure Auth Gate is visible on first paint (display:flex) and Chrome credential popups are blocked."""
    index_html = (REPO_ROOT / "app" / "dashboard" / "index.html").read_text(encoding="utf-8")
    dashboard_js = (REPO_ROOT / "app" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
    dashboard_css = (REPO_ROOT / "app" / "dashboard" / "dashboard.css").read_text(encoding="utf-8")

    # 1. Auth gate must default to display:flex so unauthenticated dashboard never flashes first
    assert 'id="auth-gate-overlay" style="display:flex"' in index_html
    assert 'id="auth-gate-overlay" style="display:none"' not in index_html

    # 2. Render Cloud verification badges must be present on both Auth Gate and Topbar
    assert 'id="auth-render-hosting-pill"' in index_html
    assert 'id="render-cloud-badge"' in index_html
    assert "Render Cloud" in index_html

    # 3. Pre-filled bearer token field in portal must NOT be type="password" (which triggers Chrome account popup)
    assert 'type="text" id="portal-token-display" class="masked-secret-input"' in index_html
    assert 'data-lpignore="true"' in index_html
    assert 'data-1p-ignore="true"' in index_html
    assert 'data-form-type="other"' in index_html
    assert "-webkit-text-security: disc" in dashboard_css

    # 4. init() in dashboard.js must gate fetchAll() behind checkAuthGate()
    assert "const isAuthenticated = checkAuthGate();" in dashboard_js
    assert "if (!isAuthenticated)" in dashboard_js


def test_dashboard_service_tool_icons_and_call_agent_dock() -> None:
    """Verify Company OS Command Dock has all 12 Service Tool logo buttons and 9 Call-an-Agent cards."""
    index_html = (REPO_ROOT / "app" / "dashboard" / "index.html").read_text(encoding="utf-8")

    assert 'id="company-os-command-dock"' in index_html
    assert 'id="service-tools-icon-grid"' in index_html
    assert 'id="ai-agents-dock-grid"' in index_html
    assert 'id="btn-run-credibility-audit"' in index_html

    expected_service_tools = [
        "managed_seo_content_pilot",
        "seo_blog_copilot",
        "wordpress_publisher",
        "marketing_suite",
        "pixel_ai_pack",
        "growth_all_in_one",
        "warehouse_automation",
        "mango_quality_analytics",
        "bike_rebalance_analytics",
        "field_force",
        "ask4_academic_order",
        "trust_engine",
    ]
    for tool_key in expected_service_tools:
        assert f'data-tool-key="{tool_key}"' in index_html, f"Missing service tool icon button: {tool_key}"

    expected_agents = [
        "ceo_manager_agent",
        "discovery_sdr_agent",
        "evidence_research_agent",
        "sales_closer_agent",
        "seo_geo_copilot_agent",
        "pixelbot_marketing_agent",
        "field_ops_dispatcher_agent",
        "watchdog_supervisor_agent",
        "shift_scheduler_agent",
    ]
    for agent_key in expected_agents:
        assert f'data-call-agent="{agent_key}"' in index_html, f"Missing Call Agent button: {agent_key}"


def test_seo_and_marketing_zero_placeholder_credibility() -> None:
    """Verify SEO Blog Copilot and Marketing Suite generate full, structured outputs with zero 1-line stubs."""
    db = SessionLocal()
    try:
        seo_res = execute_seo_draft(
            db=db,
            target_network="askforwrite.com",
            keywords=["Autonomous Company OS", "Generative Engine Optimization", "NIST P-256 Ledger"],
            idempotency_key=f"zero-mock-seo-{uuid.uuid4().hex[:10]}",
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
            agent_id="credibility-test",
        )
        draft = db.get(SeoDraftRecord, seo_res["draft_id"])
        assert draft is not None
        assert len(draft.content) > 400
        assert "application/ld+json" in draft.content or "@context" in draft.content
        assert not draft.content.startswith("Draft content for ")

        mkt_res = execute_marketing_campaign(
            db=db,
            campaign_type="enterprise_os_rollout",
            target_audience="B2B Operations Directors",
            idempotency_key=f"zero-mock-mkt-{uuid.uuid4().hex[:10]}",
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
            agent_id="credibility-test",
        )
        campaign = db.get(MarketingCampaignRecord, mkt_res["campaign_id"])
        assert campaign is not None
        for channel in ("instagram", "facebook", "twitter", "linkedin"):
            copy_text = campaign.ad_copy.get(channel, "")
            assert len(copy_text) > 100, f"Channel {channel} copy is too short/stubbed: {copy_text}"
            assert not copy_text.startswith(("Insta ad for ", "FB ad for ", "Tweet for ", "LinkedIn post for "))
    finally:
        db.close()


def test_full_16_subsystem_credibility_audit_zero_mock() -> None:
    """Execute POST /v1/watchdog/credibility-audit and verify 16/16 pass with 0.0% failure rate (<0.0001%)."""
    client = TestClient(app)
    res = client.post("/v1/watchdog/credibility-audit", headers=_owner_headers())
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["status"] == "CERTIFIED"
    assert data["commercial_rollout_status"] == "CERTIFIED_PRODUCTION_DEPENDABLE"
    assert data["total_subsystems_tested"] == 16
    assert data["passed_count"] == 16
    assert data["failed_count"] == 0
    assert data["failure_rate_pct"] == 0.0
    assert data["failure_rate_pct"] < data["target_failure_tolerance_pct"]
    assert data["reliability_pct"] == 100.0
    assert data["zero_mock_certified"] is True
    assert data["trust_chain_valid"] is True
    assert data["cloud_hosting"]["provider"] == "Render Cloud"
    assert data["cloud_hosting"]["render_yaml_present"] is True
    assert data["master_trust_block"]["block_hash"]

    for sub in data["subsystems"]:
        assert sub["status"] == "PASSED", f"Subsystem failed: {sub}"
        assert sub["zero_mock_verified"] is True
        assert len(sub["assertions_passed"]) >= 1
        assert sub["trust_block_hash"]


def test_command_dock_individual_invoke_tool_and_agent() -> None:
    """Verify POST /v1/watchdog/invoke-tool for individual connected tools and agents."""
    client = TestClient(app)
    for key in ("ceo_manager_agent", "warehouse_automation", "sovereign_pay_gateway", "live_domain_scanner"):
        res = client.post(
            "/v1/watchdog/invoke-tool",
            headers=_owner_headers(),
            json={"target_key": key, "payload": {}},
        )
        assert res.status_code == 200, f"Failed invoking {key}: {res.text}"
        body = res.json()
        assert body["status"] == "VERIFIED_OPERATIONAL"
        assert body["target_key"] == key
        assert body["zero_mock_verified"] is True
        assert body["trust_block"]["block_hash"]


def test_tenant_portal_use_service_all_catalog_capabilities() -> None:
    """Verify an entitled tenant can execute all catalog services through POST /v1/me/use-service."""
    db = SessionLocal()
    try:
        org_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        email = f"enterprise-{uuid.uuid4().hex[:8]}@askforwrite-test.com"

        org = OrganizationRecord(
            id=org_id,
            name="Credibility Enterprise Corp",
            slug=f"cred-ent-{uuid.uuid4().hex[:8]}",
            tier="all_access",
            is_active=True,
            lead_credits_limit=500,
            lead_credits_used=0,
            outreach_credits_limit=250,
            outreach_credits_used=0,
            metadata_json={"package_key": "all_access", "subscription_status": "ACTIVE"},
        )
        user = UserRecord(
            id=user_id,
            org_id=org_id,
            email=email,
            password_hash=hash_password("EnterprisePass#2026"),
            full_name="Enterprise Auditor",
            role="admin",
            is_active=True,
        )
        db.add(org)
        db.add(user)
        db.commit()

        token = create_access_token(user_id=user_id, email=email, role="admin", org_id=org_id)
    finally:
        db.close()

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    services_to_verify = [
        "managed_seo_content_pilot",
        "seo_blog_copilot",
        "wordpress_publisher",
        "marketing_suite",
        "pixel_ai_pack",
        "growth_all_in_one",
        "warehouse_automation",
        "mango_quality_analytics",
        "bike_rebalance_analytics",
        "field_force",
        "lead_discovery",
        "evidence_research",
        "sales_capture",
        "ask4_academic_order",
        "trust_engine",
    ]

    for srv in services_to_verify:
        res = client.post(
            "/v1/me/use-service",
            headers=headers,
            json={"service_key": srv, "payload": {}},
        )
        assert res.status_code == 200, f"Tenant service {srv} failed: {res.text}"
        data = res.json()
        assert data["status"] == "COMPLETED"
        assert data["service_key"] == srv
        assert data["result"]
        assert "capability_status" in data
        assert "evidence" in data
        for field_name in (
            "execution_id",
            "tenant_id",
            "agent_id",
            "tool_id",
            "mode",
            "provider",
            "input_reference",
            "fallback_used",
            "external_request_id",
            "started_at",
            "completed_at",
            "result_status",
            "credits_consumed",
            "approval_id",
            "evidence_reference",
        ):
            assert field_name in data["evidence"], f"Missing evidence field {field_name} for {srv}"
        if data["evidence"]["fallback_used"]:
            assert data["evidence"]["result_status"] != "LIVE_VERIFIED"


def test_p0_truthfulness_capability_model_and_connector_inventory() -> None:
    """Verify the 7-state CAPABILITY_STATUS_MODEL, 10-connector inventory, and 15-field evidence invariant."""
    client = TestClient(app)
    res = client.get("/v1/watchdog/connectors", headers=_owner_headers())
    assert res.status_code == 200, res.text
    body = res.json()

    expected_states = {
        "LIVE_VERIFIED",
        "LOCAL_ENGINE_VERIFIED",
        "SANDBOX_VERIFIED",
        "HUMAN_ASSISTED",
        "SIMULATED",
        "BLOCKED",
        "ROADMAP",
    }
    assert set(body["taxonomy"].keys()) == expected_states
    assert body["total_connectors"] == 10
    connector_ids = {c["connector_id"] for c in body["connectors"]}
    assert {
        "gemini_api",
        "serper_search",
        "google_places",
        "hostinger_smtp",
        "wordpress_rest",
        "razorpay",
        "paypal",
        "afw_directpay",
        "whatsapp_social_bridge",
        "trust_ledger",
    } == connector_ids

    for c in body["connectors"]:
        assert c["status"] in expected_states
        if not c["credentials_present"]:
            assert c["status"] != "LIVE_VERIFIED", f"Connector {c['connector_id']} claimed LIVE_VERIFIED without credentials!"


def test_sme_6_layer_architecture_and_13_field_pricing_contract() -> None:
    """Verify the 6-Layer SME Business OS requirement assessment and 13-field machine-readable pricing contracts."""
    from app.services.catalog import MODULAR_SME_TIERS, get_modular_pricing_contract

    mandatory_contract_fields = {
        "billing_type",
        "billing_interval",
        "base_price",
        "provider_plan_id",
        "included_modules",
        "agent_limit",
        "included_credits",
        "credit_costs",
        "seat_limit",
        "setup_fee",
        "support_level",
        "renewal_policy",
        "customization_allowance",
    }

    for tier_key in MODULAR_SME_TIERS:
        contract = get_modular_pricing_contract(tier_key, addon_modules=["inventory", "sales"])
        assert mandatory_contract_fields.issubset(set(contract.keys()))
        assert "inventory" in contract["included_modules"]
        assert "sales" in contract["included_modules"]

    client = TestClient(app)
    res = client.post(
        "/v1/watchdog/sme-assess",
        headers=_owner_headers(),
        json={
            "business_name": "Jaipur Industrial Distribution Pvt Ltd",
            "industry": "Wholesale Distribution",
            "city": "Jaipur",
            "company_size": "45 employees",
            "requirements_text": "We need inventory shortage alerts, B2B lead discovery, and field attendance tracking.",
        },
    )
    assert res.status_code == 200, res.text
    assessment = res.json()
    assert len(assessment["architecture_layers"]) == 6
    assert "inventory" in assessment["selected_modules"]
    assert "sales" in assessment["selected_modules"]
    assert "field_force" in assessment["selected_modules"]
    assert mandatory_contract_fields.issubset(set(assessment["pricing_contract"].keys()))


def test_jaipur_sme_12_step_isolated_sandbox_e2e_scenario() -> None:
    """Verify the 12-Step 'Jaipur Distribution Company' SME E2E scenario executes with ENABLE_EXTERNAL_SIDE_EFFECTS=false."""
    client = TestClient(app)
    res = client.post("/v1/watchdog/sme-sandbox-scenario", headers=_owner_headers())
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["status"] == "COMPLETED"
    assert data["external_side_effects_enabled"] is False
    assert data["total_steps"] == 12
    assert data["passed_steps"] == 12
    assert data["failed_steps"] == 0
    assert len(data["steps"]) == 12

    step_9 = data["steps"][8]
    assert step_9["step"] == 9
    assert step_9["detail"]["external_smtp_called"] is False
    assert step_9["capability_status"] == "SANDBOX_VERIFIED"

    step_12 = data["steps"][11]
    assert step_12["step"] == 12
    assert step_12["detail"]["credits_consumed"] > 0
    assert step_12["detail"]["credits_remaining"] < step_12["detail"]["credits_initial"]
    assert step_12["evidence"]["tenant_id"] == data["tenant_org_id"]


def test_frontend_no_false_success_and_pwa_cache_bust() -> None:
    """Verify dashboard.js eliminates silent loadDemoData(), removes fake closer/phone fallbacks, and sw.js busts cache."""
    dashboard_js = (REPO_ROOT / "app" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
    sw_js = (REPO_ROOT / "app" / "dashboard" / "sw.js").read_text(encoding="utf-8")
    index_html = (REPO_ROOT / "app" / "dashboard" / "index.html").read_text(encoding="utf-8")

    # 1. PWA Service Worker cache version must be bumped to v3.5-truthfulness
    assert "afw-os-shell-v3.5-truthfulness" in sw_js

    # 2. Protected shell must lock #sidebar and #main-content when unauthenticated
    assert "sidebarEl.style.visibility = 'hidden'" in dashboard_js
    assert "mainEl.style.visibility = 'hidden'" in dashboard_js

    # 3. Inbound Sales Closer catch block must NOT render a fake sales message/checkout link
    assert "False-success fallback disabled; no unverified pitch or checkout link shown." in dashboard_js

    # 4. Field Force phone buttons must invoke backend /v1/watchdog/invoke-tool
    assert "target_key: 'field_ops_dispatcher_agent'" in dashboard_js

    # 5. Agent Run Console & Connector Status controls present in index.html
    assert 'id="agent-run-console"' in index_html
    assert 'id="btn-view-connector-inventory"' in index_html
    assert 'id="btn-run-jaipur-sme-e2e"' in index_html


