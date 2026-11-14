"""P5 Productization & Multi-Customer Scale service layer.

Implements:
- Catalog-grounded multi-tenant onboarding templates (bound strictly to CATALOG + MODULAR_SME_TIERS)
- Idempotent 9-state Tenant Provisioning State Machine with retry/recovery
- Per-tenant rate limit, quota, credit budget, and SLA policies + usage evaluation
- Multi-tenant operational incident tracking and SLA deadlines
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    OrganizationRecord,
    P5OperationalIncidentRecord,
    P5ProvisioningRunRecord,
    P5TenantPolicyRecord,
    P5TenantTemplateRecord,
    P5UsageQuotaEventRecord,
)
from app.services.billing_ledger import apply_subscription_configuration, compose_modular_pricing
from app.services.catalog import CATALOG, MODULAR_SERVICE_MODULES, MODULAR_SME_TIERS
from app.services.connectors import CONNECTOR_SPECS, configure_connector
from app.services.execution_guard import is_external_side_effect_blocked, resolve_execution_mode
from app.services.registry import AGENT_REGISTRY
from app.security.trust_chain import seal_task_to_block

PROVISIONING_STATES: tuple[str, ...] = (
    "REQUESTED",
    "ORG_CREATED",
    "SUBSCRIPTION_BOUND",
    "TEMPLATES_APPLIED",
    "CONNECTORS_STAGED",
    "HEALTH_CHECKED",
    "ACTIVE",
    "FAILED",
    "RECOVERING",
)

PROVISIONING_PIPELINE: tuple[str, ...] = (
    "ORG_CREATED",
    "SUBSCRIPTION_BOUND",
    "TEMPLATES_APPLIED",
    "CONNECTORS_STAGED",
    "HEALTH_CHECKED",
)

QUOTA_METRICS: tuple[str, ...] = (
    "rate_limit_rpm",
    "daily_agent_runs_cap",
    "monthly_credit_budget",
    "storage_quota_mb",
)

INCIDENT_SEVERITIES: tuple[str, ...] = (
    "SEV1_CRITICAL",
    "SEV2_HIGH",
    "SEV3_MEDIUM",
    "SEV4_LOW",
)

INCIDENT_CATEGORIES: tuple[str, ...] = (
    "PROVISIONING_FAILURE",
    "QUOTA_BREACH",
    "SLA_DEGRADATION",
    "CONNECTOR_OUTAGE",
    "BILLING_DISCREPANCY",
)

INCIDENT_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "OPEN": ("ACKNOWLEDGED", "MITIGATING", "RESOLVED"),
    "ACKNOWLEDGED": ("MITIGATING", "RESOLVED"),
    "MITIGATING": ("RESOLVED",),
    "RESOLVED": (),
}

TIER_POLICY_DEFAULTS: dict[str, dict[str, Any]] = {
    "launch": {
        "rate_limit_rpm": 60,
        "daily_agent_runs_cap": 100,
        "monthly_credit_budget": 150,
        "storage_quota_mb": 1024,
        "sla_target_uptime_pct": 99.0,
        "sla_response_minutes": 480,
    },
    "growth": {
        "rate_limit_rpm": 120,
        "daily_agent_runs_cap": 300,
        "monthly_credit_budget": 400,
        "storage_quota_mb": 5120,
        "sla_target_uptime_pct": 99.5,
        "sla_response_minutes": 240,
    },
    "operations": {
        "rate_limit_rpm": 240,
        "daily_agent_runs_cap": 750,
        "monthly_credit_budget": 900,
        "storage_quota_mb": 15360,
        "sla_target_uptime_pct": 99.5,
        "sla_response_minutes": 180,
    },
    "business_pro": {
        "rate_limit_rpm": 400,
        "daily_agent_runs_cap": 1500,
        "monthly_credit_budget": 2000,
        "storage_quota_mb": 51200,
        "sla_target_uptime_pct": 99.9,
        "sla_response_minutes": 120,
    },
    "enterprise": {
        "rate_limit_rpm": 1000,
        "daily_agent_runs_cap": 5000,
        "monthly_credit_budget": 10000,
        "storage_quota_mb": 204800,
        "sla_target_uptime_pct": 99.95,
        "sla_response_minutes": 60,
    },
}

DEFAULT_P5_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "template_key": "india_agency_starter",
        "name": "India Agency Starter Blueprint",
        "description": "Catalog-grounded Launch bundle with SEO & Sales modules for boutique Indian agencies.",
        "industry": "digital_agency",
        "tier_id": "launch",
        "selected_modules": ["seo", "sales"],
        "catalog_service_ids": ["seo_blog_copilot", "company_os_starter"],
        "default_agent_ids": ["seo_content_agent", "discovery_sdr_agent"],
        "connector_requirements": ["gemini_api", "wordpress_rest", "hostinger_smtp"],
    },
    {
        "template_key": "growth_gtm_suite",
        "name": "B2B Growth & GTM Engine Suite",
        "description": "Growth tier provisioning Sales, Marketing, and SEO workflows with HITL campaign staging.",
        "industry": "b2b_services",
        "tier_id": "growth",
        "selected_modules": ["sales", "marketing", "seo"],
        "catalog_service_ids": ["growth_all_in_one", "marketing_suite", "seo_blog_copilot"],
        "default_agent_ids": ["gtm_strategist_agent", "competitive_intel_agent", "sales_proposal_agent"],
        "connector_requirements": ["gemini_api", "serper_search", "hostinger_smtp", "razorpay"],
    },
    {
        "template_key": "distribution_operations_pack",
        "name": "Distribution & Field Operations Pack",
        "description": "Operations tier combining warehouse inventory, field dispatch, and customer success.",
        "industry": "wholesale_distribution",
        "tier_id": "operations",
        "selected_modules": ["inventory", "field_force", "customer_ops"],
        "catalog_service_ids": ["warehouse_automation", "field_force", "company_os_pro"],
        "default_agent_ids": ["warehouse_stocksense_agent", "field_ops_agent", "customer_success_agent"],
        "connector_requirements": ["gemini_api", "whatsapp_bridge", "razorpay"],
    },
    {
        "template_key": "enterprise_full_os",
        "name": "Enterprise Full AI Company OS",
        "description": "Full multi-department SME OS blueprint with governance, growth, ops, and trust enforcement.",
        "industry": "multi_unit_sme",
        "tier_id": "enterprise",
        "selected_modules": ["sales", "marketing", "seo", "inventory", "field_force", "customer_ops"],
        "catalog_service_ids": ["all_access", "company_os_enterprise", "trust_engine"],
        "default_agent_ids": ["ceo_manager_agent", "gtm_strategist_agent", "warehouse_stocksense_agent", "trust_governance_agent"],
        "connector_requirements": ["gemini_api", "serper_search", "wordpress_rest", "razorpay", "whatsapp_bridge"],
    },
)


def _normalize_mode(requested_mode: str | None) -> str:
    raw = (requested_mode or "SIMULATION").strip().upper()
    canonical = "PRODUCTION" if raw == "LIVE" else raw
    if canonical not in ("SIMULATION", "SANDBOX", "PRODUCTION"):
        raise ValueError(f"Unsupported execution_mode '{requested_mode}'")
    resolved = resolve_execution_mode(canonical)
    if resolved == "PRODUCTION" and is_external_side_effect_blocked():
        raise PermissionError("PRODUCTION provisioning blocked while sandbox/test external side-effect guard is active")
    return resolved


def validate_template_spec(
    *,
    tier_id: str,
    selected_modules: list[str],
    catalog_service_ids: list[str],
    default_agent_ids: list[str],
    connector_requirements: list[str],
) -> dict[str, Any]:
    """Validate a tenant template strictly against live CATALOG, MODULAR_SME_TIERS, AGENT_REGISTRY, and CONNECTOR_SPECS."""
    clean_tier = tier_id.strip().lower()
    if clean_tier not in MODULAR_SME_TIERS:
        raise ValueError(f"Unknown tier_id '{tier_id}'; must be one of {sorted(MODULAR_SME_TIERS.keys())}")

    clean_modules = list(dict.fromkeys(m.strip().lower() for m in selected_modules if str(m).strip()))
    bad_modules = [m for m in clean_modules if m not in MODULAR_SERVICE_MODULES]
    if bad_modules:
        raise ValueError(f"Unknown selected_modules {bad_modules}; allowed: {sorted(MODULAR_SERVICE_MODULES.keys())}")

    clean_services = list(dict.fromkeys(s.strip() for s in catalog_service_ids if str(s).strip()))
    bad_services = [s for s in clean_services if s not in CATALOG]
    if bad_services:
        raise ValueError(f"Unknown catalog_service_ids {bad_services}; must exist in CATALOG")

    clean_agents = list(dict.fromkeys(a.strip() for a in default_agent_ids if str(a).strip()))
    bad_agents = [a for a in clean_agents if a not in AGENT_REGISTRY]
    if bad_agents:
        raise ValueError(f"Unknown default_agent_ids {bad_agents}; must exist in AGENT_REGISTRY")

    clean_connectors = list(dict.fromkeys(c.strip() for c in connector_requirements if str(c).strip()))
    bad_connectors = [c for c in clean_connectors if c not in CONNECTOR_SPECS]
    if bad_connectors:
        raise ValueError(f"Unknown connector_requirements {bad_connectors}; must exist in CONNECTOR_SPECS")

    pricing = compose_modular_pricing(
        base_plan_key=clean_tier,
        selected_modules=clean_modules,
        currency="INR",
    )
    policy_defaults = dict(TIER_POLICY_DEFAULTS.get(clean_tier, TIER_POLICY_DEFAULTS["launch"]))
    policy_defaults["monthly_credit_budget"] = max(
        int(policy_defaults["monthly_credit_budget"]),
        int(pricing.get("included_credits") or 0),
    )

    return {
        "tier_id": clean_tier,
        "selected_modules": clean_modules,
        "catalog_service_ids": clean_services,
        "default_agent_ids": clean_agents,
        "connector_requirements": clean_connectors,
        "monthly_price_inr": int(pricing["total_recurring_price"]),
        "policy_defaults": policy_defaults,
        "pricing_quote": pricing,
    }


def _serialize_template(rec: P5TenantTemplateRecord) -> dict[str, Any]:
    return {
        "template_id": rec.id,
        "template_key": rec.template_key,
        "name": rec.name,
        "description": rec.description,
        "industry": rec.industry,
        "tier_id": rec.tier_id,
        "selected_modules": list(rec.selected_modules_json or []),
        "catalog_service_ids": list(rec.catalog_service_ids_json or []),
        "default_agent_ids": list(rec.default_agent_ids_json or []),
        "connector_requirements": list(rec.connector_requirements_json or []),
        "policy_defaults": dict(rec.policy_defaults_json or {}),
        "monthly_price_inr": int(rec.monthly_price_inr or 0),
        "is_active": bool(rec.is_active),
        "evidence_status": rec.evidence_status,
        "created_by": rec.created_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def create_or_update_template(
    db: Session,
    *,
    template_key: str,
    name: str,
    description: str,
    industry: str,
    tier_id: str,
    selected_modules: list[str],
    catalog_service_ids: list[str],
    default_agent_ids: list[str] | None = None,
    connector_requirements: list[str] | None = None,
    policy_overrides: dict[str, Any] | None = None,
    is_active: bool = True,
    actor: str = "system",
) -> dict[str, Any]:
    """Validate against CATALOG/MODULAR_SME_TIERS and persist a tenant onboarding template."""
    clean_key = template_key.strip().lower()
    if len(clean_key) < 3:
        raise ValueError("template_key must be at least 3 characters")

    validated = validate_template_spec(
        tier_id=tier_id,
        selected_modules=selected_modules,
        catalog_service_ids=catalog_service_ids,
        default_agent_ids=default_agent_ids or [],
        connector_requirements=connector_requirements or [],
    )
    policy_defaults = dict(validated["policy_defaults"])
    if policy_overrides:
        for k in ("rate_limit_rpm", "daily_agent_runs_cap", "monthly_credit_budget", "storage_quota_mb", "sla_response_minutes"):
            if k in policy_overrides and int(policy_overrides[k]) > 0:
                policy_defaults[k] = int(policy_overrides[k])
        if "sla_target_uptime_pct" in policy_overrides:
            pct = float(policy_overrides["sla_target_uptime_pct"])
            if 50.0 <= pct <= 100.0:
                policy_defaults["sla_target_uptime_pct"] = pct

    existing = db.query(P5TenantTemplateRecord).filter_by(template_key=clean_key).first()
    now = datetime.now(UTC)
    if existing:
        existing.name = name.strip()
        existing.description = description.strip()
        existing.industry = industry.strip().lower()
        existing.tier_id = validated["tier_id"]
        existing.selected_modules_json = validated["selected_modules"]
        existing.catalog_service_ids_json = validated["catalog_service_ids"]
        existing.default_agent_ids_json = validated["default_agent_ids"]
        existing.connector_requirements_json = validated["connector_requirements"]
        existing.policy_defaults_json = policy_defaults
        existing.monthly_price_inr = validated["monthly_price_inr"]
        existing.is_active = bool(is_active)
        existing.updated_at = now
        db.commit()
        db.refresh(existing)
        return _serialize_template(existing)

    rec = P5TenantTemplateRecord(
        id=str(uuid.uuid4()),
        template_key=clean_key,
        name=name.strip(),
        description=description.strip(),
        industry=industry.strip().lower(),
        tier_id=validated["tier_id"],
        selected_modules_json=validated["selected_modules"],
        catalog_service_ids_json=validated["catalog_service_ids"],
        default_agent_ids_json=validated["default_agent_ids"],
        connector_requirements_json=validated["connector_requirements"],
        policy_defaults_json=policy_defaults,
        monthly_price_inr=validated["monthly_price_inr"],
        is_active=bool(is_active),
        evidence_status="CATALOG_GROUNDED",
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_template(rec)


def seed_default_p5_templates(db: Session, *, actor: str = "system") -> list[dict[str, Any]]:
    """Seed canonical catalog-grounded P5 templates idempotently."""
    results: list[dict[str, Any]] = []
    for spec in DEFAULT_P5_TEMPLATES:
        results.append(
            create_or_update_template(
                db,
                template_key=spec["template_key"],
                name=spec["name"],
                description=spec["description"],
                industry=spec["industry"],
                tier_id=spec["tier_id"],
                selected_modules=spec["selected_modules"],
                catalog_service_ids=spec["catalog_service_ids"],
                default_agent_ids=spec["default_agent_ids"],
                connector_requirements=spec["connector_requirements"],
                actor=actor,
            )
        )
    return results


def list_p5_templates(db: Session, *, industry: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
    """List tenant onboarding templates, seeding catalog defaults if empty."""
    if db.query(P5TenantTemplateRecord).count() == 0:
        seed_default_p5_templates(db)
    q = db.query(P5TenantTemplateRecord)
    if industry:
        q = q.filter(P5TenantTemplateRecord.industry == industry.strip().lower())
    if active_only:
        q = q.filter(P5TenantTemplateRecord.is_active.is_(True))
    return [_serialize_template(r) for r in q.order_by(P5TenantTemplateRecord.monthly_price_inr.asc()).all()]


def _serialize_policy(rec: P5TenantPolicyRecord) -> dict[str, Any]:
    return {
        "policy_id": rec.id,
        "org_id": rec.org_id,
        "tier_id": rec.tier_id,
        "rate_limit_rpm": int(rec.rate_limit_rpm),
        "daily_agent_runs_cap": int(rec.daily_agent_runs_cap),
        "monthly_credit_budget": int(rec.monthly_credit_budget),
        "storage_quota_mb": int(rec.storage_quota_mb),
        "sla_target_uptime_pct": float(rec.sla_target_uptime_pct),
        "sla_response_minutes": int(rec.sla_response_minutes),
        "auto_throttle_on_breach": bool(rec.auto_throttle_on_breach),
        "custom_limits": dict(rec.custom_limits_json or {}),
        "updated_by": rec.updated_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def upsert_tenant_policy(
    db: Session,
    *,
    org_id: str,
    tier_id: str | None = None,
    rate_limit_rpm: int | None = None,
    daily_agent_runs_cap: int | None = None,
    monthly_credit_budget: int | None = None,
    storage_quota_mb: int | None = None,
    sla_target_uptime_pct: float | None = None,
    sla_response_minutes: int | None = None,
    auto_throttle_on_breach: bool | None = None,
    custom_limits: dict[str, Any] | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Create or update rate limit, quota, budget, and SLA policies for an organization."""
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")

    resolved_tier = (tier_id or org.tier or "launch").strip().lower()
    if resolved_tier not in MODULAR_SME_TIERS:
        resolved_tier = "launch"
    defaults = TIER_POLICY_DEFAULTS[resolved_tier]

    rec = db.query(P5TenantPolicyRecord).filter_by(org_id=org_id).first()
    now = datetime.now(UTC)

    rpm = int(rate_limit_rpm if rate_limit_rpm is not None else (rec.rate_limit_rpm if rec else defaults["rate_limit_rpm"]))
    runs_cap = int(
        daily_agent_runs_cap
        if daily_agent_runs_cap is not None
        else (rec.daily_agent_runs_cap if rec else defaults["daily_agent_runs_cap"])
    )
    budget = int(
        monthly_credit_budget
        if monthly_credit_budget is not None
        else (rec.monthly_credit_budget if rec else defaults["monthly_credit_budget"])
    )
    storage = int(
        storage_quota_mb if storage_quota_mb is not None else (rec.storage_quota_mb if rec else defaults["storage_quota_mb"])
    )
    uptime = float(
        sla_target_uptime_pct
        if sla_target_uptime_pct is not None
        else (rec.sla_target_uptime_pct if rec else defaults["sla_target_uptime_pct"])
    )
    sla_mins = int(
        sla_response_minutes
        if sla_response_minutes is not None
        else (rec.sla_response_minutes if rec else defaults["sla_response_minutes"])
    )
    if rpm <= 0 or runs_cap <= 0 or budget <= 0 or storage <= 0 or sla_mins <= 0:
        raise ValueError("Policy quotas and SLA minutes must be positive integers")
    if not (50.0 <= uptime <= 100.0):
        raise ValueError("sla_target_uptime_pct must be between 50.0 and 100.0")

    if rec:
        rec.tier_id = resolved_tier
        rec.rate_limit_rpm = rpm
        rec.daily_agent_runs_cap = runs_cap
        rec.monthly_credit_budget = budget
        rec.storage_quota_mb = storage
        rec.sla_target_uptime_pct = uptime
        rec.sla_response_minutes = sla_mins
        if auto_throttle_on_breach is not None:
            rec.auto_throttle_on_breach = bool(auto_throttle_on_breach)
        if custom_limits is not None:
            rec.custom_limits_json = dict(custom_limits)
        rec.updated_by = actor
        rec.updated_at = now
    else:
        rec = P5TenantPolicyRecord(
            id=str(uuid.uuid4()),
            org_id=org_id,
            tier_id=resolved_tier,
            rate_limit_rpm=rpm,
            daily_agent_runs_cap=runs_cap,
            monthly_credit_budget=budget,
            storage_quota_mb=storage,
            sla_target_uptime_pct=uptime,
            sla_response_minutes=sla_mins,
            auto_throttle_on_breach=True if auto_throttle_on_breach is None else bool(auto_throttle_on_breach),
            custom_limits_json=dict(custom_limits or {}),
            updated_by=actor,
            created_at=now,
            updated_at=now,
        )
        db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_policy(rec)


