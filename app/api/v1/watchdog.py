"""API router for System Monitoring & Controlling Watchdog Agent."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import APIPrincipal, require_platform_manager
from app.services.watchdog import (
    WatchdogAlertNotFound,
    assess_sme_business_requirements,
    control_agent_runtime,
    get_commercial_release_checklist,
    get_connector_inventory,
    get_system_control_telemetry,
    invoke_connected_tool_or_agent,
    list_watchdog_alerts,
    resolve_watchdog_alert,
    run_jaipur_sme_sandbox_scenario,
    run_system_credibility_audit,
    run_system_watchdog_scan,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/watchdog", tags=["watchdog"])


class WatchdogScanRequest(BaseModel):
    stale_minutes: int = Field(
        default=60,
        ge=1,
        le=10080,
        description="Threshold in minutes to classify pending tasks/approvals/orders as stalled",
    )


class ResolveAlertRequest(BaseModel):
    resolved_by: str = Field(default="owner", max_length=100)
    resolution_notes: str = Field(default="", max_length=1000)


class InvokeToolOrAgentRequest(BaseModel):
    target_key: str = Field(
        min_length=1,
        max_length=100,
        description="Identifier of the connected Service Tool or Specialist AI Agent to execute",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional execution parameters for the target tool or agent",
    )


@router.post("/scan")
def trigger_system_watchdog_scan(
    payload: WatchdogScanRequest | None = None,
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    _principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Execute real-time supervisory scan across tasks, approvals, field presence, and ledger integrity."""
    stale_mins = payload.stale_minutes if payload else 60
    return run_system_watchdog_scan(
        db=db,
        stale_minutes=stale_mins,
        correlation_id=x_correlation_id,
    )


@router.get("/alerts")
def get_watchdog_alerts(
    status_filter: str | None = Query(default=None, alias="status", description="Filter by status (OPEN, RESOLVED)"),
    severity: str | None = Query(default=None, description="Filter by severity (CRITICAL, HIGH, MEDIUM, LOW)"),
    limit: int = Query(default=100, ge=1, le=500),
    _principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve operational alerts flagged by the Watchdog and Supervisor Co-Pilot."""
    alerts = list_watchdog_alerts(db=db, status=status_filter, severity=severity, limit=limit)
    return {
        "count": len(alerts),
        "alerts": alerts,
    }


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(
    alert_id: str,
    payload: ResolveAlertRequest | None = None,
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    _principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Resolve an operational alert and cryptographically seal the resolution action."""
    resolved_by = payload.resolved_by if payload else "owner"
    notes = payload.resolution_notes if payload else ""
    try:
        res = resolve_watchdog_alert(
            db=db,
            alert_id=alert_id,
            resolved_by=resolved_by,
            resolution_notes=notes,
            correlation_id=x_correlation_id,
        )
        return {
            "status": "RESOLVED",
            "alert": res,
            "block_hash": res.get("block_hash"),
        }
    except WatchdogAlertNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/telemetry")
def get_watchdog_telemetry(
    _principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Compile real-time operational control telemetry for L0 Owner cockpit."""
    return get_system_control_telemetry(db=db)


@router.post("/invoke-tool")
def invoke_tool_or_agent_endpoint(
    body: InvokeToolOrAgentRequest,
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Invoke a connected Service Tool or Specialist AI Agent directly from the Company OS Command Dock."""
    try:
        return invoke_connected_tool_or_agent(
            db=db,
            target_key=body.target_key,
            payload=body.payload,
            correlation_id=x_correlation_id,
            agent_id=principal.subject or "owner-command-dock",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=str(exc),
        ) from exc


@router.post("/credibility-audit")
def trigger_system_credibility_audit(
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Run an internal end-to-end simulated environment credibility test across all 16 connected
    tools and specialist AI agents to verify 0% mocking/faking and <0.0001% failure tolerance."""
    return run_system_credibility_audit(
        db=db,
        correlation_id=x_correlation_id,
        agent_id=principal.subject or "credibility-auditor-l0",
    )


class SmeAssessmentRequest(BaseModel):
    business_name: str = Field(default="SME Enterprise", max_length=200)
    industry: str = Field(default="Distribution & Retail", max_length=200)
    city: str = Field(default="Jaipur", max_length=100)
    company_size: str = Field(default="10-50 employees", max_length=100)
    requirements_text: str = Field(
        default="Manage inventory stockouts, automate B2B lead discovery, and publish SEO content",
        max_length=2000,
    )


@router.get("/connectors")
def list_connector_inventory(
    _principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return the 10-connector truthfulness inventory classified under the 7-state CAPABILITY_STATUS_MODEL."""
    return get_connector_inventory(db=db)


@router.post("/sme-assess")
def assess_sme_requirements_endpoint(
    body: SmeAssessmentRequest,
    _principal: APIPrincipal = Depends(require_platform_manager),
) -> dict[str, Any]:
    """Assess SME business profile & requirements into modular services, specialist agents, and 13-field pricing contract."""
    return assess_sme_business_requirements(
        business_name=body.business_name,
        industry=body.industry,
        city=body.city,
        company_size=body.company_size,
        requirements_text=body.requirements_text,
    )


@router.post("/sme-sandbox-scenario")
def trigger_jaipur_sme_sandbox_scenario(
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    _principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Execute the 12-Step 'Jaipur Distribution Company' SME E2E scenario in an isolated sandbox
    with ENABLE_EXTERNAL_SIDE_EFFECTS=false, real credit deduction, and 15-field evidence verification."""
    return run_jaipur_sme_sandbox_scenario(
        db=db,
        correlation_id=x_correlation_id,
    )


class AgentControlRequest(BaseModel):
    agent_key: str = Field(default="__all__", max_length=100)
    action: str = Field(default="activate", description="activate | pause | emergency_stop | resume | configure")
    reason: str = Field(default="", max_length=500)
    budget_credits: int | None = Field(default=None, ge=0, le=100000)


@router.post("/agent-control")
def control_agent_runtime_endpoint(
    body: AgentControlRequest,
    principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Activate, pause, configure, or emergency-stop an AI agent or the entire workforce."""
    try:
        return control_agent_runtime(
            db=db,
            agent_key=body.agent_key,
            action=body.action,
            reason=body.reason,
            budget_credits=body.budget_credits,
            operator_id=principal.subject or "owner-l0",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/release-checklist")
def get_release_checklist_endpoint(
    _principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Evaluate all 12 items of the Commercial Release Acceptance Checklist with live verification evidence."""
    return get_commercial_release_checklist(db=db)


