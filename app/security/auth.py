"""API-key authentication and role authorization for gateway routes."""

import hmac
import os
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException


@dataclass(frozen=True)
class APIPrincipal:
    subject: str
    role: str


def get_current_principal(
    x_api_key: str | None = Header(default=None),
) -> APIPrincipal:
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
    if principal.role not in {"owner", "manager"}:
        raise HTTPException(status_code=403, detail="Manager role required")
    return principal


def require_owner(
    principal: APIPrincipal = Depends(get_current_principal),
) -> APIPrincipal:
    if principal.role != "owner":
        raise HTTPException(status_code=403, detail="Owner role required")
    return principal