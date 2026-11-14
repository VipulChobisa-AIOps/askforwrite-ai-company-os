"""P3 Subscription State Machine, Grace/Suspension/Restoration, Controlled Expansion/Referral & Unit Economics."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import (
    ApprovalRequest,
    AuditLog,
    ExecutionEvidenceRecord,
    InvoiceRecord,
    OrganizationRecord,
    P2CustomerEngagementRecord,
    P3CustomerCostBudgetRecord,
    P3GrowthOpportunityRecord,
    P3OperationalIncidentRecord,
    P3ServiceDeliveryRecord,
    P3SubscriptionEventRecord,
    P3SupportTicketRecord,
    P3UnitEconomicsEntryRecord,
    SubscriptionRecord,
    SupervisorAlertRecord,
    TaskRecord,
    TenantSubscriptionRecord,
    WorkflowRunRecord,
)
from app.services.billing_ledger import (
    EXTRA_SEAT_PRICE,
    MODULAR_SERVICE_MODULES,
    apply_subscription_configuration,
)
from app.services.catalog import CATALOG, get_package
from app.services.p3_customer_success import ensure_customer_account

SUBSCRIPTION_STATES = (
    "PENDING",
    "TRIALING",
    "ACTIVE",
    "PAST_DUE",
    "PAUSED",
    "CANCELLED",
    "EXPIRED",
    "REFUNDED",
)

BILLING_CATEGORIES = (
    "RECURRING_SUBSCRIPTION",
    "ONE_TIME_PURCHASE",
    "MANAGED_SERVICE_PILOT",
    "MANUAL_PAYMENT_PROOF",
    "EXPANSION_PURCHASE",
)

COST_CATEGORIES = (
    "AI_API_USAGE",
    "INFRASTRUCTURE_ALLOCATION",
    "HUMAN_DELIVERY",
    "SUPPORT_COST",
    "ACQUISITION_COST",
)

COST_TYPE_LABELS = ("ACTUAL", "ALLOCATED", "ESTIMATED")

OPPORTUNITY_TYPES = (
    "ADDITIONAL_MODULE",
    "PACKAGE_UPGRADE",
    "EXTRA_SEATS",
    "ADDITIONAL_SERVICE",
    "MANAGED_EXTENSION",
    "REFERRAL_REQUEST",
)


class CostBudgetExceededError(PermissionError):
    """Raised when customer spend exceeds hard cap without an Owner HITL exception approval."""


def _derive_billing_category(sku_key: str | None, billing_type: str | None) -> str:
    clean_sku = (sku_key or "").lower()
    clean_bt = (billing_type or "").lower()
    if "pilot" in clean_sku or "pilot" in clean_bt:
        return "MANAGED_SERVICE_PILOT"
    if "one_time" in clean_bt or "b2c" in clean_bt:
        return "ONE_TIME_PURCHASE"
    return "RECURRING_SUBSCRIPTION"


def record_subscription_lifecycle_event(
    db: Session,
    *,
    org_id: str,
    event_type: str,
    target_state: str,
    idempotency_key: str,
    billing_category: str | None = None,
    is_provider_confirmed: bool = False,
    provider: str = "internal",
    provider_subscription_id: str | None = None,
    internal_sku: str | None = None,
    billing_interval: str | None = None,
    amount: float = 0.0,
    currency: str = "INR",
    renewal_date: datetime | None = None,
    grace_until: datetime | None = None,
    approval_id: str | None = None,
    actor: str = "system",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an idempotent subscription lifecycle transition and sync tenant entitlements cleanly."""
    clean_state = target_state.strip().upper()
    if clean_state not in SUBSCRIPTION_STATES:
        raise ValueError(f"Unsupported subscription state '{target_state}'")

    existing = db.query(P3SubscriptionEventRecord).filter_by(idempotency_key=idempotency_key.strip()).first()
    if existing:
        return {
            "status": "DUPLICATE_IGNORED",
            "event": serialize_subscription_event(existing),
        }

    account = ensure_customer_account(db, org_id=org_id, sku_key=internal_sku, commit=False)
    org = db.get(OrganizationRecord, org_id)
    tenant_sub = db.query(TenantSubscriptionRecord).filter_by(org_id=org_id).first()
    eff_sku = internal_sku or (tenant_sub.internal_sku if tenant_sub else None) or (org.tier if org else None)
    is_manual_proof = (
        "manual" in provider.lower()
        or "manual" in event_type.lower()
        or provider.lower() in ("manual_proof", "afw_directpay_manual", "offline")
        or (provider.lower() == "afw_directpay" and not is_provider_confirmed)
    )
    if billing_category:
        eff_cat = billing_category.strip().upper()
    elif is_manual_proof:
        eff_cat = "MANUAL_PAYMENT_PROOF"
    else:
        eff_cat = _derive_billing_category(eff_sku, tenant_sub.billing_type if tenant_sub else None)
    if eff_cat not in BILLING_CATEGORIES:
        eff_cat = "ONE_TIME_PURCHASE"

    # Rule: Manual payment proof can NEVER mark a subscription as provider-confirmed recurring billing
    if is_manual_proof or event_type == "MANUAL_PROOF_RECORDED":
        is_provider_confirmed = False

    now = datetime.now(UTC)
    evt = P3SubscriptionEventRecord(
        org_id=org_id,
        subscription_id=tenant_sub.id if tenant_sub else None,
        idempotency_key=idempotency_key.strip(),
        event_type=event_type.strip().upper(),
        subscription_state=clean_state,
        billing_category=eff_cat,
        is_provider_confirmed=bool(is_provider_confirmed),
        provider=provider.strip().lower(),
        provider_subscription_id=provider_subscription_id,
        internal_sku=eff_sku,
        billing_interval=billing_interval or (tenant_sub.billing_interval if tenant_sub else "monthly"),
        amount=float(amount),
        currency=currency.strip().upper(),
        renewal_date=renewal_date or (tenant_sub.current_period_end if tenant_sub else None),
        grace_until=grace_until,
        approval_id=approval_id,
        actor=actor,
        details_json=dict(details or {}),
        created_at=now,
    )
    db.add(evt)

    if tenant_sub is not None:
        tenant_sub.status = clean_state.lower()
        if renewal_date:
            tenant_sub.current_period_end = renewal_date
        tenant_sub.updated_at = now
        db.add(tenant_sub)

    # Entitlement suspension vs restoration sync on OrganizationRecord
    if org is not None:
        meta = dict(org.metadata_json or {})
        meta["subscription_state"] = clean_state
        meta["billing_category"] = eff_cat
        meta["provider_confirmed_recurring"] = bool(is_provider_confirmed and eff_cat == "RECURRING_SUBSCRIPTION")
        if clean_state in ("CANCELLED", "EXPIRED", "REFUNDED", "PAUSED"):
            if clean_state in ("EXPIRED", "REFUNDED", "CANCELLED") and (tenant_sub is None or not tenant_sub.cancel_at_period_end or clean_state != "CANCELLED"):
                if meta.get("entitled_capabilities"):
                    meta["suspended_entitled_capabilities"] = list(meta.get("entitled_capabilities") or [])
                meta["entitled_capabilities"] = []
                meta["suspended_tier"] = meta.get("suspended_tier") or org.tier
                org.tier = "free"
        elif clean_state == "ACTIVE":
            restored = meta.pop("suspended_entitled_capabilities", None)
            if restored and not meta.get("entitled_capabilities"):
                meta["entitled_capabilities"] = restored
            if org.tier == "free" and meta.get("suspended_tier"):
                org.tier = str(meta.pop("suspended_tier"))
            elif org.tier == "free" and eff_sku:
                pkg = get_package(eff_sku)
                if pkg:
                    org.tier = pkg.tier
                    meta["entitled_capabilities"] = list(pkg.entitled_capabilities)
        org.metadata_json = meta
        flag_modified(org, "metadata_json")
        db.add(org)

    if renewal_date:
        account.renewal_date = renewal_date
    if clean_state == "PAST_DUE" and account.lifecycle_state == "ACTIVE":
        account.lifecycle_state = "AT_RISK"
    elif clean_state in ("EXPIRED", "PAUSED") and account.lifecycle_state in ("ACTIVE", "AT_RISK"):
        account.lifecycle_state = "SUSPENDED"
    elif clean_state in ("CANCELLED", "REFUNDED") and account.lifecycle_state not in ("CLOSED",):
        account.lifecycle_state = "CHURNED"
    elif clean_state == "ACTIVE" and account.activation_ready and account.lifecycle_state in ("AT_RISK", "SUSPENDED"):
        account.lifecycle_state = "ACTIVE"
    account.updated_at = now
    db.add(account)

    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id=actor,
            capability_name="p3_subscription_lifecycle",
            action=f"subscription_{event_type.lower()}",
            input_payload={"org_id": org_id, "target_state": clean_state, "provider": provider, "idempotency_key": idempotency_key},
            output_payload={"subscription_state": clean_state, "is_provider_confirmed": evt.is_provider_confirmed},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(evt)
    return {"status": "RECORDED", "event": serialize_subscription_event(evt)}


