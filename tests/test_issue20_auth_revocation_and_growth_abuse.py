"""Security tests for P0 hardcoded backdoor removal and Issue #20
(user deactivation, JWT revocation on credential/role change, public growth API quotas, and redirect SSRF).
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.smb_search_source import _AUDIT_CACHE, audit_live_website_seo_geo
from app.api.v1.growth_suite import _reset_growth_rate_limits
from app.db.database import Base, get_db
from app.db.models import OrganizationRecord, UserRecord
from app.main import app
from app.security.auth import hash_password

ENV_OWNER_KEY = "fresh-rotated-owner-key-32-chars-ok!"
ENV_MGR_KEY = "fresh-rotated-manager-key-32chars!!"


@pytest.fixture()
def sec_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("OWNER_API_KEY", ENV_OWNER_KEY)
    monkeypatch.setenv("MANAGER_API_KEY", ENV_MGR_KEY)
    monkeypatch.setenv("JWT_SECRET_KEY", "issue20-jwt-secret-key-32-chars-min!")
    _reset_growth_rate_limits()
    _AUDIT_CACHE.clear()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionLocal()

    org = OrganizationRecord(
        id="org-sec-20",
        name="Revocation Test Org",
        slug="revocation-test-org",
        tier="pro",
        is_active=True,
        metadata_json={"package_key": "company_os_pro"},
    )
    admin_user = UserRecord(
        id="user-admin-20",
        org_id=org.id,
        email="admin@sec20.test",
        full_name="Admin Sec20",
        role="tenant_admin",
        password_hash=hash_password("InitialPass!123"),
        is_active=True,
    )
    member_user = UserRecord(
        id="user-member-20",
        org_id=org.id,
        email="member@sec20.test",
        full_name="Member Sec20",
        role="tenant_admin",
        password_hash=hash_password("MemberPass!123"),
        is_active=True,
    )
    db.add_all([org, admin_user, member_user])
    db.commit()

    def _override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    try:
        yield client, db, org, admin_user, member_user
    finally:
        _reset_growth_rate_limits()
        _AUDIT_CACHE.clear()
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_hardcoded_compromised_backdoor_keys_are_always_rejected(sec_env):
    """P0 regression: Former hardcoded keys in auth.py MUST NEVER authenticate when not in env."""
    client, _db, _org, _admin, _member = sec_env

    for leaked_key in (
        "JCNgmM5bVjXTKLaBwfAcP8E_uRxGBvp9XaF-xB5c_LhXDL0w5nnk4HOaIy6qeoGC",
        "x_NwJFYiaMGYDs2k2Ztqyav0FxQd98hn1szgMRSta6AIBJuvpYnJ2c7BY5nuINcI",
        "staging-owner-verify-key-2026-isolated-32chars-minimum",
    ):
        resp = client.get("/v1/cs/release-readiness", headers={"X-API-Key": leaked_key})
        assert resp.status_code == 401, f"Compromised key must be rejected with 401, got {resp.status_code}"

    # Fresh env-configured key succeeds
    ok = client.get("/v1/cs/release-readiness", headers={"X-API-Key": ENV_OWNER_KEY})
    assert ok.status_code == 200


def test_deactivated_user_password_reset_and_role_downgrade_invalidate_active_jwts(sec_env):
    """Issue #20: Previously valid JWTs fail immediately upon deactivation, password reset, role downgrade, or org suspension."""
    client, db, org, admin_user, member_user = sec_env

    # Login both users to obtain genuine Bearer JWTs
    r_login_admin = client.post("/v1/auth/login", json={"email": admin_user.email, "password": "InitialPass!123"})
    assert r_login_admin.status_code == 200
    admin_hdr = {"Authorization": f"Bearer {r_login_admin.json()['access_token']}"}

    r_login_mem = client.post("/v1/auth/login", json={"email": member_user.email, "password": "MemberPass!123"})
    assert r_login_mem.status_code == 200
    mem_hdr = {"Authorization": f"Bearer {r_login_mem.json()['access_token']}"}

    # Both tokens initially work
    assert client.get("/v1/auth/me", headers=admin_hdr).status_code == 200
    assert client.get("/v1/auth/me", headers=mem_hdr).status_code == 200

    # 1. Role downgrade via accounts endpoint bumps token_version -> old admin token immediately rejected (401)
    r_down = client.post(
        f"/v1/accounts/orgs/{org.id}/users/{member_user.id}/role",
        json={"role": "member"},
        headers=admin_hdr,
    )
    assert r_down.status_code == 200, r_down.text
    assert client.get("/v1/auth/me", headers=mem_hdr).status_code == 401

    # Re-login gets fresh token with downgraded 'member' role
    r_relogin = client.post("/v1/auth/login", json={"email": member_user.email, "password": "MemberPass!123"})
    assert r_relogin.status_code == 200
    fresh_mem_hdr = {"Authorization": f"Bearer {r_relogin.json()['access_token']}"}
    assert client.get("/v1/auth/me", headers=fresh_mem_hdr).json()["role"] == "member"

    # 2. Password reset invalidates existing token immediately (401)
    member_user.password_hash = hash_password("RotatedNewPass!999")
    db.commit()
    assert client.get("/v1/auth/me", headers=fresh_mem_hdr).status_code == 401

    # 3. User deactivation immediately blocks previously valid JWT (403)
    admin_user.is_active = False
    db.commit()
    assert client.get("/v1/auth/me", headers=admin_hdr).status_code == 403

    # Re-activate user and suspend organization -> blocked immediately (403)
    admin_user.is_active = True
    org.is_active = False
    db.commit()
    assert client.get("/v1/auth/me", headers=admin_hdr).status_code == 403


