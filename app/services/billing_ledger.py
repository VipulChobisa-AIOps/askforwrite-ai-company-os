"""Modular subscription architecture, 15-field pricing contract, canonical SKU analytics, and atomic credit ledger."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import (
    AuditLog,
    CreditLedgerRecord,
    OrganizationRecord,
    SubscriptionRecord,
    TenantSubscriptionRecord,
)
from app.services.catalog import (
    CATALOG,
    MODULAR_SERVICE_MODULES,
    MODULAR_SME_TIERS,
    PackageDefinition,
    get_modular_pricing_contract,
    get_package,
)


class InsufficientCreditsError(ValueError):
    """Raised when a tenant lacks sufficient execution/lead credits."""


class InsufficientAICreditsError(InsufficientCreditsError):
    """Raised when a tenant lacks sufficient Managed AI Usage Credits (triggers HTTP 402)."""


class DailySpendCapExceededError(InsufficientCreditsError):
    """Raised when a tenant exceeds its daily platform AI COGS safety ceiling."""


# Transparent action -> Managed AI Credit costs (>95% gross margin at ₹5/credit vs Gemini Flash COGS)
AI_CREDIT_COSTS: dict[str, int] = {
    "seo_blog_copilot": 10,
    "managed_seo_content_pilot": 10,
    "seo_article_with_qa": 10,
    "digital_qa": 2,
    "digital_qa_benchmark": 2,
    "marketing_suite": 5,
    "growth_all_in_one": 5,
    "ask4_academic_order": 5,
    "pixel_ai_pack": 5,
    "field_receipt_ocr": 1,
    "field_photo_vision": 1,
    "field_voice_debrief": 1,
    "warehouse_ai_brief": 2,
    "default": 1,
}

AI_CREDIT_TOPUP_PACKS: dict[str, dict[str, int]] = {
    "ai_credits_100": {"credits": 100, "INR": 499, "USD": 7},
    "ai_credits_500": {"credits": 500, "INR": 1999, "USD": 25},
    "ai_credits_2000": {"credits": 2000, "INR": 6499, "USD": 79},
}

TIER_AI_CREDIT_ALLOWANCES: dict[str, dict[str, Any]] = {
    "managed_pilot": {"ai_credits": 100, "daily_spend_cap_inr": 100.0},
    "managed_seo_content_pilot": {"ai_credits": 100, "daily_spend_cap_inr": 100.0},
    "launch": {"ai_credits": 150, "daily_spend_cap_inr": 100.0},
    "starter": {"ai_credits": 150, "daily_spend_cap_inr": 100.0},
    "company_os_starter": {"ai_credits": 150, "daily_spend_cap_inr": 100.0},
    "modular_seo": {"ai_credits": 150, "daily_spend_cap_inr": 100.0},
    "modular_marketing": {"ai_credits": 150, "daily_spend_cap_inr": 100.0},
    "modular_field_ops": {"ai_credits": 150, "daily_spend_cap_inr": 100.0},
    "modular_inventory_ai": {"ai_credits": 150, "daily_spend_cap_inr": 100.0},
    "modular_trust": {"ai_credits": 150, "daily_spend_cap_inr": 100.0},
    "growth": {"ai_credits": 600, "daily_spend_cap_inr": 350.0},
    "growth_all_in_one": {"ai_credits": 600, "daily_spend_cap_inr": 350.0},
    "pro": {"ai_credits": 600, "daily_spend_cap_inr": 350.0},
    "business_pro": {"ai_credits": 600, "daily_spend_cap_inr": 350.0},
    "company_os_pro": {"ai_credits": 600, "daily_spend_cap_inr": 350.0},
    "operations": {"ai_credits": 800, "daily_spend_cap_inr": 400.0},
    "operations_suite": {"ai_credits": 800, "daily_spend_cap_inr": 400.0},
    "enterprise": {"ai_credits": 3000, "daily_spend_cap_inr": 1500.0},
    "company_os_enterprise": {"ai_credits": 3000, "daily_spend_cap_inr": 1500.0},
    "all_access": {"ai_credits": 3000, "daily_spend_cap_inr": 1500.0},
    "free": {"ai_credits": 0, "daily_spend_cap_inr": 0.0},
}


# Map canonical SKUs & provider plan IDs to MRR monthly INR & USD equivalents
EXTRA_AGENT_PRICE = {"INR": 999, "USD": 15}
EXTRA_SEAT_PRICE = {"INR": 499, "USD": 8}
CREDIT_PACK_UNIT = {"credits": 100, "INR": 1499, "USD": 19}
INTEGRATION_ADDON_PRICE = {"INR": 1499, "USD": 19}
CUSTOMIZATION_LEVELS = {
    "standard": {"INR": 0, "USD": 0, "custom_workflows": 3, "custom_connectors": 2},
    "bespoke_workflows": {"INR": 4999, "USD": 59, "custom_workflows": 15, "custom_connectors": 8},
    "enterprise_dedicated": {"INR": 14999, "USD": 179, "custom_workflows": 100, "custom_connectors": 50},
}

# Module -> capability and agent mappings so modular plans activate real capabilities cleanly
MODULE_CAPABILITY_MAP: dict[str, dict[str, Any]] = {
    "lead_discovery": {
        "capabilities": ["lead_generation", "customer_discovery"],
        "agents": ["discovery_sdr_agent"],
        "price_inr": 1999,
        "price_usd": 29,
    },
    "research_intelligence": {
        "capabilities": ["evidence_research", "askforwrite_academic_ask4"],
        "agents": ["research_analyst_agent", "academic_research_agent"],
        "price_inr": 1499,
        "price_usd": 19,
    },
    "sales_proposals": {
        "capabilities": ["sales_proposal", "inbound_sales_closer"],
        "agents": ["sales_proposal_agent"],
        "price_inr": 2499,
        "price_usd": 29,
    },
    "seo": {
        "capabilities": ["seo_content_automation", "seo_blog_copilot", "digital_qa", "wordpress_publisher"],
        "agents": ["seo_content_agent", "digital_qa_agent"],
        "price_inr": 1999,
        "price_usd": 29,
    },
    "seo_content": {
        "capabilities": ["seo_content_automation", "seo_blog_copilot", "digital_qa", "wordpress_publisher"],
        "agents": ["seo_content_agent", "digital_qa_agent"],
        "price_inr": 1999,
        "price_usd": 29,
    },
    "marketing": {
        "capabilities": ["marketing_campaign_suite", "pixel_ai_creative_studio"],
        "agents": ["marketing_creative_agent"],
        "price_inr": 2499,
        "price_usd": 35,
    },
    "marketing_campaigns": {
        "capabilities": ["marketing_campaign_suite", "pixel_ai_creative_studio"],
        "agents": ["marketing_creative_agent"],
        "price_inr": 2499,
        "price_usd": 35,
    },
    "sales": {
        "capabilities": ["sales_proposal", "lead_generation", "customer_discovery", "inbound_sales_closer", "support_followup"],
        "agents": ["sales_proposal_agent", "discovery_sdr_agent"],
        "price_inr": 3499,
        "price_usd": 45,
    },
    "customer_ops": {
        "capabilities": ["support_followup", "trust_ledger_audit", "digital_qa"],
        "agents": ["support_followup_agent", "trust_governance_agent", "digital_qa_agent"],
        "price_inr": 3499,
        "price_usd": 45,
    },
    "customer_support": {
        "capabilities": ["support_followup"],
        "agents": ["support_followup_agent"],
        "price_inr": 1999,
        "price_usd": 29,
    },
    "field_force": {
        "capabilities": ["field_force_automation", "delivery_field_force"],
        "agents": ["field_ops_agent"],
        "price_inr": 3999,
        "price_usd": 49,
    },
    "field_operations": {
        "capabilities": ["field_force_automation", "delivery_field_force"],
        "agents": ["field_ops_agent"],
        "price_inr": 3999,
        "price_usd": 49,
    },
    "inventory": {
        "capabilities": ["warehouse_automation", "warehouse_stocksense", "inventory_analytics"],
        "agents": ["warehouse_stocksense_agent"],
        "price_inr": 3999,
        "price_usd": 49,
    },
    "inventory_quality": {
        "capabilities": ["warehouse_automation", "warehouse_stocksense", "inventory_analytics", "digital_qa"],
        "agents": ["warehouse_stocksense_agent", "digital_qa_agent"],
        "price_inr": 3999,
        "price_usd": 49,
    },
    "governance_trust": {
        "capabilities": ["trust_ledger_audit"],
        "agents": ["trust_governance_agent", "ceo_manager_agent"],
        "price_inr": 3999,
        "price_usd": 49,
    },
}


def build_canonical_package_contract(
    package_or_tier_key: str,
    *,
    currency: str = "INR",
    billing_interval: str = "monthly",
) -> dict[str, Any]:
    """Return all 15 required canonical subscription contract fields for any SKU or tier."""
    base = get_modular_pricing_contract(package_or_tier_key)
    tier_info = MODULAR_SME_TIERS.get(package_or_tier_key)
    sku_key = base["sku_key"]
    cur = currency.upper() if currency.upper() in ("INR", "USD") else "INR"
    interval = billing_interval.lower() if billing_interval.lower() in ("monthly", "annual", "one_time") else "monthly"

    # Derive entitled agents from included modules + tier scope
    entitled_agents: list[str] = ["ceo_manager_agent"] if any(k in sku_key for k in ("growth", "operations", "enterprise", "all_access", "pro")) else []
    for mod in base.get("included_modules", []):
        m_info = MODULE_CAPABILITY_MAP.get(mod)
        if m_info:
            for ag in m_info["agents"]:
                if ag not in entitled_agents:
                    entitled_agents.append(ag)
    if not entitled_agents:
        entitled_agents = ["seo_content_agent", "research_analyst_agent"]

    if sku_key in ("company_os_enterprise", "all_access") or (tier_info and package_or_tier_key == "enterprise"):
        for mod_info in MODULE_CAPABILITY_MAP.values():
            for ag in mod_info["agents"]:
                if ag not in entitled_agents:
                    entitled_agents.append(ag)

    credits_dict = base.get("included_credits", {})
    exec_limit = int(credits_dict.get("ai_execution_credits", 300))

    b_type = "one_time" if (interval == "one_time" or base.get("billing_type") == "one_time_purchase") else "recurring"
    base_price_inr = int(base["base_price"].get("inr", 0))
    base_price_usd = int(base["base_price"].get("usd", 0))
    annual_price = base.get("annual_price") or {
        "inr": round(base_price_inr * 0.8),
        "usd": round(base_price_usd * 0.8),
        "discount_pct": 20,
    }
    contract = {
        **base,
        # Canonical 15 fields (§5) + cluster metadata
        "internal_sku": sku_key,
        "plan_name": base.get("plan_name") or base.get("name") or sku_key,
        "included_clusters": list(base.get("included_clusters", [])),
        "annual_price": annual_price,
        "billing_type": b_type,
        "billing_interval": interval,
        "base_price": base["base_price"],
        "currency": cur,
        "provider_plan_id": base["provider_plan_id"],
        "included_modules": list(base.get("included_modules", [])),
        "entitled_agents": entitled_agents,
        "agent_execution_limit": exec_limit,
        "included_credits": int(credits_dict.get("lead_credits", 100) + credits_dict.get("ai_execution_credits", 100)),
        "credit_costs": dict(base.get("credit_costs", {"agent_run": 1})),
        "seat_limit": int(base.get("seat_limit", 5)),
        "setup_fee": base["setup_fee"],
        "support_level": base["support_level"],
        "customization_allowance": {
            "mode": base.get("customization_allowance", "standard"),
            "custom_workflows": 10 if "pro" in sku_key or "enterprise" in sku_key else 3,
            "custom_connectors": 8 if "pro" in sku_key or "enterprise" in sku_key else 2,
        },
        "renewal_policy": base["renewal_policy"],
    }
    return contract


def resolve_internal_sku_for_subscription(sub: SubscriptionRecord) -> dict[str, Any]:
    """Map any SubscriptionRecord (by metadata internal_sku, package_key, or provider plan_id) to its canonical SKU & MRR."""
    meta = sub.metadata_json if isinstance(sub.metadata_json, dict) else {}
    candidate = meta.get("internal_sku") or meta.get("package_key") or sub.plan_id or ""

    pkg: PackageDefinition | None = get_package(candidate) or CATALOG.get(candidate)
    if pkg is None:
        # Reverse-lookup provider plan ID (plan_... or P-...)
        for p_key, p_def in CATALOG.items():
            c = get_modular_pricing_contract(p_key)
            prov_ids = c.get("provider_plan_id", {})
            if candidate in prov_ids.values() or candidate == p_key:
                pkg = p_def
                break

    if pkg is None:
        return {
            "internal_sku": meta.get("internal_sku") or f"custom:{candidate or 'unknown'}",
            "matched": False,
            "billing_interval": meta.get("billing_interval", "monthly"),
            "monthly_mrr_inr": int(meta.get("monthly_mrr_inr", 0) or 0),
            "monthly_mrr_usd": int(meta.get("monthly_mrr_usd", 0) or 0),
        }

    interval = str(meta.get("billing_interval", "monthly")).lower()
    raw_inr = int(meta.get("total_recurring_price") or pkg.price_inr)
    raw_usd = pkg.price_usd
    if pkg.category == "b2c_one_off":
        monthly_inr = 0
        monthly_usd = 0
    elif interval == "annual":
        monthly_inr = round(raw_inr / 12)
        monthly_usd = round((raw_usd * 10) / 12)
    else:
        monthly_inr = raw_inr
        monthly_usd = raw_usd

    return {
        "internal_sku": pkg.key,
        "matched": True,
        "billing_interval": interval,
        "monthly_mrr_inr": monthly_inr,
        "monthly_mrr_usd": monthly_usd,
    }


def compose_modular_pricing(
    *,
    base_plan_key: str = "launch",
    selected_modules: list[str] | None = None,
    billing_type: str = "recurring",
    billing_interval: str = "monthly",
    currency: str = "INR",
    extra_agents: int = 0,
    extra_seats: int = 0,
    credit_packs: int = 0,
    integration_addons: list[str] | None = None,
    setup_fee_override: int | None = None,
    customization_level: str = "standard",
) -> dict[str, Any]:
    """Calculate full composed SME subscription pricing, entitlements, limits, and credits."""
    cur = currency.upper() if currency.upper() in ("INR", "USD") else "INR"
    interval = billing_interval.lower() if billing_interval.lower() in ("monthly", "annual", "one_time") else "monthly"
    contract = build_canonical_package_contract(base_plan_key, currency=cur, billing_interval=interval)

    base_monthly = int(contract["base_price"]["inr"] if cur == "INR" else contract["base_price"]["usd"])
    included_mods = list(contract["included_modules"])
    mods = list(dict.fromkeys([m.strip().lower() for m in (selected_modules or []) if m and m.strip()]))

    module_total = 0
    all_caps: set[str] = set()
    entitled_agents: list[str] = list(contract["entitled_agents"])
    pkg = get_package(contract["internal_sku"])
    if pkg:
        all_caps.update(pkg.entitled_capabilities)

    # Ensure capabilities from included modules AND selected/addon modules come directly from MODULAR_SERVICE_MODULES + MODULE_CAPABILITY_MAP
    effective_mods = list(dict.fromkeys(included_mods + mods))
    addon_mods: list[str] = []
    for mod in effective_mods:
        mod_spec = MODULE_CAPABILITY_MAP.get(mod)
        cat_mod = MODULAR_SERVICE_MODULES.get(mod)
        if mod in mods and mod not in included_mods:
            addon_mods.append(mod)
            if cat_mod and ("monthly_price_inr" in cat_mod or "monthly_inr" in cat_mod):
                inr_val = cat_mod.get("monthly_price_inr", cat_mod.get("monthly_inr", 0))
                usd_val = cat_mod.get("monthly_price_usd", cat_mod.get("monthly_usd", 29))
                module_total += int(inr_val if cur == "INR" else usd_val)
            elif mod_spec:
                module_total += mod_spec["price_inr"] if cur == "INR" else mod_spec["price_usd"]
        if cat_mod:
            for c in cat_mod.get("capabilities", []):
                all_caps.add(str(c))
            for ag in cat_mod.get("agents", []):
                if str(ag) not in entitled_agents:
                    entitled_agents.append(str(ag))
        if mod_spec:
            all_caps.update(mod_spec["capabilities"])
            for ag in mod_spec["agents"]:
                if ag not in entitled_agents:
                    entitled_agents.append(ag)

    extra_agents_cnt = max(0, int(extra_agents))
    extra_seats_cnt = max(0, int(extra_seats))
    packs_cnt = max(0, int(credit_packs))
    addons_list = [a.strip().lower() for a in (integration_addons or []) if a and a.strip()]

    agents_cost = extra_agents_cnt * EXTRA_AGENT_PRICE[cur]
    seats_cost = extra_seats_cnt * EXTRA_SEAT_PRICE[cur]
    integrations_cost = len(addons_list) * INTEGRATION_ADDON_PRICE[cur]
    credit_packs_cost = packs_cnt * CREDIT_PACK_UNIT[cur]
    cust_spec = CUSTOMIZATION_LEVELS.get(customization_level, CUSTOMIZATION_LEVELS["standard"])
    cust_cost = int(cust_spec[cur])

    monthly_recurring = base_monthly + module_total + agents_cost + seats_cost + integrations_cost
    if interval == "annual":
        # 2 months free on annual commitment
        recurring_charge = round(monthly_recurring * 10)
    elif billing_type == "one_time" or interval == "one_time":
        recurring_charge = monthly_recurring
    else:
        recurring_charge = monthly_recurring

    setup_default = int(contract["setup_fee"]["inr"] if cur == "INR" else contract["setup_fee"]["usd"])
    setup_charge = (setup_fee_override if setup_fee_override is not None else setup_default) + cust_cost + credit_packs_cost

    included_credits = int(contract["included_credits"]) + (packs_cnt * CREDIT_PACK_UNIT["credits"])
    lead_limit = int(contract["included_credits"]) + (packs_cnt * CREDIT_PACK_UNIT["credits"])
    outreach_limit = max(25, round(lead_limit * 0.5))
    agent_exec_limit = int(contract["agent_execution_limit"]) + (packs_cnt * 100) + (extra_agents_cnt * 100)

    return {
        "internal_sku": contract["internal_sku"],
        "package_name": contract["name"],
        "billing_type": "one_time" if (billing_type == "one_time" or interval == "one_time") else "recurring",
        "billing_interval": interval,
        "currency": cur,
        "base_price": contract["base_price"],
        "provider_plan_id": contract["provider_plan_id"],
        "included_modules": included_mods,
        "selected_modules": mods or included_mods,
        "addon_modules": addon_mods,
        "entitled_agents": entitled_agents,
        "entitled_capabilities": sorted(all_caps),
        "agent_execution_limit": agent_exec_limit,
        "included_credits": included_credits,
        "lead_credits_limit": lead_limit,
        "outreach_credits_limit": outreach_limit,
        "credit_costs": contract["credit_costs"],
        "seat_limit": int(contract["seat_limit"]) + extra_seats_cnt,
        "setup_fee": setup_default,
        "support_level": contract["support_level"],
        "customization_allowance": {
            "level": customization_level,
            "custom_workflows": cust_spec["custom_workflows"],
            "custom_connectors": cust_spec["custom_connectors"],
        },
        "renewal_policy": contract["renewal_policy"],
        "extra_agents": extra_agents_cnt,
        "extra_seats": extra_seats_cnt,
        "credit_packs_purchased": packs_cnt,
        "integration_addons": addons_list,
        "monthly_equivalent_price": monthly_recurring,
        "total_recurring_price": recurring_charge,
        "total_setup_price": setup_charge,
        "total_due_now": recurring_charge + setup_charge,
    }


def apply_subscription_configuration(
    db: Session,
    *,
    org_id: str,
    actor: str,
    action: str = "configure",
    base_plan_key: str = "launch",
    selected_modules: list[str] | None = None,
    billing_type: str = "recurring",
    billing_interval: str = "monthly",
    currency: str = "INR",
    extra_agents: int = 0,
    extra_seats: int = 0,
    credit_packs: int = 0,
    integration_addons: list[str] | None = None,
    customization_level: str = "standard",
    cancel_at_period_end: bool = True,
) -> dict[str, Any]:
    """Configure, upgrade, downgrade, cancel, renew, or buy credit packs atomically for a tenant."""
    org = db.get(OrganizationRecord, org_id)
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")

    sub_prof = db.query(TenantSubscriptionRecord).filter_by(org_id=org_id).first()
    now = datetime.now(UTC)
    clean_action = action.strip().lower()

    if clean_action == "cancel":
        if sub_prof is None:
            sub_prof = TenantSubscriptionRecord(
                org_id=org_id,
                internal_sku=org.tier or "company_os_starter",
                base_price={"inr": 0, "usd": 0},
                currency=currency,
                status="cancelled",
                cancel_at_period_end=cancel_at_period_end,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )
            db.add(sub_prof)
        sub_prof.cancel_at_period_end = bool(cancel_at_period_end)
        sub_prof.renewal_policy = "cancel_at_period_end" if cancel_at_period_end else "cancelled_immediately"
        if not cancel_at_period_end:
            sub_prof.status = "cancelled"
            org.tier = "free"
            org_meta = dict(org.metadata_json or {})
            org_meta["package_key"] = "free"
            org_meta["entitled_capabilities"] = []
            org_meta["entitled_agents"] = []
            org.metadata_json = org_meta
            flag_modified(org, "metadata_json")
        else:
            sub_prof.status = "cancelling"
        sub_prof.updated_at = now
        db.add(
            AuditLog(
                task_id=str(uuid.uuid4()),
                correlation_id=str(uuid.uuid4()),
                agent_id=actor,
                capability_name="subscription_billing",
                action="subscription_cancelled",
                input_payload={"org_id": org_id, "cancel_at_period_end": cancel_at_period_end},
                output_payload={"status": sub_prof.status},
                status="COMPLETED",
            )
        )
        db.commit()
        return {"status": sub_prof.status, "org_id": org_id, "subscription": serialize_tenant_subscription(sub_prof)}

    if clean_action == "renew" and sub_prof is not None:
        sub_prof.status = "active"
        sub_prof.cancel_at_period_end = False
        sub_prof.renewal_policy = "auto_renew"
        sub_prof.current_period_start = now
        days = 365 if sub_prof.billing_interval == "annual" else 30
        sub_prof.current_period_end = now + timedelta(days=days)
        sub_prof.updated_at = now
        org.lead_credits_used = 0
        org.outreach_credits_used = 0
        db.add(
            CreditLedgerRecord(
                org_id=org_id,
                execution_id=None,
                idempotency_key=f"renew:{org_id}:{uuid.uuid4().hex[:12]}",
                entry_type="GRANT",
                credit_pool="lead_credits",
                delta=sub_prof.included_credits,
                balance_after=org.lead_credits_limit,
                status="COMMITTED",
                reason="Subscription renewal cycle credit reset",
                created_by=actor,
            )
        )
        db.commit()
        return {"status": "renewed", "org_id": org_id, "subscription": serialize_tenant_subscription(sub_prof)}

    if clean_action == "purchase_credits":
        packs = max(1, int(credit_packs))
        added_credits = packs * CREDIT_PACK_UNIT["credits"]
        org.lead_credits_limit = int(org.lead_credits_limit or 0) + added_credits
        org.outreach_credits_limit = int(org.outreach_credits_limit or 0) + round(added_credits * 0.5)
        if sub_prof is not None:
            sub_prof.credit_packs_purchased += packs
            sub_prof.included_credits += added_credits
            sub_prof.updated_at = now
        new_bal = org.lead_credits_limit - int(org.lead_credits_used or 0)
        db.add(
            CreditLedgerRecord(
                org_id=org_id,
                execution_id=None,
                idempotency_key=f"topup:{org_id}:{uuid.uuid4().hex[:12]}",
                entry_type="TOPUP",
                credit_pool="lead_credits",
                delta=added_credits,
                balance_after=new_bal,
                status="COMMITTED",
                reason=f"Purchased {packs} credit pack(s) (+{added_credits} credits)",
                created_by=actor,
            )
        )
        db.commit()
        return {
            "status": "CREDITS_ADDED",
            "org_id": org_id,
            "credits_added": added_credits,
            "lead_credits_limit": org.lead_credits_limit,
            "available_credits": new_bal,
        }

    composed = compose_modular_pricing(
        base_plan_key=base_plan_key,
        selected_modules=selected_modules,
        billing_type=billing_type,
        billing_interval=billing_interval,
        currency=currency,
        extra_agents=extra_agents,
        extra_seats=extra_seats,
        credit_packs=credit_packs,
        integration_addons=integration_addons,
        customization_level=customization_level,
    )

    period_days = 365 if composed["billing_interval"] == "annual" else 30
    if sub_prof is None:
        sub_prof = TenantSubscriptionRecord(
            org_id=org_id,
            internal_sku=composed["internal_sku"],
            created_at=now,
        )
        db.add(sub_prof)

    sub_prof.internal_sku = composed["internal_sku"]
    sub_prof.billing_type = composed["billing_type"]
    sub_prof.billing_interval = composed["billing_interval"]
    sub_prof.base_price = composed["base_price"]
    sub_prof.currency = composed["currency"]
    sub_prof.provider_plan_id = str(composed["provider_plan_id"].get("razorpay", ""))
    sub_prof.included_modules = composed["included_modules"]
    sub_prof.selected_modules = composed["selected_modules"]
    sub_prof.entitled_agents = composed["entitled_agents"]
    sub_prof.agent_execution_limit = composed["agent_execution_limit"]
    sub_prof.included_credits = composed["included_credits"]
    sub_prof.credit_costs = composed["credit_costs"]
    sub_prof.seat_limit = composed["seat_limit"]
    sub_prof.setup_fee = composed["setup_fee"]
    sub_prof.support_level = composed["support_level"]
    sub_prof.customization_allowance = composed["customization_allowance"]
    sub_prof.renewal_policy = composed["renewal_policy"]
    sub_prof.extra_agents = composed["extra_agents"]
    sub_prof.extra_seats = composed["extra_seats"]
    sub_prof.credit_packs_purchased = composed["credit_packs_purchased"]
    sub_prof.integration_addons = composed["integration_addons"]
    sub_prof.total_recurring_price = composed["total_recurring_price"]
    sub_prof.total_setup_price = composed["total_setup_price"]
    sub_prof.status = "active"
    sub_prof.cancel_at_period_end = False
    sub_prof.current_period_start = now
    sub_prof.current_period_end = now + timedelta(days=period_days)
    sub_prof.updated_at = now
    sub_prof.metadata_json = {"action": clean_action, "monthly_mrr_inr": composed["monthly_equivalent_price"]}

    org.tier = composed["internal_sku"]
    org.is_active = True
    org.lead_credits_limit = max(int(org.lead_credits_limit or 0), composed["lead_credits_limit"]) if clean_action == "upgrade" else composed["lead_credits_limit"]
    org.outreach_credits_limit = max(int(org.outreach_credits_limit or 0), composed["outreach_credits_limit"]) if clean_action == "upgrade" else composed["outreach_credits_limit"]

    org_meta = dict(org.metadata_json or {})
    org_meta["package_key"] = composed["internal_sku"]
    org_meta["internal_sku"] = composed["internal_sku"]
    org_meta["selected_modules"] = composed["selected_modules"]
    org_meta["entitled_capabilities"] = composed["entitled_capabilities"]
    org_meta["entitled_agents"] = composed["entitled_agents"]
    org_meta["seat_limit"] = composed["seat_limit"]
    org_meta["billing_interval"] = composed["billing_interval"]
    org.metadata_json = org_meta
    flag_modified(org, "metadata_json")

    db.add(
        CreditLedgerRecord(
            org_id=org_id,
            execution_id=None,
            idempotency_key=f"sub:{clean_action}:{org_id}:{uuid.uuid4().hex[:12]}",
            entry_type="GRANT",
            credit_pool="lead_credits",
            delta=org.lead_credits_limit,
            balance_after=max(0, org.lead_credits_limit - int(org.lead_credits_used or 0)),
            status="COMMITTED",
            reason=f"Subscription {clean_action}: {composed['internal_sku']}",
            created_by=actor,
        )
    )
    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id=actor,
            capability_name="subscription_billing",
            action=f"subscription_{clean_action}",
            input_payload={"org_id": org_id, "base_plan": base_plan_key, "modules": selected_modules},
            output_payload={"internal_sku": composed["internal_sku"], "total_due_now": composed["total_due_now"]},
            status="COMPLETED",
        )
    )
    db.commit()
    return {
        "status": "CONFIGURED",
        "action": clean_action,
        "org_id": org_id,
        "pricing": composed,
        "subscription": serialize_tenant_subscription(sub_prof),
    }


def serialize_tenant_subscription(rec: TenantSubscriptionRecord) -> dict[str, Any]:
    """Serialize all 15+ fields of a persisted TenantSubscriptionRecord."""
    return {
        "id": rec.id,
        "org_id": rec.org_id,
        "internal_sku": rec.internal_sku,
        "billing_type": rec.billing_type,
        "billing_interval": rec.billing_interval,
        "base_price": rec.base_price,
        "currency": rec.currency,
        "provider_plan_id": rec.provider_plan_id,
        "included_modules": rec.included_modules,
        "selected_modules": rec.selected_modules,
        "entitled_agents": rec.entitled_agents,
        "agent_execution_limit": rec.agent_execution_limit,
        "included_credits": rec.included_credits,
        "credit_costs": rec.credit_costs,
        "seat_limit": rec.seat_limit,
        "setup_fee": rec.setup_fee,
        "support_level": rec.support_level,
        "customization_allowance": rec.customization_allowance,
        "renewal_policy": rec.renewal_policy,
        "extra_agents": rec.extra_agents,
        "extra_seats": rec.extra_seats,
        "credit_packs_purchased": rec.credit_packs_purchased,
        "integration_addons": rec.integration_addons,
        "total_recurring_price": rec.total_recurring_price,
        "total_setup_price": rec.total_setup_price,
        "status": rec.status,
        "cancel_at_period_end": rec.cancel_at_period_end,
        "current_period_start": rec.current_period_start.isoformat() if rec.current_period_start else None,
        "current_period_end": rec.current_period_end.isoformat() if rec.current_period_end else None,
        "version": rec.version,
    }


def reserve_execution_credits(
    db: Session,
    *,
    org_id: str,
    cost: int,
    idempotency_key: str,
    execution_id: str,
    actor: str = "system",
    reason: str = "Agent execution reservation",
) -> dict[str, Any]:
    """Atomically and idempotently reserve execution credits (never double-debits or goes negative)."""
    clean_cost = max(0, int(cost))
    existing = db.query(CreditLedgerRecord).filter_by(idempotency_key=idempotency_key).first()
    if existing:
        return {
            "idempotent_replay": True,
            "entry_id": existing.id,
            "delta": existing.delta,
            "balance_after": existing.balance_after,
            "status": existing.status,
        }

    org = db.get(OrganizationRecord, org_id)
    if not org or not org.is_active:
        raise InsufficientCreditsError(f"Organization '{org_id}' is missing or inactive")

    if clean_cost > 0:
        stmt = (
            update(OrganizationRecord)
            .where(
                and_(
                    OrganizationRecord.id == org_id,
                    OrganizationRecord.is_active.is_(True),
                    (OrganizationRecord.lead_credits_limit - OrganizationRecord.lead_credits_used) >= clean_cost,
                )
            )
            .values(lead_credits_used=OrganizationRecord.lead_credits_used + clean_cost)
        )
        res = db.execute(stmt)
        if res.rowcount != 1:
            remaining = max(0, int(org.lead_credits_limit or 0) - int(org.lead_credits_used or 0))
            raise InsufficientCreditsError(
                f"Insufficient credits for organization '{org_id}': required={clean_cost}, remaining={remaining}"
            )
        db.expire(org, ["lead_credits_used"])
        org = db.get(OrganizationRecord, org_id)

    balance_after = max(0, int(org.lead_credits_limit or 0) - int(org.lead_credits_used or 0))
    entry = CreditLedgerRecord(
        org_id=org_id,
        execution_id=execution_id,
        idempotency_key=idempotency_key,
        entry_type="RESERVE",
        credit_pool="lead_credits",
        delta=-clean_cost,
        balance_after=balance_after,
        status="RESERVED",
        reason=reason,
        created_by=actor,
    )
    db.add(entry)
    db.flush()
    return {
        "idempotent_replay": False,
        "entry_id": entry.id,
        "delta": -clean_cost,
        "balance_after": balance_after,
        "status": "RESERVED",
    }


def commit_credit_reservation(db: Session, *, idempotency_key: str) -> None:
    """Finalize a credit reservation once execution succeeds."""
    entry = db.query(CreditLedgerRecord).filter_by(idempotency_key=idempotency_key).first()
    if entry and entry.status == "RESERVED":
        entry.status = "COMMITTED"
        entry.entry_type = "DEBIT"
        db.flush()


def refund_credit_reservation(
    db: Session,
    *,
    org_id: str,
    cost: int,
    idempotency_key: str,
    execution_id: str,
    actor: str = "system",
    reason: str = "Refund for failed or blocked execution",
) -> dict[str, Any]:
    """Idempotently refund reserved credits on execution failure/block so failed runs consume zero credits."""
    clean_cost = max(0, int(cost))
    refund_key = f"refund:{idempotency_key}"
    existing_refund = db.query(CreditLedgerRecord).filter_by(idempotency_key=refund_key).first()
    if existing_refund:
        return {"already_refunded": True, "balance_after": existing_refund.balance_after}

    orig = db.query(CreditLedgerRecord).filter_by(idempotency_key=idempotency_key).first()
    if orig is None or clean_cost == 0:
        org = db.get(OrganizationRecord, org_id)
        bal = max(0, int(org.lead_credits_limit or 0) - int(org.lead_credits_used or 0)) if org else 0
        return {"already_refunded": False, "balance_after": bal}

    if orig.status == "REVERSED":
        return {"already_refunded": True, "balance_after": orig.balance_after}

    stmt = (
        update(OrganizationRecord)
        .where(OrganizationRecord.id == org_id)
        .values(
            lead_credits_used=case(
                (OrganizationRecord.lead_credits_used >= clean_cost, OrganizationRecord.lead_credits_used - clean_cost),
                else_=0,
            )
        )
    )
    db.execute(stmt)
    orig.status = "REVERSED"
    org = db.get(OrganizationRecord, org_id)
    if org:
        db.expire(org, ["lead_credits_used"])
        org = db.get(OrganizationRecord, org_id)
    balance_after = max(0, int(org.lead_credits_limit or 0) - int(org.lead_credits_used or 0)) if org else 0

    db.add(
        CreditLedgerRecord(
            org_id=org_id,
            execution_id=execution_id,
            idempotency_key=refund_key,
            entry_type="REFUND",
            credit_pool="lead_credits",
            delta=clean_cost,
            balance_after=balance_after,
            status="COMMITTED",
            reason=reason,
            created_by=actor,
        )
    )
    db.flush()
    return {"already_refunded": False, "balance_after": balance_after}


# ── Dedicated Managed AI Usage-Credit Pool (Separate from Lead/Outreach Credits) ──


def get_ai_credit_cost(action_key: str) -> int:
    """Return transparent Managed AI Credit cost for an action/service."""
    return int(AI_CREDIT_COSTS.get((action_key or "").strip().lower(), AI_CREDIT_COSTS["default"]))


def get_ai_credit_summary(db: Session, org_id: str) -> dict[str, Any]:
    """Return current Managed AI Usage-Credit balance, spend cap, billing mode, and recent ledger."""
    org = db.get(OrganizationRecord, org_id)
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")
    limit = int(getattr(org, "ai_credits_limit", 150) or 0)
    used = int(getattr(org, "ai_credits_used", 0) or 0)
    remaining = max(0, limit - used)
    pct_used = round((used / limit) * 100.0, 1) if limit > 0 else 100.0
    entries = (
        db.query(CreditLedgerRecord)
        .filter(
            CreditLedgerRecord.org_id == org_id,
            CreditLedgerRecord.credit_pool == "ai_credits",
        )
        .order_by(CreditLedgerRecord.created_at.desc())
        .limit(25)
        .all()
    )
    return {
        "org_id": org.id,
        "tier": org.tier,
        "ai_billing_mode": str(getattr(org, "ai_billing_mode", "MANAGED_CREDITS") or "MANAGED_CREDITS"),
        "ai_credits_limit": limit,
        "ai_credits_used": used,
        "ai_credits_remaining": remaining,
        "utilization_pct": pct_used,
        "low_balance_warning": pct_used >= 80.0 or remaining <= 10,
        "ai_daily_spend_cap_inr": float(getattr(org, "ai_daily_spend_cap_inr", 100.0) or 0.0),
        "action_costs": dict(AI_CREDIT_COSTS),
        "topup_packs": {
            k: {**v, "checkout_url": f"/v1/pay/checkout?package={k}"}
            for k, v in AI_CREDIT_TOPUP_PACKS.items()
        },
        "recent_ledger": [
            {
                "id": e.id,
                "entry_type": e.entry_type,
                "delta": e.delta,
                "balance_after": e.balance_after,
                "status": e.status,
                "reason": e.reason,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
    }


def reserve_ai_credits(
    db: Session,
    *,
    org_id: str,
    cost: int,
    idempotency_key: str,
    execution_id: str,
    actor: str = "system",
    reason: str = "Managed AI execution",
    byok_supplied: bool = False,
) -> dict[str, Any]:
    """Atomically reserve Managed AI Credits with daily COGS spend circuit breaker (0 deduction when BYOK)."""
    existing = db.query(CreditLedgerRecord).filter_by(idempotency_key=idempotency_key).first()
    if existing:
        return {
            "idempotent_replay": True,
            "entry_id": existing.id,
            "delta": existing.delta,
            "balance_after": existing.balance_after,
            "status": existing.status,
            "byok_zero_credit": existing.delta == 0,
        }

    org = db.get(OrganizationRecord, org_id)
    if not org or not org.is_active:
        raise InsufficientAICreditsError(f"Organization '{org_id}' is missing or inactive")

    if byok_supplied:
        rem = max(0, int(getattr(org, "ai_credits_limit", 0) or 0) - int(getattr(org, "ai_credits_used", 0) or 0))
        entry = CreditLedgerRecord(
            org_id=org_id,
            execution_id=execution_id,
            idempotency_key=idempotency_key,
            entry_type="BYOK_ZERO_DEBIT",
            credit_pool="ai_credits",
            delta=0,
            balance_after=rem,
            status="COMMITTED",
            reason=f"{reason} (BYOK key supplied — 0 managed AI credits deducted)",
            created_by=actor,
        )
        db.add(entry)
        db.flush()
        return {
            "idempotent_replay": False,
            "entry_id": entry.id,
            "delta": 0,
            "balance_after": rem,
            "status": "COMMITTED",
            "byok_zero_credit": True,
        }

    # Check per-tenant hard daily platform API spend circuit breaker
    from sqlalchemy import func
    from app.db.models import ExecutionEvidenceRecord

    daily_cap = float(getattr(org, "ai_daily_spend_cap_inr", 100.0) or 0.0)
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today_spend = float(
        db.query(func.coalesce(func.sum(ExecutionEvidenceRecord.provider_cost_inr), 0.0))
        .filter(
            ExecutionEvidenceRecord.tenant_id == org_id,
            ExecutionEvidenceRecord.started_at >= today_start,
        )
        .scalar()
        or 0.0
    )
    if daily_cap > 0 and today_spend >= daily_cap:
        raise DailySpendCapExceededError(
            f"Daily managed AI spend safety cap reached (₹{today_spend:.2f} / ₹{daily_cap:.2f}). "
            "Supply a BYOK X-Gemini-API-Key or wait for daily reset."
        )

    clean_cost = max(1, int(cost))
    stmt = (
        update(OrganizationRecord)
        .where(
            and_(
                OrganizationRecord.id == org_id,
                OrganizationRecord.is_active.is_(True),
                (OrganizationRecord.ai_credits_limit - OrganizationRecord.ai_credits_used) >= clean_cost,
            )
        )
        .values(ai_credits_used=OrganizationRecord.ai_credits_used + clean_cost)
    )
    res = db.execute(stmt)
    if res.rowcount != 1:
        remaining = max(0, int(org.ai_credits_limit or 0) - int(org.ai_credits_used or 0))
        raise InsufficientAICreditsError(
            f"Insufficient Managed AI Credits: required={clean_cost}, remaining={remaining}. "
            "Top up via /v1/pay/checkout?package=ai_credits_100 or provide your own X-Gemini-API-Key."
        )
    db.expire(org, ["ai_credits_used"])
    org = db.get(OrganizationRecord, org_id)
    balance_after = max(0, int(org.ai_credits_limit or 0) - int(org.ai_credits_used or 0))

    entry = CreditLedgerRecord(
        org_id=org_id,
        execution_id=execution_id,
        idempotency_key=idempotency_key,
        entry_type="RESERVE",
        credit_pool="ai_credits",
        delta=-clean_cost,
        balance_after=balance_after,
        status="RESERVED",
        reason=reason,
        created_by=actor,
    )
    db.add(entry)
    db.flush()
    return {
        "idempotent_replay": False,
        "entry_id": entry.id,
        "delta": -clean_cost,
        "balance_after": balance_after,
        "status": "RESERVED",
        "byok_zero_credit": False,
    }


def commit_ai_credit_reservation(db: Session, *, idempotency_key: str) -> None:
    """Finalize a reserved Managed AI Credit entry after live execution succeeds."""
    entry = db.query(CreditLedgerRecord).filter_by(idempotency_key=idempotency_key).first()
    if entry and entry.status == "RESERVED":
        entry.status = "COMMITTED"
        entry.entry_type = "DEBIT"
        db.flush()


def refund_ai_credit_reservation(
    db: Session,
    *,
    org_id: str,
    cost: int,
    idempotency_key: str,
    execution_id: str,
    actor: str = "system",
    reason: str = "Automatic refund for failed live AI execution",
) -> dict[str, Any]:
    """Idempotently refund reserved Managed AI Credits so failed provider calls cost 0 credits."""
    clean_cost = max(0, int(cost))
    refund_key = f"refund:{idempotency_key}"
    existing_refund = db.query(CreditLedgerRecord).filter_by(idempotency_key=refund_key).first()
    if existing_refund:
        return {"already_refunded": True, "balance_after": existing_refund.balance_after}

    orig = db.query(CreditLedgerRecord).filter_by(idempotency_key=idempotency_key).first()
    if orig is None or clean_cost == 0 or orig.status == "REVERSED" or orig.delta == 0:
        org = db.get(OrganizationRecord, org_id)
        bal = max(0, int(org.ai_credits_limit or 0) - int(org.ai_credits_used or 0)) if org else 0
        return {"already_refunded": orig is not None and orig.status == "REVERSED", "balance_after": bal}

    stmt = (
        update(OrganizationRecord)
        .where(OrganizationRecord.id == org_id)
        .values(
            ai_credits_used=case(
                (OrganizationRecord.ai_credits_used >= clean_cost, OrganizationRecord.ai_credits_used - clean_cost),
                else_=0,
            )
        )
    )
    db.execute(stmt)
    orig.status = "REVERSED"
    org = db.get(OrganizationRecord, org_id)
    if org:
        db.expire(org, ["ai_credits_used"])
        org = db.get(OrganizationRecord, org_id)
    balance_after = max(0, int(org.ai_credits_limit or 0) - int(org.ai_credits_used or 0)) if org else 0

    db.add(
        CreditLedgerRecord(
            org_id=org_id,
            execution_id=execution_id,
            idempotency_key=refund_key,
            entry_type="REFUND",
            credit_pool="ai_credits",
            delta=clean_cost,
            balance_after=balance_after,
            status="COMMITTED",
            reason=reason,
            created_by=actor,
        )
    )
    db.flush()
    return {"already_refunded": False, "balance_after": balance_after}


def grant_ai_credit_topup(
    db: Session,
    *,
    org_id: str,
    pack_key: str,
    actor: str = "system",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Atomically credit a prepaid AI Credit Top-Up Pack (100 / 500 / 2,000 credits) to an organization."""
    spec = AI_CREDIT_TOPUP_PACKS.get((pack_key or "").strip().lower())
    if not spec:
        raise ValueError(f"Unknown AI credit top-up pack '{pack_key}'. Valid: {', '.join(AI_CREDIT_TOPUP_PACKS)}")
    idem = (idempotency_key or f"ai-topup:{org_id}:{pack_key}:{uuid.uuid4().hex[:10]}").strip()
    existing = db.query(CreditLedgerRecord).filter_by(idempotency_key=idem).first()
    if existing:
        return {"idempotent_replay": True, "credits_added": existing.delta, "balance_after": existing.balance_after}

    org = db.get(OrganizationRecord, org_id)
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")
    added = int(spec["credits"])
    org.ai_credits_limit = int(org.ai_credits_limit or 0) + added
    new_bal = max(0, org.ai_credits_limit - int(org.ai_credits_used or 0))
    db.add(
        CreditLedgerRecord(
            org_id=org_id,
            execution_id=None,
            idempotency_key=idem,
            entry_type="TOPUP",
            credit_pool="ai_credits",
            delta=added,
            balance_after=new_bal,
            status="COMMITTED",
            reason=f"Purchased Managed AI Credit Pack '{pack_key}' (+{added} credits, ₹{spec['INR']} / ${spec['USD']})",
            created_by=actor,
        )
    )
    db.commit()
    return {
        "idempotent_replay": False,
        "pack_key": pack_key,
        "credits_added": added,
        "ai_credits_limit": org.ai_credits_limit,
        "ai_credits_remaining": new_bal,
    }