def handle_payment_failure_and_grace_period(
    db: Session,
    *,
    org_id: str,
    amount: float,
    currency: str = "INR",
    grace_days: int = 5,
    reason: str = "Recurring charge failed",
    idempotency_key: str,
    provider: str = "razorpay",
    actor: str = "billing_watchdog",
) -> dict[str, Any]:
    """Transition subscription to PAST_DUE with explicit grace window and emit an internal billing alert."""
    now = datetime.now(UTC)
    grace_until = now + timedelta(days=max(1, int(grace_days)))
    res = record_subscription_lifecycle_event(
        db,
        org_id=org_id,
        event_type="PAYMENT_FAILED",
        target_state="PAST_DUE",
        idempotency_key=idempotency_key,
        is_provider_confirmed=False,
        provider=provider,
        amount=amount,
        currency=currency,
        grace_until=grace_until,
        actor=actor,
        details={"reason": reason, "grace_days": grace_days},
    )
    if res["status"] == "RECORDED":
        db.add(
            SupervisorAlertRecord(
                org_id=org_id,
                alert_type="SUBSCRIPTION_PAYMENT_FAILED",
                severity="CRITICAL",
                title=f"Payment failed for org {org_id} — {grace_days}-day grace period active",
                description=f"{reason}. Grace period ends {grace_until.isoformat()}.",
                suggested_action="Send approved billing recovery link or verify gateway card/mandate status.",
                metadata_json={"internal_only": True, "grace_until": grace_until.isoformat()},
            )
        )
        db.commit()
    return res


