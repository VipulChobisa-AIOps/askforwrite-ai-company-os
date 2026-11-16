"""Adversarial P8 marketplace security hardening tests."""

from __future__ import annotations

from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    OrganizationRecord,
    P8DeveloperProfileRecord,
    P8MarketplaceListingRecord,
)
from app.main import app
from app.services.p8_marketplace import (
    list_developers,
    register_developer_profile,
)

OWNER_KEY = "p8-sec-owner-key-32-characters!!"
MANAGER_KEY = "p8-sec-manager-key-32-chars!!!!!"
JWT_SECRET = "p8-sec-jwt-secret-32-characters!"


@pytest.fixture()
def p8_sec_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Session]:
    monkeypatch.setenv("OWNER_API_KEY", OWNER_KEY)
    monkeypatch.setenv("MANAGER_API_KEY", MANAGER_KEY)
    monkeypatch.setenv("JWT_SECRET_KEY", JWT_SECRET)

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    db = TestingSessionLocal()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client, db
    finally:
        app.dependency_overrides.clear()
        db.close()


def _signup_tenant(client: TestClient, email: str, company: str) -> dict[str, Any]:
    res = client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "StrongPassword!123", "full_name": "Founder", "company_name": company},
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()
    return {"org_id": data["org_id"], "headers": {"Authorization": f"Bearer {data['access_token']}"}}


def _setup_published_listing(client: TestClient, t1: dict[str, Any], owner_hdrs: dict[str, str], slug: str) -> tuple[str, str]:
    dev_res = client.post(
        "/v1/p8/marketplace/developers",
        headers=t1["headers"],
        json={
            "developer_name": "Kaveri Integrations",
            "contact_email": "dev@kaveri.example.in",
            "legal_entity_name": "Kaveri Pvt Ltd",
            "tax_or_gst_id": "27AABCK1234F1Z5",
            "payout_account": "HDFC000123456789",
        },
    )
    assert dev_res.status_code == 200, dev_res.text
    dev_id = dev_res.json()["developer_id"]
    kyb_res = client.post(
        f"/v1/p8/marketplace/developers/{dev_id}/kyb",
        headers=owner_hdrs,
        json={"kyb_status": "VERIFIED", "kyb_notes": "Secret KYB verification memo"},
    )
    assert kyb_res.status_code == 200, kyb_res.text

    lst_res = client.post(
        "/v1/p8/marketplace/listings",
        headers=t1["headers"],
        json={
            "developer_id": dev_id,
            "listing_slug": slug,
            "name": "Ledger Sync Plugin",
            "package_type": "AGENT_PLUGIN",
            "description": "Reconciles tenant ledger events safely in sandbox.",
            "requested_permissions": ["read_metrics"],
            "endpoint_url": "https://api.kaveri.example.in/hooks",
        },
    )
    assert lst_res.status_code == 200, lst_res.text
    lid = lst_res.json()["listing_id"]

    pub_res = client.post(
        f"/v1/p8/marketplace/listings/{lid}/review",
        headers=owner_hdrs,
        json={"security_review_status": "APPROVED", "publish": True, "review_notes": "Internal security team check"},
    )
    assert pub_res.status_code == 200, pub_res.text
    return dev_id, lid


