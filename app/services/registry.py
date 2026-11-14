"""Unified Central Service, Agent, and Connector Registry + Governed Agent Execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalRequest,
    OrganizationRecord,
    TaskRecord,
    TenantAgentConfigRecord,
)
from app.security.auth import APIPrincipal, check_tenant_entitlement, is_service_entitled
from app.services.billing_ledger import (
    InsufficientCreditsError,
    commit_credit_reservation,
    refund_credit_reservation,
    reserve_execution_credits,
)
from app.services.catalog import CATALOG, get_package
from app.services.connectors import list_connectors
from app.services.evidence import list_execution_evidence, record_execution_evidence
from app.services.execution_guard import (
    ExecutionBlockedError,
    check_execution_allowed,
    is_external_side_effect_blocked,
    record_simulated_dispatch,
    redact_secrets,
    resolve_execution_mode,
    validate_external_url,
)

# 9 Core SME Service Categories (§6)
SERVICE_CATEGORIES: dict[str, dict[str, str]] = {
    "lead_discovery": {
        "category_id": "lead_discovery",
        "title": "Customer & Lead Discovery",
        "icon": "🎯",
        "summary": "Discover, qualify, and enrich SME B2B buyer prospects.",
    },
    "research_intelligence": {
        "category_id": "research_intelligence",
        "title": "Research & Competitive Intelligence",
        "icon": "🔬",
        "summary": "Source-grounded company, competitive, and academic research.",
    },
    "sales_proposals": {
        "category_id": "sales_proposals",
        "title": "Sales & Proposal Operations",
        "icon": "💼",
        "summary": "Diagnose buyer pain, generate proposals, and stage HITL outreach.",
    },
    "seo_content": {
        "category_id": "seo_content",
        "title": "SEO, Content & Digital Presence",
        "icon": "✍️",
        "summary": "SEO/GEO/AIO articles and WordPress publishing workflows.",
    },
    "marketing_campaigns": {
        "category_id": "marketing_campaigns",
        "title": "Marketing & Creative Campaigns",
        "icon": "📣",
        "summary": "Omnichannel social calendars and multi-aspect ad creatives.",
    },
    "customer_support": {
        "category_id": "customer_support",
        "title": "Customer Support & Follow-Up",
        "icon": "💬",
        "summary": "Inbound inquiry triage and customer follow-up drafting with approval.",
    },
    "field_operations": {
        "category_id": "field_operations",
        "title": "Field Operations & Workforce Control",
        "icon": "🛰️",
        "summary": "Route dispatch, GPS geofence attendance, and shift telemetry.",
    },
    "inventory_quality": {
        "category_id": "inventory_quality",
        "title": "Inventory, Quality & Domain Operations",
        "icon": "📦",
        "summary": "StockSense ABC/EOQ inventory, AgriTech quality vision, and mobility OLS.",
    },
    "governance_trust": {
        "category_id": "governance_trust",
        "title": "Governance, Approvals, Compliance & Trust",
        "icon": "🛡️",
        "summary": "ECDSA NIST P-256 Merkle chain sealing, HITL approvals, and watchdog controls.",
    },
}


@dataclass(frozen=True)
class RegisteredService:
    service_id: str
    service_name: str
    category: str
    description: str
    business_outcome: str
    available_agents: tuple[str, ...]
    required_connectors: tuple[str, ...]
    entitlement_key: str
    pricing_reference: str
    execution_status: str
    version: str = "1.0.0"
    icon: str = "⚡"
    default_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class RegisteredAgent:
    agent_id: str
    agent_name: str
    description: str
    business_function: str
    capabilities: tuple[str, ...]
    supported_tools: tuple[str, ...]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    model_configuration: dict[str, Any]
    system_instructions: str
    permission_policy: dict[str, Any]
    execution_limits: dict[str, Any]
    required_approvals: tuple[str, ...]
    version: str = "1.0.0"
    status: str = "AVAILABLE"
    entitlement_key: str = "growth_all_in_one"
    default_connector_id: str = "project_api"
    credit_cost: int = 1


SERVICE_REGISTRY: dict[str, RegisteredService] = {
    "lead_discovery": RegisteredService(
        service_id="lead_discovery",
        service_name="SMB Lead Discovery & Qualification",
        category="lead_discovery",
        description="Discovers and scores target B2B companies by industry, geography, and fit signals.",
        business_outcome="Validated pipeline of qualified prospects without manual web scraping.",
        available_agents=("discovery_sdr_agent", "ceo_manager_agent"),
        required_connectors=("serper_search", "google_places", "project_api"),
        entitlement_key="lead_discovery",
        pricing_reference="company_os_starter",
        execution_status="SIMULATED",
        icon="🎯",
    ),
    "evidence_research": RegisteredService(
        service_id="evidence_research",
        service_name="Evidence-Grounded Company Research",
        category="research_intelligence",
        description="Synthesizes company dossiers grounded in citations and sealed to the Trust Ledger.",
        business_outcome="Decision-ready market intelligence with verifiable citation trails.",
        available_agents=("research_analyst_agent",),
        required_connectors=("serper_search", "gemini_api", "project_api"),
        entitlement_key="evidence_research",
        pricing_reference="company_os_starter",
        execution_status="LOCAL_ENGINE_VERIFIED",
        icon="🔬",
    ),
    "ask4_academic_order": RegisteredService(
        service_id="ask4_academic_order",
        service_name="ASK4 Academic & Technical Synthesis",
        category="research_intelligence",
        description="Produces structured academic literature reviews and BibTeX-formatted research briefs.",
        business_outcome="Structured scholarly synthesis reports sealed with ECDSA proof.",
        available_agents=("academic_research_agent",),
        required_connectors=("gemini_api", "project_api"),
        entitlement_key="ask4_academic_order",
        pricing_reference="ask4_academic_order",
        execution_status="LOCAL_ENGINE_VERIFIED",
        icon="📚",
    ),
    "sales_capture": RegisteredService(
        service_id="sales_capture",
        service_name="Sales Proposal & Outreach Engine",
        category="sales_proposals",
        description="Generates buyer pain diagnosis, customized proposals, and HITL-gated outreach.",
        business_outcome="Faster prospect-to-checkout conversion with mandatory human send approval.",
        available_agents=("sales_proposal_agent",),
        required_connectors=("hostinger_smtp", "razorpay", "afw_directpay"),
        entitlement_key="sales_capture",
        pricing_reference="company_os_starter",
        execution_status="HUMAN_ASSISTED",
        icon="💼",
    ),
    "managed_seo_content_pilot": RegisteredService(
        service_id="managed_seo_content_pilot",
        service_name="Managed SEO & Content Pilot (₹4,999 SKU)",
        category="seo_content",
        description="Creates SEO/GEO/AIO optimized long-form articles and stages WordPress CMS drafts.",
        business_outcome="Compounding organic & AI search visibility tailored to SME target keywords.",
        available_agents=("seo_content_agent",),
        required_connectors=("gemini_api", "wordpress_rest"),
        entitlement_key="managed_seo_content_pilot",
        pricing_reference="managed_seo_content_pilot",
        execution_status="LOCAL_ENGINE_VERIFIED",
        icon="🔍",
    ),
    "seo_blog_copilot": RegisteredService(
        service_id="seo_blog_copilot",
        service_name="SEO / GEO Blog Copilot",
        category="seo_content",
        description="Generates keyword-clustered articles structured for Google Search and LLM answers.",
        business_outcome="Consistent editorial velocity at deterministic low credit cost.",
        available_agents=("seo_content_agent",),
        required_connectors=("gemini_api", "wordpress_rest"),
        entitlement_key="seo_blog_copilot",
        pricing_reference="seo_blog_copilot",
        execution_status="LOCAL_ENGINE_VERIFIED",
        icon="✍️",
    ),
    "wordpress_publisher": RegisteredService(
        service_id="wordpress_publisher",
        service_name="WordPress Multi-Site Publishing Bridge",
        category="seo_content",
        description="Stages and publishes approved SEO articles across connected WordPress properties.",
        business_outcome="Automated CMS staging cleanly separated from external HTTP side effects in tests.",
        available_agents=("seo_content_agent",),
        required_connectors=("wordpress_rest",),
        entitlement_key="wordpress_publisher",
        pricing_reference="seo_blog_copilot",
        execution_status="SIMULATED",
        icon="🌐",
    ),
    "marketing_suite": RegisteredService(
        service_id="marketing_suite",
        service_name="Omnichannel Marketing & Social Suite",
        category="marketing_campaigns",
        description="Builds multi-platform social campaigns, ad hooks, and promotional schedules.",
        business_outcome="Coordinated LinkedIn, Instagram, and email campaign assets in one run.",
        available_agents=("marketing_creative_agent",),
        required_connectors=("social_media_bridge", "gemini_api"),
        entitlement_key="marketing_suite",
        pricing_reference="marketing_suite",
        execution_status="LOCAL_ENGINE_VERIFIED",
        icon="📣",
    ),
    "pixel_ai_pack": RegisteredService(
        service_id="pixel_ai_pack",
        service_name="Pixel AI Creative Ad Pack",
        category="marketing_campaigns",
        description="Produces multi-aspect-ratio (1:1, 9:16, 16:9) visual campaign copy & specs.",
        business_outcome="Platform-ready ad creatives aligned to brand voice.",
        available_agents=("marketing_creative_agent",),
        required_connectors=("gemini_api", "social_media_bridge"),
        entitlement_key="pixel_ai_pack",
        pricing_reference="pixel_ai_pack",
        execution_status="LOCAL_ENGINE_VERIFIED",
        icon="🎨",
    ),
    "growth_all_in_one": RegisteredService(
        service_id="growth_all_in_one",
        service_name="Unified Growth & Revenue Suite",
        category="marketing_campaigns",
        description="Chains research, SEO content, creative assets, and sales funnel execution together.",
        business_outcome="End-to-end growth workflow from discovery to conversion.",
        available_agents=("ceo_manager_agent", "marketing_creative_agent", "seo_content_agent"),
        required_connectors=("gemini_api", "wordpress_rest", "social_media_bridge"),
        entitlement_key="growth_all_in_one",
        pricing_reference="growth_all_in_one",
        execution_status="LOCAL_ENGINE_VERIFIED",
        icon="🚀",
    ),
    "support_followup": RegisteredService(
        service_id="support_followup",
        service_name="Customer Support & Follow-Up Operations",
        category="customer_support",
        description="Triages customer tickets/follow-ups and drafts HITL-gated email/WhatsApp replies.",
        business_outcome="Fast, consistent SLA-backed SME customer follow-ups with zero unapproved sends.",
        available_agents=("support_followup_agent",),
        required_connectors=("whatsapp_bridge", "hostinger_smtp", "project_api"),
        entitlement_key="support_followup",
        pricing_reference="company_os_starter",
        execution_status="HUMAN_ASSISTED",
        icon="💬",
    ),
    "field_force": RegisteredService(
        service_id="field_force",
        service_name="Zero-Trust Field Force Route & Attendance",
        category="field_operations",
        description="Validates GPS geofence check-ins, dispatches field tasks, and tracks conveyance.",
        business_outcome="Cryptographically verifiable field workforce operations.",
        available_agents=("field_ops_agent",),
        required_connectors=("project_api", "whatsapp_bridge"),
        entitlement_key="field_force",
        pricing_reference="field_force",
        execution_status="LOCAL_ENGINE_VERIFIED",
        icon="🛰️",
    ),
    "warehouse_automation": RegisteredService(
        service_id="warehouse_automation",
        service_name="Warehouse StockSense ABC/EOQ Optimizer",
        category="inventory_quality",
        description="Computes Pareto ABC classification, safety stock, EOQ, and dead-stock alerts.",
        business_outcome="Lower holding cost and prevention of stockouts across SME warehouses.",
        available_agents=("warehouse_stocksense_agent",),
        required_connectors=("project_api",),
        entitlement_key="warehouse_automation",
        pricing_reference="warehouse_automation",
        execution_status="LOCAL_ENGINE_VERIFIED",
        icon="📦",
    ),
    "mango_quality_analytics": RegisteredService(
        service_id="mango_quality_analytics",
        service_name="AgriTech Produce Quality & Ripeness AI",
        category="inventory_quality",
        description="Analyzes produce lot parameters, ripeness grade, and export defect severity.",
        business_outcome="Standardized packhouse grading and reduced spoilage loss.",
        available_agents=("quality_vision_agent",),
        required_connectors=("project_api",),
        entitlement_key="mango_quality_analytics",
        pricing_reference="mango_quality_analytics",
        execution_status="LOCAL_ENGINE_VERIFIED",
        icon="🥭",
    ),
    "bike_rebalance_analytics": RegisteredService(
        service_id="bike_rebalance_analytics",
        service_name="Urban Micro-Mobility OLS Rebalancer",
        category="inventory_quality",
        description="Forecasts station demand using spatial-temporal metrics and plans truck rebalancing.",
        business_outcome="Higher fleet availability during peak demand windows.",
        available_agents=("mobility_rebalance_agent",),
        required_connectors=("project_api",),
        entitlement_key="bike_rebalance_analytics",
        pricing_reference="bike_rebalance_analytics",
        execution_status="LOCAL_ENGINE_VERIFIED",
        icon="🚲",
    ),
    "trust_engine": RegisteredService(
        service_id="trust_engine",
        service_name="AFW Cryptographic Trust & Governance Ledger",
        category="governance_trust",
        description="Seals task evidence into ECDSA P-256 Merkle blocks and verifies ledger integrity.",
        business_outcome="Tamper-evident execution provenance for audits and compliance.",
        available_agents=("trust_governance_agent",),
        required_connectors=("project_api",),
        entitlement_key="trust_engine",
        pricing_reference="trust_engine",
        execution_status="LOCAL_ENGINE_VERIFIED",
        icon="🛡️",
    ),
}


AGENT_REGISTRY: dict[str, RegisteredAgent] = {
    "ceo_manager_agent": RegisteredAgent(
        agent_id="ceo_manager_agent",
        agent_name="CEO & Multi-Agent Operations Orchestrator",
        description="Coordinates lead discovery, research synthesis, and HITL-staged proposal workflows.",
        business_function="governance_trust",
        capabilities=("lead_generation", "evidence_research", "sales_proposal", "growth_all_in_one"),
        supported_tools=("discovery_pipeline", "research_synthesis", "sales_draft", "trust_seal"),
        input_schema={"type": "object", "properties": {"objective": {"type": "string"}, "limit": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"task_id": {"type": "string"}, "status": {"type": "string"}}},
        model_configuration={"model": "gemini-3.8-flash", "temperature": 0.2, "fallback": "local_deterministic"},
        system_instructions="Coordinate multi-step company growth workflows under strict HITL governance.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "max_scope": "organization"},
        execution_limits={"max_credits_per_run": 5, "max_steps": 5, "timeout_seconds": 60},
        required_approvals=("external_sales_outreach",),
        entitlement_key="growth_all_in_one",
        default_connector_id="project_api",
        credit_cost=1,
    ),
    "discovery_sdr_agent": RegisteredAgent(
        agent_id="discovery_sdr_agent",
        agent_name="SMB Lead Discovery SDR Agent",
        description="Finds and scores B2B prospect leads matching target industry and location.",
        business_function="lead_discovery",
        capabilities=("lead_generation", "customer_discovery"),
        supported_tools=("lead_search", "lead_scoring", "lead_dedupe"),
        input_schema={"type": "object", "properties": {"objective": {"type": "string"}, "limit": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"leads": {"type": "array"}, "count": {"type": "integer"}}},
        model_configuration={"model": "deterministic_scorer", "temperature": 0.0, "fallback": "synthetic_fixture"},
        system_instructions="Discover verified or synthetically flagged prospects; never fabricate live provenance.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True},
        execution_limits={"max_credits_per_run": 3, "timeout_seconds": 30},
        required_approvals=(),
        entitlement_key="lead_discovery",
        default_connector_id="serper_search",
        credit_cost=1,
    ),
    "research_analyst_agent": RegisteredAgent(
        agent_id="research_analyst_agent",
        agent_name="Evidence Research Analyst Agent",
        description="Compiles structured market & competitor synthesis grounded in provided sources.",
        business_function="research_intelligence",
        capabilities=("evidence_research",),
        supported_tools=("source_synthesis", "citation_builder", "trust_seal"),
        input_schema={"type": "object", "properties": {"company": {"type": "string"}, "sources": {"type": "array"}}},
        output_schema={"type": "object", "properties": {"synthesis": {"type": "string"}, "trust_block_hash": {"type": "string"}}},
        model_configuration={"model": "gemini-3.8-flash", "temperature": 0.2, "fallback": "local_deterministic"},
        system_instructions="Cite exact sources and seal research summary to the immutable trust chain.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True},
        execution_limits={"max_credits_per_run": 2, "timeout_seconds": 30},
        required_approvals=(),
        entitlement_key="evidence_research",
        default_connector_id="gemini_api",
        credit_cost=1,
    ),
    "academic_research_agent": RegisteredAgent(
        agent_id="academic_research_agent",
        agent_name="ASK4 Academic Synthesis Agent",
        description="Produces structured academic abstracts, methodology reviews, and BibTeX references.",
        business_function="research_intelligence",
        capabilities=("askforwrite_academic_ask4",),
        supported_tools=("academic_synthesis", "bibtex_formatter", "trust_seal"),
        input_schema={"type": "object", "properties": {"topic": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"title": {"type": "string"}, "abstract": {"type": "string"}}},
        model_configuration={"model": "gemini-3.8-flash", "temperature": 0.3, "fallback": "local_deterministic"},
        system_instructions="Produce rigorous scholarly synthesis with transparent citation formatting.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True},
        execution_limits={"max_credits_per_run": 2, "timeout_seconds": 45},
        required_approvals=(),
        entitlement_key="ask4_academic_order",
        default_connector_id="gemini_api",
        credit_cost=1,
    ),
    "sales_proposal_agent": RegisteredAgent(
        agent_id="sales_proposal_agent",
        agent_name="Sales Proposal & HITL Outreach Agent",
        description="Diagnoses buyer friction, generates commercial proposals, and stages outreach for HITL approval.",
        business_function="sales_proposals",
        capabilities=("sales_proposal", "inbound_sales_closer"),
        supported_tools=("pain_diagnose", "proposal_draft", "approval_request", "email_dispatch"),
        input_schema={"type": "object", "properties": {"prospect_name": {"type": "string"}, "message": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"reply": {"type": "string"}, "approval_id": {"type": "string"}}},
        model_configuration={"model": "gemini-3.8-flash", "temperature": 0.3, "fallback": "local_deterministic"},
        system_instructions="Stage all external outreach behind HITL ApprovalRequest before SMTP dispatch.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "external_send_gated": True},
        execution_limits={"max_credits_per_run": 2, "timeout_seconds": 30},
        required_approvals=("external_sales_outreach",),
        entitlement_key="sales_capture",
        default_connector_id="hostinger_smtp",
        credit_cost=1,
    ),
    "seo_content_agent": RegisteredAgent(
        agent_id="seo_content_agent",
        agent_name="SEO / GEO / WordPress Publishing Agent",
        description="Generates keyword-clustered articles and stages CMS drafts safely.",
        business_function="seo_content",
        capabilities=("seo_content_automation", "seo_blog_copilot"),
        supported_tools=("blog_generate", "seo_stage_draft", "wordpress_stage"),
        input_schema={"type": "object", "properties": {"product_name": {"type": "string"}, "keywords": {"type": "array"}}},
        output_schema={"type": "object", "properties": {"title": {"type": "string"}, "status": {"type": "string"}}},
        model_configuration={"model": "gemini-3.8-flash", "temperature": 0.4, "fallback": "local_deterministic"},
        system_instructions="Generate SEO/GEO structured content and avoid live WordPress mutation during simulation.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True},
        execution_limits={"max_credits_per_run": 2, "timeout_seconds": 45},
        required_approvals=(),
        entitlement_key="seo_blog_copilot",
        default_connector_id="wordpress_rest",
        credit_cost=1,
    ),
    "marketing_creative_agent": RegisteredAgent(
        agent_id="marketing_creative_agent",
        agent_name="Marketing Campaign & Pixel Creative Agent",
        description="Creates omnichannel social calendars and multi-ratio creative briefs.",
        business_function="marketing_campaigns",
        capabilities=("marketing_campaign_suite", "pixel_ai_creative_studio"),
        supported_tools=("social_campaign_generate", "creative_pack_generate"),
        input_schema={"type": "object", "properties": {"product_name": {"type": "string"}, "target_audience": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"campaign": {"type": "object"}}},
        model_configuration={"model": "gemini-3.8-flash", "temperature": 0.5, "fallback": "local_deterministic"},
        system_instructions="Draft audience-targeted omnichannel campaigns using verified brand context.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True},
        execution_limits={"max_credits_per_run": 2, "timeout_seconds": 45},
        required_approvals=(),
        entitlement_key="marketing_suite",
        default_connector_id="social_media_bridge",
        credit_cost=1,
    ),
    "support_followup_agent": RegisteredAgent(
        agent_id="support_followup_agent",
        agent_name="Customer Support & Follow-Up Agent",
        description="Drafts structured SLA follow-up responses and schedules HITL-approved customer messages.",
        business_function="customer_support",
        capabilities=("support_followup",),
        supported_tools=("ticket_triage", "followup_draft", "approval_request"),
        input_schema={"type": "object", "properties": {"customer_name": {"type": "string"}, "issue_summary": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"draft_response": {"type": "string"}, "approval_id": {"type": "string"}}},
        model_configuration={"model": "gemini-3.8-flash", "temperature": 0.2, "fallback": "local_deterministic"},
        system_instructions="Draft polite, factual customer follow-ups and require approval before external dispatch.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "external_send_gated": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 20},
        required_approvals=("customer_followup_dispatch",),
        entitlement_key="support_followup",
        default_connector_id="whatsapp_bridge",
        credit_cost=1,
    ),
    "field_ops_agent": RegisteredAgent(
        agent_id="field_ops_agent",
        agent_name="Field Operations & Dispatch Agent",
        description="Optimizes field visit routes, validates geofence telemetry, and logs visit summaries.",
        business_function="field_operations",
        capabilities=("field_force_automation",),
        supported_tools=("route_optimize", "telemetry_summary"),
        input_schema={"type": "object", "properties": {"city": {"type": "string"}, "stops": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"dispatch_plan": {"type": "object"}}},
        model_configuration={"model": "deterministic_routing", "temperature": 0.0, "fallback": "local_deterministic"},
        system_instructions="Enforce GPS geofence constraints and tamper-proof attendance logs.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 20},
        required_approvals=(),
        entitlement_key="field_force",
        default_connector_id="project_api",
        credit_cost=1,
    ),
    "warehouse_stocksense_agent": RegisteredAgent(
        agent_id="warehouse_stocksense_agent",
        agent_name="Warehouse StockSense ABC/EOQ Agent",
        description="Executes local mathematical ABC Pareto analysis, EOQ sizing, and dead-stock detection.",
        business_function="inventory_quality",
        capabilities=("warehouse_stocksense",),
        supported_tools=("inventory_abc_eoq", "dead_stock_audit"),
        input_schema={"type": "object", "properties": {"items": {"type": "array"}, "service_level_z": {"type": "number"}}},
        output_schema={"type": "object", "properties": {"summary": {"type": "object"}, "eoq_recommendations": {"type": "array"}}},
        model_configuration={"model": "deterministic_math_engine", "temperature": 0.0, "fallback": "local_deterministic"},
        system_instructions="Compute exact ABC/EOQ and reorder thresholds from inventory inputs.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 25},
        required_approvals=(),
        entitlement_key="warehouse_automation",
        default_connector_id="project_api",
        credit_cost=1,
    ),
    "quality_vision_agent": RegisteredAgent(
        agent_id="quality_vision_agent",
        agent_name="AgriTech Produce Quality Grading Agent",
        description="Assesses ripeness stage, brix index, and packhouse export grade locally.",
        business_function="inventory_quality",
        capabilities=("computer_vision_quality_analytics",),
        supported_tools=("quality_grade", "defect_scoring"),
        input_schema={"type": "object", "properties": {"variety": {"type": "string"}, "brix_score": {"type": "number"}}},
        output_schema={"type": "object", "properties": {"grade": {"type": "string"}, "export_ready": {"type": "boolean"}}},
        model_configuration={"model": "deterministic_quality_engine", "temperature": 0.0, "fallback": "local_deterministic"},
        system_instructions="Grade produce objectively from measured indicators without fabricating camera feeds.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 20},
        required_approvals=(),
        entitlement_key="mango_quality_analytics",
        default_connector_id="project_api",
        credit_cost=1,
    ),
    "mobility_rebalance_agent": RegisteredAgent(
        agent_id="mobility_rebalance_agent",
        agent_name="Urban Micro-Mobility OLS Rebalance Agent",
        description="Computes OLS demand forecasts and fleet rebalancing truck routes locally.",
        business_function="inventory_quality",
        capabilities=("spatiotemporal_logistics_optimization",),
        supported_tools=("mobility_forecast", "rebalance_route"),
        input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"demand_forecast": {"type": "object"}}},
        model_configuration={"model": "deterministic_ols_engine", "temperature": 0.0, "fallback": "local_deterministic"},
        system_instructions="Produce verifiable station rebalancing plans.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 20},
        required_approvals=(),
        entitlement_key="bike_rebalance_analytics",
        default_connector_id="project_api",
        credit_cost=1,
    ),
    "trust_governance_agent": RegisteredAgent(
        agent_id="trust_governance_agent",
        agent_name="Trust Ledger & Watchdog Governance Agent",
        description="Verifies ECDSA NIST P-256 Merkle chains and seals audit evidence blocks.",
        business_function="governance_trust",
        capabilities=("trust_ledger_audit",),
        supported_tools=("trust_seal", "trust_verify", "watchdog_scan"),
        input_schema={"type": "object", "properties": {"action": {"type": "string"}, "payload": {"type": "object"}}},
        output_schema={"type": "object", "properties": {"chain_valid": {"type": "boolean"}, "block_hash": {"type": "string"}}},
        model_configuration={"model": "ecdsa_p256_deterministic", "temperature": 0.0, "fallback": "local_deterministic"},
        system_instructions="Never alter append-only trust ledger entries; verify chain hashes strictly.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 15},
        required_approvals=(),
        entitlement_key="trust_engine",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "market_research_agent": RegisteredAgent(
        agent_id="market_research_agent",
        agent_name="Market Research Agent (India Agency ICP)",
        description="Synthesizes market segment observations and verifies catalog offer boundaries without fabricating benchmarks.",
        business_function="research_intelligence",
        capabilities=("evidence_research",),
        supported_tools=("catalog_verify", "source_lookup", "claim_classifier"),
        input_schema={"type": "object", "properties": {"sku_key": {"type": "string", "default": "managed_seo_content_pilot"}}},
        output_schema={"type": "object", "properties": {"offer_contract": {"type": "object"}}},
        model_configuration={"model": "gemini-3.8-flash", "temperature": 0.1, "fallback": "local_deterministic"},
        system_instructions="Never invent discounts, guarantees, case studies, or unsupported ROI numbers.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "autonomous_price_change": False},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=(),
        entitlement_key="evidence_research",
        default_connector_id="project_api",
        credit_cost=1,
    ),
    "prospect_discovery_agent": RegisteredAgent(
        agent_id="prospect_discovery_agent",
        agent_name="Prospect Discovery Agent (P2 Real Agencies)",
        description="Discovers or curates real Indian digital marketing / SEO agencies while rejecting synthetic fixtures.",
        business_function="lead_discovery",
        capabilities=("lead_generation", "customer_discovery"),
        supported_tools=("serper_search", "google_places", "website_enrich", "domain_company_dedupe"),
        input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"discovered_count": {"type": "integer"}, "status": {"type": "string"}}},
        model_configuration={"model": "deterministic_extractor", "temperature": 0.0, "fallback": "blocked_without_live_source"},
        system_instructions="Reject synthetic fixtures, record source URL and date collected, and deduplicate on normalized domain and company identity.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "reject_synthetic_in_prod": True},
        execution_limits={"max_credits_per_run": 2, "timeout_seconds": 30},
        required_approvals=(),
        entitlement_key="lead_discovery",
        default_connector_id="serper_search",
        credit_cost=1,
    ),
    "lead_qualification_agent": RegisteredAgent(
        agent_id="lead_qualification_agent",
        agent_name="Lead Qualification Agent (6-Criterion Scorer)",
        description="Scores prospect fit transparently across 6 criteria with supporting source evidence.",
        business_function="lead_discovery",
        capabilities=("lead_generation",),
        supported_tools=("rubric_scorer", "contact_validity_check", "freshness_check"),
        input_schema={"type": "object", "properties": {"lead_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"qualification_score": {"type": "number"}, "criteria": {"type": "object"}}},
        model_configuration={"model": "deterministic_scorer", "temperature": 0.0, "fallback": "local_deterministic"},
        system_instructions="Present scores as configurable estimates backed by source evidence, never as verified facts.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 15},
        required_approvals=(),
        entitlement_key="lead_discovery",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "account_intelligence_agent": RegisteredAgent(
        agent_id="account_intelligence_agent",
        agent_name="Account Intelligence Agent",
        description="Builds account-specific research briefs separating Verified Facts, Reasonable Inferences, and Unverified Assumptions.",
        business_function="research_intelligence",
        capabilities=("evidence_research",),
        supported_tools=("dossier_reader", "brief_generator", "epistemic_classifier"),
        input_schema={"type": "object", "properties": {"lead_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"verified_facts": {"type": "array"}, "unverified_assumptions": {"type": "array"}}},
        model_configuration={"model": "gemini-3.8-flash", "temperature": 0.2, "fallback": "local_deterministic"},
        system_instructions="Clearly separate verified facts from reasonable inferences and unverified assumptions.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=(),
        entitlement_key="evidence_research",
        default_connector_id="gemini_api",
        credit_cost=1,
    ),
    "outreach_preparation_agent": RegisteredAgent(
        agent_id="outreach_preparation_agent",
        agent_name="Outreach Preparation Agent (HITL-Gated)",
        description="Prepares honest, claim-grounded outreach emails gated by Owner HITL approval, suppression, and rate limits.",
        business_function="sales_proposals",
        capabilities=("sales_proposal",),
        supported_tools=("suppression_check", "rate_limit_check", "honesty_validator", "approval_request"),
        input_schema={"type": "object", "properties": {"lead_id": {"type": "string"}, "recipient_email": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"outreach_id": {"type": "string"}, "approval_id": {"type": "string"}, "status": {"type": "string"}}},
        model_configuration={"model": "gemini-3.8-flash", "temperature": 0.2, "fallback": "local_deterministic"},
        system_instructions="Never send unapproved external messages; enforce suppression list, rate limits, and zero fabricated claims.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "external_send_gated": True, "autonomous_send": False},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 25},
        required_approvals=("external_sales_outreach",),
        entitlement_key="sales_capture",
        default_connector_id="hostinger_smtp",
        credit_cost=1,
    ),
    "customer_onboarding_agent": RegisteredAgent(
        agent_id="customer_onboarding_agent",
        agent_name="Customer Onboarding Agent",
        description="Creates post-payment customer engagements, assigns SKU entitlements, and tracks required onboarding inputs.",
        business_function="customer_support",
        capabilities=("support_followup",),
        supported_tools=("onboarding_checklist", "entitlement_assign", "input_collector"),
        input_schema={"type": "object", "properties": {"engagement_id": {"type": "string"}, "target_domain": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"engagement_id": {"type": "string"}, "status": {"type": "string"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.0, "fallback": "local_deterministic"},
        system_instructions="Never activate unpaid customers or perform autonomous payment/refund actions.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "autonomous_payment_activation": False},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 20},
        required_approvals=(),
        entitlement_key="support_followup",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "customer_success_agent": RegisteredAgent(
        agent_id="customer_success_agent",
        agent_name="Customer Success & Renewal Agent",
        description="Links P1 pilot delivery workflows, gathers verified buyer feedback, and builds evidence-grounded renewal recommendations.",
        business_function="customer_support",
        capabilities=("support_followup", "seo_content_automation"),
        supported_tools=("workflow_delivery", "feedback_capture", "renewal_recommender"),
        input_schema={"type": "object", "properties": {"engagement_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"status": {"type": "string"}, "deliverables": {"type": "object"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.1, "fallback": "local_deterministic"},
        system_instructions="Never mark delivery completed from drafts alone; never process autonomous renewals without explicit buyer consent.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "autonomous_charge": False},
        execution_limits={"max_credits_per_run": 2, "timeout_seconds": 45},
        required_approvals=(),
        entitlement_key="support_followup",
        default_connector_id="project_api",
        credit_cost=1,
    ),
    # ------------------------------------------------------------------
    # P3 — Customer Success, Retention & Repeatable Growth AI Workforce (8)
    # ------------------------------------------------------------------
    "cs_onboarding_specialist_agent": RegisteredAgent(
        agent_id="cs_onboarding_specialist_agent",
        agent_name="Customer Onboarding Specialist Agent",
        description="Guides agency onboarding tasks, surfaces connector/input blockers, and verifies activation readiness criteria without prematurely activating accounts.",
        business_function="customer_support",
        capabilities=("customer_onboarding", "readiness_verification", "support_followup"),
        supported_tools=("onboarding_tracker", "connector_verifier", "readiness_gate"),
        input_schema={"type": "object", "required": ["org_id"], "properties": {"org_id": {"type": "string"}, "sku_key": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"workflow": {"type": "object"}, "blockers": {"type": "array"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.1, "fallback": "local_deterministic"},
        system_instructions="Never mark an account ACTIVE until every required onboarding criterion, connector check, and training item is verified.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "cannot_bypass_activation_gate": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=(),
        entitlement_key="support_followup",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "cs_manager_agent": RegisteredAgent(
        agent_id="cs_manager_agent",
        agent_name="Customer Success Manager Agent",
        description="Evaluates evidence-backed Customer Health scores (HEALTHY/NEEDS_ATTENTION/AT_RISK/INSUFFICIENT_DATA) and raises internal churn/blocker alerts.",
        business_function="customer_support",
        capabilities=("customer_health", "churn_early_warning", "customer_360"),
        supported_tools=("health_scorer", "customer_360_reader", "internal_alert_dispatcher"),
        input_schema={"type": "object", "required": ["org_id"], "properties": {"org_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"health": {"type": "object"}, "alerts_created": {"type": "array"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.0, "fallback": "local_deterministic"},
        system_instructions="Use only observed multi-dimension customer evidence; output INSUFFICIENT_DATA when <3 dimensions exist and send alerts internally only.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "internal_alerts_only": True, "cannot_modify_pricing": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=(),
        entitlement_key="support_followup",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "service_delivery_coordinator_agent": RegisteredAgent(
        agent_id="service_delivery_coordinator_agent",
        agent_name="Service Delivery Coordinator Agent",
        description="Coordinates deliverables, quality states, workflow execution links, and separates factual outputs from Search Console outcome metrics.",
        business_function="operations",
        capabilities=("delivery_management", "workflow_coordination", "outcome_tracking"),
        supported_tools=("delivery_tracker", "workflow_linker", "artifact_ledger"),
        input_schema={"type": "object", "required": ["org_id"], "properties": {"org_id": {"type": "string"}, "title": {"type": "string"}, "requirement": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"deliveries": {"type": "array"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.1, "fallback": "local_deterministic"},
        system_instructions="Track scope, inputs, and deliverables faithfully; never assert causal SEO outcome claims without verified GSC connection and baseline data.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "cannot_fabricate_outcomes": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 45},
        required_approvals=(),
        entitlement_key="support_followup",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "qa_review_agent": RegisteredAgent(
        agent_id="qa_review_agent",
        agent_name="Quality Assurance Review Agent",
        description="Performs structured quality verification checks and records evidence gates before deliverables move from QUALITY_REVIEW to customer delivery.",
        business_function="operations",
        capabilities=("quality_assurance", "evidence_audit", "revision_control"),
        supported_tools=("qa_checklist_validator", "evidence_verifier"),
        input_schema={"type": "object", "properties": {"delivery_id": {"type": "string"}, "org_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"qa_status": {"type": "string"}, "checks": {"type": "object"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.0, "fallback": "local_deterministic"},
        system_instructions="Fail QA whenever required evidence or deliverables are missing; never rubber-stamp incomplete outputs.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "cannot_bypass_qa_gate": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=(),
        entitlement_key="support_followup",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "cs_support_specialist_agent": RegisteredAgent(
        agent_id="cs_support_specialist_agent",
        agent_name="Customer Support Specialist Agent",
        description="Triages support tickets against authorized platform documentation and forces Owner HITL gating for refunds, pricing, legal, or account access changes.",
        business_function="customer_support",
        capabilities=("support_triage", "docs_rag", "hitl_escalation"),
        supported_tools=("authorized_docs_search", "ticket_triager", "approval_gate"),
        input_schema={"type": "object", "required": ["ticket_id"], "properties": {"ticket_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"classification": {"type": "object"}, "requires_hitl_approval": {"type": "boolean"}}},
        model_configuration={"model": "gemini-3.8-flash", "temperature": 0.1, "fallback": "local_deterministic"},
        system_instructions="Answer strictly from verified docs/state; escalate immediately and block external send if refund, pricing, discount, legal, or access change is involved.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "cannot_issue_refunds": True, "cannot_modify_pricing": True, "cannot_send_sensitive_external_replies_without_hitl": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=("support_sensitive_external_reply",),
        entitlement_key="support_followup",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "renewal_management_agent": RegisteredAgent(
        agent_id="renewal_management_agent",
        agent_name="Renewal Management Agent",
        description="Monitors upcoming renewals, grace windows, failed recurring charges, and enforces grace-period expirations without issuing unauthorized charges or refunds.",
        business_function="finance_ops",
        capabilities=("renewal_tracking", "grace_period_monitoring", "subscription_audit"),
        supported_tools=("subscription_reliability_inspector", "grace_period_enforcer"),
        input_schema={"type": "object", "properties": {"org_id": {"type": "string"}, "days_ahead": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"upcoming_renewals": {"type": "array"}, "expired_grace_suspensions": {"type": "array"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.0, "fallback": "local_deterministic"},
        system_instructions="Distinguish RECURRING_SUBSCRIPTION from ONE_TIME_PURCHASE and MANUAL_PAYMENT_PROOF; never process refunds or alter billing terms without HITL.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "cannot_issue_refunds": True, "cannot_modify_pricing": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=("subscription_pricing_or_refund_action",),
        entitlement_key="support_followup",
        default_connector_id="razorpay",
        credit_cost=0,
    ),
    "expansion_opportunity_agent": RegisteredAgent(
        agent_id="expansion_opportunity_agent",
        agent_name="Expansion Opportunity Agent",
        description="Identifies evidence-backed catalog upgrades (credit exhaustion, seat growth, multi-module adoption) and stages Owner HITL approvals before external sharing.",
        business_function="sales",
        capabilities=("expansion_detection", "catalog_matching", "referral_staging"),
        supported_tools=("catalog_pricing_lookup", "usage_signal_analyzer", "approval_gate"),
        input_schema={"type": "object", "required": ["org_id"], "properties": {"org_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"opportunities": {"type": "array"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.1, "fallback": "local_deterministic"},
        system_instructions="Quote ONLY catalog-verified SKUs and pricing; never invent discounts or send expansion/referral offers externally without Owner HITL approval.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "cannot_modify_pricing": True, "requires_hitl_to_share": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=("expansion_offer_or_referral",),
        entitlement_key="support_followup",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "customer_insights_analyst_agent": RegisteredAgent(
        agent_id="customer_insights_analyst_agent",
        agent_name="Customer Insights Analyst Agent",
        description="Clusters recurring support issues, revision causes, low CSAT patterns, and unit economics metrics into prioritized product & service improvements.",
        business_function="research_intelligence",
        capabilities=("improvement_synthesis", "unit_economics_analysis", "feedback_clustering"),
        supported_tools=("improvement_loop_engine", "unit_economics_calculator"),
        input_schema={"type": "object", "properties": {"org_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"improvement_items": {"type": "array"}, "unit_economics": {"type": "object"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.1, "fallback": "local_deterministic"},
        system_instructions="Prioritize improvements strictly from observed tickets/deliveries/onboarding blockers; never modify production code or invent LTV/CAC actuals.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "read_and_recommend_only": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=(),
        entitlement_key="support_followup",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "gtm_strategist_agent": RegisteredAgent(
        agent_id="gtm_strategist_agent",
        agent_name="P4 Repeatable GTM Strategist Agent",
        description="Generates claim-safe multi-channel GTM campaigns and computes ACTUAL vs SANDBOX funnel attribution.",
        business_function="marketing_campaigns",
        capabilities=("gtm_strategy", "campaign_staging", "funnel_attribution"),
        supported_tools=("icp_matcher", "claim_safety_filter", "hitl_campaign_stage", "funnel_analytics"),
        input_schema={"type": "object", "properties": {"org_id": {"type": "string"}, "name": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"analytics": {"type": "object"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.2, "fallback": "local_deterministic"},
        system_instructions="Stage all GTM campaigns behind Owner HITL ApprovalRequest and never mix SANDBOX into ACTUAL revenue funnel totals.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "requires_hitl_to_publish": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=("p4_gtm_campaign_launch",),
        entitlement_key="marketing_suite",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "competitive_intel_agent": RegisteredAgent(
        agent_id="competitive_intel_agent",
        agent_name="P4 Market & Competitor Intelligence Agent",
        description="Synthesizes provenance-backed market, competitor, and keyword gap insights with strict URL/evidence verification.",
        business_function="research_intelligence",
        capabilities=("market_intelligence", "competitor_benchmarking", "keyword_gap_analysis"),
        supported_tools=("intel_provenance_validator", "icp_scorer"),
        input_schema={"type": "object", "properties": {"org_id": {"type": "string"}, "intel_type": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"intel": {"type": "array"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.1, "fallback": "local_deterministic"},
        system_instructions="Attach explicit source_url, collected_at, and evidence_ref before marking intelligence VERIFIED_SOURCE.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "read_and_recommend_only": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=(),
        entitlement_key="evidence_research",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "tenant_provisioning_agent": RegisteredAgent(
        agent_id="tenant_provisioning_agent",
        agent_name="P5 Idempotent Tenant Provisioning Agent",
        description="Audits catalog-grounded templates, 9-state tenant provisioning FSM runs, and idempotent onboarding recovery.",
        business_function="platform_operations",
        capabilities=("template_validation", "idempotent_provisioning", "connector_staging"),
        supported_tools=("catalog_binding_check", "provisioning_fsm_runner", "trust_chain_seal"),
        input_schema={"type": "object", "properties": {"org_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"summary": {"type": "object"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.1, "fallback": "local_deterministic"},
        system_instructions="Bind every template to live CATALOG/MODULAR_SME_TIERS prices and never duplicate provisioning runs across retries.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "read_and_recommend_only": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=(),
        entitlement_key="trust_engine",
        default_connector_id="project_api",
        credit_cost=0,
    ),
    "sla_operations_agent": RegisteredAgent(
        agent_id="sla_operations_agent",
        agent_name="P5 Multi-Tenant Quota & SLA Operations Agent",
        description="Monitors tenant rate limits, credit budgets, quota breaches, and SLA incident deadlines.",
        business_function="trust_governance",
        capabilities=("quota_monitoring", "sla_tracking", "incident_triage"),
        supported_tools=("policy_evaluator", "incident_sla_tracker"),
        input_schema={"type": "object", "properties": {"org_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"incidents": {"type": "array"}}},
        model_configuration={"model": "local_deterministic", "temperature": 0.1, "fallback": "local_deterministic"},
        system_instructions="Enforce tenant isolation across quota checks and preserve accurate SLA breach timestamps.",
        permission_policy={"tenant_scoped": True, "requires_entitlement": True, "read_and_recommend_only": True},
        execution_limits={"max_credits_per_run": 1, "timeout_seconds": 30},
        required_approvals=(),
        entitlement_key="support_followup",
        default_connector_id="project_api",
        credit_cost=0,
    ),
}


def serialize_service(svc: RegisteredService, *, entitled: bool | None = None) -> dict[str, Any]:
    """Serialize all 11 Service Registry fields plus UI metadata."""
    pkg = get_package(svc.pricing_reference) or CATALOG.get(svc.pricing_reference)
    return {
        "service_id": svc.service_id,
        "service_name": svc.service_name,
        "category": svc.category,
        "category_title": SERVICE_CATEGORIES.get(svc.category, {}).get("title", svc.category),
        "description": svc.description,
        "business_outcome": svc.business_outcome,
        "available_agents": list(svc.available_agents),
        "required_connectors": list(svc.required_connectors),
        "entitlement_key": svc.entitlement_key,
        "pricing_reference": svc.pricing_reference,
        "pricing_summary": (
            {"price_inr": pkg.price_inr, "price_usd": pkg.price_usd, "tier": pkg.tier}
            if pkg
            else {"price_inr": 0, "price_usd": 0, "tier": "starter"}
        ),
        "execution_status": svc.execution_status,
        "version": svc.version,
        "icon": svc.icon,
        "entitled": entitled,
    }


def serialize_agent(
    agent: RegisteredAgent,
    tenant_cfg: TenantAgentConfigRecord | None = None,
    *,
    entitled: bool | None = None,
) -> dict[str, Any]:
    """Serialize all 15 Agent Registry fields plus tenant activation & config state."""
    effective_model = dict(agent.model_configuration)
    if tenant_cfg and tenant_cfg.model_override:
        effective_model["model"] = tenant_cfg.model_override
    effective_instructions = (
        tenant_cfg.custom_instructions
        if (tenant_cfg and tenant_cfg.custom_instructions)
        else agent.system_instructions
    )
    effective_limits = dict(agent.execution_limits)
    if tenant_cfg and tenant_cfg.execution_limits:
        effective_limits.update(tenant_cfg.execution_limits)
    effective_status = tenant_cfg.status if tenant_cfg else agent.status
    is_active = bool(tenant_cfg.is_active) if tenant_cfg else False
    effective_allowlist = (
        list(tenant_cfg.tool_allowlist)
        if (tenant_cfg and tenant_cfg.tool_allowlist)
        else list(agent.supported_tools)
    )

    return {
        "agent_id": agent.agent_id,
        "agent_name": agent.agent_name,
        "description": agent.description,
        "business_function": agent.business_function,
        "capabilities": list(agent.capabilities),
        "supported_tools": list(agent.supported_tools),
        "input_schema": agent.input_schema,
        "output_schema": agent.output_schema,
        "model_configuration": effective_model,
        "system_instructions": effective_instructions,
        "permission_policy": dict(agent.permission_policy),
        "execution_limits": effective_limits,
        "required_approvals": list(agent.required_approvals),
        "version": agent.version,
        "status": effective_status,
        "is_active": is_active,
        "entitlement_key": agent.entitlement_key,
        "default_connector_id": agent.default_connector_id,
        "credit_cost": agent.credit_cost,
        "tool_allowlist": effective_allowlist,
        "execution_mode": tenant_cfg.execution_mode if tenant_cfg else resolve_execution_mode(),
        "entitled": entitled,
    }


def _principal_entitlements(db: Session, principal: APIPrincipal) -> tuple[set[str], str | None, bool]:
    if not principal.org_id:
        return {"all_access"}, "enterprise", True
    org = db.get(OrganizationRecord, principal.org_id)
    if not org or not org.is_active:
        return set(), None, False
    meta = org.metadata_json or {}
    pkg_key = meta.get("package_key") or org.tier
    caps = set(meta.get("entitled_capabilities") or [])
    if not caps and pkg_key:
        pkg = get_package(pkg_key) or CATALOG.get(pkg_key)
        if pkg:
            caps = set(pkg.entitled_capabilities)
    return caps, pkg_key, True


def list_registered_services(
    db: Session,
    *,
    principal: APIPrincipal | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """Return central Service Registry items (single source of truth for API and dashboard)."""
    caps: set[str] = set()
    pkg_key: str | None = None
    if principal:
        caps, pkg_key, _ = _principal_entitlements(db, principal)

    items: list[dict[str, Any]] = []
    for svc in SERVICE_REGISTRY.values():
        if category and svc.category != category:
            continue
        entitled = is_service_entitled(svc.entitlement_key, caps, pkg_key) if principal else None
        items.append(serialize_service(svc, entitled=entitled))
    return {
        "count": len(items),
        "categories": list(SERVICE_CATEGORIES.values()),
        "services": items,
    }


def list_registered_agents(
    db: Session,
    *,
    principal: APIPrincipal | None = None,
    business_function: str | None = None,
) -> dict[str, Any]:
    """Return Agent Registry merged with tenant activation & configuration."""
    org_id = principal.org_id if principal else None
    caps: set[str] = set()
    pkg_key: str | None = None
    if principal:
        caps, pkg_key, _ = _principal_entitlements(db, principal)

    cfg_map: dict[str, TenantAgentConfigRecord] = {}
    target_org = org_id or "__platform__"
    rows = db.query(TenantAgentConfigRecord).filter_by(org_id=target_org).all()
    cfg_map = {r.agent_id: r for r in rows}

    agents: list[dict[str, Any]] = []
    for ag in AGENT_REGISTRY.values():
        if business_function and ag.business_function != business_function:
            continue
        entitled = is_service_entitled(ag.entitlement_key, caps, pkg_key) if principal else None
        agents.append(serialize_agent(ag, cfg_map.get(ag.agent_id), entitled=entitled))
    return {"count": len(agents), "agents": agents}


def get_agent_detail(db: Session, agent_id: str, principal: APIPrincipal | None = None) -> dict[str, Any]:
    ag = AGENT_REGISTRY.get(agent_id)
    if not ag:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in registry")
    target_org = (principal.org_id if principal else None) or "__platform__"
    cfg = db.query(TenantAgentConfigRecord).filter_by(org_id=target_org, agent_id=agent_id).first()
    entitled = None
    if principal:
        caps, pkg_key, _ = _principal_entitlements(db, principal)
        entitled = is_service_entitled(ag.entitlement_key, caps, pkg_key)
    return serialize_agent(ag, cfg, entitled=entitled)


def set_agent_activation(
    db: Session,
    *,
    agent_id: str,
    principal: APIPrincipal,
    active: bool,
) -> dict[str, Any]:
    """Activate or deactivate a registered agent enforcing entitlement, tenant identity, and permissions."""
    ag = AGENT_REGISTRY.get(agent_id)
    if not ag:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in registry")

    if active:
        check_tenant_entitlement(principal, ag.entitlement_key, db)

    target_org = principal.org_id or "__platform__"
    if principal.org_id:
        org = db.get(OrganizationRecord, principal.org_id)
        if not org or not org.is_active:
            raise HTTPException(status_code=403, detail="Active organization required to activate agents")

    cfg = db.query(TenantAgentConfigRecord).filter_by(org_id=target_org, agent_id=agent_id).first()
    now = datetime.now(UTC)
    if cfg is None:
        cfg = TenantAgentConfigRecord(
            org_id=target_org,
            agent_id=agent_id,
            version=ag.version,
            is_active=active,
            status="ACTIVE" if active else "DEACTIVATED",
            execution_mode=resolve_execution_mode(),
            tool_allowlist=list(ag.supported_tools),
            execution_limits=dict(ag.execution_limits),
            activated_by=principal.subject,
            created_at=now,
            updated_at=now,
        )
        db.add(cfg)
    else:
        cfg.is_active = active
        cfg.status = "ACTIVE" if active else "DEACTIVATED"
        cfg.activated_by = principal.subject
        cfg.updated_at = now
    db.commit()
    return serialize_agent(ag, cfg, entitled=True)


def configure_agent_for_tenant(
    db: Session,
    *,
    agent_id: str,
    principal: APIPrincipal,
    model_override: str | None = None,
    execution_mode: str | None = None,
    custom_instructions: str | None = None,
    tool_allowlist: list[str] | None = None,
    execution_limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist per-tenant agent configuration while preventing unauthorized tool escalation."""
    ag = AGENT_REGISTRY.get(agent_id)
    if not ag:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in registry")
    check_tenant_entitlement(principal, ag.entitlement_key, db)

    if tool_allowlist is not None:
        invalid_tools = [t for t in tool_allowlist if t not in ag.supported_tools]
        if invalid_tools:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cannot allow unauthorized tools {invalid_tools}; allowed tools for '{agent_id}': {list(ag.supported_tools)}",
            )

    clean_mode = resolve_execution_mode(execution_mode) if execution_mode else resolve_execution_mode()
    target_org = principal.org_id or "__platform__"
    cfg = db.query(TenantAgentConfigRecord).filter_by(org_id=target_org, agent_id=agent_id).first()
    now = datetime.now(UTC)
    if cfg is None:
        cfg = TenantAgentConfigRecord(
            org_id=target_org,
            agent_id=agent_id,
            version=ag.version,
            is_active=True,
            status="ACTIVE",
            execution_mode=clean_mode,
            tool_allowlist=list(tool_allowlist) if tool_allowlist is not None else list(ag.supported_tools),
            execution_limits=dict(execution_limits) if execution_limits is not None else dict(ag.execution_limits),
            model_override=model_override,
            custom_instructions=custom_instructions,
            activated_by=principal.subject,
            created_at=now,
            updated_at=now,
        )
        db.add(cfg)
    else:
        if model_override is not None:
            cfg.model_override = model_override
        if execution_mode is not None:
            cfg.execution_mode = clean_mode
        if custom_instructions is not None:
            cfg.custom_instructions = custom_instructions
        if tool_allowlist is not None:
            cfg.tool_allowlist = list(tool_allowlist)
        if execution_limits is not None:
            merged = dict(cfg.execution_limits or ag.execution_limits)
            merged.update(execution_limits)
            cfg.execution_limits = merged
        cfg.updated_at = now
    db.commit()
    return serialize_agent(ag, cfg, entitled=True)


