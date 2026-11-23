"""PostgreSQL release verification tests (Issue #18) and dependency vulnerability gate tests (Issue #19).

When DATABASE_URL points to PostgreSQL (as in CI's `postgres-verification` job),
these tests run directly against PostgreSQL 16 after `alembic upgrade head`.
Locally without PostgreSQL, they fall back to SQLite so unit suites remain fast.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import OrganizationRecord, SeoDraftRecord, WebhookEventRecord
from scripts.check_dependency_vulns import evaluate_audit_payload


@pytest.fixture()
def db_session():
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url.startswith("postgres"):
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
        elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+psycopg://"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
        engine = create_engine(db_url)
    else:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionLocal()
    try:
        yield db, engine
    finally:
        db.close()
        engine.dispose()


def test_database_json_uniqueness_and_transaction_rollback(db_session):
    """Issue #18: Verify JSON round-trip, webhook deduplication unique constraint, and rollback safety."""
    db, engine = db_session
    suffix = uuid.uuid4().hex[:8]

    # 1. Verify Alembic head if running on migrated PostgreSQL
    if engine.dialect.name == "postgresql":
        rev = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert rev == "p6e1f2a3b4c5"

    # 2. JSON metadata round-trip on OrganizationRecord & SeoDraftRecord
    org = OrganizationRecord(
        id=f"org-pg-{suffix}",
        name=f"PG Verify Org {suffix}",
        slug=f"pg-verify-{suffix}",
        tier="growth",
        lead_credits_limit=300,
        lead_credits_used=10,
        metadata_json={"package_key": "growth_all_in_one", "nested": {"flags": ["a", "b"]}},
    )
    draft = SeoDraftRecord(
        id=f"draft-pg-{suffix}",
        task_id=f"task-pg-{suffix}",
        org_id=org.id,
        target_network="askforwrite.in",
        keywords=["postgres", "alembic"],
        content="# PG Verification\nBody",
        status="DRAFT",
        publish_metadata={"verified": False, "attempt": 1},
    )
    db.add_all([org, draft])
    db.commit()

    db.expire_all()
    loaded_org = db.get(OrganizationRecord, org.id)
    loaded_draft = db.get(SeoDraftRecord, draft.id)
    assert loaded_org is not None
    assert loaded_org.metadata_json["nested"]["flags"] == ["a", "b"]
    assert loaded_draft is not None
    assert loaded_draft.org_id == org.id
    assert loaded_draft.publish_metadata["attempt"] == 1

    # 3. Webhook deduplication unique constraint enforcement + clean rollback
    ev1 = WebhookEventRecord(
        provider="razorpay",
        provider_event_id=f"evt_pg_uniq_{suffix}",
        event_type="payment.captured",
        raw_event_type="payment.captured",
        resource_id=f"pay_{suffix}",
        resource_type="payment",
        payload={"amount": 499900},
        processed=True,
    )
    db.add(ev1)
    db.commit()

    ev_dup = WebhookEventRecord(
        provider="razorpay",
        provider_event_id=f"evt_pg_uniq_{suffix}",
        event_type="payment.captured",
        raw_event_type="payment.captured",
        resource_id=f"pay_{suffix}",
        resource_type="payment",
        payload={"amount": 499900},
        processed=False,
    )
    db.add(ev_dup)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # 4. Atomic credit update via SQL expression
    db.execute(
        text("UPDATE organizations SET lead_credits_used = lead_credits_used + 5 WHERE id = :oid"),
        {"oid": org.id},
    )
    db.commit()
    db.expire_all()
    assert db.get(OrganizationRecord, org.id).lead_credits_used == 15

    # Clean up test rows cleanly
    db.delete(ev1)
    db.delete(loaded_draft)
    db.delete(loaded_org)
    db.commit()


def test_issue19_dependency_gate_fails_unwaived_and_expired_waivers(tmp_path: Path):
    """Issue #19: Known vulnerability fails unless covered by an active, unexpired waiver."""
    waiver_file = tmp_path / "waivers.json"
    waiver_file.write_text(
        json.dumps(
            {
                "waivers": [
                    {
                        "package": "pytest",
                        "vuln_ids": ["PYSEC-2026-1845"],
                        "owner": "VipulChobisa-AIOps",
                        "rationale": "Dev only",
                        "compensating_control": "Excluded from Dockerfile",
                        "expires_on": "2026-12-31",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    # 1. Unwaived vulnerability MUST fail
    unwaived_payload = {
        "dependencies": [
            {
                "name": "cryptography",
                "version": "44.0.3",
                "vulns": [{"id": "PYSEC-2026-2141", "aliases": ["CVE-2026-26007"], "fix_versions": ["46.0.5"]}],
            }
        ]
    }
    res_fail = evaluate_audit_payload(unwaived_payload, waiver_file, today=date(2026, 11, 23))
    assert res_fail["passed"] is False
    assert res_fail["unwaived_count"] == 1

    # 2. Active valid waiver MUST pass before expiry
    waived_payload = {
        "dependencies": [
            {
                "name": "pytest",
                "version": "8.4.2",
                "vulns": [{"id": "PYSEC-2026-1845", "aliases": [], "fix_versions": ["9.0.3"]}],
            }
        ]
    }
    res_pass = evaluate_audit_payload(waived_payload, waiver_file, today=date(2026, 11, 23))
    assert res_pass["passed"] is True
    assert res_pass["waived_count"] == 1

    # 3. Same waiver after expiry date MUST fail automatically
    res_expired = evaluate_audit_payload(waived_payload, waiver_file, today=date(2027, 1, 1))
    assert res_expired["passed"] is False
    assert len(res_expired["waiver_errors"]) == 1
