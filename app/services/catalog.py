"""Commercial product catalog and pricing matrix for AskforWrite Company AI OS.

Defines:
- Modular a-la-carte specialist tools (SEO Blog Copilot, Marketing Suite, Field Operations Automation Suite, Trust Engine)
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
    category: Literal["modular_tool", "master_bundle", "b2c_one_off", "managed_pilot"]
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
        price_inr=2499,
        price_usd=35,
        currency_default="INR",
        entitled_capabilities=("marketing_campaign_suite", "pixel_ai_creative_studio"),
        lead_credits_monthly=50,
        outreach_credits_monthly=25,
        tier="modular_marketing",
    ),
    "field_force": PackageDefinition(
        key="field_force",
        name="AskforWrite FieldGuard — GPS Attendance, Tour & Conveyance Audit",
        category="modular_tool",
        description="Fraud-proof field workforce & business tour operations: anti-spoof GPS attendance, real Gemini Vision receipt OCR, perceptual duplicate receipt blocking, server-issued 6-digit Geo-OTP, configurable travel/hotel/DA policies, multi-day tour settlements, Tally XML / NEFT payout exports, and offline-first Mobile PWA.",
        target_buyer_persona="Distributors, FMCG/pharma field sales networks, service/AMC crews, and B2B teams managing employees on tour & travel.",
        target_pain_point="Proxy attendance fraud, inflated petrol/conveyance claims, duplicate bills, untracked tour advances, and slow manual payroll reconciliation.",
        key_features=(
            "Anti-spoofing GPS geofence attendance, teleportation velocity detection & stationary drift filtering",
            "Real Gemini Vision Receipt OCR (1 AI Credit) + exact SHA-256, perceptual dHash & invoice duplicate blocking",
            "Server-issued single-use 6-digit Geo-OTP + real Pillow photo EXIF/blur forensics",
            "Per-org & grade travel policies (2W/4W/Transit rates, Tier-1/2/3 DA & hotel caps) + multi-day tour settlement vouchers",
            "Append-only ECDSA manager review queue (APPROVE/PARTIAL/REJECT) + 1-click CSV, Tally XML & ICICI/HDFC NEFT exports",
            "Installable offline-first FieldGuard Mobile PWA (/mobile/) with IndexedDB sync queue & live camera capture",
        ),
        deliverables=(
            "FieldGuard operations dashboard, REST API & installable offline-first Mobile PWA (/mobile/)",
            "Cryptographically sealed attendance logs, tour settlement vouchers & manager claim review queue",
            "1-click monthly Tally XML, CSV & ICICI/HDFC NEFT bulk reimbursement exports with SHA-256 batch digest",
        ),
        seo_geo_aio_capabilities=(
            "Location-grounded local business schema markup",
            "Regional distribution & field service operational transparency",
        ),
        price_inr=3999,
        price_usd=49,
        currency_default="INR",
        entitled_capabilities=("delivery_field_force", "field_force_automation", "trust_ledger_audit"),
        lead_credits_monthly=50,
        outreach_credits_monthly=25,
        tier="modular_field_ops",
    ),
    "trust_engine": PackageDefinition(
        key="trust_engine",
        name="AskforWrite Cryptographic Audit Chain & Verification Receipts",
        category="modular_tool",
        description="Embedded ECDSA NIST P-256 tamper-evident SHA-256 linear hash-chain for verifiable Digital QA human-review receipts, field attendance proofs, and warehouse cycle-count audits.",
        target_buyer_persona="Digital agencies, B2B content teams, distributors, and SME warehouse operators requiring tamper-evident client delivery and internal audit receipts.",
        target_pain_point="Client skepticism toward AI-generated deliverables, disputed editorial reviews, and mutable operational logs.",
        key_features=(
            "NIST P-256 ECDSA digital signatures with sequential SHA-256 linear hash-chaining",
            "Public verification endpoint (/v1/trust/verify & /v1/digital-qa/receipts/{receipt_id}) for client sign-off",
            "Full tamper-evident state chaining across Digital QA approvals, payments, and operations",
            "Genesis block provenance with sequential parent-hash anchoring",
        ),
        deliverables=(
            "Signed Digital QA & human-review delivery certificates for client agencies",
            "Auditor-ready JSON export of verified hash-chain blocks",
            "Automated chain integrity diagnostic verification",
        ),
        seo_geo_aio_capabilities=(
            "Verifiable editorial provenance signals for client trust",
            "Structured review-receipt metadata",
        ),
        price_inr=3999,
        price_usd=49,
        currency_default="INR",
        entitled_capabilities=("trust_ledger_audit", "digital_qa"),
        lead_credits_monthly=50,
        outreach_credits_monthly=25,
        tier="modular_trust",
    ),
    "warehouse_automation": PackageDefinition(
        key="warehouse_automation",
        name="AskforWrite StockSense — SME Warehouse & 3PL OS (Phase 3 Design Partner)",
        category="modular_tool",
        description="Inventory analytics (Pareto ABC-XYZ, dynamic ROP/EOQ, dead-stock risk) evolving into a persistent multi-tenant SME Warehouse & 3PL Operations OS. (Phase 3 Design Partner Early Access).",
        target_buyer_persona="SME warehouse operators (5,000–100,000 sq ft), distributors, and regional 3PL fulfillment providers moving off Excel and manual Tally sheets.",
        target_pain_point="Stockouts on Class-A items, capital locked in dead stock, manual GRN/pick errors, and unbilled 3PL storage/handling fees.",
        key_features=(
            "Pareto ABC-XYZ classification & exact normal-CDF service-level ROP/EOQ calculations",
            "Dead-stock aging and locked-capital risk scoring (>90 days low velocity alerts)",
            "ECDSA NIST P-256 linear hash-chain stocktake audit sealing",
            "Phase 3 roadmap: Persistent bin/lot ledger, GRN/Putaway/FEFO wave picking, phone barcode PWA & 3PL client billing",
        ),
        deliverables=(
            "Programmatic inventory analytics & replenishment recommendation API endpoints",
            "Dead-stock liquidation and replenishment priority reports",
            "Design-partner onboarding slot for Phase 3 persistent WMS & 3PL rollout",
        ),
        seo_geo_aio_capabilities=(
            "Smart SME warehousing and regional 3PL fulfillment schema optimization",
        ),
        price_inr=3999,
        price_usd=49,
        currency_default="INR",
        entitled_capabilities=("inventory_analytics", "warehouse_automation", "trust_ledger_audit"),
        lead_credits_monthly=50,
        outreach_credits_monthly=25,
        tier="modular_inventory_ai",
    ),
    "ai_credits_100": PackageDefinition(
        key="ai_credits_100",
        name="AskforWrite Managed AI Credits Top-Up (100 Credits)",
        category="b2c_one_off",
        description="Prepaid pack of 100 Managed AI Execution Credits (approx. 10 full SEO/GEO + Digital QA articles or 100 OCR/vision checks) with zero BYOK key setup.",
        target_buyer_persona="Active AskforWrite OS subscribers needing additional monthly AI execution capacity.",
        target_pain_point="Running out of included monthly AI credits mid-campaign without wanting to manage external cloud LLM billing.",
        key_features=(
            "Instant +100 AI Credits credited atomically to organization ai_credits pool",
            "Zero canned fallback text — live managed Gemini execution with automatic refund on API failure",
            "Full token & INR cost telemetry inside Execution Evidence ledger",
        ),
        deliverables=("+100 Managed AI Credits added to organization balance",),
        seo_geo_aio_capabilities=("Powers live SEO/GEO generation and Digital QA benchmarking",),
        price_inr=499,
        price_usd=7,
        currency_default="INR",
        entitled_capabilities=("ai_credit_topup",),
        lead_credits_monthly=0,
        outreach_credits_monthly=0,
        tier="credit_pack",
    ),
    "ai_credits_500": PackageDefinition(
        key="ai_credits_500",
        name="AskforWrite Managed AI Credits Top-Up (500 Credits)",
        category="b2c_one_off",
        description="Prepaid pack of 500 Managed AI Execution Credits for growing agencies and multi-site publishing teams.",
        target_buyer_persona="Digital agencies and growth teams running high-volume SEO, Digital QA, and marketing operations.",
        target_pain_point="Scaling live AI content and verification volume predictably without API billing surprises.",
        key_features=(
            "Instant +500 AI Credits credited atomically to organization ai_credits pool",
            "20% volume savings vs Starter 100-credit pack",
        ),
        deliverables=("+500 Managed AI Credits added to organization balance",),
        seo_geo_aio_capabilities=("Powers high-volume live SEO/GEO and Digital QA pipelines",),
        price_inr=1999,
        price_usd=25,
        currency_default="INR",
        entitled_capabilities=("ai_credit_topup",),
        lead_credits_monthly=0,
        outreach_credits_monthly=0,
        tier="credit_pack",
    ),
    "ai_credits_2000": PackageDefinition(
        key="ai_credits_2000",
        name="AskforWrite Managed AI Credits Top-Up (2,000 Credits)",
        category="b2c_one_off",
        description="Scale prepaid pack of 2,000 Managed AI Execution Credits for high-volume agency & multi-department Company OS operations.",
        target_buyer_persona="Scaling agencies and multi-branch SMEs running daily SEO, Digital QA, and FieldGuard OCR.",
        target_pain_point="Minimizing per-execution unit cost while retaining managed reliability and spend caps.",
        key_features=(
            "Instant +2,000 AI Credits credited atomically to organization ai_credits pool",
            "35% volume savings vs Starter 100-credit pack",
        ),
        deliverables=("+2,000 Managed AI Credits added to organization balance",),
        seo_geo_aio_capabilities=("Enterprise-volume live SEO/GEO and Digital QA execution",),
        price_inr=6499,
        price_usd=79,
        currency_default="INR",
        entitled_capabilities=("ai_credit_topup",),
        lead_credits_monthly=0,
        outreach_credits_monthly=0,
        tier="credit_pack",
    ),
    "ask4_academic_order": PackageDefinition(
        key="ask4_academic_order",
        name="AskforWrite ASK4 Academic Research & Order Fulfillment (Single)",
        category="b2c_one_off",
        description="One-time comprehensive academic research report, structured bibliography, and verified thesis literature analysis.",
        target_buyer_persona="Postgraduate students, researchers, academic fellows, and scholarly authors.",
        target_pain_point="Time constraints, difficulty synthesizing multi-disciplinary academic sources, and formatting citations.",
        key_features=(
            "Deep scholarly literature retrieval across arXiv, bioRxiv, PubMed, and Europe PMC",
            "Formal academic citation formatting (APA, IEEE, Harvard)",
            "NIST P-256 Tamper-Evident Linear Hash-Chain academic integrity cryptographic certification",
        ),
        deliverables=(
            "Full academic synthesis report (PDF & Markdown)",
            "Structured citation bibtex database",
            "Cryptographic proof of original computation",
        ),
        seo_geo_aio_capabilities=(
            "Academic schema.org ScholarlyArticle metadata",
        ),
        price_inr=999,
        price_usd=15,
        currency_default="INR",
        entitled_capabilities=("askforwrite_academic_ask4", "academic_research", "trust_ledger_audit"),
        lead_credits_monthly=0,
        outreach_credits_monthly=0,
        tier="b2c_single_order",
    ),
    "pixel_ai_pack": PackageDefinition(
        key="pixel_ai_pack",
        name="AskforWrite Pixel AI Visual Creative Pack (20 Visuals)",
        category="b2c_one_off",
        description="20 high-converting advertising visual creatives across 1:1, 9:16, 16:9, and 4:5 aspect ratios for social media and display campaigns.",
        target_buyer_persona="D2C brands, social media marketers, and solo creators needing fast high-impact ad creatives.",
        target_pain_point="High graphic designer costs, slow revision turnarounds, and inconsistent multi-platform aspect ratio sizing.",
        key_features=(
            "20 tailored visual prompts with headline overlays and call-to-action badges",
            "Omnichannel aspect ratio variants (Instagram Feed, Story/Reel, LinkedIn, Display)",
            "NIST P-256 cryptographic provenance sealing",
        ),
        deliverables=(
            "20 downloadable ad creative assets and prompt recipes",
            "Instant campaign launch kit",
        ),
        seo_geo_aio_capabilities=(
            "Visual asset schema metadata for Google Image & Social SEO",
        ),
        price_inr=1499,
        price_usd=19,
        currency_default="INR",
        entitled_capabilities=("pixel_ai_pack", "pixel_ai_studio", "marketing_content_generation"),
        lead_credits_monthly=0,
        outreach_credits_monthly=0,
        tier="b2c_single_pack",
    ),
    "managed_seo_content_pilot": PackageDefinition(
        key="managed_seo_content_pilot",
        name="AskforWrite Managed SEO, Content & Digital QA Pilot (14-Day)",
        category="managed_pilot",
        description="14-Day Done-For-You Managed SEO & Digital QA Pilot: 1 technical SEO/GEO audit, 1 commercial keyword cluster, 2 live-LLM human-reviewed articles benchmarked against your Digital QA Brand Protocol, Schema.org JSON-LD, and a signed ECDSA Human-Review Receipt.",
        target_buyer_persona="B2B founders, digital/SEO agencies, and marketing leaders needing anti-slop, audit-verified content delivered directly to their CMS.",
        target_pain_point="AI-content liability, generic boilerplate from freelance writers or unverified tools, and lack of client-shareable proof of human editorial review.",
        key_features=(
            "1 In-depth technical SEO & Generative Engine Optimization (GEO) audit report for target domain",
            "1 High-intent commercial keyword cluster map with competitor gap analysis",
            "2 Comprehensive, live-LLM human-reviewed articles (1,500+ words each) gated by Digital Asset & Content QA Benchmark",
            "Configurable brand voice & anti-slop protocol (forbidden terms, claim verification, Schema.org JSON-LD validation)",
            "Signed ECDSA NIST P-256 Human-Review QA Receipt shareable with agency clients",
        ),
        deliverables=(
            "1 Comprehensive Technical SEO & GEO Gap Audit (PDF & Markdown)",
            "1 High-Intent Keyword Cluster & Content Plan",
            "2 Publication-ready authoritative articles delivered to client CMS as reviewed drafts",
            "2 Signed Digital QA & Human-Review Verification Receipts (publicly verifiable via /v1/digital-qa/receipts/{id})",
            "Projected ROI metrics are benchmark-based estimates, not guaranteed financial returns",
        ),
        seo_geo_aio_capabilities=(
            "Direct Perplexity & ChatGPT citation formatting with semantic entity grounding",
            "Complete Schema.org structured data graph injection",
            "Configurable Digital QA anti-slop protocol gate with human claim verification",
        ),
        price_inr=4999,
        price_usd=59,
        currency_default="INR",
        entitled_capabilities=(
            "seo_content_automation",
            "digital_qa",
            "evidence_research",
            "trust_ledger_audit",
        ),
        lead_credits_monthly=50,
        outreach_credits_monthly=25,
        tier="managed_pilot",
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
        price_inr=2999,
        price_usd=39,
        currency_default="INR",
        entitled_capabilities=(
            "seo_content_automation",
            "marketing_campaign_suite",
            "pixel_ai_creative_studio",
            "pixel_ai_pack",
            "wordpress_publisher",
            "evidence_research",
            "trust_ledger_audit",
        ),
        lead_credits_monthly=50,
        outreach_credits_monthly=25,
        tier="launch",
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
        price_inr=17999,
        price_usd=229,
        currency_default="INR",
        entitled_capabilities=(
            "customer_discovery",
            "evidence_research",
            "sales_proposal",
            "inbound_sales_closer",
            "support_followup",
            "delivery_field_force",
            "field_force_automation",
            "warehouse_automation",
            "inventory_analytics",
            "digital_qa",
            "trust_ledger_audit",
            "seo_content_automation",
            "marketing_campaign_suite",
            "pixel_ai_creative_studio",
            "growth_suite",
        ),
        lead_credits_monthly=1200,
        outreach_credits_monthly=600,
        tier="business_pro",
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
        price_inr=44999,
        price_usd=549,
        currency_default="INR",
        entitled_capabilities=(
            "all_access",
            "customer_discovery",
            "evidence_research",
            "sales_proposal",
            "inbound_sales_closer",
            "support_followup",
            "delivery_field_force",
            "field_force_automation",
            "trust_ledger_audit",
            "seo_content_automation",
            "marketing_campaign_suite",
            "pixel_ai_creative_studio",
            "growth_suite",
            "warehouse_automation",
            "inventory_analytics",
            "digital_qa",
            "ask4_academic_order",
            "pixel_ai_pack",
        ),
        lead_credits_monthly=5000,
        outreach_credits_monthly=2500,
        tier="enterprise",
    ),
    "growth_all_in_one": PackageDefinition(
        key="growth_all_in_one",
        name="AskforWrite Autonomous AI Growth & Inbound Sales Suite",
        category="master_bundle",
        description="All-in-one AI Growth & Revenue Suite: Pixel AI Creative Studio prompt specifications, 4-Site SEO Blog Copilot with HITL WordPress publishing, Omnichannel Campaign copy scripts, and Inbound Sales Closer conversation logic.",
        target_buyer_persona="Solo founders, D2C e-commerce brands, SMB service businesses, and scaling agencies wanting full-funnel creative, SEO, and sales closing workflows.",
        target_pain_point="Juggling expensive design tools, slow content writers, fragmented ad tools, and losing inbound leads on WhatsApp/chat due to slow human response times.",
        key_features=(
            "Pixel AI Creative Studio: Structured prompt recipes, visual composition blueprints, and multi-aspect prompt specs (1:1, 9:16, 16:9) ready for external diffusion rendering",
            "4-Site SEO & GEO Blog Copilot: Entity-dense topical authority publishing structured for Google SERPs, ChatGPT, and Perplexity with human-in-the-loop review gating",
            "Omnichannel Marketing Engine: Tailored ad copy scripts for Meta Ads, Google Search, LinkedIn, and social media posting schedules",
            "Inbound Sales Closer: Conversational objection handling and payment link generation with webhook integration ready for WhatsApp/web chat bridges",
            "ECDSA NIST P-256 tamper-evident hash-chain audit trail certifying lead conversions and state transitions",
        ),
        deliverables=(
            "Full access to Pixel AI Creative Studio & prompt composition engine",
            "WordPress SEO publishing bridge with Schema.org JSON-LD and HITL approval gating",
            "Inbound Sales Closer webhook endpoints for WhatsApp and Web Chat bridges",
            "350 qualified lead discovery credits / month with tech-stack profiling",
            "175 approved outreach & closing dispatch credits / month",
            "Projected ROI metrics are benchmark-based estimates, not guaranteed financial returns",
        ),
        seo_geo_aio_capabilities=(
            "Full-funnel Generative Engine Optimization (GEO) structured for citation in SearchGPT, Perplexity, and Claude",
            "Product & visual entity clustering with Schema.org Product, Article, and Organization JSON-LD",
            "Conversion-focused conversational sales scripting aligned with search intent",
        ),
        price_inr=6999,
        price_usd=89,
        currency_default="INR",
        entitled_capabilities=(
            "pixel_ai_creative_studio",
            "pixel_ai_pack",
            "seo_content_automation",
            "wordpress_publisher",
            "marketing_campaign_suite",
            "growth_suite",
            "growth_all_in_one",
            "customer_discovery",
            "evidence_research",
            "sales_proposal",
            "inbound_sales_closer",
            "support_followup",
            "trust_ledger_audit",
        ),
        lead_credits_monthly=300,
        outreach_credits_monthly=150,
        tier="growth",
    ),
    "operations_suite": PackageDefinition(
        key="operations_suite",
        name="AskforWrite Operations — FieldGuard & StockSense Warehouse Suite (Phase 2/3)",
        category="master_bundle",
        description="Cluster 3 + Cluster 4 Audit Chain: FieldGuard GPS Attendance, Tour & Conveyance Audit (Phase 2 Beta) + StockSense SME Warehouse & 3PL OS (Phase 3 Design Partner) backed by ECDSA NIST P-256 audit proofs.",
        target_buyer_persona="Distributors, FMCG/pharma field sales networks, SME warehouses (5k–100k sq ft), and regional 3PL fulfillment operators.",
        target_pain_point="Paying separately for disconnected field tracking apps and warehouse spreadsheets with zero tamper-evident attendance, conveyance, or stocktake auditability.",
        key_features=(
            "FieldGuard GPS & Tour Ops (Phase 2 Beta): Anti-spoof GPS attendance, beat routing, visit verification & conveyance claim auditing",
            "StockSense SME Warehouse & 3PL (Phase 3 Design Partner): Pareto ABC-XYZ, ROP/EOQ, dead-stock alerts & persistent WMS roadmap",
            "ECDSA NIST P-256 tamper-evident hash-chain sealing every visit, claim, and inventory audit",
        ),
        deliverables=(
            "FieldGuard & StockSense workspaces unlocked in the Customer Portal and REST API",
            "200 lead discovery credits & 100 outreach credits / month + 800 Managed AI Credits",
            "6 specialist agents & 10 team seats with ERP/Tally export readiness",
        ),
        seo_geo_aio_capabilities=(
            "Tamper-evident ECDSA operational SLA proof certificates for B2B buyers",
        ),
        price_inr=9999,
        price_usd=129,
        currency_default="INR",
        entitled_capabilities=(
            "warehouse_automation",
            "inventory_analytics",
            "warehouse_stocksense",
            "delivery_field_force",
            "field_force_automation",
            "digital_qa",
            "trust_ledger_audit",
        ),
        lead_credits_monthly=200,
        outreach_credits_monthly=100,
        tier="operations",
    ),
    "all_access": PackageDefinition(
        key="all_access",
        name="AskforWrite Company OS All-Access Master Suite",
        category="master_bundle",
        description="Complete unrestricted enterprise access to AskforWrite Company OS: SEO/GEO & Digital QA, Growth & Sniper Outbound, FieldGuard Tour/GPS Ops, StockSense Warehouse/3PL, and ECDSA Audit Chain.",
        target_buyer_persona="Multi-department B2B companies and scaling agencies wanting unified growth, content QA, field operations, and warehouse governance.",
        target_pain_point="Multi-divisional operational fragmentation across content/growth, on-ground field teams, and warehousing.",
        key_features=(
            "Full access to every AskforWrite OS capability and master bundle workflow",
            "Dedicated private deployment option and enterprise SLA guarantees",
            "High-volume Managed AI Credits plus optional zero-credit BYOK key support",
        ),
        deliverables=(
            "Unrestricted enterprise API key access",
            "Dedicated account architect and quarterly calibration",
            "All core OS engines enabled out-of-the-box",
        ),
        seo_geo_aio_capabilities=(
            "Complete omni-platform search, Digital QA, and answer engine optimization",
        ),
        price_inr=44999,
        price_usd=549,
        currency_default="INR",
        entitled_capabilities=(
            "customer_discovery",
            "evidence_research",
            "sales_proposal",
            "delivery_field_force",
            "field_force_automation",
            "trust_ledger_audit",
            "seo_content_automation",
            "digital_qa",
            "marketing_campaign_suite",
            "warehouse_automation",
            "inventory_analytics",
            "ask4_academic_order",
            "pixel_ai_pack",
            "inbound_sales_closer",
        ),
        lead_credits_monthly=10000,
        outreach_credits_monthly=5000,
        tier="all_access",
    ),
}


def get_all_packages() -> list[PackageDefinition]:
    """Return all commercial packages in the catalog."""
    return list(CATALOG.values())


def get_package(package_key: str) -> PackageDefinition | None:
    """Lookup a package by its catalog key or tier alias."""
    if not package_key:
        return None
    pkg = CATALOG.get(package_key)
    if pkg:
        return pkg
    alias_map = {
        "launch": "company_os_starter",
        "starter": "company_os_starter",
        "growth": "growth_all_in_one",
        "operations": "operations_suite",
        "business_pro": "company_os_pro",
        "pro": "company_os_pro",
        "professional": "company_os_pro",
        "enterprise": "company_os_enterprise",
        "managed_pilot": "managed_seo_content_pilot",
        "pilot": "managed_seo_content_pilot",
    }
    target_key = alias_map.get(package_key.lower().strip())
    if target_key:
        return CATALOG.get(target_key)
    for p in CATALOG.values():
        if p.tier.lower() == package_key.lower().strip():
            return p
    return None


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
    if prov in ("afw_directpay", "sovereign_pay", "directpay", "sovereign_direct"):
        base_url = os.getenv("AFW_DIRECTPAY_URL", "https://os.askforwrite.com/v1/pay/checkout")
        comp = quote_plus(company or "")
        return f"{base_url}?package={pkg.key}&company={comp}"
    elif prov == "paypal":
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


# ═══════════════════════════════════════════════════════════════════════════════
# Unified SME Business OS — Modular Subscription & 13-Field Pricing Contracts
# ═══════════════════════════════════════════════════════════════════════════════

PRICING_CLUSTERS: dict[str, dict[str, object]] = {
    "content_creative": {
        "cluster_key": "content_creative",
        "cluster_number": 1,
        "name": "Cluster 1: Content, SEO & Creative Studio",
        "tagline": "SEO/GEO blogs, 4-site WordPress publishing, Pixel AI ad specs, 7-channel social copy & ASK4 research.",
        "standalone_monthly_inr": 2999,
        "standalone_monthly_usd": 39,
        "services": [
            "seo_blog_copilot",
            "wordpress_publisher",
            "pixel_ai_pack",
            "marketing_suite",
            "ask4_academic_order",
        ],
        "modules": ["seo", "marketing"],
        "entry_packs": ["ask4_academic_order", "pixel_ai_pack", "managed_seo_content_pilot"],
    },
    "sales_closer": {
        "cluster_key": "sales_closer",
        "cluster_number": 2,
        "name": "Cluster 2: Sales, Lead Discovery & AI Closer",
        "tagline": "Live SMB discovery, Opportunity Gap Scanner, evidence briefs, 24/7 WhatsApp/Web closer & follow-ups.",
        "standalone_monthly_inr": 3499,
        "standalone_monthly_usd": 45,
        "services": [
            "lead_discovery",
            "evidence_research",
            "sales_capture",
            "support_followup",
        ],
        "modules": ["sales"],
        "entry_packs": [],
    },
    "operations_vertical_ai": {
        "cluster_key": "operations_vertical_ai",
        "cluster_number": 3,
        "name": "Cluster 3: FieldGuard GPS/Tour Ops & StockSense Warehouse/3PL (Phase 2/3)",
        "tagline": "FieldGuard GPS Attendance & Conveyance Audit (Phase 2 Beta) and StockSense SME Warehouse & 3PL OS (Phase 3 Design Partner).",
        "standalone_monthly_inr": 9999,
        "standalone_monthly_usd": 129,
        "per_tool_monthly_inr": 3999,
        "per_tool_monthly_usd": 49,
        "services": [
            "warehouse_automation",
            "field_force",
        ],
        "modules": ["inventory", "field_force", "customer_ops"],
        "entry_packs": [],
    },
    "governance_scale": {
        "cluster_key": "governance_scale",
        "cluster_number": 4,
        "name": "Cluster 4: Digital QA, Audit Chain & Managed AI Credits",
        "tagline": "Digital Asset & Content QA Benchmark, ECDSA NIST P-256 Linear Hash-Chain, HITL approval gates & Managed AI Credits.",
        "standalone_monthly_inr": 3999,
        "standalone_monthly_usd": 49,
        "services": [
            "trust_engine",
        ],
        "modules": ["customer_ops"],
        "entry_packs": ["ai_credits_100", "ai_credits_500", "ai_credits_2000"],
    },
}

MODULAR_SERVICE_MODULES: dict[str, dict[str, object]] = {
    "seo": {
        "module_key": "seo",
        "cluster_key": "content_creative",
        "name": "SEO, GEO, Digital QA & WordPress Publishing Module",
        "monthly_price_inr": 1999,
        "monthly_price_usd": 29,
        "agents": ["seo_geo_copilot_agent", "digital_qa_agent"],
        "capabilities": ["seo_content_automation", "digital_qa", "wordpress_publisher", "managed_seo_content_pilot"],
    },
    "marketing": {
        "module_key": "marketing",
        "cluster_key": "content_creative",
        "name": "Marketing & Pixel AI Creative Studio Module",
        "monthly_price_inr": 2499,
        "monthly_price_usd": 35,
        "agents": ["pixelbot_marketing_agent"],
        "capabilities": ["marketing_campaign_suite", "pixel_ai_creative_studio", "pixel_ai_pack"],
    },
    "sales": {
        "module_key": "sales",
        "cluster_key": "sales_closer",
        "name": "Sales, Lead Discovery & 10/Day Sniper Outbound Module",
        "monthly_price_inr": 3499,
        "monthly_price_usd": 45,
        "agents": ["discovery_sdr_agent", "sales_closer_agent", "evidence_research_agent"],
        "capabilities": ["customer_discovery", "evidence_research", "sales_proposal", "inbound_sales_closer", "support_followup"],
    },
    "inventory": {
        "module_key": "inventory",
        "cluster_key": "operations_vertical_ai",
        "name": "StockSense SME Warehouse & 3PL Module (Phase 3 Design Partner)",
        "monthly_price_inr": 3999,
        "monthly_price_usd": 49,
        "agents": ["warehouse_automation"],
        "capabilities": ["warehouse_automation", "inventory_analytics"],
    },
    "field_force": {
        "module_key": "field_force",
        "cluster_key": "operations_vertical_ai",
        "name": "FieldGuard GPS, Tour & Conveyance Audit Module (Phase 2 Beta)",
        "monthly_price_inr": 3999,
        "monthly_price_usd": 49,
        "agents": ["field_ops_dispatcher_agent"],
        "capabilities": ["delivery_field_force", "field_force_automation"],
    },
    "customer_ops": {
        "module_key": "customer_ops",
        "cluster_key": "governance_scale",
        "name": "Digital QA Verification, Compliance & ECDSA Audit Chain Module",
        "monthly_price_inr": 3499,
        "monthly_price_usd": 45,
        "agents": ["watchdog_supervisor_agent", "shift_scheduler_agent", "digital_qa_agent"],
        "capabilities": ["trust_ledger_audit", "digital_qa"],
    },
}

MODULAR_SME_TIERS: dict[str, dict[str, object]] = {
    "launch": {
        "tier_key": "launch",
        "name": "Launch — Content, SEO & Creative Studio",
        "target_sme": "Solo founders, creators & local SMBs",
        "included_clusters": ["content_creative"],
        "base_price": {"inr": 2999, "usd": 39},
        "annual_price": {"inr": 2399, "usd": 31, "discount_pct": 20},
        "included_modules": ["seo", "marketing"],
        "agent_limit": 2,
        "seat_limit": 2,
        "included_credits": {"lead_credits": 50, "outreach_credits": 25, "ai_execution_credits": 150},
        "support_level": "standard_sla",
        "customization_allowance": "standard_templates",
    },
    "growth": {
        "tier_key": "growth",
        "name": "Growth Suite — Sales & Marketing OS",
        "target_sme": "Agencies, D2C brands & B2B growth teams",
        "included_clusters": ["content_creative", "sales_closer"],
        "base_price": {"inr": 6999, "usd": 89},
        "annual_price": {"inr": 5599, "usd": 71, "discount_pct": 20},
        "included_modules": ["sales", "marketing", "seo"],
        "agent_limit": 5,
        "seat_limit": 5,
        "included_credits": {"lead_credits": 300, "outreach_credits": 150, "ai_execution_credits": 600},
        "support_level": "priority_business_hours",
        "customization_allowance": "workflow_and_prompt_tuning",
    },
    "operations": {
        "tier_key": "operations",
        "name": "Operations — Field & Vertical AI Suite",
        "target_sme": "Warehouses, distributors, packhouses & EV fleets",
        "included_clusters": ["operations_vertical_ai", "governance_scale"],
        "base_price": {"inr": 9999, "usd": 129},
        "annual_price": {"inr": 7999, "usd": 103, "discount_pct": 20},
        "included_modules": ["inventory", "field_force", "customer_ops"],
        "agent_limit": 6,
        "seat_limit": 10,
        "included_credits": {"lead_credits": 200, "outreach_credits": 100, "ai_execution_credits": 800},
        "support_level": "priority_business_hours",
        "customization_allowance": "erp_and_warehouse_connectors",
    },
    "business_pro": {
        "tier_key": "business_pro",
        "name": "Business Pro — Full Company OS (All 4 Clusters)",
        "target_sme": "Multi-department SMBs & scaling companies",
        "included_clusters": ["content_creative", "sales_closer", "operations_vertical_ai", "governance_scale"],
        "base_price": {"inr": 17999, "usd": 229},
        "annual_price": {"inr": 14399, "usd": 183, "discount_pct": 20},
        "included_modules": ["sales", "marketing", "seo", "inventory", "field_force", "customer_ops"],
        "agent_limit": 15,
        "seat_limit": 25,
        "included_credits": {"lead_credits": 1200, "outreach_credits": 600, "ai_execution_credits": 3000},
        "support_level": "priority_24x7",
        "customization_allowance": "custom_workflows_and_connectors",
    },
    "enterprise": {
        "tier_key": "enterprise",
        "name": "Enterprise — Sovereign Scale (All 4 Clusters + Dedicated)",
        "target_sme": "Regulated & multi-branch enterprise operations",
        "included_clusters": ["content_creative", "sales_closer", "operations_vertical_ai", "governance_scale"],
        "base_price": {"inr": 44999, "usd": 549},
        "annual_price": {"inr": 35999, "usd": 439, "discount_pct": 20},
        "included_modules": ["sales", "marketing", "seo", "inventory", "field_force", "customer_ops"],
        "agent_limit": 50,
        "seat_limit": 100,
        "included_credits": {"lead_credits": 5000, "outreach_credits": 2500, "ai_execution_credits": 12000},
        "support_level": "dedicated_architect_sla",
        "customization_allowance": "bespoke_private_node_and_custom_integrations",
    },
}


def get_modular_pricing_contract(
    package_or_tier_key: str,
    addon_modules: list[str] | None = None,
) -> dict[str, object]:
    """Return the 13-field machine-readable pricing & entitlement contract for any SKU or Modular SME Plan."""
    clean_key = (package_or_tier_key or "growth").strip().lower()
    addons = [m.strip().lower() for m in (addon_modules or []) if m.strip().lower() in MODULAR_SERVICE_MODULES]

    credit_costs = {
        "agent_run": 1,
        "seo_article": 2,
        "lead_discovery": 1,
        "inventory_audit": 1,
        "field_dispatch": 1,
        "marketing_campaign": 2,
    }

    if clean_key in MODULAR_SME_TIERS:
        tier_spec = MODULAR_SME_TIERS[clean_key]
        base_mods = list(tier_spec["included_modules"])  # type: ignore[arg-type]
        combined_mods = list(dict.fromkeys(base_mods + addons))
        extra_mods = [m for m in addons if m not in base_mods]
        extra_inr = sum(int(MODULAR_SERVICE_MODULES[m]["monthly_price_inr"]) for m in extra_mods)  # type: ignore[arg-type]
        extra_usd = sum(int(MODULAR_SERVICE_MODULES[m]["monthly_price_usd"]) for m in extra_mods)  # type: ignore[arg-type]
        base_price_dict = dict(tier_spec["base_price"])  # type: ignore[arg-type]
        total_inr = int(base_price_dict["inr"]) + extra_inr
        total_usd = int(base_price_dict["usd"]) + extra_usd

        annual_dict = dict(tier_spec.get("annual_price", {}))  # type: ignore[arg-type]
        return {
            "sku_key": clean_key,
            "name": tier_spec["name"],
            "plan_name": tier_spec["name"],
            "target_sme": tier_spec.get("target_sme", ""),
            "included_clusters": list(tier_spec.get("included_clusters", [])),  # type: ignore[arg-type]
            "billing_type": "recurring_subscription",
            "billing_interval": "monthly",
            "base_price": {"inr": total_inr, "usd": total_usd, "addon_inr": extra_inr, "addon_usd": extra_usd},
            "annual_price": {
                "inr": round(total_inr * 0.8),
                "usd": round(total_usd * 0.8),
                "discount_pct": int(annual_dict.get("discount_pct", 20)),
            },
            "provider_plan_id": {
                "razorpay": f"plan_afw_{clean_key}_inr",
                "paypal": f"P-AFW-{clean_key.upper()}-USD",
                "sovereign_direct": f"direct_afw_{clean_key}",
            },
            "included_modules": combined_mods,
            "addon_modules": extra_mods,
            "agent_limit": int(tier_spec["agent_limit"]) + (len(extra_mods) * 2),  # type: ignore[arg-type]
            "included_credits": dict(tier_spec["included_credits"]),  # type: ignore[arg-type]
            "credit_costs": credit_costs,
            "seat_limit": int(tier_spec["seat_limit"]),  # type: ignore[arg-type]
            "setup_fee": {"inr": 0 if clean_key in ("launch", "growth") else 4999, "usd": 0 if clean_key in ("launch", "growth") else 59},
            "support_level": tier_spec["support_level"],
            "renewal_policy": "auto_renew_monthly_cancel_anytime",
            "customization_allowance": tier_spec["customization_allowance"],
        }

    pkg = get_package(clean_key) or CATALOG["managed_seo_content_pilot"]
    if pkg.category == "managed_pilot":
        billing_type = "managed_pilot_14d"
        billing_interval = "14_days"
        renewal_policy = "manual_pilot_conversion_After_14d"
    elif pkg.category == "b2c_one_off":
        billing_type = "one_time_purchase"
        billing_interval = "one_time"
        renewal_policy = "one_time_no_renewal"
    else:
        billing_type = "recurring_subscription"
        billing_interval = "monthly"
        renewal_policy = "auto_renew_monthly_cancel_anytime"

    inferred_modules: list[str] = []
    caps_str = " ".join(pkg.entitled_capabilities)
    if "seo" in caps_str:
        inferred_modules.append("seo")
    if "marketing" in caps_str or "pixel" in caps_str:
        inferred_modules.append("marketing")
    if "discovery" in caps_str or "sales" in caps_str:
        inferred_modules.append("sales")
    if "warehouse" in caps_str or "inventory" in caps_str:
        inferred_modules.append("inventory")
    if "field" in caps_str or "mobility" in caps_str:
        inferred_modules.append("field_force")
    if "trust" in caps_str or "quality" in caps_str or not inferred_modules:
        inferred_modules.append("customer_ops")
    for m in addons:
        if m not in inferred_modules:
            inferred_modules.append(m)

    return {
        "sku_key": pkg.key,
        "name": pkg.name,
        "billing_type": billing_type,
        "billing_interval": billing_interval,
        "base_price": {"inr": pkg.price_inr, "usd": pkg.price_usd},
        "provider_plan_id": {
            "razorpay": f"plan_{pkg.key}_inr" if billing_type == "recurring_subscription" else f"order_{pkg.key}_inr",
            "paypal": f"P-{pkg.key.upper()[:14]}-USD",
            "sovereign_direct": f"direct_{pkg.key}",
        },
        "included_modules": inferred_modules,
        "addon_modules": addons,
        "agent_limit": 9 if pkg.category == "master_bundle" else 3,
        "included_credits": {
            "lead_credits": pkg.lead_credits_monthly,
            "outreach_credits": pkg.outreach_credits_monthly,
            "ai_execution_credits": max(50, pkg.lead_credits_monthly * 2),
        },
        "credit_costs": credit_costs,
        "seat_limit": 10 if pkg.category == "master_bundle" else 3,
        "setup_fee": {"inr": 0, "usd": 0},
        "support_level": "priority_24x7" if pkg.price_inr >= 9999 else "standard_sla",
        "renewal_policy": renewal_policy,
        "customization_allowance": (
            "custom_workflows_and_connectors"
            if pkg.category == "master_bundle"
            else "standard_templates"
        ),
    }

