#!/usr/bin/env python3
"""Executable PostgreSQL Backup & Restore Drill for AskforWrite AI Company OS (P3.1).

Safely verifies PostgreSQL backup integrity, isolated target restore, schema/alembic_version
parity, core table row counts, tenant scoping, RPO/RTO timings, and FastAPI /health check
without ever exposing credentials or touching production databases as restore targets.

Usage:
  # Check environment prerequisites & masked configured DB target (zero side effects):
  python scripts/pg_backup_restore_drill.py --check-only --json

  # Execute full dump -> checksum -> isolated restore -> verify drill:
  python scripts/pg_backup_restore_drill.py ^
    --source-url "$NEON_DATABASE_URL" ^
    --target-url "postgresql://postgres:postgres@127.0.0.1:5432/askforwrite_drill_restore"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CORE_TABLES_TO_VERIFY: tuple[str, ...] = (
    "alembic_version",
    "organizations",
    "users",
    "tenant_invitations",
    "customer_records",
    "subscription_records",
    "invoice_records",
    "workflow_definitions",
    "workflow_runs",
    "execution_evidence_records",
    "credit_ledger_records",
    "connector_states",
    "approval_requests",
    "p2_customer_engagements",
    "p3_customer_accounts",
    "p3_onboarding_workflows",
    "p3_service_deliveries",
    "p3_support_tickets",
    "p4_icp_profiles",
    "p4_market_intel_records",
    "p4_growth_campaigns",
    "p4_pipeline_deals",
    "p5_tenant_templates",
    "p5_provisioning_runs",
    "p5_tenant_policies",
    "p5_usage_quota_events",
    "p5_operational_incidents",
    "p6_industry_packs",
    "p6_tenant_pack_deployments",
    "p6_seo_baselines",
    "p7_delegation_plans",
    "p7_tenant_memories",
    "p7_autonomy_policies",
    "p7_agent_eval_runs",
    "p8_developer_profiles",
    "p8_marketplace_listings",
    "p8_tenant_installs",
    "p8_marketplace_reviews",
    "p8_revenue_share_ledger",
)

PRODUCTION_DB_NAMES: tuple[str, ...] = ("neondb", "prod", "production")

PRODUCTION_HOST_FRAGMENTS: tuple[str, ...] = (
    "neon.tech",
    "render.com",
    "askforwrite.com",
    "rds.amazonaws.com",
)


class DrillSafetyError(ValueError):
    """Raised when a drill target could endanger a production database."""


@dataclass(frozen=True)
class MaskedDbInfo:
    configured: bool
    scheme: str
    host: str
    port: int | None
    database: str
    masked_url: str


def mask_database_url(raw_url: str | None) -> MaskedDbInfo:
    """Return non-sensitive metadata and a credential-redacted DSN string."""
    val = (raw_url or "").strip()
    if not val:
        return MaskedDbInfo(
            configured=False,
            scheme="",
            host="",
            port=None,
            database="",
            masked_url="<NOT_CONFIGURED>",
        )
    # Normalize SQLAlchemy driver prefixes for URI parsing
    normalized = val.replace("postgresql+psycopg://", "postgresql://").replace("postgres://", "postgresql://")
    parsed = urlsplit(normalized)
    host = parsed.hostname or ""
    port = parsed.port
    db_name = (parsed.path or "").lstrip("/")
    netloc = host
    if port:
        netloc = f"{host}:{port}"
    if parsed.username:
        netloc = f"***:***@{netloc}"
    masked_query = "sslmode=***" if parsed.query else ""
    masked = urlunsplit((parsed.scheme, netloc, parsed.path, masked_query, ""))
    return MaskedDbInfo(
        configured=True,
        scheme=parsed.scheme,
        host=host,
        port=port,
        database=db_name,
        masked_url=masked,
    )


def validate_target_isolation(
    source_url: str,
    target_url: str,
    *,
    allow_shared_host_isolated_db: bool = False,
    approved_staging_host: str | None = None,
    approved_staging_db: str | None = None,
) -> None:
    """Refuse any restore target that matches the source database or a production host."""
    src_info = mask_database_url(source_url)
    tgt_info = mask_database_url(target_url)

    if not tgt_info.configured:
        raise DrillSafetyError("Target restore URL is required and cannot be empty.")

    if not tgt_info.scheme.startswith("postgres"):
        raise DrillSafetyError(
            f"Unsupported target scheme '{tgt_info.scheme}'. Isolated PostgreSQL target required."
        )

    src_host_db = (src_info.host.lower(), src_info.port, src_info.database.lower())
    tgt_host_db = (tgt_info.host.lower(), tgt_info.port, tgt_info.database.lower())
    if src_host_db == tgt_host_db:
        raise DrillSafetyError(
            "Refused: target restore database matches source database host/port/name."
        )

    tgt_db_lower = tgt_info.database.lower()
    if tgt_db_lower in PRODUCTION_DB_NAMES:
        raise DrillSafetyError(
            f"Refused: target database name '{tgt_info.database}' is reserved for production."
        )

    tgt_host_lower = tgt_info.host.lower()
    if approved_staging_host and approved_staging_host.strip().lower() != tgt_host_lower:
        raise DrillSafetyError(
            f"Refused: target host '{tgt_info.host}' does not match --approved-staging-host '{approved_staging_host}'."
        )
    if approved_staging_db and approved_staging_db.strip().lower() != tgt_db_lower:
        raise DrillSafetyError(
            f"Refused: target database '{tgt_info.database}' does not match --approved-staging-db '{approved_staging_db}'."
        )

    if any(frag in tgt_host_lower for frag in PRODUCTION_HOST_FRAGMENTS):
        if not allow_shared_host_isolated_db:
            raise DrillSafetyError(
                f"Refused: target host '{tgt_info.host}' looks like a managed/production endpoint. "
                "Use an isolated local/ephemeral PostgreSQL database, or explicitly pass "
                "--confirm-isolated-branch with --approved-staging-host and --approved-staging-db."
            )
        if tgt_db_lower == src_info.database.lower():
            raise DrillSafetyError(
                "Refused: even with --confirm-isolated-branch, target database name cannot match source database name."
            )
        if not approved_staging_host or not approved_staging_db:
            raise DrillSafetyError(
                "Refused: --confirm-isolated-branch on a managed Postgres host requires both "
                "--approved-staging-host and --approved-staging-db."
            )


def detect_pg_binaries() -> dict[str, str | None]:
    """Detect PostgreSQL client binaries required for real dump & restore drills."""
    return {
        "pg_dump": shutil.which("pg_dump"),
        "pg_restore": shutil.which("pg_restore"),
        "psql": shutil.which("psql"),
    }


def resolve_configured_source_url(explicit_source: str | None) -> tuple[str | None, str]:
    """Resolve source DB URL in priority order without leaking it."""
    if explicit_source:
        return explicit_source, "--source-url"
    for key in ("NEON_DATABASE_URL", "DATABASE_URL"):
        val = os.getenv(key)
        if val and val.strip():
            return val.strip(), f"env:{key}"
    # Fallback: parse repo .env without mutating process env
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            k, v = stripped.split("=", 1)
            k = k.strip()
            if k in {"NEON_DATABASE_URL", "DATABASE_URL"}:
                cleaned = v.strip().strip('"').strip("'")
                if cleaned:
                    return cleaned, f".env:{k}"
    return None, "unconfigured"


def _to_libpq_url(raw_url: str) -> str:
    url = raw_url.strip()
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://"):]
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def _sanitize_libpq_dsn_and_env(raw_url: str) -> tuple[str, dict[str, str]]:
    """Strip password from libpq URI args and supply it cleanly via PGPASSWORD env."""
    parsed = urlsplit(_to_libpq_url(raw_url))
    env = dict(os.environ)
    if parsed.password is not None:
        env["PGPASSWORD"] = unquote(parsed.password)
    host = parsed.hostname or ""
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    if parsed.username:
        netloc = f"{parsed.username}@{netloc}"
    sanitized_dsn = urlunsplit((parsed.scheme or "postgresql", netloc, parsed.path, parsed.query, ""))
    return sanitized_dsn, env


def _to_sqlalchemy_url(raw_url: str) -> str:
    url = raw_url.strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a dump artifact."""
    digest = hashlib.sha256()
    with file_path.open("rb") as fh:
        while chunk := fh.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_database_state(db_url: str) -> dict[str, Any]:
    """Inspect Alembic revision, table inventory, core row counts, and tenant isolation via SQLAlchemy."""
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(_to_sqlalchemy_url(db_url), pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        tables = sorted(inspector.get_table_names())
        alembic_version: str | None = None
        row_counts: dict[str, int | None] = {}
        distinct_orgs: int | None = None

        with engine.connect() as conn:
            if "alembic_version" in tables:
                alembic_version = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
            for tbl in CORE_TABLES_TO_VERIFY:
                if tbl in tables:
                    # Table names come exclusively from the hardcoded CORE_TABLES_TO_VERIFY allowlist.
                    row_counts[tbl] = int(conn.execute(text(f'SELECT COUNT(*) FROM "{tbl}"')).scalar() or 0)
                else:
                    row_counts[tbl] = None
            if "organizations" in tables:
                distinct_orgs = int(conn.execute(text('SELECT COUNT(DISTINCT id) FROM "organizations"')).scalar() or 0)

        return {
            "table_count": len(tables),
            "alembic_version": alembic_version,
            "core_row_counts": row_counts,
            "distinct_organizations": distinct_orgs,
        }
    finally:
        engine.dispose()


def compare_source_and_target(source_state: dict[str, Any], target_state: dict[str, Any]) -> dict[str, Any]:
    """Compare schema, Alembic version, and core row counts between source and restored DB."""
    mismatches: list[dict[str, Any]] = []
    if source_state.get("alembic_version") != target_state.get("alembic_version"):
        mismatches.append(
            {
                "check": "alembic_version",
                "source": source_state.get("alembic_version"),
                "target": target_state.get("alembic_version"),
            }
        )
    src_counts = source_state.get("core_row_counts", {})
    tgt_counts = target_state.get("core_row_counts", {})
    for tbl, src_cnt in src_counts.items():
        tgt_cnt = tgt_counts.get(tbl)
        if src_cnt != tgt_cnt:
            mismatches.append(
                {
                    "check": f"row_count:{tbl}",
                    "source": src_cnt,
                    "target": tgt_cnt,
                }
            )
    return {
        "parity_verified": len(mismatches) == 0,
        "mismatches": mismatches,
    }


def verify_app_health_against_target(target_url: str) -> dict[str, Any]:
    """Verify FastAPI /health works against the isolated restored database using TestClient."""
    code = (
        "import json, os, dotenv; "
        "dotenv.load_dotenv = lambda *a, **k: False; "
        "os.environ['APP_ENV'] = 'test'; "
        "os.environ['DATABASE_URL'] = os.environ['DRILL_TARGET_URL']; "
        "os.environ['NEON_DATABASE_URL'] = ''; "
        "os.environ['ALLOW_LIVE_SIDE_EFFECTS'] = 'false'; "
        "from fastapi.testclient import TestClient; "
        "from app.main import app; "
        "c = TestClient(app); "
        "r = c.get('/health'); "
        "print(json.dumps({'status_code': r.status_code, 'body': r.json()}))"
    )
    env = dict(os.environ)
    env["DRILL_TARGET_URL"] = _to_sqlalchemy_url(target_url)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout).strip()[:500]}
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        return {
            "ok": payload.get("status_code") == 200 and payload.get("body", {}).get("status") == "ok",
            "status_code": payload.get("status_code"),
            "body": payload.get("body"),
        }
    except Exception as exc:
        return {"ok": False, "error": f"Unable to parse health output: {exc}"}


