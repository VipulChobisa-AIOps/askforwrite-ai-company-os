"""Provider-shaped Razorpay recurring webhook idempotency & out-of-order tests (Issue #16)
and extended refund fail-closed / quarantine / cross-tenant tests (Issue #13).
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    AuditLog,
    InvoiceRecord,
    OrganizationRecord,
    SubscriptionRecord,
    WebhookEventRecord,
)
from app.main import app

RZP_SECRET = "rzp_whsec_issue16_recurring_32chars!"


@pytest.fixture()
def rzp_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", RZP_SECRET)
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_issue16")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_secret_issue16")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionLocal()

    org_a = OrganizationRecord(
        id="org-rec-a",
        name="Recurring Agency A",
        slug="recurring-agency-a",
        tier="growth",
        lead_credits_limit=300,
        lead_credits_used=240,
        outreach_credits_limit=150,
        outreach_credits_used=110,
        is_active=True,
        metadata_json={"package_key": "growth_all_in_one", "entitled_capabilities": ["seo_content_automation", "growth_suite"]},
    )
    org_b = OrganizationRecord(
        id="org-rec-b",
        name="Isolated Agency B",
        slug="isolated-agency-b",
        tier="growth",
        lead_credits_limit=300,
        lead_credits_used=50,
        outreach_credits_limit=150,
        outreach_credits_used=20,
        is_active=True,
        metadata_json={"package_key": "growth_all_in_one", "entitled_capabilities": ["seo_content_automation", "growth_suite"]},
    )
    sub_a = SubscriptionRecord(
        id="sub-local-a",
        org_id=org_a.id,
        customer_id="cust-a",
        plan_id="plan_afw_growth_inr",
        provider="razorpay",
        provider_subscription_id="sub_RzpRecurring001",
        status="active",
        metadata_json={"internal_sku": "growth_all_in_one"},
    )
    inv_a = InvoiceRecord(
        id="inv-rec-a",
        org_id=org_a.id,
        customer_id="cust-a",
        provider="razorpay",
        provider_invoice_id="inv_rzp_rec_a",
        provider_payment_id="pay_RzpRecBase001",
        amount=699900.0,
        currency="INR",
        status="paid",
        metadata_json={"settlement_status": "CAPTURED_PENDING_SETTLEMENT"},
    )
    inv_b = InvoiceRecord(
        id="inv-rec-b",
        org_id=org_b.id,
        customer_id="cust-b",
        provider="razorpay",
        provider_invoice_id="inv_rzp_rec_b",
        provider_payment_id="pay_RzpRecBaseB001",
        amount=699900.0,
        currency="INR",
        status="paid",
        metadata_json={"settlement_status": "CAPTURED_PENDING_SETTLEMENT"},
    )
    db.add_all([org_a, org_b, sub_a, inv_a, inv_b])
    db.commit()

    def _override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    try:
        yield client, db, org_a, org_b, sub_a, inv_a, inv_b
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def _post_rzp(client: TestClient, payload_dict: dict, *, event_id_header: str | None = None):
    raw = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(RZP_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    headers = {"content-type": "application/json", "x-razorpay-signature": sig}
    if event_id_header:
        headers["x-razorpay-event-id"] = event_id_header
    return client.post("/v1/webhooks/payment", content=raw, headers=headers)


def _charged_fixture(*, sub_id: str, payment_id: str, created_at: int, paid_count: int) -> dict:
    """Realistic sanitized Razorpay `subscription.charged` webhook containing both subscription and payment entities."""
    return {
        "entity": "event",
        "account_id": "acc_TestSanitized01",
        "event": "subscription.charged",
        "contains": ["subscription", "payment"],
        "created_at": created_at,
        "payload": {
            "subscription": {
                "entity": {
                    "id": sub_id,
                    "entity": "subscription",
                    "plan_id": "plan_afw_growth_inr",
                    "status": "active",
                    "paid_count": paid_count,
                    "current_start": created_at,
                    "current_end": created_at + 2592000,
                }
            },
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": 699900,
                    "currency": "INR",
                    "status": "captured",
                    "method": "upi",
                }
            },
        },
    }


def test_provider_shaped_multi_cycle_renewals_idempotency_and_audit_traceability(rzp_env):
    """Issue #16: Two distinct billing cycles process independently, redelivery is idempotent,
    missing event_id uses deterministic payment-scoped fallback, and audit retains both IDs."""
    client, db, org_a, _org_b, _sub_a, _inv_a, _inv_b = rzp_env

    # Cycle 1 WITHOUT x-razorpay-event-id header (tests deterministic fallback with payment_id)
    c1 = _charged_fixture(sub_id="sub_RzpRecurring001", payment_id="pay_CycleOne001", created_at=1790000001, paid_count=1)
    r1 = _post_rzp(client, c1)
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "processed"

    db.expire_all()
    org_after_c1 = db.get(OrganizationRecord, org_a.id)
    assert org_after_c1.lead_credits_used == 0
    assert org_after_c1.outreach_credits_used == 0

    # Simulate mid-cycle usage
    org_after_c1.lead_credits_used = 125
    org_after_c1.outreach_credits_used = 40
    db.commit()

    # Exact redelivery of Cycle 1 MUST be deduplicated and MUST NOT reset mid-cycle usage!
    r1_dup = _post_rzp(client, c1)
    assert r1_dup.status_code == 200
    assert r1_dup.json()["status"] == "duplicate"
    db.expire_all()
    assert db.get(OrganizationRecord, org_a.id).lead_credits_used == 125

    # Cycle 2 with new payment_id MUST get a distinct event_id and replenish credits once
    c2 = _charged_fixture(sub_id="sub_RzpRecurring001", payment_id="pay_CycleTwo002", created_at=1792592001, paid_count=2)
    r2 = _post_rzp(client, c2)
    assert r2.status_code == 200
    assert r2.json()["status"] == "processed"
    db.expire_all()
    assert db.get(OrganizationRecord, org_a.id).lead_credits_used == 0

    # Verify DB recorded exactly 2 distinct WebhookEventRecords + AuditLog retains subscription & payment IDs
    events = db.query(WebhookEventRecord).filter_by(provider="razorpay").all()
    assert len(events) == 2
    assert len({e.provider_event_id for e in events}) == 2
    assert any("pay_CycleOne001" in e.provider_event_id for e in events)
    assert any("pay_CycleTwo002" in e.provider_event_id for e in events)

    audits = db.query(AuditLog).filter_by(action="subscription.charged").all()
    assert len(audits) == 2
    payment_ids = {a.input_payload.get("payment_id") for a in audits}
    assert payment_ids == {"pay_CycleOne001", "pay_CycleTwo002"}


def test_out_of_order_charged_event_after_cancellation_does_not_reactivate(rzp_env):
    """Issue #16: A late-arriving `subscription.charged` after `subscription.cancelled` must NOT reactivate."""
    client, db, org_a, _org_b, sub_a, _inv_a, _inv_b = rzp_env

    # 1. Cancel subscription
    cancel_evt = {
        "event": "subscription.cancelled",
        "created_at": 1795000000,
        "payload": {"subscription": {"entity": {"id": sub_a.provider_subscription_id, "status": "cancelled"}}},
    }
    r_cancel = _post_rzp(client, cancel_evt, event_id_header="evt_rzp_cancel_terminal_1")
    assert r_cancel.status_code == 200
    db.expire_all()
    assert db.get(SubscriptionRecord, sub_a.id).status == "cancelled"
    assert db.get(OrganizationRecord, org_a.id).tier == "free"

    # 2. Out-of-order delayed renewal arrives AFTER cancellation -> must NOT reactivate
    stale_charged = _charged_fixture(
        sub_id=sub_a.provider_subscription_id,
        payment_id="pay_StaleDelayed999",
        created_at=1794999900,
        paid_count=3,
    )
    r_stale = _post_rzp(client, stale_charged, event_id_header="evt_rzp_stale_charged_1")
    assert r_stale.status_code == 200
    db.expire_all()
    assert db.get(SubscriptionRecord, sub_a.id).status == "cancelled"
    assert db.get(OrganizationRecord, org_a.id).tier == "free"


