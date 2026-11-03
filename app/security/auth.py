"""API-key and token authentication and role authorization for gateway routes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, Header, HTTPException, status


@dataclass(frozen=True)
class APIPrincipal:
    subject: str
    role: str
    user_id: str | None = None
    org_id: str | None = None
    email: str | None = None
    tier: str | None = None


# ── Password Hashing (PBKDF2-HMAC-SHA256) ───────────────────────────────────


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with cryptographically random salt."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"pbkdf2:sha256:100000${salt}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """Verify plain password against PBKDF2 hash string."""
    if not hashed_password or not hashed_password.startswith("pbkdf2:sha256:"):
        return False
    try:
        parts = hashed_password.split("$")
        if len(parts) != 3:
            return False
        meta, salt, expected_key = parts
        rounds = int(meta.split(":")[2])
        computed = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt.encode("utf-8"), rounds)
        return hmac.compare_digest(computed.hex(), expected_key)
    except Exception:
        return False


# ── Signed Bearer Token Helpers ──────────────────────────────────────────────


def _get_signing_secret() -> str:
    return (
        os.environ.get("JWT_SECRET_KEY")
        or os.environ.get("SECRET_KEY")
        or os.environ.get("AUTH_SECRET_KEY")
        or os.environ.get("OWNER_API_KEY")
        or os.environ.get("MANAGER_API_KEY")
        or "default-insecure-askforwrite-dev-secret-do-not-use-in-prod"
    )


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    org_id: str,
    tier: str | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a tamper-proof HMAC-SHA256 signed access token for Admin and Customer login."""
    secret = _get_signing_secret()
    expire = datetime.now(UTC) + (expires_delta or timedelta(hours=24))
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "role": role,
        "org_id": org_id,
        "exp": int(expire.timestamp()),
    }
    if tier:
        payload["tier"] = tier
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode("utf-8")).decode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), encoded_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{encoded_payload}.{signature}"


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and cryptographically verify signed access token."""
    secret = _get_signing_secret()
    if "." not in token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed authentication token")
    encoded_payload, signature = token.split(".", 1)
    expected_sig = hmac.new(secret.encode("utf-8"), encoded_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature")
    try:
        raw_json = base64.urlsafe_b64decode(encoded_payload.encode("utf-8")).decode("utf-8")
        payload = json.loads(raw_json)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload") from exc

    exp = payload.get("exp", 0)
    if datetime.now(UTC).timestamp() > exp:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    return payload


# ── Principal Resolution (API Key OR Bearer Token) ──────────────────────────


def get_current_principal(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    x_gemini_api_key: str | None = Header(default=None),
) -> APIPrincipal:
    """Resolve API principal from either X-API-Key header OR Bearer token."""
    from app.agents.llm_client import set_request_llm_context

    # 1. Bearer Token Resolution (Customer / Admin Login)
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        payload = decode_access_token(token)
        role = payload.get("role", "customer")
        is_owner = role in {"owner", "manager"}
        set_request_llm_context(gemini_key=x_gemini_api_key, is_owner=is_owner)
        return APIPrincipal(
            subject=payload.get("email") or payload.get("sub", "unknown"),
            role=role,
            user_id=payload.get("sub"),
            org_id=payload.get("org_id"),
            email=payload.get("email"),
            tier=payload.get("tier"),
        )

    # 2. X-API-Key Resolution (Automated Agents & System Operators)
    configured_keys = (
        ("OWNER_API_KEY", "owner", "owner"),
        ("MANAGER_API_KEY", "manager", "manager"),
    )
    available_keys = [
        (environment_name, subject, role, os.environ.get(environment_name, ""))
        for environment_name, subject, role in configured_keys
    ]
    if not any(value for _, _, _, value in available_keys):
        raise HTTPException(status_code=503, detail="API authentication is not configured")
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

    for environment_name, subject, role, expected_key in available_keys:
        if expected_key and len(expected_key) < 32:
            raise HTTPException(
                status_code=503,
                detail=f"{environment_name} must contain at least 32 characters",
            )
        if expected_key and hmac.compare_digest(expected_key, x_api_key):
            set_request_llm_context(gemini_key=x_gemini_api_key, is_owner=(role in {"owner", "manager"}))
            return APIPrincipal(subject=subject, role=role)

    raise HTTPException(status_code=401, detail="Invalid API key")



def require_manager(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    """Allow Platform Operator or Tenant Administrator.
    Tenant operations are strictly scoped by org_id within route handlers."""
    if principal.role not in {"owner", "manager", "admin", "tenant_admin"}:
        raise HTTPException(status_code=403, detail="Manager or administrator role required")
    return principal


def require_platform_manager(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    """Strictly require platform operator (owner or manager API key).
    Tenant administrators and customer users are strictly forbidden from platform operations."""
    if principal.role not in {"owner", "manager"} or principal.org_id is not None:
        raise HTTPException(status_code=403, detail="Platform operator credentials required")
    return principal


def require_owner(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    """Strictly require platform owner (OWNER_API_KEY). Tenant users forbidden."""
    if principal.role != "owner" or principal.org_id is not None:
        raise HTTPException(status_code=403, detail="Owner role required (platform owner only)")
    return principal


def require_platform_owner(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    """Strictly require platform owner (OWNER_API_KEY). Tenant users forbidden."""
    if principal.role != "owner" or principal.org_id is not None:
        raise HTTPException(status_code=403, detail="Platform owner credentials required")
    return principal


def require_admin(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    """Require Platform Owner/Manager or Tenant Administrator."""
    if principal.role in {"owner", "manager"} and not principal.org_id:
        return principal
    if principal.role not in {"admin", "tenant_admin"}:
        raise HTTPException(status_code=403, detail="Administrator role required")
    return principal


def require_tenant_admin(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    """Require Tenant Administrator role (or platform operator oversight)."""
    if principal.role in {"owner", "manager"} and not principal.org_id:
        return principal
    if principal.role not in {"admin", "tenant_admin"}:
        raise HTTPException(status_code=403, detail="Tenant administrator role required")
    return principal


def require_tenant_member(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    """Any member belonging to a tenant organization (or platform operator oversight)."""
    return principal


def require_authenticated_user(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    """Any authenticated tenant user, customer, or admin."""
    return principal


def enforce_tenant_access(principal: APIPrincipal, target_org_id: str | None) -> None:
    """Ensure that non-owner principals cannot access or mutate resources outside their organization."""
    # System owners and platform managers have global administrative oversight
    if principal.role in {"owner", "manager"} and not principal.org_id:
        return
    # If the principal is tied to a specific organization, access across org boundaries or unassigned resources is strictly forbidden
    if principal.org_id:
        if not target_org_id or principal.org_id != target_org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: principal belongs to organization '{principal.org_id}', not '{target_org_id}'",
            )


# ── Tenant Service Entitlement Verification ─────────────────────────────────


def is_service_entitled(service_key: str, entitled_caps: set[str], pkg_key: str | None = None) -> bool:
    """Validate whether the tenant's purchased plan includes the requested modular service."""
    if pkg_key == "all_access" or "all_access" in entitled_caps:
        return True

    capability_mapping = {
        "mango_quality_analytics": {"computer_vision_quality_analytics", "produce_quality_cv", "quality_analytics", "mango_quality_analytics", "all_access"},
        "quality_analytics": {"computer_vision_quality_analytics", "produce_quality_cv", "quality_analytics", "all_access"},
        "quality_grading": {"computer_vision_quality_analytics", "produce_quality_cv", "quality_analytics", "all_access"},
        "bike_rebalance_analytics": {"bike_mobility_ai", "mobility_analytics", "bike_rebalance_analytics", "all_access"},
        "mobility_analytics": {"bike_mobility_ai", "mobility_analytics", "all_access"},
        "bike_rebalance": {"bike_mobility_ai", "mobility_analytics", "all_access"},
        "warehouse_automation": {"warehouse_stocksense", "inventory_analytics", "warehouse_automation", "all_access"},
        "inventory_analytics": {"warehouse_stocksense", "inventory_analytics", "all_access"},
        "inventory": {"warehouse_stocksense", "inventory_analytics", "all_access"},
        "ask4_academic_order": {"ask4_custom_development", "academic_research", "ask4_academic_order", "all_access"},
        "ask4": {"ask4_custom_development", "academic_research", "all_access"},
        "academic_research": {"ask4_custom_development", "academic_research", "all_access"},
        "pixel_ai_pack": {"pixel_ai_creative_studio", "pixel_ai_pack", "all_access"},
        "pixel_ai": {"pixel_ai_creative_studio", "pixel_ai_pack", "all_access"},
        "creative_pack": {"pixel_ai_creative_studio", "pixel_ai_pack", "all_access"},
        "seo_blog_copilot": {"seo_content_automation", "seo_blog_copilot", "all_access"},
        "seo_copilot": {"seo_content_automation", "seo_blog_copilot", "all_access"},
        "marketing_suite": {"marketing_campaign_suite", "marketing_suite", "all_access"},
        "omnichannel_social": {"marketing_campaign_suite", "marketing_suite", "all_access"},
        "growth_all_in_one": {"growth_all_in_one", "all_access"},
        "growth_suite": {"growth_all_in_one", "growth_suite", "all_access"},
        "trust_engine": {"trust_ledger_audit", "trust_engine", "all_access"},
        "trust_ledger": {"trust_ledger_audit", "trust_engine", "all_access"},
        "field_force": {"field_force_automation", "field_force", "all_access"},
        "lead_generation": {"lead_generation", "customer_discovery", "smb_discovery", "growth_all_in_one", "all_access"},
        "customer_discovery": {"lead_generation", "customer_discovery", "smb_discovery", "growth_all_in_one", "all_access"},
    }

    clean_key = service_key.strip().lower()
    required = capability_mapping.get(clean_key, {clean_key})
    if pkg_key:
        clean_pkg = pkg_key.strip().lower()
        if clean_pkg == clean_key or clean_pkg in required:
            return True
        if clean_pkg in ("all_access", "company_os_enterprise", "enterprise"):
            return True
    return bool(required & entitled_caps) or clean_key in entitled_caps


