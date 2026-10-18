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
) -> APIPrincipal:
    """Resolve API principal from either X-API-Key header OR Bearer token."""
    # 1. Bearer Token Resolution (Customer / Admin Login)
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        payload = decode_access_token(token)
        return APIPrincipal(
            subject=payload.get("email") or payload.get("sub", "unknown"),
            role=payload.get("role", "customer"),
            user_id=payload.get("sub"),
            org_id=payload.get("org_id"),
            email=payload.get("email"),
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
            return APIPrincipal(subject=subject, role=role)

    raise HTTPException(status_code=401, detail="Invalid API key")


def require_manager(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    if principal.role not in {"owner", "manager", "admin"}:
        raise HTTPException(status_code=403, detail="Manager role required")
    return principal


def require_owner(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    if principal.role != "owner":
        raise HTTPException(status_code=403, detail="Owner role required")
    return principal


def require_admin(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    """Require Owner or Admin role."""
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admin role required")
    return principal


def require_authenticated_user(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    """Any authenticated tenant user, customer, or admin."""
    return principal


def enforce_tenant_access(principal: APIPrincipal, target_org_id: str | None) -> None:
    """Ensure that non-owner principals cannot access or mutate resources outside their organization."""
    if not target_org_id:
        return
    # System owners and platform managers have global administrative oversight
    if principal.role in {"owner", "manager"} and not principal.org_id:
        return
    # If the principal is tied to a specific organization, access across org boundaries is strictly forbidden
    if principal.org_id and principal.org_id != target_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: principal belongs to organization '{principal.org_id}', not '{target_org_id}'",
        )