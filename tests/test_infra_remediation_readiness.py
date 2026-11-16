"""Infrastructure remediation, healthcheck deadline, ECDSA key durability/rotation,
PayPal mode reconciliation, and Render/Neon configuration verification tests.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db, get_database_topology_summary, normalize_database_url
from app.main import app
from app.security import ecdsa_pki
from app.security.trust_chain import seal_task_to_block, verify_chain_integrity
from app.services.p8_marketplace import (
    create_marketplace_listing,
    register_developer_profile,
    verify_developer_kyb,
    verify_listing_signature,
)
from app.services.payment import inspect_payment_provider_config, resolve_paypal_mode
from app.services.payment_paypal import PayPalProvider


@pytest.fixture()
def isolated_infra_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("TRUST_ENGINE_KEYS_DIR", str(tmp_path / "keys"))
    monkeypatch.delenv("TRUST_ENGINE_PRIVATE_KEY_PEM", raising=False)
    monkeypatch.delenv("TRUST_ENGINE_PUBLIC_KEY_PEM", raising=False)
    monkeypatch.delenv("TRUST_ENGINE_RETIRED_PUBLIC_KEYS_PEM", raising=False)
    ecdsa_pki._reset_cached_keys()

    db_file = tmp_path / "infra_test.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _override():
        sess = TestingSession()
        try:
            yield sess
        finally:
            sess.close()

    prev_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override
    try:
        with TestingSession() as db:
            with TestClient(app) as client:
                yield client, db, TestingSession, tmp_path
    finally:
        if prev_override is not None:
            app.dependency_overrides[get_db] = prev_override
        else:
            app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        ecdsa_pki._reset_cached_keys()


def test_healthz_liveness_stays_fast_even_when_db_down(isolated_infra_db) -> None:
    """/healthz is zero-dependency process liveness and succeeds even if get_db fails."""
    client, _db, _sf, _tmp = isolated_infra_db

    broken_db = MagicMock()
    broken_db.execute.side_effect = RuntimeError("DB completely unreachable")
    app.dependency_overrides[get_db] = lambda: broken_db

    t0 = time.perf_counter()
    rz = client.get("/healthz")
    cold_elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert rz.status_code == 200
    assert rz.json()["status"] == "alive"
    assert cold_elapsed_ms < 3000.0

    t1 = time.perf_counter()
    rz_warm = client.get("/healthz")
    warm_elapsed_ms = (time.perf_counter() - t1) * 1000.0
    assert rz_warm.status_code == 200
    assert warm_elapsed_ms < 100.0

    # /readyz and /health still expose DB degradation honestly via 503 (never masking failure)
    rd = client.get("/readyz")
    assert rd.status_code == 503
    assert rd.json()["detail"]["status"] == "not_ready"
    assert rd.json()["detail"]["database"] == "degraded"

    rh = client.get("/health")
    assert rh.status_code == 503
    assert rh.json()["detail"]["status"] == "unhealthy"
    assert rh.json()["detail"]["database"] == "degraded"


def test_readyz_and_health_happy_path_and_blackhole_pg_timeout_under_5s(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Simulate a hung PostgreSQL TCP socket and verify /readyz + /health fail closed within <2.5s (never 35s+)."""
    monkeypatch.setenv("TRUST_ENGINE_KEYS_DIR", str(tmp_path / "keys"))
    monkeypatch.setenv("HEALTHCHECK_DB_TIMEOUT_SECONDS", "1.0")
    ecdsa_pki._reset_cached_keys()

    # Bind a silent TCP server that accepts sockets and never sends PG wire bytes (simulates stalled compute/pool)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    port = srv.getsockname()[1]
    stop_flag = threading.Event()
    conns: list[socket.socket] = []

    def _accept_loop() -> None:
        srv.settimeout(0.2)
        while not stop_flag.is_set():
            try:
                c, _ = srv.accept()
                conns.append(c)
            except TimeoutError:
                continue
            except OSError:
                break

    th = threading.Thread(target=_accept_loop, daemon=True)
    th.start()

    prev_override = app.dependency_overrides.pop(get_db, None)
    monkeypatch.setenv("DATABASE_URL", f"postgresql+psycopg://postgres:pass@127.0.0.1:{port}/staging_test")
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)

    try:
        with TestClient(app) as client:
            rz = client.get("/healthz")
            assert rz.status_code == 200
            assert rz.json()["status"] == "alive"

            t0 = time.perf_counter()
            rd = client.get("/readyz")
            elapsed_ready = time.perf_counter() - t0
            assert rd.status_code == 503
            assert elapsed_ready < 3.0, f"/readyz took {elapsed_ready:.2f}s (must stay < 5.0s)"
            detail = rd.json()["detail"]
            assert detail["database"] == "degraded"
            assert detail["status"] == "not_ready"

            t1 = time.perf_counter()
            rh = client.get("/health")
            elapsed_health = time.perf_counter() - t1
            assert rh.status_code == 503
            assert elapsed_health < 3.0, f"/health took {elapsed_health:.2f}s (must stay < 5.0s)"
            assert rh.json()["detail"]["database"] == "degraded"
    finally:
        stop_flag.set()
        for c in conns:
            try:
                c.close()
            except OSError:
                pass
        srv.close()
        th.join(timeout=2.0)
        if prev_override is not None:
            app.dependency_overrides[get_db] = prev_override
        ecdsa_pki._reset_cached_keys()