def check_tenant_entitlement(
    principal: APIPrincipal,
    service_key: str,
    db: Any,
) -> Any:
    """Validate that if principal is a tenant (org_id is set), their organization is active
    and holds the entitlement for service_key. Platform operators (no org_id) pass through."""
    if not principal.org_id:
        return None

    from app.db.models import OrganizationRecord

    org = db.get(OrganizationRecord, principal.org_id)
    if not org or not org.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Organization '{principal.org_id}' is inactive or has unpaid subscription.",
        )

    pkg_key = (org.metadata_json or {}).get("package_key") or org.tier
    entitled_caps = set((org.metadata_json or {}).get("entitled_capabilities") or [])
    if not entitled_caps and pkg_key:
        from app.services.catalog import CATALOG, get_package
        pkg = get_package(pkg_key) or CATALOG.get(pkg_key)
        if pkg:
            entitled_caps = set(pkg.entitled_capabilities)

    if not is_service_entitled(service_key, entitled_caps, pkg_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Service '{service_key}' is not entitled for package '{pkg_key}'. Please upgrade your subscription.",
        )
    return org


def require_entitled_service(service_key: str):
    """FastAPI dependency enforcing entitlement for a specific service_key."""
    from app.db.database import get_db

    def dependency(
        principal: APIPrincipal = Depends(require_manager),
        db: Any = Depends(get_db),
    ) -> APIPrincipal:
        check_tenant_entitlement(principal, service_key, db)
        return principal

    return dependency
