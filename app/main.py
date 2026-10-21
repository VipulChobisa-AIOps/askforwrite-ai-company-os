"""FastAPI development surface for the first offline MVP capability."""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.accounts import router as accounts_router
from app.api.v1.audit_export import router as audit_export_router
from app.api.v1.auth import router as auth_router
from app.api.v1.customer_portal import router as customer_portal_router
from app.api.v1.field_force import router as field_force_router
from app.api.v1.growth_suite import router as growth_suite_router
from app.api.v1.inventory_analytics import router as inventory_analytics_router
from app.api.v1.leads import router as leads_router
from app.api.v1.legal import router as legal_router
from app.api.v1.mobile_bridge import router as mobile_bridge_router
from app.api.v1.mobility_analytics import router as mobility_analytics_router
from app.api.v1.outreach import router as outreach_router
from app.api.v1.previews import router as previews_router
from app.api.v1.quality_analytics import router as quality_analytics_router
from app.api.v1.revenue import router as revenue_router
from app.api.v1.scheduler import router as scheduler_router
from app.api.v1.sovereign_pay import router as sovereign_pay_router
from app.api.v1.subscriptions import router as subscriptions_router
from app.api.v1.watchdog import router as watchdog_router
from app.api.v1.webhooks import router as webhooks_router
from app.clients.field_force import FieldForceClient, get_field_force_client
from app.db.database import get_db
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    ConversationRecord,
    CustomerRecord,
    DeliveryRecord,
    IdempotencyRecord,
    InvoiceRecord,
    LeadRecordRow,
    MarketingCampaignRecord,
    OrderRecord,
    OrganizationRecord,
    OutreachRecord,
    ProposalRecord,
    RequirementRecord,
    ResearchRecord,
    SeoDraftRecord,
    SubscriptionRecord,
    TaskRecord,
    TrustBlock,
    UserRecord,
    WebhookEventRecord,
)
from app.logging_config import configure_logging
from app.middleware import add_production_middleware
from app.monitoring import init_sentry
from app.security.auth import APIPrincipal, require_manager, require_owner
from app.security.trust_chain import verify_chain_integrity
from app.services.approvals import (
    ApprovalConflict,
    ApprovalNotFound,
    decide_approval,
    request_approval,
)
from app.services.delivery import (
    DeliveryConflict,
    DeliveryNotApproved,
    DeliveryNotFound,
    execute_delivery,
)
from app.services.discovery import IdempotencyConflict, execute_discovery
from app.services.manager import ManagerConflict, execute_manager_workflow
from app.services.marketing import MarketingConflict, execute_marketing_campaign
from app.services.orders import (
    OrderConflict,
    OrderValidationFailed,
    fulfill_order,
    fulfill_pending_orders,
    ingest_order,
    list_orders,
)
from app.services.research import ResearchConflict, ResearchNotFound, execute_research
from app.services.sales import SalesConflict, SalesNotFound, execute_sales_capture
from app.services.seo import SeoConflict, execute_seo_draft
from app.services.wordpress_publisher import (
    get_supported_networks,
    publish_seo_draft_to_wordpress,
)

# Initialize logging system and error tracking early
configure_logging()
init_sentry()


@asynccontextmanager

async def lifespan(app: FastAPI):
    """Create tables (SQLite dev) and initialize Genesis trust block on startup."""
    from app.db.database import DATABASE_URL, Base, engine
    if DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    from app.db.database import SessionLocal
    from app.security.trust_chain import ensure_genesis_block
    db = SessionLocal()
    try:
        ensure_genesis_block(db)
    finally:
        db.close()
    yield
    # Shutdown logic (if needed in the future) goes here


app = FastAPI(
    title="AskforWrite AI Company OS",
    version="0.2.0",
    description=(
        "**AskforWrite AI Company OS** — A production-grade, multi-agent B2B SaaS platform.\n\n"
        "### Key capabilities\n"
        "- 🤖 **Multi-agent orchestration** (Discovery → Research → Sales → Delivery) with Human-in-the-Loop governance\n"
        "- 🔐 **Cryptographic trust ledger** — ECDSA P-256 Merkle chain, tamper-evident audit trail\n"
        "- 📍 **Field Force Management** — GPS attendance, visit verification, task dispatch, conveyance claims\n"
        "- 💰 **Revenue Engine** — AI pitch generation with embedded Razorpay/PayPal payment links\n"
        "- 🏢 **Multi-tenant SaaS** — Org isolation, tiered rate limiting, self-serve signup\n"
        "- 📊 **Customer Portal** — Self-service credit usage, billing history, capability entitlements\n\n"
        "### Authentication\n"
        "- **API Key** (`X-API-Key` header): Manager role or Owner role — for internal agent pipelines\n"
        "- **Bearer Token** (`Authorization: Bearer <token>`): For customer portal endpoints\n"
    ),
    contact={
        "name": "AskforWrite Support",
        "email": "info@askforwrite.in",
        "url": "https://askforwrite.in",
    },
    license_info={
        "name": "Proprietary — AskforWrite Technologies",
        "url": "https://os.askforwrite.com/legal/tos",
    },
    openapi_tags=[
        {"name": "authentication", "description": "User login, signup, and JWT token management"},
        {"name": "customer-portal", "description": "Self-service tenant dashboard: profile, usage, billing, capabilities"},
        {"name": "accounts", "description": "Multi-tenant organization and team management"},
        {"name": "leads", "description": "AI-powered lead discovery, enrichment, and lifecycle management"},
        {"name": "outreach", "description": "HITL-gated email outreach drafting and dispatch"},
        {"name": "revenue", "description": "AI revenue pitch generation with payment link embedding"},
        {"name": "field-force", "description": "GPS attendance, visit verification, task dispatch, and conveyance"},
        {"name": "subscriptions", "description": "Subscription and plan management via Razorpay/PayPal"},
        {"name": "webhooks", "description": "Payment provider webhook ingestion and tenant provisioning"},
        {"name": "audit-export", "description": "Compliance audit log export (JSON/CSV) — Owner only"},
        {"name": "legal", "description": "Public Terms of Service, Privacy Policy, MSME Statutory Declaration & Copyrights (UDYAM-RJ-14-0018404)"},
        {"name": "watchdog", "description": "L1 active monitoring, stalled task detection & self-healing watchdog agent"},
    ],
    lifespan=lifespan,
)

