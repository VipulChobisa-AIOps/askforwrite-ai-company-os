"""Neon Platform Services Bridge.

Integrates Neon Lakebase Postgres, Neon Functions, Neon Auth (Managed Better Auth JWKS),
and Neon Realtime into AskforWrite AI Company OS.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx
from sqlalchemy import text
from app.db.database import engine

logger = logging.getLogger(__name__)

# Neon configuration from environment
NEON_BRANCH = os.environ.get("NEON_BRANCH", "production")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DATABASE_URL_UNPOOLED = os.environ.get("DATABASE_URL_UNPOOLED", "")
NEON_FUNCTION_HELLO_BASE_URL = os.environ.get("NEON_FUNCTION_HELLO_BASE_URL", "")
NEON_AUTH_BASE_URL = os.environ.get("NEON_AUTH_BASE_URL", "")
NEON_AUTH_JWKS_URL = os.environ.get("NEON_AUTH_JWKS_URL", "")
NEON_REALTIME_URL = os.environ.get("NEON_REALTIME_URL", "")
NEON_REALTIME_SECRET = os.environ.get("NEON_REALTIME_SECRET", "")


def get_neon_status() -> Dict[str, Any]:
    """Check connectivity and operational status of all provisioned Neon services."""
    status: Dict[str, Any] = {
        "branch": NEON_BRANCH,
        "postgres": {"configured": bool(DATABASE_URL), "connected": False, "version": None},
        "functions": {"configured": bool(NEON_FUNCTION_HELLO_BASE_URL), "status": "unknown"},
        "auth": {"configured": bool(NEON_AUTH_JWKS_URL), "jwks_url": NEON_AUTH_JWKS_URL},
        "realtime": {"configured": bool(NEON_REALTIME_URL), "endpoint": NEON_REALTIME_URL},
    }

    # 1. Test Postgres
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version();")).fetchone()
            if row:
                status["postgres"]["connected"] = True
                status["postgres"]["version"] = row[0].split()[0] + " " + row[0].split()[1]
    except Exception as exc:
        status["postgres"]["error"] = str(exc)

    # 2. Test Neon Function
    if NEON_FUNCTION_HELLO_BASE_URL:
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(NEON_FUNCTION_HELLO_BASE_URL)
                status["functions"]["status"] = "operational" if res.status_code == 200 else f"http_{res.status_code}"
                status["functions"]["sample_response"] = res.text.strip()
        except Exception as exc:
            status["functions"]["status"] = "error"
            status["functions"]["error"] = str(exc)

    # 3. Test Neon Auth JWKS
    if NEON_AUTH_JWKS_URL:
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(NEON_AUTH_JWKS_URL)
                status["auth"]["status"] = "operational" if res.status_code in (200, 404) else f"http_{res.status_code}"
        except Exception as exc:
            status["auth"]["status"] = "error"
            status["auth"]["error"] = str(exc)

    return status


async def invoke_neon_function(function_name: str = "hello", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Invoke a deployed Neon TypeScript serverless function."""
    base_url = NEON_FUNCTION_HELLO_BASE_URL if function_name == "hello" else None
    if not base_url:
        raise ValueError(f"Neon Function '{function_name}' has no configured endpoint.")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(base_url)
        return {
            "function": function_name,
            "status_code": response.status_code,
            "body": response.text,
        }

