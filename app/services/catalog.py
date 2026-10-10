"""Commercial product catalog and pricing matrix for AskforWrite Company AI OS.

Defines:
- Modular a-la-carte specialist tools (SEO Blog Copilot, Marketing Suite, Field Force, Trust Engine)
- All-in-One Master Bundles (AskforWrite Company OS Starter, Pro, Enterprise)
- Deep architectural capabilities: SEO, GEO (Generative Engine Optimization), AIO (AI Optimization)
- Concrete deliverables, target buyer personas, and operational advantages
- Payment link builders for Razorpay (INR) and PayPal (USD)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote_plus


@dataclass(frozen=True)
class PackageDefinition:
    key: str
    name: str
    category: Literal["modular_tool", "master_bundle"]
    description: str
    target_buyer_persona: str
    target_pain_point: str
    key_features: tuple[str, ...]
    deliverables: tuple[str, ...]
    seo_geo_aio_capabilities: tuple[str, ...]
    price_inr: int  # in Rupees
    price_usd: int  # in USD
    currency_default: str
    entitled_capabilities: tuple[str, ...]
    lead_credits_monthly: int
    outreach_credits_monthly: int
    tier: str


CATALOG: dict[str, PackageDefinition] = {
    "seo_blog_copilot": PackageDefinition(
        key="seo_blog_copilot",
        name="AskforWrite SEO Blog Copilot",
        category="modular_tool",
        description="Automated 4-site WordPress content generation, keyword optimization, and publishing pipeline with GEO & AIO readiness.",
        target_buyer_persona="Content agencies, affiliate media networks, publishing houses, and inbound marketing teams.",
        target_pain_point="Manual content creation bottlenecks, high freelance writer costs, and failure to rank in both traditional Google Search and Generative AI engines (ChatGPT, Perplexity).",
        key_features=(
            "4-Site WordPress REST API publishing bridge with automated category/tag taxonomy",
            "Generative Engine Optimization (GEO) structured for citation in Perplexity, SearchGPT, and Claude",
            "AI Optimization (AIO) using semantic heading trees, Schema.org JSON-LD, and entity clustering",
            "Automated internal linking engine and featured image prompt generator",
            "Human-in-the-Loop publishing gating with draft preview and 1-click owner approval",
        ),
        deliverables=(
            "Full access to 4 WordPress publishing pipeline endpoints",
            "Monthly quota of 30 qualified SEO leads with topical audit reports",
            "Direct API keys for programmatic article generation and draft ingestion",
            "Custom SEO/GEO audit scorecards for target domains",
        ),
        seo_geo_aio_capabilities=(
            "Topical authority mapping for high-intent transactional search terms",
            "AI answer engine citation formatting (clear answers, bulleted takeaways, FAQ markup)",
            "Schema.org Article, FAQPage, and Organization JSON-LD injection",
        ),
        price_inr=1999,
        price_usd=29,
        currency_default="INR",
        entitled_capabilities=("seo_content_automation",),
        lead_credits_monthly=30,
        outreach_credits_monthly=15,
        tier="modular_seo",
    ),
    "marketing_suite": PackageDefinition(
        key="marketing_suite",
        name="PixelBot Omnichannel Marketing Suite",
        category="modular_tool",
        description="Conversational ad copy, multi-channel social promotions, and marketing campaign automation.",
        target_buyer_persona="B2B SaaS companies, D2C e-commerce brands, performance marketing agencies, and growth consultants.",
        target_pain_point="Expensive marketing agency retainers, slow ad creative turnaround, low social engagement, and disconnected lead generation funnels.",
        key_features=(
            "PixelBot conversational sales agent with prompt engineering for omnichannel conversions",
            "Multi-channel ad copy generator for LinkedIn Ads, Meta Ads, and Google Search campaigns",
            "Automated email nurture sequences with personalized hooks and problem-agitate-solve formulas",
            "Audience segmentation based on firmographic signals and ICP qualification",
        ),
        deliverables=(
            "Instant ad copy variations for 3 major ad platforms per campaign",
            "50 monthly lead enrichment credits with social profile extraction",
            "Ready-to-deploy conversational chatbot embed snippet",
            "Exportable ad campaign bundles with A/B testing variations",
        ),
        seo_geo_aio_capabilities=(
            "Conversion-optimized landing page copy with high semantic relevance",
            "Social sharing OpenGraph / Twitter Cards optimization",
            "Entity-aligned promotional hooks matching high-volume organic search queries",
        ),
        price_inr=2999,
        price_usd=39,
        currency_default="INR",
        entitled_capabilities=("marketing_campaign_suite",),
        lead_credits_monthly=50,
        outreach_credits_monthly=25,
        tier="modular_marketing",
    ),
    "field_force": PackageDefinition(
        key="field_force",
        name="Field Force Workforce & GPS Automation",
        category="modular_tool",
        description="Supervisor workforce coordination, real-time verified readback, and GPS geofence tracking.",
        target_buyer_persona="Logistics operators, field sales distribution networks, construction and facilities management firms.",
        target_pain_point="Proxy field attendance, untracked remote workers, supervisor coordination delays, and inability to verify task execution on the ground.",
        key_features=(
            "Unolo Field Force microservice integration with verified task status readback",
            "Real-time GPS geofencing with location audit validation",
            "Automated supervisor notification triggers and task dispatching",
            "Fraud-proof timestamped field attendance logging",
        ),
        deliverables=(
            "Connected Field Force microservice dashboard access",
            "Field team activity and geofence compliance reporting",
            "50 monthly prospect discovery credits for regional logistics and retail chains",
            "Dedicated webhook endpoints for field status sync",
        ),
        seo_geo_aio_capabilities=(
            "Location-grounded local business schema markup",
            "Regional supply-chain and distribution directory optimization",
        ),
        price_inr=3999,
        price_usd=49,
        currency_default="INR",
        entitled_capabilities=("delivery_field_force",),
        lead_credits_monthly=50,
        outreach_credits_monthly=25,
        tier="modular_field_force",
    ),
    "trust_engine": PackageDefinition(
        key="trust_engine",
        name="AFW 2030 Cryptographic Trust Engine",
        category="modular_tool",
        description="ECDSA NIST P-256 Merkle DAG ledger for immutable operational audits and compliance verification.",
        target_buyer_persona="Regulated fintechs, health-tech providers, legal tech firms, and enterprises requiring verifiable AI governance.",
        target_pain_point="Unverifiable autonomous AI agent actions, regulatory compliance exposure, and risk of data tampering or disputed state transitions.",
        key_features=(
            "NIST P-256 ECDSA cryptographic block signing and Merkle DAG hashing",
            "Tamper-evident verification endpoint (/v1/trust/verify) for external auditors",
            "Full cryptographic state chaining for all tasks, approvals, and deliveries",
            "Genesis block provenance with cryptographic parent-hash anchoring",
        ),
        deliverables=(
            "Cryptographic proof-of-execution certificates for all operations",
            "Auditor-ready JSON export of verified Merkle blocks",
            "100 lead discovery credits targeting compliance and legal prospects",
            "Automated daily chain integrity diagnostic alerts",
        ),
        seo_geo_aio_capabilities=(
            "Cryptographic transparency metadata for verifiable web trust signals",
            "Institutional credibility and verifiable authenticity proof",
        ),
        price_inr=4999,
        price_usd=69,
        currency_default="INR",
        entitled_capabilities=("trust_ledger_audit",),
        lead_credits_monthly=100,
        outreach_credits_monthly=50,
        tier="modular_trust",
    ),
    "company_os_starter": PackageDefinition(
        key="company_os_starter",
        name="AskforWrite AI Company OS (Starter)",
        category="master_bundle",
        description="All 7 Specialist AI Agents, CEO Orchestrator, human-in-the-loop governance, and multi-tenant portal.",
        target_buyer_persona="Solo founders, boutique agency owners, and growing SMB operators looking to automate core operations.",
        target_pain_point="Overwhelmed by daily operations, juggling disconnected single-purpose tools, and lacking an integrated operating system for growth.",
        key_features=(
            "CEO / Manager Agent orchestrator coordinating 7 specialist agents",
            "Human-in-the-Loop (HITL) approval governance protecting all external outreach",
            "Live SEO, GEO, and AIO content generation pipeline",
            "Dual payment gateway (Razorpay INR + PayPal USD) auto-provisioning",
            "Cryptographic trust ledger audit trail for full transparency",
        ),
        deliverables=(
            "Dedicated multi-tenant Organization account with Admin & Member logins",
            "150 qualified lead discovery credits / month with live SEO domain enrichment",
            "75 approved email outreach dispatch credits / month via Hostinger SMTP",
            "Access to all 7 specialist agents and live status dashboard",
        ),
        seo_geo_aio_capabilities=(
            "Complete holistic SEO + GEO + AIO marketing engine across web, social, and search",
            "Organic domain ranking acceleration with entity-dense content trees",
            "Automated prospect website SEO gap analysis during sales discovery",
        ),
        price_inr=7999,
        price_usd=99,
        currency_default="INR",
        entitled_capabilities=(
            "customer_discovery",
            "evidence_research",
            "sales_proposal",
            "delivery_field_force",
            "trust_ledger_audit",
            "seo_content_automation",
            "marketing_campaign_suite",
        ),
        lead_credits_monthly=150,
        outreach_credits_monthly=75,
        tier="starter",
    ),
    "company_os_pro": PackageDefinition(
        key="company_os_pro",
        name="AskforWrite AI Company OS (Pro)",
        category="master_bundle",
        description="Autonomous AI Company OS with high-volume discovery, automated prospecting, and priority execution.",
        target_buyer_persona="Mid-market companies, scaling digital agencies, and B2B tech firms running multi-channel acquisition.",
        target_pain_point="Sales bottlenecks, manual prospect research slowing down deals, and high overhead costs managing separate SDR and marketing teams.",
        key_features=(
            "High-volume live web scraping & prospect enrichment with SEO gap identification",
            "Automated pitch generation with personalized pain diagnosis and embedded checkout links",
            "Priority task scheduling and parallel agent execution",
            "Multi-tenant team management with role-based access control",
        ),
        deliverables=(
            "600 lead discovery credits / month with deep tech stack and SEO profiling",
            "300 owner-gated outreach dispatch credits / month",
            "Dedicated webhook support for CRM and ERP sync",
            "Quarterly strategic capability review and custom prompt optimization",
        ),
        seo_geo_aio_capabilities=(
            "High-throughput publishing across multiple WordPress network properties",
            "Omnichannel GEO footprint across ChatGPT, Perplexity, and Claude answer engines",
            "Automated competitive SERP gap analysis for target sales verticals",
        ),
        price_inr=19999,
        price_usd=249,
        currency_default="INR",
        entitled_capabilities=(
            "customer_discovery",
            "evidence_research",
            "sales_proposal",
            "delivery_field_force",
            "trust_ledger_audit",
            "seo_content_automation",
            "marketing_campaign_suite",
        ),
        lead_credits_monthly=600,
        outreach_credits_monthly=300,
        tier="pro",
    ),
    "company_os_enterprise": PackageDefinition(
        key="company_os_enterprise",
        name="AskforWrite AI Company OS (Enterprise)",
        category="master_bundle",
        description="Bespoke private deployment, unlimited capability bridges, dedicated agent instances, and maximum quota.",
        target_buyer_persona="Enterprises, corporate holding companies, and regulated institutions requiring private cloud deployment.",
        target_pain_point="Stringent data privacy mandates, high operational complexity, and requiring bespoke integrations with existing legacy ERP/CRMs.",
        key_features=(
            "Private Docker / Kubernetes deployment support with PostgreSQL backend",
            "Dedicated LLM fallback routing (Gemini 2.0 / 3.0 + custom fine-tuned endpoints)",
            "Unlimited capability bridges and custom agent creation",
            "Cryptographic HSM / KMS hardware signing module integration",
        ),
        deliverables=(
            "5,000 monthly lead credits and 2,500 monthly outreach dispatch credits",
            "Custom SLA with dedicated 24/7 technical architect support",
            "Enterprise single sign-on (SSO) and custom data residency configuration",
            "Full source code access for internal audits and compliance validation",
        ),
        seo_geo_aio_capabilities=(
            "Enterprise-scale global SEO, GEO, and AIO brand defense architecture",
            "Cross-border multi-lingual content clusters and international search authority",
        ),
        price_inr=49999,
        price_usd=499,
        currency_default="INR",
        entitled_capabilities=(
            "customer_discovery",
            "evidence_research",
            "sales_proposal",
            "delivery_field_force",
            "trust_ledger_audit",
            "seo_content_automation",
            "marketing_campaign_suite",
        ),
        lead_credits_monthly=5000,
        outreach_credits_monthly=2500,
        tier="enterprise",
    ),
}


def get_all_packages() -> list[PackageDefinition]:
    """Return all commercial packages in the catalog."""
    return list(CATALOG.values())


def get_package(package_key: str) -> PackageDefinition | None:
    """Lookup a package by its catalog key."""
    return CATALOG.get(package_key)


def build_payment_link(
    package_key: str,
    customer_email: str | None = None,
    company: str | None = None,
    provider: str = "razorpay",
) -> str:
    """Build a direct payment / checkout URL for the specified package and provider."""
    pkg = get_package(package_key)
    if not pkg:
        pkg = CATALOG["company_os_starter"]

    prov = provider.lower().strip()
    if prov == "paypal":
        base_url = os.getenv("PAYPAL_PAYMENT_LINK", "https://paypal.me/ask4write")
        amount = pkg.price_usd
        note = f"{pkg.name} for {company or 'Client'}"
        return f"{base_url.rstrip('/')}/{amount}USD?memo={quote_plus(note)}"
    else:
        # Default to Razorpay
        base_url = os.getenv("RAZORPAY_PAYMENT_LINK", "https://razorpay.me/@askforwrite")
        amount = pkg.price_inr
        note = f"{pkg.name} for {company or 'Client'}"
        return f"{base_url.rstrip('/')}?amount={amount*100}&notes_package={pkg.key}&notes_company={quote_plus(company or '')}"
