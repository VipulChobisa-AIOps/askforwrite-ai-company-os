"""Execution guard, simulation sandbox controls, SSRF/tool allowlist checks, and 4-level emergency stop."""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.db.models import EmergencyStopRecord

VALID_EXECUTION_MODES = ("SIMULATION", "SANDBOX", "PRODUCTION")
STOP_SCOPE_LEVELS = ("execution", "agent", "tenant", "platform")

# Recorded synthetic external dispatches captured in SIMULATION mode (zero real external side effects)
_SIMULATION_DISPATCH_SINK: list[dict[str, Any]] = []
_CURRENT_EXECUTION_MODE: ContextVar[str | None] = ContextVar("afw_execution_mode", default=None)

SECRET_FIELD_PATTERNS = re.compile(
    r"(api_?key|secret|password|passwd|token|private_?key|webhook_?secret|authorization|credential)",
    re.IGNORECASE,
)
RAW_SECRET_VALUE_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z\-_]{10,}"),
    re.compile(r"rzp_(live|test)_[0-9A-Za-z]{6,}"),
    re.compile(r"sk-[0-9A-Za-z\-_]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-_\.]{12,}", re.IGNORECASE),
)


class ExecutionBlockedError(RuntimeError):
    """Raised when execution is blocked by emergency stop, mode lock, SSRF check, or tool policy."""

    def __init__(self, reason: str, code: str = "EXECUTION_BLOCKED") -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


def redact_secrets(value: Any, _depth: int = 0) -> Any:
    """Recursively redact sensitive keys and raw API key/token strings."""
    if _depth > 8:
        return "[REDACTED_DEPTH_LIMIT]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for k, v in value.items():
            key_str = str(k)
            if SECRET_FIELD_PATTERNS.search(key_str) and not key_str.endswith("_masked") and not key_str.startswith("has_"):
                if v is None or v == "":
                    sanitized[key_str] = None
                elif isinstance(v, bool):
                    sanitized[key_str] = v
                else:
                    s_val = str(v)
                    sanitized[key_str] = f"••••{s_val[-4:]}" if len(s_val) >= 6 else "••••"
            else:
                sanitized[key_str] = redact_secrets(v, _depth + 1)
        return sanitized
    if isinstance(value, list):
        return [redact_secrets(item, _depth + 1) for item in value]
    if isinstance(value, str):
        out = value
        for pat in RAW_SECRET_VALUE_PATTERNS:
            out = pat.sub("[REDACTED_SECRET]", out)
        return out
    return value


def is_external_side_effect_blocked() -> bool:
    """Return True if staging/test/simulation lock prohibits real external network or SMTP side effects."""
    app_env = os.environ.get("APP_ENV", "development").strip().lower()
    ext_flag = os.environ.get("ENABLE_EXTERNAL_SIDE_EFFECTS", "").strip().lower()
    sim_only = os.environ.get("SIMULATION_ONLY", "").strip().lower()
    if ext_flag in ("0", "false", "no") or sim_only in ("1", "true", "yes"):
        return True
    if app_env in ("staging", "test", "testing", "simulation"):
        return True
    if "pytest" in sys.modules or "unittest" in sys.modules:
        return os.environ.get("ALLOW_LIVE_IN_TEST", "").strip().lower() not in ("1", "true", "yes")
    return False


def resolve_execution_mode(requested_mode: str | None = None) -> str:
    """Resolve canonical execution mode: SIMULATION, SANDBOX, or PRODUCTION."""
    ctx_mode = _CURRENT_EXECUTION_MODE.get()
    raw = (requested_mode or ctx_mode or os.environ.get("DEFAULT_EXECUTION_MODE") or "").strip().upper()
    if raw in VALID_EXECUTION_MODES:
        return raw
    if is_external_side_effect_blocked():
        return "SIMULATION"
    if os.environ.get("APP_ENV", "").strip().lower() == "production":
        return "PRODUCTION"
    return "SIMULATION"


