"""SME 13-Field Business Onboarding Profile, Structured Requirements, & Explainable Recommendations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import BusinessProfileRecord, OrganizationRecord, StructuredRequirementRecord
from app.services.billing_ledger import apply_subscription_configuration, compose_modular_pricing
from app.services.catalog import get_modular_pricing_contract
from app.services.registry import AGENT_REGISTRY, SERVICE_REGISTRY

AUTOMATION_TO_RECOMMENDATION: dict[str, dict[str, Any]] = {
    "lead_generation": {
        "module": "lead_discovery",
        "service": "lead_discovery",
        "agent": "discovery_sdr_agent",
        "connectors": ["serper_search", "google_places"],
        "credits": 40,
        "why": "Automated B2B prospect discovery and qualification matches your lead-generation objective.",
        "limitations": "Live web discovery requires Serper/Places probes; runs in SIMULATION until connectors are verified.",
    },
    "sales": {
        "module": "sales_proposals",
        "service": "sales_capture",
        "agent": "sales_proposal_agent",
        "connectors": ["hostinger_smtp", "razorpay", "afw_directpay"],
        "credits": 30,
        "why": "Structured proposal generation and payment-link capture automate quote-to-cash velocity.",
        "limitations": "External outreach emails always require Human-in-the-Loop (HITL) approval before SMTP send.",
    },
    "seo": {
        "module": "seo_content",
        "service": "seo_blog_copilot",
        "agent": "seo_content_agent",
        "connectors": ["gemini_api", "wordpress_rest"],
        "credits": 25,
        "why": "SEO/GEO content automation improves organic visibility across Search and AI assistants.",
        "limitations": "WordPress auto-publish requires verified REST App Password; otherwise drafts stage locally.",
    },
    "marketing": {
        "module": "marketing_campaigns",
        "service": "marketing_suite",
        "agent": "marketing_creative_agent",
        "connectors": ["social_media_bridge", "gemini_api"],
        "credits": 25,
        "why": "Omnichannel creative packs and social calendars accelerate campaign launches.",
        "limitations": "Automated social publishing is HUMAN_ASSISTED unless verified OAuth tokens are attached.",
    },
    "support": {
        "module": "customer_support",
        "service": "support_followup",
        "agent": "support_followup_agent",
        "connectors": ["whatsapp_bridge", "hostinger_smtp"],
        "credits": 20,
        "why": "Ticket triage and SLA follow-up drafting keep customer response times consistently low.",
        "limitations": "WhatsApp Cloud API delivery requires verified Meta Business credentials.",
    },
    "inventory": {
        "module": "inventory_quality",
        "service": "warehouse_automation",
        "agent": "warehouse_stocksense_agent",
        "connectors": ["project_api"],
        "credits": 20,
        "why": "StockSense ABC Pareto & EOQ mathematics optimize warehouse capital and prevent stockouts.",
        "limitations": "Local mathematical engine; external ERP sync requires custom API integration.",
    },
    "field_ops": {
        "module": "field_operations",
        "service": "field_force",
        "agent": "field_ops_agent",
        "connectors": ["project_api", "whatsapp_bridge"],
        "credits": 20,
        "why": "Zero-trust GPS geofence attendance and visit routing verify field team productivity.",
        "limitations": "Requires employee mobile GPS check-in events.",
    },
    "research": {
        "module": "research_intelligence",
        "service": "evidence_research",
        "agent": "research_analyst_agent",
        "connectors": ["serper_search", "gemini_api"],
        "credits": 15,
        "why": "Evidence-grounded market and competitor synthesis reduces strategy research hours.",
        "limitations": "External live citations use Serper/Web probes; offline runs stay labeled deterministic/simulated.",
    },
    "governance": {
        "module": "governance_trust",
        "service": "trust_engine",
        "agent": "trust_governance_agent",
        "connectors": ["project_api"],
        "credits": 10,
        "why": "ECDSA P-256 Merkle sealing provides tamper-evident audit trails for every workflow run.",
        "limitations": "None for local ledger sealing.",
    },
}


def _normalize_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    if isinstance(value, list):
        return [str(s).strip() for s in value if str(s).strip()]
    return [str(value).strip()]


def _infer_requirements(profile_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert raw 13-field SME profile text/lists into structured module, agent, and connector recommendations."""
    combined_text = " ".join(
        [
            str(profile_data.get("industry", "")),
            str(profile_data.get("description", "")),
            " ".join(_normalize_list(profile_data.get("operational_pain_points"))),
            " ".join(_normalize_list(profile_data.get("business_objectives"))),
            " ".join(_normalize_list(profile_data.get("required_automations"))),
            " ".join(_normalize_list(profile_data.get("sales_channels"))),
        ]
    ).lower()

    matched_keys: list[str] = []
    keyword_map = {
        "lead_generation": ("lead", "prospect", "b2b", "pipeline", "outreach"),
        "sales": ("sales", "proposal", "quote", "revenue", "closer", "crm", "follow-up", "followup"),
        "seo": ("seo", "blog", "content", "wordpress", "organic", "search", "website"),
        "marketing": ("marketing", "social", "ad", "creative", "campaign", "brand"),
        "support": ("support", "ticket", "customer care", "whatsapp", "inquiry", "helpdesk"),
        "inventory": ("warehouse", "inventory", "stock", "eoq", "supply", "produce", "mango", "bike", "fleet"),
        "field_ops": ("field", "gps", "delivery", "visit", "attendance", "route"),
        "research": ("research", "competitor", "academic", "citation", "report"),
        "governance": ("audit", "compliance", "approval", "hitl", "trust", "governance"),
    }
    for req_key, words in keyword_map.items():
        if any(w in combined_text for w in words):
            matched_keys.append(req_key)

    if not matched_keys:
        matched_keys = ["lead_generation", "sales", "seo"]
    if "governance" not in matched_keys:
        matched_keys.append("governance")

    reqs: list[dict[str, Any]] = []
    for idx, key in enumerate(matched_keys):
        spec = AUTOMATION_TO_RECOMMENDATION[key]
        reqs.append(
            {
                "category": spec["module"],
                "title": SERVICE_REGISTRY[spec["service"]].service_name if spec["service"] in SERVICE_REGISTRY else spec["service"],
                "description": spec["why"],
                "priority": "HIGH" if idx < 3 else "MEDIUM",
                "recommended_modules": [spec["module"]],
                "recommended_agents": [spec["agent"]],
                "required_connectors": list(spec["connectors"]),
                "expected_monthly_credits": int(spec["credits"]),
                "limitations": [spec["limitations"]],
            }
        )
    return reqs


