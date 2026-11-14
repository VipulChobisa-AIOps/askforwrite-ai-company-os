"""Unified Service, Agent, Connector, and Execution Evidence Registry API router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import APIPrincipal, get_current_principal, require_tenant_operator
from app.services.connectors import configure_connector, verify_connector
from app.services.evidence import get_execution_evidence, list_execution_evidence
from app.services.execution_guard import ExecutionBlockedError
from app.services.registry import (
    SERVICE_REGISTRY,
    configure_agent_for_tenant,
    execute_registered_agent,
    get_agent_detail,
    get_agent_execution_history,
    get_connector_registry_view,
    list_registered_agents,
    list_registered_services,
    serialize_service,
    set_agent_activation,
)

router = APIRouter(prefix="/v1/registry", tags=["unified-registry"])


def get_optional_principal(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    x_gemini_api_key: str | None = Header(default=None),
) -> APIPrincipal | None:
    """Resolve principal if auth headers are present; reject invalid tokens but allow unauthenticated public catalog discovery."""
    if not x_api_key and not authorization:
        return None
    return get_current_principal(
        x_api_key=x_api_key,
        authorization=authorization,
        x_gemini_api_key=x_gemini_api_key,
    )


class AgentConfigureRequest(BaseModel):
    model_override: str | None = Field(default=None, max_length=120)
    execution_mode: str | None = Field(default=None, max_length=32)
    custom_instructions: str | None = Field(default=None, max_length=4000)
    tool_allowlist: list[str] | None = Field(default=None)
    execution_limits: dict[str, Any] | None = Field(default=None)


class AgentExecuteRequest(BaseModel):
    input_payload: dict[str, Any] = Field(default_factory=dict)
    execution_mode: str | None = Field(default=None, max_length=32)
    requested_tools: list[str] | None = Field(default=None)
    idempotency_key: str | None = Field(default=None, max_length=200)


class ConnectorConfigureRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    environment: str | None = Field(default=None, max_length=32)


class ConnectorVerifyRequest(BaseModel):
    mode: str | None = Field(default=None, max_length=32)


@router.get("/services")
def list_services_endpoint(
    category: str | None = Query(default=None),
    principal: APIPrincipal | None = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List all services from the single source-of-truth Service Registry."""
    return list_registered_services(db, principal=principal, category=category)