def record_simulated_dispatch(channel: str, target: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Capture synthetic external dispatches in SIMULATION mode instead of calling external APIs."""
    entry = {
        "dispatch_id": f"sim-{uuid.uuid4().hex[:12]}",
        "channel": channel,
        "target": target,
        "payload": redact_secrets(payload),
        "simulated": True,
        "external_network_called": False,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    _SIMULATION_DISPATCH_SINK.append(entry)
    return entry


def get_simulation_dispatch_sink(limit: int = 50) -> list[dict[str, Any]]:
    """Return captured simulation-mode external dispatches."""
    return list(_SIMULATION_DISPATCH_SINK[-limit:])


def clear_simulation_dispatch_sink() -> None:
    """Reset the in-memory simulation dispatch sink (used in tests)."""
    _SIMULATION_DISPATCH_SINK.clear()


def validate_external_url(url: str, *, allow_domains: set[str] | None = None) -> str:
    """Validate an outbound HTTP(S) URL against SSRF, private IPs, and disallowed schemes."""
    raw = (url or "").strip()
    if not raw:
        raise ExecutionBlockedError("URL cannot be empty", code="SSRF_INVALID_URL")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ExecutionBlockedError(f"Blocked disallowed URL scheme '{parsed.scheme}'", code="SSRF_DISALLOWED_SCHEME")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ExecutionBlockedError("Blocked URL with missing hostname", code="SSRF_INVALID_HOST")
    if host in ("localhost", "127.0.0.1", "::1", "169.254.169.254", "metadata.google.internal"):
        raise ExecutionBlockedError(f"Blocked SSRF internal/metadata host '{host}'", code="SSRF_BLOCKED_HOST")

    # Direct IP literal check (covers private, loopback, unspecified 0.0.0.0/::, link-local, reserved, multicast)
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_unspecified or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ExecutionBlockedError(f"Blocked non-public IP address '{host}'", code="SSRF_PRIVATE_IP")
    except ValueError:
        # Hostname — perform best-effort DNS check without breaking deterministic offline environments
        if host.endswith((".local", ".internal", ".localhost")):
            raise ExecutionBlockedError(f"Blocked internal hostname '{host}'", code="SSRF_INTERNAL_DOMAIN")
        try:
            infos = socket.getaddrinfo(host, None)
            for info in infos:
                addr = info[4][0]
                ip_obj = ipaddress.ip_address(addr)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_unspecified or ip_obj.is_link_local or ip_obj.is_reserved:
                    raise ExecutionBlockedError(f"Blocked host '{host}' resolving to private IP '{addr}'", code="SSRF_DNS_PRIVATE")
        except socket.gaierror:
            # DNS resolution offline or synthetic test domain: allow domain format check unless private suffix
            pass

    if allow_domains is not None and host not in {d.lower() for d in allow_domains}:
        raise ExecutionBlockedError(f"Host '{host}' is not in connector allowlist", code="HOST_NOT_ALLOWLISTED")
    return raw


def set_emergency_stop(
    db: Session,
    *,
    scope_level: str,
    scope_target: str,
    state: str,
    reason: str,
    triggered_by: str,
    org_id: str | None = None,
) -> dict[str, Any]:
    """Persist and enforce 4-level emergency stop / pause state (execution, agent, tenant, platform)."""
    clean_level = scope_level.strip().lower()
    if clean_level not in STOP_SCOPE_LEVELS:
        raise ValueError(f"Invalid scope_level '{scope_level}'. Must be one of {STOP_SCOPE_LEVELS}")
    clean_state = state.strip().upper()
    if clean_state not in ("ACTIVE", "PAUSED", "EMERGENCY_STOPPED"):
        raise ValueError(f"Invalid control state '{state}'. Must be ACTIVE, PAUSED, or EMERGENCY_STOPPED")
    clean_target = (scope_target or "*").strip()

    # Deactivate prior active controls on the exact same scope
    existing = (
        db.query(EmergencyStopRecord)
        .filter_by(scope_level=clean_level, scope_target=clean_target, org_id=org_id, is_active=True)
        .all()
    )
    for row in existing:
        row.is_active = False

    now = datetime.now(UTC)
    new_active = clean_state in ("PAUSED", "EMERGENCY_STOPPED")
    rec = EmergencyStopRecord(
        scope_level=clean_level,
        scope_target=clean_target,
        org_id=org_id,
        state=clean_state,
        reason=reason,
        triggered_by=triggered_by,
        is_active=new_active,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.flush()

    # Sync legacy in-memory dict in watchdog.py for seamless P0 interoperability
    try:
        from app.services.watchdog import AGENT_RUNTIME_CONTROLS

        mem_key = "__all__" if (clean_level == "platform" or clean_target == "*") else clean_target.lower()
        AGENT_RUNTIME_CONTROLS[mem_key] = {
            "agent_key": mem_key,
            "state": clean_state,
            "reason": reason,
            "updated_by": triggered_by,
            "updated_at": now.isoformat(),
            "scope_level": clean_level,
            "org_id": org_id,
        }
    except Exception:
        # Watchdog sync failure must not prevent DB persistence; log via caller if needed
        pass

    return {
        "stop_id": rec.id,
        "scope_level": clean_level,
        "scope_target": clean_target,
        "org_id": org_id,
        "state": clean_state,
        "is_active": new_active,
        "reason": reason,
        "triggered_by": triggered_by,
        "updated_at": now.isoformat(),
    }


def list_active_emergency_stops(db: Session, org_id: str | None = None) -> list[dict[str, Any]]:
    """List currently active emergency stop / pause records visible to org or platform."""
    q = db.query(EmergencyStopRecord).filter_by(is_active=True)
    if org_id:
        q = q.filter((EmergencyStopRecord.org_id == org_id) | (EmergencyStopRecord.scope_level == "platform"))
    rows = q.order_by(EmergencyStopRecord.created_at.desc()).all()
    return [
        {
            "stop_id": r.id,
            "scope_level": r.scope_level,
            "scope_target": r.scope_target,
            "org_id": r.org_id,
            "state": r.state,
            "reason": r.reason,
            "triggered_by": r.triggered_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def check_execution_allowed(
    db: Session,
    *,
    execution_id: str | None = None,
    agent_id: str | None = None,
    org_id: str | None = None,
    execution_mode: str = "SIMULATION",
    requested_tools: list[str] | None = None,
    agent_supported_tools: list[str] | None = None,
    tenant_tool_allowlist: list[str] | None = None,
) -> None:
    """Enforce 4-level emergency stop, simulation-to-production lock, and least-privilege tool allowlists."""
    mode = execution_mode.strip().upper()
    if mode not in VALID_EXECUTION_MODES:
        raise ExecutionBlockedError(f"Unsupported execution_mode '{execution_mode}'", code="INVALID_MODE")

    if mode == "PRODUCTION" and is_external_side_effect_blocked():
        raise ExecutionBlockedError(
            "PRODUCTION mode is blocked while simulation/staging isolation is active (ENABLE_EXTERNAL_SIDE_EFFECTS=false).",
            code="SIMULATION_MODE_LOCK",
        )

    # Check persistent 4-level DB stops
    active_stops = db.query(EmergencyStopRecord).filter_by(is_active=True).all()
    for s in active_stops:
        if s.scope_level == "platform":
            raise ExecutionBlockedError(
                f"Platform-wide emergency control active ({s.state}): {s.reason}",
                code="EMERGENCY_STOP_PLATFORM",
            )
        if org_id and s.scope_level == "tenant" and (s.scope_target == org_id or s.org_id == org_id):
            raise ExecutionBlockedError(
                f"Tenant '{org_id}' execution is {s.state}: {s.reason}",
                code="EMERGENCY_STOP_TENANT",
            )
        if agent_id and s.scope_level == "agent" and s.scope_target == agent_id:
            if s.org_id is None or s.org_id == org_id:
                raise ExecutionBlockedError(
                    f"Agent '{agent_id}' is {s.state}: {s.reason}",
                    code="EMERGENCY_STOP_AGENT",
                )
        if execution_id and s.scope_level == "execution" and s.scope_target == execution_id:
            raise ExecutionBlockedError(
                f"Execution '{execution_id}' is {s.state}: {s.reason}",
                code="EMERGENCY_STOP_EXECUTION",
            )

    # Sync check against legacy in-memory watchdog controls if not present in DB
    try:
        from app.services.watchdog import AGENT_RUNTIME_CONTROLS

        for key in ("__all__", (agent_id or "").lower()):
            entry = AGENT_RUNTIME_CONTROLS.get(key)
            if entry and entry.get("state") in ("PAUSED", "EMERGENCY_STOPPED"):
                ctrl_org = entry.get("org_id")
                if ctrl_org is None or ctrl_org == org_id:
                    raise ExecutionBlockedError(
                        f"Agent '{key}' is {entry['state']}: {entry.get('reason', 'operator control')}",
                        code="EMERGENCY_STOP_LEGACY",
                    )
    except ImportError:
        pass

    # Least-privilege tool allowlist verification
    if requested_tools:
        supported = set(agent_supported_tools or [])
        for tool in requested_tools:
            if supported and tool not in supported:
                raise ExecutionBlockedError(
                    f"Tool '{tool}' is not in agent '{agent_id}' supported tool allowlist",
                    code="TOOL_NOT_SUPPORTED",
                )
            if tenant_tool_allowlist is not None and len(tenant_tool_allowlist) > 0 and tool not in tenant_tool_allowlist:
                raise ExecutionBlockedError(
                    f"Tool '{tool}' is restricted by tenant agent allowlist policy",
                    code="TOOL_NOT_ALLOWED_FOR_TENANT",
                )