def test_readyz_happy_path_reports_connected_and_signing_keys(isolated_infra_db) -> None:
    client, _db, _sf, _tmp = isolated_infra_db
    rd = client.get("/readyz")
    assert rd.status_code == 200
    body = rd.json()
    assert body["status"] == "ready"
    assert body["database"] == "connected"
    assert body["signing_keys"]["kid"]
    assert body["signing_keys"]["durable"] is True


def test_ecdsa_durable_env_injection_and_zero_downtime_rotation(
    isolated_infra_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify env-injected keys survive ephemeral disk wipe and key rotation preserves P8 + TrustChain verification."""
    client, db, _sf, tmp_path = isolated_infra_db

    # 1. Seed verified developer and P8 listing signed with keypair #1
    dev = register_developer_profile(
        db,
        org_id=None,
        developer_name="Rotation Test Dev",
        contact_email="dev-rot@askforwrite.test",
        legal_entity_name="Rotation Dev LLP",
    )
    verify_developer_kyb(db, developer_id=dev["developer_id"], kyb_status="VERIFIED", kyb_notes="ok", actor="owner")

    l1 = create_marketplace_listing(
        db,
        developer_id=dev["developer_id"],
        listing_slug="pre-rotation-pkg",
        name="Pre Rotation Package",
        version="1.0.0",
        is_platform_operator=True,
    )
    b1 = seal_task_to_block(db, task_id="task-pre-rot", capability_name="p8", action="sign", payload={"v": 1})
    assert b1.index >= 1

    # 2. Rotate keypair atomically cleanly (old public key archived in retired_public_keys.json)
    rot = ecdsa_pki.rotate_node_keypair()
    assert rot["previous_kid"] != rot["new_kid"]
    assert rot["retired_trusted_keys_count"] >= 1

    l2 = create_marketplace_listing(
        db,
        developer_id=dev["developer_id"],
        listing_slug="post-rotation-pkg",
        name="Post Rotation Package",
        version="1.1.0",
        is_platform_operator=True,
    )
    seal_task_to_block(db, task_id="task-post-rot", capability_name="p8", action="sign", payload={"v": 2})

    # Both pre-rotation and post-rotation listings and TrustChain must verify!
    v1 = verify_listing_signature(db, listing_id=l1["listing_id"], is_platform_operator=True)
    v2 = verify_listing_signature(db, listing_id=l2["listing_id"], is_platform_operator=True)
    assert v1["verified"] is True
    assert v1["public_key_pinned"] is True
    assert v2["verified"] is True
    assert verify_chain_integrity(db)["chain_valid"] is True

    # 3. Simulate stateless container restart on blank ephemeral disk using env secrets ONLY
    new_priv_pem = (tmp_path / "keys" / "node_private_key.pem").read_text(encoding="utf-8")
    escaped_priv_pem = new_priv_pem.strip().replace("\n", "\\n")
    empty_keys_dir = tmp_path / "blank_ephemeral_keys"
    empty_keys_dir.mkdir(parents=True, exist_ok=True)

    ecdsa_pki._reset_cached_keys()
    monkeypatch.setenv("TRUST_ENGINE_KEYS_DIR", str(empty_keys_dir))
    monkeypatch.setenv("TRUST_ENGINE_PRIVATE_KEY_PEM", escaped_priv_pem)
    monkeypatch.setenv("TRUST_ENGINE_RETIRED_PUBLIC_KEYS_PEM", rot["retired_public_keys_env_json"])

    status_env = ecdsa_pki.get_node_key_status()
    assert status_env["source"] == "env"
    assert status_env["durable"] is True
    assert status_env["multi_instance_safe"] is True
    assert status_env["kid"] == rot["new_kid"]
    assert rot["previous_kid"] in status_env["retired_kids"]

    # Even with empty ephemeral disk, BOTH pre-rotation and post-rotation listings verify cleanly
    assert verify_listing_signature(db, listing_id=l1["listing_id"], is_platform_operator=True)["verified"] is True
    assert verify_listing_signature(db, listing_id=l2["listing_id"], is_platform_operator=True)["verified"] is True

    # Mismatched public/private env keys must fail closed
    rogue_pub = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("utf-8")
    )
    monkeypatch.setenv("TRUST_ENGINE_PUBLIC_KEY_PEM", rogue_pub)
    with pytest.raises(ValueError, match="does not match"):
        ecdsa_pki.init_node_keys()
    monkeypatch.delenv("TRUST_ENGINE_PUBLIC_KEY_PEM", raising=False)
    ecdsa_pki._reset_cached_keys()


def test_paypal_mode_reconciliation_and_db_topology_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure PayPal mode fails safe to sandbox unless explicitly 'live', and DB topology distinguishes pooled/direct."""
    monkeypatch.delenv("PAYPAL_MODE", raising=False)
    assert resolve_paypal_mode() == "sandbox"
    assert PayPalProvider()._base_url == PayPalProvider.SANDBOX_URL
    assert inspect_payment_provider_config()["paypal"]["mode"] == "sandbox"

    monkeypatch.setenv("PAYPAL_MODE", "LIVE")
    assert resolve_paypal_mode() == "live"
    assert PayPalProvider()._base_url == PayPalProvider.LIVE_URL

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@ep-abc-pooler.c-6.us-east-2.aws.neon.tech:5432/appdb")
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", "postgresql://u:p@ep-abc.c-6.us-east-2.aws.neon.tech:5432/appdb")
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    topo = get_database_topology_summary()
    assert topo["dialect"] == "postgresql"
    assert topo["runtime_connection_mode"] == "pooled"
    assert topo["unpooled_migration_url_configured"] is True
    assert topo["unpooled_url_is_direct"] is True
    assert "pooler" not in normalize_database_url(os.environ["DATABASE_URL_UNPOOLED"])


def test_render_blueprint_staging_single_worker_and_healthz() -> None:
    """Validate render.yaml staging service enforces 1 worker, /healthz, bounded DB probe, and key secret slots."""
    repo_root = Path(__file__).resolve().parents[1]
    render_yaml = (repo_root / "render.yaml").read_text(encoding="utf-8")
    staging_block = render_yaml.split("name: askforwrite-ai-company-os-staging", 1)[1]
    assert "healthCheckPath: /healthz" in staging_block
    assert 'value: "1"' in staging_block  # UVICORN_WORKERS=1 on staging
    assert "key: DATABASE_URL_UNPOOLED" in staging_block
    assert "key: TRUST_ENGINE_PRIVATE_KEY_PEM" in staging_block
    assert "key: TRUST_ENGINE_RETIRED_PUBLIC_KEYS_PEM" in staging_block
    assert "key: HEALTHCHECK_DB_TIMEOUT_SECONDS" in staging_block

    inv_path = repo_root / "docs" / "route_authorization_inventory.json"
    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    paths = {r["path"] for r in inv["routes"]}
    assert {"/health", "/healthz", "/readyz"}.issubset(paths)