def get_tenant_policy(db: Session, *, org_id: str) -> dict[str, Any]:
    """Return an organization's P5 policy, falling back to tier defaults if uncustomized."""
    rec = db.query(P5TenantPolicyRecord).filter_by(org_id=org_id).first()
    if rec:
        return _serialize_policy(rec)
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")
    tier_id = (org.tier or "launch").strip().lower()
    if tier_id not in TIER_POLICY_DEFAULTS:
        tier_id = "launch"
    defaults = TIER_POLICY_DEFAULTS[tier_id]
    return {
        "policy_id": None,
        "org_id": org_id,
        "tier_id": tier_id,
        "rate_limit_rpm": defaults["rate_limit_rpm"],
        "daily_agent_runs_cap": defaults["daily_agent_runs_cap"],
        "monthly_credit_budget": defaults["monthly_credit_budget"],
        "storage_quota_mb": defaults["storage_quota_mb"],
        "sla_target_uptime_pct": defaults["sla_target_uptime_pct"],
        "sla_response_minutes": defaults["sla_response_minutes"],
        "auto_throttle_on_breach": True,
        "custom_limits": {},
        "updated_by": "default_tier_policy",
        "created_at": None,
        "updated_at": None,
    }


def list_tenant_policies(db: Session, *, org_id: str | None = None) -> list[dict[str, Any]]:
    """List persisted P5 tenant policies."""
    q = db.query(P5TenantPolicyRecord)
    if org_id is not None:
        q = q.filter(P5TenantPolicyRecord.org_id == org_id)
    return [_serialize_policy(r) for r in q.order_by(P5TenantPolicyRecord.updated_at.desc()).all()]


