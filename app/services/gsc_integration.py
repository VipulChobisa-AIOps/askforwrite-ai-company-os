"""Google Search Console (GSC) OAuth 2.0, Property Verification, Search Analytics & Attribution Service."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import AuditLog, ConnectorStateRecord
from app.services.execution_guard import is_external_side_effect_blocked, redact_secrets

logger = logging.getLogger(__name__)

GSC_CONNECTOR_ID = "google_search_console"
GSC_READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GSC_SUPPORTED_SCOPES = frozenset({
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/webmasters",
})
GSC_VALID_DIMENSIONS = frozenset({"query", "page", "date", "country", "device", "searchAppearance"})
GSC_VERIFIED_PERMISSIONS = frozenset({"siteOwner", "siteFullUser", "siteRestrictedUser"})

GSC_STATES = (
    "OAuth_CONNECTED",
    "PROPERTY_VERIFIED",
    "DATA_FETCH_VERIFIED",
    "ATTRIBUTION_READY",
    "BLOCKED",
)

GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_GSC_API_BASE = "https://www.googleapis.com/webmasters/v3"


class GscIntegrationError(RuntimeError):
    """Structured non-2xx / blocked error for Google Search Console operations."""

    def __init__(self, message: str, *, code: str = "GSC_BLOCKED", status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def _derive_fernet() -> Fernet:
    """Derive a deterministic Fernet cipher from environment master secrets."""
    raw_secret = (
        os.environ.get("GSC_TOKEN_ENCRYPTION_KEY", "").strip()
        or os.environ.get("JWT_SECRET_KEY", "").strip()
        or os.environ.get("OWNER_API_KEY", "").strip()
        or "afw-local-development-fallback-gsc-seal"
    )
    digest = hashlib.sha256(f"afw-gsc-token-v1:{raw_secret}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_vault_bundle(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _derive_fernet().encrypt(serialized).decode("ascii")


def _decrypt_vault_bundle(cipher_text: str | None) -> dict[str, Any]:
    if not cipher_text:
        return {}
    try:
        raw = _derive_fernet().decrypt(cipher_text.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise GscIntegrationError(
            "Stored GSC OAuth credentials could not be decrypted; re-authorization is required.",
            code="GSC_CREDENTIALS_UNREADABLE",
            status_code=409,
        ) from exc


def _gsc_env_config(redirect_uri_override: str | None = None) -> tuple[str, str, str, list[str]]:
    client_id = os.environ.get("GSC_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GSC_CLIENT_SECRET", "").strip()
    redirect_uri = (redirect_uri_override or os.environ.get("GSC_REDIRECT_URI", "")).strip()
    missing: list[str] = []
    if not client_id or client_id.startswith("mock-"):
        missing.append("GSC_CLIENT_ID")
    if not client_secret or client_secret.startswith("mock-"):
        missing.append("GSC_CLIENT_SECRET")
    if not redirect_uri:
        missing.append("GSC_REDIRECT_URI")
    return client_id, client_secret, redirect_uri, missing


def _validate_redirect_uri(redirect_uri: str) -> str:
    clean = (redirect_uri or "").strip()
    parsed = urlparse(clean)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise GscIntegrationError("Invalid OAuth redirect_uri.", code="GSC_INVALID_REDIRECT_URI", status_code=422)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in ("localhost", "127.0.0.1"):
        raise GscIntegrationError(
            "Non-local GSC redirect_uri must use HTTPS.",
            code="GSC_INSECURE_REDIRECT_URI",
            status_code=422,
        )
    return clean


def _get_or_create_gsc_record(db: Session, org_id: str) -> ConnectorStateRecord:
    rec = db.query(ConnectorStateRecord).filter_by(org_id=org_id, connector_id=GSC_CONNECTOR_ID).first()
    if rec is None:
        now = datetime.now(UTC)
        rec = ConnectorStateRecord(
            org_id=org_id,
            connector_id=GSC_CONNECTOR_ID,
            provider="Google Search Console API",
            service_category="seo_analytics_attribution",
            authentication_type="oauth2_authorization_code",
            environment="PRODUCTION" if not is_external_side_effect_blocked() else "SANDBOX",
            connection_status="NOT_CONNECTED",
            capability_state="BLOCKED",
            config_summary={
                "gsc_state": "BLOCKED",
                "has_access_cred": False,
                "has_refresh_cred": False,
                "selected_property": None,
                "property_permission": None,
                "granted_scopes": [],
                "token_expires_at": None,
                "has_baseline_attribution": False,
            },
            last_error="Google Search Console OAuth connection not yet completed.",
            version="1.0.0",
            created_at=now,
            updated_at=now,
        )
        db.add(rec)
        db.flush()
    return rec


def serialize_gsc_state(rec: ConnectorStateRecord | None, *, env_missing: list[str] | None = None) -> dict[str, Any]:
    """Serialize non-secret GSC connection & verification metadata (never exposes tokens or ciphertext)."""
    cfg = dict(rec.config_summary or {}) if rec else {}
    raw_state = str(cfg.get("gsc_state") or "BLOCKED")
    if raw_state not in GSC_STATES:
        raw_state = "BLOCKED"
    missing = env_missing if env_missing is not None else _gsc_env_config(cfg.get("redirect_uri"))[3]
    return {
        "org_id": rec.org_id if rec else None,
        "connector_id": GSC_CONNECTOR_ID,
        "gsc_state": raw_state,
        "capability_state": rec.capability_state if rec else "BLOCKED",
        "connection_status": rec.connection_status if rec else "NOT_CONNECTED",
        "oauth_configured": len(missing) == 0,
        "missing_env_vars": missing,
        "redirect_uri": cfg.get("redirect_uri"),
        "granted_scopes": list(cfg.get("granted_scopes") or []),
        "has_access_cred": bool(cfg.get("has_access_cred", False)),
        "has_refresh_cred": bool(cfg.get("has_refresh_cred", False)),
        "token_expires_at": cfg.get("token_expires_at"),
        "selected_property": cfg.get("selected_property"),
        "property_permission": cfg.get("property_permission"),
        "has_baseline_attribution": bool(cfg.get("has_baseline_attribution", False)),
        "latest_analytics_summary": redact_secrets(cfg.get("latest_analytics_summary") or {}),
        "last_verified_at": rec.last_verified_at.isoformat() if rec and rec.last_verified_at else None,
        "last_error": rec.last_error if rec else "Google Search Console OAuth connection not yet completed.",
    }


def get_gsc_status(db: Session, *, org_id: str) -> dict[str, Any]:
    rec = db.query(ConnectorStateRecord).filter_by(org_id=org_id, connector_id=GSC_CONNECTOR_ID).first()
    return serialize_gsc_state(rec)


def _record_gsc_audit(db: Session, *, actor: str, org_id: str, action: str, output_payload: dict[str, Any], status: str = "COMPLETED") -> None:
    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id=actor,
            capability_name="gsc_integration",
            action=action,
            input_payload={"org_id": org_id, "connector_id": GSC_CONNECTOR_ID},
            output_payload=redact_secrets(output_payload),
            status=status,
        )
    )


def _assert_live_call_allowed(http_client: httpx.Client | None) -> None:
    """Allow real Google HTTP calls only when external side effects are allowed OR an explicit injected client is used in tests."""
    if http_client is None and is_external_side_effect_blocked():
        raise GscIntegrationError(
            "Live Google Search Console HTTP calls are blocked under staging/simulation lock without an explicit test transport.",
            code="GSC_BLOCKED_BY_ENVIRONMENT_LOCK",
            status_code=409,
        )


def build_gsc_oauth_authorization_url(
    db: Session,
    *,
    org_id: str,
    redirect_uri: str | None = None,
    scopes: list[str] | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Generate a Google OAuth 2.0 consent URL with CSRF state nonce and validated redirect URI."""
    client_id, _secret, resolved_redirect, missing = _gsc_env_config(redirect_uri)
    if missing:
        rec = _get_or_create_gsc_record(db, org_id)
        cfg = dict(rec.config_summary or {})
        cfg["gsc_state"] = "BLOCKED"
        rec.config_summary = cfg
        rec.connection_status = "BLOCKED"
        rec.capability_state = "BLOCKED"
        rec.last_error = f"Missing required Google Search Console OAuth env var(s): {', '.join(missing)}"
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        db.commit()
        raise GscIntegrationError(
            rec.last_error,
            code="GSC_OAUTH_NOT_CONFIGURED",
            status_code=400,
        )

    clean_redirect = _validate_redirect_uri(resolved_redirect)
    requested_scopes = scopes or [GSC_READONLY_SCOPE]
    if not all(s in GSC_SUPPORTED_SCOPES for s in requested_scopes):
        raise GscIntegrationError(
            f"Unsupported GSC OAuth scope requested. Allowed: {sorted(GSC_SUPPORTED_SCOPES)}",
            code="GSC_INVALID_SCOPE",
            status_code=422,
        )

    state_nonce = secrets.token_urlsafe(24)
    state_hash = hashlib.sha256(state_nonce.encode("utf-8")).hexdigest()

    rec = _get_or_create_gsc_record(db, org_id)
    cfg = dict(rec.config_summary or {})
    cfg["oauth_state_hash"] = state_hash
    cfg["redirect_uri"] = clean_redirect
    cfg["requested_scopes"] = requested_scopes
    cfg["oauth_state_issued_at"] = datetime.now(UTC).isoformat()
    rec.config_summary = cfg
    rec.updated_at = datetime.now(UTC)
    flag_modified(rec, "config_summary")
    _record_gsc_audit(
        db,
        actor=actor,
        org_id=org_id,
        action="gsc_oauth_url_generated",
        output_payload={"redirect_uri": clean_redirect, "scopes": requested_scopes},
    )
    db.commit()

    params = {
        "client_id": client_id,
        "redirect_uri": clean_redirect,
        "response_type": "code",
        "scope": " ".join(requested_scopes),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state_nonce,
    }
    return {
        "org_id": org_id,
        "authorization_url": f"{GOOGLE_OAUTH_AUTH_URL}?{urlencode(params)}",
        "state": state_nonce,
        "redirect_uri": clean_redirect,
        "scopes": requested_scopes,
        "gsc_state": cfg.get("gsc_state", "BLOCKED"),
    }