def enforce_grace_period_expirations(db: Session, *, org_id: str | None = None, as_of: datetime | None = None) -> list[dict[str, Any]]:
    """Suspend entitlements for PAST_DUE subscriptions whose grace_until has passed."""
    now = as_of or datetime.now(UTC)
    q = db.query(P3SubscriptionEventRecord).filter_by(subscription_state="PAST_DUE")
    if org_id:
        q = q.filter_by(org_id=org_id)
    past_due_evts = q.order_by(P3SubscriptionEventRecord.created_at.desc()).all()

    seen_orgs: set[str] = set()
    suspended: list[dict[str, Any]] = []
    for evt in past_due_evts:
        if evt.org_id in seen_orgs:
            continue
        seen_orgs.add(evt.org_id)
        # Check if latest event for this org is still PAST_DUE
        latest = (
            db.query(P3SubscriptionEventRecord)
            .filter_by(org_id=evt.org_id)
            .order_by(P3SubscriptionEventRecord.created_at.desc())
            .first()
        )
        if not latest or latest.subscription_state != "PAST_DUE" or not latest.grace_until:
            continue
        g_dt = latest.grace_until if latest.grace_until.tzinfo else latest.grace_until.replace(tzinfo=UTC)
        if now > g_dt:
            res = record_subscription_lifecycle_event(
                db,
                org_id=evt.org_id,
                event_type="GRACE_PERIOD_EXPIRED_SUSPENDED",
                target_state="EXPIRED",
                idempotency_key=f"grace-expire:{evt.org_id}:{latest.id}",
                is_provider_confirmed=False,
                provider=latest.provider,
                internal_sku=latest.internal_sku,
                amount=latest.amount,
                currency=latest.currency,
                actor="system_grace_enforcer",
                details={"expired_grace_until": g_dt.isoformat()},
            )
            suspended.append(res)
    return suspended


def restore_subscription_after_recovery(
    db: Session,
    *,
    org_id: str,
    amount: float,
    currency: str = "INR",
    provider: str = "razorpay",
    provider_confirmed: bool = True,
    idempotency_key: str,
    actor: str = "owner",
) -> dict[str, Any]:
    """Restore suspended/past-due entitlements after verified recovery payment."""
    next_ren = datetime.now(UTC) + timedelta(days=30)
    return record_subscription_lifecycle_event(
        db,
        org_id=org_id,
        event_type="PAYMENT_RECOVERED_RESTORED",
        target_state="ACTIVE",
        idempotency_key=idempotency_key,
        is_provider_confirmed=provider_confirmed,
        provider=provider,
        amount=amount,
        currency=currency,
        renewal_date=next_ren,
        actor=actor,
        details={"restored_at": datetime.now(UTC).isoformat()},
    )


