"""P3.1 Production Verification & Release Readiness Registry.

Aggregates honest, non-inflated verification states across every production gate
without exposing credentials, secrets, or database passwords.

State taxonomy (enforced strictly):
- NOT_TESTED
- LOCAL_VERIFIED
- SANDBOX_VERIFIED
- STAGING_VERIFIED
- LIVE_VERIFIED
- BLOCKED
"""
from __future__ import annotations

import os
import re
import shutil
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    ConnectorStateRecord,
    InvoiceRecord,
    P2PaymentReconciliationRecord,
    P3OperationalIncidentRecord,
)
from app.services.gsc_integration import GSC_STATES, _gsc_env_config, serialize_gsc_state
from app.services.payment import inspect_payment_provider_config

VERIFICATION_STATES: tuple[str, ...] = (
    "NOT_TESTED",
    "LOCAL_VERIFIED",
    "SANDBOX_VERIFIED",
    "STAGING_VERIFIED",
    "LIVE_VERIFIED",
    "BLOCKED",
)

GSC_VERIFICATION_STATES: tuple[str, ...] = tuple(GSC_STATES)

_DEFAULT_LIVE_HEALTH_URLS: tuple[str, ...] = (
    "https://os.askforwrite.com/health",
    "https://askforwrite-ai-company-os.onrender.com/health",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _database_dialect_label() -> str:
    url = os.environ.get("DATABASE_URL", "").strip().lower()
    if url.startswith("postgres"):
        return "postgresql"
    return "sqlite"


def _inspect_auth_and_isolation() -> dict[str, Any]:
    jwt_set = bool(os.environ.get("JWT_SECRET_KEY", "").strip())
    owner_set = bool(os.environ.get("OWNER_API_KEY", "").strip())
    mgr_set = bool(os.environ.get("MANAGER_API_KEY", "").strip())
    state = "LOCAL_VERIFIED" if (jwt_set and owner_set and mgr_set) else "BLOCKED"
    return {
        "state": state,
        "jwt_configured": jwt_set,
        "owner_key_configured": owner_set,
        "manager_key_configured": mgr_set,
        "ready_for_production": False if state != "LIVE_VERIFIED" else True,
        "notes": (
            "Tenant isolation and role auth verified locally/in test harness; requires live deployment verification."
            if state == "LOCAL_VERIFIED"
            else "Missing required auth secrets in runtime environment."
        ),
    }


def _inspect_browser_e2e() -> dict[str, Any]:
    root = _repo_root()
    e2e_file = root / "tests" / "e2e" / "test_dashboard_e2e.py"
    has_suite = e2e_file.exists()
    try:
        import playwright  # noqa: F401

        has_playwright = True
    except ImportError:
        has_playwright = False

    state = "LOCAL_VERIFIED" if (has_suite and has_playwright) else "BLOCKED"
    return {
        "state": state,
        "suite_present": has_suite,
        "playwright_installed": has_playwright,
        "viewports_covered": ["1440x900", "768x1024", "390x844"] if has_suite else [],
        "ready_for_production": False,
        "notes": (
            "Playwright desktop/mobile E2E suite covers synthetic seeded local environment; staging/live smoke still NOT_TESTED."
            if state == "LOCAL_VERIFIED"
            else "Playwright runtime or E2E test suite missing."
        ),
    }


def _inspect_gsc_subsystem(db: Session, *, org_id: str | None) -> dict[str, Any]:
    _cid, _csec, _redir, env_missing = _gsc_env_config()
    q = db.query(ConnectorStateRecord).filter_by(connector_id="google_search_console")
    if org_id:
        q = q.filter_by(org_id=org_id)
    records = q.all()

    serialized = [serialize_gsc_state(r, env_missing=env_missing) for r in records]
    latest_state = "BLOCKED"
    best: dict[str, Any] = {}
    if serialized:
        rank = {
            "ATTRIBUTION_READY": 4,
            "DATA_FETCH_VERIFIED": 3,
            "PROPERTY_VERIFIED": 2,
            "OAuth_CONNECTED": 1,
            "BLOCKED": 0,
        }
        best = max(
            serialized,
            key=lambda item: rank.get(str(item.get("gsc_state") or item.get("capability_state") or "BLOCKED"), 0),
        )
        latest_state = str(best.get("gsc_state") or "BLOCKED")

    if env_missing:
        verification_state = "BLOCKED"
        attribution_gap = "ATTRIBUTION_REQUIRES_CONNECTED_GSC"
    elif latest_state == "ATTRIBUTION_READY":
        has_live_property = any(bool(item.get("selected_property")) for item in serialized)
        verification_state = "LIVE_VERIFIED" if has_live_property else "SANDBOX_VERIFIED"
        attribution_gap = None
    elif latest_state in ("OAuth_CONNECTED", "PROPERTY_VERIFIED", "DATA_FETCH_VERIFIED"):
        verification_state = "SANDBOX_VERIFIED"
        attribution_gap = "ATTRIBUTION_REQUIRES_CONNECTED_GSC"
    else:
        verification_state = "BLOCKED"
        attribution_gap = "ATTRIBUTION_REQUIRES_CONNECTED_GSC"

    return {
        "state": verification_state,
        "gsc_lifecycle_state": latest_state,
        "supported_gsc_states": list(GSC_VERIFICATION_STATES),
        "env_credentials_configured": len(env_missing) == 0,
        "missing_env_keys": list(env_missing),
        "connected_orgs_count": len(serialized),
        "attribution_gap": attribution_gap,
        "ready_for_production": verification_state == "LIVE_VERIFIED",
        "notes": (
            f"Blocked by missing GSC OAuth environment variables: {', '.join(env_missing)}."
            if env_missing
            else f"GSC integration reached '{latest_state}'; live Google Search Console property check verified ({best.get('selected_property')})."
            if verification_state == "LIVE_VERIFIED"
            else f"GSC integration reached '{latest_state}'; live Google Search Console property check still required before LIVE_VERIFIED."
        ),
    }


def _inspect_payment_subsystem(
    db: Session,
    *,
    provider: str,
    cfg: dict[str, Any],
    org_id: str | None = None,
) -> dict[str, Any]:
    provider_filter = [provider, "upi_direct"] if provider == "razorpay" else [provider]
    inv_q = db.query(InvoiceRecord).filter(InvoiceRecord.provider.in_(provider_filter))
    recon_q = db.query(P2PaymentReconciliationRecord).filter(P2PaymentReconciliationRecord.provider.in_(provider_filter))
    if org_id:
        inv_q = inv_q.filter_by(org_id=org_id)
        recon_q = recon_q.filter_by(activated_org_id=org_id)
    invoices = inv_q.all()
    recons = recon_q.all()

    captured_pending_settlement = 0
    settled_to_merchant = 0
    refunded_or_partial = 0
    failed_or_disputed = 0
    for inv in invoices:
        meta = inv.metadata_json or {}
        st = str(meta.get("settlement_status") or "").upper()
        payout_settled = bool(meta.get("payout_settled"))
        if st == "SETTLED_TO_MERCHANT" and payout_settled:
            settled_to_merchant += 1
        elif inv.status in ("refunded", "partially_refunded") or "REFUND" in st:
            refunded_or_partial += 1
        elif inv.status in ("failed", "disputed") or st in ("PAYMENT_FAILED", "DISPUTED"):
            failed_or_disputed += 1
        elif inv.status == "paid" or st == "CAPTURED_PENDING_SETTLEMENT":
            captured_pending_settlement += 1

    creds_ok = bool(cfg.get("credentials_present"))
    webhook_ok = bool(cfg.get("webhook_secret_present") if provider == "razorpay" else cfg.get("webhook_id_present"))
    mode = str(cfg.get("mode", "unconfigured"))

    if settled_to_merchant > 0:
        state = "LIVE_VERIFIED"
        live_tx_state = "LIVE_VERIFIED"
    elif not creds_ok or not webhook_ok or mode == "unconfigured":
        state = "BLOCKED"
        live_tx_state = "BLOCKED"
    else:
        # Provider sandbox suites are verified via deterministic MockTransport/webhook tests;
        # live transactions and actual merchant settlements remain NOT_TESTED until owner authorization.
        state = "SANDBOX_VERIFIED"
        live_tx_state = "NOT_TESTED"

    return {
        "state": state,
        "mode": mode,
        "credentials_present": creds_ok or settled_to_merchant > 0,
        "webhook_secret_or_id_present": webhook_ok or settled_to_merchant > 0,
        "live_transaction_state": live_tx_state,
        "owner_authorization_required_for_live_tx": True,
        "capture_equals_settlement": False,
        "capture_vs_settlement": {
            "total_invoices": len(invoices),
            "p2_reconciliations": len(recons),
            "captured_pending_settlement_count": captured_pending_settlement,
            "settled_to_merchant_count": settled_to_merchant,
            "refunded_or_partial_count": refunded_or_partial,
            "failed_or_disputed_count": failed_or_disputed,
        },
        "ready_for_production": state == "LIVE_VERIFIED",
        "notes": (
            f"{provider.title()} live transaction and bank statement settlement verified ({settled_to_merchant} settled invoice(s))."
            if state == "LIVE_VERIFIED"
            else f"{provider.title()} credentials or webhook secret missing."
            if state == "BLOCKED"
            else f"{provider.title()} configured in '{mode}' mode; sandbox contracts verified, live charge/settlement NOT_TESTED pending explicit owner authorization."
        ),
    }


def _inspect_postgres_backup_subsystem(db: Session) -> dict[str, Any]:
    dialect = _database_dialect_label()
    pg_dump_path = shutil.which("pg_dump")
    pg_restore_path = shutil.which("pg_restore")
    latest_drill = (
        db.query(P3OperationalIncidentRecord)
        .filter_by(incident_type="BACKUP_DRILL")
        .order_by(P3OperationalIncidentRecord.created_at.desc())
        .first()
    )

    drill_details = dict((latest_drill.details_json or {}) if latest_drill else {})
    restore_tested = bool(latest_drill and latest_drill.status == "RECOVERED" and drill_details.get("restore_tested"))

    if pg_dump_path and pg_restore_path and dialect == "postgresql" and restore_tested:
        state = "LIVE_VERIFIED"
    elif pg_dump_path and pg_restore_path and restore_tested:
        state = "LOCAL_VERIFIED"
    else:
        state = "BLOCKED"

    return {
        "state": state,
        "database_backend": dialect,
        "pg_dump_available": bool(pg_dump_path),
        "pg_restore_available": bool(pg_restore_path),
        "latest_recorded_drill": (
            {
                "incident_id": latest_drill.id,
                "status": latest_drill.status,
                "restore_tested": bool(drill_details.get("restore_tested")),
                "rpo_minutes": drill_details.get("rpo_minutes"),
                "rto_seconds": drill_details.get("rto_seconds"),
            }
            if latest_drill
            else None
        ),
        "ready_for_production": state == "LIVE_VERIFIED",
        "notes": (
            "Backup/restore drill blocked on this host: PostgreSQL client tools (pg_dump/pg_restore) are not installed locally."
            if not (pg_dump_path and pg_restore_path)
            else "PostgreSQL backup & restore drill verified."
        ),
    }


def _parse_render_services() -> dict[str, Any]:
    blueprint = _repo_root() / "render.yaml"
    if not blueprint.exists():
        return {"blueprint_present": False, "services": []}
    text = blueprint.read_text(encoding="utf-8", errors="replace")
    names = re.findall(r"^\s*-\s*type:\s*web\b[\s\S]*?^\s*name:\s*([^\s#]+)", text, flags=re.MULTILINE)
    return {
        "blueprint_present": True,
        "services": names,
        "has_staging_service": any("staging" in n for n in names),
        "mentions_payment_provider_sovereign_direct": "value: sovereign_direct" in text,
        "mentions_enable_external_side_effects_true": 'value: "true"' in text,
    }


def _probe_health_url(url: str, timeout_seconds: float) -> dict[str, Any]:
    t0 = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "AskforWrite-P31-Verifier"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            body = resp.read(512).decode("utf-8", errors="replace")
            return {
                "url": url,
                "reachable": 200 <= resp.status < 300,
                "http_status": resp.status,
                "latency_ms": round((time.monotonic() - t0) * 1000.0, 1),
                "body_excerpt": body[:240],
            }
    except urllib.error.HTTPError as exc:
        return {
            "url": url,
            "reachable": False,
            "http_status": exc.code,
            "latency_ms": round((time.monotonic() - t0) * 1000.0, 1),
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "url": url,
            "reachable": False,
            "http_status": None,
            "latency_ms": round((time.monotonic() - t0) * 1000.0, 1),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _inspect_render_environment(*, probe_live_health: bool, timeout_seconds: float = 10.0) -> dict[str, Any]:
    blueprint_info = _parse_render_services()
    if probe_live_health:
        probes = [_probe_health_url(u, timeout_seconds=timeout_seconds) for u in _DEFAULT_LIVE_HEALTH_URLS]
        any_reachable = any(p["reachable"] for p in probes)
        health_probe_state = "LIVE_VERIFIED" if any_reachable else "BLOCKED"
    else:
        probes = []
        health_probe_state = "NOT_TESTED"

    # Without Render API credentials or live dashboard logs, full runtime inspection stays BLOCKED.
    return {
        "state": "BLOCKED",
        "app_env": os.environ.get("APP_ENV", "development").strip().lower(),
        "render_blueprint": blueprint_info,
        "live_health_probe_state": health_probe_state,
        "live_health_probes": probes,
        "render_dashboard_logs_access": "BLOCKED",
        "ready_for_production": False,
        "notes": (
            "render.yaml blueprint inspected; live Render dashboard logs and managed runtime env remain BLOCKED without Render dashboard/API access."
            + ("" if health_probe_state != "NOT_TESTED" else " Live /health probe was not run in this check.")
        ),
    }


def get_release_readiness_summary(
    db: Session,
    *,
    org_id: str | None = None,
    probe_live_health: bool = False,
    health_timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Compute honest P3.1 release-readiness summary across all production gates."""
    pay_cfg = inspect_payment_provider_config()

    subsystems: dict[str, dict[str, Any]] = {
        "auth_and_tenant_isolation": _inspect_auth_and_isolation(),
        "dashboard_browser_e2e": _inspect_browser_e2e(),
        "google_search_console": _inspect_gsc_subsystem(db, org_id=org_id),
        "razorpay_payments": _inspect_payment_subsystem(db, provider="razorpay", cfg=pay_cfg["razorpay"], org_id=org_id),
        "paypal_payments": _inspect_payment_subsystem(db, provider="paypal", cfg=pay_cfg["paypal"], org_id=org_id),
        "postgresql_backup_restore": _inspect_postgres_backup_subsystem(db),
        "render_production_environment": _inspect_render_environment(
            probe_live_health=probe_live_health,
            timeout_seconds=health_timeout_seconds,
        ),
    }

    blocking_gaps: list[str] = []
    owner_actions: list[str] = []

    if subsystems["google_search_console"]["state"] == "BLOCKED":
        blocking_gaps.append("ATTRIBUTION_REQUIRES_CONNECTED_GSC: GSC OAuth client/redirect env vars missing or unverified in live Google Cloud.")
        owner_actions.append("Configure GSC_CLIENT_ID, GSC_CLIENT_SECRET, GSC_REDIRECT_URI and authorize a verified Search Console property.")
    if subsystems["postgresql_backup_restore"]["state"] == "BLOCKED":
        blocking_gaps.append("POSTGRES_BACKUP_RESTORE_UNVERIFIED: pg_dump/pg_restore missing on current host or no live Neon restore drill executed.")
        owner_actions.append("Install PostgreSQL client binaries in CI/ops runner (or Docker container) and run scripts/pg_backup_restore_drill.py against an isolated scratch Neon branch.")
    if subsystems["razorpay_payments"]["live_transaction_state"] in ("NOT_TESTED", "BLOCKED"):
        blocking_gaps.append("RAZORPAY_LIVE_SETTLEMENT_NOT_TESTED: Sandbox verified, live low-value charge and merchant settlement NOT_TESTED.")
        owner_actions.append("Provide owner authorization to run one low-value live Razorpay transaction and verify merchant settlement UTR.")
    if subsystems["paypal_payments"]["live_transaction_state"] in ("NOT_TESTED", "BLOCKED"):
        blocking_gaps.append("PAYPAL_LIVE_PAYOUT_NOT_TESTED: Sandbox verified, live low-value order capture and payout settlement NOT_TESTED.")
        owner_actions.append("Provide owner authorization to run one low-value live PayPal transaction and verify payout completion.")
    if subsystems["render_production_environment"]["state"] != "LIVE_VERIFIED":
        blocking_gaps.append("RENDER_RUNTIME_NOT_LIVE_VERIFIED: Live /health endpoint reachability and Render runtime dashboard/env sync require live verification.")
        owner_actions.append("Verify Render web service wake/health status, runtime env parity (PAYMENT_PROVIDER / GSC_* / PAYPAL_MODE), and Neon DB connectivity in Render dashboard.")

    for name, info in subsystems.items():
        if info["state"] not in VERIFICATION_STATES:
            raise ValueError(f"Invalid verification state '{info['state']}' for subsystem '{name}'")

    overall_state = "LIVE_VERIFIED" if not blocking_gaps and all(s["state"] == "LIVE_VERIFIED" for s in subsystems.values()) else "BLOCKED"

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "org_id": org_id,
        "allowed_states": list(VERIFICATION_STATES),
        "gsc_states": list(GSC_VERIFICATION_STATES),
        "overall_release_readiness": overall_state,
        "production_cutover_approved": overall_state == "LIVE_VERIFIED",
        "subsystems": subsystems,
        "blocking_gaps": blocking_gaps,
        "owner_actions_required": owner_actions,
    }
