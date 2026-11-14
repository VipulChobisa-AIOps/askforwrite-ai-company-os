"""P8 Marketplace Ecosystem & Master Roadmap Scorecard test suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import migrations.versions.n4c9d0e1f2a3_add_p8_marketplace_ecosystem_tables as p8_migration
from app.db.database import Base, get_db
from app.db.models import P8MarketplaceListingRecord, P8TenantInstallRecord
from app.main import app

OWNER_KEY = "p8-marketplace-owner-key-32-chr!"
MANAGER_KEY = "p8-marketplace-mgr-key-32-chars!"
JWT_SECRET = "p8-marketplace-jwt-secret-32-ch!"


@pytest.fixture()
def p8_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Session]:
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


def _create_tenant(client: TestClient, email: str, company: str) -> dict[str, Any]:
    res = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "StrongPassword!123", "full_name": "Founder", "company_name": company},
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()
    return {"org_id": data["org_id"], "headers": {"Authorization": f"Bearer {data['access_token']}"}}


def test_p8_alembic_migration_upgrade_and_downgrade_parity() -> None:
    """Verify n4c9d0e1f2a3 creates all 5 P8 tables and explicit indexes cleanly."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn)
        op = Operations(ctx)
        orig_op = p8_migration.op
        p8_migration.op = op
        try:
            p8_migration.upgrade()
            conn.commit()
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            expected = {
                "p8_developer_profiles",
                "p8_marketplace_listings",
                "p8_tenant_installs",
                "p8_marketplace_reviews",
                "p8_revenue_share_ledger",
            }
            assert expected <= tables
            assert "ix_p8_dev_kyb_status" in {ix["name"] for ix in insp.get_indexes("p8_developer_profiles")}
            assert "ix_p8_list_dev_pub" in {ix["name"] for ix in insp.get_indexes("p8_marketplace_listings")}
            assert "ix_p8_inst_org_listing" in {ix["name"] for ix in insp.get_indexes("p8_tenant_installs")}
            assert "ix_p8_rev_listing_mod" in {ix["name"] for ix in insp.get_indexes("p8_marketplace_reviews")}
            assert "ix_p8_rev_dev_origin" in {ix["name"] for ix in insp.get_indexes("p8_revenue_share_ledger")}

            p8_migration.downgrade()
            conn.commit()
            remaining = set(inspect(conn).get_table_names())
            assert not (expected & remaining)
        finally:
            p8_migration.op = orig_op