def exchange_gsc_oauth_code(
    db: Session,
    *,
    org_id: str,
    code: str,
    state: str,
    redirect_uri: str | None = None,
    actor: str = "owner",
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Exchange OAuth authorization code for encrypted tokens; never logs tokens and checks scope grant."""
    _assert_live_call_allowed(http_client)
    client_id, client_secret, resolved_redirect, missing = _gsc_env_config(redirect_uri)
    if missing:
        raise GscIntegrationError(
            f"Missing required Google Search Console OAuth env var(s): {', '.join(missing)}",
            code="GSC_OAUTH_NOT_CONFIGURED",
            status_code=400,
        )
    clean_redirect = _validate_redirect_uri(resolved_redirect)
    if not code or not code.strip():
        raise GscIntegrationError("OAuth authorization code is required.", code="GSC_MISSING_CODE", status_code=422)

    rec = _get_or_create_gsc_record(db, org_id)
    cfg = dict(rec.config_summary or {})
    expected_state_hash = cfg.get("oauth_state_hash")
    if not expected_state_hash or not secrets.compare_digest(
        expected_state_hash, hashlib.sha256((state or "").encode("utf-8")).hexdigest()
    ):
        cfg["gsc_state"] = "BLOCKED"
        rec.config_summary = cfg
        rec.connection_status = "BLOCKED"
        rec.capability_state = "BLOCKED"
        rec.last_error = "OAuth state mismatch or missing state nonce."
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        db.commit()
        raise GscIntegrationError(rec.last_error, code="GSC_OAUTH_STATE_MISMATCH", status_code=400)

    expected_redirect = cfg.get("redirect_uri") or clean_redirect
    if clean_redirect != expected_redirect:
        raise GscIntegrationError(
            "Redirect URI mismatch against authorization request.",
            code="GSC_REDIRECT_URI_MISMATCH",
            status_code=400,
        )

    close_client = http_client is None
    client = http_client or httpx.Client(timeout=20.0)
    try:
        resp = client.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data={
                "code": code.strip(),
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": clean_redirect,
                "grant_type": "authorization_code",
            },
        )
    except httpx.HTTPError as exc:
        cfg["gsc_state"] = "BLOCKED"
        rec.config_summary = cfg
        rec.connection_status = "ERROR"
        rec.capability_state = "BLOCKED"
        rec.last_error = f"Google OAuth token exchange transport error: {exc}"
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        db.commit()
        raise GscIntegrationError(rec.last_error, code="GSC_TOKEN_EXCHANGE_HTTP_ERROR", status_code=502) from exc
    finally:
        if close_client:
            client.close()

    if resp.status_code != 200:
        err_desc = "Token exchange failed"
        try:
            body_err = resp.json()
            err_desc = str(body_err.get("error_description") or body_err.get("error") or err_desc)
        except Exception:
            pass
        cfg["gsc_state"] = "BLOCKED"
        rec.config_summary = cfg
        rec.connection_status = "ERROR"
        rec.capability_state = "BLOCKED"
        rec.last_error = f"Google OAuth token exchange rejected ({resp.status_code}): {err_desc}"
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        _record_gsc_audit(db, actor=actor, org_id=org_id, action="gsc_oauth_exchange_failed", output_payload={"error": rec.last_error}, status="FAILED")
        db.commit()
        raise GscIntegrationError(rec.last_error, code="GSC_TOKEN_EXCHANGE_REJECTED", status_code=400)

    token_data = resp.json()
    access_token = str(token_data.get("access_token") or "").strip()
    refresh_token = str(token_data.get("refresh_token") or "").strip()
    expires_in = int(token_data.get("expires_in") or 3600)
    granted_scopes = [s for s in str(token_data.get("scope") or "").split() if s]

    if not access_token or not any(s in GSC_SUPPORTED_SCOPES for s in granted_scopes):
        cfg["gsc_state"] = "BLOCKED"
        rec.config_summary = cfg
        rec.connection_status = "BLOCKED"
        rec.capability_state = "BLOCKED"
        rec.last_error = "OAuth response lacked valid Search Console access_token or webmasters scope."
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        db.commit()
        raise GscIntegrationError(rec.last_error, code="GSC_SCOPE_INSUFFICIENT", status_code=403)

    now = datetime.now(UTC)
    existing_vault: dict[str, Any] = {}
    if cfg.get("vault_cipher_payload"):
        try:
            existing_vault = _decrypt_vault_bundle(cfg["vault_cipher_payload"])
        except GscIntegrationError:
            existing_vault = {}

    final_refresh = refresh_token or str(existing_vault.get("refresh_token") or "")
    vault_payload = {
        "access_token": access_token,
        "refresh_token": final_refresh,
        "token_type": str(token_data.get("token_type") or "Bearer"),
    }
    expires_at = (now + timedelta(seconds=expires_in)).isoformat()

    cfg["vault_cipher_payload"] = _encrypt_vault_bundle(vault_payload)
    cfg.pop("oauth_state_hash", None)
    cfg["gsc_state"] = "OAuth_CONNECTED"
    cfg["has_access_cred"] = True
    cfg["has_refresh_cred"] = bool(final_refresh)
    cfg["granted_scopes"] = granted_scopes
    cfg["token_expires_at"] = expires_at
    cfg["redirect_uri"] = clean_redirect
    rec.config_summary = cfg
    rec.connection_status = "OAUTH_CONNECTED"
    # Critical truthfulness: OAuth connection alone does NOT prove attribution is ready
    rec.capability_state = "CONFIGURED_UNVERIFIED"
    rec.last_verified_at = now
    rec.last_error = None
    rec.updated_at = now
    flag_modified(rec, "config_summary")
    _record_gsc_audit(
        db,
        actor=actor,
        org_id=org_id,
        action="gsc_oauth_connected",
        output_payload={"gsc_state": "OAuth_CONNECTED", "scopes": granted_scopes, "has_refresh": bool(final_refresh)},
    )
    db.commit()
    db.refresh(rec)
    return serialize_gsc_state(rec)


def _refresh_access_token_if_needed(
    db: Session,
    rec: ConnectorStateRecord,
    *,
    force_refresh: bool = False,
    http_client: httpx.Client | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return a valid GSC access token, refreshing automatically when near expiry or expired."""
    cfg = dict(rec.config_summary or {})
    vault = _decrypt_vault_bundle(cfg.get("vault_cipher_payload"))
    access_token = str(vault.get("access_token") or "").strip()
    refresh_token = str(vault.get("refresh_token") or "").strip()
    if not access_token:
        raise GscIntegrationError(
            "Google Search Console account is disconnected; OAuth sign-in required.",
            code="GSC_NOT_CONNECTED",
            status_code=401,
        )

    needs_refresh = force_refresh
    exp_str = cfg.get("token_expires_at")
    if exp_str and not needs_refresh:
        try:
            exp_dt = datetime.fromisoformat(str(exp_str))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=UTC)
            if exp_dt <= datetime.now(UTC) + timedelta(seconds=60):
                needs_refresh = True
        except ValueError:
            needs_refresh = True

    if not needs_refresh:
        return access_token, cfg

    if not refresh_token:
        cfg["gsc_state"] = "BLOCKED"
        cfg["has_access_cred"] = False
        cfg.pop("vault_cipher_payload", None)
        rec.config_summary = cfg
        rec.connection_status = "BLOCKED"
        rec.capability_state = "BLOCKED"
        rec.last_error = "GSC access token expired and no refresh_token is stored."
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        db.commit()
        raise GscIntegrationError(rec.last_error, code="GSC_TOKEN_EXPIRED_NO_REFRESH", status_code=401)

    _assert_live_call_allowed(http_client)
    client_id, client_secret, _redir, missing = _gsc_env_config(cfg.get("redirect_uri"))
    if any(m in ("GSC_CLIENT_ID", "GSC_CLIENT_SECRET") for m in missing):
        raise GscIntegrationError(
            "GSC_CLIENT_ID and GSC_CLIENT_SECRET are required to refresh expired OAuth tokens.",
            code="GSC_OAUTH_NOT_CONFIGURED",
            status_code=400,
        )

    close_client = http_client is None
    client = http_client or httpx.Client(timeout=20.0)
    try:
        resp = client.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    except httpx.HTTPError as exc:
        cfg["gsc_state"] = "BLOCKED"
        rec.config_summary = cfg
        rec.connection_status = "ERROR"
        rec.capability_state = "BLOCKED"
        rec.last_error = f"GSC OAuth refresh transport error: {exc}"
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        db.commit()
        raise GscIntegrationError(rec.last_error, code="GSC_REFRESH_HTTP_ERROR", status_code=502) from exc
    finally:
        if close_client:
            client.close()

    if resp.status_code != 200:
        cfg["gsc_state"] = "BLOCKED"
        cfg["has_access_cred"] = False
        cfg["has_refresh_cred"] = False
        cfg.pop("vault_cipher_payload", None)
        rec.config_summary = cfg
        rec.connection_status = "BLOCKED"
        rec.capability_state = "BLOCKED"
        rec.last_error = f"GSC OAuth refresh token rejected or revoked ({resp.status_code})."
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        db.commit()
        raise GscIntegrationError(rec.last_error, code="GSC_REFRESH_REVOKED", status_code=401)

    refreshed = resp.json()
    new_access = str(refreshed.get("access_token") or "").strip()
    expires_in = int(refreshed.get("expires_in") or 3600)
    if not new_access:
        raise GscIntegrationError("Refresh response did not include access_token.", code="GSC_REFRESH_EMPTY", status_code=502)

    now = datetime.now(UTC)
    vault["access_token"] = new_access
    if refreshed.get("refresh_token"):
        vault["refresh_token"] = str(refreshed["refresh_token"]).strip()
    cfg["vault_cipher_payload"] = _encrypt_vault_bundle(vault)
    cfg["token_expires_at"] = (now + timedelta(seconds=expires_in)).isoformat()
    cfg["has_access_cred"] = True
    rec.config_summary = cfg
    rec.updated_at = now
    flag_modified(rec, "config_summary")
    db.commit()
    return new_access, cfg