add_production_middleware(app)

# ── Phase 1-3 Routers ────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(leads_router)
app.include_router(outreach_router)
app.include_router(revenue_router)
app.include_router(subscriptions_router)
app.include_router(webhooks_router)
app.include_router(field_force_router)

# ── Phase 4 Routers: Customer Portal, Audit Export, Legal, Mobile Bridge ────
app.include_router(customer_portal_router)
app.include_router(audit_export_router)
app.include_router(legal_router)
app.include_router(mobile_bridge_router)
app.include_router(growth_suite_router)
app.include_router(quality_analytics_router)
app.include_router(mobility_analytics_router)
app.include_router(inventory_analytics_router)
app.include_router(watchdog_router)
app.include_router(previews_router)
app.include_router(scheduler_router)
app.include_router(sovereign_pay_router)

# ── Admin & Customer Portal Static Frontend ──────────────────────────────────
# ── Admin & Customer Portal Static Frontend ──────────────────────────────────
dashboard_dir = Path(__file__).resolve().parent / "dashboard"
if dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")
    app.mount("/static", StaticFiles(directory=str(dashboard_dir)), name="static")


@app.get("/health", tags=["system"])
def health_check(db: Session = Depends(get_db)) -> dict[str, str]:
    """Production health check endpoint for Render, cloud monitors, and load balancers."""
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "degraded"

    return {
        "status": "healthy",
        "service": "AskforWrite AI Company OS",
        "version": "0.2.0",
        "database": db_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/", include_in_schema=False)
def root(request: Request) -> Any:
    """Root entrypoint: returns service metadata for API clients or redirects browsers to dashboard."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept and "application/json" not in accept:
        return RedirectResponse(url="/dashboard/")
    return {
        "status": "online",
        "service": "AskforWrite AI Company OS",
        "version": "0.2.0",
        "docs_url": "/docs",
        "health_url": "/health",
        "dashboard_url": "/dashboard/",
        "api_prefix": "/v1",
        "message": "Welcome to AskforWrite AI Company OS Gateway. Visit /dashboard/ for Owner UI or /docs for interactive Swagger UI."
    }


@app.get("/login", include_in_schema=False)
def login_redirect() -> RedirectResponse:
    """Redirect /login directly to the portal login view."""
    return RedirectResponse(url="/dashboard/#portal")


@app.get("/portal", include_in_schema=False)
@app.get("/app", include_in_schema=False)
def portal_redirect() -> RedirectResponse:
    """Redirect /portal and /app directly to the unified frontend portal."""
    return RedirectResponse(url="/dashboard/#portal")


@app.get("/admin", include_in_schema=False)
def admin_redirect() -> RedirectResponse:
    """Redirect /admin directly to the dashboard interface."""
    return RedirectResponse(url="/dashboard/")


@app.get("/terms", include_in_schema=False)
@app.get("/tos", include_in_schema=False)
def terms_redirect() -> RedirectResponse:
    """Redirect /terms and /tos to official Terms of Service."""
    return RedirectResponse(url="/legal/tos")


@app.get("/privacy", include_in_schema=False)
def privacy_redirect() -> RedirectResponse:
    """Redirect /privacy to official Privacy Policy."""
    return RedirectResponse(url="/legal/privacy")


@app.get("/msme", include_in_schema=False)
@app.get("/declaration", include_in_schema=False)
def msme_redirect() -> RedirectResponse:
    """Redirect /msme to official MSME statutory declaration UDYAM-RJ-14-0018404."""
    return RedirectResponse(url="/legal/declaration")


@app.get("/refund-policy", include_in_schema=False)
@app.get("/refunds", include_in_schema=False)
def refund_redirect() -> RedirectResponse:
    """Redirect /refund-policy to official Refund Policy."""
    return RedirectResponse(url="/legal/refund-policy")


@app.get("/mobile/manifest.json", include_in_schema=False)
def mobile_manifest() -> dict[str, object]:
    """Progressive Web App (PWA) manifest for Android and iOS home screen installation."""
    return {
        "name": "AskforWrite Company OS — Field & Mobile",
        "short_name": "AFW OS",
        "description": "Pixel AI & Field Force mobile operations portal with offline GPS check-in",
        "start_url": "/dashboard/#mobile",
        "display": "standalone",
        "background_color": "#0b0f19",
        "theme_color": "#4f46e5",
        "icons": [
            {
                "src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='20' fill='%234f46e5'/><text x='50' y='65' font-size='50' font-family='sans-serif' fill='white' text-anchor='middle'>AFW</text></svg>",
                "sizes": "192x192 512x512",
                "type": "image/svg+xml",
                "purpose": "any maskable"
            }
        ]
    }



class DiscoveryRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ApprovalRequestPayload(BaseModel):
    task_id: str = Field(min_length=1, max_length=36)
    lead_id: str | None = Field(default=None, max_length=36)
    action: str = Field(min_length=1, max_length=100)
    detail: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ApprovalDecisionPayload(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    reason: str | None = Field(default=None, max_length=1000)


class ResearchExecutePayload(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=200)


class ManagerExecutePayload(DiscoveryRequest):
    pass


class SalesExecutePayload(BaseModel):
    lead_id: str = Field(min_length=1, max_length=36)
    conversation_notes: str = Field(min_length=1, max_length=10000)
    channel: Literal["internal_notes", "call_notes", "meeting_notes", "email_notes"] = "internal_notes"
    idempotency_key: str = Field(min_length=1, max_length=200)


class DeliveryExecutePayload(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=36)
    assigned_to: str = Field(min_length=1, max_length=100)
    due_date: datetime | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)


class OrderIngestPayload(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=100)
    amount: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=10)
    customer_email: str = Field(min_length=3, max_length=250)
    idempotency_key: str = Field(min_length=1, max_length=200)


class SeoDraftPayload(BaseModel):
    target_network: str = Field(min_length=1, max_length=100)
    keywords: list[str] = Field(min_length=1, max_length=20)
    idempotency_key: str = Field(min_length=1, max_length=200)


class MarketingCampaignPayload(BaseModel):
    campaign_type: str = Field(min_length=1, max_length=100)
    target_audience: str = Field(min_length=1, max_length=250)
    idempotency_key: str = Field(min_length=1, max_length=200)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "system": "AskforWrite AI Company OS",
        "status": "online",
        "docs_url": "/docs",
        "health_url": "/health",
        "dashboard_url": "/dashboard/",
        "api_prefix": "/v1",
        "message": "Welcome to AskforWrite AI Company OS Gateway. Visit /dashboard/ for Owner UI or /docs for interactive Swagger UI."
    }


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as error:
        raise HTTPException(status_code=503, detail="database unavailable") from error
    return {"status": "healthy", "capability": "offline_discovery", "database": "connected"}


@app.get("/v1/project/status")
def get_project_status(
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    db_counts = {
        "tasks": db.query(TaskRecord).count(),
        "leads": db.query(LeadRecordRow).count(),
        "research_records": db.query(ResearchRecord).count(),
        "requirements": db.query(RequirementRecord).count(),
        "proposals": db.query(ProposalRecord).count(),
        "approval_requests": db.query(ApprovalRequest).count(),
        "delivery_records": db.query(DeliveryRecord).count(),
        "audit_logs": db.query(AuditLog).count(),
        "conversations": db.query(ConversationRecord).count(),
        "idempotency_records": db.query(IdempotencyRecord).count(),
        "trust_blocks": db.query(TrustBlock).count(),
        "order_records": db.query(OrderRecord).count(),
        "seo_draft_records": db.query(SeoDraftRecord).count(),
        "marketing_campaign_records": db.query(MarketingCampaignRecord).count(),
        "organizations": db.query(OrganizationRecord).count(),
        "users": db.query(UserRecord).count(),
        "customers": db.query(CustomerRecord).count(),
        "subscriptions": db.query(SubscriptionRecord).count(),
        "invoices": db.query(InvoiceRecord).count(),
        "webhook_events": db.query(WebhookEventRecord).count(),
        "outreach_records": db.query(OutreachRecord).count(),
    }
    return {
        "system": "AskforWrite AI Company OS",
        "version": "0.2.0",
        "status": "operational",
        "caller": {
            "subject": principal.subject,
            "role": principal.role,
        },
        "operating_model": {
            "l0_human_authority": "Vipul Chobisa (Owner)",
            "l1_orchestrator": "Manager/CEO Agent (os_gateway)",
            "l2_active_specialists": [
                "Customer Discovery Agent",
                "Research Agent",
                "Sales & Requirement Agent",
                "Marketing Agent",
                "Editorial & Content Agent",
                "Operations & Finance Agent",
                "Revenue & Commercial Growth Agent",
                "Lead Discovery & Enrichment Agent",
                "Outreach & Dispatch Agent",
                "Auto-Provisioning Engine",
                "StockSense Warehouse & Inventory Specialist",
                "AgriTech Produce Quality Vision Specialist",
                "Urban Micro-Mobility & Logistics Specialist",
                "Autonomous Growth & Inbound Closer Specialist",
                "System Watchdog & Controlling Agent",
            ],
            "l3_connected_capabilities": [
                {
                    "name": "customer_discovery",
                    "status": "active",
                    "mode": "offline_synthetic",
                },
                {
                    "name": "evidence_research",
                    "status": "active",
                    "mode": "evidence_grounded",
                },
                {
                    "name": "sales_proposal",
                    "status": "active",
                    "mode": "owner_gated",
                },
                {
                    "name": "field_force_engine",
                    "status": "active",
                    "mode": "verified_readback",
                },
                {
                    "name": "afw_2030_trust_engine",
                    "status": "ready_for_pki_bridge",
                    "path": "afw 2030/ai 2030",
                    "asset": "ECDSA NIST P-256 Merkle Ledger",
                },
                {
                    "name": "seo_blog_copilot",
                    "status": "active",
                    "path": "antigravity/SEO-Blog-Automation-Copilot",
                    "asset": "WordPress 4-Site Publishing Pipeline",
                },
                {
                    "name": "node_marketing_suite",
                    "status": "active",
                    "path": "afw 2030/ai-marketing-suite.jsx",
                    "asset": "PixelBot & Multi-Channel Ad Generator",
                },
                {
                    "name": "askforwrite_academic_ask4",
                    "status": "active",
                    "path": "Documents/ask4/ASK4",
                    "asset": "4,850+ Article Archive & Payment Webhooks",
                },
                {
                    "name": "pixel_ai_ecosystem",
                    "status": "ready_for_bridge",
                    "path": "Documents/Pixel_AI_App",
                    "asset": "React Web + Backend + Signed Android APK",
                },
                {
                    "name": "revenue_commercial_engine",
                    "status": "active",
                    "mode": "razorpay_paypal_dual_gateway",
                    "asset": "Lead Diagnosis → Pitch → Payment → Auto-Provisioning",
                },
                {
                    "name": "lead_discovery_enrichment",
                    "status": "active",
                    "mode": "live_web_scraping",
                    "asset": "Multi-tenant Lead DB with Quota Enforcement",
                },
                {
                    "name": "outreach_dispatch",
                    "status": "active",
                    "mode": "owner_hitl_gated",
                    "asset": "SMTP Email Dispatch with Approval Workflow",
                },
                {
                    "name": "payment_webhook_provisioning",
                    "status": "active",
                    "mode": "auto_provision_on_capture",
                    "asset": "Razorpay & PayPal Webhook → Org + User + Invoice",
                },
                {
                    "name": "mango_quality_analytics",
                    "status": "active",
                    "mode": "computer_vision_colorimetry",
                    "asset": "HSV + GLCM Ripeness Grading & Brix Projection",
                },
                {
                    "name": "bike_rebalance_analytics",
                    "status": "active",
                    "mode": "spatiotemporal_regression",
                    "asset": "OLS Demand Forecasting & Station Net Churn Rebalancing",
                },
                {
                    "name": "warehouse_automation",
                    "status": "active",
                    "mode": "stocksense_pareto_abc_xyz",
                    "asset": "StockSense Inventory Audits, Dynamic ROP/EOQ & Dead Stock Detection",
                },
                {
                    "name": "growth_suite",
                    "status": "active",
                    "mode": "autonomous_growth_all_in_one",
                    "asset": "Pixel AI Studio, SEO Blog Staging & 24/7 Inbound Closer",
                },
                {
                    "name": "customer_portal",
                    "status": "active",
                    "mode": "tenant_self_service",
                    "asset": "Profile, Quota Usage, Invoices & Service Execution",
                },
                {
                    "name": "mobile_bridge",
                    "status": "active",
                    "mode": "pwa_offline_sync",
                    "asset": "Offline Sync, Service Worker & Mobile Telemetry",
                },
                {
                    "name": "system_watchdog_controller",
                    "status": "active",
                    "mode": "autonomous_supervisory_watchdog",
                    "asset": "Active Stalled Task, GPS Spoof, Quota Depletion & Trust Chain Supervisor",
                },
            ],
            "l4_data_layer": {
                "active_database": "company_os.db (SQLite dev) / PostgreSQL (production)",
                "schema_version": "20260926_0006_trust_blocks (head)",
                "counts": db_counts,
            },
        },
        "recovery_protocol": {
            "section": "Master Document Section 16",
            "last_verified_tests": "260+ passing (100% green)",
            "current_milestone": "Sprint 1 Complete: Catalog Completeness, StockSense Integration & Sales Alignment",
            "next_milestone": "Sprint 2: Watchdog Supervisor Agent & Automated Self-Healing",
        },
    }


@app.get("/v1/capabilities")
def list_capabilities(
    principal: APIPrincipal = Depends(require_manager),
) -> dict[str, object]:
    return {
        "system": "AskforWrite AI Company OS Capability Registry",
        "version": "0.1.0",
        "standard": "Master Document Section 7",
        "capabilities": [
            {
                "id": "customer_discovery",
                "version": "0.1.0",
                "description": "Scores synthetic offline leads with source provenance.",
                "permissions": ["manager"],
                "approval_gates": ["external_sales_outreach"],
                "data_mode": "offline_synthetic",
                "health_status": "healthy",
            },
            {
                "id": "research",
                "version": "0.1.0",
                "description": "Synthesizes supplied lead evidence without external research.",
                "permissions": ["manager"],
                "approval_gates": [],
                "data_mode": "evidence_grounded",
                "health_status": "healthy",
            },
            {
                "id": "sales_capture",
                "version": "0.1.0",
                "description": "Captures customer requirement conversations and drafts proposals.",
                "permissions": ["manager"],
                "approval_gates": ["proposal_delivery"],
                "data_mode": "internal_notes",
                "health_status": "healthy",
            },
            {
                "id": "delivery_field_force",
                "version": "0.1.0",
                "description": "Dispatches owner-approved tasks to AskforWrite Field Force Engine with status readback.",
                "permissions": ["manager"],
                "approval_gates": ["owner_approval"],
                "data_mode": "field_force_api",
                "health_status": "healthy",
            },
            {
                "id": "trust_ledger_audit",
                "version": "2.0.0",
                "description": "AFW 2030 Cryptographic Merkle ledger sealing and tamper verification.",
                "permissions": ["manager", "owner"],
                "approval_gates": [],
                "data_mode": "cryptographic_dag",
                "health_status": "healthy",
            },
            {
                "id": "seo_content_automation",
                "version": "1.0.0",
                "description": "Generates SEO drafts and publishes to 4 WordPress property sites.",
                "permissions": ["manager"],
                "approval_gates": ["live_publishing"],
                "data_mode": "multi_tenant_wordpress",
                "health_status": "healthy",
            },
            {
                "id": "marketing_campaign_suite",
                "version": "1.0.0",
                "description": "PixelBot conversational sales and multi-channel ad copy generation.",
                "permissions": ["manager"],
                "approval_gates": ["external_messaging"],
                "data_mode": "omnichannel_prompts",
                "health_status": "healthy",
            },
            {
                "id": "revenue_commercial_engine",
                "version": "1.0.0",
                "description": "Diagnoses prospect pain points and generates personalized commercial pitches with embedded Razorpay/PayPal checkout links.",
                "permissions": ["manager"],
                "approval_gates": ["owner_outreach_approval"],
                "data_mode": "live_payment_links",
                "health_status": "healthy",
            },
            {
                "id": "lead_discovery_enrichment",
                "version": "1.0.0",
                "description": "Multi-tenant live web scraping lead discovery with quota enforcement and domain deduplication.",
                "permissions": ["manager"],
                "approval_gates": [],
                "data_mode": "live_web_scraping",
                "health_status": "healthy",
            },
            {
                "id": "outreach_dispatch",
                "version": "1.0.0",
                "description": "Owner-HITL-gated email outreach drafting and SMTP dispatch with lifecycle tracking.",
                "permissions": ["manager", "owner"],
                "approval_gates": ["owner_dispatch_approval"],
                "data_mode": "smtp_email",
                "health_status": "healthy",
            },
            {
                "id": "payment_auto_provisioning",
                "version": "1.0.0",
                "description": "Auto-provisions Organization, User, and Invoice records on confirmed Razorpay/PayPal webhook payment capture.",
                "permissions": ["system"],
                "approval_gates": [],
                "data_mode": "webhook_triggered",
                "health_status": "healthy",
            },
            {
                "id": "mango_quality_analytics",
                "version": "1.0.0",
                "description": "Computer vision quality grading, HSV/GLCM colorimetry & Brix projection for fresh produce.",
                "permissions": ["manager", "portal_user"],
                "approval_gates": [],
                "data_mode": "computer_vision",
                "health_status": "healthy",
            },
            {
                "id": "bike_rebalance_analytics",
                "version": "1.0.0",
                "description": "Hourly micro-mobility demand forecasting (OLS/VIF) & dynamic station rebalancing dispatch.",
                "permissions": ["manager", "portal_user"],
                "approval_gates": [],
                "data_mode": "spatiotemporal_regression",
                "health_status": "healthy",
            },
            {
                "id": "warehouse_automation",
                "version": "2.4.0",
                "description": "StockSense Pareto ABC-XYZ segmentation, dynamic ROP/EOQ reorder plan & dead stock alerts.",
                "permissions": ["manager", "portal_user"],
                "approval_gates": [],
                "data_mode": "stocksense_engine",
                "health_status": "healthy",
            },
            {
                "id": "growth_suite",
                "version": "1.0.0",
                "description": "Pixel AI visual asset generation, SEO blog staging & 24/7 autonomous inbound sales closer.",
                "permissions": ["manager", "portal_user"],
                "approval_gates": ["external_messaging"],
                "data_mode": "omnichannel_growth",
                "health_status": "healthy",
            },
            {
                "id": "customer_portal",
                "version": "1.0.0",
                "description": "Self-service tenant profile, usage analytics, billing history, and modular service execution.",
                "permissions": ["portal_user", "manager", "owner"],
                "approval_gates": [],
                "data_mode": "tenant_saas",
                "health_status": "healthy",
            },
            {
                "id": "mobile_bridge",
                "version": "1.0.0",
                "description": "PWA manifest, offline queue synchronization, and field mobile telemetry bridge.",
                "permissions": ["mobile_user", "manager"],
                "approval_gates": [],
                "data_mode": "offline_pwa",
                "health_status": "healthy",
            },
            {
                "id": "system_watchdog_controller",
                "version": "1.0.0",
                "description": "L1 active monitoring, stalled task detection, GPS spoof alert, quota exhaustion, and trust chain integrity supervisor.",
                "permissions": ["manager", "owner"],
                "approval_gates": [],
                "data_mode": "live_supervisory_scan",
                "health_status": "healthy",
            },
        ],
    }


@app.get("/v1/discovery/schema")
def discovery_schema() -> dict[str, object]:
    return {
        "name": "customer_discovery",
        "version": "0.1.0",
        "description": "Scores synthetic offline leads with source provenance.",
        "permissions": ["manager"],
        "approval_gates": ["external_sales_outreach"],
        "data_mode": "offline_synthetic",
        "health_status": "healthy",
    }


@app.post("/v1/discovery/execute")
def execute_discovery_endpoint(
    payload: DiscoveryRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="X-Correlation-ID is too long")
    try:
        return execute_discovery(
            db=db,
            objective=payload.objective,
            limit=payload.limit,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            agent_id=principal.subject,
        )
    except IdempotencyConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/v1/discovery/status/{task_id}")
def get_discovery_status(
    task_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    task = db.get(TaskRecord, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task.id,
        "correlation_id": task.correlation_id,
        "status": task.status,
        "result": task.result,
    }


@app.get("/v1/discovery/leads")
def list_discovery_leads(
    min_fit: float = Query(default=0.0, ge=0.0, le=1.0),
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    query = db.query(LeadRecordRow).filter(LeadRecordRow.fit_score >= min_fit)
    if status:
        query = query.filter(LeadRecordRow.status == status)
    leads = query.order_by(LeadRecordRow.fit_score.desc()).limit(limit).all()
    return {
        "count": len(leads),
        "leads": [{
            "lead_id": lead.id,
            "company": lead.company,
            "website": lead.website,
            "industry": lead.industry,
            "geography": lead.geography,
            "observed_signals": lead.observed_signals,
            "sources": lead.sources,
            "product_match": lead.product_match,
            "fit_score": lead.fit_score,
            "confidence": lead.confidence,
            "public_contact_channel": lead.public_contact_channel,
            "recommended_next_step": lead.recommended_next_step,
            "do_not_contact": lead.do_not_contact,
            "status": lead.status,
        } for lead in leads],
    }


@app.get("/v1/discovery/audit/{task_id}")
def get_discovery_audit(
    task_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if db.get(TaskRecord, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    logs = db.query(AuditLog).filter(
        AuditLog.task_id == task_id,
    ).order_by(AuditLog.id.asc()).all()
    return {
        "task_id": task_id,
        "logs": [{
            "correlation_id": log.correlation_id,
            "agent_id": log.agent_id,
            "capability": log.capability_name,
            "action": log.action,
            "input": log.input_payload,
            "output": log.output_payload,
            "status": log.status,
            "created_at": log.created_at.isoformat(),
        } for log in logs],
    }


@app.get("/v1/research/schema")
def research_schema() -> dict[str, object]:
    return {
        "name": "research",
        "version": "0.1.0",
        "description": "Synthesizes supplied lead evidence without external research.",
        "permissions": ["manager"],
        "external_research_performed": False,
        "health_status": "healthy",
    }


@app.post("/v1/research/leads/{lead_id}/execute")
def execute_research_endpoint(
    lead_id: str,
    payload: ResearchExecutePayload,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="X-Correlation-ID is too long")
    try:
        return execute_research(
            db=db,
            lead_id=lead_id,
            idempotency_key=payload.idempotency_key,
            requested_by=principal.subject,
            correlation_id=correlation_id,
        )
    except ResearchConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ResearchNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/v1/research/leads/{lead_id}")
def get_lead_research(
    lead_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    record = db.query(ResearchRecord).filter_by(lead_id=lead_id).order_by(
        ResearchRecord.created_at.desc(),
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Research not found")
    return {
        "research_id": record.id,
        "lead_id": record.lead_id,
        "task_id": record.task_id,
        "synthesis": record.synthesis,
        "analysis": record.analysis,
        "sources": record.sources,
        "external_research_performed": False,
    }


@app.post("/v1/manager/execute")
def execute_manager_endpoint(
    payload: ManagerExecutePayload,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="X-Correlation-ID is too long")
    try:
        return execute_manager_workflow(
            db=db,
            objective=payload.objective,
            limit=payload.limit,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            manager_id=principal.subject,
        )
    except ManagerConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/v1/manager/status/{task_id}")
def get_manager_status(
    task_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    task = db.get(TaskRecord, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task.id,
        "correlation_id": task.correlation_id,
        "status": task.status,
        "result": task.result,
    }


@app.post("/v1/approvals")
def create_approval_request(
    payload: ApprovalRequestPayload,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="X-Correlation-ID is too long")
    try:
        return request_approval(
            db=db,
            task_id=payload.task_id,
            lead_id=payload.lead_id,
            action=payload.action,
            detail=payload.detail,
            idempotency_key=payload.idempotency_key,
            requested_by=principal.subject,
            correlation_id=correlation_id,
        )
    except ApprovalConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ApprovalNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/v1/approvals")
def list_approval_requests(
    status: Literal["PENDING", "APPROVED", "REJECTED"] = Query(default="PENDING"),
    limit: int = Query(default=100, ge=1, le=500),
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    approvals = db.query(ApprovalRequest).filter_by(status=status).order_by(
        ApprovalRequest.created_at.asc(),
    ).limit(limit).all()
    return {
        "count": len(approvals),
        "approvals": [{
            "approval_id": approval.id,
            "task_id": approval.task_id,
            "lead_id": approval.lead_id,
            "action": approval.action,
            "detail": approval.detail,
            "status": approval.status,
            "requested_by": approval.requested_by,
            "created_at": approval.created_at.isoformat(),
        } for approval in approvals],
    }


@app.get("/v1/approvals/pending/count")
def get_pending_approval_count(
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Quick-check endpoint for the Owner dashboard: how many approvals need attention."""
    pending = db.query(ApprovalRequest).filter_by(status="PENDING").count()
    return {
        "pending_approvals": pending,
        "action_required": pending > 0,
        "review_url": "/v1/approvals?status=PENDING",
    }


@app.post("/v1/approvals/{approval_id}/decision")
@app.post("/v1/approvals/{approval_id}/decide")
def make_approval_decision(
    approval_id: str,
    payload: ApprovalDecisionPayload,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="X-Correlation-ID is too long")
    try:
        return decide_approval(
            db=db,
            approval_id=approval_id,
            decision=payload.decision,
            decided_by=principal.subject,
            correlation_id=correlation_id,
            decision_note=payload.reason,
        )
    except ApprovalConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ApprovalNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/v1/sales/execute")
def execute_sales_endpoint(
    payload: SalesExecutePayload,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="X-Correlation-ID is too long")
    try:
        return execute_sales_capture(
            db=db,
            lead_id=payload.lead_id,
            conversation_notes=payload.conversation_notes,
            channel=payload.channel,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            agent_id=principal.subject,
        )
    except SalesConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SalesNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/v1/sales/requirements")
def list_sales_requirements(
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    query = db.query(RequirementRecord)
    if status:
        query = query.filter(RequirementRecord.status == status)
    requirements = query.order_by(RequirementRecord.created_at.desc()).limit(limit).all()
    return {
        "count": len(requirements),
        "requirements": [{
            "requirement_id": requirement.id,
            "lead_id": requirement.lead_id,
            "conversation_id": requirement.conversation_id,
            "task_id": requirement.task_id,
            "customer_company": requirement.customer_company,
            "stated_needs": requirement.stated_needs,
            "has_budget_signal": requirement.has_budget_signal,
            "has_timeline": requirement.has_timeline,
            "constraints": requirement.constraints,
            "product_match": requirement.product_match,
            "priority": requirement.priority,
            "status": requirement.status,
        } for requirement in requirements],
    }


@app.get("/v1/sales/proposals/{requirement_id}")
def get_sales_proposal(
    requirement_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    proposal = db.query(ProposalRecord).filter_by(
        requirement_id=requirement_id,
    ).order_by(ProposalRecord.created_at.desc()).first()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {
        "proposal_id": proposal.id,
        "task_id": proposal.task_id,
        "requirement_id": proposal.requirement_id,
        "lead_id": proposal.lead_id,
        "title": proposal.title,
        "summary": proposal.summary,
        "scope": proposal.scope,
        "pricing_model": proposal.pricing_model,
        "status": proposal.status,
        "external_delivery_performed": False,
    }


@app.post("/v1/delivery/execute")
async def execute_delivery_endpoint(
    payload: DeliveryExecutePayload,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
    field_force_client: FieldForceClient = Depends(get_field_force_client),
) -> dict[str, object]:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="X-Correlation-ID is too long")
    try:
        return await execute_delivery(
            db=db,
            proposal_id=payload.proposal_id,
            assigned_to=payload.assigned_to,
            due_date=payload.due_date.isoformat() if payload.due_date else None,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            manager_id=principal.subject,
            client=field_force_client,
        )
    except DeliveryConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DeliveryNotApproved as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except DeliveryNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/v1/delivery/status/{task_id}")
def get_delivery_status(
    task_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    task = db.get(TaskRecord, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Delivery task not found")
    records = db.query(DeliveryRecord).filter_by(task_id=task_id).all()
    return {
        "task_id": task.id,
        "correlation_id": task.correlation_id,
        "status": task.status,
        "result": task.result,
        "delivery_records": [{
            "proposal_id": record.proposal_id,
            "customer_company": record.customer_company,
            "summary": record.summary,
            "evidence": record.evidence,
            "status": record.status,
            "delivered_at": record.delivered_at.isoformat(),
        } for record in records],
    }


@app.get("/v1/trust/verify")
def verify_trust_chain(
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Cryptographically verifies the full SHA-256 Merkle hash chain

    and ECDSA NIST P-256 digital signatures from Genesis to Tip.
    """
    result = verify_chain_integrity(db)
    return {
        "system": "AskforWrite AI Company OS Trust Ledger",
        "protocol": "AFW-COMPANY-OS-TRUST-CHAIN-V2",
        "chain_valid": result["chain_valid"],
        "total_blocks": result["total_blocks"],
        "genesis_hash": result["genesis_hash"],
        "tip_index": result["tip_index"],
        "tip_hash": result["tip_hash"],
        "errors": result["errors"],
        "verified_by": principal.subject,
    }


@app.post("/v1/orders/ingest")
async def ingest_order_endpoint(
    request: "Request",
    x_correlation_id: str | None = Header(default=None),
    x_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="X-Correlation-ID is too long")

    # Read raw body for HMAC verification, then validate through Pydantic
    raw_body = (await request.body()).decode("utf-8")
    try:
        payload = OrderIngestPayload.model_validate_json(raw_body)
    except Exception as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    import os
    secret = os.environ.get("ASK4_WEBHOOK_SECRET")

    # Strip 'sha256=' prefix if present
    sig = x_signature
    if sig and sig.startswith("sha256="):
        sig = sig[7:]

    try:
        return ingest_order(
            db=db,
            transaction_id=payload.transaction_id,
            amount=payload.amount,
            currency=payload.currency,
            customer_email=payload.customer_email,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            secret=secret,
            signature=sig,
            raw_payload=raw_body if secret else None,
        )
    except OrderValidationFailed as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except OrderConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/v1/orders/{transaction_id}/fulfill")
def fulfill_order_endpoint(
    transaction_id: str,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Fulfill a confirmed order: complete task, update order to FULFILLED, and cryptographically seal TrustBlock."""
    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="X-Correlation-ID is too long")
    try:
        return fulfill_order(
            db=db,
            transaction_id=transaction_id,
            correlation_id=correlation_id,
            fulfilled_by=principal.subject,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/v1/seo/generate-draft")
def seo_generate_draft_endpoint(
    payload: SeoDraftPayload,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="X-Correlation-ID is too long")
    
    try:
        return execute_seo_draft(
            db=db,
            target_network=payload.target_network,
            keywords=payload.keywords,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            agent_id=principal.subject,
        )
    except SeoConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/v1/marketing/generate-campaign")
def marketing_generate_campaign_endpoint(
    payload: MarketingCampaignPayload,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="X-Correlation-ID is too long")
    
    try:
        return execute_marketing_campaign(
            db=db,
            campaign_type=payload.campaign_type,
            target_audience=payload.target_audience,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            agent_id=principal.subject,
        )
    except MarketingConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/v1/seo/networks")
def get_seo_networks_endpoint(
    principal: APIPrincipal = Depends(require_manager),
) -> dict[str, object]:
    """List 4 owned media networks supported by WordPress publisher bridge."""
    return {
        "networks": get_supported_networks(),
        "total_networks": len(get_supported_networks()),
    }


@app.post("/v1/seo/drafts/{draft_id}/publish")
def publish_seo_draft_endpoint(
    draft_id: str,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Publish an SEO draft to its target WordPress network and cryptographically seal TrustBlock."""
    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(status_code=422, detail="X-Correlation-ID is too long")
    try:
        return publish_seo_draft_to_wordpress(
            db=db,
            draft_id=draft_id,
            correlation_id=correlation_id,
            published_by=principal.subject,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/v1/orders")
def list_orders_endpoint(
    status: str | None = None,
    limit: int = 100,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """List customer orders, optionally filtered by status (e.g. CONFIRMED, FULFILLED)."""
    orders = list_orders(db=db, status=status, limit=limit)
    return {
        "orders": orders,
        "count": len(orders),
        "status_filter": status,
    }


@app.post("/v1/orders/fulfill-pending")
def fulfill_pending_orders_endpoint(
    limit: int = 50,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Batch-fulfill all pending confirmed orders with LLM manifest synthesis and cryptographic TrustBlocks."""
    return fulfill_pending_orders(
        db=db,
        limit=limit,
        fulfilled_by=principal.subject,
    )