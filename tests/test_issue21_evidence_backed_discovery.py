"""Tests for Issue #21: Evidence-backed and suppression-aware SMB lead discovery & outreach."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.smb_search_source import _AUDIT_CACHE, audit_live_website_seo_geo, discover_smb_leads
from app.db.database import Base
from app.db.models import ApprovalRequest, LeadRecordRow, OrganizationRecord
from app.security.trust_chain import ensure_genesis_block
from app.services.outreach import dispatch_outreach, draft_outreach
from app.services.suppression import _SUPPRESSED_DOMAINS, _SUPPRESSED_EMAILS, add_db_suppression, add_to_suppression_list


@pytest.fixture()
def disc_db():
    _AUDIT_CACHE.clear()
    orig_domains = set(_SUPPRESSED_DOMAINS)
    orig_emails = set(_SUPPRESSED_EMAILS)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionLocal()
    ensure_genesis_block(db)
    try:
        yield db
    finally:
        _SUPPRESSED_DOMAINS.clear()
        _SUPPRESSED_DOMAINS.update(orig_domains)
        _SUPPRESSED_EMAILS.clear()
        _SUPPRESSED_EMAILS.update(orig_emails)
        _AUDIT_CACHE.clear()
        db.close()
        engine.dispose()


def test_production_discovery_never_falls_back_to_curated_fixtures_when_live_empty(monkeypatch: pytest.MonkeyPatch):
    """Issue #21: Production discovery returns [] rather than returning curated fixtures as live search results."""
    monkeypatch.setenv("APP_ENV", "production")
    with patch("app.agents.smb_search_source._search_serper_live", return_value=[]), \
         patch("app.agents.smb_search_source._search_google_places_live", return_value=[]), \
         patch("app.agents.smb_search_source._search_duckduckgo_live", return_value=[]):
        leads = discover_smb_leads(vertical="seo_blog_copilot", region="India", limit=5)
        assert leads == []


def test_production_discovery_requires_evidence_urls_timestamps_and_forbids_synthetic_emails(monkeypatch: pytest.MonkeyPatch):
    """Issue #21: Production live leads carry evidence_urls, observed_at, source_type='live_search',
    confidence_rationale, and NEVER synthesize contact@domain emails."""
    monkeypatch.setenv("APP_ENV", "production")
    live_hit = [
        {
            "company": "Acme Verified Logistics",
            "website": "https://acme-live-logistics.in",
            "domain": "acme-live-logistics.in",
            "industry": "Logistics",
            "geography": "India",
            "signals": ["hiring logistics ops manager"],
            "source": "serper_live",
            "evidence_urls": ["https://acme-live-logistics.in/careers"],
        }
    ]
    with patch("app.agents.smb_search_source._search_serper_live", return_value=live_hit), \
         patch("app.agents.smb_search_source.audit_live_website_seo_geo", return_value={
             "audit_status": "LIVE_VERIFIED",
             "extracted_emails": [],
             "is_contact_verified": False,
             "contact_verification_status": "UNVERIFIED_NO_PUBLIC_CONTACT",
             "seo_geo_gap_score": 45,
         }):
        leads = discover_smb_leads(vertical="field_force", region="India", limit=5)
        assert len(leads) == 1
        ld = leads[0]
        assert ld["source_type"] == "live_search"
        assert ld["is_curated_fixture"] is False
        assert ld["observed_at"]
        assert "https://acme-live-logistics.in" in ld["evidence_urls"]
        assert "https://acme-live-logistics.in/careers" in ld["evidence_urls"]
        assert ld["public_contact_channel"] is None
        assert ld["contact_verification_status"] == "UNVERIFIED_NO_PUBLIC_CONTACT"
        assert ld["contact_permission"] == "UNKNOWN"
        assert ld["outreach_eligible"] is False
        assert "source_type=live_search" in ld["confidence_rationale"]

    # Also confirm audit_live_website_seo_geo does not synthesize contact@ in production
    audit = audit_live_website_seo_geo("https://no-email-site.in", timeout=0.0)
    assert audit["extracted_emails"] == []
    assert audit["contact_verification_status"] == "UNVERIFIED_NO_PUBLIC_CONTACT"


