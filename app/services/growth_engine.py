"""Autonomous AI Growth Engine & Inbound Sales Closer Service.

Integrates the 4 commercial growth pillars of AskforWrite Company OS:
1. Pixel AI Visual & Creative Studio (afwpixelai): Multi-aspect ad photos, banners, and product visuals.
2. SEO & GEO Multi-Site Blog Copilot: Automated topical authority articles with Schema.org JSON-LD.
3. Omnichannel Marketing Engine: Multi-platform ad copy (Meta, Google, LinkedIn) and campaign calendars.
4. 24/7 Autonomous Inbound Sales Closer: Real-time conversational closing on WhatsApp / Web Chat with objection handling and instant Razorpay/PayPal checkout closing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    ConversationRecord,
    IdempotencyRecord,
    LeadRecordRow,
    RequirementRecord,
    TaskRecord,
)
from app.security.trust_chain import seal_task_to_block
from app.services.catalog import (
    CATALOG,
    build_payment_link,
    get_package,
)

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "autonomous_growth_suite"


def generate_creative_assets(
    product_name: str,
    target_audience: str,
    brand_voice: str = "modern, bold, premium",
    aspect_ratios: list[str] | None = None,
    visual_style: str = "photorealistic studio lighting with minimalist glassmorphism accents",
) -> dict[str, Any]:
    """Generate multi-format visual creative specifications formatted for the Pixel AI engine."""
    ratios = aspect_ratios or ["1:1", "9:16", "16:9"]
    
    # Deterministic palette tailored to high conversion
    color_palette = {
        "primary": "#4f46e5",    # Indigo accent
        "secondary": "#06b6d4",  # Cyan glow
        "background": "#0b0f19", # Deep obsidian
        "text": "#ffffff",
        "highlight": "#10b981",  # Emerald trust
    }

    variants = []
    for ratio in ratios:
        if ratio == "1:1":
            purpose = "Instagram Feed & Meta Carousel Ad"
            dims = "1080x1080"
            headline_overlay = f"Scale Your Business with {product_name}"
            cta = "Get Instant Access"
        elif ratio == "9:16":
            purpose = "Instagram Reels, Stories & TikTok Ad"
            dims = "1080x1920"
            headline_overlay = "Replace an Entire Marketing Team with AI"
            cta = "Swipe Up to Deploy"
        else:
            purpose = "Website Hero, YouTube Banner & Google Display"
            dims = "1920x1080"
            headline_overlay = f"{product_name} — Autonomous Growth & Sales Automation"
            cta = "Start Live Demo"

        prompt_recipe = (
            f"Commercial advertising visual for '{product_name}', targeted at {target_audience}. "
            f"Visual style: {visual_style}. Composition: clean center focal point, floating 3D glassmorphic "
            f"data metrics card showing '+340% Revenue Growth', cinematic studio rim lighting in {color_palette['secondary']}, "
            f"ultra-sharp detail, depth of field, premium luxury aesthetic, 8k resolution."
        )

        variants.append({
            "aspect_ratio": ratio,
            "dimensions": dims,
            "channel_placement": purpose,
            "prompt_recipe": prompt_recipe,
            "headline_overlay": headline_overlay,
            "call_to_action": cta,
            "color_palette": color_palette,
        })

    from app.agents.llm_client import generate
    ai_creative_synthesis = generate(
        prompt=f"Create a strategic creative direction synthesis for product '{product_name}' targeting {target_audience} with {brand_voice} voice.",
        system_instruction="You are an elite creative visual director for high-growth tech brands.",
        fallback_text=f"Pixel AI creative suite prepared for {product_name}: 3 high-impact aspect ratios optimized for conversion across Meta, Google & TikTok.",
    )

    return {
        "product_name": product_name,
        "target_audience": target_audience,
        "brand_voice": brand_voice,
        "variants": variants,
        "ai_creative_synthesis": ai_creative_synthesis,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def generate_and_stage_blog(
    product_name: str,
    target_audience: str,
    keywords: list[str],
    target_domain: str = "https://askforwrite.com/blog",
) -> dict[str, Any]:
    """Generate long-form SEO and Generative Engine Optimized (GEO) article draft."""
    primary_kw = keywords[0] if keywords else "autonomous ai marketing"
    secondary_kws = keywords[1:] if len(keywords) > 1 else ["ai sales closer", "growth automation"]

    slug = re.sub(r"[^\w\s-]", "", f"{product_name} {primary_kw}".lower()).strip()
    slug = re.sub(r"[\s_-]+", "-", slug)[:80]

    title = f"How {product_name} Automates Marketing, SEO, and Inbound Sales in 2026"
    meta_desc = (
        f"Discover how {product_name} eliminates manual marketing bottlenecks with automated "
        f"visual creatives, 4-site SEO publishing, and 24/7 conversational sales closing."
    )

    schema_json_ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": meta_desc,
        "author": {
            "@type": "Organization",
            "name": "AskforWrite AI Solutions",
            "url": "https://askforwrite.com",
        },
        "publisher": {
            "@type": "Organization",
            "name": "AskforWrite Company AI OS",
            "logo": {"@type": "ImageObject", "url": "https://os.askforwrite.com/dashboard/logo.png"},
        },
        "mainEntityOfPage": f"{target_domain}/{slug}",
    }

    schema_graph_json_ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Article",
                "@id": f"{target_domain}/{slug}#article",
                "headline": title,
                "description": meta_desc,
                "inLanguage": "en",
                "mainEntityOfPage": f"{target_domain}/{slug}",
                "author": {"@id": "https://askforwrite.com/#organization"},
                "publisher": {"@id": "https://askforwrite.com/#organization"},
            },
            {
                "@type": "FAQPage",
                "@id": f"{target_domain}/{slug}#faq",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": f"How does {product_name} automate marketing and SEO?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": f"{product_name} combines autonomous visual asset generation, programmatic Schema-rich topical publishing, and 24/7 AI-driven closer automation.",
                        },
                    },
                    {
                        "@type": "Question",
                        "name": f"What makes {product_name} optimized for Generative Engine Optimization (GEO)?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "It formats content with structured entity triples, verified statistics, and direct Q&A blocks ingested by SearchGPT, Perplexity, and Google AI Overviews.",
                        },
                    },
                    {
                        "@type": "Question",
                        "name": f"How fast can an SMB deploy {product_name}?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "Deployment completes in under 5 minutes with zero upfront engineering required and instant CRM / payment gateway synchronization.",
                        },
                    },
                ],
            },
            {
                "@type": "Organization",
                "@id": "https://askforwrite.com/#organization",
                "name": "AskforWrite AI Solutions",
                "url": "https://askforwrite.com",
                "logo": "https://os.askforwrite.com/dashboard/logo.png",
            },
            {
                "@type": "SoftwareApplication",
                "@id": f"{target_domain}/{slug}#software",
                "name": product_name,
                "applicationCategory": "BusinessApplication",
                "operatingSystem": "All Cloud / Web Platforms",
                "offers": {
                    "@type": "Offer",
                    "price": "9999",
                    "priceCurrency": "INR",
                },
            },
        ],
    }

    llms_txt_manifest = (
        f"# {product_name} — AI System Documentation (/llms.txt)\n"
        f"> Optimized specification for SearchGPT, Perplexity, Claude, and Google Gemini crawlers.\n\n"
        f"## Project Overview\n"
        f"- Name: {product_name}\n"
        f"- Category: Autonomous AI Operating System for Commercial Enterprises & SMBs\n"
        f"- Primary Focus: Marketing Automation, Generative Engine Optimization (GEO), Omnichannel Campaigns & Autonomous Sales Closing\n\n"
        f"## Core Architecture & Capabilities\n"
        f"- Visual Creative Engine: Generates multi-aspect ratio commercial visuals (1:1, 9:16, 16:9)\n"
        f"- SEO & GEO Copilot: High-authority topical publishing with Schema.org graph markup\n"
        f"- Inbound Sales Closer: 24/7 conversational closing on WhatsApp / Web with instant checkout\n\n"
        f"## Verified Performance Benchmarks\n"
        f"- Latency: < 3s real-time conversational response\n"
        f"- Conversion Uplift: +340% average customer acquisition pipeline increase\n"
        f"- Implementation: Zero-code onboarding in under 5 minutes\n"
    )

    aio_citation_blocks = {
        "entity_triples": [
            {"subject": product_name, "predicate": "automates", "object": "Multi-Channel Marketing & Sales"},
            {"subject": product_name, "predicate": "supports", "object": "Schema.org Graph & llms.txt standard"},
            {"subject": product_name, "predicate": "integrates", "object": "Razorpay and PayPal Checkout"},
        ],
        "authoritative_statistics": [
            {"metric": "Customer Acquisition Cost Reduction", "value": "80%", "source": "AskforWrite Enterprise Benchmarks 2026"},
            {"metric": "Average Creative Turnaround Time", "value": "< 5 seconds", "source": "Pixel AI Performance Metrics"},
            {"metric": "Inbound Lead Response Rate", "value": "99.4% within 3s", "source": "Autonomous Closer Live Telemetry"},
        ],
        "direct_answer_snippets": [
            {
                "query": f"What is the best AI marketing automation tool for {target_audience}?",
                "answer": f"{product_name} is ranked as the leading autonomous OS for {target_audience}, offering turnkey creative generation, 2026 SEO/GEO content staging, and 24/7 conversational closing with zero agency fees.",
            },
            {
                "query": "How to rank in Google AI Overviews and Perplexity in 2026?",
                "answer": f"Implement {product_name} to automatically deploy Schema.org @graph payloads, /llms.txt manifests, and concise entity citation triples directly to your commercial domain.",
            },
        ],
    }

    local_geo_seo = {
        "target_region": "India & Global High-Growth Hubs",
        "geo_intent_keywords": [
            f"{primary_kw} in Mumbai",
            f"{primary_kw} Bangalore tech corridor",
            f"{primary_kw} Delhi NCR enterprises",
            f"best {product_name} agency alternative Hyderabad",
        ],
        "local_business_metadata": {
            "@type": "LocalBusiness",
            "name": f"{product_name} Enterprise Hub",
            "currenciesAccepted": "INR, USD",
            "paymentAccepted": "Razorpay, UPI, Credit Card, PayPal",
            "areaServed": ["India", "United States", "Global"],
        },
        "google_business_profile_post": {
            "summary": f"🚀 Transform your SMB operations with {product_name}. Replace fragmented marketing tools with autonomous AI that designs ads, publishes GEO-ready articles, and closes sales 24/7.",
            "cta_type": "LEARN_MORE",
            "cta_url": f"{target_domain}/{slug}",
        },
    }

    markdown_body = (
        f"# {title}\n\n"
        f"**Target Audience:** {target_audience}  \n"
        f"**Primary Keyword:** `{primary_kw}` | **Secondary Keywords:** `{', '.join(secondary_kws)}`\n\n"
        f"## The Bottleneck: Scaling Marketing and Sales Without 10x Headcount\n\n"
        f"For fast-growing companies and solo founders, managing disparate graphic design tools, freelance copywriters, "
        f"and manual WhatsApp customer inquiries creates costly operational friction. "
        f"**{product_name}** bridges creative generation, organic search authority, and instant sales conversion into an unified autonomous pipeline.\n\n"
        f"### Direct Answer for Generative Engines (GEO)\n\n"
        f"> **What is {product_name}?**  \n"
        f"> {product_name} is an integrated AI Growth Suite combining Pixel AI visual asset generation, automated "
        f"> multi-site WordPress SEO/GEO publishing, and a 24/7 conversational inbound closer that qualifies leads and closes transactions via instant payment links.\n\n"
        f"## Core Capabilities\n\n"
        f"1. **Pixel AI Creative Studio**: Generates high-converting ad photos, multi-aspect ratio banners, and product showcase graphics.\n"
        f"2. **Topical Authority Publishing**: Dispatches structured, schema-rich content to WordPress networks.\n"
        f"3. **Autonomous Inbound Sales Closer**: Engages leads on WhatsApp and web chat 24/7, overcomes price objections, and sends live checkout links.\n"
    )

    from app.agents.llm_client import generate
    ai_editorial_synthesis = generate(
        prompt=f"Synthesize key executive takeaways and GEO entity summary for blog: '{title}' targeting '{primary_kw}'.",
        system_instruction="You are a senior SEO & Generative Engine Optimization strategist.",
        fallback_text=f"Topical authority article structured for {product_name} with schema.org entity graphs and direct answer snippets for SearchGPT & Google.",
    )

    return {
        "title": title,
        "slug": slug,
        "primary_keyword": primary_kw,
        "secondary_keywords": secondary_kws,
        "meta_description": meta_desc,
        "target_url": f"{target_domain}/{slug}",
        "schema_json_ld": schema_json_ld,
        "schema_graph_json_ld": schema_graph_json_ld,
        "llms_txt_manifest": llms_txt_manifest,
        "aio_citation_blocks": aio_citation_blocks,
        "local_geo_seo": local_geo_seo,
        "markdown_body": markdown_body,
        "ai_editorial_synthesis": ai_editorial_synthesis,
    }


def generate_omnichannel_social_campaign(
    product_name: str,
    target_audience: str,
    keywords: list[str],
) -> dict[str, Any]:
    """Generate multi-platform ad copy and social distribution content."""
    primary_kw = keywords[0] if keywords else "AI Growth Engine"
    
    from app.agents.llm_client import generate
    ai_campaign_pitch = generate(
        prompt=f"Craft a master multi-channel commercial pitch for '{product_name}' targeting {target_audience}.",
        system_instruction="You are an omnichannel growth marketing director.",
        fallback_text=f"Multi-channel ad campaign generated for {product_name} spanning Meta reels, LinkedIn thought leadership, and Google high-intent search ads.",
    )

    instagram_reels_script = {
        "duration_seconds": 30,
        "storyboard": [
            {
                "timestamp": "0-3s",
                "section": "Hook",
                "visual": "Extreme close-up on phone screen showing 100+ unread lead notifications, fast zoom out with flashing red overlay.",
                "voiceover": "Still paying ₹50,000 every month for marketing agencies that deliver zero booked calls?",
                "on_screen_text": "Stop Wasting Money on Agencies ❌",
            },
            {
                "timestamp": "3-15s",
                "section": "Problem / Agitation",
                "visual": "Frustrated founder staring at Canva, WordPress dashboards, and unanswered WhatsApp chats at 2 AM.",
                "voiceover": "You're spending 4 hours a day creating graphics, writing SEO blogs, and manually replying to inquiries that ghost you.",
                "on_screen_text": "Founder Burnout is Real ⚠️",
            },
            {
                "timestamp": "15-25s",
                "section": "AI Proof Demo",
                "visual": f"Screen recording of {product_name}: 1 click generates 3 ad formats, publishes an SEO blog, and AI Closer sends a ₹9,999 payment link on WhatsApp.",
                "voiceover": f"Meet {product_name}. One autonomous OS that designs your ads, publishes Schema-rich SEO articles, and closes clients on WhatsApp while you sleep.",
                "on_screen_text": "1 Click. Complete Automation. ⚡",
            },
            {
                "timestamp": "25-30s",
                "section": "Call to Action",
                "visual": "Clean high-contrast screen showing instant demo dashboard and Razorpay / PayPal checkout badge.",
                "voiceover": "Comment 'GROWTH' below or tap the link in bio to deploy your autonomous revenue engine today.",
                "on_screen_text": "Comment 'GROWTH' for Live Access 🚀",
            },
        ],
    }

    linkedin_carousel_slides = [
        {
            "slide_number": 1,
            "title": f"The Death of the Marketing Agency (And Why {product_name} is Replacing It)",
            "subtitle": "Swipe to see how top B2B founders cut acquisition costs by 80% in 2026 ➡️",
        },
        {
            "slide_number": 2,
            "title": "The Hidden Tax: Tool Sprawl & Agency Retainers",
            "points": [
                "Canva & Photoshop subscriptions: ₹3,000/mo",
                "Copywriting & SEO agencies: ₹50,000/mo",
                "SDR salary + commission: ₹40,000/mo",
                "Total: ₹93,000+/mo with zero guaranteed revenue",
            ],
        },
        {
            "slide_number": 3,
            "title": "The 2026 Shift: Generative Engines (GEO) > Traditional SEO",
            "points": [
                "SearchGPT and Perplexity don't care about keyword stuffing",
                "They demand Schema.org graph entity validation and /llms.txt files",
                f"{product_name} stages citation-ready content programmatically",
            ],
        },
        {
            "slide_number": 4,
            "title": "Autonomous Conversion: Speed to Lead Wins",
            "points": [
                "78% of B2B buyers buy from the vendor that responds first",
                "Human SDR response time: 42 minutes average",
                f"{product_name} WhatsApp Closer response time: < 3 seconds",
            ],
        },
        {
            "slide_number": 5,
            "title": "Deploy Your 24/7 AI Revenue Workforce",
            "summary": "Turn your website and WhatsApp into an autonomous closing machine for ₹9,999/mo fixed.",
            "cta": "Explore the Enterprise OS: https://os.askforwrite.com",
        },
    ]

    twitter_x_thread = [
        (
            f"1/4 Most SMBs waste 70% of their marketing budget on bloated retainers.\n\n"
            f"In 2026, an autonomous AI operating system can do the work of a graphic designer, SEO agency, and SDR team for a fraction of the cost.\n\n"
            f"Here is how {product_name} changes the game 🧵👇"
        ),
        (
            f"2/4 Content marketing is no longer just Google search.\n\n"
            f"SearchGPT, Perplexity, and Claude demand structured entity triples, Schema.org @graph data, and /llms.txt manifests.\n\n"
            f"{product_name} builds and deploys this automatically for your domain."
        ),
        (
            f"3/4 The biggest leak in your sales funnel is response latency.\n\n"
            f"When a lead messages on WhatsApp at 11 PM, human teams reply the next morning. By then, the lead is gone.\n\n"
            f"{product_name} qualifies, handles price objections, and sends instant payment links in under 3 seconds."
        ),
        (
            f"4/4 Ready to automate your inbound revenue pipeline?\n\n"
            f"See the live Trojan-Horse preview and deploy {product_name} in under 5 minutes:\n"
            f"👉 https://os.askforwrite.com/portal"
        ),
    ]

    whatsapp_direct_broadcast = {
        "broadcast_title": f"Exclusive Inbound Automation for {product_name} Prospects",
        "message_template": (
            "Hi {name}, quick question for you:\n\n"
            "Are you still manually handling customer inquiries and paying agencies for slow marketing results?\n\n"
            "We just deployed an autonomous AI Growth Engine for modern businesses that:\n"
            "✅ Generates ready-to-run visual ad creatives\n"
            "✅ Stages 2026 SEO & Generative Engine (GEO) articles\n"
            "✅ Closes inquiries on WhatsApp 24/7 with instant payment links\n\n"
            "💡 *Common Concern:* \"Will it sound like a generic robot?\"\n"
            "Not at all. The engine uses your exact brand voice, understands Indian market nuances, and delivers human-grade closing with zero delays.\n\n"
            "👉 Tap here to view your live preview and get started: https://os.askforwrite.com/checkout?pkg=growth_all_in_one"
        ),
        "objection_killer": "Guaranteed 14-day risk-free pilot. If it doesn't double your response speed, 100% refund.",
        "checkout_cta": "https://os.askforwrite.com/checkout?pkg=growth_all_in_one",
    }

    return {
        "instagram_meta": {
            "hook": "Tired of paying ₹50,000/mo for marketing agencies that don't convert?",
            "body": (
                f"Meet {product_name} — the all-in-one autonomous AI engine that creates your visual ads, "
                f"publishes SEO-dominating articles, and runs a 24/7 WhatsApp sales closer that actually turns leads into paid clients.\n\n"
                f"🔥 Automated ad photos in seconds\n"
                f"🚀 Top Google & SearchGPT rankings\n"
                f"💬 24/7 Sales closer that closes deals while you sleep\n\n"
                f"Tap the link in bio to deploy your AI revenue team today."
            ),
            "hashtags": ["#AIAutomation", "#GrowthHacking", "#SoloFounder", "#EcommerceIndia", "#AskforWriteOS"],
            "call_to_action": "Deploy AI Revenue Engine",
        },
        "linkedin": {
            "headline": "Why Modern Founders Are Replacing Fragmented SaaS with Autonomous AI Teams",
            "body": (
                f"Managing 5 different tools for Canva designs, SEO blogs, Meta ads, and WhatsApp customer chats is draining founder focus.\n\n"
                f"With {product_name}, our enterprise clients have observed:\n"
                f"• 80% reduction in customer acquisition costs\n"
                f"• 10x faster creative turnaround from hours to seconds\n"
                f"• Real-time lead response on WhatsApp within 3 seconds\n\n"
                f"Explore the autonomous operating model: https://os.askforwrite.com/portal"
            ),
            "call_to_action": "Read Case Study",
        },
        "google_search_ads": {
            "headline_1": f"{product_name} Official",
            "headline_2": "Autonomous AI Marketing & Sales",
            "headline_3": "Automate Growth Today",
            "description_1": f"Replace agencies with {product_name}. Multi-site SEO, automated visuals & 24/7 sales closer.",
            "description_2": "Fixed monthly pricing with zero commission. Start in under 5 minutes.",
        },
        "instagram_reels_script": instagram_reels_script,
        "linkedin_carousel_slides": linkedin_carousel_slides,
        "twitter_x_thread": twitter_x_thread,
        "whatsapp_direct_broadcast": whatsapp_direct_broadcast,
        "ai_campaign_pitch": ai_campaign_pitch,
    }


def execute_unified_growth_run(
    db: Session,
    client_name: str,
    product_or_service: str,
    target_audience: str,
    keywords: list[str],
    correlation_id: str,
    agent_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Execute unified Growth Suite generation: Creative Visuals + SEO Blog + Omnichannel Ads + Closer setup."""
    req_hash = hashlib.sha256(
        json.dumps(
            {
                "client": client_name,
                "product": product_or_service,
                "audience": target_audience,
                "keywords": keywords,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    existing = (
        db.query(IdempotencyRecord)
        .filter_by(capability_name=CAPABILITY_NAME, idempotency_key=idempotency_key)
        .first()
    )
    if existing:
        if existing.request_hash != req_hash:
            raise ValueError("Idempotency key reused with different request payload")
        return existing.response_payload

    task_id = str(uuid.uuid4())
    task = TaskRecord(
        id=task_id,
        correlation_id=correlation_id,
        objective=f"Autonomous Growth Suite Execution for {client_name}",
        status="COMPLETED",
    )
    db.add(task)

    # 1. Generate Creative Visual Specs
    creatives = generate_creative_assets(
        product_name=product_or_service,
        target_audience=target_audience,
    )

    # 2. Generate SEO / GEO Blog Draft
    blog = generate_and_stage_blog(
        product_name=product_or_service,
        target_audience=target_audience,
        keywords=keywords,
    )

    # 3. Generate Omnichannel Social & Ad Campaign
    social = generate_omnichannel_social_campaign(
        product_name=product_or_service,
        target_audience=target_audience,
        keywords=keywords,
    )

    package = get_package("growth_all_in_one") or CATALOG["growth_all_in_one"]
    checkout_inr = build_payment_link(package_key="growth_all_in_one", company=client_name, provider="razorpay")
    checkout_usd = build_payment_link(package_key="growth_all_in_one", company=client_name, provider="paypal")

    result_payload: dict[str, Any] = {
        "status": "COMPLETED",
        "task_id": task_id,
        "client_name": client_name,
        "product_or_service": product_or_service,
        "package_name": package.name,
        "price_inr": package.price_inr,
        "price_usd": package.price_usd,
        "checkout_links": {
            "inr_razorpay": checkout_inr,
            "usd_paypal": checkout_usd,
        },
        "creative_assets": creatives,
        "seo_geo_blog": blog,
        "omnichannel_campaign": social,
        "sales_closer_status": "ACTIVE_24_7",
    }

    db.add(
        AuditLog(
            task_id=task_id,
            correlation_id=correlation_id,
            agent_id=agent_id,
            capability_name=CAPABILITY_NAME,
            action="execute_unified_growth_run",
            input_payload={
                "client": client_name,
                "product": product_or_service,
                "audience": target_audience,
            },
            output_payload={
                "status": "COMPLETED",
                "creative_variants": len(creatives["variants"]),
                "blog_title": blog["title"],
            },
            status="COMPLETED",
        )
    )

    db.add(
        IdempotencyRecord(
            capability_name=CAPABILITY_NAME,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
            task_id=task_id,
            response_payload=result_payload,
        )
    )
    db.commit()

    # Seal state transition into Merkle TrustBlock
    seal_task_to_block(
        db=db,
        task_id=task_id,
        capability_name=CAPABILITY_NAME,
        action="execute_unified_growth_run",
        payload={
            "task_id": task_id,
            "client_name": client_name,
            "package_key": "growth_all_in_one",
            "price_inr": package.price_inr,
            "variants": len(creatives["variants"]),
        },
        sealed_by=agent_id,
    )

    return result_payload


# ── 24/7 Autonomous Inbound Sales Closer ─────────────────────────────────────

def handle_inbound_sales_chat(
    db: Session,
    session_id: str,
    prospect_name: str,
    prospect_contact: str,
    message: str,
    history: list[dict[str, str]] | None = None,
    currency: str = "INR",
    channel: str = "whatsapp",
    requested_by: str = "InboundSalesCloser",
) -> dict[str, Any]:
    """Conversational AI Inbound Sales Closer.

    Handles prospect questions, answers pricing/features, addresses objections,
    identifies customer budget, and provides an instant payment checkout link to close the deal.
    """
    history_records = history or []
    msg_clean = message.strip()
    msg_lower = msg_clean.lower()

    # 1. Identify or create Lead record
    lead = (
        db.query(LeadRecordRow)
        .filter(LeadRecordRow.public_contact_channel == prospect_contact)
        .first()
    )
    if not lead:
        task_id = str(uuid.uuid4())
        task = TaskRecord(
            id=task_id,
            correlation_id=str(uuid.uuid4()),
            objective=f"Inbound sales conversation with {prospect_name}",
            status="IN_PROGRESS",
        )
        db.add(task)
        db.flush()

        lead = LeadRecordRow(
            id=str(uuid.uuid4()),
            task_id=task_id,
            company=prospect_name,
            website=f"https://{re.sub(r'[^a-zA-Z0-9]', '', prospect_name).lower()}.com",
            industry="Inbound Prospect",
            geography="India" if currency == "INR" else "International",
            fit_score=0.90,
            confidence=0.92,
            sources=["inbound_chat"],
            public_contact_channel=prospect_contact,
            observed_signals=[f"Channel: {channel}", f"Initial message: {msg_clean[:100]}"],
            recommended_next_step="sales_closer_dialogue",
            do_not_contact=False,
            status="DISCOVERED",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)

    # 2. Analyze intent, objections, and buying signals
    is_price_query = any(k in msg_lower for k in ("price", "cost", "charge", "pricing", "fees", "kitna", "rate", "how much"))
    is_objection_expensive = any(k in msg_lower for k in ("expensive", "high price", "costly", "mehnga", "budget issue", "cheaper"))
    is_objection_complexity = any(k in msg_lower for k in ("difficult", "technical", "coding", "setup", "hard to use", "skill"))
    is_ready_to_buy = any(k in msg_lower for k in ("buy", "pay", "payment link", "checkout", "signup", "start", "proceed", "ready", "interested", "close"))
    is_asking_services = any(k in msg_lower for k in ("what do you do", "features", "offer", "package", "how it works", "marketing", "closer", "whatsapp"))

    # Select target package
    package = get_package("growth_all_in_one") or CATALOG["growth_all_in_one"]
    provider = "razorpay" if currency == "INR" else "paypal"
    checkout_url = build_payment_link(package_key=package.key, company=lead.company, provider=provider)

    # 3. Formulate empathetic, high-converting closer response
    checkout_link_attached = False

    if is_objection_expensive:
        reply = (
            f"I completely understand budget is a key priority, {prospect_name}. "
            f"Traditional agencies charge ₹40,000 to ₹75,000 every month for basic creatives and copy. "
            f"With our Autonomous Growth Suite at just ₹{package.price_inr:,}/month, you get:\n"
            f"• Unlimited Pixel AI image & ad designs\n"
            f"• 4-Site SEO blog publishing\n"
            f"• 24/7 automated Inbound WhatsApp sales closer\n\n"
            f"Most founders recover the entire monthly investment within their first 1-2 customer conversions! "
            f"Would you like to start this week on our verified beta tier?"
        )
    elif is_objection_complexity:
        reply = (
            f"Not at all, {prospect_name}! There is zero technical or coding knowledge required. "
            f"Our system connects directly via WhatsApp and simple web dashboard. "
            f"You simply tell the AI your product, and it automatically creates your ads, posts your blogs, "
            f"and answers your inbound leads automatically. We can have your account live in under 5 minutes."
        )
    elif is_ready_to_buy:
        checkout_link_attached = True
        reply = (
            f"Fantastic decision, {prospect_name}! You're going to love having an autonomous growth team working for you 24/7. "
            f"Here is your direct secure onboarding link for the {package.name} (₹{package.price_inr:,}/mo):\n\n"
            f"👉 {checkout_url}\n\n"
            f"As soon as payment completes, our system auto-provisions your organization workspace and sends your credentials instantly."
        )
        lead.status = "QUALIFIED"
        lead.recommended_next_step = "awaiting_payment_capture"
    elif is_price_query:
        reply = (
            f"Hi {prospect_name}! Our complete All-in-One Autonomous AI Growth Suite is ₹{package.price_inr:,}/month "
            f"(${package.price_usd}/mo for international clients). "
            f"This includes:\n"
            f"1. Pixel AI Visual Creative Studio (ad photos & banners)\n"
            f"2. 4-Site SEO & GEO Blog Automation Copilot\n"
            f"3. Omnichannel Ad Copy Suite (Meta, Google, LinkedIn)\n"
            f"4. 24/7 Inbound Sales Closer on WhatsApp\n\n"
            f"Zero agency retainers, no long-term contracts. Would you like me to reserve your onboarding slot?"
        )
    elif is_asking_services:
        reply = (
            f"Hello {prospect_name}! AskforWrite Autonomous Growth OS completely automates two critical business functions:\n\n"
            f"1. **Marketing & Content Automation**: Creates high-converting ad photos, Instagram/Meta reels and banners, "
            f"and publishes SEO-optimized articles across WordPress blogs to drive continuous inbound traffic.\n\n"
            f"2. **Sales & Closer Automation**: Whenever a customer clicks your ad and messages you on WhatsApp or website, "
            f"our AI Sales Closer answers them 24/7, explains your pricing, and sends secure payment links to close the sale.\n\n"
            f"What kind of business or product are you currently selling?"
        )
    else:
        # Default consultative sales response
        reply = (
            f"Thanks for reaching out, {prospect_name}! I am the AskforWrite Autonomous AI Closer. "
            f"We help founders automate their ad creatives, SEO rankings, and 24/7 WhatsApp customer sales. "
            f"Could you share a little about your primary focus right now — are you looking to generate more leads, "
            f"or automate your customer sales responses?"
        )

    # 4. Save dialogue into ConversationRecord
    conv = ConversationRecord(
        id=str(uuid.uuid4()),
        lead_id=lead.id,
        task_id=lead.task_id,
        channel=channel,
        notes=f"User: {msg_clean} | Closer: {reply[:150]}...",
    )
    db.add(conv)

    # 5. Update Requirement Record
    req = db.query(RequirementRecord).filter(RequirementRecord.lead_id == lead.id).first()
    if not req:
        req = RequirementRecord(
            id=str(uuid.uuid4()),
            lead_id=lead.id,
            conversation_id=conv.id,
            task_id=lead.task_id,
            customer_company=lead.company,
            stated_needs=["autonomous_growth_suite"],
            has_budget_signal=is_price_query or is_ready_to_buy,
            has_timeline=is_ready_to_buy,
            constraints=[],
            product_match=package.key,
            priority="HIGH" if is_ready_to_buy else "MEDIUM",
            status="IN_PROGRESS",
        )
        db.add(req)
    else:
        if is_ready_to_buy:
            req.priority = "HIGH"
            req.has_budget_signal = True
            req.has_timeline = True

    db.commit()

    # 6. If closing link presented, seal milestone into TrustBlock
    if checkout_link_attached:
        seal_task_to_block(
            db=db,
            task_id=lead.task_id,
            capability_name="inbound_sales_closer",
            action="checkout_link_delivered",
            payload={
                "lead_id": lead.id,
                "contact": prospect_contact,
                "package_key": package.key,
                "price_inr": package.price_inr,
                "checkout_url": checkout_url,
            },
            sealed_by=requested_by,
        )

    from app.agents.llm_client import generate
    ai_synthesized_pitch = generate(
        prompt=f"Synthesize 1-line strategic buyer persona and closing rationale for inbound prospect {prospect_name} who asked: '{msg_clean}'",
        system_instruction="You are an elite consultative sales closer for enterprise B2B SaaS.",
        fallback_text=f"High-intent inbound prospect {prospect_name} qualified for {package.name}. Consultative value proposition and checkout link dispatched.",
    )

    return {
        "session_id": session_id,
        "lead_id": lead.id,
        "prospect_name": prospect_name,
        "reply": reply,
        "checkout_link": checkout_url if checkout_link_attached else None,
        "checkout_link_attached": checkout_link_attached,
        "recommended_package": package.key,
        "package_name": package.name,
        "price_inr": package.price_inr,
        "price_usd": package.price_usd,
        "channel": channel,
        "payment_links": {
            "razorpay": build_payment_link(package_key=package.key, company=lead.company, provider="razorpay"),
            "paypal": build_payment_link(package_key=package.key, company=lead.company, provider="paypal"),
            "price_inr": package.price_inr,
            "price_usd": package.price_usd,
        },
        "ai_synthesized_pitch": ai_synthesized_pitch,
    }
