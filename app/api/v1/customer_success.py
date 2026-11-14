"""P3 Customer Success, Retention & Repeatable Growth API Router (/v1/cs/*)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import P3GrowthOpportunityRecord, P3ImprovementItemRecord
from app.security.auth import APIPrincipal, require_manager, require_owner, require_platform_manager
from app.services.p3_customer_success import (
    confirm_customer_activation,
    create_or_get_onboarding_workflow,
    ensure_customer_account,
    get_customer_360_profile,
    list_customer_accounts,
    transition_customer_lifecycle,
    update_customer_profile_settings,
    update_onboarding_task,
)
from app.services.p3_delivery_health import (
    compute_customer_health,
    create_service_delivery,
    generate_internal_health_alerts,
    list_service_deliveries,
    record_delivery_metrics_and_outcomes,
    submit_delivery_quality_check,
    transition_delivery_quality_state,
)
from app.services.p3_ops_compliance_cc import (
    export_customer_data_bundle,
    get_operational_readiness_summary,
    get_p3_customer_ops_control_centre,
    record_backup_verification_drill,
    request_customer_deletion_or_offboarding,
    retry_dlq_workflow_run,
    run_scheduled_p3_maintenance,
    scan_and_recover_stale_workflows,
    seed_and_get_p3_acceptance_checklist,
    update_consent_and_retention,
    update_p3_acceptance_step,
)
from app.services.p3_revenue_growth import (
    CostBudgetExceededError,
    authorize_and_share_growth_opportunity,
    change_subscription_plan,
    compute_customer_unit_economics,
    enforce_grace_period_expirations,
    evaluate_expansion_opportunities,
    get_subscription_reliability_summary,
    handle_payment_failure_and_grace_period,
    record_subscription_lifecycle_event,
    record_unit_economics_cost,
    request_or_execute_refund_workflow,
    restore_subscription_after_recovery,
    serialize_growth_opportunity,
    set_customer_cost_budget,
)
from app.services.p3_1_verification_registry import get_release_readiness_summary
from app.services.p3_support_improvements import (
    add_ticket_message,
    create_support_ticket,
    list_support_tickets,
    run_ai_support_assistant,
    serialize_improvement_item,
    submit_ticket_csat,
    synthesize_improvement_loop,
    transition_ticket_state,
)
from app.services.gsc_integration import (
    GscIntegrationError,
    build_gsc_oauth_authorization_url,
    disconnect_gsc_account,
    exchange_gsc_oauth_code,
    fetch_gsc_search_analytics,
    get_gsc_status,
    verify_and_select_gsc_property,
)

router = APIRouter(prefix="/v1/cs", tags=["P3 Customer Success & Growth Engine"])


def _handle_service_err(exc: Exception) -> HTTPException:
    if isinstance(exc, GscIntegrationError):
        return HTTPException(status_code=exc.status_code, detail=f"{exc.code}: {exc.message}")
    if isinstance(exc, CostBudgetExceededError):
        return HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    msg = str(exc)
    if "not found" in msg.lower():
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
    if "honesty guard" in msg.lower():
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=msg)
    if (
        "cannot" in msg.lower()
        or "incomplete" in msg.lower()
        or "already" in msg.lower()
        or "blocked" in msg.lower()
        or ("invalid" in msg.lower() and "transition" in msg.lower())
    ):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=msg)


# ── Pydantic Request Schemas ─────────────────────────────────────────────────


class EnsureCustomerRequest(BaseModel):
    human_owner: str = Field(default="owner", max_length=200)
    acquisition_source: str | None = Field(default=None, max_length=120)
    initial_state: str = Field(default="ONBOARDING", max_length=32)
    sku_key: str | None = Field(default=None, max_length=100)
    business_goals: list[str] = Field(default_factory=list)
    expected_outcomes: list[str] = Field(default_factory=list)


class LifecycleTransitionRequest(BaseModel):
    target_state: str = Field(min_length=2, max_length=32)
    reason: str = Field(min_length=3, max_length=500)


class CustomerProfileUpdateRequest(BaseModel):
    human_owner: str | None = Field(default=None, max_length=200)
    assigned_agents: list[str] | None = None
    business_goals: list[str] | None = None
    expected_outcomes: list[str] | None = None
    renewal_date: datetime | None = None


class OnboardingTaskUpdateRequest(BaseModel):
    completed: bool
    evidence_summary: str | None = Field(default=None, max_length=1000)
    evidence_ref: str | None = Field(default=None, max_length=500)
    blockers: list[str] | None = None
    assigned_to: str | None = Field(default=None, max_length=200)
    sku_key: str | None = Field(default=None, max_length=100)


class ConfirmActivationRequest(BaseModel):
    sku_key: str | None = Field(default=None, max_length=100)
    confirmation_note: str | None = Field(default=None, max_length=500)


class CreateDeliveryRequest(BaseModel):
    org_id: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=2, max_length=250)
    original_requirement: str = Field(min_length=3, max_length=3000)
    approved_scope: list[str] = Field(default_factory=list)
    sku_key: str = Field(default="managed_seo_content_pilot", max_length=100)
    service_id: str = Field(default="seo_blog_copilot", max_length=100)
    p2_engagement_id: str | None = Field(default=None, max_length=36)
    workflow_run_id: str | None = Field(default=None, max_length=36)
    assigned_owner: str = Field(default="owner", max_length=200)
    assigned_agent_id: str | None = Field(default="service_delivery_coordinator_agent", max_length=100)
    input_data: dict[str, Any] = Field(default_factory=dict)
    source_evidence: list[dict[str, Any]] = Field(default_factory=list)
    due_days: int = Field(default=7, ge=1, le=90)


class DeliveryTransitionRequest(BaseModel):
    target_state: str = Field(min_length=2, max_length=32)
    note: str | None = Field(default=None, max_length=1000)
    output_artifacts: dict[str, Any] | None = None
    approval_checkpoint: dict[str, Any] | None = None
    source_evidence_item: dict[str, Any] | None = None


class DeliveryQARequest(BaseModel):
    passed: bool
    checks: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)
    output_artifacts: dict[str, Any] | None = None


class DeliveryMetricsRequest(BaseModel):
    output_metrics: dict[str, Any] | None = None
    outcome_metrics: dict[str, Any] | None = None


class CreateTicketRequest(BaseModel):
    org_id: str = Field(min_length=2, max_length=64)
    subject: str = Field(min_length=3, max_length=300)
    description: str = Field(min_length=3, max_length=4000)
    category: str = Field(default="general", max_length=64)
    priority: str = Field(default="MEDIUM", max_length=24)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    assigned_owner: str = Field(default="support_team", max_length=200)


class TicketTransitionRequest(BaseModel):
    target_state: str = Field(min_length=2, max_length=32)
    reason: str | None = Field(default=None, max_length=500)
    assigned_owner: str | None = Field(default=None, max_length=200)


class TicketMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    visibility: Literal["customer_visible", "internal_only", "internal_note"] = "customer_visible"
    sender_type: Literal["staff", "customer", "ai_assistant"] = "staff"
    approval_id: str | None = Field(default=None, max_length=64)


class TicketCSATRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class SubscriptionEventRequest(BaseModel):
    event_type: str = Field(min_length=2, max_length=64)
    target_state: str = Field(min_length=2, max_length=32)
    idempotency_key: str = Field(min_length=3, max_length=200)
    billing_category: str | None = Field(default=None, max_length=48)
    is_provider_confirmed: bool = False
    provider: str = Field(default="internal", max_length=32)
    provider_subscription_id: str | None = Field(default=None, max_length=200)
    internal_sku: str | None = Field(default=None, max_length=100)
    billing_interval: str | None = Field(default=None, max_length=32)
    amount: float = Field(default=0.0, ge=0.0)
    currency: str = Field(default="INR", max_length=10)
    renewal_date: datetime | None = None
    grace_until: datetime | None = None
    approval_id: str | None = Field(default=None, max_length=64)
    details: dict[str, Any] = Field(default_factory=dict)


class PaymentFailureRequest(BaseModel):
    amount: float = Field(default=0.0, ge=0.0)
    currency: str = Field(default="INR", max_length=10)
    grace_days: int = Field(default=5, ge=1, le=30)
    reason: str = Field(default="Recurring charge failed", max_length=500)
    idempotency_key: str = Field(min_length=3, max_length=200)
    provider: str = Field(default="razorpay", max_length=32)


class RestoreSubscriptionRequest(BaseModel):
    idempotency_key: str = Field(min_length=3, max_length=200)
    amount: float = Field(default=0.0, ge=0.0)
    currency: str = Field(default="INR", max_length=10)
    provider: str = Field(default="razorpay", max_length=32)
    provider_confirmed: bool = True


class RefundWorkflowRequest(BaseModel):
    amount_inr: float = Field(gt=0.0)
    currency: str = Field(default="INR", max_length=10)
    reason: str = Field(min_length=3, max_length=500)
    invoice_id: str | None = Field(default=None, max_length=100)
    approval_id: str | None = Field(default=None, max_length=64)


class PlanChangeRequest(BaseModel):
    action: Literal["upgrade", "downgrade", "configure", "cancel", "renew"] = "upgrade"
    new_sku_key: str = Field(min_length=2, max_length=100)
    selected_modules: list[str] | None = None
    billing_interval: str = Field(default="monthly", max_length=32)
    currency: str = Field(default="INR", max_length=10)
    extra_seats: int = Field(default=0, ge=0)
    extra_agents: int = Field(default=0, ge=0)
    credit_packs: int = Field(default=0, ge=0)
    integration_addons: list[str] | None = None
    customization_level: str = Field(default="standard", max_length=32)


class ShareGrowthOpportunityRequest(BaseModel):
    approval_id: str | None = Field(default=None, max_length=64)
    referred_company: str | None = Field(default=None, max_length=250)


class SetCostBudgetRequest(BaseModel):
    monthly_cost_limit_inr: float = Field(ge=0.0)
    alert_threshold_pct: float = Field(default=80.0, ge=1.0, le=100.0)
    hard_cap_enforced: bool = True
    exception_approval_id: str | None = Field(default=None, max_length=64)
    exception_limit_inr: float | None = Field(default=None, ge=0.0)


class RecordUnitCostRequest(BaseModel):
    cost_category: str = Field(min_length=2, max_length=48)
    cost_type_label: Literal["ACTUAL", "ALLOCATED", "ESTIMATED"] = "ACTUAL"
    amount_inr: float = Field(ge=0.0)
    amount_usd: float = Field(default=0.0, ge=0.0)
    service_id: str = Field(default="general", max_length=100)
    provider: str = Field(default="internal", max_length=64)
    tokens_input: int = Field(default=0, ge=0)
    tokens_output: int = Field(default=0, ge=0)
    delivery_id: str | None = Field(default=None, max_length=36)
    workflow_run_id: str | None = Field(default=None, max_length=36)
    execution_id: str | None = Field(default=None, max_length=64)
    evidence_ref: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)


class ImprovementStatusRequest(BaseModel):
    status: Literal["OPEN", "IN_BACKLOG", "PLANNED", "RESOLVED", "DISMISSED"]


class ConsentRetentionUpdateRequest(BaseModel):
    consent_preferences: dict[str, Any] | None = None
    retention_policy: dict[str, Any] | None = None


class ComplianceOffboardRequest(BaseModel):
    request_type: Literal["ACCOUNT_OFFBOARDING", "DATA_DELETION"] = "ACCOUNT_OFFBOARDING"
    reason: str = Field(min_length=3, max_length=500)
    approval_id: str | None = Field(default=None, max_length=64)


class BackupDrillRequest(BaseModel):
    target_scope: str = Field(default="postgresql_primary_database", min_length=3, max_length=200)
    restore_tested: bool
    recovery_point_objective_minutes: int | None = Field(default=None, ge=0)
    recovery_time_seconds: float | None = Field(default=None, ge=0.0)
    evidence_ref: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)


class AcceptanceStepUpdateRequest(BaseModel):
    verification_status: Literal["NOT_TESTED", "SANDBOX_VERIFIED", "LIVE_VERIFIED"]
    evidence_summary: str = Field(min_length=3, max_length=2000)
    evidence_ref: str | None = Field(default=None, max_length=500)


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/control-centre", summary="Founder Control Centre: Customer Operations KPIs")
def cs_control_centre(
    period_days: int = Query(default=30, ge=1, le=365),
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_p3_customer_ops_control_centre(db, period_days=period_days)


@router.get("/customers", summary="List Customer Success accounts")
def cs_list_customers(
    lifecycle_state: str | None = None,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = list_customer_accounts(db, lifecycle_state=lifecycle_state)
    return {"count": len(rows), "customers": rows}


@router.post("/customers/{org_id}/ensure", summary="Ensure P3 Customer Success account exists")
def cs_ensure_customer(
    org_id: str,
    body: EnsureCustomerRequest,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        ensure_customer_account(
            db,
            org_id=org_id,
            human_owner=body.human_owner,
            acquisition_source=body.acquisition_source,
            initial_state=body.initial_state,
            business_goals=body.business_goals or None,
            expected_outcomes=body.expected_outcomes or None,
            sku_key=body.sku_key,
            commit=True,
        )
        return get_customer_360_profile(db, org_id=org_id)
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.get("/customers/{org_id}", summary="Customer 360 profile")
def cs_get_customer_360(
    org_id: str,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return get_customer_360_profile(db, org_id=org_id)
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/customers/{org_id}/lifecycle", summary="Validated & audited lifecycle state transition")
def cs_transition_lifecycle(
    org_id: str,
    body: LifecycleTransitionRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return transition_customer_lifecycle(
            db, org_id=org_id, target_state=body.target_state, reason=body.reason, actor=principal.subject
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.patch("/customers/{org_id}/profile", summary="Update customer CS owner, agents, goals, renewal date")
def cs_update_customer_profile(
    org_id: str,
    body: CustomerProfileUpdateRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return update_customer_profile_settings(
            db,
            org_id=org_id,
            human_owner=body.human_owner,
            assigned_agents=body.assigned_agents,
            business_goals=body.business_goals,
            expected_outcomes=body.expected_outcomes,
            renewal_date=body.renewal_date,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.get("/customers/{org_id}/onboarding", summary="Get or create configurable product onboarding workflow")
def cs_get_onboarding(
    org_id: str,
    sku_key: str | None = None,
    template_key: str | None = None,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return create_or_get_onboarding_workflow(
            db, org_id=org_id, sku_key=sku_key, template_key=template_key, actor=principal.subject
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.patch("/customers/{org_id}/onboarding/tasks/{task_key}", summary="Update onboarding task completion & blockers")
def cs_update_onboarding_task(
    org_id: str,
    task_key: str,
    body: OnboardingTaskUpdateRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return update_onboarding_task(
            db,
            org_id=org_id,
            task_key=task_key,
            completed=body.completed,
            evidence_summary=body.evidence_summary,
            evidence_ref=body.evidence_ref,
            blockers=body.blockers,
            assigned_to=body.assigned_to,
            sku_key=body.sku_key,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/customers/{org_id}/onboarding/confirm-activation", summary="Enforce readiness criteria & confirm ACTIVE state")
def cs_confirm_activation(
    org_id: str,
    body: ConfirmActivationRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return confirm_customer_activation(
            db, org_id=org_id, sku_key=body.sku_key, confirmation_note=body.confirmation_note, actor=principal.subject
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.get("/deliveries", summary="List customer service deliveries")
def cs_list_deliveries(
    org_id: str | None = None,
    quality_state: str | None = None,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = list_service_deliveries(db, org_id=org_id, quality_state=quality_state)
    return {"count": len(rows), "deliveries": rows}


@router.post("/deliveries", summary="Create service delivery engagement & scope record")
def cs_create_delivery(
    body: CreateDeliveryRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return create_service_delivery(
            db,
            org_id=body.org_id,
            title=body.title,
            original_requirement=body.original_requirement,
            approved_scope=body.approved_scope,
            sku_key=body.sku_key,
            service_id=body.service_id,
            p2_engagement_id=body.p2_engagement_id,
            workflow_run_id=body.workflow_run_id,
            assigned_owner=body.assigned_owner,
            assigned_agent_id=body.assigned_agent_id,
            input_data=body.input_data,
            source_evidence=body.source_evidence,
            due_days=body.due_days,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/deliveries/{delivery_id}/transition", summary="Transition deliverable quality state")
def cs_transition_delivery(
    delivery_id: str,
    body: DeliveryTransitionRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return transition_delivery_quality_state(
            db,
            delivery_id=delivery_id,
            target_state=body.target_state,
            note=body.note,
            output_artifacts=body.output_artifacts,
            approval_checkpoint=body.approval_checkpoint,
            source_evidence_item=body.source_evidence_item,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/deliveries/{delivery_id}/qa-review", summary="Record QA verification checks on a deliverable")
def cs_qa_review_delivery(
    delivery_id: str,
    body: DeliveryQARequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return submit_delivery_quality_check(
            db,
            delivery_id=delivery_id,
            passed=body.passed,
            checks=body.checks,
            reviewer=principal.subject,
            output_artifacts=body.output_artifacts,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/deliveries/{delivery_id}/metrics", summary="Record separated output vs Search Console outcome metrics")
def cs_record_delivery_metrics(
    delivery_id: str,
    body: DeliveryMetricsRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return record_delivery_metrics_and_outcomes(
            db,
            delivery_id=delivery_id,
            output_metrics=body.output_metrics,
            outcome_metrics=body.outcome_metrics,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.get("/customers/{org_id}/health", summary="Compute explainable Customer Health Score")
def cs_get_health(
    org_id: str,
    save_snapshot: bool = True,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return compute_customer_health(db, org_id=org_id, save_snapshot=save_snapshot)
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/customers/{org_id}/health/alerts", summary="Generate internal early-warning churn/blocker alerts")
def cs_generate_health_alerts(
    org_id: str,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        alerts = generate_internal_health_alerts(db, org_id=org_id)
        return {"org_id": org_id, "count": len(alerts), "alerts": alerts}
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.get("/support/tickets", summary="List customer support tickets")
def cs_list_tickets(
    org_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = list_support_tickets(db, org_id=org_id, status=status_filter, include_internal=True)
    return {"count": len(rows), "tickets": rows}


@router.post("/support/tickets", summary="Open support ticket for customer org")
def cs_create_ticket(
    body: CreateTicketRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return create_support_ticket(
            db,
            org_id=body.org_id,
            subject=body.subject,
            description=body.description,
            category=body.category,
            priority=body.priority,
            created_by_user_id=principal.user_id,
            created_by_email=principal.email,
            attachments=body.attachments,
            assigned_owner=body.assigned_owner,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/support/tickets/{ticket_id}/transition", summary="Transition support ticket status")
def cs_transition_ticket(
    ticket_id: str,
    body: TicketTransitionRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return transition_ticket_state(
            db,
            ticket_id=ticket_id,
            target_state=body.target_state,
            assigned_owner=body.assigned_owner,
            escalation_reason=body.reason if body.target_state.upper() == "ESCALATED" else None,
            internal_note=body.reason,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/support/tickets/{ticket_id}/messages", summary="Post internal note or customer-visible reply (HITL checked)")
def cs_add_ticket_message(
    ticket_id: str,
    body: TicketMessageRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return add_ticket_message(
            db,
            ticket_id=ticket_id,
            body=body.body,
            visibility=body.visibility,
            sender_type=body.sender_type,
            sender=principal.subject,
            approval_id=body.approval_id,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/support/tickets/{ticket_id}/ai-assist", summary="Run docs-grounded AI Support Assistant triage")
def cs_ai_assist_ticket(
    ticket_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return run_ai_support_assistant(db, ticket_id=ticket_id, actor=principal.subject)
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/support/tickets/{ticket_id}/csat", summary="Record CSAT rating on ticket")
def cs_submit_ticket_csat(
    ticket_id: str,
    body: TicketCSATRequest,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return submit_ticket_csat(db, ticket_id=ticket_id, rating=body.rating, comment=body.comment)
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.get("/subscriptions/reliability", summary="Upcoming renewals, verified provider subscriptions & history")
def cs_subscription_reliability(
    org_id: str | None = None,
    days_ahead: int = Query(default=30, ge=1, le=365),
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_subscription_reliability_summary(db, org_id=org_id, days_ahead=days_ahead)


@router.post("/subscriptions/{org_id}/events", summary="Record idempotent subscription lifecycle event")
def cs_record_subscription_event(
    org_id: str,
    body: SubscriptionEventRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return record_subscription_lifecycle_event(
            db,
            org_id=org_id,
            event_type=body.event_type,
            target_state=body.target_state,
            idempotency_key=body.idempotency_key,
            billing_category=body.billing_category,
            is_provider_confirmed=body.is_provider_confirmed,
            provider=body.provider,
            provider_subscription_id=body.provider_subscription_id,
            internal_sku=body.internal_sku,
            billing_interval=body.billing_interval,
            amount=body.amount,
            currency=body.currency,
            renewal_date=body.renewal_date,
            grace_until=body.grace_until,
            approval_id=body.approval_id,
            actor=principal.subject,
            details=body.details,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/subscriptions/{org_id}/payment-failure", summary="Trigger PAST_DUE grace period on recurring payment failure")
def cs_payment_failure(
    org_id: str,
    body: PaymentFailureRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return handle_payment_failure_and_grace_period(
            db,
            org_id=org_id,
            amount=body.amount,
            currency=body.currency,
            grace_days=body.grace_days,
            reason=body.reason,
            idempotency_key=body.idempotency_key,
            provider=body.provider,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/subscriptions/enforce-grace", summary="Suspend expired PAST_DUE subscriptions")
def cs_enforce_grace(
    org_id: str | None = None,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    suspended = enforce_grace_period_expirations(db, org_id=org_id)
    return {"suspended_count": len(suspended), "suspended": suspended}


@router.post("/subscriptions/{org_id}/restore", summary="Restore suspended subscription after verified payment recovery")
def cs_restore_subscription(
    org_id: str,
    body: RestoreSubscriptionRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return restore_subscription_after_recovery(
            db,
            org_id=org_id,
            amount=body.amount,
            currency=body.currency,
            provider=body.provider,
            provider_confirmed=body.provider_confirmed,
            idempotency_key=body.idempotency_key,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/subscriptions/{org_id}/refund", summary="Owner HITL-gated refund request/execution")
def cs_refund_workflow(
    org_id: str,
    body: RefundWorkflowRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return request_or_execute_refund_workflow(
            db,
            org_id=org_id,
            amount=body.amount_inr,
            currency=body.currency,
            reason=body.reason,
            invoice_id=body.invoice_id,
            approval_id=body.approval_id,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/subscriptions/{org_id}/plan-change", summary="Upgrade or downgrade catalog subscription SKU")
def cs_plan_change(
    org_id: str,
    body: PlanChangeRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return change_subscription_plan(
            db,
            org_id=org_id,
            action=body.action,
            base_plan_key=body.new_sku_key,
            selected_modules=body.selected_modules,
            billing_interval=body.billing_interval,
            currency=body.currency,
            extra_seats=body.extra_seats,
            extra_agents=body.extra_agents,
            credit_packs=body.credit_packs,
            integration_addons=body.integration_addons,
            customization_level=body.customization_level,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/growth/{org_id}/evaluate", summary="Identify catalog-grounded expansion & referral opportunities")
def cs_evaluate_growth(
    org_id: str,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        opps = evaluate_expansion_opportunities(db, org_id=org_id)
        return {"org_id": org_id, "count": len(opps), "opportunities": opps}
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.get("/growth", summary="List expansion & referral opportunities")
def cs_list_growth(
    org_id: str | None = None,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    q = db.query(P3GrowthOpportunityRecord)
    if org_id:
        q = q.filter(P3GrowthOpportunityRecord.org_id == org_id)
    rows = q.order_by(P3GrowthOpportunityRecord.created_at.desc()).all()
    return {"count": len(rows), "opportunities": [serialize_growth_opportunity(r) for r in rows]}


@router.post("/growth/opportunities/{opp_id}/share", summary="HITL-gated expansion offer / referral share")
def cs_share_growth_opportunity(
    opp_id: str,
    body: ShareGrowthOpportunityRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return authorize_and_share_growth_opportunity(
            db,
            opportunity_id=opp_id,
            approval_id=body.approval_id,
            referred_company=body.referred_company,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.put("/unit-economics/{org_id}/budget", summary="Configure monthly cost limit & exception override")
def cs_set_cost_budget(
    org_id: str,
    body: SetCostBudgetRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return set_customer_cost_budget(
            db,
            org_id=org_id,
            monthly_cost_limit_inr=body.monthly_cost_limit_inr,
            alert_threshold_pct=body.alert_threshold_pct,
            hard_cap_enforced=body.hard_cap_enforced,
            exception_approval_id=body.exception_approval_id,
            exception_limit_inr=body.exception_limit_inr,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/unit-economics/{org_id}/costs", summary="Record ACTUAL/ALLOCATED/ESTIMATED delivery cost")
def cs_record_cost(
    org_id: str,
    body: RecordUnitCostRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return record_unit_economics_cost(
            db,
            org_id=org_id,
            cost_category=body.cost_category,
            cost_type_label=body.cost_type_label,
            amount_inr=body.amount_inr,
            amount_usd=body.amount_usd,
            service_id=body.service_id,
            provider=body.provider,
            tokens_input=body.tokens_input,
            tokens_output=body.tokens_output,
            delivery_id=body.delivery_id,
            workflow_run_id=body.workflow_run_id,
            execution_id=body.execution_id,
            evidence_ref=body.evidence_ref,
            notes=body.notes,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.get("/unit-economics/{org_id}", summary="Customer unit economics & margin summary")
def cs_get_unit_economics(
    org_id: str,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return compute_customer_unit_economics(db, org_id=org_id)
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/improvements/synthesize", summary="Cluster tickets, revisions, CSAT & blockers into Improvement Loop")
def cs_synthesize_improvements(
    org_id: str | None = None,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    items = synthesize_improvement_loop(db, org_id=org_id)
    return {"count": len(items), "improvements": items}


@router.get("/improvements", summary="List prioritized Product & Service Improvement Loop items")
def cs_list_improvements(
    status_filter: str | None = Query(default=None, alias="status"),
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    q = db.query(P3ImprovementItemRecord)
    if status_filter:
        q = q.filter(P3ImprovementItemRecord.status == status_filter.strip().upper())
    rows = q.order_by(P3ImprovementItemRecord.priority_score.desc()).all()
    return {"count": len(rows), "improvements": [serialize_improvement_item(r) for r in rows]}


@router.patch("/improvements/{item_id}", summary="Update improvement item triage status")
def cs_update_improvement_status(
    item_id: str,
    body: ImprovementStatusRequest,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    item = db.get(P3ImprovementItemRecord, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Improvement item not found")
    item.status = body.status
    db.add(item)
    db.commit()
    db.refresh(item)
    return serialize_improvement_item(item)


@router.patch("/compliance/{org_id}/consent-retention", summary="Update DPDP/GDPR consent, retention & legal hold")
def cs_update_consent_retention(
    org_id: str,
    body: ConsentRetentionUpdateRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return update_consent_and_retention(
            db,
            org_id=org_id,
            consent_preferences=body.consent_preferences,
            retention_policy=body.retention_policy,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/compliance/{org_id}/export", summary="Export org-scoped secret-redacted customer data bundle")
def cs_export_customer_data(
    org_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return export_customer_data_bundle(db, org_id=org_id, requested_by=principal.subject, customer_safe_only=False)
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/compliance/{org_id}/offboard-delete", summary="Legal-hold & Owner HITL gated deletion / offboarding")
def cs_offboard_or_delete(
    org_id: str,
    body: ComplianceOffboardRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return request_customer_deletion_or_offboarding(
            db,
            org_id=org_id,
            request_type=body.request_type,
            requested_by=principal.subject,
            reason=body.reason,
            approval_id=body.approval_id,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.get("/ops/readiness", summary="Multi-tenant concurrency, DB latency, connectors, DLQ & backup drills")
def cs_ops_readiness(
    org_id: str | None = None,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_operational_readiness_summary(db, org_id=org_id)


@router.post("/ops/workflows/scan-timeouts", summary="Detect stale/timed-out workflow runs & move to DLQ")
def cs_scan_timeouts(
    timeout_seconds: int | None = Query(default=None, ge=10, le=86400),
    org_id: str | None = None,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return scan_and_recover_stale_workflows(db, timeout_seconds=timeout_seconds, org_id=org_id, actor=principal.subject)


@router.post("/ops/dlq/{incident_id}/retry", summary="Re-queue failed/timed-out workflow run from DLQ")
def cs_retry_dlq(
    incident_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return retry_dlq_workflow_run(db, incident_id=incident_id, actor=principal.subject)
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/ops/backup-drill", summary="Record verified database backup & restore drill evidence")
def cs_record_backup_drill(
    body: BackupDrillRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return record_backup_verification_drill(
        db,
        verified_by=principal.subject,
        target_scope=body.target_scope,
        restore_tested=body.restore_tested,
        recovery_point_objective_minutes=body.recovery_point_objective_minutes,
        recovery_time_seconds=body.recovery_time_seconds,
        evidence_ref=body.evidence_ref,
        notes=body.notes,
    )


@router.post("/ops/run-maintenance", summary="Run scheduled P3 maintenance sweep (grace, timeouts, health alerts)")
def cs_run_scheduled_maintenance(
    org_id: str | None = None,
    stale_timeout_seconds: int = Query(default=600, ge=10, le=86400),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return run_scheduled_p3_maintenance(
        db,
        org_id=org_id,
        stale_timeout_seconds=stale_timeout_seconds,
        actor=principal.subject,
    )


@router.get("/acceptance", summary="Get 12-step P3 real-world verification checklist")
def cs_get_acceptance(
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    steps = seed_and_get_p3_acceptance_checklist(db)
    return {
        "steps": steps,
        "summary": {
            "live_verified_count": sum(1 for s in steps if s["verification_status"] == "LIVE_VERIFIED"),
            "sandbox_verified_count": sum(1 for s in steps if s["verification_status"] == "SANDBOX_VERIFIED"),
            "not_tested_count": sum(1 for s in steps if s["verification_status"] == "NOT_TESTED"),
        },
    }


@router.post("/acceptance/{step_number}", summary="Update verification status of a P3 acceptance step")
def cs_update_acceptance(
    step_number: int,
    body: AcceptanceStepUpdateRequest,
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return update_p3_acceptance_step(
            db,
            step_number=step_number,
            verification_status=body.verification_status,
            evidence_summary=body.evidence_summary,
            evidence_ref=body.evidence_ref,
            verified_by=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


# ── P3.1 Google Search Console Integration & Attribution ────────────────────


class GscOAuthUrlRequest(BaseModel):
    redirect_uri: str | None = Field(default=None, max_length=500)
    scopes: list[str] | None = None


class GscOAuthExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    state: str = Field(min_length=1, max_length=500)
    redirect_uri: str | None = Field(default=None, max_length=500)


class GscPropertyVerifyRequest(BaseModel):
    site_url: str = Field(min_length=3, max_length=500)


class GscAnalyticsQueryRequest(BaseModel):
    start_date: str = Field(min_length=10, max_length=10)
    end_date: str = Field(min_length=10, max_length=10)
    dimensions: list[str] | None = None
    row_limit: int = Field(default=250, ge=1, le=5000)
    baseline_start_date: str | None = Field(default=None, max_length=10)
    baseline_end_date: str | None = Field(default=None, max_length=10)
    delivery_id: str | None = Field(default=None, max_length=64)
    claimed_askforwrite_caused: bool = False


@router.get("/integrations/gsc/{org_id}/status", summary="Inspect GSC integration verification state")
def cs_gsc_status(
    org_id: str,
    _principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_gsc_status(db, org_id=org_id)


@router.post("/integrations/gsc/{org_id}/oauth/url", summary="Generate GSC OAuth 2.0 consent URL with CSRF state")
def cs_gsc_oauth_url(
    org_id: str,
    body: GscOAuthUrlRequest,
    principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return build_gsc_oauth_authorization_url(
            db,
            org_id=org_id,
            redirect_uri=body.redirect_uri,
            scopes=body.scopes,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/integrations/gsc/{org_id}/oauth/exchange", summary="Exchange GSC OAuth code and encrypt tokens")
def cs_gsc_oauth_exchange(
    org_id: str,
    body: GscOAuthExchangeRequest,
    principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return exchange_gsc_oauth_code(
            db,
            org_id=org_id,
            code=body.code,
            state=body.state,
            redirect_uri=body.redirect_uri,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/integrations/gsc/{org_id}/properties/verify", summary="Verify and bind a GSC property to organization")
def cs_gsc_verify_property(
    org_id: str,
    body: GscPropertyVerifyRequest,
    principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return verify_and_select_gsc_property(
            db,
            org_id=org_id,
            site_url=body.site_url,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/integrations/gsc/{org_id}/analytics/query", summary="Fetch GSC searchAnalytics and persist attribution evidence")
def cs_gsc_analytics_query(
    org_id: str,
    body: GscAnalyticsQueryRequest,
    principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return fetch_gsc_search_analytics(
            db,
            org_id=org_id,
            start_date=body.start_date,
            end_date=body.end_date,
            dimensions=body.dimensions,
            row_limit=body.row_limit,
            baseline_start_date=body.baseline_start_date,
            baseline_end_date=body.baseline_end_date,
            delivery_id=body.delivery_id,
            claimed_askforwrite_caused=body.claimed_askforwrite_caused,
            actor=principal.subject,
        )
    except Exception as exc:
        raise _handle_service_err(exc) from exc


@router.post("/integrations/gsc/{org_id}/disconnect", summary="Revoke/remove GSC OAuth tokens and mark BLOCKED")
def cs_gsc_disconnect(
    org_id: str,
    principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return disconnect_gsc_account(db, org_id=org_id, actor=principal.subject)


@router.get("/release-readiness", summary="Aggregate honest P3.1 production verification & release-readiness summary")
def cs_release_readiness(
    org_id: str | None = None,
    probe_live_health: bool = False,
    _principal: APIPrincipal = Depends(require_platform_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_release_readiness_summary(db, org_id=org_id, probe_live_health=probe_live_health)