def test_issue13_refund_quarantine_failed_state_malformed_currency_mismatch_and_cross_tenant(rzp_env):
    """Issue #13: Failed/pending refunds, currency mismatches, malformed amounts, and unmatched invoices
    fail closed without revoking entitlements, and full refund of Org A never touches Org B."""
    client, db, org_a, org_b, _sub_a, inv_a, inv_b = rzp_env

    # 1. Failed refund state -> REFUND_NOT_COMPLETED, access preserved
    r_failed = _post_rzp(
        client,
        {"event": "refund.failed", "payload": {"refund": {"entity": {"id": "rfnd_fail_1", "payment_id": inv_a.provider_payment_id, "amount": 699900, "status": "failed", "currency": "INR"}}}},
        event_id_header="evt_rfnd_failed_1",
    )
    assert r_failed.status_code == 200
    assert r_failed.json()["settlement_classification"] == "REFUND_NOT_COMPLETED"
    db.expire_all()
    assert db.get(OrganizationRecord, org_a.id).tier == "growth"

    # 2. Currency mismatch (USD refund against INR invoice) -> QUARANTINED, access preserved
    r_curr = _post_rzp(
        client,
        {"event": "refund.processed", "payload": {"refund": {"entity": {"id": "rfnd_curr_1", "payment_id": inv_a.provider_payment_id, "amount": 699900, "status": "processed", "currency": "USD"}}}},
        event_id_header="evt_rfnd_curr_mismatch_1",
    )
    assert r_curr.status_code == 200
    assert r_curr.json()["settlement_classification"] == "REFUND_CURRENCY_MISMATCH_QUARANTINED"
    db.expire_all()
    assert db.get(OrganizationRecord, org_a.id).tier == "growth"

    # 3. Malformed non-numeric refund amount -> REFUND_PENDING_VERIFICATION, access preserved
    r_mal = _post_rzp(
        client,
        {"event": "refund.processed", "payload": {"refund": {"entity": {"id": "rfnd_mal_1", "payment_id": inv_a.provider_payment_id, "amount": "not-a-number", "status": "processed", "currency": "INR"}}}},
        event_id_header="evt_rfnd_malformed_1",
    )
    assert r_mal.status_code == 200
    assert r_mal.json()["settlement_classification"] == "REFUND_PENDING_VERIFICATION"
    db.expire_all()
    assert db.get(OrganizationRecord, org_a.id).tier == "growth"

    # 4. Unmatched invoice -> REFUND_UNMATCHED_INVOICE, neither org touched
    r_unm = _post_rzp(
        client,
        {"event": "refund.processed", "payload": {"refund": {"entity": {"id": "rfnd_unm_1", "payment_id": "pay_DoesNotExist999", "amount": 699900, "status": "processed", "currency": "INR"}}}},
        event_id_header="evt_rfnd_unmatched_1",
    )
    assert r_unm.status_code == 200
    assert r_unm.json()["settlement_classification"] == "REFUND_UNMATCHED_INVOICE"

    # 5. Verified full refund on Org A revokes ONLY Org A — Org B remains completely untouched
    r_full = _post_rzp(
        client,
        {"event": "refund.processed", "payload": {"refund": {"entity": {"id": "rfnd_full_a", "payment_id": inv_a.provider_payment_id, "amount": 699900, "status": "processed", "currency": "INR"}}}},
        event_id_header="evt_rfnd_full_a",
    )
    assert r_full.status_code == 200
    db.expire_all()
    assert db.get(OrganizationRecord, org_a.id).tier == "free"
    assert db.get(OrganizationRecord, org_b.id).tier == "growth"
    assert db.get(InvoiceRecord, inv_b.id).status == "paid"