def verify_and_select_gsc_property(
    db: Session,
    *,
    org_id: str,
    site_url: str,
    actor: str = "owner",
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch Search Console sites, confirm ownership/access level, and promote state to PROPERTY_VERIFIED."""
    clean_site = (site_url or "").strip()
    if not clean_site:
        raise GscIntegrationError("site_url is required (e.g. 'sc-domain:example.com' or 'https://example.com/').", code="GSC_MISSING_SITE_URL", status_code=422)

    rec = _get_or_create_gsc_record(db, org_id)
    _assert_live_call_allowed(http_client)
    access_token, cfg = _refresh_access_token_if_needed(db, rec, http_client=http_client)

    close_client = http_client is None
    client = http_client or httpx.Client(timeout=20.0)
    try:
        resp = client.get(
            f"{GOOGLE_GSC_API_BASE}/sites",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code == 401:
            access_token, cfg = _refresh_access_token_if_needed(db, rec, force_refresh=True, http_client=client)
            resp = client.get(
                f"{GOOGLE_GSC_API_BASE}/sites",
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:
        cfg["gsc_state"] = "BLOCKED"
        rec.config_summary = cfg
        rec.connection_status = "ERROR"
        rec.capability_state = "BLOCKED"
        rec.last_error = f"Failed to reach Search Console /sites API: {exc}"
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        db.commit()
        raise GscIntegrationError(rec.last_error, code="GSC_SITES_HTTP_ERROR", status_code=502) from exc
    finally:
        if close_client:
            client.close()

    if resp.status_code != 200:
        cfg["gsc_state"] = "BLOCKED"
        rec.config_summary = cfg
        rec.connection_status = "ERROR"
        rec.capability_state = "BLOCKED"
        rec.last_error = f"Search Console /sites API returned HTTP {resp.status_code}."
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        db.commit()
        raise GscIntegrationError(rec.last_error, code="GSC_SITES_API_REJECTED", status_code=403 if resp.status_code in (401, 403) else 502)

    entries = resp.json().get("siteEntry") or []
    matched = next((e for e in entries if e.get("siteUrl") == clean_site), None)
    if not matched:
        cfg["gsc_state"] = "BLOCKED"
        cfg["selected_property"] = clean_site
        cfg["property_permission"] = None
        rec.config_summary = cfg
        rec.connection_status = "BLOCKED"
        rec.capability_state = "BLOCKED"
        rec.last_error = f"Search Console property '{clean_site}' not found on authorized Google account."
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        db.commit()
        raise GscIntegrationError(rec.last_error, code="GSC_PROPERTY_NOT_FOUND", status_code=404)

    perm = str(matched.get("permissionLevel") or "siteUnverifiedUser")
    if perm not in GSC_VERIFIED_PERMISSIONS:
        cfg["gsc_state"] = "BLOCKED"
        cfg["selected_property"] = clean_site
        cfg["property_permission"] = perm
        rec.config_summary = cfg
        rec.connection_status = "BLOCKED"
        rec.capability_state = "BLOCKED"
        rec.last_error = f"Search Console property '{clean_site}' permission is '{perm}' (unverified/insufficient)."
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        db.commit()
        raise GscIntegrationError(rec.last_error, code="GSC_PROPERTY_UNVERIFIED", status_code=403)

    now = datetime.now(UTC)
    cfg["selected_property"] = clean_site
    cfg["property_permission"] = perm
    cfg["gsc_state"] = "PROPERTY_VERIFIED"
    cfg["available_properties"] = [
        {"siteUrl": e.get("siteUrl"), "permissionLevel": e.get("permissionLevel")}
        for e in entries[:50]
    ]
    rec.config_summary = cfg
    rec.connection_status = "PROPERTY_VERIFIED"
    rec.capability_state = "CONFIGURED_UNVERIFIED"
    rec.last_verified_at = now
    rec.last_error = None
    rec.updated_at = now
    flag_modified(rec, "config_summary")
    _record_gsc_audit(
        db,
        actor=actor,
        org_id=org_id,
        action="gsc_property_verified",
        output_payload={"site_url": clean_site, "permission_level": perm, "gsc_state": "PROPERTY_VERIFIED"},
    )
    db.commit()
    db.refresh(rec)
    return serialize_gsc_state(rec)


def _validate_iso_range(start_date: str, end_date: str) -> tuple[str, str]:
    try:
        sd = date.fromisoformat(start_date.strip())
        ed = date.fromisoformat(end_date.strip())
    except (ValueError, AttributeError) as exc:
        raise GscIntegrationError("Dates must be valid YYYY-MM-DD strings.", code="GSC_INVALID_DATE_RANGE", status_code=422) from exc
    if sd > ed:
        raise GscIntegrationError("start_date must be <= end_date.", code="GSC_INVALID_DATE_RANGE", status_code=422)
    return sd.isoformat(), ed.isoformat()


def _summarize_analytics_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    clicks = sum(int(r.get("clicks", 0) or 0) for r in rows)
    impressions = sum(int(r.get("impressions", 0) or 0) for r in rows)
    ctr = round((clicks / impressions), 6) if impressions > 0 else 0.0
    if impressions > 0:
        weighted_pos = sum(float(r.get("position", 0.0) or 0.0) * int(r.get("impressions", 0) or 0) for r in rows)
        avg_position = round(weighted_pos / impressions, 2)
    elif rows:
        avg_position = round(sum(float(r.get("position", 0.0) or 0.0) for r in rows) / len(rows), 2)
    else:
        avg_position = None
    return {
        "row_count": len(rows),
        "clicks": clicks,
        "impressions": impressions,
        "ctr": ctr,
        "avg_position": avg_position,
    }


def fetch_gsc_search_analytics(
    db: Session,
    *,
    org_id: str,
    start_date: str,
    end_date: str,
    dimensions: list[str] | None = None,
    row_limit: int = 250,
    baseline_start_date: str | None = None,
    baseline_end_date: str | None = None,
    delivery_id: str | None = None,
    claimed_askforwrite_caused: bool = False,
    actor: str = "owner",
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Query Search Analytics API, optionally compare baseline window, promote state, and persist attribution."""
    sd, ed = _validate_iso_range(start_date, end_date)
    dims = dimensions or ["query", "page"]
    if not dims or any(d not in GSC_VALID_DIMENSIONS for d in dims):
        raise GscIntegrationError(
            f"Invalid dimensions. Allowed: {sorted(GSC_VALID_DIMENSIONS)}",
            code="GSC_INVALID_DIMENSIONS",
            status_code=422,
        )
    has_baseline_range = bool(baseline_start_date and baseline_end_date)
    if (baseline_start_date and not baseline_end_date) or (baseline_end_date and not baseline_start_date):
        raise GscIntegrationError("Provide both baseline_start_date and baseline_end_date together.", code="GSC_INCOMPLETE_BASELINE", status_code=422)
    bsd, bed = _validate_iso_range(baseline_start_date, baseline_end_date) if has_baseline_range else (None, None)

    rec = _get_or_create_gsc_record(db, org_id)
    cfg = dict(rec.config_summary or {})
    site_url = cfg.get("selected_property")
    if not site_url or cfg.get("gsc_state") in ("BLOCKED", "OAuth_CONNECTED") or cfg.get("property_permission") not in GSC_VERIFIED_PERMISSIONS:
        raise GscIntegrationError(
            "Verify a Search Console property before querying Search Analytics (state must be PROPERTY_VERIFIED+).",
            code="GSC_PROPERTY_REQUIRED",
            status_code=400,
        )

    _assert_live_call_allowed(http_client)
    access_token, cfg = _refresh_access_token_if_needed(db, rec, http_client=http_client)

    encoded_site = quote(str(site_url), safe="")
    query_url = f"{GOOGLE_GSC_API_BASE}/sites/{encoded_site}/searchAnalytics/query"

    def _run_query(client_obj: httpx.Client, token: str, s_dt: str, e_dt: str) -> httpx.Response:
        return client_obj.post(
            query_url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "startDate": s_dt,
                "endDate": e_dt,
                "dimensions": dims,
                "rowLimit": max(1, min(int(row_limit), 5000)),
            },
        )

    close_client = http_client is None
    client = http_client or httpx.Client(timeout=25.0)
    try:
        current_resp = _run_query(client, access_token, sd, ed)
        if current_resp.status_code == 401:
            access_token, cfg = _refresh_access_token_if_needed(db, rec, force_refresh=True, http_client=client)
            current_resp = _run_query(client, access_token, sd, ed)
        if current_resp.status_code != 200:
            raise GscIntegrationError(
                f"Search Analytics query failed with HTTP {current_resp.status_code}.",
                code="GSC_ANALYTICS_API_ERROR",
                status_code=403 if current_resp.status_code in (401, 403) else 502,
            )

        baseline_resp = None
        if bsd and bed:
            baseline_resp = _run_query(client, access_token, bsd, bed)
            if baseline_resp.status_code != 200:
                raise GscIntegrationError(
                    f"Baseline Search Analytics query failed with HTTP {baseline_resp.status_code}.",
                    code="GSC_BASELINE_API_ERROR",
                    status_code=403 if baseline_resp.status_code in (401, 403) else 502,
                )
    except httpx.HTTPError as exc:
        cfg["gsc_state"] = "BLOCKED"
        rec.config_summary = cfg
        rec.connection_status = "ERROR"
        rec.capability_state = "BLOCKED"
        rec.last_error = f"Search Analytics HTTP error: {exc}"
        rec.updated_at = datetime.now(UTC)
        flag_modified(rec, "config_summary")
        db.commit()
        raise GscIntegrationError(rec.last_error, code="GSC_ANALYTICS_HTTP_ERROR", status_code=502) from exc
    finally:
        if close_client:
            client.close()

    current_rows = (current_resp.json().get("rows") or []) if isinstance(current_resp.json(), dict) else []
    current_summary = _summarize_analytics_rows(current_rows)
    baseline_summary = None
    if baseline_resp is not None:
        base_rows = (baseline_resp.json().get("rows") or []) if isinstance(baseline_resp.json(), dict) else []
        baseline_summary = _summarize_analytics_rows(base_rows)

    now = datetime.now(UTC)
    new_gsc_state = "ATTRIBUTION_READY" if baseline_summary is not None else "DATA_FETCH_VERIFIED"
    snapshot_summary = {
        "site_url": site_url,
        "date_range": {"start_date": sd, "end_date": ed},
        "dimensions": dims,
        "current": current_summary,
        "baseline_date_range": {"start_date": bsd, "end_date": bed} if baseline_summary else None,
        "baseline": baseline_summary,
        "delta_clicks": (current_summary["clicks"] - baseline_summary["clicks"]) if baseline_summary else None,
        "delta_impressions": (current_summary["impressions"] - baseline_summary["impressions"]) if baseline_summary else None,
        "fetched_at": now.isoformat(),
    }

    cfg["gsc_state"] = new_gsc_state
    cfg["has_baseline_attribution"] = bool(baseline_summary is not None)
    cfg["latest_analytics_summary"] = snapshot_summary
    rec.config_summary = cfg
    rec.connection_status = "VERIFIED"
    rec.capability_state = "SANDBOX_VERIFIED" if http_client is not None else "LIVE_VERIFIED"
    rec.last_verified_at = now
    rec.last_error = None
    rec.updated_at = now
    flag_modified(rec, "config_summary")

    delivery_update = None
    if delivery_id:
        from app.services.p3_delivery_health import record_delivery_metrics_and_outcomes

        evidence_ref = f"gsc://{re.sub(r'[^a-zA-Z0-9._-]+', '_', str(site_url))}/{sd}..{ed}"
        outcome_payload: dict[str, Any] = {
            "gsc_connected": True,
            "gsc_property": site_url,
            "organic_traffic": current_summary["clicks"],
            "impressions": current_summary["impressions"],
            "keyword_visibility": current_summary["row_count"],
            "avg_position": current_summary["avg_position"],
            "ctr": current_summary["ctr"],
            "attribution_evidence_level": "GSC_VERIFIED_WITH_BASELINE" if baseline_summary is not None else "GSC_CURRENT_WINDOW_ONLY",
            "attribution_evidence_refs": [evidence_ref],
            "claimed_askforwrite_caused": bool(claimed_askforwrite_caused and baseline_summary is not None),
            "baseline_comparison": snapshot_summary,
            "attribution_note": (
                "Verified Search Console searchAnalytics query with baseline window persisted."
                if baseline_summary is not None
                else "Verified Search Console searchAnalytics query persisted (no baseline window yet)."
            ),
        }
        delivery_update = record_delivery_metrics_and_outcomes(
            db,
            delivery_id=delivery_id,
            outcome_metrics=outcome_payload,
            actor=actor,
        )

    _record_gsc_audit(
        db,
        actor=actor,
        org_id=org_id,
        action="gsc_search_analytics_fetched",
        output_payload={
            "gsc_state": new_gsc_state,
            "site_url": site_url,
            "clicks": current_summary["clicks"],
            "impressions": current_summary["impressions"],
            "has_baseline": baseline_summary is not None,
            "delivery_id": delivery_id,
        },
    )
    db.commit()
    db.refresh(rec)
    return {
        **serialize_gsc_state(rec),
        "analytics": snapshot_summary,
        "top_rows": current_rows[:25],
        "delivery_updated": delivery_update,
    }


