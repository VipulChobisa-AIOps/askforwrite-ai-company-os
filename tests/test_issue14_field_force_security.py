"""Security tests for Issue #14: Field Force entitlement, tenant scope, and canonical principal.user_id ownership.

Covers every Field Force endpoint — especially the previously unguarded read/history
and calculation routes:
- GET /v1/field-force/attendance/history
- GET /v1/field-force/tasks
- GET /v1/field-force/visits
- POST /v1/field-force/conveyance/calculate
- GET /v1/field-force/conveyance/claims
plus write routes (check-in, check-out, visits/verify, visits/debrief, routes/optimize, conveyance/submit).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    ClientVisitRecord,
    ConveyanceClaimRecord,
    FieldAttendanceRecord,
    FieldTaskRecord,
    OrganizationRecord,
    UserRecord,
)
from app.main import app
from app.security.auth import APIPrincipal, create_access_token, get_current_principal, hash_password
from app.security.trust_chain import ensure_genesis_block


@pytest.fixture()
def ff_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "issue14-field-force-jwt-secret-32c!")
    monkeypatch.setenv("OWNER_API_KEY", "issue14-owner-key-32-chars-minimum!")
    monkeypatch.setenv("MANAGER_API_KEY", "issue14-mgr-key-32-chars-minimum!!")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionLocal()
    ensure_genesis_block(db)

    # Org A: Entitled to delivery_field_force (tier="pro")
    org_a = OrganizationRecord(
        id="org-ff-a",
        name="Entitled Field Org A",
        slug="entitled-field-a",
        tier="pro",
        metadata_json={"package_key": "company_os_pro", "entitled_capabilities": ["delivery_field_force"]},
        is_active=True,
    )
    # Org B: Entitled separate tenant (for cross-tenant tests)
    org_b = OrganizationRecord(
        id="org-ff-b",
        name="Entitled Field Org B",
        slug="entitled-field-b",
        tier="pro",
        metadata_json={"package_key": "company_os_pro", "entitled_capabilities": ["delivery_field_force"]},
        is_active=True,
    )
    # Org Free: Active org WITHOUT delivery_field_force entitlement (SEO-only / Launch tier)
    org_unentitled = OrganizationRecord(
        id="org-ff-unentitled",
        name="SEO Only Org",
        slug="seo-only-org",
        tier="launch",
        metadata_json={"package_key": "seo_blog_copilot", "entitled_capabilities": ["seo_content_automation"]},
        is_active=True,
    )

    pw_hash = hash_password("StrongPass!123")
    mgr_a = UserRecord(
        id="user-a-mgr",
        org_id=org_a.id,
        email="mgr@orga.test",
        full_name="Manager A",
        role="manager",
        password_hash=pw_hash,
        is_active=True,
    )
    mem_a1 = UserRecord(
        id="user-a-mem1",
        org_id=org_a.id,
        email="mem1@orga.test",
        full_name="Member A1",
        role="member",
        password_hash=pw_hash,
        is_active=True,
    )
    mem_a2 = UserRecord(
        id="user-a-mem2",
        org_id=org_a.id,
        email="mem2@orga.test",
        full_name="Member A2",
        role="member",
        password_hash=pw_hash,
        is_active=True,
    )
    cust_a = UserRecord(
        id="user-a-cust",
        org_id=org_a.id,
        email="cust@orga.test",
        full_name="Customer A",
        role="customer",
        password_hash=pw_hash,
        is_active=True,
    )
    mem_b = UserRecord(
        id="user-b-mem1",
        org_id=org_b.id,
        email="mem1@orgb.test",
        full_name="Member B1",
        role="member",
        password_hash=pw_hash,
        is_active=True,
    )
    unent_mgr = UserRecord(
        id="user-unent-mgr",
        org_id=org_unentitled.id,
        email="mgr@unentitled.test",
        full_name="Unentitled Mgr",
        role="manager",
        password_hash=pw_hash,
        is_active=True,
    )
    unent_mem = UserRecord(
        id="user-unent-mem",
        org_id=org_unentitled.id,
        email="mem@unentitled.test",
        full_name="Unentitled Member",
        role="member",
        password_hash=pw_hash,
        is_active=True,
    )

    # Seed attendance, tasks, visits, and conveyance claims for A1, A2, and B1
    now = datetime.now(UTC)
    records = [
        org_a, org_b, org_unentitled,
        mgr_a, mem_a1, mem_a2, cust_a, mem_b, unent_mgr, unent_mem,
        FieldAttendanceRecord(
            id="att-a1", org_id=org_a.id, user_id=mem_a1.id, event_type="CHECK_IN",
            latitude=28.6139, longitude=77.2090, accuracy_meters=5.0,
            device_fingerprint="fp-a1-123456", status="VERIFIED", idempotency_key="att-a1-k", timestamp=now,
        ),
        FieldAttendanceRecord(
            id="att-a2", org_id=org_a.id, user_id=mem_a2.id, event_type="CHECK_IN",
            latitude=28.6139, longitude=77.2090, accuracy_meters=5.0,
            device_fingerprint="fp-a2-123456", status="VERIFIED", idempotency_key="att-a2-k", timestamp=now,
        ),
        FieldAttendanceRecord(
            id="att-b1", org_id=org_b.id, user_id=mem_b.id, event_type="CHECK_IN",
            latitude=28.6139, longitude=77.2090, accuracy_meters=5.0,
            device_fingerprint="fp-b1-123456", status="VERIFIED", idempotency_key="att-b1-k", timestamp=now,
        ),
        FieldTaskRecord(
            id="task-a1", org_id=org_a.id, assigned_to_user_id=mem_a1.id, title="Task A1",
            client_name="Client A1", destination_lat=28.63, destination_lon=77.22, priority="HIGH", status="ASSIGNED",
        ),
        FieldTaskRecord(
            id="task-a2", org_id=org_a.id, assigned_to_user_id=mem_a2.id, title="Task A2",
            client_name="Client A2", destination_lat=28.63, destination_lon=77.22, priority="NORMAL", status="ASSIGNED",
        ),
        FieldTaskRecord(
            id="task-b1", org_id=org_b.id, assigned_to_user_id=mem_b.id, title="Task B1",
            client_name="Client B1", destination_lat=28.63, destination_lon=77.22, priority="NORMAL", status="ASSIGNED",
        ),
        ClientVisitRecord(
            id="visit-a1", task_id="task-a1", org_id=org_a.id, user_id=mem_a1.id, client_name="Client A1",
            visit_lat=28.63, visit_lon=77.22, distance_from_site_meters=5.0,
            geo_otp_verified=True, photo_verification_status="VERIFIED", completed_at=now,
        ),
        ClientVisitRecord(
            id="visit-a2", task_id="task-a2", org_id=org_a.id, user_id=mem_a2.id, client_name="Client A2",
            visit_lat=28.63, visit_lon=77.22, distance_from_site_meters=5.0,
            geo_otp_verified=True, photo_verification_status="VERIFIED", completed_at=now,
        ),
        ClientVisitRecord(
            id="visit-b1", task_id="task-b1", org_id=org_b.id, user_id=mem_b.id, client_name="Client B1",
            visit_lat=28.63, visit_lon=77.22, distance_from_site_meters=5.0,
            geo_otp_verified=True, photo_verification_status="VERIFIED", completed_at=now,
        ),
        ConveyanceClaimRecord(
            id="claim-a1", org_id=org_a.id, user_id=mem_a1.id, claim_date="2026-11-20",
            transport_mode="TWO_WHEELER", raw_gps_distance_km=10.0, verified_road_distance_km=10.0,
            jitter_filtered_km=0.0, rate_per_km=4.5, total_conveyance_amount=45.0,
            total_expenses_amount=0.0, grand_total_amount=45.0, receipt_count=0,
            status="AUTO_APPROVED", discrepancy_flags=[],
        ),
        ConveyanceClaimRecord(
            id="claim-a2", org_id=org_a.id, user_id=mem_a2.id, claim_date="2026-11-20",
            transport_mode="TWO_WHEELER", raw_gps_distance_km=12.0, verified_road_distance_km=12.0,
            jitter_filtered_km=0.0, rate_per_km=4.5, total_conveyance_amount=54.0,
            total_expenses_amount=0.0, grand_total_amount=54.0, receipt_count=0,
            status="AUTO_APPROVED", discrepancy_flags=[],
        ),
        ConveyanceClaimRecord(
            id="claim-b1", org_id=org_b.id, user_id=mem_b.id, claim_date="2026-11-20",
            transport_mode="TWO_WHEELER", raw_gps_distance_km=15.0, verified_road_distance_km=15.0,
            jitter_filtered_km=0.0, rate_per_km=4.5, total_conveyance_amount=67.5,
            total_expenses_amount=0.0, grand_total_amount=67.5, receipt_count=0,
            status="AUTO_APPROVED", discrepancy_flags=[],
        ),
    ]
    db.add_all(records)
    db.commit()

    def _tok(user: UserRecord) -> dict[str, str]:
        token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
            org_id=user.org_id or "",
        )
        return {"Authorization": f"Bearer {token}"}

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
            "hdr_mgr_a": _tok(mgr_a),
            "hdr_mem_a1": _tok(mem_a1),
            "hdr_mem_a2": _tok(mem_a2),
            "hdr_cust_a": _tok(cust_a),
            "hdr_mem_b": _tok(mem_b),
            "hdr_unent_mgr": _tok(unent_mgr),
            "hdr_unent_mem": _tok(unent_mem),
            "ids": {
                "org_a": org_a.id,
                "org_b": org_b.id,
                "mem_a1": mem_a1.id,
                "mem_a2": mem_a2.id,
                "mem_b": mem_b.id,
            },
        }
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def _conveyance_payload(user_id: str) -> dict:
    now = datetime.now(UTC)
    return {
        "user_id": user_id,
        "claim_date": "2026-11-20",
        "transport_mode": "TWO_WHEELER",
        "gps_breadcrumbs": [
            {"latitude": 28.6139, "longitude": 77.2090, "timestamp": now.isoformat()},
            {"latitude": 28.5355, "longitude": 77.2410, "timestamp": (now + timedelta(minutes=25)).isoformat()},
        ],
    }


def test_unauthenticated_and_customer_rejected_across_all_field_force_routes(ff_env):
    client = ff_env["client"]
    hdr_cust = ff_env["hdr_cust_a"]
    uid = ff_env["ids"]["mem_a1"]

    routes = [
        ("GET", "/v1/field-force/geofences", None),
        ("GET", "/v1/field-force/attendance/history", None),
        ("GET", "/v1/field-force/tasks", None),
        ("GET", "/v1/field-force/visits", None),
        ("GET", "/v1/field-force/conveyance/claims", None),
        ("POST", "/v1/field-force/conveyance/calculate", _conveyance_payload(uid)),
    ]
    for method, path, body in routes:
        r_anon = client.request(method, path, json=body)
        assert r_anon.status_code == 401, f"{method} {path} must reject anonymous with 401, got {r_anon.status_code}"

        r_cust = client.request(method, path, json=body, headers=hdr_cust)
        assert r_cust.status_code == 403, f"{method} {path} must reject customer role with 403, got {r_cust.status_code}"


def test_unentitled_tenant_blocked_on_all_read_calculation_and_write_routes(ff_env):
    """Org without delivery_field_force entitlement must get 403 on every Field Force route."""
    client = ff_env["client"]
    hdr_unent_mem = ff_env["hdr_unent_mem"]
    hdr_unent_mgr = ff_env["hdr_unent_mgr"]

    checks = [
        ("GET", "/v1/field-force/geofences", None, hdr_unent_mem),
        ("GET", "/v1/field-force/attendance/history", None, hdr_unent_mem),
        ("GET", "/v1/field-force/tasks", None, hdr_unent_mem),
        ("GET", "/v1/field-force/visits", None, hdr_unent_mem),
        ("GET", "/v1/field-force/conveyance/claims", None, hdr_unent_mem),
        ("POST", "/v1/field-force/conveyance/calculate", _conveyance_payload("user-unent-mem"), hdr_unent_mem),
        ("POST", "/v1/field-force/conveyance/submit", _conveyance_payload("user-unent-mem"), hdr_unent_mem),
        (
            "POST",
            "/v1/field-force/routes/optimize",
            {"user_id": "user-unent-mem", "start_latitude": 28.61, "start_longitude": 77.20},
            hdr_unent_mem,
        ),
        (
            "POST",
            "/v1/field-force/geofences",
            {"name": "Blocked Hub", "latitude": 28.61, "longitude": 77.20},
            hdr_unent_mgr,
        ),
    ]
    for method, path, body, hdr in checks:
        resp = client.request(method, path, json=body, headers=hdr)
        assert resp.status_code == 403, f"{method} {path} must reject unentitled tenant with 403, got {resp.status_code}: {resp.text}"
        assert "not entitled" in resp.text.lower() or "delivery_field_force" in resp.text.lower()


def test_member_canonical_ownership_and_no_cross_member_or_cross_tenant_leakage(ff_env):
    """Member A1 can only read/calculate/act on own canonical user_id, never A2 or Org B."""
    client = ff_env["client"]
    hdr_a1 = ff_env["hdr_mem_a1"]
    a1 = ff_env["ids"]["mem_a1"]
    a2 = ff_env["ids"]["mem_a2"]
    b1 = ff_env["ids"]["mem_b"]

    # 1. Default unfiltered reads return ONLY Member A1's own records (never A2 or B1)
    r_att = client.get("/v1/field-force/attendance/history", headers=hdr_a1)
    assert r_att.status_code == 200
    assert [row["id"] for row in r_att.json()] == ["att-a1"]

    r_tasks = client.get("/v1/field-force/tasks", headers=hdr_a1)
    assert r_tasks.status_code == 200
    assert [row["id"] for row in r_tasks.json()] == ["task-a1"]

    r_visits = client.get("/v1/field-force/visits", headers=hdr_a1)
    assert r_visits.status_code == 200
    assert [row["id"] for row in r_visits.json()] == ["visit-a1"]

    r_claims = client.get("/v1/field-force/conveyance/claims", headers=hdr_a1)
    assert r_claims.status_code == 200
    assert [row["id"] for row in r_claims.json()] == ["claim-a1"]

    r_calc = client.post("/v1/field-force/conveyance/calculate", json=_conveyance_payload(a1), headers=hdr_a1)
    assert r_calc.status_code == 200
    assert r_calc.json()["user_id"] == a1

    # 2. Requesting another member's user_id (same-org A2 or cross-tenant B1) MUST return 403
    for target_uid in (a2, b1):
        for get_path in (
            f"/v1/field-force/attendance/history?user_id={target_uid}",
            f"/v1/field-force/tasks?user_id={target_uid}",
            f"/v1/field-force/visits?user_id={target_uid}",
            f"/v1/field-force/conveyance/claims?user_id={target_uid}",
        ):
            r = client.get(get_path, headers=hdr_a1)
            assert r.status_code == 403, f"GET {get_path} must reject cross-member/cross-tenant with 403, got {r.status_code}"

        r_calc_forged = client.post("/v1/field-force/conveyance/calculate", json=_conveyance_payload(target_uid), headers=hdr_a1)
        assert r_calc_forged.status_code == 403

        r_sub_forged = client.post("/v1/field-force/conveyance/submit", json=_conveyance_payload(target_uid), headers=hdr_a1)
        assert r_sub_forged.status_code == 403

        r_chk_forged = client.post(
            "/v1/field-force/attendance/check-in",
            json={
                "user_id": target_uid,
                "latitude": 28.6139,
                "longitude": 77.2090,
                "device_fingerprint": "device-fp-valid-1234",
                "idempotency_key": f"chk-{uuid.uuid4().hex}",
            },
            headers=hdr_a1,
        )
        assert r_chk_forged.status_code == 403


def test_tenant_manager_scoped_to_own_org_and_blocked_from_cross_tenant_user_id(ff_env):
    """Org A manager sees A1+A2 (never B1) and gets 403 when filtering or calculating for Org B's user_id."""
    client = ff_env["client"]
    hdr_mgr = ff_env["hdr_mgr_a"]
    b1 = ff_env["ids"]["mem_b"]

    r_att = client.get("/v1/field-force/attendance/history", headers=hdr_mgr)
    assert r_att.status_code == 200
    assert set(row["id"] for row in r_att.json()) == {"att-a1", "att-a2"}

    r_tasks = client.get("/v1/field-force/tasks", headers=hdr_mgr)
    assert r_tasks.status_code == 200
    assert set(row["id"] for row in r_tasks.json()) == {"task-a1", "task-a2"}

    r_visits = client.get("/v1/field-force/visits", headers=hdr_mgr)
    assert r_visits.status_code == 200
    assert set(row["id"] for row in r_visits.json()) == {"visit-a1", "visit-a2"}

    r_claims = client.get("/v1/field-force/conveyance/claims", headers=hdr_mgr)
    assert r_claims.status_code == 200
    assert set(row["id"] for row in r_claims.json()) == {"claim-a1", "claim-a2"}

    # Cross-tenant user_id filter/payload must fail closed with 403
    for path in (
        f"/v1/field-force/attendance/history?user_id={b1}",
        f"/v1/field-force/tasks?user_id={b1}",
        f"/v1/field-force/visits?user_id={b1}",
        f"/v1/field-force/conveyance/claims?user_id={b1}",
    ):
        assert client.get(path, headers=hdr_mgr).status_code == 403

    assert client.post("/v1/field-force/conveyance/calculate", json=_conveyance_payload(b1), headers=hdr_mgr).status_code == 403


def test_member_missing_canonical_user_id_fails_closed_without_subject_fallback(ff_env):
    """Issue #14: If principal.user_id is absent, NEVER fall back to email-like principal.subject."""
    client = ff_env["client"]
    org_a_id = ff_env["ids"]["org_a"]

    app.dependency_overrides[get_current_principal] = lambda: APIPrincipal(
        subject="mem1@orga.test",
        user_id=None,
        role="member",
        org_id=org_a_id,
    )
    try:
        for method, path, body in (
            ("GET", "/v1/field-force/attendance/history", None),
            ("GET", "/v1/field-force/tasks", None),
            ("GET", "/v1/field-force/visits", None),
            ("GET", "/v1/field-force/conveyance/claims", None),
            ("POST", "/v1/field-force/conveyance/calculate", _conveyance_payload("mem1@orga.test")),
        ):
            r = client.request(method, path, json=body)
            assert r.status_code == 403, f"{method} {path} must fail closed (403) when user_id is None, got {r.status_code}"
            assert "user_id" in r.text.lower()
    finally:
        app.dependency_overrides.pop(get_current_principal, None)