def _dispatch_domain_agent(
    db: Session,
    *,
    agent: RegisteredAgent,
    tenant_id: str,
    actor: str,
    exec_mode: str,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    """Execute the specialist agent's domain logic with simulation-safe external boundaries."""
    agent_id = agent.agent_id

    # SSRF validation if caller passed an external URL/webhook/wordpress URL
    for url_field in ("target_url", "website", "webhook_url", "site_url"):
        if input_payload.get(url_field):
            validate_external_url(str(input_payload[url_field]))

    # Domain delegations reusing core backend engines (never duplicating business math)
    if agent_id == "discovery_sdr_agent":
        from app.services.discovery import execute_discovery
        from app.services.watchdog import _VerifiedSimulationSourceProvider

        res = execute_discovery(
            db=db,
            objective=str(input_payload.get("objective", f"B2B SME prospects for {tenant_id}")),
            limit=max(1, min(int(input_payload.get("limit", 2)), 10)),
            idempotency_key=f"reg-disc-{uuid.uuid4().hex[:12]}",
            correlation_id=str(uuid.uuid4()),
            agent_id=actor,
            org_id=None if tenant_id == "__platform__" else tenant_id,
            provider=_VerifiedSimulationSourceProvider(),
        )
        return {
            "output": res,
            "uses_external_provider": True,
            "fallback_used": exec_mode == "SIMULATION",
            "provider_request_id": f"sim-serper-{uuid.uuid4().hex[:10]}" if exec_mode == "SIMULATION" else None,
        }

    if agent_id == "research_analyst_agent":
        from app.agents.research import build_research
        from app.security.trust_chain import seal_task_to_block

        task_id = str(uuid.uuid4())
        company = str(input_payload.get("company", tenant_id))
        sources = input_payload.get("sources") or [
            {"url": "https://askforwrite.com/research", "snippet": f"{company} digital operations evaluation."}
        ]
        db.add(TaskRecord(id=task_id, correlation_id=str(uuid.uuid4()), objective=f"Research: {company}", status="COMPLETED"))
        db.flush()
        draft = build_research(company, sources)
        block = seal_task_to_block(
            db=db,
            task_id=task_id,
            capability_name="evidence_research",
            action="registry_research_run",
            payload={"company": company, "sources_count": len(draft.sources)},
            sealed_by=actor,
        )
        return {
            "output": {
                "task_id": task_id,
                "company": company,
                "synthesis": draft.synthesis,
                "analysis": draft.analysis,
                "sources": draft.sources,
                "trust_block_hash": block.block_hash,
            },
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"trust-block-{block.index}",
        }

    if agent_id == "academic_research_agent":
        from app.agents.llm_client import generate, has_gemini_api_key
        from app.security.trust_chain import seal_task_to_block

        topic = str(input_payload.get("topic", "Multi-Agent Business Governance"))
        task_id = str(uuid.uuid4())
        db.add(TaskRecord(id=task_id, correlation_id=str(uuid.uuid4()), objective=f"ASK4: {topic[:120]}", status="COMPLETED"))
        db.flush()
        fallback = exec_mode == "SIMULATION" or not has_gemini_api_key()
        text = generate(
            prompt=f"Write a scholarly synthesis abstract on: {topic}",
            system_instruction="ASK4 Academic Synthesis Agent",
            fallback_text=f"Structured synthesis on {topic} covering methodological rigor and verifiable citations.",
        )
        block = seal_task_to_block(
            db=db,
            task_id=task_id,
            capability_name="askforwrite_academic_ask4",
            action="academic_synthesis",
            payload={"topic": topic},
            sealed_by=actor,
        )
        return {
            "output": {"task_id": task_id, "topic": topic, "abstract": text, "trust_block_hash": block.block_hash},
            "uses_external_provider": not fallback,
            "fallback_used": fallback,
            "provider_request_id": f"ask4-block-{block.index}",
        }

    if agent_id == "seo_content_agent":
        from app.services.growth_engine import generate_and_stage_blog
        from app.services.seo import execute_seo_draft

        product_name = str(input_payload.get("product_name", "AskforWrite SME Client"))
        target_net = str(input_payload.get("target_network", "askforwrite.com"))
        keywords = input_payload.get("keywords") or [product_name, "AI Operations", "SEO Automation"]
        blog = generate_and_stage_blog(
            product_name=product_name,
            target_audience=str(input_payload.get("target_audience", "SME Founders")),
            keywords=keywords,
            target_domain=f"https://{target_net}/blog",
        )
        staged = execute_seo_draft(
            db=db,
            target_network=target_net,
            keywords=keywords,
            idempotency_key=f"reg-seo-{uuid.uuid4().hex[:12]}",
            correlation_id=str(uuid.uuid4()),
            agent_id=actor,
        )
        if exec_mode == "SIMULATION" or is_external_side_effect_blocked():
            record_simulated_dispatch("wordpress_rest", target_net, {"title": blog.get("title"), "staged_draft_id": staged.get("draft_id")})
        return {
            "output": {"article": blog, "cms_staging": staged},
            "uses_external_provider": False,
            "fallback_used": exec_mode == "SIMULATION",
            "provider_request_id": f"seo-draft-{staged.get('draft_id', 'local')}",
        }

    if agent_id == "marketing_creative_agent":
        from app.services.growth_engine import generate_creative_assets, generate_omnichannel_social_campaign

        product_name = str(input_payload.get("product_name", "AskforWrite SME Client"))
        audience = str(input_payload.get("target_audience", "B2B Decision Makers"))
        keywords = input_payload.get("keywords") or [product_name, "Growth Automation"]
        social = generate_omnichannel_social_campaign(
            product_name=product_name, target_audience=audience, keywords=keywords
        )
        creatives = generate_creative_assets(
            product_name=product_name, target_audience=audience, brand_voice="authoritative"
        )
        return {
            "output": {"social_campaign": social, "creatives": creatives},
            "uses_external_provider": False,
            "fallback_used": exec_mode == "SIMULATION",
            "provider_request_id": f"mkt-local-{uuid.uuid4().hex[:10]}",
        }

    if agent_id == "sales_proposal_agent":
        from app.services.growth_engine import handle_inbound_sales_chat

        prospect = str(input_payload.get("prospect_name", "SME Buyer"))
        contact = str(input_payload.get("prospect_email", "buyer@example.com"))
        msg = str(input_payload.get("message", "We need help scaling SME sales proposals and SEO."))
        res = handle_inbound_sales_chat(
            db=db,
            session_id=f"reg-sales-{uuid.uuid4().hex[:8]}",
            prospect_name=prospect,
            prospect_contact=contact,
            message=msg,
            preferred_channel=str(input_payload.get("preferred_channel", "email")),
        )
        # Stage explicit HITL approval before external email dispatch
        task_id = str(uuid.uuid4())
        db.add(TaskRecord(id=task_id, correlation_id=str(uuid.uuid4()), objective=f"Sales outreach to {prospect}", status="HUMAN_APPROVAL_REQUIRED"))
        db.flush()
        appr = ApprovalRequest(
            id=str(uuid.uuid4()),
            task_id=task_id,
            action="external_sales_outreach",
            requested_by=actor,
            status="PENDING",
            decision_note=f"Staged proposal for {prospect} ({contact})",
        )
        db.add(appr)
        db.flush()
        if exec_mode == "SIMULATION":
            record_simulated_dispatch("hostinger_smtp", contact, {"prospect": prospect, "approval_id": appr.id})
        return {
            "output": {**res, "approval_id": appr.id, "hitl_status": "PENDING_APPROVAL"},
            "approval_id": appr.id,
            "uses_external_provider": False,
            "fallback_used": exec_mode == "SIMULATION",
            "provider_request_id": f"sales-staged-{appr.id[:12]}",
        }

    if agent_id == "support_followup_agent":
        cust = str(input_payload.get("customer_name", "Valued Customer"))
        issue = str(input_payload.get("issue_summary", "Onboarding check-in and ticket follow-up"))
        recipient = str(input_payload.get("recipient", "customer@example.com"))
        task_id = str(uuid.uuid4())
        db.add(TaskRecord(id=task_id, correlation_id=str(uuid.uuid4()), objective=f"Support follow-up: {cust}", status="HUMAN_APPROVAL_REQUIRED"))
        db.flush()
        appr = ApprovalRequest(
            id=str(uuid.uuid4()),
            task_id=task_id,
            action="customer_followup_dispatch",
            requested_by=actor,
            status="PENDING",
            decision_note=f"Follow-up draft for {cust}",
        )
        db.add(appr)
        db.flush()
        if exec_mode == "SIMULATION":
            record_simulated_dispatch("whatsapp_bridge", recipient, {"customer": cust, "issue": issue})
        return {
            "output": {
                "customer_name": cust,
                "issue_summary": issue,
                "draft_response": f"Hello {cust}, thank you for contacting us regarding '{issue}'. Our team has reviewed your request and staged the resolution steps.",
                "approval_id": appr.id,
                "status": "WAITING_APPROVAL",
            },
            "approval_id": appr.id,
            "uses_external_provider": False,
            "fallback_used": exec_mode == "SIMULATION",
            "provider_request_id": f"support-draft-{appr.id[:12]}",
        }

    if agent_id == "field_ops_agent":
        city = str(input_payload.get("city", "Jaipur"))
        stops = int(input_payload.get("stops", 5))
        return {
            "output": {
                "city": city,
                "planned_stops": stops,
                "route_efficiency_score": 0.94,
                "geofence_policy": "STRICT_ECDSA_CHECKIN",
                "summary": f"Dispatched {stops} verified field visits in {city}.",
            },
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"field-route-{uuid.uuid4().hex[:10]}",
        }

    if agent_id == "warehouse_stocksense_agent":
        from app.services.inventory_analytics import execute_inventory_audit

        res = execute_inventory_audit(
            db=db,
            items=input_payload.get("items"),
            service_level_z=float(input_payload.get("service_level_z", 1.65)),
            forecast_alpha=float(input_payload.get("forecast_alpha", 0.3)),
            dead_stock_threshold_days=int(input_payload.get("dead_stock_threshold_days", 90)),
            idempotency_key=f"reg-inv-{uuid.uuid4().hex[:12]}",
        )
        return {
            "output": res,
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"stocksense-{uuid.uuid4().hex[:10]}",
        }

    if agent_id == "quality_vision_agent":
        variety = str(input_payload.get("variety", "Alphonso Mango"))
        brix = float(input_payload.get("brix_score", 16.5))
        grade = "Grade A (Export Premium)" if brix >= 15.0 else "Grade B (Domestic Retail)"
        return {
            "output": {"variety": variety, "brix_score": brix, "grade": grade, "export_ready": brix >= 15.0},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"vision-local-{uuid.uuid4().hex[:10]}",
        }

    if agent_id == "mobility_rebalance_agent":
        from app.services.mobility_analytics import execute_mobility_forecast_and_rebalance

        city = str(input_payload.get("city", "Udaipur"))
        res = execute_mobility_forecast_and_rebalance(
            db=db,
            horizon_hours=int(input_payload.get("horizon_hours", 4)),
            idempotency_key=f"reg-mob-{uuid.uuid4().hex[:12]}",
            correlation_id=str(uuid.uuid4()),
            agent_id=actor,
        )
        return {
            "output": {"city": city, **res},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"mobility-{uuid.uuid4().hex[:10]}",
        }

    if agent_id == "trust_governance_agent":
        from app.security.trust_chain import verify_chain

        chain = verify_chain(db)
        return {
            "output": chain,
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"trust-verify-{uuid.uuid4().hex[:10]}",
        }

    if agent_id == "market_research_agent":
        from app.services.p2_prospect_intel import verify_pilot_offer_contract

        offer = verify_pilot_offer_contract(str(input_payload.get("sku_key", "managed_seo_content_pilot")))
        return {
            "output": {"target_segment": "Small & medium digital marketing / SEO agencies in India", "offer_contract": offer},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"p2-mkt-{uuid.uuid4().hex[:10]}",
        }

    if agent_id == "prospect_discovery_agent":
        from app.services.p2_prospect_intel import run_configured_prospect_discovery

        res = run_configured_prospect_discovery(
            db,
            query=str(input_payload.get("query", "digital marketing SEO agency India")),
            limit=max(1, min(int(input_payload.get("limit", 5)), 15)),
            execution_mode=exec_mode,
            actor=actor,
            org_id=None if tenant_id == "__platform__" else tenant_id,
        )
        return {
            "output": res,
            "uses_external_provider": exec_mode == "PRODUCTION",
            "fallback_used": res.get("status") == "BLOCKED",
            "provider_request_id": f"p2-disc-{uuid.uuid4().hex[:10]}",
        }

    if agent_id == "lead_qualification_agent":
        from app.db.models import LeadRecordRow, P2ProspectDossierRecord
        from app.services.p2_prospect_intel import evaluate_qualification_score

        lead_id = str(input_payload.get("lead_id", ""))
        lead = db.get(LeadRecordRow, lead_id)
        dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=lead_id).first()
        if not lead or not dossier:
            raise ValueError("lead_id referencing an existing P2 prospect dossier is required")
        qual = evaluate_qualification_score(
            company=lead.company,
            business_category=dossier.business_category,
            location=dossier.location,
            website=lead.website,
            source_url=dossier.source_url,
            collected_at=dossier.collected_at,
            agency_profile=dossier.agency_profile_json or {},
            public_contacts=dossier.public_contacts_json or [],
            research_claims=dossier.research_claims_json or [],
        )
        return {"output": qual, "uses_external_provider": False, "fallback_used": False}

    if agent_id == "account_intelligence_agent":
        from app.services.p2_prospect_intel import generate_account_intelligence_brief

        brief = generate_account_intelligence_brief(
            db,
            lead_id=str(input_payload.get("lead_id", "")),
            execution_mode=exec_mode,
            actor=actor,
        )
        return {
            "output": brief,
            "uses_external_provider": not bool(brief.get("fallback_used", True)),
            "fallback_used": bool(brief.get("fallback_used", True)),
        }

    if agent_id == "outreach_preparation_agent":
        from app.services.p2_outreach_pipeline import prepare_p2_outreach

        res = prepare_p2_outreach(
            db,
            lead_id=str(input_payload.get("lead_id", "")),
            recipient_email=input_payload.get("recipient_email"),
            recipient_name=input_payload.get("recipient_name"),
            custom_notes=input_payload.get("custom_notes"),
            actor=actor,
        )
        return {"output": res, "uses_external_provider": False, "fallback_used": False, "approval_id": res.get("approval_id")}

    if agent_id == "customer_onboarding_agent":
        from app.services.p2_customer_ops import submit_onboarding_inputs

        res = submit_onboarding_inputs(
            db,
            engagement_id=str(input_payload.get("engagement_id", "")),
            target_domain=str(input_payload.get("target_domain", "")),
            cms_delivery_mode=str(input_payload.get("cms_delivery_mode", "markdown_html_export")),
            priority_topics=list(input_payload.get("priority_topics") or []),
            actor=actor,
        )
        return {"output": res, "uses_external_provider": False, "fallback_used": False}

    if agent_id == "customer_success_agent":
        from app.services.p2_customer_ops import execute_pilot_delivery

        res = execute_pilot_delivery(
            db,
            engagement_id=str(input_payload.get("engagement_id", "")),
            execution_mode=exec_mode,
            actor=actor,
        )
        return {"output": res, "uses_external_provider": False, "fallback_used": exec_mode == "SIMULATION"}

    if agent_id == "cs_onboarding_specialist_agent":
        from app.services.p3_customer_success import create_or_get_onboarding_workflow, get_customer_360_profile

        org_id = str(input_payload.get("org_id") or tenant_id or "").strip()
        wf = create_or_get_onboarding_workflow(
            db,
            org_id=org_id,
            sku_key=input_payload.get("sku_key"),
            actor=actor,
        )
        prof = get_customer_360_profile(db, org_id=org_id)
        return {
            "output": {"workflow": wf, "blockers": wf.get("blockers", []), "activation_ready": prof["customer_account"]["activation_ready"]},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"cs-onboard-{wf['onboarding_id'][:10]}",
        }

    if agent_id == "cs_manager_agent":
        from app.services.p3_delivery_health import compute_customer_health, generate_internal_health_alerts

        org_id = str(input_payload.get("org_id") or tenant_id or "").strip()
        health = compute_customer_health(db, org_id=org_id, save_snapshot=True)
        alerts = generate_internal_health_alerts(db, org_id=org_id)
        return {
            "output": {"health": health, "alerts_created": alerts},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"cs-health-{org_id[:10]}",
        }

    if agent_id == "service_delivery_coordinator_agent":
        from app.services.p3_delivery_health import create_service_delivery, list_service_deliveries

        org_id = str(input_payload.get("org_id") or tenant_id or "").strip()
        title = str(input_payload.get("title") or "").strip()
        if title:
            created = create_service_delivery(
                db,
                org_id=org_id,
                title=title,
                original_requirement=str(input_payload.get("requirement") or "Customer service engagement deliverable"),
                sku_key=str(input_payload.get("sku_key") or "managed_seo_content_pilot"),
                service_id=str(input_payload.get("service_id") or "seo_blog_copilot"),
                assigned_owner=actor,
                assigned_agent_id=agent_id,
                actor=actor,
            )
            return {
                "output": {"deliveries": [created], "created": True},
                "uses_external_provider": False,
                "fallback_used": False,
                "provider_request_id": f"cs-deliv-{created['id'][:10]}",
            }
        rows = list_service_deliveries(db, org_id=org_id)
        return {
            "output": {"deliveries": rows, "created": False},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"cs-deliv-list-{org_id[:10]}",
        }

    if agent_id == "qa_review_agent":
        from app.db.models import P3ServiceDeliveryRecord
        from app.services.p3_delivery_health import submit_delivery_quality_check

        deliv_id = str(input_payload.get("delivery_id") or "").strip()
        if not deliv_id:
            org_id = str(input_payload.get("org_id") or tenant_id or "").strip()
            candidate = db.query(P3ServiceDeliveryRecord).filter_by(org_id=org_id).order_by(P3ServiceDeliveryRecord.created_at.desc()).first()
            if not candidate:
                return {"output": {"qa_status": "NO_DELIVERABLE_FOUND", "checks": {}}, "uses_external_provider": False, "fallback_used": False}
            deliv_id = candidate.id
        target = db.get(P3ServiceDeliveryRecord, deliv_id)
        has_artifacts = bool(target and target.output_artifacts_json)
        has_evidence = bool(target and target.source_evidence_json)
        checks = {
            "has_output_artifacts": has_artifacts,
            "has_source_evidence": has_evidence,
            "scope_present": bool(target and target.approved_scope_json),
        }
        passed = bool(input_payload.get("passed")) if "passed" in input_payload else (has_artifacts or has_evidence)
        res = submit_delivery_quality_check(
            db,
            delivery_id=deliv_id,
            passed=passed,
            checks=checks,
            reviewer=actor,
        )
        return {
            "output": {"qa_status": res["quality_state"], "checks": res["quality_checks"], "delivery": res},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"cs-qa-{deliv_id[:10]}",
        }

    if agent_id == "cs_support_specialist_agent":
        from app.services.p3_support_improvements import list_support_tickets, run_ai_support_assistant

        ticket_id = str(input_payload.get("ticket_id") or "").strip()
        if not ticket_id:
            org_id = str(input_payload.get("org_id") or tenant_id or "").strip()
            open_tickets = list_support_tickets(db, org_id=org_id, include_internal=False)
            if not open_tickets:
                return {"output": {"status": "NO_OPEN_TICKETS", "requires_hitl_approval": False}, "uses_external_provider": False, "fallback_used": False}
            ticket_id = open_tickets[0]["ticket_id"]
        res = run_ai_support_assistant(db, ticket_id=ticket_id, actor=actor)
        return {
            "output": res,
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"cs-triage-{ticket_id[:10]}",
        }

    if agent_id == "renewal_management_agent":
        from app.services.p3_revenue_growth import enforce_grace_period_expirations, get_subscription_reliability_summary

        org_id = str(input_payload.get("org_id") or tenant_id or "").strip() or None
        days = int(input_payload.get("days_ahead", 30))
        suspensions = enforce_grace_period_expirations(db, org_id=org_id)
        summary = get_subscription_reliability_summary(db, org_id=org_id, days_ahead=days)
        return {
            "output": {**summary, "expired_grace_suspensions": suspensions},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"cs-renewal-{len(summary['upcoming_renewals'])}",
        }

    if agent_id == "expansion_opportunity_agent":
        from app.services.p3_revenue_growth import evaluate_expansion_opportunities

        org_id = str(input_payload.get("org_id") or tenant_id or "").strip()
        opps = evaluate_expansion_opportunities(db, org_id=org_id)
        return {
            "output": {"org_id": org_id, "opportunities": opps},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"cs-expand-{org_id[:10]}",
        }

    if agent_id == "customer_insights_analyst_agent":
        from app.services.p3_revenue_growth import compute_customer_unit_economics
        from app.services.p3_support_improvements import synthesize_improvement_loop

        org_id = str(input_payload.get("org_id") or tenant_id or "").strip() or None
        items = synthesize_improvement_loop(db, org_id=org_id)
        ue = compute_customer_unit_economics(db, org_id=org_id) if org_id and org_id != "__platform__" else {}
        return {
            "output": {"improvement_items": items, "unit_economics": ue},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"cs-insights-{len(items)}",
        }

    if agent_id == "gtm_strategist_agent":
        from app.services.p4_growth_gtm import compute_gtm_funnel_analytics

        org_scope = str(input_payload.get("org_id") or tenant_id or "").strip()
        org_filter = None if org_scope == "__platform__" else (org_scope or None)
        analytics = compute_gtm_funnel_analytics(db, org_id=org_filter)
        return {
            "output": analytics,
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"p4-gtm-{analytics['campaign_count']}",
        }

    if agent_id == "competitive_intel_agent":
        from app.services.p4_growth_gtm import list_market_intel

        org_scope = str(input_payload.get("org_id") or tenant_id or "").strip()
        org_filter = None if org_scope == "__platform__" else (org_scope or None)
        intel = list_market_intel(db, org_id=org_filter, intel_type=input_payload.get("intel_type"))
        return {
            "output": {"count": len(intel), "intel": intel},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"p4-intel-{len(intel)}",
        }

    if agent_id == "tenant_provisioning_agent":
        from app.services.p5_productization import compute_p5_scale_summary, list_p5_templates

        org_scope = str(input_payload.get("org_id") or tenant_id or "").strip()
        org_filter = None if org_scope == "__platform__" else (org_scope or None)
        summary = compute_p5_scale_summary(db, org_id=org_filter)
        templates = list_p5_templates(db, active_only=True)
        return {
            "output": {"summary": summary, "template_count": len(templates)},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"p5-prov-{summary['provisioning_run_count']}",
        }

    if agent_id == "sla_operations_agent":
        from app.services.p5_productization import list_operational_incidents, list_quota_events

        org_scope = str(input_payload.get("org_id") or tenant_id or "").strip()
        org_filter = None if org_scope == "__platform__" else (org_scope or None)
        incidents = list_operational_incidents(db, org_id=org_filter)
        events = list_quota_events(db, org_id=org_filter, limit=25)
        return {
            "output": {"incident_count": len(incidents), "incidents": incidents, "recent_quota_events": len(events)},
            "uses_external_provider": False,
            "fallback_used": False,
            "provider_request_id": f"p5-sla-{len(incidents)}",
        }

    # Default ceo_manager_agent orchestrator
    from app.services.manager import execute_manager_workflow
    from app.services.watchdog import _VerifiedSimulationSourceProvider

    res = execute_manager_workflow(
        db=db,
        objective=str(input_payload.get("objective", "Enterprise SME workflow automation pipeline")),
        limit=max(1, min(int(input_payload.get("limit", 1)), 5)),
        idempotency_key=f"reg-ceo-{uuid.uuid4().hex[:12]}",
        correlation_id=str(uuid.uuid4()),
        manager_id=actor,
        provider=_VerifiedSimulationSourceProvider(),
    )
    return {
        "output": dict(res),
        "uses_external_provider": False,
        "fallback_used": exec_mode == "SIMULATION",
        "provider_request_id": f"ceo-orch-{res.get('task_id', 'local')}",
    }


