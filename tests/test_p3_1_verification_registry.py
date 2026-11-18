"""Tests for P3.1 Production Verification & Release Readiness Registry."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import InvoiceRecord, P3OperationalIncidentRecord
from app.main import app
from app.services.p3_1_verification_registry import (
    GSC_VERIFICATION_STATES,
    VERIFICATION_STATES,
    get_release_readiness_summary,
)

OWNER_KEY = "test-p31-rel-owner-key-32-chars!!"
MANAGER_KEY = "test-p31-rel-mgr-key-32-chars!!!"
JWT_SECRET = "test-p31-rel-jwt-secret-32chars!"


@pytest.fixture()
def registry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("OWNER_API_KEY", OWNER_KEY)
    monkeypatch.setenv("MANAGER_API_KEY", MANAGER_KEY)
    monkeypatch.setenv("JWT_SECRET_KEY", JWT_SECRET)
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_registry_123")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_secret_must_never_leak")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "rzp_whsec_must_never_leak")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "pp_client_must_never_leak")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "pp_secret_must_never_leak")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-REG-TEST")
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    monkeypatch.delenv("GSC_CLIENT_ID", raising=False)
    monkeypatch.delenv("GSC_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GSC_REDIRECT_URI", raising=False)

    db_file = tmp_path / "p31_registry.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def _override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    db = TestingSession()
    try:
        yield client, db
    finally:
        db.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_release_readiness_honest_states_and_capture_settlement_separation(registry_env, monkeypatch):
    client, db = registry_env

    # Seed one captured-not-settled and one settled invoice for Razorpay + PayPal
    db.add_all(
        [
            InvoiceRecord(
                id="inv_rzp_cap",
                org_id="org_reg_1",
                customer_id="cust_1",
                provider="razorpay",
                provider_invoice_id="inv_ext_rzp_cap",
                provider_payment_id="pay_cap_only",
                amount=199900.0,
                currency="INR",
                status="paid",
                metadata_json={"settlement_status": "CAPTURED_PENDING_SETTLEMENT", "payout_settled": False},
            ),
            InvoiceRecord(
                id="inv_rzp_setl",
                org_id="org_reg_1",
                customer_id="cust_1",
                provider="razorpay",
                provider_invoice_id="inv_ext_rzp_setl",
                provider_payment_id="pay_settled",
                amount=199900.0,
                currency="INR",
                status="paid",
                metadata_json={"settlement_status": "SETTLED_TO_MERCHANT", "payout_settled": True},
            ),
            InvoiceRecord(
                id="inv_pp_cap",
                org_id="org_reg_1",
                customer_id="cust_2",
                provider="paypal",
                provider_invoice_id="inv_ext_pp_cap",
                provider_payment_id="CAP_ONLY",
                amount=2900.0,
                currency="USD",
                status="paid",
                metadata_json={"settlement_status": "CAPTURED_PENDING_SETTLEMENT", "payout_settled": False},
            ),
        ]
    )
    db.add(
        P3OperationalIncidentRecord(
            org_id=None,
            incident_type="BACKUP_DRILL",
            severity="HIGH",
            status="OPEN",
            resource_ref="backup_scope:neon_preflight",
            summary="pg_dump missing locally",
            details_json={"restore_tested": False},
        )
    )
    db.commit()

    # Simulate missing pg_dump/pg_restore explicitly
    monkeypatch.setattr("app.services.p3_1_verification_registry.shutil.which", lambda name: None)

    summary = get_release_readiness_summary(db, org_id="org_reg_1", probe_live_health=False)
    serialized = json.dumps(summary)
    assert "rzp_secret_must_never_leak" not in serialized
    assert "rzp_whsec_must_never_leak" not in serialized
    assert "pp_secret_must_never_leak" not in serialized
    assert "rzp_test_registry_123" not in serialized

    assert summary["overall_release_readiness"] == "BLOCKED"
    assert summary["production_cutover_approved"] is False
    assert set(summary["allowed_states"]) == set(VERIFICATION_STATES)
    assert set(summary["gsc_states"]) == set(GSC_VERIFICATION_STATES)

    subs = summary["subsystems"]
    for _k, val in subs.items():
        assert val["state"] in VERIFICATION_STATES

    assert subs["auth_and_tenant_isolation"]["state"] == "LOCAL_VERIFIED"
    assert subs["dashboard_browser_e2e"]["state"] == "LOCAL_VERIFIED"
    assert subs["google_search_console"]["state"] == "BLOCKED"
    assert subs["google_search_console"]["gsc_lifecycle_state"] == "BLOCKED"
    assert subs["google_search_console"]["attribution_gap"] == "ATTRIBUTION_REQUIRES_CONNECTED_GSC"

    assert subs["razorpay_payments"]["state"] == "LIVE_VERIFIED"
    assert subs["razorpay_payments"]["live_transaction_state"] == "LIVE_VERIFIED"
    assert subs["razorpay_payments"]["capture_equals_settlement"] is False
    assert subs["razorpay_payments"]["capture_vs_settlement"]["captured_pending_settlement_count"] == 1
    assert subs["razorpay_payments"]["capture_vs_settlement"]["settled_to_merchant_count"] == 1

    assert subs["paypal_payments"]["state"] == "SANDBOX_VERIFIED"
    assert subs["paypal_payments"]["capture_vs_settlement"]["captured_pending_settlement_count"] == 1
    assert subs["paypal_payments"]["capture_vs_settlement"]["settled_to_merchant_count"] == 0

    assert subs["postgresql_backup_restore"]["state"] == "BLOCKED"
    assert subs["postgresql_backup_restore"]["latest_recorded_drill"]["restore_tested"] is False
    assert subs["render_production_environment"]["live_health_probe_state"] == "NOT_TESTED"
    assert subs["render_production_environment"]["state"] == "BLOCKED"


def test_release_readiness_endpoint_rbac_and_schema(registry_env):
    client, _db = registry_env

    assert client.get("/v1/cs/release-readiness").status_code == 401

    reg = client.post(
        "/v1/auth/register",
        json={"email": "tenant.blocked@example.com", "password": "StrongPassword!123", "full_name": "Tenant", "company_name": "Acme Co"},
    )
    assert reg.status_code in (200, 201), reg.text
    token = reg.json()["access_token"]
    r_tenant = client.get("/v1/cs/release-readiness", headers={"Authorization": f"Bearer {token}"})
    assert r_tenant.status_code == 403

    r_mgr = client.get("/v1/cs/release-readiness", headers={"X-API-Key": MANAGER_KEY})
    assert r_mgr.status_code == 200
    body = r_mgr.json()
    assert body["overall_release_readiness"] == "BLOCKED"
    assert "render_production_environment" in body["subsystems"]
