"""Truthful public claims & pricing parity tests (Issue #22)
and end-to-end tenant subscription lifecycle + RBAC matrix tests (Issue #24).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import CustomerRecord, OrganizationRecord, SubscriptionRecord, UserRecord
from app.main import app
from app.security.auth import create_access_token, hash_password
from app.services.catalog import CATALOG
from app.services.payment import CustomerInfo, PaymentProvider, PlanInfo, SubscriptionInfo, SubscriptionStatus

OWNER_KEY = "issue24-platform-owner-key-32chars!"
MGR_KEY = "issue24-platform-mgr-key-32-chars!!"


@pytest.fixture()
def sub_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("OWNER_API_KEY", OWNER_KEY)
    monkeypatch.setenv("MANAGER_API_KEY", MGR_KEY)
    monkeypatch.setenv("JWT_SECRET_KEY", "issue24-jwt-secret-key-32-chars-ok!")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionLocal()

    org_a = OrganizationRecord(id="org-sub-a", name="Tenant Sub A", slug="tenant-sub-a", tier="growth", is_active=True)
    org_b = OrganizationRecord(id="org-sub-b", name="Tenant Sub B", slug="tenant-sub-b", tier="growth", is_active=True)
    pw = hash_password("StrongPass!123")
    admin_a = UserRecord(id="u-a-admin", org_id=org_a.id, email="admin@suba.test", full_name="Admin A", role="tenant_admin", password_hash=pw, is_active=True)
    mgr_a = UserRecord(id="u-a-mgr", org_id=org_a.id, email="mgr@suba.test", full_name="Mgr A", role="manager", password_hash=pw, is_active=True)
    mem_a = UserRecord(id="u-a-mem", org_id=org_a.id, email="mem@suba.test", full_name="Mem A", role="member", password_hash=pw, is_active=True)
    admin_b = UserRecord(id="u-b-admin", org_id=org_b.id, email="admin@subb.test", full_name="Admin B", role="tenant_admin", password_hash=pw, is_active=True)
    db.add_all([org_a, org_b, admin_a, mgr_a, mem_a, admin_b])
    db.commit()

    def _hdr(u: UserRecord) -> dict[str, str]:
        tok = create_access_token(user_id=u.id, email=u.email, role=u.role, org_id=u.org_id, password_hash=u.password_hash)
        return {"Authorization": f"Bearer {tok}"}

    def _override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    try:
        yield {
            "client": client,
            "db": db,
            "org_a": org_a,
            "org_b": org_b,
            "hdr_owner": {"X-API-Key": OWNER_KEY},
            "hdr_plat_mgr": {"X-API-Key": MGR_KEY},
            "hdr_admin_a": _hdr(admin_a),
            "hdr_mgr_a": _hdr(mgr_a),
            "hdr_mem_a": _hdr(mem_a),
            "hdr_admin_b": _hdr(admin_b),
        }
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_issue22_public_service_pages_and_growth_status_align_with_catalog_and_boundaries(sub_env):
    """Issue #22: Public pages and APIs reflect canonical prices, billing types, and operational boundaries."""
    client = sub_env["client"]

    # 1. /services directory matches canonical clustered prices & removes misleading blanket claims
    r_dir = client.get("/services")
    assert r_dir.status_code == 200
    body_dir = r_dir.text
    for expected in ("₹2,999", "₹6,999", "₹9,999", "₹17,999", "₹44,999", "0% AskforWrite platform commission", "Owner HITL approval"):
        assert expected in body_dir
    assert "zero payment gateway commission" not in body_dir.lower()

    # 2. Individual pilot page states 14-day one-time billing, legal/refund links, and zero-guarantee boundaries
    r_pilot = client.get("/services/managed_seo_content_pilot")
    assert r_pilot.status_code == 200
    pilot_html = r_pilot.text
    pilot_pkg = CATALOG["managed_seo_content_pilot"]
    assert f"₹{pilot_pkg.price_inr:,}" in pilot_html
    assert f"${pilot_pkg.price_usd}" in pilot_html
    assert "14-Day Managed Pilot (One-Time, Non-Renewing)" in pilot_html
    assert "/legal/refund-policy" in pilot_html
    assert "No ranking, AI citation, conversion, or ROI guarantees" in pilot_html
    assert "Purchase &amp; Activate Instant Access" not in pilot_html

    # 3. /v1/growth/status returns canonical price + explicit capability boundaries
    r_status = client.get("/v1/growth/status")
    assert r_status.status_code == 200
    st = r_status.json()
    assert st["price_inr"] == CATALOG["growth_all_in_one"].price_inr
    assert st["price_usd"] == CATALOG["growth_all_in_one"].price_usd
    assert st["capability_boundaries"]["creative_studio"] == "DRAFT_AND_PROMPT_SPECS_ONLY"
    assert st["capability_boundaries"]["seo_blog_copilot"] == "HITL_APPROVAL_AND_WP_CREDENTIALS_REQUIRED"
    assert "24/7 Autonomous" not in st["pillars"]["inbound_sales_closer"]