def _serialize_quota_event(rec: P5UsageQuotaEventRecord) -> dict[str, Any]:
    return {
        "event_id": rec.id,
        "org_id": rec.org_id,
        "metric_type": rec.metric_type,
        "observed_value": float(rec.observed_value),
        "limit_value": float(rec.limit_value),
        "breached": bool(rec.breached),
        "action_taken": rec.action_taken,
        "details": dict(rec.details_json or {}),
        "recorded_by": rec.recorded_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def evaluate_quota_event(
    db: Session,
    *,
    org_id: str,
    metric_type: str,
    observed_value: float,
    details: dict[str, Any] | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Evaluate a tenant usage observation against its policy limit and record an audit event."""
    clean_metric = metric_type.strip().lower()
    if clean_metric not in QUOTA_METRICS:
        raise ValueError(f"Unsupported metric_type '{metric_type}'; allowed: {QUOTA_METRICS}")
    if observed_value < 0:
        raise ValueError("observed_value must be non-negative")

    policy = get_tenant_policy(db, org_id=org_id)
    limit_value = float(policy[clean_metric])
    breached = float(observed_value) > limit_value
    if not breached:
        action = "ALLOWED"
    elif policy.get("auto_throttle_on_breach", True):
        action = "THROTTLED"
    else:
        action = "WARNED"

    rec = P5UsageQuotaEventRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        metric_type=clean_metric,
        observed_value=float(observed_value),
        limit_value=limit_value,
        breached=breached,
        action_taken=action,
        details_json=dict(details or {}),
        recorded_by=actor,
        created_at=datetime.now(UTC),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_quota_event(rec)


def list_quota_events(db: Session, *, org_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List tenant usage quota evaluation events."""
    q = db.query(P5UsageQuotaEventRecord)
    if org_id is not None:
        q = q.filter(P5UsageQuotaEventRecord.org_id == org_id)
    return [_serialize_quota_event(r) for r in q.order_by(P5UsageQuotaEventRecord.created_at.desc()).limit(limit).all()]


def _serialize_provisioning_run(rec: P5ProvisioningRunRecord) -> dict[str, Any]:
    return {
        "run_id": rec.id,
        "org_id": rec.org_id,
        "idempotency_key": rec.idempotency_key,
        "template_key": rec.template_key,
        "state": rec.state,
        "completed_steps": list(rec.completed_steps_json or []),
        "failed_step": rec.failed_step,
        "failure_reason": rec.failure_reason,
        "attempt_count": int(rec.attempt_count or 1),
        "max_attempts": int(rec.max_attempts or 3),
        "config_snapshot": dict(rec.config_snapshot_json or {}),
        "execution_mode": rec.execution_mode,
        "created_by": rec.created_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def _run_provisioning_step(
    db: Session,
    *,
    run: P5ProvisioningRunRecord,
    step: str,
    template: P5TenantTemplateRecord,
    company_name: str | None,
    actor: str,
) -> dict[str, Any]:
    """Execute one idempotent step of the P5 tenant provisioning FSM."""
    snapshot = dict(run.config_snapshot_json or {})
    if step == "ORG_CREATED":
        if run.org_id:
            org = db.query(OrganizationRecord).filter_by(id=run.org_id).first()
            if not org:
                raise ValueError(f"Organization '{run.org_id}' not found")
        else:
            if not company_name or not company_name.strip():
                raise ValueError("company_name is required when provisioning a new organization")
            new_org_id = str(uuid.uuid4())
            clean_slug = "".join(ch if ch.isalnum() else "-" for ch in company_name.strip().lower()).strip("-")[:60]
            org = OrganizationRecord(
                id=new_org_id,
                name=company_name.strip(),
                slug=f"{clean_slug or 'tenant'}-{new_org_id[:8]}",
                tier=template.tier_id,
                is_active=True,
            )
            db.add(org)
            db.flush()
            run.org_id = org.id
        snapshot["org_name"] = org.name
        return snapshot

    if not run.org_id:
        raise ValueError("Cannot advance provisioning without resolved org_id")

    if step == "SUBSCRIPTION_BOUND":
        sub_res = apply_subscription_configuration(
            db,
            org_id=run.org_id,
            actor=actor,
            action="p5_provision",
            base_plan_key=template.tier_id,
            selected_modules=list(template.selected_modules_json or []),
            currency="INR",
        )
        snapshot["subscription_quote"] = {
            "base_plan_key": template.tier_id,
            "selected_modules": list(template.selected_modules_json or []),
            "monthly_price_inr": sub_res.get("quote", {}).get("total_recurring_price", template.monthly_price_inr),
        }
        return snapshot

    if step == "TEMPLATES_APPLIED":
        defaults = dict(template.policy_defaults_json or {})
        policy = upsert_tenant_policy(
            db,
            org_id=run.org_id,
            tier_id=template.tier_id,
            rate_limit_rpm=defaults.get("rate_limit_rpm"),
            daily_agent_runs_cap=defaults.get("daily_agent_runs_cap"),
            monthly_credit_budget=defaults.get("monthly_credit_budget"),
            storage_quota_mb=defaults.get("storage_quota_mb"),
            sla_target_uptime_pct=defaults.get("sla_target_uptime_pct"),
            sla_response_minutes=defaults.get("sla_response_minutes"),
            actor=actor,
        )
        snapshot["policy_id"] = policy["policy_id"]
        snapshot["default_agent_ids"] = list(template.default_agent_ids_json or [])
        return snapshot

    if step == "CONNECTORS_STAGED":
        staged: list[str] = []
        env_label = "sandbox" if run.execution_mode != "PRODUCTION" else "production"
        for conn_id in list(template.connector_requirements_json or []):
            if conn_id in CONNECTOR_SPECS:
                configure_connector(
                    db,
                    connector_id=conn_id,
                    org_id=run.org_id,
                    settings_payload={"provisioned_by": "p5_fsm", "template_key": template.template_key},
                    environment=env_label,
                )
                staged.append(conn_id)
        snapshot["connectors_staged"] = staged
        return snapshot

    if step == "HEALTH_CHECKED":
        org = db.query(OrganizationRecord).filter_by(id=run.org_id).first()
        policy = db.query(P5TenantPolicyRecord).filter_by(org_id=run.org_id).first()
        if not org or not org.is_active or not policy:
            raise RuntimeError("Tenant health verification failed: active organization or policy missing")
        seal_task_to_block(
            db=db,
            task_id=run.id,
            capability_name="p5_productization_scale",
            action="tenant_provisioned",
            payload={"org_id": run.org_id, "template_key": template.template_key, "tier_id": template.tier_id},
            sealed_by=actor,
        )
        snapshot["health_status"] = "HEALTHY"
        return snapshot

    return snapshot


def _advance_provisioning_pipeline(
    db: Session,
    *,
    run: P5ProvisioningRunRecord,
    template: P5TenantTemplateRecord,
    company_name: str | None,
    simulate_fail_at_step: str | None,
    actor: str,
) -> P5ProvisioningRunRecord:
    """Execute pending provisioning steps in strict pipeline order."""
    completed = list(run.completed_steps_json or [])
    for step in PROVISIONING_PIPELINE:
        if step in completed:
            continue
        if simulate_fail_at_step == step and run.execution_mode != "PRODUCTION":
            run.state = "FAILED"
            run.failed_step = step
            run.failure_reason = f"Simulated failure at step '{step}' for recovery drill"
            run.updated_at = datetime.now(UTC)
            db.commit()
            db.refresh(run)
            return run
        try:
            snapshot = _run_provisioning_step(
                db,
                run=run,
                step=step,
                template=template,
                company_name=company_name,
                actor=actor,
            )
            completed.append(step)
            run.completed_steps_json = completed
            run.config_snapshot_json = snapshot
            run.state = step
            run.failed_step = None
            run.failure_reason = None
            run.updated_at = datetime.now(UTC)
            db.flush()
        except Exception as exc:
            run.state = "FAILED"
            run.failed_step = step
            run.failure_reason = str(exc)[:500]
            run.updated_at = datetime.now(UTC)
            db.commit()
            db.refresh(run)
            return run

    run.state = "ACTIVE"
    run.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    return run


def start_provisioning_run(
    db: Session,
    *,
    template_key: str,
    idempotency_key: str,
    org_id: str | None = None,
    company_name: str | None = None,
    execution_mode: str = "SIMULATION",
    simulate_fail_at_step: str | None = None,
    max_attempts: int = 3,
    actor: str = "system",
) -> dict[str, Any]:
    """Start or idempotently replay a catalog-grounded tenant provisioning FSM run."""
    if db.query(P5TenantTemplateRecord).count() == 0:
        seed_default_p5_templates(db, actor=actor)

    clean_key = idempotency_key.strip()
    if len(clean_key) < 4:
        raise ValueError("idempotency_key must be at least 4 characters")

    clean_tpl = template_key.strip().lower()
    template = db.query(P5TenantTemplateRecord).filter_by(template_key=clean_tpl, is_active=True).first()
    if not template:
        raise ValueError(f"Active template '{template_key}' not found")

    if simulate_fail_at_step and simulate_fail_at_step not in PROVISIONING_PIPELINE:
        raise ValueError(f"simulate_fail_at_step must be one of {PROVISIONING_PIPELINE}")

    mode = _normalize_mode(execution_mode)

    existing = db.query(P5ProvisioningRunRecord).filter_by(idempotency_key=clean_key).first()
    if existing:
        if existing.template_key != clean_tpl or (org_id is not None and existing.org_id and existing.org_id != org_id):
            raise ValueError("idempotency_key already registered for a different template or organization")
        res = _serialize_provisioning_run(existing)
        res["idempotent_replay"] = True
        return res

    now = datetime.now(UTC)
    run = P5ProvisioningRunRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        idempotency_key=clean_key,
        template_key=clean_tpl,
        state="REQUESTED",
        completed_steps_json=[],
        attempt_count=1,
        max_attempts=max(1, min(10, int(max_attempts))),
        config_snapshot_json={"template_key": clean_tpl, "tier_id": template.tier_id},
        execution_mode=mode,
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    db.flush()

    updated = _advance_provisioning_pipeline(
        db,
        run=run,
        template=template,
        company_name=company_name,
        simulate_fail_at_step=simulate_fail_at_step,
        actor=actor,
    )
    res = _serialize_provisioning_run(updated)
    res["idempotent_replay"] = False
    return res


def retry_provisioning_run(
    db: Session,
    *,
    run_id: str,
    org_id: str | None = None,
    company_name: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Recover a FAILED/RECOVERING provisioning run without repeating already completed steps."""
    run = db.get(P5ProvisioningRunRecord, run_id)
    if not run or (org_id is not None and run.org_id != org_id):
        raise ValueError(f"Provisioning run '{run_id}' not found")
    if run.state not in ("FAILED", "RECOVERING"):
        raise ValueError(f"Provisioning run is in state '{run.state}' and cannot be retried")
    if run.attempt_count >= run.max_attempts:
        raise ValueError(f"Provisioning run exceeded max_attempts ({run.max_attempts})")

    template = db.query(P5TenantTemplateRecord).filter_by(template_key=run.template_key).first()
    if not template:
        raise ValueError(f"Referenced template '{run.template_key}' no longer exists")

    run.state = "RECOVERING"
    run.attempt_count += 1
    run.updated_at = datetime.now(UTC)
    db.flush()

    updated = _advance_provisioning_pipeline(
        db,
        run=run,
        template=template,
        company_name=company_name,
        simulate_fail_at_step=None,
        actor=actor,
    )
    return _serialize_provisioning_run(updated)


def list_provisioning_runs(db: Session, *, org_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List provisioning runs, optionally scoped to an organization."""
    q = db.query(P5ProvisioningRunRecord)
    if org_id is not None:
        q = q.filter(P5ProvisioningRunRecord.org_id == org_id)
    return [_serialize_provisioning_run(r) for r in q.order_by(P5ProvisioningRunRecord.created_at.desc()).limit(limit).all()]


def _serialize_incident(rec: P5OperationalIncidentRecord) -> dict[str, Any]:
    return {
        "incident_id": rec.id,
        "org_id": rec.org_id,
        "title": rec.title,
        "severity": rec.severity,
        "category": rec.category,
        "status": rec.status,
        "root_cause": rec.root_cause,
        "mitigation_notes": rec.mitigation_notes,
        "sla_due_at": rec.sla_due_at.isoformat() if rec.sla_due_at else None,
        "resolved_at": rec.resolved_at.isoformat() if rec.resolved_at else None,
        "reported_by": rec.reported_by,
        "assigned_to": rec.assigned_to,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def create_operational_incident(
    db: Session,
    *,
    org_id: str | None,
    title: str,
    severity: str = "SEV3_MEDIUM",
    category: str = "SLA_DEGRADATION",
    root_cause: str | None = None,
    assigned_to: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Open a multi-tenant SLA/quota/provisioning operational incident with tier SLA deadline."""
    clean_sev = severity.strip().upper()
    clean_cat = category.strip().upper()
    if clean_sev not in INCIDENT_SEVERITIES:
        raise ValueError(f"Unsupported severity '{severity}'; allowed: {INCIDENT_SEVERITIES}")
    if clean_cat not in INCIDENT_CATEGORIES:
        raise ValueError(f"Unsupported category '{category}'; allowed: {INCIDENT_CATEGORIES}")

    sla_minutes = 240
    if org_id:
        try:
            policy = get_tenant_policy(db, org_id=org_id)
            sla_minutes = int(policy["sla_response_minutes"])
        except ValueError as exc:
            raise ValueError(f"Organization '{org_id}' not found") from exc

    sev_divisor = {"SEV1_CRITICAL": 4, "SEV2_HIGH": 2, "SEV3_MEDIUM": 1, "SEV4_LOW": 1}[clean_sev]
    due_mins = max(15, sla_minutes // sev_divisor)
    now = datetime.now(UTC)

    rec = P5OperationalIncidentRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        title=title.strip(),
        severity=clean_sev,
        category=clean_cat,
        status="OPEN",
        root_cause=root_cause.strip() if root_cause else None,
        sla_due_at=now + timedelta(minutes=due_mins),
        reported_by=actor,
        assigned_to=assigned_to,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_incident(rec)


def transition_operational_incident(
    db: Session,
    *,
    incident_id: str,
    org_id: str | None,
    target_status: str,
    root_cause: str | None = None,
    mitigation_notes: str | None = None,
    assigned_to: str | None = None,
) -> dict[str, Any]:
    """Transition an operational incident cleanly along the incident lifecycle."""
    rec = db.get(P5OperationalIncidentRecord, incident_id)
    if not rec or (org_id is not None and rec.org_id != org_id):
        raise ValueError(f"Incident '{incident_id}' not found")

    clean_target = target_status.strip().upper()
    allowed = INCIDENT_TRANSITIONS.get(rec.status, ())
    if clean_target not in allowed:
        raise ValueError(f"Invalid incident transition {rec.status} -> {clean_target}; allowed: {allowed}")

    now = datetime.now(UTC)
    rec.status = clean_target
    if root_cause is not None:
        rec.root_cause = root_cause.strip()
    if mitigation_notes is not None:
        rec.mitigation_notes = mitigation_notes.strip()
    if assigned_to is not None:
        rec.assigned_to = assigned_to.strip()
    if clean_target == "RESOLVED":
        rec.resolved_at = now
    rec.updated_at = now
    db.commit()
    db.refresh(rec)
    return _serialize_incident(rec)


def list_operational_incidents(
    db: Session,
    *,
    org_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List P5 operational incidents."""
    q = db.query(P5OperationalIncidentRecord)
    if org_id is not None:
        q = q.filter(P5OperationalIncidentRecord.org_id == org_id)
    if status:
        q = q.filter(P5OperationalIncidentRecord.status == status.strip().upper())
    return [_serialize_incident(r) for r in q.order_by(P5OperationalIncidentRecord.created_at.desc()).all()]


def compute_p5_scale_summary(db: Session, *, org_id: str | None = None) -> dict[str, Any]:
    """Compute live multi-tenant provisioning, quota, and SLA incident summary."""
    templates = list_p5_templates(db, active_only=True)
    runs = list_provisioning_runs(db, org_id=org_id, limit=100)
    events = list_quota_events(db, org_id=org_id, limit=100)
    incidents = list_operational_incidents(db, org_id=org_id)

    return {
        "template_count": len(templates),
        "provisioning_run_count": len(runs),
        "active_provisioned_count": sum(1 for r in runs if r["state"] == "ACTIVE"),
        "failed_provisioned_count": sum(1 for r in runs if r["state"] == "FAILED"),
        "quota_events_count": len(events),
        "quota_breaches_count": sum(1 for e in events if e["breached"]),
        "throttled_events_count": sum(1 for e in events if e["action_taken"] == "THROTTLED"),
        "open_incidents_count": sum(1 for i in incidents if i["status"] != "RESOLVED"),
        "resolved_incidents_count": sum(1 for i in incidents if i["status"] == "RESOLVED"),
    }