def test_discovery_derives_do_not_contact_from_suppression_registry(disc_db, monkeypatch: pytest.MonkeyPatch):
    """Issue #21: Suppressed domain/email sets do_not_contact=True, status='DO_NOT_CONTACT', outreach_eligible=False."""
    monkeypatch.setenv("APP_ENV", "production")
    add_to_suppression_list("suppressed-buyer.in")

    live_hits = [
        {
            "company": "Opted Out Corp",
            "website": "https://suppressed-buyer.in",
            "domain": "suppressed-buyer.in",
            "signals": ["needs seo"],
            "public_contact_channel": "founder@suppressed-buyer.in",
            "is_contact_verified": True,
        }
    ]
    with patch("app.agents.smb_search_source._search_serper_live", return_value=live_hits), \
         patch("app.agents.smb_search_source.audit_live_website_seo_geo", return_value={"audit_status": "LIVE_VERIFIED", "extracted_emails": []}):
        leads = discover_smb_leads(vertical="seo_blog_copilot", limit=5)
        assert len(leads) == 1
        assert leads[0]["do_not_contact"] is True
        assert leads[0]["status"] == "DO_NOT_CONTACT"
        assert leads[0]["contact_permission"] == "SUPPRESSED"
        assert leads[0]["outreach_eligible"] is False


def test_outreach_blocks_synthetic_contact_in_prod_and_mid_flight_suppression_at_dispatch(disc_db, monkeypatch: pytest.MonkeyPatch):
    """Issue #21: Production draft_outreach rejects synthetic contact@domain; dispatch_outreach re-checks suppression."""
    org = OrganizationRecord(
        id="org-out-21",
        name="Outreach Test Org",
        slug="outreach-test-21",
        tier="growth",
        outreach_credits_limit=50,
        outreach_credits_used=0,
        is_active=True,
    )
    lead = LeadRecordRow(
        id="lead-21-synth",
        task_id="task-21-synth",
        org_id=org.id,
        domain="prospect-real.in",
        company="Prospect Real Pvt Ltd",
        website="https://prospect-real.in",
        industry="Retail",
        geography="India",
        observed_signals=["missing schema"],
        sources=[{"source": "serper_live"}],
        public_contact_channel="contact@prospect-real.in",
        recommended_next_step="owner_review",
        do_not_contact=False,
        status="DISCOVERED",
    )
    lead_verified = LeadRecordRow(
        id="lead-21-verified",
        task_id="task-21-verified",
        org_id=org.id,
        domain="verified-client.in",
        company="Verified Client LLP",
        website="https://verified-client.in",
        industry="B2B Services",
        geography="India",
        observed_signals=["missing llms.txt"],
        sources=[{"source": "serper_live"}],
        public_contact_channel="priya@verified-client.in",
        recommended_next_step="owner_review",
        do_not_contact=False,
        status="DISCOVERED",
    )
    disc_db.add_all([org, lead, lead_verified])
    disc_db.commit()

    # 1. Production blocks synthetic contact@domain at draft time
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValueError, match="guessed/synthetic"):
        draft_outreach(
            db=disc_db,
            lead_id=lead.id,
            org_id=org.id,
            recipient_email="contact@prospect-real.in",
            recipient_name="Team",
            custom_notes=None,
            channel="email",
            idempotency_key=f"idemp-{uuid.uuid4().hex}",
            correlation_id="corr-21-1",
            requested_by="manager",
        )

    # 2. Verified contact drafts cleanly, gets owner APPROVED, then opts out BEFORE dispatch -> dispatch MUST block!
    drafted = draft_outreach(
        db=disc_db,
        lead_id=lead_verified.id,
        org_id=org.id,
        recipient_email="priya@verified-client.in",
        recipient_name="Priya",
        custom_notes=None,
        channel="email",
        idempotency_key=f"idemp-{uuid.uuid4().hex}",
        correlation_id="corr-21-2",
        requested_by="manager",
    )
    appr = disc_db.get(ApprovalRequest, drafted["approval_id"])
    appr.status = "APPROVED"
    disc_db.commit()

    # Prospect opts out mid-flight after approval (persisted in DB suppression table)
    add_db_suppression(disc_db, "priya@verified-client.in", reason="unsubscribe_link_clicked")
    disc_db.commit()

    mock_disp = MagicMock()
    with pytest.raises(ValueError, match="suppressed"):
        dispatch_outreach(
            db=disc_db,
            outreach_id=str(drafted["outreach_id"]),
            correlation_id="corr-21-3",
            dispatched_by="owner",
            dispatcher=mock_disp,
        )
    mock_disp.send.assert_not_called()