def test_p8_cross_tenant_developer_ownership_visibility_and_pii_redaction(p8_sec_client) -> None:
    """Verify developer ownership checks, inactive org guard, draft hiding, and PII/review redaction."""
    client, db = p8_sec_client
    owner_hdrs = {"x-api-key": OWNER_KEY}
    mgr_hdrs = {"x-api-key": MANAGER_KEY}
    t1 = _signup_tenant(client, "p8sec-t1@example.in", "Tenant One Co")
    t2 = _signup_tenant(client, "p8sec-t2@example.in", "Tenant Two Co")

    # Service-layer developer registration checks missing / inactive org
    with pytest.raises(ValueError, match="not found"):
        register_developer_profile(
            db,
            org_id="nonexistent-org-id",
            developer_name="Ghost Dev",
            contact_email="g@example.in",
            legal_entity_name="Ghost Co",
        )

    dev_res = client.post(
        "/v1/p8/marketplace/developers",
        headers=t1["headers"],
        json={
            "developer_name": "T1 Studio",
            "contact_email": "secret-founder@t1.example.in",
            "legal_entity_name": "T1 Studio LLP",
            "tax_or_gst_id": "29AABCT9999K1Z2",
            "payout_account": "ICIC00099887766",
        },
    )
    assert dev_res.status_code == 200
    dev_id = dev_res.json()["developer_id"]
    client.post(f"/v1/p8/marketplace/developers/{dev_id}/kyb", headers=owner_hdrs, json={"kyb_status": "VERIFIED"})

    # Cross-tenant listing creation using Tenant 1's developer_id blocked with 403
    forged_create = client.post(
        "/v1/p8/marketplace/listings",
        headers=t2["headers"],
        json={"developer_id": dev_id, "listing_slug": "hijacked-dev-pkg", "name": "Hijacked Package"},
    )
    assert forged_create.status_code == 403

    # Tenant 1 creates a DRAFT listing
    draft_res = client.post(
        "/v1/p8/marketplace/listings",
        headers=t1["headers"],
        json={"developer_id": dev_id, "listing_slug": "t1-secret-draft", "name": "T1 Secret Draft"},
    )
    assert draft_res.status_code == 200
    draft_id = draft_res.json()["listing_id"]

    # Tenant 2 cannot see Tenant 1's DRAFT via default GET, ?published_only=false, overview, or verify-signature
    assert client.get("/v1/p8/marketplace/listings", headers=t2["headers"]).json()["count"] == 0
    t2_all = client.get("/v1/p8/marketplace/listings?published_only=false", headers=t2["headers"]).json()
    assert t2_all["count"] == 0
    t2_overview = client.get("/v1/p8/marketplace/overview", headers=t2["headers"]).json()
    assert all(l["listing_id"] != draft_id for l in t2_overview["listings"])
    assert t2_overview["developers"] == []
    assert client.get(f"/v1/p8/marketplace/listings/{draft_id}/verify-signature", headers=t2["headers"]).status_code == 403

    # Approve and publish; Tenant 2 now sees listing with private review_notes/signature hex redacted
    client.post(
        f"/v1/p8/marketplace/listings/{draft_id}/review",
        headers=owner_hdrs,
        json={"security_review_status": "APPROVED", "publish": True, "review_notes": "Private pentest note"},
    )
    t2_pub = client.get("/v1/p8/marketplace/listings", headers=t2["headers"]).json()["listings"]
    assert len(t2_pub) == 1
    assert t2_pub[0]["is_signed"] is True
    assert t2_pub[0]["ecdsa_signature_hex"] is None
    assert t2_pub[0]["review_notes"] is None
    assert t2_pub[0]["approved_by"] is None

    # Non-operator developer listing redacts PII when called across orgs or scoped
    t2_view_devs = list_developers(db, org_id=t1["org_id"], viewer_org_id=t2["org_id"], is_platform_operator=False)
    assert len(t2_view_devs) == 1
    assert t2_view_devs[0]["tax_or_gst_id"] is None
    assert t2_view_devs[0]["payout_account_masked"] is None
    assert "secret-founder" not in (t2_view_devs[0]["contact_email"] or "")

    # Inactive organization check on developer registration
    org2 = db.get(OrganizationRecord, t2["org_id"])
    org2.is_active = False
    db.commit()
    with pytest.raises(PermissionError, match="inactive"):
        register_developer_profile(
            db,
            org_id=t2["org_id"],
            developer_name="Suspended Org Dev",
            contact_email="s@example.in",
            legal_entity_name="Suspended Co",
        )

    # Scorecard access: tenant forbidden, platform manager and owner allowed
    assert client.get("/v1/ops/roadmap-scorecard", headers=t1["headers"]).status_code == 403
    assert client.get("/v1/ops/roadmap-scorecard", headers=mgr_hdrs).status_code == 200
    assert client.get("/v1/ops/roadmap-scorecard", headers=owner_hdrs).status_code == 200


def test_p8_signature_key_pinning_rereview_and_kyb_revocation(p8_sec_client) -> None:
    """Verify node-pinned key check, canonical match, KYB suspend block, and PENDING_REVIEW demotion."""
    client, db = p8_sec_client
    owner_hdrs = {"x-api-key": OWNER_KEY}
    t1 = _signup_tenant(client, "p8sig-t1@example.in", "Sig Owner Co")
    t2 = _signup_tenant(client, "p8sig-t2@example.in", "Sig Installer Co")
    dev_id, lid = _setup_published_listing(client, t1, owner_hdrs, "pin-test-pkg")

    # Attacker swaps signing_public_key_pem + ecdsa_signature_hex with rogue keypair
    row = db.get(P8MarketplaceListingRecord, lid)
    orig_pem = row.signing_public_key_pem
    orig_sig = row.ecdsa_signature_hex
    rogue_priv = ec.generate_private_key(ec.SECP256R1())
    rogue_pub = rogue_priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    row.signing_public_key_pem = rogue_pub
    row.ecdsa_signature_hex = rogue_priv.sign(
        row.manifest_sha256.encode("utf-8"), ec.ECDSA(hashes.SHA256())
    ).hex()
    db.commit()

    sig_check = client.get(f"/v1/p8/marketplace/listings/{lid}/verify-signature", headers=t1["headers"]).json()
    assert sig_check["public_key_pinned"] is False
    assert sig_check["verified"] is False
    assert client.post("/v1/p8/marketplace/installs", headers=t2["headers"], json={"listing_id": lid}).status_code == 403

    # Restore keys, then drift DB name without changing manifest_json
    row.signing_public_key_pem = orig_pem
    row.ecdsa_signature_hex = orig_sig
    orig_name = row.name
    row.name = "Mutated Display Name"
    db.commit()
    drift_check = client.get(f"/v1/p8/marketplace/listings/{lid}/verify-signature", headers=t1["headers"]).json()
    assert drift_check["manifest_canonical_match"] is False
    assert drift_check["verified"] is False
    row.name = orig_name
    db.commit()

    # Re-review to PENDING_REVIEW demotes published_status back to DRAFT and clears approved_by
    demote = client.post(
        f"/v1/p8/marketplace/listings/{lid}/review",
        headers=owner_hdrs,
        json={"security_review_status": "PENDING_REVIEW", "publish": False},
    )
    assert demote.status_code == 200
    assert demote.json()["published_status"] == "DRAFT"
    assert demote.json()["approved_by"] is None
    assert client.post("/v1/p8/marketplace/installs", headers=t2["headers"], json={"listing_id": lid}).status_code == 403

    # Re-approve, then suspend developer KYB -> install blocked
    assert (
        client.post(
            f"/v1/p8/marketplace/listings/{lid}/review",
            headers=owner_hdrs,
            json={"security_review_status": "APPROVED", "publish": True},
        ).status_code
        == 200
    )
    client.post(
        f"/v1/p8/marketplace/developers/{dev_id}/kyb",
        headers=owner_hdrs,
        json={"kyb_status": "SUSPENDED", "kyb_notes": "KYB expired"},
    )
    dev_row = db.get(P8DeveloperProfileRecord, dev_id)
    assert dev_row.kyb_status == "SUSPENDED"
    assert client.post("/v1/p8/marketplace/installs", headers=t2["headers"], json={"listing_id": lid}).status_code == 403


