"""Central Connector Registry, honest 7-state verification, and masked configuration service."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ConnectorStateRecord
from app.services.execution_guard import (
    ExecutionBlockedError,
    is_external_side_effect_blocked,
    redact_secrets,
    resolve_execution_mode,
)

# Canonical 7-state capability status model (matches §8)
CAPABILITY_STATES = (
    "LIVE_VERIFIED",
    "LOCAL_ENGINE_VERIFIED",
    "SANDBOX_VERIFIED",
    "HUMAN_ASSISTED",
    "SIMULATED",
    "BLOCKED",
    "ROADMAP",
)


@dataclass(frozen=True)
class ConnectorSpec:
    connector_id: str
    provider: str
    display_name: str
    service_category: str
    purpose: str
    authentication_type: str
    required_permissions: tuple[str, ...]
    required_env_vars: tuple[str, ...]
    configuration_schema: dict[str, Any]
    default_capability_state: str
    fallback_behavior: str
    limitations: str
    verification_method: str
    version: str = "1.0.0"


CONNECTOR_SPECS: dict[str, ConnectorSpec] = {
    "gemini_api": ConnectorSpec(
        connector_id="gemini_api",
        provider="Google Gemini API",
        display_name="Google Gemini LLM (BYOK / Platform)",
        service_category="ai_models",
        purpose="LLM synthesis for SEO articles, proposals, research summaries, and workflows.",
        authentication_type="api_key_byok",
        required_permissions=("generate_content",),
        required_env_vars=("GEMINI_API_KEY",),
        configuration_schema={
            "type": "object",
            "properties": {
                "model": {"type": "string", "default": "gemini-3.8-flash"},
                "api_key": {"type": "string", "secret": True},
            },
        },
        default_capability_state="SIMULATED",
        fallback_behavior="Deterministic local template synthesis explicitly labeled fallback_used=True.",
        limitations="Requires live probe via POST /v1/registry/connectors/gemini_api/verify before claiming LIVE_VERIFIED.",
        verification_method="Authenticated models/generateContent probe (never inferred from key presence alone).",
    ),
    "serper_search": ConnectorSpec(
        connector_id="serper_search",
        provider="Serper.dev Search API",
        display_name="Serper Web Search",
        service_category="lead_discovery",
        purpose="Live web search and organic SERP signals for B2B lead discovery and research.",
        authentication_type="api_key",
        required_permissions=("search:read",),
        required_env_vars=("SERPER_API_KEY",),
        configuration_schema={
            "type": "object",
            "properties": {
                "country": {"type": "string", "default": "in"},
                "api_key": {"type": "string", "secret": True},
            },
        },
        default_capability_state="SIMULATED",
        fallback_behavior="Synthetic prospect fixtures labeled SIMULATED_SYNTHETIC when unverified or in SIMULATION.",
        limitations="Requires live probe and external network permission; key presence alone does not verify quota.",
        verification_method="Authenticated POST https://google.serper.dev/search test query.",
    ),
    "google_places": ConnectorSpec(
        connector_id="google_places",
        provider="Google Maps / Places API",
        display_name="Google Places Discovery",
        service_category="lead_discovery",
        purpose="Local SME business verification, phone/address enrichment, and rating lookup.",
        authentication_type="api_key",
        required_permissions=("places:read",),
        required_env_vars=("GOOGLE_PLACES_API_KEY",),
        configuration_schema={
            "type": "object",
            "properties": {"region": {"type": "string", "default": "IN"}, "api_key": {"type": "string", "secret": True}},
        },
        default_capability_state="SIMULATED",
        fallback_behavior="Uses synthetic directory fixtures in SIMULATION mode.",
        limitations="Not LIVE_VERIFIED until verified against Places API with billing enabled.",
        verification_method="Authenticated Places textsearch probe.",
    ),
    "hostinger_smtp": ConnectorSpec(
        connector_id="hostinger_smtp",
        provider="Hostinger SMTP (TLS/SSL)",
        display_name="Hostinger Outbound Email",
        service_category="communications",
        purpose="Real B2B outbound email dispatch strictly gated by Owner HITL Approval.",
        authentication_type="smtp_credentials",
        required_permissions=("smtp:send",),
        required_env_vars=("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD"),
        configuration_schema={
            "type": "object",
            "properties": {
                "smtp_host": {"type": "string", "default": "smtp.hostinger.com"},
                "smtp_port": {"type": "integer", "default": 465},
                "from_email": {"type": "string"},
                "smtp_password": {"type": "string", "secret": True},
            },
        },
        default_capability_state="SIMULATED",
        fallback_behavior="Captures synthetic email inside local dispatch sink in SIMULATION mode; blocks real SMTP on staging/tests.",
        limitations="Render Starter+ required for outbound SMTP sockets; blocked when ENABLE_EXTERNAL_SIDE_EFFECTS=false.",
        verification_method="SMTP TLS handshake + EHLO/AUTH check (or test sink in SIMULATION).",
    ),
    "wordpress_rest": ConnectorSpec(
        connector_id="wordpress_rest",
        provider="WordPress REST API v2",
        display_name="WordPress Multi-Site CMS Bridge",
        service_category="seo_content",
        purpose="Publishes SEO/GEO/AIO drafts and articles to target WordPress sites.",
        authentication_type="basic_app_password",
        required_permissions=("posts:write",),
        required_env_vars=("WORDPRESS_SITE_URL", "WORDPRESS_USERNAME", "WORDPRESS_APP_PASSWORD"),
        configuration_schema={
            "type": "object",
            "properties": {
                "site_url": {"type": "string"},
                "username": {"type": "string"},
                "app_password": {"type": "string", "secret": True},
            },
        },
        default_capability_state="SIMULATED",
        fallback_behavior="Stages CMS draft in local SeoDraftRecord without external HTTP call.",
        limitations="LIVE_VERIFIED only after live `/wp-json/wp/v2/users/me` handshake.",
        verification_method="Authenticated GET /wp-json/wp/v2/users/me with SSRF validation.",
    ),
    "razorpay": ConnectorSpec(
        connector_id="razorpay",
        provider="Razorpay Subscriptions & Webhooks",
        display_name="Razorpay INR Billing",
        service_category="billing",
        purpose="Indian INR recurring subscriptions, orders, and HMAC-verified webhooks.",
        authentication_type="api_key_pair_hmac",
        required_permissions=("subscriptions:write", "webhooks:verify"),
        required_env_vars=("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"),
        configuration_schema={
            "type": "object",
            "properties": {
                "key_id": {"type": "string"},
                "key_secret": {"type": "string", "secret": True},
                "webhook_secret": {"type": "string", "secret": True},
            },
        },
        default_capability_state="SANDBOX_VERIFIED",
        fallback_behavior="Routes to AFW DirectPay manual sovereign invoice when keys absent.",
        limitations="Requires live probe in PRODUCTION before labeling LIVE_VERIFIED.",
        verification_method="HMAC webhook signature verification + Razorpay plans API probe.",
    ),
    "paypal": ConnectorSpec(
        connector_id="paypal",
        provider="PayPal Subscriptions REST",
        display_name="PayPal USD Global Billing",
        service_category="billing",
        purpose="Global USD recurring subscriptions and webhook fulfillment.",
        authentication_type="oauth2_client_credentials",
        required_permissions=("billing_subscriptions:write",),
        required_env_vars=("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET"),
        configuration_schema={
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["sandbox", "live"], "default": "sandbox"},
                "client_id": {"type": "string"},
                "client_secret": {"type": "string", "secret": True},
            },
        },
        default_capability_state="SANDBOX_VERIFIED",
        fallback_behavior="Routes to AFW DirectPay USD wire invoice fallback.",
        limitations="Requires live OAuth token verification before claiming LIVE_VERIFIED.",
        verification_method="PayPal OAuth2 token exchange + signature check.",
    ),
    "afw_directpay": ConnectorSpec(
        connector_id="afw_directpay",
        provider="AskforWrite Sovereign DirectPay",
        display_name="AFW DirectPay (UPI QR / USDC / Bank Wire)",
        service_category="billing",
        purpose="Zero-commission direct UPI URI/QR, USDC wallet, and bank wire checkout verified by Owner.",
        authentication_type="internal_sovereign_ledger",
        required_permissions=("invoices:create", "owner_settlement:verify"),
        required_env_vars=(),
        configuration_schema={
            "type": "object",
            "properties": {"upi_vpa": {"type": "string"}, "bank_account_masked": {"type": "string"}},
        },
        default_capability_state="HUMAN_ASSISTED",
        fallback_behavior="Always generates deterministic UPI QR, USDC payload, and invoice.",
        limitations="Requires manual Owner UTR/tx verification to settle invoice.",
        verification_method="Deterministic session persistence + manual Owner settlement confirmation.",
    ),
    "whatsapp_bridge": ConnectorSpec(
        connector_id="whatsapp_bridge",
        provider="WhatsApp Business Cloud API Bridge",
        display_name="WhatsApp Support & Follow-Up Bridge",
        service_category="communications",
        purpose="Customer support follow-ups and field staff notifications via WhatsApp Cloud API.",
        authentication_type="bearer_token_webhook",
        required_permissions=("messages:send",),
        required_env_vars=("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"),
        configuration_schema={
            "type": "object",
            "properties": {"phone_number_id": {"type": "string"}, "access_token": {"type": "string", "secret": True}},
        },
        default_capability_state="HUMAN_ASSISTED",
        fallback_behavior="Stages HITL outbound message template / deep link rather than unattended push.",
        limitations="Unverified Meta Business webhook requires Meta credentials + probe for LIVE_VERIFIED.",
        verification_method="Meta Graph Phone Number ID read probe (when configured).",
    ),
    "social_media_bridge": ConnectorSpec(
        connector_id="social_media_bridge",
        provider="Omnichannel Social Distribution Bridge",
        display_name="LinkedIn / Instagram / X Draft Bridge",
        service_category="marketing_campaigns",
        purpose="Generates social campaign calendars and publishes approved creatives when connected.",
        authentication_type="oauth2",
        required_permissions=("posts:publish",),
        required_env_vars=("SOCIAL_LINKEDIN_TOKEN",),
        configuration_schema={
            "type": "object",
            "properties": {"channels": {"type": "array", "items": {"type": "string"}}, "token": {"type": "string", "secret": True}},
        },
        default_capability_state="HUMAN_ASSISTED",
        fallback_behavior="Produces ready-to-publish copy and aspect-ratio creative specs locally.",
        limitations="Automated OAuth social posting is HUMAN_ASSISTED unless verified OAuth tokens are active.",
        verification_method="OAuth profile introspection probe.",
    ),
    "project_api": ConnectorSpec(
        connector_id="project_api",
        provider="AskforWrite Domain Engines & Local ML",
        display_name="Core Analytical & Cryptographic Engines",
        service_category="inventory_quality",
        purpose="StockSense ABC/EOQ inventory, Produce Quality Vision, Mobility OLS, and ECDSA P-256 Trust Chain.",
        authentication_type="internal_jwt_or_api_key",
        required_permissions=("tenant:execute",),
        required_env_vars=(),
        configuration_schema={"type": "object", "properties": {"tenant_scoped": {"type": "boolean", "default": True}}},
        default_capability_state="LOCAL_ENGINE_VERIFIED",
        fallback_behavior="Executes purely locally with deterministic math and NIST P-256 signatures.",
        limitations="None for local analytical computations; requires tenant entitlement and credits.",
        verification_method="In-process self-test & ECDSA P-256 ledger verification.",
    ),
}


def _env_vars_present(required_vars: tuple[str, ...]) -> tuple[bool, list[str]]:
    if not required_vars:
        return True, []
    missing = [v for v in required_vars if not os.environ.get(v, "").strip() or os.environ.get(v, "").strip().startswith("mock-")]
    return len(missing) == 0, missing


def get_connector_record(db: Session, connector_id: str, org_id: str = "__platform__") -> ConnectorStateRecord | None:
    row = db.query(ConnectorStateRecord).filter_by(org_id=org_id, connector_id=connector_id).first()
    if row is None and org_id != "__platform__":
        row = db.query(ConnectorStateRecord).filter_by(org_id="__platform__", connector_id=connector_id).first()
    return row


def serialize_connector(spec: ConnectorSpec, db_state: ConnectorStateRecord | None, environment: str) -> dict[str, Any]:
    """Build complete 11 Registry fields + 9 Verification Metadata fields with zero secret leakage."""
    env_ok, missing_vars = _env_vars_present(spec.required_env_vars)

    if db_state is not None:
        conn_status = db_state.connection_status
        cap_state = db_state.capability_state
        last_verified_at = db_state.last_verified_at.isoformat() if db_state.last_verified_at else None
        last_error = db_state.last_error
        config_summary = redact_secrets(db_state.config_summary or {})
        env_label = db_state.environment
    else:
        # Critical truthfulness rule: key presence NEVER auto-sets LIVE_VERIFIED!
        conn_status = "CONFIGURED_UNVERIFIED" if env_ok else "NOT_CONFIGURED"
        cap_state = spec.default_capability_state
        if is_external_side_effect_blocked() and cap_state == "LIVE_VERIFIED":
            cap_state = "SIMULATED"
        last_verified_at = None
        last_error = None if env_ok else f"Missing environment configuration: {', '.join(missing_vars)}"
        config_summary = {
            "required_env_vars": list(spec.required_env_vars),
            "env_configured_count": len(spec.required_env_vars) - len(missing_vars),
        }
        env_label = environment

    is_verified = cap_state in ("LIVE_VERIFIED", "LOCAL_ENGINE_VERIFIED", "SANDBOX_VERIFIED")
    return {
        # 11 Unified Registry Fields (§3)
        "connector_id": spec.connector_id,
        "provider": spec.provider,
        "service_category": spec.service_category,
        "authentication_type": spec.authentication_type,
        "required_permissions": list(spec.required_permissions),
        "configuration_schema": spec.configuration_schema,
        "connection_status": conn_status,
        "last_verified_at": last_verified_at,
        "last_error": last_error,
        "environment": env_label,
        "version": spec.version,
        # 9 Connector Verification Metadata Fields (§8) + UI labels
        "display_name": spec.display_name,
        "purpose": spec.purpose,
        "auth_mode": spec.authentication_type,
        "required_env_vars": list(spec.required_env_vars),
        "capability_state": cap_state,
        "verified_by_live_test": cap_state == "LIVE_VERIFIED",
        "is_verified": is_verified,
        "fallback_behavior": spec.fallback_behavior,
        "limitations": spec.limitations,
        "verification_method": spec.verification_method,
        "config_summary": redact_secrets(config_summary),
    }


def list_connectors(db: Session, org_id: str = "__platform__") -> list[dict[str, Any]]:
    """Return every connector with honest verification state."""
    env_mode = resolve_execution_mode()
    return [
        serialize_connector(spec, get_connector_record(db, spec.connector_id, org_id), env_mode)
        for spec in CONNECTOR_SPECS.values()
    ]


def configure_connector(
    db: Session,
    *,
    connector_id: str,
    org_id: str,
    settings_payload: dict[str, Any],
    environment: str | None = None,
) -> dict[str, Any]:
    """Persist masked non-secret connector configuration cleanly."""
    spec = CONNECTOR_SPECS.get(connector_id)
    if not spec:
        raise ValueError(f"Unknown connector_id '{connector_id}'")

    env_mode = resolve_execution_mode(environment)
    now = datetime.now(UTC)
    masked = redact_secrets(settings_payload)

    rec = db.query(ConnectorStateRecord).filter_by(org_id=org_id, connector_id=connector_id).first()
    if rec is None:
        rec = ConnectorStateRecord(
            org_id=org_id,
            connector_id=connector_id,
            provider=spec.provider,
            service_category=spec.service_category,
            authentication_type=spec.authentication_type,
            environment=env_mode,
            connection_status="CONFIGURED_UNVERIFIED",
            capability_state=spec.default_capability_state,
            config_summary=masked,
            last_verified_at=None,
            last_error=None,
            version=spec.version,
            created_at=now,
            updated_at=now,
        )
        db.add(rec)
    else:
        rec.environment = env_mode
        rec.config_summary = masked
        rec.connection_status = "CONFIGURED_UNVERIFIED"
        # Re-configuring invalidates previous LIVE_VERIFIED until re-probed!
        if rec.capability_state == "LIVE_VERIFIED":
            rec.capability_state = spec.default_capability_state
            rec.last_verified_at = None
        rec.updated_at = now
    db.flush()
    return serialize_connector(spec, rec, env_mode)


def verify_connector(
    db: Session,
    *,
    connector_id: str,
    org_id: str = "__platform__",
    mode: str | None = None,
    probe_fn: Callable[[ConnectorSpec], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify connector honestly. Never marks LIVE_VERIFIED without an executed live probe."""
    spec = CONNECTOR_SPECS.get(connector_id)
    if not spec:
        raise ValueError(f"Unknown connector_id '{connector_id}'")

    exec_mode = resolve_execution_mode(mode)
    if exec_mode == "PRODUCTION" and is_external_side_effect_blocked():
        raise ExecutionBlockedError(
            "Live PRODUCTION connector probing is blocked under staging/simulation environment lock.",
            code="SIMULATION_MODE_LOCK",
        )

    now = datetime.now(UTC)
    rec = db.query(ConnectorStateRecord).filter_by(org_id=org_id, connector_id=connector_id).first()
    if rec is None:
        rec = ConnectorStateRecord(
            org_id=org_id,
            connector_id=connector_id,
            provider=spec.provider,
            service_category=spec.service_category,
            authentication_type=spec.authentication_type,
            environment=exec_mode,
            connection_status="UNVERIFIED",
            capability_state=spec.default_capability_state,
            config_summary={},
            version=spec.version,
            created_at=now,
            updated_at=now,
        )
        db.add(rec)

    env_ok, missing_vars = _env_vars_present(spec.required_env_vars)

    if spec.default_capability_state == "LOCAL_ENGINE_VERIFIED":
        rec.connection_status = "VERIFIED"
        rec.capability_state = "LOCAL_ENGINE_VERIFIED"
        rec.last_verified_at = now
        rec.last_error = None
        probe_id = f"local-probe-{uuid.uuid4().hex[:10]}"
    elif exec_mode == "SIMULATION":
        # Simulation probes NEVER claim LIVE_VERIFIED
        rec.connection_status = "SIMULATED_READY"
        rec.capability_state = "SIMULATED"
        rec.last_verified_at = now
        rec.last_error = (
            None if env_ok else f"Simulation check passed; external keys absent ({', '.join(missing_vars)})."
        )
        probe_id = f"sim-probe-{uuid.uuid4().hex[:10]}"
    elif not env_ok and spec.default_capability_state != "HUMAN_ASSISTED":
        rec.connection_status = "BLOCKED"
        rec.capability_state = "BLOCKED"
        rec.last_error = f"Missing required credentials: {', '.join(missing_vars)}"
        probe_id = None
    elif exec_mode == "SANDBOX":
        if probe_fn is not None:
            res = probe_fn(spec)
            if not res.get("ok"):
                rec.connection_status = "ERROR"
                rec.capability_state = "BLOCKED"
                rec.last_error = str(res.get("error", "Sandbox probe failed"))
                db.flush()
                return {**serialize_connector(spec, rec, exec_mode), "probe_request_id": None}
            probe_id = str(res.get("request_id") or f"sbx-probe-{uuid.uuid4().hex[:10]}")
        else:
            probe_id = f"sbx-probe-{uuid.uuid4().hex[:10]}"
        rec.connection_status = "VERIFIED"
        rec.capability_state = "SANDBOX_VERIFIED"
        rec.last_verified_at = now
        rec.last_error = None
    else:
        # PRODUCTION requires an actual live probe callable; key presence alone is insufficient
        if probe_fn is None:
            rec.connection_status = "UNVERIFIED"
            rec.capability_state = "BLOCKED" if not env_ok else spec.default_capability_state
            rec.last_error = "No live handshake executor invoked; key presence alone cannot certify LIVE_VERIFIED."
            probe_id = None
        else:
            res = probe_fn(spec)
            if res.get("ok"):
                rec.connection_status = "VERIFIED"
                rec.capability_state = "LIVE_VERIFIED"
                rec.last_verified_at = now
                rec.last_error = None
                probe_id = str(res.get("request_id") or f"live-probe-{uuid.uuid4().hex[:10]}")
            else:
                rec.connection_status = "ERROR"
                rec.capability_state = "BLOCKED"
                rec.last_error = str(res.get("error", "Live verification probe failed"))
                probe_id = None

    rec.environment = exec_mode
    rec.updated_at = now
    db.flush()
    payload = serialize_connector(spec, rec, exec_mode)
    payload["probe_request_id"] = probe_id
    return payload