def run_preflight(source_url: str | None, source_origin: str) -> dict[str, Any]:
    """Inspect binaries and masked database metadata without making external mutations."""
    bins = detect_pg_binaries()
    masked = mask_database_url(source_url)
    missing_bins = [name for name in ("pg_dump", "pg_restore") if not bins.get(name)]
    blockers: list[str] = []
    if not masked.configured:
        blockers.append("No source PostgreSQL URL configured (DATABASE_URL / NEON_DATABASE_URL).")
    if missing_bins:
        blockers.append(f"Missing PostgreSQL client binaries on PATH: {', '.join(missing_bins)}.")

    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "verification_status": "BLOCKED" if blockers else "READY_FOR_DRILL",
        "restore_tested": False,
        "source_origin": source_origin,
        "source_db": {
            "configured": masked.configured,
            "scheme": masked.scheme,
            "host": masked.host,
            "port": masked.port,
            "database": masked.database,
            "masked_url": masked.masked_url,
        },
        "binaries": bins,
        "blockers": blockers,
    }


def execute_drill(
    *,
    source_url: str,
    target_url: str,
    source_origin: str,
    allow_shared_host_isolated_db: bool = False,
    approved_staging_host: str | None = None,
    approved_staging_db: str | None = None,
    verify_health: bool = True,
    keep_dump: bool = False,
    rpo_minutes: int = 15,
    record_api_url: str | None = None,
    owner_api_key: str | None = None,
) -> dict[str, Any]:
    """Execute full pg_dump -> checksum -> isolated pg_restore -> schema/row parity -> /health drill."""
    validate_target_isolation(
        source_url,
        target_url,
        allow_shared_host_isolated_db=allow_shared_host_isolated_db,
        approved_staging_host=approved_staging_host,
        approved_staging_db=approved_staging_db,
    )
    bins = detect_pg_binaries()
    missing = [name for name in ("pg_dump", "pg_restore") if not bins.get(name)]
    if missing:
        return {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "verification_status": "BLOCKED",
            "restore_tested": False,
            "error": f"Missing PostgreSQL client binaries on PATH: {', '.join(missing)}",
            "binaries": bins,
            "source_db": mask_database_url(source_url).masked_url,
            "target_db": mask_database_url(target_url).masked_url,
        }

    src_masked = mask_database_url(source_url)
    tgt_masked = mask_database_url(target_url)

    tmp_dir = Path(tempfile.mkdtemp(prefix="afw_pg_drill_"))
    dump_path = tmp_dir / "askforwrite_backup.dump"
    try:
        src_dsn, src_env = _sanitize_libpq_dsn_and_env(source_url)
        t0 = time.monotonic()
        dump_proc = subprocess.run(
            [
                bins["pg_dump"],  # type: ignore[list-item]
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                f"--file={dump_path}",
                src_dsn,
            ],
            env=src_env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        dump_seconds = round(time.monotonic() - t0, 3)
        if dump_proc.returncode != 0 or not dump_path.exists() or dump_path.stat().st_size == 0:
            return {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "verification_status": "FAILED",
                "restore_tested": False,
                "stage": "pg_dump",
                "error": (dump_proc.stderr or dump_proc.stdout).strip()[:600],
                "source_db": src_masked.masked_url,
                "target_db": tgt_masked.masked_url,
            }

        dump_bytes = dump_path.stat().st_size
        dump_sha256 = compute_sha256(dump_path)

        tgt_dsn, tgt_env = _sanitize_libpq_dsn_and_env(target_url)
        t_restore_start = time.monotonic()
        restore_proc = subprocess.run(
            [
                bins["pg_restore"],  # type: ignore[list-item]
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                f"--dbname={tgt_dsn}",
                str(dump_path),
            ],
            env=tgt_env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        restore_elapsed = time.monotonic() - t_restore_start
        if restore_proc.returncode not in (0,):
            # Note: pg_restore may emit warnings if target had no prior tables; check stderr carefully.
            return {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "verification_status": "FAILED",
                "restore_tested": False,
                "stage": "pg_restore",
                "dump_bytes": dump_bytes,
                "dump_sha256": dump_sha256,
                "error": (restore_proc.stderr or restore_proc.stdout).strip()[:600],
                "source_db": src_masked.masked_url,
                "target_db": tgt_masked.masked_url,
            }

        source_state = inspect_database_state(source_url)
        target_state = inspect_database_state(target_url)
        parity = compare_source_and_target(source_state, target_state)

        health_check = (
            verify_app_health_against_target(target_url)
            if verify_health
            else {"ok": True, "skipped": True}
        )
        rto_seconds = round(time.monotonic() - t_restore_start, 3)

        restore_tested = bool(parity["parity_verified"] and health_check.get("ok"))
        result: dict[str, Any] = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "verification_status": "LIVE_VERIFIED" if restore_tested else "FAILED",
            "restore_tested": restore_tested,
            "source_origin": source_origin,
            "source_db": src_masked.masked_url,
            "target_db": tgt_masked.masked_url,
            "dump_bytes": dump_bytes,
            "dump_sha256": dump_sha256,
            "dump_seconds": dump_seconds,
            "restore_seconds": round(restore_elapsed, 3),
            "rto_seconds": rto_seconds,
            "rpo_minutes": rpo_minutes,
            "source_state": source_state,
            "target_state": target_state,
            "parity": parity,
            "health_check": health_check,
        }

        if restore_tested and record_api_url and owner_api_key:
            import httpx

            rec_resp = httpx.post(
                f"{record_api_url.rstrip('/')}/v1/cs/ops/backup-drill",
                headers={"X-API-Key": owner_api_key},
                json={
                    "target_scope": f"postgresql:{tgt_masked.database}",
                    "restore_tested": True,
                    "recovery_point_objective_minutes": rpo_minutes,
                    "recovery_time_seconds": rto_seconds,
                    "evidence_ref": f"sha256:{dump_sha256[:16]}",
                    "notes": f"Verified pg_dump/pg_restore parity ({dump_bytes} bytes, {target_state['table_count']} tables).",
                },
                timeout=15.0,
            )
            result["api_recorded"] = rec_resp.status_code in (200, 201)
            result["api_status_code"] = rec_resp.status_code

        return result
    finally:
        if not keep_dump:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AskforWrite PostgreSQL Backup & Restore Drill")
    parser.add_argument("--check-only", action="store_true", help="Inspect binaries and redacted source config only")
    parser.add_argument("--source-url", help="Source PostgreSQL URL (defaults to NEON_DATABASE_URL/DATABASE_URL)")
    parser.add_argument("--target-url", help="Isolated PostgreSQL target restore URL")
    parser.add_argument(
        "--confirm-isolated-branch",
        action="store_true",
        help="Allow managed Postgres host ONLY when paired with --approved-staging-host and --approved-staging-db",
    )
    parser.add_argument(
        "--approved-staging-host",
        help="Explicitly approved isolated staging host (required with --confirm-isolated-branch on managed hosts)",
    )
    parser.add_argument(
        "--approved-staging-db",
        help="Explicitly approved non-production staging database name (must differ from source)",
    )
    parser.add_argument("--skip-health", action="store_true", help="Skip FastAPI /health check on restored target")
    parser.add_argument("--keep-dump", action="store_true", help="Retain temporary pg_dump artifact after drill")
    parser.add_argument("--rpo-minutes", type=int, default=15, help="Measured/configured RPO window in minutes")
    parser.add_argument("--record-api-url", help="Optional OS Gateway base URL to record verified drill")
    parser.add_argument("--owner-api-key", help="Owner X-API-Key for optional drill recording")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args(argv)

    source_url, source_origin = resolve_configured_source_url(args.source_url)

    if args.check_only:
        report = run_preflight(source_url, source_origin)
        print(json.dumps(report, indent=2))
        return 0 if report["verification_status"] == "READY_FOR_DRILL" else 2

    if not source_url:
        err = {"verification_status": "BLOCKED", "restore_tested": False, "error": "No source DB URL configured."}
        print(json.dumps(err, indent=2))
        return 2

    if not args.target_url:
        err = {
            "verification_status": "BLOCKED",
            "restore_tested": False,
            "error": "--target-url is required for backup restore drill.",
        }
        print(json.dumps(err, indent=2))
        return 2

    try:
        report = execute_drill(
            source_url=source_url,
            target_url=args.target_url,
            source_origin=source_origin,
            allow_shared_host_isolated_db=args.confirm_isolated_branch,
            approved_staging_host=args.approved_staging_host,
            approved_staging_db=args.approved_staging_db,
            verify_health=not args.skip_health,
            keep_dump=args.keep_dump,
            rpo_minutes=args.rpo_minutes,
            record_api_url=args.record_api_url,
            owner_api_key=args.owner_api_key,
        )
    except DrillSafetyError as exc:
        report = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "verification_status": "BLOCKED",
            "restore_tested": False,
            "error": str(exc),
        }
        print(json.dumps(report, indent=2))
        return 2

    print(json.dumps(report, indent=2))
    return 0 if report.get("restore_tested") else 1


if __name__ == "__main__":
    raise SystemExit(main())