def test_public_growth_endpoints_rate_limits_and_payload_budgets(sec_env, monkeypatch: pytest.MonkeyPatch):
    """Issue #20: Per-IP & per-session quotas return 429; oversized history/keywords return 422."""
    client, _db, _org, _admin, _member = sec_env
    monkeypatch.setenv("PUBLIC_GROWTH_CHAT_SESSION_RPM", "2")
    monkeypatch.setenv("PUBLIC_GROWTH_AUDIT_IP_RPM", "2")

    # 1. Oversized conversation history (> 20 items) rejected with 422
    r_big_hist = client.post(
        "/v1/growth/sales-closer/chat",
        json={
            "session_id": "sess-oversized",
            "prospect_name": "Test Buyer",
            "prospect_contact": "buyer@company.in",
            "message": "Pricing?",
            "history": [{"role": "user", "content": "hi"}] * 25,
        },
    )
    assert r_big_hist.status_code == 422

    # 2. Repeated chat requests hit per-session quota (429 + Retry-After)
    chat_body = {
        "session_id": "sess-quota-1",
        "prospect_name": "Test Buyer",
        "prospect_contact": "buyer@company.in",
        "message": "Tell me about the 14-day pilot",
    }
    assert client.post("/v1/growth/sales-closer/chat", json=chat_body).status_code == 200
    assert client.post("/v1/growth/sales-closer/chat", json=chat_body).status_code == 200
    r_throttled = client.post("/v1/growth/sales-closer/chat", json=chat_body)
    assert r_throttled.status_code == 429
    assert "retry-after" in {k.lower() for k in r_throttled.headers}

    # 3. Repeated audit-domain requests hit per-IP quota (429)
    with patch("app.api.v1.growth_suite.audit_live_website_seo_geo", return_value={"audit_status": "ESTIMATED_OFFLINE", "seo_geo_gap_score": 50}), \
         patch("app.agents.sources.is_safe_public_url", return_value=True):
        assert client.post("/v1/growth/audit-domain", json={"website_url": "https://example.com"}).status_code == 200
        assert client.post("/v1/growth/audit-domain", json={"website_url": "https://example.com"}).status_code == 200
        r_audit_429 = client.post("/v1/growth/audit-domain", json={"website_url": "https://example.com"})
        assert r_audit_429.status_code == 429


def test_ssrf_blocks_private_ipv6_and_redirect_to_metadata(sec_env):
    """Issue #20: Direct private/IPv6 URLs AND 302 redirects to cloud metadata are rejected with 400 BLOCKED_SSRF."""
    client, _db, _org, _admin, _member = sec_env

    # 1. Direct private IPv4, metadata, and IPv6 loopback URLs
    for bad_url in (
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]:8000/",
        "http://10.0.0.1/",
    ):
        _reset_growth_rate_limits()
        r = client.post("/v1/growth/audit-domain", json={"website_url": bad_url})
        assert r.status_code == 400, f"Expected 400 SSRF block for {bad_url}, got {r.status_code}"

    # 2. Public URL redirecting (302) to cloud metadata IP must be blocked as BLOCKED_SSRF
    def _mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public-redirector.example":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
        return httpx.Response(200, text="should never be reached")

    mock_transport = httpx.MockTransport(_mock_handler)
    with patch("app.agents.sources.is_safe_public_url", side_effect=lambda u: "public-redirector.example" in u), \
         patch("app.agents.sources.SSRFSafeTransport", return_value=mock_transport):
        res = audit_live_website_seo_geo("https://public-redirector.example", timeout=2.0)
        assert res["audit_status"] == "BLOCKED_SSRF"
