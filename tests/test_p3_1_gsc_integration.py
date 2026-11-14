"""Comprehensive verification tests for Google Search Console (P3.1).

Covers all 10 integration controls and 5 explicit state transitions:
OAuth_CONNECTED -> PROPERTY_VERIFIED -> DATA_FETCH_VERIFIED -> ATTRIBUTION_READY / BLOCKED
using httpx.MockTransport and isolated SQLite DB sessions (never calling live Google APIs).
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import AuditLog, ConnectorStateRecord, P3ServiceDeliveryRecord
from app.main import app
from app.services.connectors import check_connector_execution_allowed, list_connectors
from app.services.gsc_integration import (
    GSC_STATES,
    GscIntegrationError,
    build_gsc_oauth_authorization_url,
    disconnect_gsc_account,
    exchange_gsc_oauth_code,
    fetch_gsc_search_analytics,
    get_gsc_status,
    verify_and_select_gsc_property,
)
from app.services.p3_delivery_health import create_service_delivery, transition_delivery_quality_state

TEST_OWNER_KEY = "test-p31-gsc-owner-key-32-chars!"
TEST_MANAGER_KEY = "test-p31-gsc-mgr-key-at-least32c!"
TEST_JWT_SECRET = "test-p31-gsc-jwt-secret-32chars!"


@pytest.fixture()
def gsc_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ALLOW_LIVE_SIDE_EFFECTS", "false")
    monkeypatch.setenv("OWNER_API_KEY", TEST_OWNER_KEY)
    monkeypatch.setenv("MANAGER_API_KEY", TEST_MANAGER_KEY)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)

    db_file = tmp_path / "gsc_p31_test.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    session = TestingSession()
    try:
        yield client, session
    finally:
        session.close()
        app.dependency_overrides.clear()
        engine.dispose()


def _register_customer(client: TestClient, *, email: str) -> tuple[str, dict[str, str]]:
    r = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "SyntheticGscPass!123",
            "full_name": "GSC Test User",
            "company_name": f"Co {email.split('@')[0]}",
            "role": "customer",
        },
    )
    assert r.status_code in (200, 201), r.text
    data = r.json()
    return data["org_id"], {"Authorization": f"Bearer {data['access_token']}"}


def _configure_gsc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GSC_CLIENT_ID", "test-gsc-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GSC_CLIENT_SECRET", "GOCSPX-test-secret-do-not-leak")
    monkeypatch.setenv("GSC_REDIRECT_URI", "https://os.askforwrite.com/v1/integrations/gsc/callback")
    monkeypatch.setenv("GSC_TOKEN_ENCRYPTION_KEY", "test-fernet-master-key-p3-1-gsc")


def _make_gsc_mock_transport(
    *,
    permission_level: str = "siteOwner",
    site_url: str = "sc-domain:acme-synthetic.com",
    refresh_should_fail: bool = False,
) -> tuple[httpx.MockTransport, dict[str, int]]:
    counters = {"token_exchange": 0, "token_refresh": 0, "sites": 0, "analytics": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://oauth2.googleapis.com/token"):
            body = parse_qs(request.content.decode("utf-8"))
            grant_type = (body.get("grant_type") or [""])[0]
            if grant_type == "authorization_code":
                counters["token_exchange"] += 1
                return httpx.Response(
                    200,
                    json={
                        "access_token": "ya29.synthetic_initial_access_token",
                        "refresh_token": "1//synthetic_refresh_token_secret",
                        "expires_in": 3600,
                        "scope": "https://www.googleapis.com/auth/webmasters.readonly",
                        "token_type": "Bearer",
                    },
                )
            if grant_type == "refresh_token":
                counters["token_refresh"] += 1
                if refresh_should_fail:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(
                    200,
                    json={
                        "access_token": "ya29.synthetic_refreshed_access_token",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                    },
                )

        if url.startswith("https://www.googleapis.com/webmasters/v3/sites/") and url.endswith("/searchAnalytics/query"):
            counters["analytics"] += 1
            req_json = json.loads(request.content.decode("utf-8"))
            if req_json.get("startDate", "").startswith("2026-09"):
                rows = [
                    {"keys": ["technical seo", "https://acme-synthetic.com/audit"], "clicks": 40, "impressions": 1000, "ctr": 0.04, "position": 14.2},
                ]
            else:
                rows = [
                    {"keys": ["technical seo", "https://acme-synthetic.com/audit"], "clicks": 115, "impressions": 2200, "ctr": 0.052, "position": 7.8},
                    {"keys": ["ai marketing ops", "https://acme-synthetic.com/ops"], "clicks": 60, "impressions": 900, "ctr": 0.067, "position": 5.4},
                ]
            return httpx.Response(200, json={"rows": rows})

        if url == "https://www.googleapis.com/webmasters/v3/sites":
            counters["sites"] += 1
            return httpx.Response(
                200,
                json={
                    "siteEntry": [
                        {"siteUrl": site_url, "permissionLevel": permission_level},
                    ]
                },
            )

        return httpx.Response(404, json={"error": f"Unhandled mock URL: {url}"})

    return httpx.MockTransport(handler), counters


def test_gsc_blocked_when_unconfigured_or_unsafe_redirect(gsc_env, monkeypatch: pytest.MonkeyPatch) -> None:
    client, db_session = gsc_env
    monkeypatch.delenv("GSC_CLIENT_ID", raising=False)
    monkeypatch.delenv("GSC_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GSC_REDIRECT_URI", raising=False)

    org_id, _headers = _register_customer(client, email="gsc-unconf@example.com")
    initial = get_gsc_status(db_session, org_id=org_id)
    assert initial["gsc_state"] == "BLOCKED"
    assert initial["oauth_configured"] is False
    assert set(initial["missing_env_vars"]) == {"GSC_CLIENT_ID", "GSC_CLIENT_SECRET", "GSC_REDIRECT_URI"}

    with pytest.raises(GscIntegrationError, match="Missing required Google Search Console OAuth env") as exc_info:
        build_gsc_oauth_authorization_url(db_session, org_id=org_id)
    assert exc_info.value.code == "GSC_OAUTH_NOT_CONFIGURED"

    _configure_gsc_env(monkeypatch)
    with pytest.raises(GscIntegrationError) as redir_err:
        build_gsc_oauth_authorization_url(db_session, org_id=org_id, redirect_uri="http://insecure.example.com/cb")
    assert redir_err.value.code == "GSC_INSECURE_REDIRECT_URI"

    with pytest.raises(GscIntegrationError) as scope_err:
        build_gsc_oauth_authorization_url(db_session, org_id=org_id, scopes=["https://www.googleapis.com/auth/gmail.send"])
    assert scope_err.value.code == "GSC_INVALID_SCOPE"


def test_gsc_full_lifecycle_all_5_states_encryption_refresh_and_attribution(
    gsc_env,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, db_session = gsc_env
    _configure_gsc_env(monkeypatch)
    caplog.set_level(logging.DEBUG)

    org_id, _headers = _register_customer(client, email="gsc-full@example.com")

    # Cannot query Search Analytics before OAuth + property verification
    with pytest.raises(GscIntegrationError) as pre_err:
        fetch_gsc_search_analytics(db_session, org_id=org_id, start_date="2026-10-01", end_date="2026-10-14")
    assert pre_err.value.code == "GSC_PROPERTY_REQUIRED"

    # 1. Generate OAuth URL + CSRF state
    auth_payload = build_gsc_oauth_authorization_url(db_session, org_id=org_id, actor="owner-test")
    parsed_url = urlparse(auth_payload["authorization_url"])
    qs = parse_qs(parsed_url.query)
    assert qs["client_id"] == ["test-gsc-client-id.apps.googleusercontent.com"]
    assert qs["redirect_uri"] == ["https://os.askforwrite.com/v1/integrations/gsc/callback"]
    assert qs["scope"] == ["https://www.googleapis.com/auth/webmasters.readonly"]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]

    transport, counters = _make_gsc_mock_transport()
    with httpx.Client(transport=transport) as mock_http:
        # 2. Reject mismatched CSRF state cleanly -> BLOCKED
        with pytest.raises(GscIntegrationError) as state_err:
            exchange_gsc_oauth_code(
                db_session,
                org_id=org_id,
                code="4/valid-code",
                state="tampered-state",
                http_client=mock_http,
            )
        assert state_err.value.code == "GSC_OAUTH_STATE_MISMATCH"
        assert get_gsc_status(db_session, org_id=org_id)["gsc_state"] == "BLOCKED"

        # 3. Valid OAuth code exchange -> OAuth_CONNECTED (still CONFIGURED_UNVERIFIED!)
        auth_payload = build_gsc_oauth_authorization_url(db_session, org_id=org_id)
        conn_state = exchange_gsc_oauth_code(
            db_session,
            org_id=org_id,
            code="4/synthetic-auth-code",
            state=auth_payload["state"],
            http_client=mock_http,
        )
        assert conn_state["gsc_state"] == "OAuth_CONNECTED"
        assert conn_state["capability_state"] == "CONFIGURED_UNVERIFIED"
        assert conn_state["has_access_cred"] is True
        assert conn_state["has_refresh_cred"] is True

        # Verify Fernet encrypted storage and zero token/cipher leakage anywhere
        db_rec = db_session.query(ConnectorStateRecord).filter_by(org_id=org_id, connector_id="google_search_console").one()
        cipher_blob = db_rec.config_summary.get("vault_cipher_payload", "")
        assert cipher_blob and "ya29.synthetic" not in cipher_blob and "1//synthetic" not in cipher_blob

        spec_entry = next(
            (c for c in list_connectors(db_session, org_id=org_id) if c["connector_id"] == "google_search_console"),
            None,
        )
        assert spec_entry is not None
        serialized_dump = json.dumps(spec_entry)
        assert "ya29.synthetic" not in serialized_dump
        assert "1//synthetic" not in serialized_dump
        assert "vault_cipher_payload" not in serialized_dump
        assert "GOCSPX-" not in serialized_dump

        # OAuth_CONNECTED alone MUST NOT satisfy analytics query
        with pytest.raises(GscIntegrationError) as need_prop:
            fetch_gsc_search_analytics(
                db_session,
                org_id=org_id,
                start_date="2026-10-01",
                end_date="2026-10-14",
                http_client=mock_http,
            )
        assert need_prop.value.code == "GSC_PROPERTY_REQUIRED"

        # 4. Property verification -> PROPERTY_VERIFIED
        prop_res = verify_and_select_gsc_property(
            db_session,
            org_id=org_id,
            site_url="sc-domain:acme-synthetic.com",
            http_client=mock_http,
        )
        assert prop_res["gsc_state"] == "PROPERTY_VERIFIED"
        assert prop_res["selected_property"] == "sc-domain:acme-synthetic.com"
        assert prop_res["property_permission"] == "siteOwner"

        # 5. Force token expiry -> verify automatic refresh_token rotation & DATA_FETCH_VERIFIED
        cfg = dict(db_rec.config_summary)
        cfg["token_expires_at"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        db_rec.config_summary = cfg
        db_session.commit()

        data_res = fetch_gsc_search_analytics(
            db_session,
            org_id=org_id,
            start_date="2026-10-01",
            end_date="2026-10-14",
            dimensions=["query", "page"],
            http_client=mock_http,
        )
        assert counters["token_refresh"] == 1
        assert data_res["gsc_state"] == "DATA_FETCH_VERIFIED"
        assert data_res["analytics"]["current"]["clicks"] == 175
        assert data_res["analytics"]["current"]["impressions"] == 3100

        # 6. Attribution query WITH baseline & delivery_id -> ATTRIBUTION_READY + persists to P3ServiceDeliveryRecord
        delivery = create_service_delivery(
            db_session,
            org_id=org_id,
            title="Organic Growth SEO Sprint",
            original_requirement="Improve non-branded SEO traffic via Search Console",
            approved_scope=["Audit", "Content Optimization"],
        )
        transition_delivery_quality_state(
            db_session,
            delivery_id=delivery["delivery_id"],
            target_state="IN_PROGRESS",
            actor="owner",
        )
        attr_res = fetch_gsc_search_analytics(
            db_session,
            org_id=org_id,
            start_date="2026-10-01",
            end_date="2026-10-14",
            baseline_start_date="2026-09-01",
            baseline_end_date="2026-09-14",
            dimensions=["query", "page"],
            delivery_id=delivery["delivery_id"],
            claimed_askforwrite_caused=True,
            http_client=mock_http,
        )
        assert attr_res["gsc_state"] == "ATTRIBUTION_READY"
        assert attr_res["has_baseline_attribution"] is True
        assert attr_res["analytics"]["delta_clicks"] == 135
        assert attr_res["delivery_updated"]["outcome_metrics"]["attribution_evidence_level"] == "GSC_VERIFIED_WITH_BASELINE"

        persisted_delivery = db_session.get(P3ServiceDeliveryRecord, delivery["delivery_id"])
        assert persisted_delivery is not None
        assert persisted_delivery.outcome_metrics_json["organic_traffic"] == 175

    # 7. Disconnect purges tokens and moves to BLOCKED
    disc = disconnect_gsc_account(db_session, org_id=org_id, actor="owner-test")
    assert disc["gsc_state"] == "BLOCKED"
    assert disc["has_access_cred"] is False
    assert disc["selected_property"] is None
    db_session.refresh(db_rec)
    assert "vault_cipher_payload" not in (db_rec.config_summary or {})

    # 8. Assert zero secrets leaked into logs or AuditLog rows
    assert "ya29.synthetic" not in caplog.text
    assert "1//synthetic" not in caplog.text
    assert "GOCSPX-test-secret" not in caplog.text
    audits = db_session.query(AuditLog).filter_by(capability_name="gsc_integration").all()
    assert len(audits) >= 3
    audit_dump = json.dumps([a.output_payload for a in audits])
    assert "ya29.synthetic" not in audit_dump
    assert "1//synthetic" not in audit_dump
    assert set(GSC_STATES) == {"OAuth_CONNECTED", "PROPERTY_VERIFIED", "DATA_FETCH_VERIFIED", "ATTRIBUTION_READY", "BLOCKED"}


def test_gsc_unverified_property_and_revoked_refresh_transition_to_blocked(
    gsc_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db_session = gsc_env
    _configure_gsc_env(monkeypatch)
    org_id, _headers = _register_customer(client, email="gsc-block@example.com")
    auth_payload = build_gsc_oauth_authorization_url(db_session, org_id=org_id)

    unverified_transport, _ = _make_gsc_mock_transport(permission_level="siteUnverifiedUser")
    with httpx.Client(transport=unverified_transport) as mock_http:
        exchange_gsc_oauth_code(
            db_session,
            org_id=org_id,
            code="4/code",
            state=auth_payload["state"],
            http_client=mock_http,
        )
        with pytest.raises(GscIntegrationError) as unv_err:
            verify_and_select_gsc_property(
                db_session,
                org_id=org_id,
                site_url="sc-domain:acme-synthetic.com",
                http_client=mock_http,
            )
        assert unv_err.value.code == "GSC_PROPERTY_UNVERIFIED"
        assert unv_err.value.status_code == 403
        assert get_gsc_status(db_session, org_id=org_id)["gsc_state"] == "BLOCKED"

    # Revoked refresh token clears vault and sets BLOCKED
    revoked_transport, _ = _make_gsc_mock_transport(permission_level="siteOwner", refresh_should_fail=True)
    with httpx.Client(transport=revoked_transport) as mock_http:
        auth2 = build_gsc_oauth_authorization_url(db_session, org_id=org_id)
        exchange_gsc_oauth_code(db_session, org_id=org_id, code="4/code2", state=auth2["state"], http_client=mock_http)
        verify_and_select_gsc_property(db_session, org_id=org_id, site_url="sc-domain:acme-synthetic.com", http_client=mock_http)

        rec = db_session.query(ConnectorStateRecord).filter_by(org_id=org_id, connector_id="google_search_console").one()
        cfg = dict(rec.config_summary)
        cfg["token_expires_at"] = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
        rec.config_summary = cfg
        db_session.commit()

        with pytest.raises(GscIntegrationError) as rev_err:
            fetch_gsc_search_analytics(db_session, org_id=org_id, start_date="2026-10-01", end_date="2026-10-14", http_client=mock_http)
        assert rev_err.value.code == "GSC_REFRESH_REVOKED"
        assert rev_err.value.status_code == 401
        assert get_gsc_status(db_session, org_id=org_id)["gsc_state"] == "BLOCKED"


def test_gsc_api_routes_tenant_isolation_and_registry_listing(
    gsc_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db_session = gsc_env
    _configure_gsc_env(monkeypatch)
    org_a, headers_a = _register_customer(client, email="gsc-tenant-a@example.com")
    org_b, headers_b = _register_customer(client, email="gsc-tenant-b@example.com")
    owner_headers = {"X-API-Key": TEST_OWNER_KEY}

    # Connector appears in /v1/connectors and blocks live execution when unverified
    connectors_list = list_connectors(db_session, org_id=org_a)
    gsc_conn = next((c for c in connectors_list if c["connector_id"] == "google_search_console"), None)
    assert gsc_conn is not None
    gate = check_connector_execution_allowed(db_session, "google_search_console", org_id=org_a)
    assert gate["allowed"] is False and gate["capability_state"] == "BLOCKED" and gate["reason"] is not None

    # Tenant A generates OAuth URL via /v1/me/integrations/gsc/oauth/url
    r_url = client.post("/v1/me/integrations/gsc/oauth/url", headers=headers_a, json={})
    assert r_url.status_code == 200, r_url.text
    assert "accounts.google.com/o/oauth2/v2/auth" in r_url.json()["authorization_url"]

    # Tenant B cannot see Tenant A's status or access CS operator GSC routes
    r_status_b = client.get("/v1/me/integrations/gsc/status", headers=headers_b)
    assert r_status_b.status_code == 200
    assert r_status_b.json()["org_id"] is None or r_status_b.json()["gsc_state"] == "BLOCKED"
    r_cross = client.get(f"/v1/cs/integrations/gsc/{org_a}/status", headers=headers_b)
    assert r_cross.status_code == 403

    # Owner endpoint rejects unconfigured live Analytics query cleanly (BLOCKED under staging lock / missing property)
    r_cs_status = client.get(f"/v1/cs/integrations/gsc/{org_a}/status", headers=owner_headers)
    assert r_cs_status.status_code == 200
    assert r_cs_status.json()["gsc_state"] == "BLOCKED"