def test_p8_kyb_signing_tamper_detection_and_secret_isolation(p8_client) -> None:
    """Verify developer KYB gate, SSRF/permission checks, ECDSA verification, tamper block, and secret masking."""
    client, db = p8_client
    owner_hdrs = {"x-api-key": OWNER_KEY}
    t1 = _create_tenant(client, "p8-t1@example.in", "Tenant One Mfg")
    t2 = _create_tenant(client, "p8-t2@example.in", "Tenant Two Dist")

    # Register developer -> starts PENDING, payout masked
    dev_res = client.post(
        "/v1/p8/marketplace/developers",
        headers=t1["headers"],
        json={
            "developer_name": "Kaveri Integrations",
            "contact_email": "dev@kaveri.in",
            "legal_entity_name": "Kaveri Softech Pvt Ltd",
            "tax_or_gst_id": "29AAACB1234F1Z5",
            "payout_account": "HDFC0001234567890",
        },
    )
    assert dev_res.status_code == 200, dev_res.text
    dev = dev_res.json()
    assert dev["kyb_status"] == "PENDING"
    assert dev["payout_account_masked"] == "••••7890"
    assert "HDFC0001234567890" not in str(dev)

    # Unverified PENDING developer blocked from listing
    blocked_list = client.post(
        "/v1/p8/marketplace/listings",
        headers=t1["headers"],
        json={
            "developer_id": dev["developer_id"],
            "listing_slug": "unverified-plugin",
            "name": "Unverified Plugin",
        },
    )
    assert blocked_list.status_code == 403

    # Owner approves developer KYB
    kyb_ok = client.post(
        f"/v1/p8/marketplace/developers/{dev['developer_id']}/kyb",
        headers=owner_hdrs,
        json={"kyb_status": "VERIFIED", "kyb_notes": "GSTIN verified cleanly"},
    )
    assert kyb_ok.status_code == 200
    assert kyb_ok.json()["kyb_status"] == "VERIFIED"

    # Reject wildcard permission, SSRF URL, and exaggerated marketing claims
    bad_perm = client.post(
        "/v1/p8/marketplace/listings",
        headers=t1["headers"],
        json={
            "developer_id": dev["developer_id"],
            "listing_slug": "bad-perm-pkg",
            "name": "Bad Perm Package",
            "requested_permissions": ["*"],
        },
    )
    assert bad_perm.status_code == 422

    bad_ssrf = client.post(
        "/v1/p8/marketplace/listings",
        headers=t1["headers"],
        json={
            "developer_id": dev["developer_id"],
            "listing_slug": "bad-ssrf-pkg",
            "name": "Bad SSRF Package",
            "endpoint_url": "http://127.0.0.1:8080/internal",
        },
    )
    assert bad_ssrf.status_code == 422

    bad_claim = client.post(
        "/v1/p8/marketplace/listings",
        headers=t1["headers"],
        json={
            "developer_id": dev["developer_id"],
            "listing_slug": "bad-claim-pkg",
            "name": "Guaranteed 10x ROI Plugin",
            "description": "Achieve +340% Revenue Growth overnight",
        },
    )
    assert bad_claim.status_code == 422

    # Valid listing submission gets SHA-256 + ECDSA signature in PENDING_REVIEW / DRAFT
    listing_res = client.post(
        "/v1/p8/marketplace/listings",
        headers=t1["headers"],
        json={
            "developer_id": dev["developer_id"],
            "listing_slug": "gst-tally-bridge",
            "name": "GST & Tally Sync Connector",
            "package_type": "CONNECTOR_ADAPTER",
            "description": "Reconciles tenant sales invoices with sandbox validation rules.",
            "requested_permissions": ["read_metrics", "stage_content"],
            "endpoint_url": "https://hooks.kaveri-partner.in/events",
            "price_inr_monthly": 2000,
            "commission_bps": 1500,
        },
    )
    assert listing_res.status_code == 200, listing_res.text
    listing = listing_res.json()
    lid = listing["listing_id"]
    assert listing["security_review_status"] == "PENDING_REVIEW"
    assert listing["published_status"] == "DRAFT"
    assert len(listing["manifest_sha256"]) == 64

    sig_res = client.get(f"/v1/p8/marketplace/listings/{lid}/verify-signature", headers=t1["headers"])
    assert sig_res.status_code == 200
    assert sig_res.json()["verified"] is True

    # Cannot publish without APPROVED security review; cannot install DRAFT
    bad_pub = client.post(
        f"/v1/p8/marketplace/listings/{lid}/review",
        headers=owner_hdrs,
        json={"security_review_status": "PENDING_REVIEW", "publish": True},
    )
    assert bad_pub.status_code == 403

    draft_install = client.post(
        "/v1/p8/marketplace/installs",
        headers=t1["headers"],
        json={"listing_id": lid},
    )
    assert draft_install.status_code == 403

    # Owner approves and publishes
    pub_res = client.post(
        f"/v1/p8/marketplace/listings/{lid}/review",
        headers=owner_hdrs,
        json={"security_review_status": "APPROVED", "publish": True, "review_notes": "Manifest scopes verified"},
    )
    assert pub_res.status_code == 200
    assert pub_res.json()["published_status"] == "PUBLISHED"

    # Tampering manifest_json breaks verification AND blocks installation
    row = db.get(P8MarketplaceListingRecord, lid)
    original_manifest = dict(row.manifest_json)
    row.manifest_json = {**original_manifest, "permissions": ["admin_root"]}
    db.commit()

    tamper_sig = client.get(f"/v1/p8/marketplace/listings/{lid}/verify-signature", headers=t1["headers"])
    assert tamper_sig.status_code == 200
    assert tamper_sig.json()["sha256_match"] is False
    assert tamper_sig.json()["verified"] is False

    tamper_install = client.post("/v1/p8/marketplace/installs", headers=t1["headers"], json={"listing_id": lid})
    assert tamper_install.status_code == 403

    # Restore clean manifest before verified tenant installation
    row.manifest_json = original_manifest
    db.commit()

    # Over-permissioned grant beyond manifest rejected
    over_perm = client.post(
        "/v1/p8/marketplace/installs",
        headers=t1["headers"],
        json={"listing_id": lid, "granted_permissions": ["read_metrics", "emit_webhook"]},
    )
    assert over_perm.status_code == 403

    # Clean install isolates secret into SHA-256 digest + masked preview only
    raw_secret = "partner-live-secret-token-4321"
    inst_res = client.post(
        "/v1/p8/marketplace/installs",
        headers=t1["headers"],
        json={
            "listing_id": lid,
            "granted_permissions": ["read_metrics"],
            "secrets_payload": {"partner_api_key": raw_secret},
            "config": {"sync_mode": "SANDBOX"},
        },
    )
    assert inst_res.status_code == 200, inst_res.text
    inst = inst_res.json()
    assert inst["secret_previews"]["partner_api_key"] == "••••4321"
    assert raw_secret not in str(inst)
    db_inst = db.get(P8TenantInstallRecord, inst["install_id"])
    assert raw_secret not in str(db_inst.secret_digests_json)

    # Cross-tenant isolation check: Tenant 2 cannot read Tenant 1 installs
    cross_read = client.get(f"/v1/p8/marketplace/installs?org_id={t1['org_id']}", headers=t2["headers"])
    assert cross_read.status_code == 403