def disconnect_gsc_account(db: Session, *, org_id: str, actor: str = "owner") -> dict[str, Any]:
    """Revoke/remove stored encrypted OAuth credentials and move GSC state cleanly to BLOCKED/disconnected."""
    rec = _get_or_create_gsc_record(db, org_id)
    now = datetime.now(UTC)
    cfg = dict(rec.config_summary or {})
    cfg.pop("vault_cipher_payload", None)
    cfg.pop("oauth_state_hash", None)
    cfg["has_access_cred"] = False
    cfg["has_refresh_cred"] = False
    cfg["token_expires_at"] = None
    cfg["selected_property"] = None
    cfg["property_permission"] = None
    cfg["granted_scopes"] = []
    cfg["has_baseline_attribution"] = False
    cfg["gsc_state"] = "BLOCKED"
    rec.config_summary = cfg
    rec.connection_status = "NOT_CONNECTED"
    rec.capability_state = "BLOCKED"
    rec.last_error = "Google Search Console account disconnected by user/owner."
    rec.updated_at = now
    flag_modified(rec, "config_summary")
    _record_gsc_audit(
        db,
        actor=actor,
        org_id=org_id,
        action="gsc_account_disconnected",
        output_payload={"gsc_state": "BLOCKED"},
    )
    db.commit()
    db.refresh(rec)
    return serialize_gsc_state(rec)
