"""P3 Customer Success 360 Management, Lifecycle State Machine & Configurable Onboarding Activation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import (
    AuditLog,
    BusinessProfileRecord,
    ConnectorStateRecord,
    InvoiceRecord,
    OrganizationRecord,
    P2CustomerEngagementRecord,
    P2ProspectDossierRecord,
    P3CustomerAccountRecord,
    P3GrowthOpportunityRecord,
    P3OnboardingWorkflowRecord,
    P3ServiceDeliveryRecord,
    P3SubscriptionEventRecord,
    P3SupportTicketRecord,
    SubscriptionRecord,
    TenantSubscriptionRecord,
    UserRecord,
)
from app.security.auth import get_org_entitled_capabilities
from app.security.trust_chain import seal_task_to_block
from app.services.billing_ledger import serialize_tenant_subscription
from app.services.catalog import CATALOG, get_package
from app.services.execution_guard import redact_secrets

CUSTOMER_LIFECYCLE_STATES = (
    "LEAD",
    "ONBOARDING",
    "ACTIVATION_PENDING",
    "ACTIVE",
    "AT_RISK",
    "SUSPENDED",
    "CHURNED",
    "CLOSED",
)

ALLOWED_LIFECYCLE_TRANSITIONS: dict[str, set[str]] = {
    "LEAD": {"ONBOARDING", "ACTIVATION_PENDING", "CHURNED", "CLOSED"},
    "ONBOARDING": {"ACTIVATION_PENDING", "ACTIVE", "AT_RISK", "SUSPENDED", "CHURNED", "CLOSED"},
    "ACTIVATION_PENDING": {"ONBOARDING", "ACTIVE", "AT_RISK", "SUSPENDED", "CHURNED", "CLOSED"},
    "ACTIVE": {"AT_RISK", "SUSPENDED", "CHURNED", "CLOSED"},
    "AT_RISK": {"ACTIVE", "SUSPENDED", "CHURNED", "CLOSED"},
    "SUSPENDED": {"ONBOARDING", "ACTIVATION_PENDING", "ACTIVE", "AT_RISK", "CHURNED", "CLOSED"},
    "CHURNED": {"ONBOARDING", "ACTIVATION_PENDING", "ACTIVE", "CLOSED"},
    "CLOSED": set(),
}

ONBOARDING_TEMPLATES: dict[str, dict[str, Any]] = {
    "india_seo_agency_pilot": {
        "template_key": "india_seo_agency_pilot",
        "sku_keys": ("managed_seo_content_pilot",),
        "title": "India Digital Marketing & SEO Agency — 14-Day Pilot Onboarding",
        "segment": "Small & medium digital marketing / SEO agencies in India",
        "default_agents": ["seo_content_agent", "research_analyst_agent", "cs_onboarding_specialist_agent", "qa_review_agent"],
        "tasks": [
            ("business_profile", "Collect Agency Business Profile & Client Niche", "customer", 1, True),
            ("goals_and_requirements", "Confirm Target Goals, Deliverables & Acceptance Criteria", "owner", 1, True),
            ("website_and_platform", "Verify Client Domain, Target URLs & Publishing Platform", "customer", 2, True),
            ("credentials_and_connectors", "Configure Required Credentials Safely (Vault/BYOK Only)", "customer", 2, True),
            ("connector_verification", "Authorize & Verify Delivery Connectors (WordPress / Email / GSC)", "owner", 2, True),
            ("module_configuration", "Configure Entitled Pilot Modules & Brand/Tone Guardrails", "agent", 2, True),
            ("agent_assignment", "Assign Human Account Owner & Specialist AI Agents", "owner", 2, True),
            ("initial_workflow_setup", "Provision Initial SEO Audit, Cluster & Content Workflow", "agent", 3, True),
            ("customer_training_handover", "Complete Agency Walkthrough, Approval Rules & Handover", "owner", 4, True),
            ("activation_confirmation", "Verify All Readiness Criteria & Confirm Live Activation", "owner", 4, True),
        ],
    },
    "india_seo_agency_recurring": {
        "template_key": "india_seo_agency_recurring",
        "sku_keys": ("launch", "growth", "pro", "enterprise", "growth_all_in_one", "company_os_starter", "company_os_pro", "company_os_enterprise"),
        "title": "India Agency Recurring Workspace Onboarding",
        "segment": "Small & medium digital marketing / SEO agencies in India",
        "default_agents": ["seo_content_agent", "discovery_sdr_agent", "research_analyst_agent", "cs_manager_agent", "service_delivery_coordinator_agent"],
        "tasks": [
            ("business_profile", "Complete 13-Field Business Profile & Agency Client Verticals", "customer", 1, True),
            ("goals_and_requirements", "Define Monthly Recurring KPIs & SLA Expectations", "owner", 2, True),
            ("website_and_platform", "Connect Primary Websites, Analytics & Search Console Properties", "customer", 3, True),
            ("credentials_and_connectors", "Store & Redact API/CMS Credentials via Connector Settings", "customer", 3, True),
            ("connector_verification", "Verify Live Connector Readiness & Billing Webhook Health", "owner", 4, True),
            ("module_configuration", "Configure Subscribed Modules, Approval Gates & Credit Limits", "owner", 4, True),
            ("agent_assignment", "Assign Tenant AI Workforce & Human Success Owner", "owner", 5, True),
            ("initial_workflow_setup", "Initialize Recurring Delivery & Cadence Workflows", "agent", 5, True),
            ("customer_training_handover", "Deliver Agency Team Training & Escalation Playbook", "owner", 6, True),
            ("activation_confirmation", "Confirm Readiness & Transition Account to ACTIVE", "owner", 7, True),
        ],
    },
    "seo_blog_copilot": {
        "template_key": "seo_blog_copilot",
        "sku_keys": ("seo_blog_copilot",),
        "title": "SEO Blog Copilot Agency Onboarding",
        "segment": "Digital Marketing & SEO Agencies",
        "default_agents": ["seo_content_agent", "qa_review_agent"],
        "tasks": [
            ("business_profile", "Confirm Target Agency Domains & Content Personas", "customer", 1, True),
            ("goals_and_requirements", "Define Monthly Article Cadence & Quality Guidelines", "owner", 1, True),
            ("website_and_platform", "Verify WordPress REST / Export Target Endpoints", "customer", 2, True),
            ("credentials_and_connectors", "Attach Application Password Safely via Connector Vault", "customer", 2, True),
            ("connector_verification", "Test Connector Draft Staging & SSRF Guard", "owner", 2, True),
            ("module_configuration", "Configure Schema.org JSON-LD & Editorial Rules", "agent", 3, True),
            ("agent_assignment", "Assign SEO Content Agent & QA Reviewer", "owner", 3, True),
            ("initial_workflow_setup", "Stage First Content Workflow Run", "agent", 3, True),
            ("customer_training_handover", "Confirm Client HITL Draft Review Process", "owner", 4, True),
            ("activation_confirmation", "Verify Readiness & Activate Workspace", "owner", 4, True),
        ],
    },
}


def resolve_onboarding_template(sku_key: str | None) -> dict[str, Any]:
    """Select the appropriate configurable onboarding template for a purchased SKU or tier."""
    clean = (sku_key or "").strip().lower()
    for tpl in ONBOARDING_TEMPLATES.values():
        if clean in tpl["sku_keys"]:
            return tpl
    return ONBOARDING_TEMPLATES["india_seo_agency_recurring"]


def _build_tasks_from_template(template: dict[str, Any], human_owner: str) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    tasks: list[dict[str, Any]] = []
    for idx, (key, title, owner_role, due_days, req_act) in enumerate(template["tasks"], start=1):
        tasks.append(
            {
                "task_key": key,
                "step_order": idx,
                "category": key,
                "title": title,
                "owner_role": owner_role,
                "assigned_to": human_owner if owner_role == "owner" else owner_role,
                "deadline_at": (now + timedelta(days=due_days)).isoformat(),
                "required_for_activation": bool(req_act),
                "completed": False,
                "completed_at": None,
                "completed_by": None,
                "evidence_summary": None,
                "evidence_ref": None,
                "blockers": [],
            }
        )
    return tasks


def _compute_workflow_readiness(tasks: list[dict[str, Any]]) -> tuple[float, dict[str, bool], list[str], bool]:
    req_tasks = [t for t in tasks if t.get("required_for_activation", True)]
    total = len(req_tasks) or len(tasks) or 1
    completed_count = sum(1 for t in (req_tasks or tasks) if t.get("completed"))
    pct = round((completed_count / total) * 100.0, 1)

    task_map = {str(t.get("task_key")): t for t in tasks}
    criteria = {
        "business_profile": bool(task_map.get("business_profile", {}).get("completed")),
        "goals_and_requirements": bool(task_map.get("goals_and_requirements", {}).get("completed")),
        "website_and_platform": bool(task_map.get("website_and_platform", {}).get("completed")),
        "credentials_and_connectors": bool(
            task_map.get("credentials_and_connectors", {}).get("completed")
            and task_map.get("connector_verification", {}).get("completed")
        ),
        "module_and_agent_setup": bool(
            task_map.get("module_configuration", {}).get("completed")
            and task_map.get("agent_assignment", {}).get("completed")
        ),
        "initial_workflow_setup": bool(task_map.get("initial_workflow_setup", {}).get("completed")),
        "customer_training_handover": bool(task_map.get("customer_training_handover", {}).get("completed")),
    }
    blockers: list[str] = []
    for t in tasks:
        for b in t.get("blockers") or []:
            if str(b).strip():
                blockers.append(f"{t.get('task_key')}: {str(b).strip()}")

    non_final_required = [
        t for t in req_tasks if t.get("task_key") != "activation_confirmation" and not t.get("completed")
    ]
    ready_for_activation = (len(non_final_required) == 0) and (len(blockers) == 0)
    return pct, criteria, blockers, ready_for_activation


def ensure_customer_account(
    db: Session,
    *,
    org_id: str,
    human_owner: str = "owner",
    acquisition_source: str | None = None,
    initial_state: str = "ONBOARDING",
    lead_id: str | None = None,
    business_goals: list[str] | None = None,
    expected_outcomes: list[str] | None = None,
    renewal_date: datetime | None = None,
    sku_key: str | None = None,
    commit: bool = True,
) -> P3CustomerAccountRecord:
    """Idempotently ensure a P3 Customer Success account profile exists; NEVER prematurely sets ACTIVE."""
    org = db.get(OrganizationRecord, org_id)
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")

    clean_state = initial_state.strip().upper()
    if clean_state == "ACTIVE":
        clean_state = "ACTIVATION_PENDING"
    if clean_state not in CUSTOMER_LIFECYCLE_STATES:
        clean_state = "ONBOARDING"

    account = db.query(P3CustomerAccountRecord).filter_by(org_id=org_id).first()
    primary_user = (
        db.query(UserRecord)
        .filter(UserRecord.org_id == org_id, UserRecord.is_active.is_(True))
        .order_by(UserRecord.created_at.asc())
        .first()
    )
    meta = org.metadata_json or {}
    effective_sku = sku_key or meta.get("package_key") or meta.get("internal_sku") or org.tier or "managed_seo_content_pilot"
    template = resolve_onboarding_template(effective_sku)

    dossier = None
    if lead_id:
        dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=lead_id).first()
    if not dossier:
        dossier = db.query(P2ProspectDossierRecord).filter_by(activated_org_id=org_id).first()

    profile = db.query(BusinessProfileRecord).filter_by(org_id=org_id).first()
    goals = list(business_goals or (profile.business_objectives if profile else []) or [])
    outcomes = list(expected_outcomes or [])

    now = datetime.now(UTC)
    if account is None:
        account = P3CustomerAccountRecord(
            org_id=org_id,
            primary_contact_user_id=primary_user.id if primary_user else None,
            primary_contact_email=primary_user.email if primary_user else None,
            primary_contact_name=primary_user.full_name if primary_user else None,
            human_owner=human_owner,
            assigned_agents_json=list(template["default_agents"]),
            acquisition_source=acquisition_source or (dossier.source_type if dossier else "direct_signup"),
            lead_id=lead_id or (dossier.lead_id if dossier else None),
            lifecycle_state=clean_state,
            business_goals_json=goals,
            expected_outcomes_json=outcomes,
            onboarding_progress_pct=0.0,
            activation_ready=False,
            renewal_date=renewal_date,
            last_customer_engagement_at=now,
            consent_preferences_json={
                "marketing": True,
                "product_updates": True,
                "feedback_followup": True,
                "data_processing": True,
                "updated_at": now.isoformat(),
            },
            retention_policy_json={
                "retention_days": 365,
                "legal_hold": False,
                "offboarded_at": None,
            },
            metadata_json={"initial_sku": effective_sku},
            created_at=now,
            updated_at=now,
        )
        db.add(account)
        db.flush()
    else:
        if primary_user and not account.primary_contact_email:
            account.primary_contact_user_id = primary_user.id
            account.primary_contact_email = primary_user.email
            account.primary_contact_name = primary_user.full_name
        if business_goals:
            account.business_goals_json = goals
        if expected_outcomes:
            account.expected_outcomes_json = outcomes
        if renewal_date and not account.renewal_date:
            account.renewal_date = renewal_date
        if lead_id and not account.lead_id:
            account.lead_id = lead_id
        account.updated_at = now
        db.add(account)

    # Ensure onboarding workflow exists for active/new paying customers
    wf = (
        db.query(P3OnboardingWorkflowRecord)
        .filter_by(org_id=org_id, sku_key=effective_sku)
        .first()
    )
    if wf is None:
        tasks = _build_tasks_from_template(template, account.human_owner)
        pct, criteria, blockers, ready = _compute_workflow_readiness(tasks)
        wf = P3OnboardingWorkflowRecord(
            org_id=org_id,
            sku_key=effective_sku,
            template_key=template["template_key"],
            status="IN_PROGRESS",
            tasks_json=tasks,
            readiness_criteria_json=criteria,
            blockers_json=blockers,
            training_completed=False,
            progress_pct=pct,
            created_at=now,
            updated_at=now,
        )
        db.add(wf)

    if commit:
        db.commit()
        db.refresh(account)
    else:
        db.flush()
    return account


def transition_customer_lifecycle(
    db: Session,
    *,
    org_id: str,
    target_state: str,
    reason: str,
    actor: str = "owner",
    commit: bool = True,
) -> dict[str, Any]:
    """Validate, execute, and audit-log a customer lifecycle state transition."""
    account = ensure_customer_account(db, org_id=org_id, commit=False)
    clean_target = target_state.strip().upper()
    if clean_target not in CUSTOMER_LIFECYCLE_STATES:
        raise ValueError(f"Unsupported customer lifecycle state '{target_state}'")

    current = account.lifecycle_state
    if clean_target == current:
        return serialize_customer_account(account)

    allowed = ALLOWED_LIFECYCLE_TRANSITIONS.get(current, set())
    if clean_target not in allowed:
        raise ValueError(f"Invalid customer lifecycle transition: {current} -> {clean_target}")

    if clean_target == "ACTIVE" and not account.activation_ready:
        raise ValueError(
            "Cannot transition customer to ACTIVE before onboarding readiness criteria and activation confirmation are completed."
        )

    now = datetime.now(UTC)
    account.lifecycle_state = clean_target
    if clean_target == "ACTIVE" and not account.activated_at:
        account.activated_at = now
    account.updated_at = now
    db.add(account)

    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id=actor,
            capability_name="p3_customer_success",
            action="customer_lifecycle_transition",
            input_payload={"org_id": org_id, "from_state": current, "to_state": clean_target, "reason": reason},
            output_payload={"lifecycle_state": clean_target},
            status="COMPLETED",
        )
    )
    if commit:
        db.commit()
        db.refresh(account)
    else:
        db.flush()
    return serialize_customer_account(account)


def create_or_get_onboarding_workflow(
    db: Session,
    *,
    org_id: str,
    sku_key: str | None = None,
    template_key: str | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Create or return the service-specific onboarding tracker for an organization."""
    account = ensure_customer_account(db, org_id=org_id, sku_key=sku_key, human_owner=actor, commit=False)
    org = db.get(OrganizationRecord, org_id)
    meta = (org.metadata_json or {}) if org else {}
    target_sku = sku_key or meta.get("package_key") or account.metadata_json.get("initial_sku") or "managed_seo_content_pilot"
    tpl = ONBOARDING_TEMPLATES.get(template_key or "") or resolve_onboarding_template(target_sku)

    wf = db.query(P3OnboardingWorkflowRecord).filter_by(org_id=org_id, sku_key=target_sku).first()
    if wf is None:
        tasks = _build_tasks_from_template(tpl, account.human_owner)
        pct, criteria, blockers, _ = _compute_workflow_readiness(tasks)
        wf = P3OnboardingWorkflowRecord(
            org_id=org_id,
            sku_key=target_sku,
            template_key=tpl["template_key"],
            status="IN_PROGRESS",
            tasks_json=tasks,
            readiness_criteria_json=criteria,
            blockers_json=blockers,
            training_completed=False,
            progress_pct=pct,
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)
    else:
        db.commit()
    return serialize_onboarding_workflow(wf)