def test_p8_reviews_hardening_install_revoke_and_redaction(p8_sec_client) -> None:
    """Verify GTM safety on reviews, 1-review-per-install, install revocation, and review redaction."""
    client, _db = p8_sec_client
    owner_hdrs = {"x-api-key": OWNER_KEY}
    t1 = _signup_tenant(client, "p8rev-t1@example.in", "Dev Publisher Co")
    t2 = _signup_tenant(client, "p8rev-t2@example.in", "Installer Tenant Co")
    t3 = _signup_tenant(client, "p8rev-t3@example.in", "Observer Tenant Co")
    _dev_id, lid = _setup_published_listing(client, t1, owner_hdrs, "review-hardening-pkg")

    inst_res = client.post(
        "/v1/p8/marketplace/installs",
        headers=t2["headers"],
        json={"listing_id": lid, "secrets_payload": {"webhook_token": "tok-secret-9999"}},
    )
    assert inst_res.status_code == 200
    install_id = inst_res.json()["install_id"]

    # Duplicate active install rejected with 409
    assert client.post("/v1/p8/marketplace/installs", headers=t2["headers"], json={"listing_id": lid}).status_code == 409

    # Unsafe fabricated claim in review rejected with 422
    bad_rev = client.post(
        "/v1/p8/marketplace/reviews",
        headers=t2["headers"],
        json={"listing_id": lid, "rating": 5, "comment": "Delivers 10x ROI with guaranteed inclusion and 100% refund!"},
    )
    assert bad_rev.status_code == 422

    # Valid review succeeds once; second review for same install rejected with 409
    ok_rev = client.post(
        "/v1/p8/marketplace/reviews",
        headers=t2["headers"],
        json={"listing_id": lid, "rating": 5, "comment": "Verified clean sandbox execution."},
    )
    assert ok_rev.status_code == 200
    rid = ok_rev.json()["review_id"]
    assert (
        client.post(
            "/v1/p8/marketplace/reviews",
            headers=t2["headers"],
            json={"listing_id": lid, "rating": 4, "comment": "Attempting duplicate review"},
        ).status_code
        == 409
    )

    # Moderation flag internal reason hidden from unrelated Tenant 3
    client.post(
        f"/v1/p8/marketplace/reviews/{rid}/moderate",
        headers=owner_hdrs,
        json={"abuse_flagged": True, "moderation_status": "FLAGGED_UNDER_REVIEW", "abuse_reason": "Internal ops note"},
    )
    t3_reviews = client.get(f"/v1/p8/marketplace/reviews?listing_id={lid}", headers=t3["headers"]).json()["reviews"]
    assert len(t3_reviews) == 1
    assert t3_reviews[0]["abuse_reason"] is None
    assert t3_reviews[0]["abuse_flagged"] is False
    assert t3_reviews[0]["created_by"] is None
    assert t3_reviews[0]["org_id"] is None

    # Cross-tenant revoke blocked; owner revoke clears secrets and blocks revenue-share on revoked install
    assert client.post(f"/v1/p8/marketplace/installs/{install_id}/revoke", headers=t3["headers"]).status_code == 403
    revoked = client.post(f"/v1/p8/marketplace/installs/{install_id}/revoke", headers=t2["headers"])
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "REVOKED"
    assert revoked.json()["configured_secret_keys"] == []
    assert (
        client.post(
            "/v1/p8/marketplace/revenue-share",
            headers=owner_hdrs,
            json={"install_id": install_id, "gross_amount_inr": 1000.0},
        ).status_code
        == 403
    )
