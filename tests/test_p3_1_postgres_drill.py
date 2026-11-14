"""Tests for scripts/pg_backup_restore_drill.py safety guards, masking, preflight, and parity logic."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.pg_backup_restore_drill import (
    DrillSafetyError,
    compare_source_and_target,
    compute_sha256,
    execute_drill,
    mask_database_url,
    run_preflight,
    validate_target_isolation,
)


def test_mask_database_url_redacts_credentials_and_query_params() -> None:
    masked = mask_database_url(
        "postgresql://superadmin:UltraSecretPass123@ep-prod-pooler.us-east-2.aws.neon.tech:5432/neondb?sslmode=require&channel_binding=require"
    )
    assert masked.configured is True
    assert masked.host == "ep-prod-pooler.us-east-2.aws.neon.tech"
    assert masked.port == 5432
    assert masked.database == "neondb"
    assert "superadmin" not in masked.masked_url
    assert "UltraSecretPass123" not in masked.masked_url
    assert "channel_binding" not in masked.masked_url
    assert "***:***@ep-prod-pooler.us-east-2.aws.neon.tech:5432/neondb" in masked.masked_url


def test_validate_target_isolation_blocks_same_or_production_targets() -> None:
    prod_src = "postgresql://user:pass@ep-abc.us-east-2.aws.neon.tech/neondb"

    with pytest.raises(DrillSafetyError, match="matches source"):
        validate_target_isolation(prod_src, prod_src)

    with pytest.raises(DrillSafetyError, match="managed/production endpoint"):
        validate_target_isolation(
            prod_src,
            "postgresql://user:pass@ep-abc.us-east-2.aws.neon.tech/neondb_restore_test",
            allow_shared_host_isolated_db=False,
        )

    with pytest.raises(DrillSafetyError, match="target database name cannot match"):
        validate_target_isolation(
            prod_src,
            "postgresql://user:pass@ep-other.us-east-2.aws.neon.tech/neondb",
            allow_shared_host_isolated_db=True,
        )

    # Local isolated Postgres DB passes cleanly
    validate_target_isolation(
        prod_src,
        "postgresql://postgres:postgres@127.0.0.1:5432/askforwrite_drill_restore",
    )


def test_compare_source_and_target_parity_checks() -> None:
    src = {
        "alembic_version": "0001_p0_hardening",
        "core_row_counts": {"organizations": 5, "customers": 3, "invoices": 2},
    }
    tgt_ok = {
        "alembic_version": "0001_p0_hardening",
        "core_row_counts": {"organizations": 5, "customers": 3, "invoices": 2},
    }
    assert compare_source_and_target(src, tgt_ok) == {"parity_verified": True, "mismatches": []}

    tgt_bad = {
        "alembic_version": "0000_old",
        "core_row_counts": {"organizations": 4, "customers": 3, "invoices": 2},
    }
    diff = compare_source_and_target(src, tgt_bad)
    assert diff["parity_verified"] is False
    assert len(diff["mismatches"]) == 2


def test_run_preflight_reports_blocked_when_pg_binaries_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.pg_backup_restore_drill.detect_pg_binaries",
        lambda: {"pg_dump": None, "pg_restore": None, "psql": None},
    )
    report = run_preflight("postgresql://u:sec@127.0.0.1:5432/db1", "env:DATABASE_URL")
    assert report["verification_status"] == "BLOCKED"
    assert report["restore_tested"] is False
    assert "sec" not in report["source_db"]["masked_url"]
    assert any("pg_dump" in b for b in report["blockers"])


def test_execute_drill_with_mocked_binaries_and_inspected_states(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "scripts.pg_backup_restore_drill.detect_pg_binaries",
        lambda: {"pg_dump": "/usr/bin/pg_dump", "pg_restore": "/usr/bin/pg_restore", "psql": "/usr/bin/psql"},
    )

    def fake_subprocess_run(cmd, **_kwargs):
        exe = str(cmd[0])
        if exe.endswith("pg_dump"):
            for arg in cmd:
                if str(arg).startswith("--file="):
                    Path(str(arg).split("=", 1)[1]).write_bytes(b"PGDMP-SYNTHETIC-ARCHIVE")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("scripts.pg_backup_restore_drill.subprocess.run", fake_subprocess_run)
    sample_state = {
        "table_count": 12,
        "alembic_version": "0001_p0_hardening",
        "core_row_counts": {"organizations": 2, "customers": 2, "alembic_version": 1},
        "distinct_organizations": 2,
    }
    monkeypatch.setattr("scripts.pg_backup_restore_drill.inspect_database_state", lambda _u: sample_state)
    monkeypatch.setattr(
        "scripts.pg_backup_restore_drill.verify_app_health_against_target",
        lambda _u: {"ok": True, "status_code": 200, "body": {"status": "ok"}},
    )

    sample_file = tmp_path / "hashcheck.bin"
    sample_file.write_bytes(b"abc")
    assert len(compute_sha256(sample_file)) == 64

    res = execute_drill(
        source_url="postgresql://srcuser:srcpass@127.0.0.1:5432/prod_clone",
        target_url="postgresql://tgtuser:tgtpass@127.0.0.1:5432/drill_restore",
        source_origin="test",
    )
    assert res["restore_tested"] is True
    assert res["verification_status"] == "LIVE_VERIFIED"
    assert res["parity"]["parity_verified"] is True
    assert res["dump_bytes"] > 0
    assert len(res["dump_sha256"]) == 64
    assert "srcpass" not in res["source_db"]
    assert "tgtpass" not in res["target_db"]
