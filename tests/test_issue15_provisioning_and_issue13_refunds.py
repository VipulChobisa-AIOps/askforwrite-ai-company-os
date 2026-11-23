"""Regression tests for Issue #15 (fail-closed provisioning, zero Starter fallbacks)
and Issue #13 (minor-unit refund consistency, cumulative refunds, duplicate replay, and full-refund revocation).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    InvoiceRecord,
    OrganizationRecord,
    P2PaymentReconciliationRecord,
    SubscriptionRecord,
    UserRecord,
)
from app.main import app
from app.services.payment import PaymentProvider, WebhookEvent
from app.services.provisioning import auto_provision_tenant_on_payment

RAZORPAY_WH_SECRET = "test_rzp_whsec_issue13_issue15_32ch"


@pytest.fixture()
def pay_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", RAZORPAY_WH_SECRET)
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_issue13")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_secret_issue13")
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-ISSUE13-TEST")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionLocal()

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
        engine.dispose()


def _sign_razorpay(body_bytes: bytes) -> str:
    return hmac.new(RAZORPAY_WH_SECRET.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# ISSUE #15 — Fail-Closed Provisioning (Zero Silent Starter Fallbacks)
# ═══════════════════════════════════════════════════════════════════════════════


def test_directpay_missing_package_fails_closed_no_starter_fallback(pay_env):
    _client, db = pay_env
    event = WebhookEvent(
        id="evt_dp_missing_pkg",
        provider=PaymentProvider.AFW_DIRECTPAY,
        event_type="sovereign.payment.verified",
        raw_event_type="sovereign.payment.verified",
        resource_type="session",
        resource_id="sess_missing_pkg_01",
        data={
            "email": "buyer@directpay.test",
            "company_name": "DirectPay Corp",
            "amount": 2999.0,
            "currency": "INR",
            # package_key intentionally omitted!
        },
    )
    res = auto_provision_tenant_on_payment(db, event)
    assert res is not None
    assert res["status"] == "missing_package_withheld"
    assert db.query(OrganizationRecord).count() == 0
    assert db.query(UserRecord).count() == 0


def test_razorpay_missing_package_and_plan_id_fails_closed(pay_env):
    _client, db = pay_env
    event = WebhookEvent(
        id="evt_rzp_missing_pkg",
        provider=PaymentProvider.RAZORPAY,
        event_type="payment.captured",
        raw_event_type="payment.captured",
        resource_type="payment",
        resource_id="pay_missing_pkg_01",
        data={
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_missing_pkg_01",
                        "email": "buyer@razorpay.test",
                        "amount": 299900,
                        "currency": "INR",
                        "notes": {"company_name": "NoPkg Co"},
                    }
                }
            }
        },
    )
    res = auto_provision_tenant_on_payment(db, event)
    assert res is not None
    assert res["status"] == "missing_package_withheld"
    assert db.query(OrganizationRecord).count() == 0
    assert db.query(UserRecord).count() == 0


def test_paypal_missing_custom_id_or_description_guessing_fails_closed(pay_env):
    """PayPal must NEVER fall back to Starter or guess SKU from description/amount."""
    _client, db = pay_env
    event = WebhookEvent(
        id="evt_pp_desc_only",
        provider=PaymentProvider.PAYPAL,
        event_type="PAYMENT.CAPTURE.COMPLETED",
        raw_event_type="PAYMENT.CAPTURE.COMPLETED",
        resource_type="capture",
        resource_id="cap_desc_only_01",
        data={
            "resource": {
                "id": "cap_desc_only_01",
                "description": "AskforWrite AI Company OS (Starter) company_os_starter",
                "payer": {"email_address": "buyer@paypal-desc.test"},
                "amount": {"value": "39.00", "currency_code": "USD"},
            }
        },
    )
    res = auto_provision_tenant_on_payment(db, event)
    assert res is not None
    assert res["status"] == "missing_package_withheld"
    assert db.query(OrganizationRecord).count() == 0


def test_missing_currency_fails_closed_across_providers(pay_env):
    _client, db = pay_env
    event = WebhookEvent(
        id="evt_missing_curr",
        provider=PaymentProvider.RAZORPAY,
        event_type="payment.captured",
        raw_event_type="payment.captured",
        resource_type="payment",
        resource_id="pay_no_curr",
        data={
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_no_curr",
                        "email": "nocurr@test.io",
                        "amount": 499900,
                        "notes": {"notes_package": "managed_seo_content_pilot"},
                    }
                }
            }
        },
    )
    res = auto_provision_tenant_on_payment(db, event)
    assert res is not None
    assert res["status"] == "unsupported_currency_withheld"
    assert db.query(OrganizationRecord).count() == 0


def test_unrecognized_provider_plan_id_fails_closed(pay_env):
    _client, db = pay_env
    event = WebhookEvent(
        id="evt_unknown_plan_id",
        provider=PaymentProvider.PAYPAL,
        event_type="BILLING.SUBSCRIPTION.ACTIVATED",
        raw_event_type="BILLING.SUBSCRIPTION.ACTIVATED",
        resource_type="subscription",
        resource_id="sub_unknown_plan",
        data={
            "resource": {
                "id": "sub_unknown_plan",
                "plan_id": "P-UNKNOWN-ROGUE-PLAN-999",
                "payer": {"email_address": "rogue@plan.test"},
                "amount": {"value": "89.00", "currency_code": "USD"},
            }
        },
    )
    res = auto_provision_tenant_on_payment(db, event)
    assert res is not None
    assert res["status"] == "unknown_package_withheld"
    assert db.query(OrganizationRecord).count() == 0


@patch("app.services.provisioning.get_email_dispatcher")
def test_verified_provider_plan_id_and_subscription_record_provision_cleanly(mock_disp_fn, pay_env):
    mock_disp_fn.return_value = MagicMock()
    _client, db = pay_env

    # 1. Canonical contract provider_plan_id mapping: plan_afw_growth_inr -> growth_all_in_one
    event_rzp = WebhookEvent(
        id="evt_rzp_valid_plan",
        provider=PaymentProvider.RAZORPAY,
        event_type="subscription.activated",
        raw_event_type="subscription.activated",
        resource_type="subscription",
        resource_id="sub_rzp_growth_01",
        data={
            "payload": {
                "subscription": {
                    "entity": {
                        "id": "sub_rzp_growth_01",
                        "plan_id": "plan_afw_growth_inr",
                        "email": "founder@growthco.in",
                        "amount": 699900,
                        "currency": "INR",
                    }
                }
            }
        },
    )
    res1 = auto_provision_tenant_on_payment(db, event_rzp)
    assert res1 is not None
    assert res1["status"] == "provisioned"
    assert res1["package_key"] == "growth_all_in_one"

    # 2. Persisted SubscriptionRecord mapping -> operations_suite
    db.add(
        SubscriptionRecord(
            id="sub-rec-ops-01",
            org_id=None,
            customer_id="cust-ops-01",
            provider="paypal",
            provider_subscription_id="I-OPS-MAPPED-01",
            plan_id="P-CUSTOM-OPS-EXT-01",
            status="created",
            metadata_json={"internal_sku": "operations_suite"},
        )
    )
    db.commit()

    event_pp = WebhookEvent(
        id="evt_pp_mapped_sub",
        provider=PaymentProvider.PAYPAL,
        event_type="BILLING.SUBSCRIPTION.ACTIVATED",
        raw_event_type="BILLING.SUBSCRIPTION.ACTIVATED",
        resource_type="subscription",
        resource_id="I-OPS-MAPPED-01",
        data={
            "resource": {
                "id": "I-OPS-MAPPED-01",
                "plan_id": "P-CUSTOM-OPS-EXT-01",
                "payer": {"email_address": "ops@warehouse.io"},
                "amount": {"value": "129.00", "currency_code": "USD"},
            }
        },
    )
    res2 = auto_provision_tenant_on_payment(db, event_pp)
    assert res2 is not None
    assert res2["status"] == "provisioned"
    assert res2["package_key"] == "operations_suite"


def test_webhook_route_withheld_missing_package_does_not_fabricate_p2_reconciliation(pay_env):
    """POST /v1/webhooks/payment with missing SKU must fail closed and NOT default P2 reconciliation to pilot."""
    client, db = pay_env
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_wh_missing_sku_01",
                    "email": "nopkg@webhook.test",
                    "amount": 499900,
                    "currency": "INR",
                    "notes": {},
                }
            }
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    resp = client.post(
        "/v1/webhooks/payment",
        content=raw,
        headers={
            "content-type": "application/json",
            "x-razorpay-signature": _sign_razorpay(raw),
            "x-razorpay-event-id": "evt_wh_missing_sku_01",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provisioning"]["status"] == "missing_package_withheld"
    assert "p2_reconciliation" not in body
    assert db.query(OrganizationRecord).count() == 0
    assert db.query(P2PaymentReconciliationRecord).count() == 0


# ═══════════════════════════════════════════════════════════════════════════════
# ISSUE #13 — Refund Unit Consistency, Cumulative Refunds, Replay & Revocation
# ═══════════════════════════════════════════════════════════════════════════════


@patch("app.services.provisioning.get_email_dispatcher")
def test_razorpay_partial_duplicate_cumulative_and_full_refund_revocation(mock_disp_fn, pay_env):
    """Verify minor-unit consistency (paise vs paise): no 100x conversion error,
    partial refunds preserve access, duplicate replays do not double-count,
    and cumulative full refund revokes org entitlements."""
    mock_disp_fn.return_value = MagicMock()
    client, db = pay_env

    # Step 1: Capture ₹4,999.00 (499900 paise) for managed_seo_content_pilot
    cap_payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_issue13_rzp_01",
                    "email": "pilot@agency.in",
                    "amount": 499900,
                    "currency": "INR",
                    "notes": {
                        "notes_package": "managed_seo_content_pilot",
                        "notes_company": "Agency Issue13",
                    },
                }
            }
        },
    }
    cap_raw = json.dumps(cap_payload).encode("utf-8")
    r_cap = client.post(
        "/v1/webhooks/payment",
        content=cap_raw,
        headers={
            "content-type": "application/json",
            "x-razorpay-signature": _sign_razorpay(cap_raw),
            "x-razorpay-event-id": "evt_issue13_cap_01",
        },
    )
    assert r_cap.status_code == 200, r_cap.text
    org_id = r_cap.json()["provisioning"]["org_id"]

    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="pay_issue13_rzp_01").first()
    assert inv is not None
    assert inv.amount == 499900.0  # Stored in minor units (paise)
    assert inv.status == "paid"

    # Step 2: Zero/missing refund amount guard must preserve tenant access
    zero_rfnd = {
        "event": "refund.processed",
        "payload": {"refund": {"entity": {"id": "rfnd_zero", "payment_id": "pay_issue13_rzp_01", "amount": 0}}},
    }
    zero_raw = json.dumps(zero_rfnd).encode("utf-8")
    r_zero = client.post(
        "/v1/webhooks/payment",
        content=zero_raw,
        headers={
            "content-type": "application/json",
            "x-razorpay-signature": _sign_razorpay(zero_raw),
            "x-razorpay-event-id": "evt_issue13_rfnd_zero",
        },
    )
    assert r_zero.status_code == 200
    assert r_zero.json()["settlement_classification"] == "REFUND_PENDING_VERIFICATION"
    db.expire_all()
    assert db.get(OrganizationRecord, org_id).tier == "managed_pilot"

    # Step 3: Partial refund of ₹1,500.00 (150000 paise) — MUST NOT revoke entitlements or mis-scale by 100x
    part1 = {
        "event": "refund.processed",
        "payload": {"refund": {"entity": {"id": "rfnd_part_1", "payment_id": "pay_issue13_rzp_01", "amount": 150000}}},
    }
    part1_raw = json.dumps(part1).encode("utf-8")
    r_p1 = client.post(
        "/v1/webhooks/payment",
        content=part1_raw,
        headers={
            "content-type": "application/json",
            "x-razorpay-signature": _sign_razorpay(part1_raw),
            "x-razorpay-event-id": "evt_issue13_rfnd_p1",
        },
    )
    assert r_p1.status_code == 200
    assert r_p1.json()["settlement_classification"] == "PARTIALLY_REFUNDED"
    db.expire_all()
    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="pay_issue13_rzp_01").first()
    org = db.get(OrganizationRecord, org_id)
    assert inv.status == "partially_refunded"
    assert inv.metadata_json["refunded_amount"] == 150000.0
    assert org.tier == "managed_pilot"
    assert len(org.metadata_json.get("entitled_capabilities", [])) > 0

    # Step 4: Duplicate replay of the SAME partial refund event MUST be ignored (no double-counting!)
    r_p1_dup = client.post(
        "/v1/webhooks/payment",
        content=part1_raw,
        headers={
            "content-type": "application/json",
            "x-razorpay-signature": _sign_razorpay(part1_raw),
            "x-razorpay-event-id": "evt_issue13_rfnd_p1",
        },
    )
    assert r_p1_dup.status_code == 200
    assert r_p1_dup.json()["status"] == "duplicate"
    db.expire_all()
    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="pay_issue13_rzp_01").first()
    assert inv.metadata_json["refunded_amount"] == 150000.0

    # Step 5: Second partial refund of ₹3,499.00 (349900 paise -> cumulative 499900 == 100%) revokes access
    part2 = {
        "event": "refund.processed",
        "payload": {"refund": {"entity": {"id": "rfnd_part_2", "payment_id": "pay_issue13_rzp_01", "amount": 349900}}},
    }
    part2_raw = json.dumps(part2).encode("utf-8")
    r_p2 = client.post(
        "/v1/webhooks/payment",
        content=part2_raw,
        headers={
            "content-type": "application/json",
            "x-razorpay-signature": _sign_razorpay(part2_raw),
            "x-razorpay-event-id": "evt_issue13_rfnd_p2",
        },
    )
    assert r_p2.status_code == 200
    assert r_p2.json()["settlement_classification"] == "REFUND_COMPLETED"
    db.expire_all()
    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="pay_issue13_rzp_01").first()
    org = db.get(OrganizationRecord, org_id)
    assert inv.status == "refunded"
    assert inv.metadata_json["refunded_amount"] == 499900.0
    assert org.tier == "free"
    assert org.metadata_json["entitled_capabilities"] == []


@patch("app.services.provisioning.get_email_dispatcher")
@patch("app.services.payment_paypal.PayPalProvider.verify_webhook", return_value=True)
def test_paypal_major_to_minor_refund_conversion_and_revocation(_mock_verify, mock_disp_fn, pay_env):
    """PayPal sends decimal major USD ('10.00', '29.00'); webhook converts once to minor cents matching InvoiceRecord.amount (3900)."""
    mock_disp_fn.return_value = MagicMock()
    client, db = pay_env

    # Step 1: Capture $39.00 USD for company_os_starter -> stored as 3900.0 minor units
    cap_body = json.dumps(
        {
            "id": "WH-PP-CAP-13",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource_type": "capture",
            "resource": {
                "id": "CAP_ISSUE13_01",
                "custom_id": "company_os_starter",
                "payer": {"email_address": "buyer@paypal-refund.test"},
                "amount": {"value": "39.00", "currency_code": "USD"},
            },
        }
    ).encode("utf-8")
    r_cap = client.post(
        "/v1/webhooks/payment",
        content=cap_body,
        headers={"content-type": "application/json", "paypal-transmission-id": "tx-cap-13"},
    )
    assert r_cap.status_code == 200, r_cap.text
    org_id = r_cap.json()["provisioning"]["org_id"]
    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="CAP_ISSUE13_01").first()
    assert inv is not None
    assert inv.amount == 3900.0

    # Step 2: Partial PayPal refund $10.00 -> 1000.0 minor units (access preserved)
    p1_body = json.dumps(
        {
            "id": "WH-PP-RFND-P1",
            "event_type": "PAYMENT.CAPTURE.REFUNDED",
            "resource_type": "refund",
            "resource": {
                "id": "RFND_PP_1",
                "supplementary_data": {"related_ids": {"capture_id": "CAP_ISSUE13_01"}},
                "amount": {"value": "10.00", "currency_code": "USD"},
            },
        }
    ).encode("utf-8")
    r_p1 = client.post(
        "/v1/webhooks/payment",
        content=p1_body,
        headers={"content-type": "application/json", "paypal-transmission-id": "tx-rfnd-p1"},
    )
    assert r_p1.status_code == 200
    assert r_p1.json()["settlement_classification"] == "PARTIALLY_REFUNDED"
    db.expire_all()
    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="CAP_ISSUE13_01").first()
    assert inv.metadata_json["refunded_amount"] == 1000.0
    assert db.get(OrganizationRecord, org_id).tier == "launch"

    # Step 3: Remaining PayPal refund $29.00 -> cumulative 3900.0 == 100% -> revoked
    p2_body = json.dumps(
        {
            "id": "WH-PP-RFND-P2",
            "event_type": "PAYMENT.CAPTURE.REFUNDED",
            "resource_type": "refund",
            "resource": {
                "id": "RFND_PP_2",
                "supplementary_data": {"related_ids": {"capture_id": "CAP_ISSUE13_01"}},
                "amount": {"value": "29.00", "currency_code": "USD"},
            },
        }
    ).encode("utf-8")
    r_p2 = client.post(
        "/v1/webhooks/payment",
        content=p2_body,
        headers={"content-type": "application/json", "paypal-transmission-id": "tx-rfnd-p2"},
    )
    assert r_p2.status_code == 200
    db.expire_all()
    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="CAP_ISSUE13_01").first()
    org = db.get(OrganizationRecord, org_id)
    assert inv.status == "refunded"
    assert inv.metadata_json["refunded_amount"] == 3900.0
    assert org.tier == "free"
    assert org.metadata_json["entitled_capabilities"] == []