def update_onboarding_task(
    db: Session,
    *,
    org_id: str,
    task_key: str,
    completed: bool,
    evidence_summary: str | None = None,
    evidence_ref: str | None = None,
    blockers: list[str] | None = None,
    assigned_to: str | None = None,
    sku_key: str | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Update a specific onboarding step with evidence, ownership, or blockers without leaking credentials."""
    account = ensure_customer_account(db, org_id=org_id, sku_key=sku_key, commit=False)
    q = db.query(P3OnboardingWorkflowRecord).filter_by(org_id=org_id)
    if sku_key:
        q = q.filter_by(sku_key=sku_key)
    wf = q.order_by(P3OnboardingWorkflowRecord.created_at.desc()).first()
    if not wf:
        created = create_or_get_onboarding_workflow(db, org_id=org_id, sku_key=sku_key, actor=actor)
        wf = db.get(P3OnboardingWorkflowRecord, created["onboarding_id"])

    tasks = list(wf.tasks_json or [])
    matched = False
    now = datetime.now(UTC)
    safe_evidence = redact_secrets(evidence_summary) if evidence_summary else None
    safe_blockers = [str(redact_secrets(b)).strip() for b in (blockers or []) if str(b).strip()]

    for item in tasks:
        if item.get("task_key") == task_key:
            matched = True
            item["completed"] = bool(completed)
            item["completed_at"] = now.isoformat() if completed else None
            item["completed_by"] = actor if completed else None
            if safe_evidence is not None:
                item["evidence_summary"] = str(safe_evidence)
            if evidence_ref is not None:
                item["evidence_ref"] = evidence_ref.strip()
            if blockers is not None:
                item["blockers"] = safe_blockers
            if assigned_to is not None:
                item["assigned_to"] = assigned_to.strip()
            break

    if not matched:
        raise ValueError(f"Onboarding task '{task_key}' not found in workflow '{wf.id}'")

    pct, criteria, all_blockers, ready_for_act = _compute_workflow_readiness(tasks)
    wf.tasks_json = tasks
    wf.readiness_criteria_json = criteria
    wf.blockers_json = all_blockers
    wf.training_completed = bool(criteria.get("customer_training_handover"))
    wf.progress_pct = pct
    if all_blockers:
        wf.status = "BLOCKED"
    elif wf.status == "ACTIVATED":
        pass
    elif ready_for_act:
        wf.status = "READY_FOR_ACTIVATION"
    else:
        wf.status = "IN_PROGRESS"
    wf.updated_at = now

    flag_modified(wf, "tasks_json")
    flag_modified(wf, "readiness_criteria_json")
    flag_modified(wf, "blockers_json")
    db.add(wf)

    account.onboarding_progress_pct = pct
    account.last_customer_engagement_at = now
    if ready_for_act and account.lifecycle_state == "ONBOARDING":
        account.lifecycle_state = "ACTIVATION_PENDING"
    account.updated_at = now
    db.add(account)

    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id=actor,
            capability_name="p3_onboarding",
            action="onboarding_task_updated",
            input_payload={"org_id": org_id, "task_key": task_key, "completed": completed},
            output_payload={"progress_pct": pct, "workflow_status": wf.status},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(wf)
    return serialize_onboarding_workflow(wf)


def confirm_customer_activation(
    db: Session,
    *,
    org_id: str,
    sku_key: str | None = None,
    confirmation_note: str | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Activate customer account strictly ONLY when all service readiness criteria & handover checks pass."""
    account = ensure_customer_account(db, org_id=org_id, sku_key=sku_key, commit=False)
    q = db.query(P3OnboardingWorkflowRecord).filter_by(org_id=org_id)
    if sku_key:
        q = q.filter_by(sku_key=sku_key)
    wf = q.order_by(P3OnboardingWorkflowRecord.created_at.desc()).first()
    if not wf:
        raise ValueError(f"No onboarding workflow found for organization '{org_id}'")

    tasks = list(wf.tasks_json or [])
    pct, criteria, blockers, ready = _compute_workflow_readiness(tasks)
    if blockers:
        raise ValueError(f"Activation blocked by open onboarding blockers: {blockers}")
    if not ready:
        missing = [k for k, v in criteria.items() if not v]
        raise ValueError(f"Activation readiness criteria not met. Incomplete areas: {missing}")

    # Require connector safety: credentials/connector verification must not use unverified failure state
    now = datetime.now(UTC)
    for item in tasks:
        if item.get("task_key") == "activation_confirmation":
            item["completed"] = True
            item["completed_at"] = now.isoformat()
            item["completed_by"] = actor
            item["evidence_summary"] = (confirmation_note or "All readiness checks verified").strip()
            break

    wf.tasks_json = tasks
    wf.progress_pct = 100.0
    wf.status = "ACTIVATED"
    wf.activation_confirmed_by = actor
    wf.activation_confirmed_at = now
    wf.updated_at = now
    flag_modified(wf, "tasks_json")
    db.add(wf)

    account.onboarding_progress_pct = 100.0
    account.activation_ready = True
    account.activated_at = now
    prev_state = account.lifecycle_state
    account.lifecycle_state = "ACTIVE"
    account.updated_at = now
    db.add(account)

    seal_task_to_block(
        db=db,
        task_id=account.id,
        capability_name="p3_customer_activation",
        action="confirm_customer_activation",
        payload={"org_id": org_id, "sku_key": wf.sku_key, "from_state": prev_state, "to_state": "ACTIVE"},
        sealed_by=actor,
        commit=False,
    )
    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id=actor,
            capability_name="p3_customer_success",
            action="customer_activated",
            input_payload={"org_id": org_id, "onboarding_id": wf.id},
            output_payload={"lifecycle_state": "ACTIVE", "progress_pct": 100.0},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(account)
    db.refresh(wf)
    return {
        "status": "ACTIVATED",
        "account": serialize_customer_account(account),
        "onboarding": serialize_onboarding_workflow(wf),
    }


def update_customer_profile_settings(
    db: Session,
    *,
    org_id: str,
    human_owner: str | None = None,
    assigned_agents: list[str] | None = None,
    business_goals: list[str] | None = None,
    expected_outcomes: list[str] | None = None,
    renewal_date: datetime | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Update Customer Success ownership, assigned AI agents, business goals, and renewal date."""
    account = ensure_customer_account(db, org_id=org_id, commit=False)
    if human_owner is not None:
        account.human_owner = human_owner.strip() or account.human_owner
    if assigned_agents is not None:
        account.assigned_agents_json = [str(a).strip() for a in assigned_agents if str(a).strip()]
    if business_goals is not None:
        account.business_goals_json = [str(g).strip() for g in business_goals if str(g).strip()]
    if expected_outcomes is not None:
        account.expected_outcomes_json = [str(o).strip() for o in expected_outcomes if str(o).strip()]
    if renewal_date is not None:
        account.renewal_date = renewal_date
    account.updated_at = datetime.now(UTC)
    db.add(account)
    db.commit()
    db.refresh(account)
    return serialize_customer_account(account)


def get_customer_360_profile(db: Session, *, org_id: str) -> dict[str, Any]:
    """Aggregate complete P3 Customer Success 360 profile reusing existing P0/P1/P2/P3 tables."""
    org = db.get(OrganizationRecord, org_id)
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")

    account = ensure_customer_account(db, org_id=org_id, commit=False)
    meta = org.metadata_json or {}
    pkg_key = meta.get("package_key") or meta.get("internal_sku") or org.tier
    pkg = get_package(str(pkg_key or "")) or CATALOG.get(str(pkg_key or ""))
    entitled_caps = sorted(get_org_entitled_capabilities(org))

    tenant_sub = db.query(TenantSubscriptionRecord).filter_by(org_id=org_id).first()
    provider_subs = db.query(SubscriptionRecord).filter_by(org_id=org_id).all()
    invoices = db.query(InvoiceRecord).filter_by(org_id=org_id).order_by(InvoiceRecord.created_at.desc()).all()
    sub_events = (
        db.query(P3SubscriptionEventRecord)
        .filter_by(org_id=org_id)
        .order_by(P3SubscriptionEventRecord.created_at.desc())
        .limit(10)
        .all()
    )
    onboarding_rows = (
        db.query(P3OnboardingWorkflowRecord)
        .filter_by(org_id=org_id)
        .order_by(P3OnboardingWorkflowRecord.created_at.desc())
        .all()
    )
    deliveries = (
        db.query(P3ServiceDeliveryRecord)
        .filter_by(org_id=org_id)
        .order_by(P3ServiceDeliveryRecord.created_at.desc())
        .all()
    )
    p2_engagements = (
        db.query(P2CustomerEngagementRecord)
        .filter_by(org_id=org_id)
        .order_by(P2CustomerEngagementRecord.created_at.desc())
        .all()
    )
    tickets = (
        db.query(P3SupportTicketRecord)
        .filter_by(org_id=org_id)
        .order_by(P3SupportTicketRecord.created_at.desc())
        .all()
    )
    opportunities = (
        db.query(P3GrowthOpportunityRecord)
        .filter_by(org_id=org_id)
        .order_by(P3GrowthOpportunityRecord.created_at.desc())
        .all()
    )
    connectors = db.query(ConnectorStateRecord).filter_by(org_id=org_id).all()

    feedback_items: list[dict[str, Any]] = []
    for t in tickets:
        if t.csat_rating is not None:
            feedback_items.append(
                {
                    "source": "support_ticket",
                    "source_id": t.id,
                    "rating": t.csat_rating,
                    "comment": t.csat_comment,
                    "submitted_at": t.feedback_submitted_at.isoformat() if t.feedback_submitted_at else None,
                }
            )
    for eng in p2_engagements:
        if eng.customer_feedback_json:
            feedback_items.append(
                {
                    "source": "p2_engagement",
                    "source_id": eng.id,
                    **eng.customer_feedback_json,
                }
            )

    unresolved_tickets = [t for t in tickets if t.status not in ("RESOLVED", "CLOSED")]
    total_paid_inr = sum(
        (inv.amount / 100.0) for inv in invoices if inv.status == "paid" and (inv.currency or "INR").upper() == "INR"
    )

    return {
        "customer_account": serialize_customer_account(account),
        "organization": {
            "org_id": org.id,
            "name": org.name,
            "slug": org.slug,
            "tier": org.tier,
            "is_active": org.is_active,
            "credits": {
                "lead_limit": org.lead_credits_limit,
                "lead_used": org.lead_credits_used,
                "outreach_limit": org.outreach_credits_limit,
                "outreach_used": org.outreach_credits_used,
            },
        },
        "purchased_packages_and_entitlements": {
            "package_key": pkg.key if pkg else pkg_key,
            "package_name": pkg.name if pkg else meta.get("package_name"),
            "selected_modules": list(meta.get("selected_modules") or (tenant_sub.selected_modules if tenant_sub else [])),
            "entitled_capabilities": entitled_caps,
            "entitled_agents": list(meta.get("entitled_agents") or (tenant_sub.entitled_agents if tenant_sub else [])),
        },
        "subscription_and_payment": {
            "tenant_subscription": serialize_tenant_subscription(tenant_sub) if tenant_sub else None,
            "provider_subscriptions": [
                {
                    "id": s.id,
                    "provider": s.provider,
                    "provider_subscription_id": s.provider_subscription_id,
                    "plan_id": s.plan_id,
                    "status": s.status,
                    "current_period_end": s.current_period_end,
                }
                for s in provider_subs
            ],
            "latest_subscription_state": sub_events[0].subscription_state if sub_events else (tenant_sub.status.upper() if tenant_sub else "PENDING"),
            "total_paid_inr": round(total_paid_inr, 2),
            "invoices_count": len(invoices),
        },
        "onboarding": [serialize_onboarding_workflow(w) for w in onboarding_rows],
        "service_delivery_history": [
            {
                "delivery_id": d.id,
                "title": d.title,
                "service_id": d.service_id,
                "quality_state": d.quality_state,
                "due_date": d.due_date.isoformat() if d.due_date else None,
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
                "accepted_at": d.accepted_at.isoformat() if d.accepted_at else None,
            }
            for d in deliveries
        ],
        "support_summary": {
            "total_tickets": len(tickets),
            "unresolved_tickets": len(unresolved_tickets),
            "escalated_tickets": sum(1 for t in unresolved_tickets if t.status == "ESCALATED"),
        },
        "customer_feedback": feedback_items,
        "account_health": account.health_snapshot_json or {"health_state": "INSUFFICIENT_DATA", "score": None},
        "expansion_opportunities": [
            {
                "opportunity_id": o.id,
                "opportunity_type": o.opportunity_type,
                "recommended_sku_key": o.recommended_sku_key,
                "title": o.title,
                "status": o.status,
            }
            for o in opportunities
        ],
        "connectors_configured": [
            {"connector_id": c.connector_id, "connection_status": c.connection_status} for c in connectors
        ],
    }


def list_customer_accounts(db: Session, *, lifecycle_state: str | None = None) -> list[dict[str, Any]]:
    """Sync active organizations lazily where needed and return all Customer Success accounts."""
    orgs = db.query(OrganizationRecord).order_by(OrganizationRecord.created_at.desc()).all()
    existing_org_ids = {r.org_id for r in db.query(P3CustomerAccountRecord).all()}
    for org in orgs:
        if org.id not in existing_org_ids:
            ensure_customer_account(
                db,
                org_id=org.id,
                initial_state="LEAD" if org.tier == "free" else "ONBOARDING",
                commit=False,
            )
    db.commit()

    q = db.query(P3CustomerAccountRecord)
    if lifecycle_state:
        q = q.filter_by(lifecycle_state=lifecycle_state.strip().upper())
    rows = q.order_by(P3CustomerAccountRecord.updated_at.desc()).all()
    return [serialize_customer_account(r) for r in rows]


def serialize_customer_account(acc: P3CustomerAccountRecord) -> dict[str, Any]:
    return {
        "account_id": acc.id,
        "org_id": acc.org_id,
        "primary_contact_user_id": acc.primary_contact_user_id,
        "primary_contact_email": acc.primary_contact_email,
        "primary_contact_name": acc.primary_contact_name,
        "human_owner": acc.human_owner,
        "assigned_agents": acc.assigned_agents_json or [],
        "acquisition_source": acc.acquisition_source,
        "lead_id": acc.lead_id,
        "lifecycle_state": acc.lifecycle_state,
        "business_goals": acc.business_goals_json or [],
        "expected_outcomes": acc.expected_outcomes_json or [],
        "onboarding_progress_pct": acc.onboarding_progress_pct,
        "activation_ready": acc.activation_ready,
        "activated_at": acc.activated_at.isoformat() if acc.activated_at else None,
        "renewal_date": acc.renewal_date.isoformat() if acc.renewal_date else None,
        "last_customer_engagement_at": acc.last_customer_engagement_at.isoformat() if acc.last_customer_engagement_at else None,
        "consent_preferences": acc.consent_preferences_json or {},
        "retention_policy": acc.retention_policy_json or {},
        "health_snapshot": acc.health_snapshot_json,
        "created_at": acc.created_at.isoformat() if acc.created_at else None,
        "updated_at": acc.updated_at.isoformat() if acc.updated_at else None,
    }


def serialize_onboarding_workflow(wf: P3OnboardingWorkflowRecord) -> dict[str, Any]:
    return {
        "onboarding_id": wf.id,
        "org_id": wf.org_id,
        "sku_key": wf.sku_key,
        "template_key": wf.template_key,
        "status": wf.status,
        "tasks": wf.tasks_json or [],
        "readiness_criteria": wf.readiness_criteria_json or {},
        "blockers": wf.blockers_json or [],
        "training_completed": wf.training_completed,
        "progress_pct": wf.progress_pct,
        "activation_confirmed_by": wf.activation_confirmed_by,
        "activation_confirmed_at": wf.activation_confirmed_at.isoformat() if wf.activation_confirmed_at else None,
        "created_at": wf.created_at.isoformat() if wf.created_at else None,
        "updated_at": wf.updated_at.isoformat() if wf.updated_at else None,
    }
