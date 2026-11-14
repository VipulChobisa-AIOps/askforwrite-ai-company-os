"""P3.1 Razorpay & PayPal Sandbox Verification + Capture-vs-Settlement Reconciliation Tests.

Verifies all Section 3 requirements using httpx.MockTransport and isolated SQLite DB:
1. Order/subscription creation (amount + currency)
2. Payment authorization & capture
3. Webhook signature validation (Razorpay HMAC-SHA256 & PayPal verify-webhook-signature API)
4. Duplicate webhook replay idempotency
5. Capture vs merchant settlement/payout separation (CAPTURED_PENDING_SETTLEMENT vs SETTLED_TO_MERCHANT)
6. Payment failure & subscription renewal grace/PAST_DUE lifecycle
7. Partial and cumulative full refund (including PayPal major-unit normalization)
8. Subscription renewal credit replenishment & cancellation entitlement revocation
9. Internal ledger/invoice/P2 reconciliation + non-secret config inspection
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import (
    InvoiceRecord,
    OrganizationRecord,
    P2PaymentReconciliationRecord,
    P3CustomerAccountRecord,
    SubscriptionRecord,
    WebhookEventRecord,
)
from app.main import app
from app.services.p3_revenue_growth import get_subscription_reliability_summary
from app.services.payment import PaymentProvider, inspect_payment_provider_config
from app.services.payment_paypal import PayPalProvider
from app.services.payment_razorpay import RazorpayProvider

RAZORPAY_WEBHOOK_SECRET = "rzp_sandbox_whsec_p31_verify_123456"
PAYPAL_WEBHOOK_ID = "WH-SANDBOX-P31-999"


def _run(coro):
    return asyncio.run(coro)


def _sign_razorpay(raw: bytes, secret: str = RAZORPAY_WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def _paypal_headers(tx_id: str) -> dict[str, str]:
    return {
        "paypal-transmission-id": tx_id,
        "paypal-transmission-time": "2026-11-14T10:00:00Z",
        "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-SANDBOX",
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-transmission-sig": "sandbox-sig-value",
        "content-type": "application/json",
    }


@pytest.fixture()
def payment_sandbox_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ALLOW_LIVE_SIDE_EFFECTS", "false")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_p31_sandbox_key")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_test_p31_sandbox_secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", RAZORPAY_WEBHOOK_SECRET)
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "pp_sandbox_client_p31")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "pp_sandbox_secret_p31")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", PAYPAL_WEBHOOK_ID)
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")

    db_file = tmp_path / "p31_payments_sandbox.db"
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


def test_razorpay_sandbox_order_capture_refund_and_settlement_api():
    """Verify Razorpay sandbox HTTP contract via httpx.MockTransport (never hitting live Razorpay)."""
    recorded_calls: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        recorded_calls.append((request.method, str(request.url), body))
        if request.method == "POST" and request.url.path == "/v1/orders":
            return httpx.Response(
                200,
                json={
                    "id": "order_rzp_sbx_001",
                    "entity": "order",
                    "amount": body["amount"],
                    "currency": body["currency"],
                    "status": "created",
                    "receipt": body.get("receipt", ""),
                },
            )
        if request.method == "POST" and request.url.path == "/v1/payments/pay_rzp_sbx_001/capture":
            return httpx.Response(
                200,
                json={
                    "id": "pay_rzp_sbx_001",
                    "order_id": "order_rzp_sbx_001",
                    "amount": body["amount"],
                    "currency": body["currency"],
                    "status": "captured",
                },
            )
        if request.method == "POST" and request.url.path == "/v1/payments/pay_rzp_sbx_001/refund":
            return httpx.Response(
                200,
                json={
                    "id": "rfnd_rzp_sbx_001",
                    "payment_id": "pay_rzp_sbx_001",
                    "amount": body.get("amount", 199900),
                    "status": "processed",
                },
            )
        if request.method == "GET" and request.url.path == "/v1/settlements/setl_rzp_sbx_001":
            return httpx.Response(
                200,
                json={
                    "id": "setl_rzp_sbx_001",
                    "entity": "settlement",
                    "amount": 195182,
                    "fees": 4718,
                    "status": "processed",
                    "utr": "UTR_SBX_001",
                },
            )
        return httpx.Response(404, json={"error": "unhandled"})

    provider = RazorpayProvider(transport=httpx.MockTransport(handler))

    async def _exercise():
        order = await provider.create_order(
            amount_minor=199900,
            currency="inr",
            receipt="rcpt_seo_pilot_01",
            notes={"package_key": "seo_blog_copilot"},
        )
        capture = await provider.capture_payment(
            payment_id="pay_rzp_sbx_001",
            amount_minor=199900,
            currency="inr",
        )
        refund = await provider.refund_payment(
            payment_id="pay_rzp_sbx_001",
            amount_minor=100000,
            notes={"reason": "partial_sandbox_refund"},
        )
        settlement = await provider.fetch_settlement("setl_rzp_sbx_001")
        return order, capture, refund, settlement

    order, capture, refund, settlement = _run(_exercise())
    assert order["id"] == "order_rzp_sbx_001"
    assert order["amount"] == 199900
    assert order["currency"] == "INR"
    assert capture["status"] == "captured"
    assert refund["id"] == "rfnd_rzp_sbx_001"
    assert refund["amount"] == 100000
    assert settlement["status"] == "processed"
    assert settlement["utr"] == "UTR_SBX_001"
    assert len(recorded_calls) == 4


def test_paypal_sandbox_order_capture_refund_and_payout_api(monkeypatch: pytest.MonkeyPatch):
    """Verify PayPal sandbox OAuth + v2 order/capture/refund + payout batch contract via MockTransport."""
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "pp_sbx_client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "pp_sbx_secret")
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")

    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(f"{request.method} {request.url}")
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok_pp_sandbox_123", "token_type": "Bearer"})
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        if request.url.path == "/v2/checkout/orders":
            return httpx.Response(
                201,
                json={
                    "id": "ORD_PP_SBX_001",
                    "status": "CREATED",
                    "intent": body["intent"],
                    "purchase_units": body["purchase_units"],
                },
            )
        if request.url.path == "/v2/checkout/orders/ORD_PP_SBX_001/capture":
            return httpx.Response(
                201,
                json={
                    "id": "ORD_PP_SBX_001",
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "payments": {
                                "captures": [
                                    {
                                        "id": "CAP_PP_SBX_001",
                                        "status": "COMPLETED",
                                        "amount": {"value": "29.00", "currency_code": "USD"},
                                    }
                                ]
                            }
                        }
                    ],
                },
            )
        if request.url.path == "/v2/payments/captures/CAP_PP_SBX_001/refund":
            return httpx.Response(
                201,
                json={"id": "RFND_PP_SBX_001", "status": "COMPLETED", "amount": body.get("amount")},
            )
        if request.url.path == "/v1/payments/payouts/BATCH_PP_SBX_001":
            return httpx.Response(
                200,
                json={"batch_header": {"payout_batch_id": "BATCH_PP_SBX_001", "batch_status": "SUCCESS"}},
            )
        return httpx.Response(404, json={"error": "unhandled"})

    provider = PayPalProvider(transport=httpx.MockTransport(handler))
    assert provider._base_url == PayPalProvider.SANDBOX_URL

    async def _exercise():
        order = await provider.create_order(
            amount=29.0,
            currency="USD",
            reference_id="prop_pp_001",
            return_url="https://example.test/return",
            cancel_url="https://example.test/cancel",
        )
        captured = await provider.capture_order(order_id=order["id"])
        refunded = await provider.refund_capture(capture_id="CAP_PP_SBX_001", amount=14.50, currency="USD")
        payout = await provider.fetch_payout_batch("BATCH_PP_SBX_001")
        return order, captured, refunded, payout

    order, captured, refunded, payout = _run(_exercise())
    assert order["id"] == "ORD_PP_SBX_001"
    assert order["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "29.00"}
    assert captured["status"] == "COMPLETED"
    assert refunded["status"] == "COMPLETED"
    assert refunded["amount"] == {"value": "14.50", "currency_code": "USD"}
    assert payout["batch_header"]["batch_status"] == "SUCCESS"
    assert all("api-m.sandbox.paypal.com" in u for u in seen_urls)


def test_razorpay_webhook_capture_settlement_partial_full_refund_and_idempotency(payment_sandbox_env):
    """Verify Razorpay HMAC validation, replay idempotency, capture!=settlement, and partial/full refund revocation."""
    client, db = payment_sandbox_env

    # 1. Invalid HMAC rejected with 401; missing provider headers rejected with 400
    bad_payload = json.dumps({"event": "payment.captured", "payload": {}}).encode("utf-8")
    r_unknown = client.post("/v1/webhooks/payment", content=bad_payload, headers={"content-type": "application/json"})
    assert r_unknown.status_code == 400

    r_bad_sig = client.post(
        "/v1/webhooks/payment",
        content=bad_payload,
        headers={"x-razorpay-signature": "invalid-signature", "content-type": "application/json"},
    )
    assert r_bad_sig.status_code == 401

    # 2. Signed payment.captured webhook -> provisions org + invoice + P2 reconciliation as CAPTURED_PENDING_SETTLEMENT
    capture_body = {
        "event": "payment.captured",
        "event_id": "evt_rzp_cap_001",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_rzp_001",
                    "order_id": "order_rzp_001",
                    "amount": 199900,
                    "currency": "INR",
                    "email": "rzp.client@sandbox.test",
                    "notes": {
                        "package_key": "seo_blog_copilot",
                        "company_name": "Sandbox SEO Co",
                    },
                }
            }
        },
    }
    raw_cap = json.dumps(capture_body).encode("utf-8")
    r_cap = client.post(
        "/v1/webhooks/payment",
        content=raw_cap,
        headers={"x-razorpay-signature": _sign_razorpay(raw_cap), "content-type": "application/json"},
    )
    assert r_cap.status_code == 200, r_cap.text
    cap_data = r_cap.json()
    assert cap_data["status"] == "processed"
    assert cap_data["settlement_classification"] == "CAPTURED_PENDING_SETTLEMENT"
    assert cap_data["provisioning"]["package_key"] == "seo_blog_copilot"
    org_id = cap_data["provisioning"]["org_id"]

    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="pay_rzp_001").one()
    assert inv.status == "paid"
    assert inv.metadata_json["settlement_status"] == "CAPTURED_PENDING_SETTLEMENT"
    assert inv.metadata_json["payout_settled"] is False

    recon = db.query(P2PaymentReconciliationRecord).filter_by(checkout_reference="pay_rzp_001").one()
    assert recon.verification_state == "ACTIVATION_COMPLETED"
    assert recon.metadata_json["settlement_status"] == "CAPTURED_PENDING_SETTLEMENT"
    assert recon.metadata_json["payout_settled"] is False

    # 3. Duplicate webhook replay returns duplicate and does NOT create second invoice/event
    r_dup = client.post(
        "/v1/webhooks/payment",
        content=raw_cap,
        headers={"x-razorpay-signature": _sign_razorpay(raw_cap), "content-type": "application/json"},
    )
    assert r_dup.status_code == 200
    assert r_dup.json()["status"] == "duplicate"
    assert db.query(InvoiceRecord).filter_by(provider_payment_id="pay_rzp_001").count() == 1
    assert db.query(WebhookEventRecord).filter_by(provider_event_id="evt_rzp_cap_001").count() == 1

    # 4. Separate settlement.processed webhook moves settlement_status -> SETTLED_TO_MERCHANT
    settlement_body = {
        "event": "settlement.processed",
        "event_id": "evt_rzp_setl_001",
        "payload": {
            "settlement": {
                "entity": {
                    "id": "setl_rzp_001",
                    "payment_id": "pay_rzp_001",
                    "amount": 195182,
                    "status": "processed",
                }
            }
        },
    }
    raw_setl = json.dumps(settlement_body).encode("utf-8")
    r_setl = client.post(
        "/v1/webhooks/payment",
        content=raw_setl,
        headers={"x-razorpay-signature": _sign_razorpay(raw_setl), "content-type": "application/json"},
    )
    assert r_setl.status_code == 200, r_setl.text
    assert r_setl.json()["settlement_classification"] == "SETTLED_TO_MERCHANT"

    db.expire_all()
    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="pay_rzp_001").one()
    recon = db.query(P2PaymentReconciliationRecord).filter_by(checkout_reference="pay_rzp_001").one()
    assert inv.metadata_json["settlement_status"] == "SETTLED_TO_MERCHANT"
    assert inv.metadata_json["payout_settled"] is True
    assert recon.metadata_json["settlement_status"] == "SETTLED_TO_MERCHANT"
    assert recon.metadata_json["payout_settled"] is True

    # 5. Partial refund (₹999.50 = 99950 paise of 199900) keeps paid tier
    partial_refund_body = {
        "event": "refund.processed",
        "event_id": "evt_rzp_rfnd_part_001",
        "payload": {
            "refund": {
                "entity": {
                    "id": "rfnd_rzp_part_001",
                    "payment_id": "pay_rzp_001",
                    "amount": 99950,
                    "status": "processed",
                }
            }
        },
    }
    raw_pr = json.dumps(partial_refund_body).encode("utf-8")
    r_pr = client.post(
        "/v1/webhooks/payment",
        content=raw_pr,
        headers={"x-razorpay-signature": _sign_razorpay(raw_pr), "content-type": "application/json"},
    )
    assert r_pr.status_code == 200, r_pr.text
    assert r_pr.json()["settlement_classification"] == "PARTIALLY_REFUNDED"
    db.expire_all()
    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="pay_rzp_001").one()
    org = db.get(OrganizationRecord, org_id)
    assert inv.status == "partially_refunded"
    assert org.tier == "modular_seo"

    # 6. Second partial refund (remaining 99950 paise -> cumulative 100%) revokes org + P2 reconciliation
    full_refund_body = {
        "event": "refund.processed",
        "event_id": "evt_rzp_rfnd_full_002",
        "payload": {
            "refund": {
                "entity": {
                    "id": "rfnd_rzp_full_002",
                    "payment_id": "pay_rzp_001",
                    "amount": 99950,
                    "status": "processed",
                }
            }
        },
    }
    raw_fr = json.dumps(full_refund_body).encode("utf-8")
    r_fr = client.post(
        "/v1/webhooks/payment",
        content=raw_fr,
        headers={"x-razorpay-signature": _sign_razorpay(raw_fr), "content-type": "application/json"},
    )
    assert r_fr.status_code == 200, r_fr.text
    assert r_fr.json()["settlement_classification"] == "REFUND_COMPLETED"
    db.expire_all()
    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="pay_rzp_001").one()
    org = db.get(OrganizationRecord, org_id)
    recon = db.query(P2PaymentReconciliationRecord).filter_by(checkout_reference="pay_rzp_001").one()
    assert inv.status == "refunded"
    assert org.tier == "free"
    assert org.metadata_json["entitled_capabilities"] == []
    assert recon.verification_state == "REFUNDED"


def test_paypal_webhook_signature_capture_settlement_and_major_unit_refund(
    payment_sandbox_env,
    monkeypatch: pytest.MonkeyPatch,
):
    """Verify PayPal verify-webhook-signature PASS/FAIL, capture!=payout, and major-unit USD refund math."""
    client, db = payment_sandbox_env
    verify_status = {"value": "FAILURE"}

    def pp_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "pp_tok_verify", "token_type": "Bearer"})
        if request.url.path == "/v1/notifications/verify-webhook-signature":
            return httpx.Response(200, json={"verification_status": verify_status["value"]})
        return httpx.Response(404)

    pp_provider = PayPalProvider(transport=httpx.MockTransport(pp_handler))
    monkeypatch.setattr(
        "app.api.v1.webhooks.get_payment_provider",
        lambda prov=None: pp_provider if prov == PaymentProvider.PAYPAL else RazorpayProvider(),
    )

    cap_event = {
        "id": "WH-PP-CAP-001",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource_type": "capture",
        "resource": {
            "id": "CAP_PP_001",
            "status": "COMPLETED",
            "amount": {"value": "29.00", "currency_code": "USD"},
            "custom_id": "seo_blog_copilot",
            "payer": {
                "email_address": "pp.buyer@sandbox.test",
                "name": {"given_name": "Priya", "surname": "Verma"},
            },
        },
    }
    raw_cap = json.dumps(cap_event).encode("utf-8")

    # Rejected signature -> 401
    r_fail = client.post("/v1/webhooks/payment", content=raw_cap, headers=_paypal_headers("TX-FAIL-1"))
    assert r_fail.status_code == 401

    # Accepted signature -> CAPTURED_PENDING_SETTLEMENT (payout_settled=False)
    verify_status["value"] = "SUCCESS"
    r_cap = client.post("/v1/webhooks/payment", content=raw_cap, headers=_paypal_headers("TX-CAP-1"))
    assert r_cap.status_code == 200, r_cap.text
    assert r_cap.json()["settlement_classification"] == "CAPTURED_PENDING_SETTLEMENT"
    org_id = r_cap.json()["provisioning"]["org_id"]

    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="CAP_PP_001").one()
    assert inv.amount == 2900.0
    assert inv.currency == "USD"
    assert inv.metadata_json["payout_settled"] is False

    # Separate merchant payout settlement webhook -> SETTLED_TO_MERCHANT
    payout_event = {
        "id": "WH-PP-PAYOUT-001",
        "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
        "resource_type": "payouts_item",
        "resource": {
            "payout_item_id": "PYI_001",
            "payout_item": {"sender_item_id": "CAP_PP_001"},
        },
    }
    r_payout = client.post(
        "/v1/webhooks/payment",
        content=json.dumps(payout_event).encode("utf-8"),
        headers=_paypal_headers("TX-PAYOUT-1"),
    )
    assert r_payout.status_code == 200, r_payout.text
    assert r_payout.json()["settlement_classification"] == "SETTLED_TO_MERCHANT"
    db.expire_all()
    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="CAP_PP_001").one()
    assert inv.metadata_json["payout_settled"] is True

    # PayPal partial major-unit refund ($14.50 USD -> 1450 cents out of 2900)
    partial_pp_refund = {
        "id": "WH-PP-RFND-001",
        "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "resource_type": "refund",
        "resource": {
            "id": "RFND_PP_001",
            "amount": {"value": "14.50", "currency_code": "USD"},
            "supplementary_data": {"related_ids": {"capture_id": "CAP_PP_001"}},
        },
    }
    r_pr = client.post(
        "/v1/webhooks/payment",
        content=json.dumps(partial_pp_refund).encode("utf-8"),
        headers=_paypal_headers("TX-RFND-1"),
    )
    assert r_pr.status_code == 200, r_pr.text
    assert r_pr.json()["settlement_classification"] == "PARTIALLY_REFUNDED"
    db.expire_all()
    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="CAP_PP_001").one()
    assert inv.status == "partially_refunded"
    assert inv.metadata_json["refunded_amount"] == 1450.0
    assert db.get(OrganizationRecord, org_id).tier == "modular_seo"

    # Second PayPal major-unit refund ($14.50 USD -> cumulative 2900/2900) -> refunded + revoked
    final_pp_refund = {
        "id": "WH-PP-RFND-002",
        "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "resource_type": "refund",
        "resource": {
            "id": "RFND_PP_002",
            "amount": {"value": "14.50", "currency_code": "USD"},
            "supplementary_data": {"related_ids": {"capture_id": "CAP_PP_001"}},
        },
    }
    r_fr = client.post(
        "/v1/webhooks/payment",
        content=json.dumps(final_pp_refund).encode("utf-8"),
        headers=_paypal_headers("TX-RFND-2"),
    )
    assert r_fr.status_code == 200, r_fr.text
    db.expire_all()
    inv = db.query(InvoiceRecord).filter_by(provider_payment_id="CAP_PP_001").one()
    org = db.get(OrganizationRecord, org_id)
    assert inv.status == "refunded"
    assert org.tier == "free"
    assert db.query(P2PaymentReconciliationRecord).filter_by(checkout_reference="CAP_PP_001").one().verification_state == "REFUNDED"


def test_subscription_renewal_payment_failure_and_cancellation_lifecycle(payment_sandbox_env):
    """Verify subscription renewal replenishment, invoice payment failure PAST_DUE handling, and cancellation."""
    client, db = payment_sandbox_env

    # Seed paid org + subscription + P3 customer profile + invoice
    org = OrganizationRecord(
        id="org_p31_sub",
        name="Renewal Agency",
        slug="renewal-agency",
        tier="modular_seo",
        lead_credits_limit=200,
        lead_credits_used=180,
        outreach_credits_limit=100,
        outreach_credits_used=90,
        metadata_json={"package_key": "seo_blog_copilot", "entitled_capabilities": ["seo_copilot"]},
    )
    db.add(org)
    db.add(
        P3CustomerAccountRecord(
            org_id="org_p31_sub",
            primary_contact_email="owner@renewal.test",
            primary_contact_name="Renewal Agency",
            lifecycle_state="ACTIVE",
        )
    )
    db.add(
        SubscriptionRecord(
            id="sub_rec_001",
            org_id="org_p31_sub",
            customer_id="cust_rzp_001",
            provider="razorpay",
            provider_subscription_id="sub_rzp_001",
            plan_id="seo_blog_copilot",
            status="active",
        )
    )
    db.add(
        InvoiceRecord(
            id="inv_rec_fail_001",
            org_id="org_p31_sub",
            customer_id="cust_rzp_001",
            provider="razorpay",
            provider_invoice_id="evt_init",
            provider_payment_id="pay_rzp_fail_001",
            amount=199900.0,
            currency="INR",
            status="pending",
            metadata_json={},
        )
    )
    db.commit()

    # 1. Renewal charged -> credits replenished to 0 used and P3 lifecycle updated ACTIVE
    renew_payload = {
        "event": "subscription.charged",
        "payload": {
            "subscription": {"entity": {"id": "sub_rzp_001", "status": "active"}},
            "payment": {"entity": {"id": "pay_rzp_renew_01", "amount": 199900, "currency": "INR"}},
        },
    }
    raw_ren = json.dumps(renew_payload).encode("utf-8")
    r_ren = client.post(
        "/v1/webhooks/payment",
        content=raw_ren,
        headers={"x-razorpay-signature": _sign_razorpay(raw_ren), "content-type": "application/json"},
    )
    assert r_ren.status_code == 200, r_ren.text
    assert r_ren.json()["p3_subscription_sync"]["event"]["subscription_state"] == "ACTIVE"
    db.expire_all()
    org = db.get(OrganizationRecord, "org_p31_sub")
    assert org.lead_credits_used == 0
    assert org.outreach_credits_used == 0

    # 2. Gateway invoice.payment_failed on subscription -> PAST_DUE summary updated
    fail_sub_payload = {
        "event": "invoice.payment_failed",
        "event_id": "evt_inv_fail_001",
        "payload": {
            "subscription": {"entity": {"id": "sub_rzp_001", "status": "pending"}},
        },
    }
    raw_sf = json.dumps(fail_sub_payload).encode("utf-8")
    r_sf = client.post(
        "/v1/webhooks/payment",
        content=raw_sf,
        headers={"x-razorpay-signature": _sign_razorpay(raw_sf), "content-type": "application/json"},
    )
    assert r_sf.status_code == 200, r_sf.text
    assert r_sf.json()["p3_subscription_sync"]["event"]["subscription_state"] == "PAST_DUE"
    db.expire_all()
    summary = get_subscription_reliability_summary(db, org_id="org_p31_sub")
    assert any(ev["subscription_state"] == "PAST_DUE" for ev in summary["renewal_history"])

    # 3. Direct payment.failed webhook on invoice -> invoice failed + PAYMENT_FAILED classification
    fail_pay_payload = {
        "event": "payment.failed",
        "event_id": "evt_pay_fail_001",
        "payload": {
            "payment": {"entity": {"id": "pay_rzp_fail_001", "amount": 199900, "currency": "INR"}},
        },
    }
    raw_pf = json.dumps(fail_pay_payload).encode("utf-8")
    r_pf = client.post(
        "/v1/webhooks/payment",
        content=raw_pf,
        headers={"x-razorpay-signature": _sign_razorpay(raw_pf), "content-type": "application/json"},
    )
    assert r_pf.status_code == 200, r_pf.text
    assert r_pf.json()["settlement_classification"] == "PAYMENT_FAILED"
    db.expire_all()
    assert db.get(InvoiceRecord, "inv_rec_fail_001").status == "failed"

    # 4. Subscription cancellation -> downgrades org to free, revokes capabilities, sets CANCELLED
    cancel_payload = {
        "event": "subscription.cancelled",
        "event_id": "evt_sub_cancel_001",
        "payload": {
            "subscription": {"entity": {"id": "sub_rzp_001", "status": "cancelled"}},
        },
    }
    raw_can = json.dumps(cancel_payload).encode("utf-8")
    r_can = client.post(
        "/v1/webhooks/payment",
        content=raw_can,
        headers={"x-razorpay-signature": _sign_razorpay(raw_can), "content-type": "application/json"},
    )
    assert r_can.status_code == 200, r_can.text
    assert r_can.json()["p3_subscription_sync"]["event"]["subscription_state"] == "CANCELLED"
    db.expire_all()
    org = db.get(OrganizationRecord, "org_p31_sub")
    sub = db.get(SubscriptionRecord, "sub_rec_001")
    assert org.tier == "free"
    assert org.metadata_json["entitled_capabilities"] == []
    assert sub.status == "cancelled"


def test_inspect_payment_provider_config_is_non_secret(monkeypatch: pytest.MonkeyPatch):
    """Ensure read-only payment config inspection accurately reports modes without leaking secrets."""
    secret_sentinel_rzp = "SUPER_SECRET_RZP_DO_NOT_LEAK_987"
    secret_sentinel_pp = "SUPER_SECRET_PP_DO_NOT_LEAK_654"
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_visible_id_only")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", secret_sentinel_rzp)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_secret_do_not_leak")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "pp_client_id_value")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", secret_sentinel_pp)
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-123")
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")

    cfg = inspect_payment_provider_config()
    serialized = json.dumps(cfg)
    assert cfg == {
        "razorpay": {
            "credentials_present": True,
            "webhook_secret_present": True,
            "mode": "sandbox_test",
        },
        "paypal": {
            "credentials_present": True,
            "webhook_id_present": True,
            "mode": "sandbox",
        },
    }
    assert secret_sentinel_rzp not in serialized
    assert secret_sentinel_pp not in serialized
    assert "rzp_test_visible_id_only" not in serialized
    assert "whsec_secret_do_not_leak" not in serialized

    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_12345")
    monkeypatch.setenv("PAYPAL_MODE", "live")
    live_cfg = inspect_payment_provider_config()
    assert live_cfg["razorpay"]["mode"] == "live"
    assert live_cfg["paypal"]["mode"] == "live"