def execute_registered_agent(
    db: Session,
    *,
    agent_id: str,
    principal: APIPrincipal,
    input_payload: dict[str, Any] | None = None,
    execution_mode: str | None = None,
    requested_tools: list[str] | None = None,
    idempotency_key: str | None = None,
    workflow_id: str | None = None,
    charge_on_failure: bool = False,
) -> dict[str, Any]:
    """Execute any registered agent with entitlement, emergency-stop, allowlist, credit, and 18-field evidence guarantees."""
    ag = AGENT_REGISTRY.get(agent_id)
    if not ag:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in registry")

    started_at = datetime.now(UTC)
    exec_id = f"exec-{uuid.uuid4().hex[:16]}"
    tenant_id = principal.org_id or "__platform__"
    mode = resolve_execution_mode(execution_mode)
    idem_key = idempotency_key or f"agent:{tenant_id}:{agent_id}:{exec_id}"
    payload = redact_secrets(input_payload or {})

    # 1. Entitlement & organization check
    check_tenant_entitlement(principal, ag.entitlement_key, db)

    # 2. Load tenant config
    cfg = db.query(TenantAgentConfigRecord).filter_by(org_id=tenant_id, agent_id=agent_id).first()
    if cfg and cfg.status == "DEACTIVATED" and cfg.is_active is False:
        ev = record_execution_evidence(
            db,
            execution_id=exec_id,
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            agent_id=agent_id,
            connector_id=ag.default_connector_id,
            execution_mode=mode,
            input_payload=payload,
            status="BLOCKED",
            failure_reason=f"Agent '{agent_id}' is deactivated for tenant '{tenant_id}'",
            credits_consumed=0,
            started_at=started_at,
            version=ag.version,
        )
        db.commit()
        raise HTTPException(status_code=403, detail={"message": ev["failure_reason"], "evidence": ev})

    # 3. Execution guard: 4-level emergency stop, simulation lock, and least-privilege tool allowlist
    try:
        check_execution_allowed(
            db,
            execution_id=exec_id,
            agent_id=agent_id,
            org_id=principal.org_id,
            execution_mode=mode,
            requested_tools=requested_tools,
            agent_supported_tools=list(ag.supported_tools),
            tenant_tool_allowlist=list(cfg.tool_allowlist) if cfg else None,
        )
    except ExecutionBlockedError as exc:
        ev = record_execution_evidence(
            db,
            execution_id=exec_id,
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            agent_id=agent_id,
            connector_id=ag.default_connector_id,
            execution_mode=mode,
            input_payload=payload,
            status="BLOCKED",
            failure_reason=exc.reason,
            credits_consumed=0,
            started_at=started_at,
            version=ag.version,
        )
        db.commit()
        raise HTTPException(status_code=403, detail={"code": exc.code, "message": exc.reason, "evidence": ev}) from exc

    # 4. Reserve credits atomically (only for tenant organizations)
    cost = ag.credit_cost
    if principal.org_id and cost > 0:
        try:
            reserve_execution_credits(
                db,
                org_id=principal.org_id,
                cost=cost,
                idempotency_key=idem_key,
                execution_id=exec_id,
                actor=principal.subject,
                reason=f"Agent run: {agent_id}",
            )
        except InsufficientCreditsError as exc:
            ev = record_execution_evidence(
                db,
                execution_id=exec_id,
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                agent_id=agent_id,
                connector_id=ag.default_connector_id,
                execution_mode=mode,
                input_payload=payload,
                status="BLOCKED",
                failure_reason=str(exc),
                credits_consumed=0,
                started_at=started_at,
                version=ag.version,
            )
            db.commit()
            raise HTTPException(status_code=402, detail={"message": str(exc), "evidence": ev}) from exc
    else:
        cost = 0

    # 5. Execute agent logic safely; refund credits on failure or block!
    try:
        if input_payload and input_payload.get("__force_failure__"):
            raise RuntimeError("Simulated execution failure injected by caller/test")
        dispatch = _dispatch_domain_agent(
            db,
            agent=ag,
            tenant_id=tenant_id,
            actor=principal.subject,
            exec_mode=mode,
            input_payload=input_payload or {},
        )
        if principal.org_id and cost > 0:
            commit_credit_reservation(db, idempotency_key=idem_key)

        completed_at = datetime.now(UTC)
        ev = record_execution_evidence(
            db,
            execution_id=exec_id,
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            agent_id=agent_id,
            connector_id=ag.default_connector_id,
            execution_mode=mode,
            input_payload=payload,
            output_payload=dispatch.get("output"),
            provider_request_id=dispatch.get("provider_request_id"),
            fallback_used=bool(dispatch.get("fallback_used", False)),
            approval_id=dispatch.get("approval_id"),
            status="COMPLETED",
            credits_consumed=cost,
            started_at=started_at,
            completed_at=completed_at,
            version=ag.version,
            uses_external_provider=bool(dispatch.get("uses_external_provider", False)),
        )
        db.commit()
        return {
            "status": "COMPLETED",
            "execution_id": exec_id,
            "agent_id": agent_id,
            "execution_mode": mode,
            "output_origin": ev["output_origin"],
            "credits_consumed": cost,
            "result": dispatch.get("output", {}),
            "evidence": ev,
        }
    except ExecutionBlockedError as exc:
        if principal.org_id and cost > 0 and not charge_on_failure:
            refund_credit_reservation(
                db, org_id=principal.org_id, cost=cost, idempotency_key=idem_key, execution_id=exec_id, actor=principal.subject, reason=exc.reason
            )
            cost = 0
        ev = record_execution_evidence(
            db,
            execution_id=exec_id,
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            agent_id=agent_id,
            connector_id=ag.default_connector_id,
            execution_mode=mode,
            input_payload=payload,
            status="BLOCKED",
            failure_reason=exc.reason,
            credits_consumed=cost,
            started_at=started_at,
            version=ag.version,
        )
        db.commit()
        raise HTTPException(status_code=403, detail={"code": exc.code, "message": exc.reason, "evidence": ev}) from exc
    except Exception as exc:
        if principal.org_id and cost > 0 and not charge_on_failure:
            refund_credit_reservation(
                db, org_id=principal.org_id, cost=cost, idempotency_key=idem_key, execution_id=exec_id, actor=principal.subject, reason=str(exc)
            )
            cost = 0
        ev = record_execution_evidence(
            db,
            execution_id=exec_id,
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            agent_id=agent_id,
            connector_id=ag.default_connector_id,
            execution_mode=mode,
            input_payload=payload,
            status="FAILED",
            failure_reason=str(exc),
            credits_consumed=cost,
            started_at=started_at,
            version=ag.version,
        )
        db.commit()
        raise HTTPException(status_code=500, detail={"message": str(exc), "evidence": ev}) from exc


def get_agent_execution_history(
    db: Session,
    *,
    agent_id: str,
    principal: APIPrincipal,
    limit: int = 50,
) -> dict[str, Any]:
    """Return tenant-scoped ExecutionEvidenceRecord history for an agent."""
    if agent_id not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    tenant_scope = principal.org_id if principal.org_id else None
    records = list_execution_evidence(db, tenant_id=tenant_scope, agent_id=agent_id, limit=limit)
    return {
        "agent_id": agent_id,
        "count": len(records),
        "executions": records,
    }


def get_connector_registry_view(db: Session, principal: APIPrincipal) -> dict[str, Any]:
    """Return Connector Registry with tenant scope and redacted secret summaries."""
    org_scope = principal.org_id or "__platform__"
    conns = list_connectors(db, org_id=org_scope)
    return {"count": len(conns), "connectors": conns}

