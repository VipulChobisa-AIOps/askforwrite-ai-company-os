"""P6 Multi-Industry SME Packs & India Local SEO Baseline engine.

Implements a configuration-driven Industry Configuration Engine binding five SME sector packs:
1. distribution_wholesale
2. logistics_warehousing
3. manufacturing
4. retail_commerce
5. professional_services

Every pack integrates real core analytics/workflow modules, derives pricing strictly from
MODULAR_SME_TIERS / CATALOG, and strictly classifies readiness as SANDBOX or ROADMAP unless
verified live commercial customer telemetry exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    OrganizationRecord,
    P6IndustryPackRecord,
    P6SeoBaselineRecord,
    P6TenantPackDeploymentRecord,
)
from app.security.trust_chain import seal_task_to_block
from app.services.billing_ledger import compose_modular_pricing
from app.services.catalog import CATALOG, MODULAR_SERVICE_MODULES, MODULAR_SME_TIERS
from app.services.execution_guard import is_external_side_effect_blocked, resolve_execution_mode
from app.services.inventory_analytics import compute_abc_analysis, compute_reorder_recommendations
from app.services.mobility_analytics import compute_station_rebalancing_plan
from app.services.p4_growth_gtm import check_gtm_copy_safety
from app.services.quality_analytics import execute_produce_quality_inspection
from app.services.registry import AGENT_REGISTRY

ALLOWED_READINESS_STATUSES: tuple[str, ...] = ("SANDBOX", "ROADMAP", "LIVE_VERIFIED")
ALLOWED_ANALYTICS_CAPABILITIES: tuple[str, ...] = (
    "warehouse_stocksense",
    "spatiotemporal_logistics_optimization",
    "computer_vision_quality_analytics",
    "india_local_seo_baseline",
    "gtm_pipeline_automation",
)

DEFAULT_P6_INDUSTRY_PACKS: tuple[dict[str, Any], ...] = (
    {
        "pack_key": "distribution_wholesale",
        "name": "Distribution & Wholesale SME Pack",
        "sector": "distribution_wholesale",
        "description": "Configuration-driven pack uniting StockSense ABC-XYZ inventory optimization, field dispatch, and billing ledger controls.",
        "tier_id": "operations",
        "selected_modules": ["inventory", "field_force", "customer_ops"],
        "catalog_service_ids": ["warehouse_automation", "field_force", "company_os_pro"],
        "agent_ids": ["warehouse_stocksense_agent", "field_ops_agent", "customer_success_agent"],
        "analytics_capabilities": ["warehouse_stocksense"],
        "kpi_definitions": ["inventory_turnover_ratio", "stockout_prevention_count", "dispatch_sla_pct"],
        "default_config": {"service_level_z": 1.65, "forecast_alpha": 0.3, "gst_invoice_mode": "INR_B2B"},
        "readiness_status": "SANDBOX",
        "verified_live_customers": 0,
    },
    {
        "pack_key": "logistics_warehousing",
        "name": "Logistics & Warehousing SME Pack",
        "sector": "logistics_warehousing",
        "description": "Combines spatiotemporal fleet/station rebalancing analytics, warehouse stock reorder, and SLA incident routing.",
        "tier_id": "operations",
        "selected_modules": ["inventory", "field_force", "customer_ops"],
        "catalog_service_ids": ["bike_rebalance_analytics", "warehouse_automation", "field_force"],
        "agent_ids": ["mobility_rebalance_agent", "warehouse_stocksense_agent", "field_ops_agent"],
        "analytics_capabilities": ["spatiotemporal_logistics_optimization", "warehouse_stocksense"],
        "kpi_definitions": ["rebalance_efficiency_score", "hub_utilization_pct", "on_time_dispatch_rate"],
        "default_config": {"rebalance_horizon_hours": 4, "default_hub_region": "Bengaluru_IN"},
        "readiness_status": "SANDBOX",
        "verified_live_customers": 0,
    },
    {
        "pack_key": "manufacturing",
        "name": "SME Manufacturing Quality & Supply Pack",
        "sector": "manufacturing",
        "description": "Integrates computer-vision surface/produce defect grading, raw-material reorder points, and trust evidence sealing.",
        "tier_id": "business_pro",
        "selected_modules": ["inventory", "field_force", "customer_ops"],
        "catalog_service_ids": ["mango_quality_analytics", "warehouse_automation", "trust_engine"],
        "agent_ids": ["quality_vision_agent", "warehouse_stocksense_agent", "trust_governance_agent"],
        "analytics_capabilities": ["computer_vision_quality_analytics", "warehouse_stocksense"],
        "kpi_definitions": ["lot_pass_rate", "defect_detection_precision", "safety_stock_coverage_days"],
        "default_config": {"quality_grade_threshold": 0.85, "sample_preset": "ripe"},
        "readiness_status": "SANDBOX",
        "verified_live_customers": 0,
    },
    {
        "pack_key": "retail_commerce",
        "name": "Retail & Omnichannel Commerce SME Pack",
        "sector": "retail_commerce",
        "description": "Omnichannel pack combining inventory replenishment, local SEO storefronts, and HITL-gated promotions.",
        "tier_id": "growth",
        "selected_modules": ["sales", "marketing", "seo", "inventory"],
        "catalog_service_ids": ["seo_blog_copilot", "marketing_suite", "warehouse_automation"],
        "agent_ids": ["seo_content_agent", "gtm_strategist_agent", "warehouse_stocksense_agent"],
        "analytics_capabilities": ["warehouse_stocksense", "india_local_seo_baseline", "gtm_pipeline_automation"],
        "kpi_definitions": ["sku_sell_through_rate", "local_seo_coverage", "campaign_approval_turnaround"],
        "default_config": {"currency": "INR", "requires_owner_hitl_publish": True},
        "readiness_status": "ROADMAP",
        "verified_live_customers": 0,
    },
    {
        "pack_key": "professional_services",
        "name": "Professional Services & Agency SME Pack",
        "sector": "professional_services",
        "description": "Built for agencies and consultancies: ICP scoring, WordPress GEO/AIO SEO baselines, proposal workflow, and CS onboarding.",
        "tier_id": "growth",
        "selected_modules": ["sales", "marketing", "seo", "customer_ops"],
        "catalog_service_ids": ["growth_all_in_one", "seo_blog_copilot", "managed_seo_content_pilot"],
        "agent_ids": ["gtm_strategist_agent", "seo_content_agent", "sales_proposal_agent", "customer_success_agent"],
        "analytics_capabilities": ["india_local_seo_baseline", "gtm_pipeline_automation"],
        "kpi_definitions": ["qualified_pipeline_count", "proposal_hitl_cycle_hours", "client_health_score"],
        "default_config": {"region": "IN", "target_clusters": ["Bengaluru", "Mumbai", "Delhi NCR"]},
        "readiness_status": "SANDBOX",
        "verified_live_customers": 0,
    },
)


def _normalize_mode(requested_mode: str | None) -> str:
    raw = (requested_mode or "SIMULATION").strip().upper()
    canonical = "PRODUCTION" if raw == "LIVE" else raw
    if canonical not in ("SIMULATION", "SANDBOX", "PRODUCTION"):
        raise ValueError(f"Unsupported execution_mode '{requested_mode}'")
    resolved = resolve_execution_mode(canonical)
    if resolved == "PRODUCTION" and is_external_side_effect_blocked():
        raise PermissionError("PRODUCTION deployment blocked while sandbox/test external side-effect guard is active")
    return resolved


def _serialize_pack(rec: P6IndustryPackRecord) -> dict[str, Any]:
    return {
        "pack_id": rec.id,
        "pack_key": rec.pack_key,
        "name": rec.name,
        "sector": rec.sector,
        "description": rec.description,
        "tier_id": rec.tier_id,
        "selected_modules": list(rec.selected_modules_json or []),
        "catalog_service_ids": list(rec.catalog_service_ids_json or []),
        "agent_ids": list(rec.agent_ids_json or []),
        "analytics_capabilities": list(rec.analytics_capabilities_json or []),
        "kpi_definitions": list(rec.kpi_definitions_json or []),
        "default_config": dict(rec.default_config_json or {}),
        "monthly_price_inr": int(rec.monthly_price_inr or 0),
        "readiness_status": rec.readiness_status,
        "verified_live_customers": int(rec.verified_live_customers or 0),
        "is_active": bool(rec.is_active),
        "created_by": rec.created_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def upsert_industry_pack(
    db: Session,
    *,
    pack_key: str,
    name: str,
    sector: str,
    description: str,
    tier_id: str,
    selected_modules: list[str],
    catalog_service_ids: list[str],
    agent_ids: list[str],
    analytics_capabilities: list[str],
    kpi_definitions: list[str] | None = None,
    default_config: dict[str, Any] | None = None,
    readiness_status: str = "SANDBOX",
    verified_live_customers: int = 0,
    is_active: bool = True,
    actor: str = "system",
) -> dict[str, Any]:
    """Create or update a configuration-driven SME pack bound strictly to CATALOG and verified readiness."""
    clean_key = pack_key.strip().lower()
    clean_tier = tier_id.strip().lower()
    clean_readiness = readiness_status.strip().upper()
    if clean_tier not in MODULAR_SME_TIERS:
        raise ValueError(f"Unknown tier_id '{tier_id}'; must exist in MODULAR_SME_TIERS")
    if clean_readiness not in ALLOWED_READINESS_STATUSES:
        raise ValueError(f"Unsupported readiness_status '{readiness_status}'; allowed: {ALLOWED_READINESS_STATUSES}")
    if clean_readiness == "LIVE_VERIFIED" and int(verified_live_customers) <= 0:
        raise ValueError("Cannot mark an industry pack LIVE_VERIFIED with zero verified_live_customers")

    clean_modules = list(dict.fromkeys(m.strip().lower() for m in selected_modules if str(m).strip()))
    bad_mods = [m for m in clean_modules if m not in MODULAR_SERVICE_MODULES]
    if bad_mods:
        raise ValueError(f"Unknown modules {bad_mods}; must exist in MODULAR_SERVICE_MODULES")

    clean_services = list(dict.fromkeys(s.strip() for s in catalog_service_ids if str(s).strip()))
    bad_svcs = [s for s in clean_services if s not in CATALOG]
    if bad_svcs:
        raise ValueError(f"Unknown catalog_service_ids {bad_svcs}; must exist in CATALOG")

    clean_agents = list(dict.fromkeys(a.strip() for a in agent_ids if str(a).strip()))
    bad_agents = [a for a in clean_agents if a not in AGENT_REGISTRY]
    if bad_agents:
        raise ValueError(f"Unknown agent_ids {bad_agents}; must exist in AGENT_REGISTRY")

    clean_caps = list(dict.fromkeys(c.strip() for c in analytics_capabilities if str(c).strip()))
    bad_caps = [c for c in clean_caps if c not in ALLOWED_ANALYTICS_CAPABILITIES]
    if bad_caps:
        raise ValueError(f"Unknown analytics_capabilities {bad_caps}; allowed: {ALLOWED_ANALYTICS_CAPABILITIES}")

    safety = check_gtm_copy_safety({"name": name, "description": description}, subject=name)
    if not safety["safe"]:
        raise ValueError(f"Pack metadata rejected by claim safety filter: {'; '.join(safety['issues'])}")

    quote = compose_modular_pricing(base_plan_key=clean_tier, selected_modules=clean_modules, currency="INR")
    monthly_price = int(quote["total_recurring_price"])
    now = datetime.now(UTC)

    existing = db.query(P6IndustryPackRecord).filter_by(pack_key=clean_key).first()
    if existing:
        existing.name = name.strip()
        existing.sector = sector.strip().lower()
        existing.description = description.strip()
        existing.tier_id = clean_tier
        existing.selected_modules_json = clean_modules
        existing.catalog_service_ids_json = clean_services
        existing.agent_ids_json = clean_agents
        existing.analytics_capabilities_json = clean_caps
        existing.kpi_definitions_json = list(kpi_definitions or [])
        existing.default_config_json = dict(default_config or {})
        existing.monthly_price_inr = monthly_price
        existing.readiness_status = clean_readiness
        existing.verified_live_customers = max(0, int(verified_live_customers))
        existing.is_active = bool(is_active)
        existing.updated_at = now
        db.commit()
        db.refresh(existing)
        return _serialize_pack(existing)

    rec = P6IndustryPackRecord(
        id=str(uuid.uuid4()),
        pack_key=clean_key,
        name=name.strip(),
        sector=sector.strip().lower(),
        description=description.strip(),
        tier_id=clean_tier,
        selected_modules_json=clean_modules,
        catalog_service_ids_json=clean_services,
        agent_ids_json=clean_agents,
        analytics_capabilities_json=clean_caps,
        kpi_definitions_json=list(kpi_definitions or []),
        default_config_json=dict(default_config or {}),
        monthly_price_inr=monthly_price,
        readiness_status=clean_readiness,
        verified_live_customers=max(0, int(verified_live_customers)),
        is_active=bool(is_active),
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_pack(rec)


def seed_default_p6_packs(db: Session, *, actor: str = "system") -> list[dict[str, Any]]:
    """Seed the 5 canonical SME vertical packs idempotently."""
    out: list[dict[str, Any]] = []
    for spec in DEFAULT_P6_INDUSTRY_PACKS:
        out.append(
            upsert_industry_pack(
                db,
                pack_key=spec["pack_key"],
                name=spec["name"],
                sector=spec["sector"],
                description=spec["description"],
                tier_id=spec["tier_id"],
                selected_modules=spec["selected_modules"],
                catalog_service_ids=spec["catalog_service_ids"],
                agent_ids=spec["agent_ids"],
                analytics_capabilities=spec["analytics_capabilities"],
                kpi_definitions=spec["kpi_definitions"],
                default_config=spec["default_config"],
                readiness_status=spec["readiness_status"],
                verified_live_customers=spec["verified_live_customers"],
                actor=actor,
            )
        )
    return out


def list_industry_packs(
    db: Session,
    *,
    sector: str | None = None,
    readiness_status: str | None = None,
) -> list[dict[str, Any]]:
    """List SME industry packs, auto-seeding canonical 5 packs on first query."""
    if db.query(P6IndustryPackRecord).count() == 0:
        seed_default_p6_packs(db)
    q = db.query(P6IndustryPackRecord).filter(P6IndustryPackRecord.is_active.is_(True))
    if sector:
        q = q.filter(P6IndustryPackRecord.sector == sector.strip().lower())
    if readiness_status:
        q = q.filter(P6IndustryPackRecord.readiness_status == readiness_status.strip().upper())
    return [_serialize_pack(r) for r in q.order_by(P6IndustryPackRecord.pack_key.asc()).all()]


def _serialize_deployment(rec: P6TenantPackDeploymentRecord) -> dict[str, Any]:
    return {
        "deployment_id": rec.id,
        "org_id": rec.org_id,
        "pack_key": rec.pack_key,
        "status": rec.status,
        "execution_mode": rec.execution_mode,
        "configuration": dict(rec.configuration_json or {}),
        "last_analytics_output": dict(rec.last_analytics_output_json or {}),
        "readiness_label": rec.readiness_label,
        "deployed_by": rec.deployed_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def deploy_industry_pack_for_tenant(
    db: Session,
    *,
    org_id: str,
    pack_key: str,
    configuration: dict[str, Any] | None = None,
    execution_mode: str = "SIMULATION",
    actor: str = "system",
) -> dict[str, Any]:
    """Deploy a configuration-driven industry pack into a tenant organization."""
    if db.query(P6IndustryPackRecord).count() == 0:
        seed_default_p6_packs(db, actor=actor)
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")
    pack = db.query(P6IndustryPackRecord).filter_by(pack_key=pack_key.strip().lower(), is_active=True).first()
    if not pack:
        raise ValueError(f"Industry pack '{pack_key}' not found")

    mode = _normalize_mode(execution_mode)
    merged_cfg = dict(pack.default_config_json or {})
    if configuration:
        merged_cfg.update(configuration)

    now = datetime.now(UTC)
    rec = P6TenantPackDeploymentRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        pack_key=pack.pack_key,
        status="CONFIGURED",
        execution_mode=mode,
        configuration_json=merged_cfg,
        last_analytics_output_json={},
        readiness_label=pack.readiness_status,
        deployed_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_deployment(rec)


def run_pack_diagnostics(
    db: Session,
    *,
    deployment_id: str,
    org_id: str | None,
    sample_inventory_items: list[dict[str, Any]] | None = None,
    hour_of_day: int = 9,
    quality_preset: str = "ripe",
    actor: str = "system",
) -> dict[str, Any]:
    """Run real vertical analytics engines configured for a deployed P6 industry pack."""
    dep = db.get(P6TenantPackDeploymentRecord, deployment_id)
    if not dep or (org_id is not None and dep.org_id != org_id):
        raise ValueError(f"Pack deployment '{deployment_id}' not found")
    pack = db.query(P6IndustryPackRecord).filter_by(pack_key=dep.pack_key).first()
    if not pack:
        raise ValueError(f"Industry pack '{dep.pack_key}' missing")

    caps = list(pack.analytics_capabilities_json or [])
    items = sample_inventory_items or [
        {"sku": "SKU-BLR-01", "name": "Fast Mover Component", "category": "industrial_fastener", "unit_cost": 450.0, "annual_demand": 2400, "daily_demand": 7.0, "lead_time_days": 5, "current_stock": 20},
        {"sku": "SKU-MUM-02", "name": "Standard Packaging Roll", "category": "packaging", "unit_cost": 120.0, "annual_demand": 800, "daily_demand": 2.5, "lead_time_days": 4, "current_stock": 60},
    ]

    results: dict[str, Any] = {
        "data_classification": "SANDBOX_SIMULATION",
        "pack_key": pack.pack_key,
        "readiness_status": pack.readiness_status,
        "modules_executed": [],
    }
    if "warehouse_stocksense" in caps:
        abc = compute_abc_analysis(items)
        reorder = compute_reorder_recommendations(
            items,
            service_level_z=float(dep.configuration_json.get("service_level_z", 1.65)),
            forecast_alpha=float(dep.configuration_json.get("forecast_alpha", 0.3)),
        )
        results["warehouse_stocksense"] = {"abc_summary": abc, "reorder_recommendations": reorder}
        results["modules_executed"].append("warehouse_stocksense")

    if "spatiotemporal_logistics_optimization" in caps:
        rebalance = compute_station_rebalancing_plan(hour_of_day=hour_of_day)
        results["spatiotemporal_logistics_optimization"] = rebalance
        results["modules_executed"].append("spatiotemporal_logistics_optimization")

    if "computer_vision_quality_analytics" in caps:
        preset = str(quality_preset or dep.configuration_json.get("sample_preset", "ripe"))
        vision = execute_produce_quality_inspection(
            db,
            preset_or_sample=preset,
            batch_lot_id=f"p6-{dep.id[:8]}",
            idempotency_key=f"p6-qual-{dep.id}",
            correlation_id=dep.id,
            agent_id="quality_vision_agent",
        )
        results["computer_vision_quality_analytics"] = vision
        results["modules_executed"].append("computer_vision_quality_analytics")

    if "india_local_seo_baseline" in caps or "gtm_pipeline_automation" in caps:
        results["gtm_and_seo_readiness"] = {
            "primary_catalog_services": list(pack.catalog_service_ids_json or []),
            "target_cluster": dep.configuration_json.get("default_hub_region", "Bengaluru_IN"),
            "hitl_publish_required": True,
        }
        results["modules_executed"].append("gtm_and_seo_readiness")

    dep.last_analytics_output_json = results
    dep.status = "SANDBOX_VALIDATED"
    dep.updated_at = datetime.now(UTC)
    seal_task_to_block(
        db=db,
        task_id=dep.id,
        capability_name="p6_industry_packs",
        action="run_pack_diagnostics",
        payload={"pack_key": dep.pack_key, "modules_executed": results["modules_executed"]},
        sealed_by=actor,
    )
    db.commit()
    db.refresh(dep)
    return _serialize_deployment(dep)


def list_pack_deployments(db: Session, *, org_id: str | None = None) -> list[dict[str, Any]]:
    """List tenant industry pack deployments."""
    q = db.query(P6TenantPackDeploymentRecord)
    if org_id is not None:
        q = q.filter(P6TenantPackDeploymentRecord.org_id == org_id)
    return [_serialize_deployment(r) for r in q.order_by(P6TenantPackDeploymentRecord.created_at.desc()).all()]


def _serialize_seo_baseline(rec: P6SeoBaselineRecord) -> dict[str, Any]:
    return {
        "baseline_id": rec.id,
        "org_id": rec.org_id,
        "region_code": rec.region_code,
        "city_or_cluster": rec.city_or_cluster,
        "industry_vertical": rec.industry_vertical,
        "primary_catalog_sku": rec.primary_catalog_sku,
        "target_keywords": list(rec.target_keywords_json or []),
        "localized_pages": list(rec.localized_pages_json or []),
        "schema_markup": dict(rec.schema_markup_json or {}),
        "baseline_status": rec.baseline_status,
        "approval_id": rec.approval_id,
        "created_by": rec.created_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def create_india_seo_baseline(
    db: Session,
    *,
    org_id: str | None,
    city_or_cluster: str,
    industry_vertical: str,
    primary_catalog_sku: str,
    target_keywords: list[str] | None = None,
    business_name: str = "AskforWrite Client SME",
    actor: str = "system",
) -> dict[str, Any]:
    """Generate a claim-checked India local SME SEO baseline grounded strictly in a real CATALOG SKU."""
    clean_sku = primary_catalog_sku.strip()
    if clean_sku not in CATALOG:
        raise ValueError(f"Unknown primary_catalog_sku '{primary_catalog_sku}'; must exist in CATALOG")
    pkg = CATALOG[clean_sku]
    clean_city = city_or_cluster.strip()
    clean_vertical = industry_vertical.strip().lower()

    keywords = [k.strip() for k in (target_keywords or []) if str(k).strip()]
    if not keywords:
        keywords = [
            f"ai workflow automation {clean_vertical} {clean_city.lower()}",
            f"{pkg.name.lower()} {clean_city.lower()} india",
        ]

    pages = [
        {
            "slug": f"/in/{clean_city.lower().replace(' ', '-')}/{clean_vertical}/{clean_sku}",
            "title": f"{pkg.name} for {clean_vertical.replace('_', ' ').title()} SMEs in {clean_city}",
            "meta_description": f"{pkg.description} Transparent starter pricing from INR {pkg.price_inr}/month (GST excluded).",
            "h1": f"{pkg.name} — {clean_city} SME Operations",
        }
    ]
    safety = check_gtm_copy_safety({"keywords": keywords, "pages": pages, "business_name": business_name}, subject="India SEO Baseline")
    if not safety["safe"]:
        raise ValueError(f"SEO baseline rejected by copy safety filter: {'; '.join(safety['issues'])}")

    schema_markup = {
        "@context": "https://schema.org",
        "@type": "Service",
        "name": pkg.name,
        "provider": {"@type": "Organization", "name": business_name.strip()},
        "areaServed": {"@type": "City", "name": clean_city, "addressCountry": "IN"},
        "offers": {"@type": "Offer", "priceCurrency": "INR", "price": int(pkg.price_inr)},
    }

    now = datetime.now(UTC)
    rec = P6SeoBaselineRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        region_code="IN",
        city_or_cluster=clean_city,
        industry_vertical=clean_vertical,
        primary_catalog_sku=clean_sku,
        target_keywords_json=keywords,
        localized_pages_json=pages,
        schema_markup_json=schema_markup,
        baseline_status="SANDBOX_DRAFT",
        approval_id=None,
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_seo_baseline(rec)


def list_india_seo_baselines(db: Session, *, org_id: str | None = None) -> list[dict[str, Any]]:
    """List India local SME SEO baselines."""
    q = db.query(P6SeoBaselineRecord)
    if org_id is not None:
        q = q.filter(P6SeoBaselineRecord.org_id == org_id)
    return [_serialize_seo_baseline(r) for r in q.order_by(P6SeoBaselineRecord.created_at.desc()).all()]


def compute_p6_overview(db: Session, *, org_id: str | None = None) -> dict[str, Any]:
    """Aggregate P6 multi-industry packs, tenant deployments, and India SEO baselines cleanly."""
    packs = list_industry_packs(db)
    deployments = list_pack_deployments(db, org_id=org_id)
    baselines = list_india_seo_baselines(db, org_id=org_id)
    return {
        "summary": {
            "pack_count": len(packs),
            "sandbox_pack_count": sum(1 for p in packs if p["readiness_status"] == "SANDBOX"),
            "roadmap_pack_count": sum(1 for p in packs if p["readiness_status"] == "ROADMAP"),
            "live_verified_pack_count": sum(1 for p in packs if p["readiness_status"] == "LIVE_VERIFIED"),
            "deployment_count": len(deployments),
            "seo_baseline_count": len(baselines),
        },
        "packs": packs,
        "deployments": deployments,
        "seo_baselines": baselines,
    }
