"""Neon Services API Router.

Provides telemetry, operational status, and invocation endpoints for:
- Neon Postgres
- Neon Functions
- Neon Auth
- Neon Realtime
"""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status

from app.security.auth import APIPrincipal, require_manager
from app.services.neon_bridge import get_neon_status, invoke_neon_function

router = APIRouter(prefix="/v1/neon", tags=["Neon Platform Integration"])


@router.get("/status", status_code=status.HTTP_200_OK)
def neon_status_endpoint() -> Dict[str, Any]:
    """Retrieve end-to-end health and operational status of all provisioned Neon cloud services."""
    return get_neon_status()


@router.post("/functions/{function_name}/invoke", status_code=status.HTTP_200_OK)
async def invoke_neon_function_endpoint(
    function_name: str,
    principal: APIPrincipal = Depends(require_manager),
) -> Dict[str, Any]:
    """Invoke a deployed Neon Function (e.g. 'hello')."""
    try:
        return await invoke_neon_function(function_name=function_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