def test_p8_verified_reviews_revenue_ledger_scorecard_agent_and_ui(p8_client) -> None:
    """Verify verified-installer reviews, moderation, revenue ledger separation, /v1/ops/roadmap-scorecard, agent, and UI."""
    client, _db = p8_client
    owner_hdrs = {"x-api-key": OWNER_KEY}
    t1 = _create_tenant(client, "p8-rev1@example.in", "Installer Co")
    t2 = _create_tenant(client, "p8-rev2@example.in", "NonInstaller Co")

    dev = client.post(
        "/v1/p8/marketplace/developers",
        headers=owner_hdrs,
        json={"developer_name": "Dev Studio", "contact_email": "studio@example.in", "legal_entity_name": "Studio LLP"},
    ).json()
    client.post(f"/v1/p8/marketplace/developers/{dev['developer_id']}/kyb", headers=owner_hdrs, json={"kyb_status": "VERIFIED"})

    listing = client.post(
        "/v1/p8/marketplace/listings",
        headers=owner_hdrs,
        json={
            "developer_id": dev["developer_id"],
            "listing_slug": "dispatch-alert-pack",
            "name": "Dispatch Alert Pack",
            "package_type": "WORKFLOW_PACK",
            "requested_permissions": ["read_metrics"],
            "commission_bps": 1500,
        },
    ).json()
    lid = listing["listing_id"]
    client.post(
        f"/v1/p8/marketplace/listings/{lid}/review",
        headers=owner_hdrs,
        json={"security_review_status": "APPROVED", "publish": True},
    )

    # Tenant 2 has NOT installed -> review blocked (403)
    unverified_rev = client.post(
        "/v1/p8/marketplace/reviews",
        headers=t2["headers"],
        json={"listing_id": lid, "rating": 1, "comment": "Competitor spam"},
    )
    assert unverified_rev.status_code == 403

    # Tenant 1 installs -> review permitted -> Owner moderates abusive review
    inst = client.post("/v1/p8/marketplace/installs", headers=t1["headers"], json={"listing_id": lid}).json()
    ok_rev = client.post(
        "/v1/p8/marketplace/reviews",
        headers=t1["headers"],
        json={"listing_id": lid, "rating": 5, "comment": "Works cleanly in sandbox verification."},
    )
    assert ok_rev.status_code == 200
    rid = ok_rev.json()["review_id"]

    mod_res = client.post(
        f"/v1/p8/marketplace/reviews/{rid}/moderate",
        headers=owner_hdrs,
        json={"abuse_flagged": True, "moderation_status": "REMOVED", "abuse_reason": "Test moderation removal"},
    )
    assert mod_res.status_code == 200
    assert mod_res.json()["moderation_status"] == "REMOVED"
    visible = client.get(f"/v1/p8/marketplace/reviews?listing_id={lid}", headers=t1["headers"]).json()
    assert visible["count"] == 0

    # Revenue share ledger separates SANDBOX from ACTUAL
    rev_res = client.post(
        "/v1/p8/marketplace/revenue-share",
        headers=owner_hdrs,
        json={"install_id": inst["install_id"], "gross_amount_inr": 2000.0, "evidence_status": "SANDBOX"},
    )
    assert rev_res.status_code == 200
    entry = rev_res.json()
    assert entry["platform_commission_inr"] == 300.0
    assert entry["developer_payout_inr"] == 1700.0
    assert entry["evidence_status"] == "SANDBOX"

    ledger = client.get("/v1/p8/marketplace/revenue-share", headers=owner_hdrs).json()
    assert ledger["sandbox_gross_inr"] == 2000.0
    assert ledger["actual_gross_inr"] == 0.0

    # Master Roadmap Scorecard preserves P3.1 blockers & BLOCKED cutover
    score_res = client.get("/v1/ops/roadmap-scorecard", headers=owner_hdrs)
    assert score_res.status_code == 200, score_res.text
    score = score_res.json()
    assert score["platform_architecture"] == "UNIFIED_SINGLE_OS"
    assert score["overall_release_readiness"] == "BLOCKED"
    assert score["production_cutover_approved"] is False
    assert len(score["p3_1_blockers"]) >= 1
    assert [p["phase"] for p in score["phases"]] == ["P0", "P1", "P2", "P3", "P3.1", "P4", "P5", "P6", "P7", "P8"]

    # Registered marketplace_curator_agent executes cleanly
    agent_res = client.post(
        "/v1/registry/agents/marketplace_curator_agent/execute",
        headers=owner_hdrs,
        json={"execution_mode": "SIMULATION", "input_payload": {}},
    )
    assert agent_res.status_code == 200, agent_res.text
    assert agent_res.json()["evidence"]["agent_id"] == "marketplace_curator_agent"

    # Dashboard P8 UI wiring check
    root = Path(__file__).resolve().parent.parent
    html_text = (root / "app" / "dashboard" / "index.html").read_text(encoding="utf-8")
    js_text = (root / "app" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
    assert "nav-p8-marketplace" in html_text
    assert "page-p8-marketplace" in html_text
    assert "p8LoadControlCentre" in js_text
