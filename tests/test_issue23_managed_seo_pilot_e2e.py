"""End-to-end operational tests for Issue #23:
₹4,999 Managed SEO & Content Pilot (14-Day) from public landing page -> checkout ->
verified payment provisioning -> structured intake -> 4 deliverables -> QA & 2-round revision limit ->
Owner HITL WordPress approval -> customer ACCEPTED delivery without manual DB edits.
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
from app.db.models import UserRecord
from app.main import app
from app.security.auth import create_access_token
from app.security.trust_chain import ensure_genesis_block
from app.services.p3_delivery_health import submit_delivery_quality_check, transition_delivery_quality_state

OWNER_KEY = "issue23-pilot-owner-key-32-chars-ok!"
RZP_SECRET = "rzp_whsec_issue23_pilot_32chars_ok!"


@pytest.fixture()
def pilot_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("OWNER_API_KEY", OWNER_KEY)
    monkeypatch.setenv("MANAGER_API_KEY", "issue23-pilot-mgr-key-32-chars-ok!!")
    monkeypatch.setenv("JWT_SECRET_KEY", "issue23-pilot-jwt-secret-32-chars!!")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", RZP_SECRET)
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_issue23")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_secret_issue23")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionLocal()
    ensure_genesis_block(db)

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


@patch("app.services.provisioning.get_email_dispatcher")
def test_managed_seo_pilot_full_customer_journey_without_manual_db_edits(mock_disp_fn, pilot_env):
    """Issue #23: Public page -> checkout -> Razorpay verified payment -> intake -> 4 deliverables ->
    revision cap (2 rounds) -> customer ACCEPTED completion."""
    mock_disp_fn.return_value = MagicMock()
    client, db = pilot_env

    # 1. Public landing page documents 14-day schedule, scope, exclusions, revision policy & legal links
    r_page = client.get("/services/managed_seo_content_pilot")
    assert r_page.status_code == 200
    html = r_page.text
    for required_text in (
        "₹4,999",
        "$59",
        "14-Day Human-Operated Pilot Schedule",
        "2 editorial revision rounds",
        "Exclusions:",
        "/legal/refund-policy",
        "/legal/tos",
        "/legal/privacy",
        "Owner HITL approval",
    ):
        assert required_text in html

    # 2. DirectPay checkout session links to exact pilot SKU
    r_sess = client.post(
        "/v1/pay/create-session",
        json={
            "package_key": "managed_seo_content_pilot",
            "customer_email": "founder@b2b-agency.in",
            "company_name": "B2B Growth Agency",
            "currency": "INR",
        },
    )
    assert r_sess.status_code in (200, 201), r_sess.text
    assert r_sess.json()["package_key"] == "managed_seo_content_pilot"
    assert float(r_sess.json()["amount"]) == 4999.0

    # 3. Verified Razorpay payment provisions tenant & initializes pilot onboarding automatically
    cap_payload = json.dumps(
        {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_pilot_e2e_01",
                        "email": "founder@b2b-agency.in",
                        "amount": 499900,
                        "currency": "INR",
                        "notes": {
                            "notes_package": "managed_seo_content_pilot",
                            "notes_company": "B2B Growth Agency",
                        },
                    }
                }
            },
        }
    ).encode("utf-8")
    sig = hmac.new(RZP_SECRET.encode("utf-8"), cap_payload, hashlib.sha256).hexdigest()
    r_wh = client.post(
        "/v1/webhooks/payment",
        content=cap_payload,
        headers={
            "content-type": "application/json",
            "x-razorpay-signature": sig,
            "x-razorpay-event-id": "evt_pilot_e2e_01",
        },
    )
    assert r_wh.status_code == 200, r_wh.text
    prov = r_wh.json()["provisioning"]
    assert prov["status"] == "provisioned"
    org_id = prov["org_id"]

    # Authenticate provisioned customer
    user = db.query(UserRecord).filter_by(email="founder@b2b-agency.in").first()
    assert user is not None
    tok = create_access_token(
        user_id=user.id, email=user.email, role=user.role, org_id=org_id, password_hash=user.password_hash
    )
    cust_hdr = {"Authorization": f"Bearer {tok}"}

    # 4. Customer submits structured pilot intake -> advances onboarding & seeds 4 canonical deliverables
    r_intake = client.post(
        "/v1/me/pilot/intake",
        headers=cust_hdr,
        json={
            "website_url": "https://b2b-agency.in",
            "target_audience": "SaaS & B2B founders in India",
            "target_geography": "India",
            "priority_services": ["Technical SEO Audit", "B2B Content Marketing"],
            "cms_platform": "wordpress",
            "cms_access_mode": "wordpress_draft",
            "approval_contact_email": "founder@b2b-agency.in",
            "brand_notes": "Authoritative, factual, zero fluff",
        },
    )
    assert r_intake.status_code == 200, r_intake.text
    intake_body = r_intake.json()
    assert intake_body["status"] == "INTAKE_RECORDED"
    assert intake_body["deliverables_seeded"] == 4
    assert intake_body["total_deliverables"] == 4
    assert intake_body["revision_limit"] == 2

    # Idempotent second intake submission does not duplicate deliverables
    r_intake_2 = client.post(
        "/v1/me/pilot/intake",
        headers=cust_hdr,
        json={
            "website_url": "https://b2b-agency.in",
            "target_audience": "SaaS & B2B founders in India",
            "target_geography": "India",
            "priority_services": ["Technical SEO Audit", "B2B Content Marketing"],
            "cms_platform": "wordpress",
            "cms_access_mode": "wordpress_draft",
            "approval_contact_email": "founder@b2b-agency.in",
        },
    )
    assert r_intake_2.status_code == 200
    assert r_intake_2.json()["deliverables_seeded"] == 0
    assert r_intake_2.json()["total_deliverables"] == 4

    # 5. Owner runs QA and delivers all 4 items; verify 2-round revision limit on item #1, then customer accepts all 4
    deliveries = intake_body["deliverables"]
    first_id = deliveries[0]["delivery_id"]

    for d in deliveries:
        did = d["delivery_id"]
        transition_delivery_quality_state(db, delivery_id=did, target_state="IN_PROGRESS", actor="owner")
        submit_delivery_quality_check(
            db,
            delivery_id=did,
            passed=True,
            checks=[{"check": "editorial_human_qa", "passed": True}],
            reviewer="owner",
            output_artifacts={"artifact_url": f"https://os.askforwrite.com/deliverables/{did}"},
        )
        transition_delivery_quality_state(db, delivery_id=did, target_state="DELIVERED", actor="owner")

    # Request 2 revisions on deliverable #1 (allowed), 3rd revision MUST fail (409)
    for round_num in (1, 2):
        r_rev = client.post(
            f"/v1/me/deliveries/{first_id}/respond",
            headers=cust_hdr,
            json={"action": "REVISION_REQUESTED", "note": f"Editorial tweak round {round_num}"},
        )
        assert r_rev.status_code == 200, r_rev.text
        submit_delivery_quality_check(
            db,
            delivery_id=first_id,
            passed=True,
            checks=[{"check": f"revision_{round_num}_qa", "passed": True}],
            reviewer="owner",
        )
        transition_delivery_quality_state(db, delivery_id=first_id, target_state="DELIVERED", actor="owner")

    r_rev_3 = client.post(
        f"/v1/me/deliveries/{first_id}/respond",
        headers=cust_hdr,
        json={"action": "REVISION_REQUESTED", "note": "Round 3 should exceed included cap"},
    )
    assert r_rev_3.status_code == 409
    assert "revision limit reached" in r_rev_3.text.lower()

    # Customer accepts all 4 deliverables
    for d in deliveries:
        r_acc = client.post(
            f"/v1/me/deliveries/{d['delivery_id']}/respond",
            headers=cust_hdr,
            json={"action": "ACCEPTED", "note": "Verified and accepted"},
        )
        assert r_acc.status_code == 200, r_acc.text

    # 6. GET /v1/me/pilot/status reflects completed 14-day pilot acceptance
    r_status = client.get("/v1/me/pilot/status", headers=cust_hdr)
    assert r_status.status_code == 200
    st = r_status.json()
    assert st["intake_completed"] is True
    assert st["deliverables_count"] == 4
    assert st["accepted_count"] == 4
    assert st["pilot_accepted_complete"] is True
    assert st["wordpress_hitl_required"] is True