def save_profile_and_generate_recommendations(
    db: Session,
    *,
    org_id: str,
    actor: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist all 13 SME onboarding fields, extract structured requirements, and explain recommendations."""
    org = db.get(OrganizationRecord, org_id)
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")

    now = datetime.now(UTC)
    emp_count = int(payload.get("employee_count") or 10)
    company_size = str(payload.get("company_size") or ("medium" if emp_count >= 50 else "small" if emp_count >= 10 else "micro"))
    pain_points = _normalize_list(payload.get("operational_pain_points") or payload.get("pain_points"))
    objectives = _normalize_list(payload.get("business_objectives") or payload.get("target_outcomes"))
    automations = _normalize_list(payload.get("required_automations") or payload.get("desired_services"))

    structured_payload = {
        "business_name": str(payload.get("business_name") or org.name),
        "industry": str(payload.get("industry") or "General Business"),
        "description": str(payload.get("description") or ""),
        "location": str(payload.get("location") or "India"),
        "website": payload.get("website"),
        "contact_info": payload.get("contact_info") if isinstance(payload.get("contact_info"), dict) else {"primary_contact": actor},
        "company_size": company_size,
        "employee_count": emp_count,
        "products_and_services": _normalize_list(payload.get("products_and_services")),
        "customer_segments": _normalize_list(payload.get("customer_segments")),
        "sales_channels": _normalize_list(payload.get("sales_channels")),
        "current_software": _normalize_list(payload.get("current_software")),
        "operational_pain_points": pain_points,
        "business_objectives": objectives,
        "required_automations": automations,
        "expected_monthly_volume": (
            payload.get("expected_monthly_volume")
            if isinstance(payload.get("expected_monthly_volume"), dict)
            else {"leads": 100, "articles": 12, "workflows": 50}
        ),
    }

    recs = _infer_requirements(structured_payload)
    rec_modules: list[str] = []
    rec_agents: list[str] = []
    rec_connectors: list[str] = []
    explanations: list[dict[str, Any]] = []
    all_limitations: list[str] = []
    expected_credits = 0

    for r in recs:
        for m in r["recommended_modules"]:
            if m not in rec_modules:
                rec_modules.append(m)
        for a in r["recommended_agents"]:
            if a not in rec_agents:
                rec_agents.append(a)
        for c in r["required_connectors"]:
            if c not in rec_connectors:
                rec_connectors.append(c)
        expected_credits += int(r["expected_monthly_credits"])
        all_limitations.extend(r["limitations"])
        explanations.append(
            {
                "module": r["category"],
                "title": r["title"],
                "reason": r["description"],
                "agents": r["recommended_agents"],
                "required_connectors": r["required_connectors"],
                "expected_monthly_credits": r["expected_monthly_credits"],
                "limitations": r["limitations"],
            }
        )

    base_tier = "enterprise" if emp_count >= 100 else "business_pro" if len(rec_modules) >= 5 else "growth" if len(rec_modules) >= 3 else "launch"
    pricing_preview = compose_modular_pricing(
        base_plan_key=base_tier,
        selected_modules=rec_modules,
        currency=str(payload.get("currency") or "INR"),
    )
    suggested_workflows = [
        {
            "workflow_key": "lead_to_proposal_hitl",
            "name": "Discover Prospect -> Research -> Draft Proposal -> HITL Approval",
            "agents": [a for a in ("discovery_sdr_agent", "research_analyst_agent", "sales_proposal_agent") if a in AGENT_REGISTRY],
            "estimated_credits": 3,
        },
        {
            "workflow_key": "seo_content_to_social",
            "name": "Keyword Research -> SEO Article -> Social Campaign Assets",
            "agents": ["seo_content_agent", "marketing_creative_agent"],
            "estimated_credits": 2,
        },
    ]

    recommended_plan = {
        "recommended_tier": base_tier,
        "canonical_sku": pricing_preview["internal_sku"],
        "contract": get_modular_pricing_contract(base_tier),
        "pricing_preview": pricing_preview,
        "recommended_modules": rec_modules,
        "recommended_agents": rec_agents,
        "recommended_workflows": suggested_workflows,
        "required_connectors": rec_connectors,
        "expected_monthly_credits": expected_credits,
        "explanations": explanations,
        "dependencies": {
            m: list(SERVICE_REGISTRY[s].required_connectors)
            for m in rec_modules
            for s in SERVICE_REGISTRY
            if SERVICE_REGISTRY[s].category == m
        },
        "limitations": list(dict.fromkeys(all_limitations)),
        "requires_explicit_confirmation": True,
    }

    profile = db.query(BusinessProfileRecord).filter_by(org_id=org_id).first()
    if profile is None:
        profile = BusinessProfileRecord(org_id=org_id, created_at=now, **structured_payload)
        db.add(profile)
    else:
        for k, v in structured_payload.items():
            setattr(profile, k, v)
        profile.updated_at = now

    # Reset selection_confirmed when profile changes materially until customer confirms
    profile.recommended_plan = recommended_plan
    profile.selection_confirmed = False
    profile.confirmed_at = None
    db.flush()

    # Replace previous extracted requirements cleanly
    db.query(StructuredRequirementRecord).filter_by(org_id=org_id).delete()
    created_reqs = []
    for r in recs:
        sr = StructuredRequirementRecord(
            org_id=org_id,
            profile_id=profile.id,
            category=r["category"],
            title=r["title"],
            description=r["description"],
            priority=r["priority"],
            recommended_modules=r["recommended_modules"],
            recommended_agents=r["recommended_agents"],
            required_connectors=r["required_connectors"],
            expected_monthly_credits=r["expected_monthly_credits"],
            limitations=r["limitations"],
            status="RECOMMENDED",
        )
        db.add(sr)
        db.flush()
        created_reqs.append(sr)

    # Maintain backward compatibility with P0 metadata field storage on OrganizationRecord
    meta = dict(org.metadata_json or {})
    meta["business_profile"] = {
        **structured_payload,
        "profile_id": profile.id,
        "updated_at": now.isoformat(),
    }
    org.metadata_json = meta
    db.commit()

    return {
        "status": "PROFILE_SAVED_PENDING_CONFIRMATION",
        "org_id": org_id,
        "profile": serialize_business_profile(profile),
        "structured_requirements": [
            {
                "requirement_id": r.id,
                "category": r.category,
                "title": r.title,
                "priority": r.priority,
                "recommended_modules": r.recommended_modules,
                "recommended_agents": r.recommended_agents,
                "required_connectors": r.required_connectors,
                "expected_monthly_credits": r.expected_monthly_credits,
                "limitations": r.limitations,
                "status": r.status,
            }
            for r in created_reqs
        ],
        "recommendation": recommended_plan,
        # P0 compatibility keys
        "business_profile": meta["business_profile"],
        "ai_recommendation": {
            "recommended_tier": base_tier,
            "recommended_modules": rec_modules,
            "estimated_monthly_inr": pricing_preview["monthly_equivalent_price"],
            "pricing_contract": recommended_plan["contract"],
            "why_recommended": explanations,
        },
    }


def serialize_business_profile(profile: BusinessProfileRecord) -> dict[str, Any]:
    """Return full 13-field SME profile dict."""
    return {
        "profile_id": profile.id,
        "org_id": profile.org_id,
        "business_name": profile.business_name,
        "industry": profile.industry,
        "description": profile.description,
        "location": profile.location,
        "website": profile.website,
        "contact_info": profile.contact_info,
        "company_size": profile.company_size,
        "employee_count": profile.employee_count,
        "products_and_services": profile.products_and_services,
        "customer_segments": profile.customer_segments,
        "sales_channels": profile.sales_channels,
        "current_software": profile.current_software,
        "operational_pain_points": profile.operational_pain_points,
        "business_objectives": profile.business_objectives,
        "required_automations": profile.required_automations,
        "expected_monthly_volume": profile.expected_monthly_volume,
        "selection_confirmed": profile.selection_confirmed,
        "confirmed_at": profile.confirmed_at.isoformat() if profile.confirmed_at else None,
        "version": profile.version,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def confirm_recommended_selection(
    db: Session,
    *,
    org_id: str,
    actor: str,
    selected_modules: list[str] | None = None,
    base_plan_key: str | None = None,
    billing_interval: str = "monthly",
    currency: str = "INR",
    activate_selection: bool = False,
) -> dict[str, Any]:
    """Record explicit customer confirmation of recommended modules/tier before activating or billing."""
    profile = db.query(BusinessProfileRecord).filter_by(org_id=org_id).first()
    if not profile:
        raise ValueError(f"Business profile for organization '{org_id}' not found")

    now = datetime.now(UTC)
    rec = profile.recommended_plan or {}
    chosen_tier = base_plan_key or rec.get("recommended_tier") or "growth"
    chosen_modules = selected_modules if selected_modules is not None else list(rec.get("recommended_modules") or ["seo_content"])

    profile.selection_confirmed = True
    profile.confirmed_at = now
    db.query(StructuredRequirementRecord).filter_by(org_id=org_id).update({"status": "CONFIRMED"})

    activation_result = None
    if activate_selection:
        activation_result = apply_subscription_configuration(
            db,
            org_id=org_id,
            actor=actor,
            action="configure",
            base_plan_key=chosen_tier,
            selected_modules=chosen_modules,
            billing_interval=billing_interval,
            currency=currency,
        )
        db.query(StructuredRequirementRecord).filter_by(org_id=org_id).update({"status": "ACTIVE"})

    db.commit()
    return {
        "status": "CONFIRMED_AND_ACTIVATED" if activate_selection else "CONFIRMED",
        "org_id": org_id,
        "confirmed_at": now.isoformat(),
        "selected_tier": chosen_tier,
        "selected_modules": chosen_modules,
        "subscription_activation": activation_result,
    }