def test_issue24_subscription_role_matrix_and_tenant_isolation_end_to_end(sub_env):
    """Issue #24: Owner-only plan creation; tenant-scoped customer, subscription create/get/list/cancel; zero cross-tenant access."""
    client = sub_env["client"]
    db = sub_env["db"]
    org_a = sub_env["org_a"]
    org_b = sub_env["org_b"]

    mock_provider = MagicMock()
    mock_provider.create_plan = AsyncMock(
        return_value=PlanInfo(
            id="plan-int-1",
            name="Growth Plan",
            amount=699900,
            currency="INR",
            interval="monthly",
            provider=PaymentProvider.RAZORPAY,
            provider_plan_id="plan_rzp_mock_1",
            metadata={},
        )
    )
    mock_provider.create_customer = AsyncMock(
        return_value=CustomerInfo(
            id="cust-int-a1",
            email="billing@suba.test",
            name="Tenant Sub A",
            provider=PaymentProvider.RAZORPAY,
            provider_customer_id="cust_rzp_a1",
            metadata={},
        )
    )
    mock_provider.create_subscription = AsyncMock(
        return_value=SubscriptionInfo(
            id="sub-int-a1",
            customer_id="cust_rzp_a1",
            plan_id="plan_rzp_mock_1",
            status=SubscriptionStatus.CREATED,
            provider=PaymentProvider.RAZORPAY,
            provider_subscription_id="sub_rzp_a1",
            current_period_start="1790000000",
            current_period_end="1792592000",
            payment_url="https://rzp.io/i/mocksub",
            metadata={},
        )
    )
    mock_provider.get_subscription = AsyncMock(
        return_value=SubscriptionInfo(
            id="sub-int-a1",
            customer_id="cust_rzp_a1",
            plan_id="plan_rzp_mock_1",
            status=SubscriptionStatus.ACTIVE,
            provider=PaymentProvider.RAZORPAY,
            provider_subscription_id="sub_rzp_a1",
            current_period_start="1790000000",
            current_period_end="1792592000",
            payment_url="https://rzp.io/i/mocksub",
            metadata={},
        )
    )
    mock_provider.cancel_subscription = AsyncMock(
        return_value=SubscriptionInfo(
            id="sub-int-a1",
            customer_id="cust_rzp_a1",
            plan_id="plan_rzp_mock_1",
            status=SubscriptionStatus.CANCELLED,
            provider=PaymentProvider.RAZORPAY,
            provider_subscription_id="sub_rzp_a1",
            metadata={},
        )
    )

    with patch("app.api.v1.subscriptions.get_payment_provider", return_value=mock_provider):
        # 1. Plan creation: ONLY Platform Owner allowed (403 for Platform Manager, Tenant Admin, Manager, Member)
        plan_body = {"name": "Growth INR", "amount": 699900, "currency": "INR", "interval": "monthly", "provider": "razorpay"}
        for blocked_hdr in (sub_env["hdr_plat_mgr"], sub_env["hdr_admin_a"], sub_env["hdr_mgr_a"], sub_env["hdr_mem_a"]):
            assert client.post("/v1/subscriptions/plans", json=plan_body, headers=blocked_hdr).status_code == 403
        r_plan = client.post("/v1/subscriptions/plans", json=plan_body, headers=sub_env["hdr_owner"])
        assert r_plan.status_code == 200
        assert r_plan.json()["provider_plan_id"] == "plan_rzp_mock_1"

        # 2. Tenant A Admin creates customer & subscription for Tenant A; cannot target Tenant B
        assert (
            client.post(
                "/v1/subscriptions/customers",
                json={"email": "x@b.test", "name": "B", "provider": "razorpay", "org_id": org_b.id},
                headers=sub_env["hdr_admin_a"],
            ).status_code
            == 403
        )
        r_cust = client.post(
            "/v1/subscriptions/customers",
            json={"email": "billing@suba.test", "name": "Tenant Sub A", "provider": "razorpay"},
            headers=sub_env["hdr_admin_a"],
        )
        assert r_cust.status_code == 200
        cust_id = r_cust.json()["customer_id"]
        assert db.get(CustomerRecord, cust_id).org_id == org_a.id

        r_sub = client.post(
            "/v1/subscriptions/create",
            json={"customer_id": cust_id, "plan_id": "plan_rzp_mock_1", "provider": "razorpay"},
            headers=sub_env["hdr_admin_a"],
        )
        assert r_sub.status_code == 200
        sub_id = r_sub.json()["subscription_id"]
        assert db.get(SubscriptionRecord, sub_id).org_id == org_a.id

        # 3. Cross-tenant isolation: Tenant B Admin gets 403 on Tenant A's subscription, customer list, and cancel
        assert client.get(f"/v1/subscriptions/{sub_id}", headers=sub_env["hdr_admin_b"]).status_code == 403
        assert client.get(f"/v1/subscriptions/customer/{cust_id}", headers=sub_env["hdr_admin_b"]).status_code == 403
        assert client.post(f"/v1/subscriptions/{sub_id}/cancel", json={"cancel_at_period_end": True}, headers=sub_env["hdr_admin_b"]).status_code == 403

        # 4. Tenant A Member & Manager cannot cancel subscription (403); Tenant A Admin CAN view & cancel (200)
        assert client.post(f"/v1/subscriptions/{sub_id}/cancel", json={"cancel_at_period_end": True}, headers=sub_env["hdr_mem_a"]).status_code == 403
        assert client.post(f"/v1/subscriptions/{sub_id}/cancel", json={"cancel_at_period_end": True}, headers=sub_env["hdr_mgr_a"]).status_code == 403

        r_get = client.get(f"/v1/subscriptions/{sub_id}", headers=sub_env["hdr_admin_a"])
        assert r_get.status_code == 200
        assert r_get.json()["status"] == "active"

        r_cancel = client.post(
            f"/v1/subscriptions/{sub_id}/cancel",
            json={"cancel_at_period_end": True},
            headers=sub_env["hdr_admin_a"],
        )
        assert r_cancel.status_code == 200
        assert r_cancel.json()["status"] == "cancelled"
        db.expire_all()
        assert db.get(SubscriptionRecord, sub_id).status == "cancelled"