@router.get("/services/{service_id}")
def get_service_endpoint(
    service_id: str,
    principal: APIPrincipal | None = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get detailed Service Registry entry by ID."""
    svc = SERVICE_REGISTRY.get(service_id)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Service '{service_id}' not found")
    data = list_registered_services(db, principal=principal)
    match = next((s for s in data["services"] if s["service_id"] == service_id), None)
    return match or serialize_service(svc)


@router.get("/agents")
def list_agents_endpoint(
    business_function: str | None = Query(default=None),
    principal: APIPrincipal | None = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Agent Discovery API returning all specialist agents merged with tenant configuration."""
    return list_registered_agents(db, principal=principal, business_function=business_function)


@router.get("/agents/{agent_id}")
def get_agent_endpoint(
    agent_id: str,
    principal: APIPrincipal | None = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Agent Detail API returning full 15-field agent specification."""
    return get_agent_detail(db, agent_id, principal=principal)


@router.post("/agents/{agent_id}/activate")
def activate_agent_endpoint(
    agent_id: str,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Activate an agent for the authenticated organization after verifying entitlement & tenant identity."""
    agent = set_agent_activation(db, agent_id=agent_id, principal=principal, active=True)
    return {"status": "ACTIVATED", "agent": agent}


@router.post("/agents/{agent_id}/deactivate")
def deactivate_agent_endpoint(
    agent_id: str,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Deactivate an agent for the authenticated organization."""
    agent = set_agent_activation(db, agent_id=agent_id, principal=principal, active=False)
    return {"status": "DEACTIVATED", "agent": agent}


@router.patch("/agents/{agent_id}/configure")
def configure_agent_endpoint(
    agent_id: str,
    body: AgentConfigureRequest,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Configure tenant-specific model, tool allowlist, instructions, and limits for an agent."""
    agent = configure_agent_for_tenant(
        db,
        agent_id=agent_id,
        principal=principal,
        model_override=body.model_override,
        execution_mode=body.execution_mode,
        custom_instructions=body.custom_instructions,
        tool_allowlist=body.tool_allowlist,
        execution_limits=body.execution_limits,
    )
    return {"status": "CONFIGURED", "agent": agent}


@router.post("/agents/{agent_id}/execute")
def execute_agent_endpoint(
    agent_id: str,
    body: AgentExecuteRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Execute a registered AI agent cleanly with credit reservation, emergency-stop guard, and 18-field evidence."""
    return execute_registered_agent(
        db,
        agent_id=agent_id,
        principal=principal,
        input_payload=body.input_payload,
        execution_mode=body.execution_mode,
        requested_tools=body.requested_tools,
        idempotency_key=body.idempotency_key,
    )


@router.get("/agents/{agent_id}/history")
def get_agent_history_endpoint(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve tenant-scoped execution history & evidence references for an agent."""
    return get_agent_execution_history(db, agent_id=agent_id, principal=principal, limit=limit)


@router.get("/connectors")
def list_connectors_endpoint(
    principal: APIPrincipal | None = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Connector Status API returning all connectors with 7-state verification & masked config summaries."""
    if principal:
        return get_connector_registry_view(db, principal)
    from app.services.connectors import list_connectors

    conns = list_connectors(db, org_id="__platform__")
    return {"count": len(conns), "connectors": conns}


@router.post("/connectors/{connector_id}/configure")
def configure_connector_endpoint(
    connector_id: str,
    body: ConnectorConfigureRequest,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Configure connector parameters cleanly with automatic secret masking."""
    org_scope = principal.org_id or "__platform__"
    try:
        conn = configure_connector(
            db,
            connector_id=connector_id,
            org_id=org_scope,
            settings_payload=body.settings,
            environment=body.environment,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "CONFIGURED_UNVERIFIED", "connector": conn}


@router.post("/connectors/{connector_id}/verify")
def verify_connector_endpoint(
    connector_id: str,
    body: ConnectorVerifyRequest | None = None,
    principal: APIPrincipal = Depends(require_tenant_operator),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Run honest verification check for a connector without fabricating LIVE_VERIFIED."""
    org_scope = principal.org_id or "__platform__"
    try:
        result = verify_connector(
            db,
            connector_id=connector_id,
            org_id=org_scope,
            mode=body.mode if body else None,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExecutionBlockedError as exc:
        raise HTTPException(status_code=403, detail=exc.reason) from exc
    return {"status": result["capability_state"], "connector": result}


@router.get("/evidence")
def list_evidence_endpoint(
    agent_id: str | None = Query(default=None),
    workflow_id: str | None = Query(default=None),
    execution_mode: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Query durable 18-field ExecutionEvidence records strictly scoped to the caller's organization."""
    tenant_scope = principal.org_id if principal.org_id else None
    rows = list_execution_evidence(
        db,
        tenant_id=tenant_scope,
        agent_id=agent_id,
        workflow_id=workflow_id,
        execution_mode=execution_mode,
        status=status,
        limit=limit,
    )
    return {"count": len(rows), "records": rows}


@router.get("/evidence/{execution_id}")
def get_evidence_detail_endpoint(
    execution_id: str,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve a single 18-field ExecutionEvidence record enforcing tenant isolation."""
    tenant_scope = principal.org_id if principal.org_id else None
    rec = get_execution_evidence(db, execution_id, tenant_id=tenant_scope)
    if not rec:
        raise HTTPException(status_code=404, detail="Execution evidence record not found")
    return rec