def request_or_execute_refund_workflow(
    db: Session,
    *,
    org_id: str,
    invoice_id: str | None = None,
    amount: float,
    currency: str = "INR",
    reason: str,
    approval_id: str | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Enforce mandatory Owner HITL approval before executing any customer refund transition."""
    if not approval_id:
        task_id = str(uuid.uuid4())
        db.add(
            TaskRecord(
                id=task_id,
                correlation_id=org_id,
                objective=f"Approve refund for org {org_id} ({currency} {amount})",
                status="HUMAN_APPROVAL_REQUIRED",
            )
        )
        db.flush()
        req_id = str(uuid.uuid4())
        req_hash = hashlib.sha256(f"{org_id}:{invoice_id}:{amount}:{reason}".encode("utf-8")).hexdigest()
        appr = ApprovalRequest(
            id=req_id,
            task_id=task_id,
            action="subscription_pricing_or_refund_action",
            detail={"org_id": org_id, "invoice_id": invoice_id, "amount": amount, "currency": currency, "reason": reason},
            idempotency_key=f"p3-refund:{org_id}:{req_id[:8]}",
            request_hash=req_hash,
            requested_by=actor,
            status="PENDING",
            decision_note=f"Refund requires explicit owner approval: {reason}",
        )
        db.add(appr)
        db.commit()
        return {
            "status": "APPROVAL_REQUIRED",
            "refund_executed": False,
            "approval_id": appr.id,
        }

    appr = db.get(ApprovalRequest, approval_id)
    if not appr or appr.status != "APPROVED":
        raise ValueError(f"Approved HITL request required before executing refund (approval_id='{approval_id}')")

    if invoice_id:
        inv = db.get(InvoiceRecord, invoice_id)
        if inv and inv.org_id == org_id:
            inv.status = "refunded"
            inv.updated_at = datetime.now(UTC)
            db.add(inv)

    res = record_subscription_lifecycle_event(
        db,
        org_id=org_id,
        event_type="REFUND_EXECUTED",
        target_state="REFUNDED",
        idempotency_key=f"refund-exec:{org_id}:{approval_id}",
        is_provider_confirmed=True,
        provider="owner_approved_refund",
        amount=amount,
        currency=currency,
        approval_id=approval_id,
        actor=actor,
        details={"reason": reason, "invoice_id": invoice_id},
    )
    return {"status": "REFUNDED", "refund_executed": True, "subscription_event": res}


def change_subscription_plan(
    db: Session,
    *,
    org_id: str,
    action: str,
    base_plan_key: str,
    selected_modules: list[str] | None = None,
    billing_interval: str = "monthly",
    currency: str = "INR",
    extra_seats: int = 0,
    extra_agents: int = 0,
    credit_packs: int = 0,
    integration_addons: list[str] | None = None,
    customization_level: str = "standard",
    actor: str = "owner",
) -> dict[str, Any]:
    """Upgrade, downgrade, cancel, or renew via billing_ledger + record P3 subscription history."""
    clean_act = action.strip().lower()
    if clean_act not in ("configure", "upgrade", "downgrade", "cancel", "renew"):
        raise ValueError(f"Unsupported plan change action '{action}'")

    res = apply_subscription_configuration(
        db,
        org_id=org_id,
        actor=actor,
        action=clean_act,
        base_plan_key=base_plan_key,
        selected_modules=selected_modules,
        billing_interval=billing_interval,
        currency=currency,
        extra_seats=extra_seats,
        extra_agents=extra_agents,
        credit_packs=credit_packs,
        integration_addons=integration_addons,
        customization_level=customization_level,
        cancel_at_period_end=(clean_act == "cancel"),
    )
    sub_data = res.get("subscription", {})
    target_state = "CANCELLED" if clean_act == "cancel" else "ACTIVE"
    evt_res = record_subscription_lifecycle_event(
        db,
        org_id=org_id,
        event_type=f"PLAN_{clean_act.upper()}",
        target_state=target_state,
        idempotency_key=f"plan-{clean_act}:{org_id}:{uuid.uuid4().hex[:10]}",
        billing_category="RECURRING_SUBSCRIPTION" if billing_interval != "one_time" else "ONE_TIME_PURCHASE",
        is_provider_confirmed=False,
        provider="catalog_plan_change",
        internal_sku=sub_data.get("internal_sku"),
        billing_interval=billing_interval,
        amount=float(sub_data.get("total_recurring_price", 0)),
        currency=currency,
        actor=actor,
        details={"action": clean_act, "modules": selected_modules or []},
    )
    return {"plan_change": res, "subscription_event": evt_res}


def get_subscription_reliability_summary(db: Session, *, org_id: str | None = None, days_ahead: int = 30) -> dict[str, Any]:
    """Inspect upcoming renewals, provider sync verification, billing categories, and event history."""
    now = datetime.now(UTC)
    horizon = now + timedelta(days=max(1, int(days_ahead)))

    sub_q = db.query(TenantSubscriptionRecord)
    if org_id:
        sub_q = sub_q.filter_by(org_id=org_id)
    subs = sub_q.all()

    upcoming_renewals: list[dict[str, Any]] = []
    for s in subs:
        if s.current_period_end:
            end_dt = s.current_period_end if s.current_period_end.tzinfo else s.current_period_end.replace(tzinfo=UTC)
            if end_dt <= horizon and s.status not in ("cancelled", "expired", "refunded"):
                upcoming_renewals.append(
                    {
                        "org_id": s.org_id,
                        "internal_sku": s.internal_sku,
                        "billing_type": s.billing_type,
                        "billing_interval": s.billing_interval,
                        "amount": s.total_recurring_price,
                        "currency": s.currency,
                        "renewal_date": end_dt.isoformat(),
                        "days_remaining": max(0, (end_dt - now).days),
                        "status": s.status.upper(),
                    }
                )

    evt_q = db.query(P3SubscriptionEventRecord)
    if org_id:
        evt_q = evt_q.filter_by(org_id=org_id)
    events = evt_q.order_by(P3SubscriptionEventRecord.created_at.desc()).limit(50).all()

    prov_q = db.query(SubscriptionRecord)
    if org_id:
        prov_q = prov_q.filter_by(org_id=org_id)
    prov_subs = prov_q.all()

    return {
        "upcoming_renewals": upcoming_renewals,
        "provider_subscriptions_verified": [
            {
                "id": p.id,
                "org_id": p.org_id,
                "provider": p.provider,
                "provider_subscription_id": p.provider_subscription_id,
                "plan_id": p.plan_id,
                "status": p.status,
                "current_period_end": p.current_period_end,
            }
            for p in prov_subs
        ],
        "renewal_history": [serialize_subscription_event(e) for e in events],
    }


def evaluate_expansion_opportunities(
    db: Session,
    *,
    org_id: str,
    actor: str = "expansion_opportunity_agent",
) -> list[dict[str, Any]]:
    """Identify catalog-grounded, evidence-backed upsell, seat, module, or referral opportunities."""
    account = ensure_customer_account(db, org_id=org_id, commit=False)
    org = db.get(OrganizationRecord, org_id)
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")

    tenant_sub = db.query(TenantSubscriptionRecord).filter_by(org_id=org_id).first()
    deliveries = db.query(P3ServiceDeliveryRecord).filter_by(org_id=org_id).all()
    p2_engs = db.query(P2CustomerEngagementRecord).filter_by(org_id=org_id).all()
    tickets = db.query(P3SupportTicketRecord).filter_by(org_id=org_id).all()
    wf_count = db.query(WorkflowRunRecord).filter_by(org_id=org_id, status="COMPLETED").count()

    current_sku = (tenant_sub.internal_sku if tenant_sub else None) or (org.metadata_json or {}).get("package_key") or org.tier
    selected_mods = set((org.metadata_json or {}).get("selected_modules") or (tenant_sub.selected_modules if tenant_sub else []))
    accepted_deliveries = [d for d in deliveries if d.quality_state in ("ACCEPTED", "DELIVERED")]
    positive_ratings = [
        t.csat_rating for t in tickets if t.csat_rating is not None and t.csat_rating >= 4
    ] + [
        e.customer_feedback_json.get("rating")
        for e in p2_engs
        if e.customer_feedback_json and int(e.customer_feedback_json.get("rating", 0)) >= 4
    ]

    candidates: list[dict[str, Any]] = []
    now = datetime.now(UTC)

    # 1. Pilot -> Managed Extension / Launch Subscription Upgrade
    if "pilot" in str(current_sku).lower() and (accepted_deliveries or positive_ratings):
        launch_pkg = get_package("launch") or CATALOG.get("growth_all_in_one")
        if launch_pkg:
            candidates.append(
                {
                    "opportunity_type": "PACKAGE_UPGRADE",
                    "recommended_sku_key": launch_pkg.key,
                    "title": f"Upgrade from pilot to {launch_pkg.name}",
                    "justification": (
                        f"Customer completed {len(accepted_deliveries)} verified deliverable(s) with positive feedback "
                        f"and is eligible to evaluate converting onto the recurring {launch_pkg.name} plan."
                    ),
                    "evidence": [f"accepted_deliveries={len(accepted_deliveries)}", f"positive_ratings={len(positive_ratings)}"],
                    "price_inr": float(launch_pkg.price_inr),
                    "price_usd": float(launch_pkg.price_usd),
                }
            )

    # 2. High credit usage or manual feature requests -> Additional Module
    credit_ratio = (org.lead_credits_used / max(1, org.lead_credits_limit)) if org.lead_credits_limit else 0.0
    if (credit_ratio >= 0.65 or wf_count >= 2) and "marketing_campaigns" not in selected_mods:
        mkt = MODULAR_SERVICE_MODULES.get("marketing_campaigns") or CATALOG.get("marketing_suite")
        inr = float(mkt.get("monthly_inr", 2999) if isinstance(mkt, dict) else mkt.price_inr)
        usd = float(mkt.get("monthly_usd", 39) if isinstance(mkt, dict) else mkt.price_usd)
        candidates.append(
            {
                "opportunity_type": "ADDITIONAL_MODULE",
                "recommended_sku_key": "marketing_suite",
                "title": "Add Omnichannel Marketing Suite Module",
                "justification": (
                    f"Strong platform adoption ({wf_count} completed workflows, {round(credit_ratio * 100, 1)}% credit utilization) "
                    "indicates readiness for automated omnichannel campaign distribution alongside SEO workflows."
                ),
                "evidence": [f"completed_workflows={wf_count}", f"credit_utilization_pct={round(credit_ratio * 100, 1)}"],
                "price_inr": inr,
                "price_usd": usd,
            }
        )

    # 3. Feature request / seat pressure -> Extra Seats or Managed Extension
    feature_tickets = [t for t in tickets if t.category == "feature_request"]
    if feature_tickets or (tenant_sub and tenant_sub.seat_limit <= 3 and len(accepted_deliveries) >= 1):
        candidates.append(
            {
                "opportunity_type": "EXTRA_SEATS",
                "recommended_sku_key": "extra_seat_addon",
                "title": "Add Agency Team Seats",
                "justification": "Agency delivery volume or team collaboration requests justify adding additional user seats at catalog rates.",
                "evidence": [f"current_seat_limit={tenant_sub.seat_limit if tenant_sub else 3}", f"feature_requests={len(feature_tickets)}"],
                "price_inr": float(EXTRA_SEAT_PRICE["INR"]),
                "price_usd": float(EXTRA_SEAT_PRICE["USD"]),
            }
        )

    # 4. Satisfied customer -> Controlled Referral Ask (owner-approved only)
    if positive_ratings and accepted_deliveries:
        candidates.append(
            {
                "opportunity_type": "REFERRAL_REQUEST",
                "recommended_sku_key": None,
                "title": f"Controlled Partner Referral Invitation for {org.name}",
                "justification": (
                    f"Verified delivery acceptance ({len(accepted_deliveries)}) and high CSAT ({max(positive_ratings)}/5) "
                    "support an honest referral request to peer Indian marketing agencies (zero discounts promised)."
                ),
                "evidence": [f"csat_max={max(positive_ratings)}", f"accepted_deliveries={len(accepted_deliveries)}"],
                "price_inr": 0.0,
                "price_usd": 0.0,
            }
        )

    existing_titles = {
        o.title for o in db.query(P3GrowthOpportunityRecord).filter_by(org_id=org_id).all()
    }
    saved: list[dict[str, Any]] = []
    for c in candidates:
        if c["title"] in existing_titles:
            continue
        opp = P3GrowthOpportunityRecord(
            org_id=org_id,
            opportunity_type=c["opportunity_type"],
            recommended_sku_key=c["recommended_sku_key"],
            title=c["title"],
            business_justification=c["justification"],
            supporting_evidence_json=c["evidence"],
            catalog_price_inr=c["price_inr"],
            catalog_price_usd=c["price_usd"],
            currency="INR",
            status="IDENTIFIED",
            referral_code=f"REF-{org.slug[:8].upper()}-{uuid.uuid4().hex[:4].upper()}" if c["opportunity_type"] == "REFERRAL_REQUEST" else None,
            created_at=now,
            updated_at=now,
        )
        db.add(opp)
        db.flush()
        saved.append(serialize_growth_opportunity(opp))

    if saved:
        db.commit()
    all_opps = (
        db.query(P3GrowthOpportunityRecord)
        .filter_by(org_id=org_id)
        .order_by(P3GrowthOpportunityRecord.created_at.desc())
        .all()
    )
    return [serialize_growth_opportunity(o) for o in all_opps]


def authorize_and_share_growth_opportunity(
    db: Session,
    *,
    opportunity_id: str,
    approval_id: str | None = None,
    referred_company: str | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Enforce Owner HITL approval and zero unauthorized discounts before sharing an expansion or referral."""
    opp = db.get(P3GrowthOpportunityRecord, opportunity_id)
    if not opp:
        raise ValueError(f"Growth opportunity '{opportunity_id}' not found")

    if not approval_id:
        task_id = str(uuid.uuid4())
        db.add(
            TaskRecord(
                id=task_id,
                correlation_id=opp.org_id,
                objective=f"Approve expansion/referral offer: {opp.title}",
                status="HUMAN_APPROVAL_REQUIRED",
            )
        )
        db.flush()
        req_id = str(uuid.uuid4())
        req_hash = hashlib.sha256(f"{opp.id}:{opp.title}:{opp.catalog_price_inr}".encode("utf-8")).hexdigest()
        appr = ApprovalRequest(
            id=req_id,
            task_id=task_id,
            action="expansion_offer_or_referral",
            detail={
                "org_id": opp.org_id,
                "opportunity_id": opp.id,
                "opportunity_type": opp.opportunity_type,
                "recommended_sku_key": opp.recommended_sku_key,
                "catalog_price_inr": opp.catalog_price_inr,
            },
            idempotency_key=f"p3-growth:{opp.id}:{req_id[:8]}",
            request_hash=req_hash,
            requested_by=actor,
            status="PENDING",
            decision_note="Owner authorization required for commercial expansion offer or referral outreach.",
        )
        db.add(appr)
        opp.approval_id = appr.id
        db.add(opp)
        db.commit()
        return {"status": "APPROVAL_REQUIRED", "shared": False, "approval_id": appr.id, "opportunity": serialize_growth_opportunity(opp)}

    appr = db.get(ApprovalRequest, approval_id)
    if not appr or appr.status != "APPROVED":
        raise ValueError("Growth opportunity cannot be shared until Owner HITL approval is APPROVED.")

    now = datetime.now(UTC)
    opp.status = "SHARED"
    opp.approval_id = approval_id
    opp.owner_authorized_by = actor
    opp.authorized_at = now
    if referred_company:
        opp.referred_company = referred_company.strip()
    opp.updated_at = now
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return {"status": "SHARED", "shared": True, "opportunity": serialize_growth_opportunity(opp)}


def set_customer_cost_budget(
    db: Session,
    *,
    org_id: str,
    monthly_cost_limit_inr: float,
    alert_threshold_pct: float = 80.0,
    hard_cap_enforced: bool = True,
    exception_approval_id: str | None = None,
    exception_limit_inr: float | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Configure per-organization spend caps and optional HITL-approved exceptional spend overrides."""
    ensure_customer_account(db, org_id=org_id, commit=False)
    if exception_approval_id:
        appr = db.get(ApprovalRequest, exception_approval_id)
        if not appr or appr.status != "APPROVED":
            raise ValueError("Exception budget override requires an APPROVED Owner ApprovalRequest")

    budget = db.query(P3CustomerCostBudgetRecord).filter_by(org_id=org_id).first()
    now = datetime.now(UTC)
    if budget is None:
        budget = P3CustomerCostBudgetRecord(
            org_id=org_id,
            monthly_cost_limit_inr=float(monthly_cost_limit_inr),
            alert_threshold_pct=float(alert_threshold_pct),
            hard_cap_enforced=bool(hard_cap_enforced),
            exception_approval_id=exception_approval_id,
            exception_limit_inr=float(exception_limit_inr) if exception_limit_inr is not None else None,
            exception_expires_at=(now + timedelta(days=30)) if exception_approval_id else None,
            updated_by=actor,
            updated_at=now,
        )
        db.add(budget)
    else:
        budget.monthly_cost_limit_inr = float(monthly_cost_limit_inr)
        budget.alert_threshold_pct = float(alert_threshold_pct)
        budget.hard_cap_enforced = bool(hard_cap_enforced)
        if exception_approval_id:
            budget.exception_approval_id = exception_approval_id
            budget.exception_limit_inr = float(exception_limit_inr or monthly_cost_limit_inr)
            budget.exception_expires_at = now + timedelta(days=30)
        budget.updated_by = actor
        budget.updated_at = now
        db.add(budget)
    db.commit()
    db.refresh(budget)
    return {
        "org_id": budget.org_id,
        "monthly_cost_limit_inr": budget.monthly_cost_limit_inr,
        "alert_threshold_pct": budget.alert_threshold_pct,
        "hard_cap_enforced": budget.hard_cap_enforced,
        "exception_limit_inr": budget.exception_limit_inr,
        "exception_approval_id": budget.exception_approval_id,
    }


def record_unit_economics_cost(
    db: Session,
    *,
    org_id: str,
    cost_category: str,
    cost_type_label: str,
    amount_inr: float,
    service_id: str = "general",
    delivery_id: str | None = None,
    workflow_run_id: str | None = None,
    execution_id: str | None = None,
    provider: str = "internal",
    tokens_input: int = 0,
    tokens_output: int = 0,
    amount_usd: float = 0.0,
    evidence_ref: str | None = None,
    notes: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Record ACTUAL, ALLOCATED, or ESTIMATED customer cost while enforcing spend budgets."""
    ensure_customer_account(db, org_id=org_id, commit=False)
    clean_cat = cost_category.strip().upper()
    if clean_cat not in COST_CATEGORIES:
        raise ValueError(f"cost_category must be one of {COST_CATEGORIES}")
    clean_label = cost_type_label.strip().upper()
    if clean_label not in COST_TYPE_LABELS:
        raise ValueError(f"cost_type_label must be one of {COST_TYPE_LABELS}")

    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    existing_month_cost = sum(
        float(e.amount_inr or 0.0)
        for e in db.query(P3UnitEconomicsEntryRecord)
        .filter(
            P3UnitEconomicsEntryRecord.org_id == org_id,
            P3UnitEconomicsEntryRecord.cost_category != "ACQUISITION_COST",
            P3UnitEconomicsEntryRecord.recorded_at >= month_start,
        )
        .all()
    )
    projected_total = existing_month_cost + float(amount_inr)
    budget = db.query(P3CustomerCostBudgetRecord).filter_by(org_id=org_id).first()

    if budget and clean_cat != "ACQUISITION_COST":
        effective_cap = float(budget.monthly_cost_limit_inr)
        if budget.exception_approval_id and budget.exception_limit_inr and budget.exception_expires_at:
            exp = budget.exception_expires_at if budget.exception_expires_at.tzinfo else budget.exception_expires_at.replace(tzinfo=UTC)
            if exp >= now:
                effective_cap = max(effective_cap, float(budget.exception_limit_inr))

        if projected_total > effective_cap and budget.hard_cap_enforced:
            db.add(
                P3OperationalIncidentRecord(
                    org_id=org_id,
                    incident_type="COST_BUDGET_BREACH",
                    severity="HIGH",
                    status="OPEN",
                    summary=f"Blocked spend INR {amount_inr} for org {org_id}: projected INR {projected_total} > cap INR {effective_cap}",
                    details_json={"projected_inr": projected_total, "cap_inr": effective_cap},
                )
            )
            db.commit()
            raise CostBudgetExceededError(
                f"Projected monthly cost INR {round(projected_total, 2)} exceeds configured cap INR {round(effective_cap, 2)} without Owner exception approval."
            )

        if effective_cap > 0 and (projected_total / effective_cap) * 100.0 >= budget.alert_threshold_pct:
            db.add(
                SupervisorAlertRecord(
                    org_id=org_id,
                    alert_type="COST_THRESHOLD_ALERT",
                    severity="MEDIUM",
                    title=f"Usage cost approaching limit for org {org_id}",
                    description=f"Monthly cost reached INR {round(projected_total, 2)} / INR {round(effective_cap, 2)}.",
                    suggested_action="Review token/provider usage or request Owner budget exception.",
                    metadata_json={"internal_only": True},
                )
            )

    entry = P3UnitEconomicsEntryRecord(
        org_id=org_id,
        service_id=service_id.strip(),
        delivery_id=delivery_id,
        workflow_run_id=workflow_run_id,
        execution_id=execution_id,
        cost_category=clean_cat,
        cost_type_label=clean_label,
        provider=provider.strip().lower(),
        tokens_input=max(0, int(tokens_input)),
        tokens_output=max(0, int(tokens_output)),
        amount_inr=float(amount_inr),
        amount_usd=float(amount_usd or round(float(amount_inr) / 84.0, 2)),
        currency="INR",
        evidence_ref=evidence_ref,
        notes=notes,
        recorded_by=actor,
        recorded_at=now,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return serialize_cost_entry(entry)


def compute_customer_unit_economics(db: Session, *, org_id: str) -> dict[str, Any]:
    """Compute customer & service revenue, ACTUAL/ALLOCATED/ESTIMATED costs, margin, and honest CAC/LTV gaps."""
    ensure_customer_account(db, org_id=org_id, commit=False)
    invoices = db.query(InvoiceRecord).filter_by(org_id=org_id).all()
    entries = db.query(P3UnitEconomicsEntryRecord).filter_by(org_id=org_id).all()
    evidences = db.query(ExecutionEvidenceRecord).filter_by(tenant_id=org_id).all()
    budget = db.query(P3CustomerCostBudgetRecord).filter_by(org_id=org_id).first()

    paid_inr = 0.0
    refunded_inr = 0.0
    revenue_by_service: dict[str, float] = {}
    for inv in invoices:
        if (inv.currency or "INR").upper() != "INR":
            continue
        amt = float(inv.amount or 0) / 100.0
        svc_key = str((inv.metadata_json or {}).get("package_key") or "subscription")
        if inv.status == "paid":
            paid_inr += amt
            revenue_by_service[svc_key] = round(revenue_by_service.get(svc_key, 0.0) + amt, 2)
        elif inv.status == "refunded":
            refunded_inr += amt

    net_verified_revenue_inr = round(max(0.0, paid_inr - refunded_inr), 2)

    costs_by_label: dict[str, float] = {"ACTUAL": 0.0, "ALLOCATED": 0.0, "ESTIMATED": 0.0}
    costs_by_category: dict[str, float] = {}
    costs_by_service: dict[str, float] = {}
    cac_inr = 0.0
    has_actual_cac = False
    direct_delivery_inr = 0.0
    support_cost_inr = 0.0
    ai_api_cost_inr = 0.0
    infra_cost_inr = 0.0
    human_delivery_inr = 0.0

    total_tokens_in = sum(int(e.tokens_input or 0) for e in entries)
    total_tokens_out = sum(int(e.tokens_output or 0) for e in entries)
    for ev in evidences:
        tok = (ev.metadata_json or {}).get("token_usage") or {}
        total_tokens_in += int(tok.get("input_tokens", 0) or 0)
        total_tokens_out += int(tok.get("output_tokens", 0) or 0)

    for e in entries:
        amt = float(e.amount_inr or 0.0)
        lbl = e.cost_type_label
        costs_by_label[lbl] = round(costs_by_label.get(lbl, 0.0) + amt, 2)
        if e.cost_category == "ACQUISITION_COST":
            cac_inr += amt
            if lbl == "ACTUAL":
                has_actual_cac = True
            continue
        costs_by_category[e.cost_category] = round(costs_by_category.get(e.cost_category, 0.0) + amt, 2)
        costs_by_service[e.service_id] = round(costs_by_service.get(e.service_id, 0.0) + amt, 2)
        if e.cost_category in ("AI_API_USAGE", "HUMAN_DELIVERY"):
            direct_delivery_inr += amt
        if e.cost_category == "AI_API_USAGE":
            ai_api_cost_inr += amt
        elif e.cost_category == "INFRASTRUCTURE_ALLOCATION":
            infra_cost_inr += amt
        elif e.cost_category == "HUMAN_DELIVERY":
            human_delivery_inr += amt
        elif e.cost_category == "SUPPORT_COST":
            support_cost_inr += amt

    total_operating_cost_inr = round(
        direct_delivery_inr + infra_cost_inr + support_cost_inr,
        2,
    )
    gross_profit_inr = round(net_verified_revenue_inr - total_operating_cost_inr, 2) if (invoices or entries) else None
    gross_margin_pct = (
        round((gross_profit_inr / net_verified_revenue_inr) * 100.0, 2)
        if (gross_profit_inr is not None and net_verified_revenue_inr > 0)
        else None
    )

    # Strict honesty rule: NEVER fabricate CAC or LTV as historical performance without actual multi-period data
    paid_invoice_months = len([i for i in invoices if i.status == "paid"])
    if has_actual_cac and paid_invoice_months >= 2 and net_verified_revenue_inr > 0:
        ltv_inr: float | str = round(net_verified_revenue_inr, 2)
        ltv_status = "OBSERVED_HISTORICAL"
        payback_months: float | str = round(cac_inr / max(1.0, (net_verified_revenue_inr / paid_invoice_months)), 1)
    else:
        ltv_inr = "INSUFFICIENT_DATA"
        ltv_status = "INSUFFICIENT_DATA"
        payback_months = "INSUFFICIENT_DATA"

    return {
        "org_id": org_id,
        "revenue_summary": {
            "verified_gross_revenue_inr": round(paid_inr, 2),
            "refunded_inr": round(refunded_inr, 2),
            "net_verified_revenue_inr": net_verified_revenue_inr,
            "revenue_by_service": revenue_by_service,
        },
        "cost_summary": {
            "direct_delivery_cost_inr": round(direct_delivery_inr, 2),
            "ai_api_usage_cost_inr": round(ai_api_cost_inr, 2),
            "infrastructure_allocated_cost_inr": round(infra_cost_inr, 2),
            "human_delivery_cost_inr": round(human_delivery_inr, 2),
            "support_cost_inr": round(support_cost_inr, 2),
            "total_operating_cost_inr": total_operating_cost_inr,
            "costs_by_quality_label": costs_by_label,
            "costs_by_category": costs_by_category,
            "costs_by_service": costs_by_service,
        },
        "token_telemetry": {
            "tokens_input": total_tokens_in,
            "tokens_output": total_tokens_out,
        },
        "profitability": {
            "gross_profit_inr": gross_profit_inr,
            "gross_margin_pct": gross_margin_pct,
        },
        "acquisition_and_ltv": {
            "customer_acquisition_cost_inr": round(cac_inr, 2) if cac_inr > 0 else "INSUFFICIENT_DATA",
            "cac_data_quality": "ACTUAL" if has_actual_cac else ("ESTIMATED" if cac_inr > 0 else "INSUFFICIENT_DATA"),
            "customer_lifetime_value_inr": ltv_inr,
            "ltv_data_quality": ltv_status,
            "payback_months": payback_months,
            "note": "Historical CAC/LTV requires verified ACTUAL acquisition cost and >=2 verified billing periods; otherwise labeled INSUFFICIENT_DATA.",
        },
        "cost_budget": {
            "monthly_cost_limit_inr": budget.monthly_cost_limit_inr if budget else 2000.0,
            "alert_threshold_pct": budget.alert_threshold_pct if budget else 80.0,
            "hard_cap_enforced": budget.hard_cap_enforced if budget else True,
        },
    }


def serialize_subscription_event(e: P3SubscriptionEventRecord) -> dict[str, Any]:
    return {
        "event_id": e.id,
        "org_id": e.org_id,
        "subscription_id": e.subscription_id,
        "idempotency_key": e.idempotency_key,
        "event_type": e.event_type,
        "subscription_state": e.subscription_state,
        "billing_category": e.billing_category,
        "is_provider_confirmed": e.is_provider_confirmed,
        "provider_confirmed_recurring": bool(e.is_provider_confirmed and e.billing_category == "RECURRING_SUBSCRIPTION"),
        "provider": e.provider,
        "provider_subscription_id": e.provider_subscription_id,
        "internal_sku": e.internal_sku,
        "billing_interval": e.billing_interval,
        "amount": e.amount,
        "currency": e.currency,
        "renewal_date": e.renewal_date.isoformat() if e.renewal_date else None,
        "grace_until": e.grace_until.isoformat() if e.grace_until else None,
        "approval_id": e.approval_id,
        "actor": e.actor,
        "details": e.details_json or {},
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def serialize_growth_opportunity(o: P3GrowthOpportunityRecord) -> dict[str, Any]:
    return {
        "opportunity_id": o.id,
        "org_id": o.org_id,
        "opportunity_type": o.opportunity_type,
        "recommended_sku_key": o.recommended_sku_key,
        "title": o.title,
        "business_justification": o.business_justification,
        "supporting_evidence": o.supporting_evidence_json or [],
        "catalog_price_inr": o.catalog_price_inr,
        "catalog_price_usd": o.catalog_price_usd,
        "currency": o.currency,
        "status": o.status,
        "approval_id": o.approval_id,
        "referral_code": o.referral_code,
        "referred_company": o.referred_company,
        "owner_authorized_by": o.owner_authorized_by,
        "authorized_at": o.authorized_at.isoformat() if o.authorized_at else None,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


def serialize_cost_entry(e: P3UnitEconomicsEntryRecord) -> dict[str, Any]:
    return {
        "entry_id": e.id,
        "org_id": e.org_id,
        "service_id": e.service_id,
        "delivery_id": e.delivery_id,
        "workflow_run_id": e.workflow_run_id,
        "execution_id": e.execution_id,
        "cost_category": e.cost_category,
        "cost_type_label": e.cost_type_label,
        "provider": e.provider,
        "tokens_input": e.tokens_input,
        "tokens_output": e.tokens_output,
        "amount_inr": e.amount_inr,
        "amount_usd": e.amount_usd,
        "currency": e.currency,
        "evidence_ref": e.evidence_ref,
        "notes": e.notes,
        "recorded_by": e.recorded_by,
        "recorded_at": e.recorded_at.isoformat() if e.recorded_at else None,
    }
