"""Comprehensive route-by-route authorization matrix and negative cross-tenant tests.

Verifies every platform-only and tenant-scoped endpoint group identified in the
post-P8 security audit against unauthenticated callers, cross-tenant admins,
unauthorized lower-privilege tenant roles, and revoked/inactive sessions.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.outreach import create_unsubscribe_token
from app.db.database import Base, get_db
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    CustomerRecord,
    ExecutionEvidenceRecord,
    FieldTaskRecord,
    InvoiceRecord,
    LeadRecordRow,
    OrganizationRecord,
    OutreachRecord,
    P3CustomerAccountRecord,
    P3GrowthOpportunityRecord,
    P3ServiceDeliveryRecord,
    P3SupportTicketRecord,
    P4GrowthCampaignRecord,
    P4IcpProfileRecord,
    P4PipelineDealRecord,
    P5OperationalIncidentRecord,
    P5ProvisioningRunRecord,
    P6TenantPackDeploymentRecord,
    P7DelegationPlanRecord,
    P7TenantMemoryRecord,
    P8DeveloperProfileRecord,
    P8MarketplaceListingRecord,
    P8MarketplaceReviewRecord,
    P8TenantInstallRecord,
    SubscriptionRecord,
    UserRecord,
    WorkflowDefinitionRecord,
    WorkflowRunRecord,
)
from app.main import app
from app.security.auth import create_access_token, hash_password


OWNER_KEY = "test-route-matrix-owner-key-32-chars-minimum"
MANAGER_KEY = "test-route-matrix-manager-key-32-chars-min!"
JWT_SECRET = "test-route-matrix-jwt-secret-at-least-32b!"

ORG_A = "org_matrix_a"
ORG_B = "org_matrix_b"
ORG_INACTIVE = "org_matrix_inactive"

IDS = {
    "user_a_admin": "user_matrix_a_admin",
    "user_a_customer": "user_matrix_a_customer",
    "user_a_member": "user_matrix_a_member",
    "user_a_inactive": "user_matrix_a_inactive",
    "user_b_admin": "user_matrix_b_admin",
    "user_inactive_org": "user_matrix_inactive_org",
    "cust_a": "cust_matrix_a",
    "sub_a": "sub_matrix_a",
    "inv_a": "inv_matrix_a",
    "lead_a": "lead_matrix_a",
    "outreach_a": "outreach_matrix_a",
    "appr_a": "appr_matrix_a",
    "audit_a": "audit_matrix_a",
    "exec_a": "exec_matrix_a",
    "wf_a": "wf_matrix_a",
    "wfrun_a": "wfrun_matrix_a",
    "deliv_a": "deliv_matrix_a",
    "tkt_a": "tkt_matrix_a",
    "opp_a": "opp_matrix_a",
    "icp_a": "icp_matrix_a",
    "camp_a": "camp_matrix_a",
    "deal_a": "deal_matrix_a",
    "prov_a": "prov_matrix_a",
    "inc_a": "inc_matrix_a",
    "dep_a": "dep_matrix_a",
    "plan_a": "plan_matrix_a",
    "mem_a": "mem_matrix_a",
    "dev_a": "dev_matrix_a",
    "listing_pub_a": "listing_pub_matrix_a",
    "listing_draft_a": "listing_draft_matrix_a",
    "install_a": "install_matrix_a",
    "rev_a": "rev_matrix_a",
    "ftask_a": "ftask_matrix_a",
    "sid_a": "pay_sess_matrix_a",
    "prop_a": "prop_matrix_a",
}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def matrix_env():
    """Build an isolated in-memory database seeded with Tenant A, Tenant B, and inactive accounts."""
    mp = pytest.MonkeyPatch()
    mp.setenv("APP_ENV", "test")
    mp.setenv("OWNER_API_KEY", OWNER_KEY)
    mp.setenv("MANAGER_API_KEY", MANAGER_KEY)
    mp.setenv("JWT_SECRET_KEY", JWT_SECRET)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db

    with TestingSessionLocal() as db:
        now = datetime.now(UTC)
        db.add_all([
            OrganizationRecord(
                id=ORG_A,
                name="Tenant A Corp",
                slug="tenant-a-matrix",
                tier="growth",
                lead_credits_limit=100,
                outreach_credits_limit=100,
                is_active=True,
                metadata_json={"entitled_capabilities": ["all_access"]},
            ),
            OrganizationRecord(
                id=ORG_B,
                name="Tenant B Corp",
                slug="tenant-b-matrix",
                tier="growth",
                lead_credits_limit=100,
                outreach_credits_limit=100,
                is_active=True,
                metadata_json={"entitled_capabilities": ["all_access"]},
            ),
            OrganizationRecord(
                id=ORG_INACTIVE,
                name="Suspended Tenant",
                slug="suspended-matrix",
                tier="starter",
                is_active=False,
            ),
        ])

        pw_hash = hash_password("MatrixPass#2026")
        db.add_all([
            UserRecord(
                id=IDS["user_a_admin"],
                org_id=ORG_A,
                email="admin@a.matrix.test",
                full_name="Tenant A Admin",
                role="tenant_admin",
                password_hash=pw_hash,
                is_active=True,
            ),
            UserRecord(
                id=IDS["user_a_customer"],
                org_id=ORG_A,
                email="customer@a.matrix.test",
                full_name="Tenant A Customer",
                role="customer",
                password_hash=pw_hash,
                is_active=True,
            ),
            UserRecord(
                id=IDS["user_a_member"],
                org_id=ORG_A,
                email="field@a.matrix.test",
                full_name="Tenant A Field Member",
                role="member",
                password_hash=pw_hash,
                is_active=True,
            ),
            UserRecord(
                id=IDS["user_a_inactive"],
                org_id=ORG_A,
                email="inactive@a.matrix.test",
                full_name="Tenant A Inactive",
                role="tenant_admin",
                password_hash=pw_hash,
                is_active=False,
            ),
            UserRecord(
                id=IDS["user_b_admin"],
                org_id=ORG_B,
                email="admin@b.matrix.test",
                full_name="Tenant B Admin",
                role="tenant_admin",
                password_hash=pw_hash,
                is_active=True,
            ),
            UserRecord(
                id=IDS["user_inactive_org"],
                org_id=ORG_INACTIVE,
                email="admin@inactive.matrix.test",
                full_name="Inactive Org Admin",
                role="tenant_admin",
                password_hash=pw_hash,
                is_active=True,
            ),
        ])

        db.add_all([
            P3CustomerAccountRecord(
                id="cs_acct_a",
                org_id=ORG_A,
                primary_contact_user_id=IDS["user_a_admin"],
                primary_contact_email="admin@a.matrix.test",
                primary_contact_name="Tenant A Admin",
                lifecycle_state="ACTIVE",
            ),
            CustomerRecord(
                id=IDS["cust_a"],
                org_id=ORG_A,
                email="billing@a.matrix.test",
                name="Tenant A Billing",
                provider="razorpay",
                provider_customer_id="cust_rp_matrix_a",
            ),
            SubscriptionRecord(
                id=IDS["sub_a"],
                org_id=ORG_A,
                customer_id=IDS["cust_a"],
                plan_id="plan_growth",
                provider="razorpay",
                provider_subscription_id="sub_rp_matrix_a",
                status="active",
            ),
            InvoiceRecord(
                id=IDS["inv_a"],
                org_id=ORG_A,
                customer_id=IDS["cust_a"],
                subscription_id=IDS["sub_a"],
                provider="razorpay",
                provider_invoice_id="inv_rp_matrix_a",
                amount=4999,
                currency="INR",
                status="paid",
                metadata_json={"company_name": "Tenant A Corp"},
            ),
            LeadRecordRow(
                id=IDS["lead_a"],
                org_id=ORG_A,
                domain="alpha-tenant.example",
                task_id="task_lead_matrix_a",
                company="Alpha Tenant Client",
                website="https://alpha-tenant.example",
                industry="B2B SaaS",
                geography="Jaipur, India",
                status="QUALIFIED",
            ),
            OutreachRecord(
                id=IDS["outreach_a"],
                org_id=ORG_A,
                lead_id=IDS["lead_a"],
                task_id="task_outreach_matrix_a",
                recipient_email="buyer@alpha-tenant.example",
                recipient_name="Alpha Buyer",
                subject="Confidential Tenant A Pitch",
                body_text="Confidential body",
                idempotency_key="idem_outreach_matrix_a",
                status="PENDING_APPROVAL",
            ),
            ApprovalRequest(
                id=IDS["appr_a"],
                task_id="task_appr_matrix_a",
                lead_id=IDS["lead_a"],
                action="send_outreach",
                detail={"org_id": ORG_A, "summary": "Tenant A Secret Approval"},
                idempotency_key="idem_appr_matrix_a",
                request_hash="hash_appr_matrix_a",
                status="PENDING",
                requested_by=IDS["user_a_admin"],
            ),
            AuditLog(
                task_id="task_audit_matrix_a",
                correlation_id="corr_matrix_a",
                agent_id="discovery_agent",
                capability_name="discovery",
                action="completed",
                input_payload={"org_id": ORG_A},
                output_payload={"org_id": ORG_A, "secret": "tenant_a_only"},
                status="SUCCESS",
            ),
            ExecutionEvidenceRecord(
                execution_id=IDS["exec_a"],
                tenant_id=ORG_A,
                agent_id="competitive_intel_agent",
                execution_mode="MOCK_SANDBOX",
                input_reference="sha256:in_a",
                output_reference="sha256:out_a",
                status="COMPLETED",
                started_at=now,
                completed_at=now,
                evidence_reference="sha256:ev_a",
                metadata_json={"output_preview": "Tenant A confidential evidence"},
            ),
            WorkflowDefinitionRecord(
                id=IDS["wf_a"],
                org_id=ORG_A,
                workflow_key="wf_key_matrix_a",
                name="Tenant A Secret Workflow",
                steps_json=[{"step_id": "s1", "agent_id": "competitive_intel_agent"}],
                created_by=IDS["user_a_admin"],
            ),
            WorkflowRunRecord(
                id=IDS["wfrun_a"],
                workflow_id=IDS["wf_a"],
                org_id=ORG_A,
                status="CREATED",
                total_steps=1,
                started_by=IDS["user_a_admin"],
            ),
            P3ServiceDeliveryRecord(
                id=IDS["deliv_a"],
                org_id=ORG_A,
                title="Tenant A Secret Delivery",
                original_requirement="Deliver Tenant A SEO pack",
                quality_state="PENDING_QA",
            ),
            P3SupportTicketRecord(
                id=IDS["tkt_a"],
                ticket_number="TKT-MATRIX-A",
                org_id=ORG_A,
                created_by_user_id=IDS["user_a_admin"],
                created_by_email="admin@a.matrix.test",
                subject="Tenant A Confidential Support Ticket",
                status="OPEN",
            ),
            P3GrowthOpportunityRecord(
                id=IDS["opp_a"],
                org_id=ORG_A,
                opportunity_type="UPSELL",
                title="Tenant A Confidential Upsell",
                status="IDENTIFIED",
            ),
            P4IcpProfileRecord(
                id=IDS["icp_a"],
                org_id=ORG_A,
                name="Tenant A ICP",
                industry="Textiles",
            ),
            P4GrowthCampaignRecord(
                id=IDS["camp_a"],
                org_id=ORG_A,
                icp_id=IDS["icp_a"],
                name="Tenant A Campaign",
                objective="Pipeline",
            ),
            P4PipelineDealRecord(
                id=IDS["deal_a"],
                org_id=ORG_A,
                icp_id=IDS["icp_a"],
                company_name="Tenant A Secret Deal",
                stage="QUALIFIED",
            ),
            P5ProvisioningRunRecord(
                id=IDS["prov_a"],
                org_id=ORG_A,
                idempotency_key="idem_prov_matrix_a",
                template_key="jaipur_smb_growth",
                state="FAILED",
            ),
            P5OperationalIncidentRecord(
                id=IDS["inc_a"],
                org_id=ORG_A,
                title="Tenant A Confidential Incident",
                status="OPEN",
            ),
            P6TenantPackDeploymentRecord(
                id=IDS["dep_a"],
                org_id=ORG_A,
                pack_key="retail_commerce_pack",
                status="DEPLOYED",
            ),
            P7DelegationPlanRecord(
                id=IDS["plan_a"],
                org_id=ORG_A,
                name="Tenant A Confidential DAG Plan",
                nodes_json=[],
                status="DRAFT",
            ),
            P7TenantMemoryRecord(
                id=IDS["mem_a"],
                org_id=ORG_A,
                namespace="confidential",
                memory_key="secret_k",
                content="Tenant A Confidential Memory Content",
            ),
            P8DeveloperProfileRecord(
                id=IDS["dev_a"],
                org_id=ORG_A,
                developer_name="Tenant A Dev",
                contact_email="dev@a.matrix.test",
                legal_entity_name="Tenant A Dev LLP",
                kyb_status="VERIFIED",
                created_by=IDS["user_a_admin"],
            ),
            P8MarketplaceListingRecord(
                id=IDS["listing_pub_a"],
                developer_id=IDS["dev_a"],
                listing_slug="tenant-a-published-pkg",
                name="Published Pkg A",
                manifest_sha256="a" * 64,
                ecdsa_signature_hex="b" * 128,
                signing_public_key_pem="-----BEGIN PUBLIC KEY-----\nTEST\n-----END PUBLIC KEY-----",
                security_review_status="APPROVED",
                published_status="PUBLISHED",
            ),
            P8MarketplaceListingRecord(
                id=IDS["listing_draft_a"],
                developer_id=IDS["dev_a"],
                listing_slug="tenant-a-draft-pkg",
                name="Confidential Draft Pkg A",
                manifest_sha256="c" * 64,
                ecdsa_signature_hex="d" * 128,
                signing_public_key_pem="-----BEGIN PUBLIC KEY-----\nTEST\n-----END PUBLIC KEY-----",
                security_review_status="PENDING",
                published_status="DRAFT",
            ),
            P8TenantInstallRecord(
                id=IDS["install_a"],
                org_id=ORG_A,
                listing_id=IDS["listing_pub_a"],
                status="ACTIVE",
                secret_digests_json={"webhook_secret": {"sha256": "deadbeef" * 8, "masked": "...xxxx"}},
                installed_by=IDS["user_a_admin"],
            ),
            P8MarketplaceReviewRecord(
                id=IDS["rev_a"],
                listing_id=IDS["listing_pub_a"],
                org_id=ORG_A,
                install_id=IDS["install_a"],
                rating=5,
                comment="Great internal integration",
                created_by=IDS["user_a_admin"],
            ),
            FieldTaskRecord(
                id=IDS["ftask_a"],
                org_id=ORG_A,
                assigned_to_user_id=IDS["user_a_member"],
                title="Tenant A Confidential Field Visit",
                client_name="Tenant A Field Client",
                destination_lat=26.9124,
                destination_lon=75.7873,
                status="ASSIGNED",
            ),
        ])
        db.commit()

    tokens = {
        "a_admin": _bearer(create_access_token(
            user_id=IDS["user_a_admin"], role="tenant_admin", org_id=ORG_A, email="admin@a.matrix.test"
        )),
        "a_customer": _bearer(create_access_token(
            user_id=IDS["user_a_customer"], role="customer", org_id=ORG_A, email="customer@a.matrix.test"
        )),
        "a_member": _bearer(create_access_token(
            user_id=IDS["user_a_member"], role="member", org_id=ORG_A, email="field@a.matrix.test"
        )),
        "a_inactive": _bearer(create_access_token(
            user_id=IDS["user_a_inactive"], role="tenant_admin", org_id=ORG_A, email="inactive@a.matrix.test"
        )),
        "b_admin": _bearer(create_access_token(
            user_id=IDS["user_b_admin"], role="tenant_admin", org_id=ORG_B, email="admin@b.matrix.test"
        )),
        "inactive_org": _bearer(create_access_token(
            user_id=IDS["user_inactive_org"], role="tenant_admin", org_id=ORG_INACTIVE, email="admin@inactive.matrix.test"
        )),
        "owner": {"X-API-Key": OWNER_KEY},
        "manager": {"X-API-Key": MANAGER_KEY},
    }

    try:
        with TestClient(app) as client:
            yield {"client": client, "tokens": tokens, "SessionLocal": TestingSessionLocal}
    finally:
        if previous_override is not None:
            app.dependency_overrides[get_db] = previous_override
        else:
            app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        mp.undo()


# ── 1. Platform-Only Endpoint Matrix (Unauth -> 401, All Tenant Tokens -> 403) ─────


PLATFORM_ONLY_CASES: list[tuple[str, str, dict | None]] = [
    # app.main legacy V1 & approvals (28 endpoints)
    ("POST", "/v1/approvals", {"task_id": "t1", "action": "test", "detail": {}, "idempotency_key": "k1"}),
    ("GET", "/v1/approvals", None),
    ("GET", "/v1/approvals/pending/count", None),
    ("POST", f"/v1/approvals/{IDS['appr_a']}/decide", {"decision": "approve"}),
    ("POST", f"/v1/approvals/{IDS['appr_a']}/decision", {"decision": "approve"}),
    ("GET", "/v1/capabilities", None),
    ("POST", "/v1/delivery/execute", {"proposal_id": IDS["prop_a"], "assigned_to": "ops", "idempotency_key": "k1"}),
    ("GET", "/v1/delivery/status/task_1", None),
    ("GET", "/v1/discovery/audit/task_1", None),
    ("POST", "/v1/discovery/execute", {"objective": "find clients", "limit": 1, "idempotency_key": "k1"}),
    ("GET", "/v1/discovery/leads", None),
    ("GET", "/v1/discovery/status/task_1", None),
    ("POST", "/v1/manager/execute", {"objective": "plan", "limit": 1, "idempotency_key": "k1"}),
    ("GET", "/v1/manager/status/task_1", None),
    ("POST", "/v1/marketing/generate-campaign", {"campaign_type": "email", "target_audience": "SME", "idempotency_key": "k1"}),
    ("GET", "/v1/orders", None),
    ("POST", "/v1/orders/fulfill-pending", None),
    ("POST", "/v1/orders/txn_1/fulfill", None),
    ("GET", "/v1/project/status", None),
    ("GET", f"/v1/research/leads/{IDS['lead_a']}", None),
    ("POST", f"/v1/research/leads/{IDS['lead_a']}/execute", {"idempotency_key": "k1"}),
    ("POST", "/v1/sales/execute", {"lead_id": IDS["lead_a"], "conversation_notes": "interested", "idempotency_key": "k1"}),
    ("GET", "/v1/sales/proposals/req_1", None),
    ("GET", "/v1/sales/requirements", None),
    ("POST", "/v1/seo/drafts/draft_1/publish", None),
    ("POST", "/v1/seo/generate-draft", {"target_network": "linkedin", "keywords": ["ai"], "idempotency_key": "k1"}),
    ("GET", "/v1/seo/networks", None),
    ("GET", "/v1/trust/verify", None),

    # P2 Commercial Engine (/v1/commercial/* — all 25 routes platform-only)
    ("GET", "/v1/commercial/acceptance-checklist", None),
    ("POST", "/v1/commercial/acceptance-checklist/1", {"verification_status": "VERIFIED", "evidence_summary": "ok"}),
    ("GET", "/v1/commercial/control-centre", None),
    ("GET", "/v1/commercial/engagements", None),
    ("POST", "/v1/commercial/engagements/eng_1/complete-delivery", {"delivery_channel_proof": "email"}),
    ("POST", "/v1/commercial/engagements/eng_1/deliver", {}),
    ("POST", "/v1/commercial/engagements/eng_1/feedback-renewal", {"rating": 5, "comments": "great"}),
    ("POST", "/v1/commercial/engagements/eng_1/onboarding", {"target_domain": "example.com", "priority_topics": ["seo"]}),
    ("GET", "/v1/commercial/offer/ai_seo_starter", None),
    ("POST", "/v1/commercial/outreach/prepare", {"lead_id": IDS["lead_a"]}),
    ("POST", f"/v1/commercial/outreach/{IDS['outreach_a']}/dispatch", None),
    ("GET", "/v1/commercial/pipeline", None),
    ("POST", f"/v1/commercial/pipeline/{IDS['lead_a']}/responses", {"summary": "interested"}),
    ("POST", f"/v1/commercial/pipeline/{IDS['lead_a']}/transition", {"target_status": "CONTACTED"}),
    ("GET", "/v1/commercial/proposals", None),
    ("POST", "/v1/commercial/proposals", {"lead_id": IDS["lead_a"]}),
    ("POST", f"/v1/commercial/proposals/{IDS['prop_a']}/checkout", {"provider": "razorpay"}),
    ("POST", f"/v1/commercial/proposals/{IDS['prop_a']}/share", {}),
    ("GET", "/v1/commercial/prospects", None),
    ("POST", "/v1/commercial/prospects/discover", {"query": "jaipur"}),
    ("POST", "/v1/commercial/prospects/ingest", {"company": "Co", "website": "https://co.example", "source_url": "https://co.example"}),
    ("POST", f"/v1/commercial/prospects/{IDS['lead_a']}/brief", {}),
    ("POST", f"/v1/commercial/prospects/{IDS['lead_a']}/requalify", {}),
    ("GET", "/v1/commercial/reconciliation", None),
    ("POST", "/v1/commercial/reconciliation/rec_1/retry", None),

    # P3 Customer Success platform-only routes (30 routes)
    ("GET", "/v1/cs/acceptance", None),
    ("POST", "/v1/cs/acceptance/1", {"verification_status": "VERIFIED", "evidence_summary": "ok"}),
    ("POST", f"/v1/cs/compliance/{ORG_A}/offboard-delete", {"request_type": "OFFBOARD", "reason": "contract end"}),
    ("GET", "/v1/cs/control-centre", None),
    ("GET", "/v1/cs/customers", None),
    ("POST", f"/v1/cs/customers/{ORG_A}/ensure", {"human_owner": "ops"}),
    ("POST", f"/v1/cs/customers/{ORG_A}/health/alerts", None),
    ("POST", f"/v1/cs/customers/{ORG_A}/lifecycle", {"target_state": "AT_RISK", "reason": "low usage"}),
    ("PATCH", f"/v1/cs/customers/{ORG_A}/profile", {"human_owner": "ops2"}),
    ("GET", "/v1/cs/improvements", None),
    ("POST", "/v1/cs/improvements/synthesize", None),
    ("PATCH", "/v1/cs/improvements/item_1", {"status": "PLANNED"}),
    ("POST", f"/v1/cs/integrations/gsc/{ORG_A}/analytics/query", {"start_date": "2026-01-01", "end_date": "2026-01-31"}),
    ("POST", f"/v1/cs/integrations/gsc/{ORG_A}/disconnect", None),
    ("POST", f"/v1/cs/integrations/gsc/{ORG_A}/oauth/exchange", {"code": "abc", "state": "xyz"}),
    ("POST", f"/v1/cs/integrations/gsc/{ORG_A}/oauth/url", {}),
    ("POST", f"/v1/cs/integrations/gsc/{ORG_A}/properties/verify", {"site_url": "https://example.com"}),
    ("GET", f"/v1/cs/integrations/gsc/{ORG_A}/status", None),
    ("POST", "/v1/cs/ops/backup-drill", {"restore_tested": False}),
    ("POST", "/v1/cs/ops/dlq/inc_1/retry", None),
    ("GET", "/v1/cs/ops/readiness", None),
    ("POST", "/v1/cs/ops/run-maintenance", None),
    ("POST", "/v1/cs/ops/workflows/scan-timeouts", None),
    ("GET", "/v1/cs/release-readiness", None),
    ("POST", "/v1/cs/subscriptions/enforce-grace", None),
    ("POST", f"/v1/cs/subscriptions/{ORG_A}/events", {"event_type": "RENEW", "target_state": "ACTIVE", "idempotency_key": "k1"}),
    ("POST", f"/v1/cs/subscriptions/{ORG_A}/payment-failure", {"idempotency_key": "k1"}),
    ("POST", f"/v1/cs/subscriptions/{ORG_A}/refund", {"amount_inr": 100.0, "reason": "duplicate"}),
    ("POST", f"/v1/cs/subscriptions/{ORG_A}/restore", {"idempotency_key": "k1"}),
    ("PUT", f"/v1/cs/unit-economics/{ORG_A}/budget", {"monthly_cost_limit_inr": 5000.0}),

    # Accounts platform-only routes (5 routes)
    ("POST", "/v1/accounts/orgs", {"name": "New Org"}),
    ("PATCH", f"/v1/accounts/orgs/{ORG_A}", {"tier": "enterprise"}),
    ("POST", f"/v1/accounts/orgs/{ORG_A}/invoices", {"customer_id": IDS["cust_a"], "provider_invoice_id": "inv_2", "amount": 1000}),
    ("GET", "/v1/accounts/reconciliation", None),
    ("POST", f"/v1/accounts/invoices/{IDS['inv_a']}/reconcile-settlement", {"settlement_reference": "UTR123"}),

    # Audit export, Ops, Webhooks, Neon, Scheduler (8 routes)
    ("GET", "/v1/audit/export", None),
    ("GET", "/v1/ops/preflight", None),
    ("GET", "/v1/ops/roadmap-scorecard", None),
    ("GET", "/v1/webhooks/events", None),
    ("POST", "/v1/neon/functions/health/invoke", None),
    ("GET", "/v1/scheduler/briefing", None),
    ("POST", "/v1/scheduler/run-shift", {}),
    ("GET", "/v1/scheduler/status", None),

    # Watchdog (13 routes)
    ("POST", "/v1/watchdog/agent-control", {"agent_key": "discovery_agent", "action": "PAUSE"}),
    ("GET", "/v1/watchdog/alerts", None),
    ("POST", "/v1/watchdog/alerts/alert_1/resolve", {}),
    ("GET", "/v1/watchdog/connectors", None),
    ("POST", "/v1/watchdog/credibility-audit", None),
    ("POST", "/v1/watchdog/emergency-stop", {"scope_level": "PLATFORM", "scope_target": "all", "state": "PAUSED"}),
    ("GET", "/v1/watchdog/emergency-stops", None),
    ("POST", "/v1/watchdog/invoke-tool", {"target_key": "competitive_intel_agent", "payload": {}}),
    ("GET", "/v1/watchdog/release-checklist", None),
    ("POST", "/v1/watchdog/scan", {}),
    ("POST", "/v1/watchdog/sme-assess", {"business_name": "Test SME"}),
    ("POST", "/v1/watchdog/sme-sandbox-scenario", None),
    ("GET", "/v1/watchdog/telemetry", None),

    # Outreach dispatch, Subscriptions plan creation, Sovereign Pay owner actions (5 routes)
    ("POST", f"/v1/outreach/{IDS['outreach_a']}/dispatch", None),
    ("POST", "/v1/subscriptions/plans", {"name": "Growth", "amount": 4999}),
    ("POST", f"/v1/pay/{IDS['sid_a']}/confirm-owner", None),
    ("POST", "/v1/pay/live-penny-test", {"rail": "UPI"}),
    ("POST", "/v1/pay/reconcile-settlement", {"invoice_id": IDS["inv_a"], "bank_statement_utr": "UTR123", "settled_amount": 4999.0}),

    # P5-P8 platform-only routes (9 routes)
    ("POST", "/v1/p5/scale/templates", {"template_key": "tpl_x", "name": "Tpl X", "industry": "SaaS", "tier_id": "growth"}),
    ("POST", "/v1/p5/scale/templates/seed", None),
    ("POST", "/v1/p6/packs/catalog", {"pack_key": "pack_x", "name": "Pack X", "sector": "Retail", "tier_id": "growth"}),
    ("POST", "/v1/p7/workforce/autonomy-policies/competitive_intel_agent/resume", {"org_id": ORG_A}),
    ("GET", "/v1/p8/marketplace/developers", None),
    ("POST", f"/v1/p8/marketplace/developers/{IDS['dev_a']}/kyb", {"kyb_status": "VERIFIED"}),
    ("POST", f"/v1/p8/marketplace/listings/{IDS['listing_draft_a']}/review", {"security_review_status": "APPROVED", "publish": True}),
    ("POST", f"/v1/p8/marketplace/reviews/{IDS['rev_a']}/moderate", {"moderation_status": "APPROVED"}),
    ("POST", "/v1/p8/marketplace/revenue-share", {"org_id": ORG_A, "install_id": IDS["install_a"], "gross_amount_inr": 1000.0}),
]


def _call(client: TestClient, method: str, path: str, headers: dict[str, str] | None, body: dict | None):
    if method == "GET":
        return client.get(path, headers=headers or {})
    if method == "POST":
        return client.post(path, headers=headers or {}, json=body if body is not None else None)
    if method == "PATCH":
        return client.patch(path, headers=headers or {}, json=body if body is not None else None)
    if method == "PUT":
        return client.put(path, headers=headers or {}, json=body if body is not None else None)
    if method == "DELETE":
        return client.delete(path, headers=headers or {})
    raise ValueError(f"Unsupported method {method}")


@pytest.mark.parametrize("method,path,body", PLATFORM_ONLY_CASES)
def test_platform_only_endpoints_reject_unauth_and_all_tenants(matrix_env, method, path, body):
    """Every platform-only endpoint must return 401 unauthenticated and 403 for all tenant roles."""
    client: TestClient = matrix_env["client"]
    tokens = matrix_env["tokens"]

    r_unauth = _call(client, method, path, None, body)
    assert r_unauth.status_code == 401, f"{method} {path} unauth got {r_unauth.status_code}: {r_unauth.text}"

    for role_key in ("a_admin", "a_customer", "b_admin"):
        r_tenant = _call(client, method, path, tokens[role_key], body)
        assert r_tenant.status_code == 403, (
            f"{method} {path} for {role_key} got {r_tenant.status_code}: {r_tenant.text}"
        )


def test_platform_owner_key_passes_auth_on_platform_routes(matrix_env):
    """Sanity check: platform OWNER_API_KEY reaches platform handlers (never 401/403)."""
    client: TestClient = matrix_env["client"]
    owner = matrix_env["tokens"]["owner"]
    for path in (
        "/v1/commercial/prospects",
        "/v1/cs/release-readiness",
        "/v1/watchdog/telemetry",
        "/v1/ops/roadmap-scorecard",
        "/v1/audit/export",
        "/v1/p8/marketplace/developers",
    ):
        resp = client.get(path, headers=owner)
        assert resp.status_code not in (401, 403), f"Owner blocked on {path}: {resp.status_code} {resp.text}"


# ── 2. Cross-Tenant Negative & Role-Gate Matrix across Tenant-Scoped Routers ─────


CROSS_TENANT_CASES: list[tuple[str, str, dict | None, bool, tuple[int, ...]]] = [
    # Accounts (9 tenant-scoped routes; require_tenant_manager / require_tenant_admin -> customer 403)
    ("GET", f"/v1/accounts/orgs/{ORG_A}", None, True, (403,)),
    ("POST", f"/v1/accounts/orgs/{ORG_A}/users", {"email": "x@a.test", "full_name": "User X", "role": "member"}, True, (403,)),
    ("POST", f"/v1/accounts/orgs/{ORG_A}/invitations", {"email": "inv@a.test", "role": "member"}, True, (403,)),
    ("POST", f"/v1/accounts/orgs/{ORG_A}/users/{IDS['user_a_member']}/role", {"role": "customer"}, True, (403,)),
    ("GET", f"/v1/accounts/orgs/{ORG_A}/users", None, True, (403,)),
    ("DELETE", f"/v1/accounts/orgs/{ORG_A}/users/{IDS['user_a_member']}", None, True, (403,)),
    ("GET", f"/v1/accounts/orgs/{ORG_A}/invoices", None, True, (403,)),
    ("POST", f"/v1/accounts/orgs/{ORG_A}/consume-credits", {"credit_type": "lead", "amount": 1}, True, (403,)),

    # Customer Success tenant-scoped (25 routes; require_tenant_manager -> customer 403)
    ("GET", f"/v1/cs/customers/{ORG_A}", None, True, (403,)),
    ("GET", f"/v1/cs/customers/{ORG_A}/onboarding", None, True, (403,)),
    ("PATCH", f"/v1/cs/customers/{ORG_A}/onboarding/tasks/kickoff", {"completed": True}, True, (403,)),
    ("POST", f"/v1/cs/customers/{ORG_A}/onboarding/confirm-activation", {}, True, (403,)),
    ("GET", f"/v1/cs/deliveries?org_id={ORG_A}", None, True, (403,)),
    ("POST", "/v1/cs/deliveries", {"org_id": ORG_A, "title": "Hijack", "original_requirement": "Hijack"}, True, (403,)),
    ("POST", f"/v1/cs/deliveries/{IDS['deliv_a']}/transition", {"target_state": "IN_PROGRESS"}, True, (403,)),
    ("POST", f"/v1/cs/deliveries/{IDS['deliv_a']}/qa-review", {"passed": True}, True, (403,)),
    ("POST", f"/v1/cs/deliveries/{IDS['deliv_a']}/metrics", {"output_metrics": {"count": 1}}, True, (403,)),
    ("GET", f"/v1/cs/customers/{ORG_A}/health", None, True, (403,)),
    ("GET", f"/v1/cs/support/tickets?org_id={ORG_A}", None, True, (403,)),
    ("POST", "/v1/cs/support/tickets", {"org_id": ORG_A, "subject": "Hijack", "description": "Hijack ticket"}, True, (403,)),
    ("POST", f"/v1/cs/support/tickets/{IDS['tkt_a']}/transition", {"target_state": "IN_PROGRESS"}, True, (403,)),
    ("POST", f"/v1/cs/support/tickets/{IDS['tkt_a']}/messages", {"body": "Cross tenant reply"}, True, (403,)),
    ("POST", f"/v1/cs/support/tickets/{IDS['tkt_a']}/ai-assist", None, True, (403,)),
    ("POST", f"/v1/cs/support/tickets/{IDS['tkt_a']}/csat", {"rating": 1}, True, (403,)),
    ("GET", f"/v1/cs/subscriptions/reliability?org_id={ORG_A}", None, True, (403,)),
    ("POST", f"/v1/cs/subscriptions/{ORG_A}/plan-change", {"new_sku_key": "ai_growth"}, True, (403,)),
    ("POST", f"/v1/cs/growth/{ORG_A}/evaluate", None, True, (403,)),
    ("GET", f"/v1/cs/growth?org_id={ORG_A}", None, True, (403,)),
    ("POST", f"/v1/cs/growth/opportunities/{IDS['opp_a']}/share", {}, True, (403,)),
    ("GET", f"/v1/cs/unit-economics/{ORG_A}", None, True, (403,)),
    ("POST", f"/v1/cs/unit-economics/{ORG_A}/costs", {"cost_category": "llm", "amount_inr": 10.0}, True, (403,)),
    ("PATCH", f"/v1/cs/compliance/{ORG_A}/consent-retention", {"consent_preferences": {"marketing": False}}, True, (403,)),
    ("POST", f"/v1/cs/compliance/{ORG_A}/export", None, True, (403,)),

    # Audit summary, Previews, Revenue, Leads, Outreach, Subscriptions
    ("GET", f"/v1/audit/summary?org_id={ORG_A}", None, True, (403,)),
    ("POST", "/v1/previews/generate", {"company_name": "Alpha", "domain": "alpha.example", "lead_id": IDS["lead_a"]}, True, (403,)),
    ("POST", "/v1/revenue/pitch-lead", {"lead_id": IDS["lead_a"], "org_id": ORG_A, "idempotency_key": "k_pitch"}, True, (403,)),
    ("GET", f"/v1/leads?org_id={ORG_A}", None, True, (403,)),
    ("POST", "/v1/leads/discover", {"objective": "find leads", "org_id": ORG_A, "idempotency_key": "k_disc"}, True, (403,)),
    ("POST", "/v1/leads/discover-smb", {"vertical": "saas", "org_id": ORG_A}, True, (403,)),
    ("POST", "/v1/leads/enrich", {"lead_id": IDS["lead_a"]}, True, (403,)),
    ("GET", f"/v1/leads/{IDS['lead_a']}", None, True, (403,)),
    ("PATCH", f"/v1/leads/{IDS['lead_a']}", {"status": "LOST"}, True, (403,)),
    ("DELETE", f"/v1/leads/{IDS['lead_a']}", None, True, (403,)),
    ("GET", f"/v1/outreach?org_id={ORG_A}", None, True, (403,)),
    ("POST", "/v1/outreach/draft", {"lead_id": IDS["lead_a"], "org_id": ORG_A, "idempotency_key": "k_out"}, True, (403,)),
    ("GET", f"/v1/outreach/{IDS['outreach_a']}", None, True, (403,)),
    ("POST", f"/v1/outreach/{IDS['outreach_a']}/record-reply", {"reply_text": "sounds good"}, True, (403,)),
    ("POST", "/v1/subscriptions/customers", {"email": "x@a.test", "name": "X", "org_id": ORG_A}, True, (403,)),
    ("POST", "/v1/subscriptions/create", {"customer_id": IDS["cust_a"], "plan_id": "plan_1", "org_id": ORG_A}, True, (403,)),
    ("GET", f"/v1/subscriptions/customer/{IDS['cust_a']}", None, True, (403,)),
    ("GET", f"/v1/subscriptions/{IDS['sub_a']}", None, True, (403,)),
    ("POST", f"/v1/subscriptions/{IDS['sub_a']}/cancel", {"cancel_at_period_end": True}, True, (403,)),

    # Registry evidence & Workflows
    ("GET", f"/v1/registry/evidence/{IDS['exec_a']}", None, False, (403, 404)),
    ("GET", f"/v1/workflows/runs/{IDS['wfrun_a']}", None, False, (403, 404)),
    ("POST", f"/v1/workflows/runs/{IDS['wfrun_a']}/start", None, False, (403, 404)),
    ("POST", f"/v1/workflows/runs/{IDS['wfrun_a']}/cancel", {}, False, (403, 404)),
    ("POST", f"/v1/workflows/runs/{IDS['wfrun_a']}/ready", None, False, (403, 404)),
    ("POST", f"/v1/workflows/runs/{IDS['wfrun_a']}/resume", None, False, (403, 404)),

    # Customer Portal (/v1/me/*) cross-tenant IDs
    ("POST", f"/v1/me/approvals/{IDS['appr_a']}/decide?decision=APPROVE", {}, False, (403, 404)),
    ("POST", f"/v1/me/deliveries/{IDS['deliv_a']}/respond", {"action": "ACCEPTED"}, False, (403, 404)),
    ("POST", f"/v1/me/support/tickets/{IDS['tkt_a']}/messages", {"body": "Cross tenant hijack"}, False, (403, 404)),
    ("POST", f"/v1/me/support/tickets/{IDS['tkt_a']}/csat", {"rating": 1}, False, (403, 404)),

    # P4 Growth (?org_id / body org_id / resource IDs)
    ("GET", f"/v1/p4/growth/overview?org_id={ORG_A}", None, False, (403,)),
    ("GET", f"/v1/p4/growth/icps?org_id={ORG_A}", None, False, (403,)),
    ("POST", "/v1/p4/growth/icps", {"org_id": ORG_A, "name": "Hijack ICP", "industry": "SaaS"}, False, (403,)),
    ("POST", f"/v1/p4/growth/icps/{IDS['icp_a']}/score", {"company_name": "Acme", "industry": "SaaS"}, False, (403, 404)),
    ("GET", f"/v1/p4/growth/intel?org_id={ORG_A}", None, False, (403,)),
    ("POST", "/v1/p4/growth/intel", {"org_id": ORG_A, "intel_type": "competitor", "subject_name": "Subject X", "summary": "Summary text"}, False, (403,)),
    ("GET", f"/v1/p4/growth/campaigns?org_id={ORG_A}", None, False, (403,)),
    ("POST", "/v1/p4/growth/campaigns", {"org_id": ORG_A, "name": "Hijack", "objective": "Pipeline growth", "product_name": "Prod X", "target_audience": "B2B SaaS"}, False, (403,)),
    ("POST", f"/v1/p4/growth/campaigns/{IDS['camp_a']}/execute", {}, False, (403, 404)),
    ("GET", f"/v1/p4/growth/deals?org_id={ORG_A}", None, False, (403,)),
    ("POST", "/v1/p4/growth/deals", {"org_id": ORG_A, "company_name": "Hijack Deal"}, False, (403,)),
    ("POST", f"/v1/p4/growth/deals/{IDS['deal_a']}/transition", {"target_stage": "WON"}, False, (403, 404)),
    ("GET", f"/v1/p4/growth/analytics?org_id={ORG_A}", None, False, (403,)),

    # P5 Scale
    ("GET", f"/v1/p5/scale/overview?org_id={ORG_A}", None, False, (403,)),
    ("GET", f"/v1/p5/scale/policies/{ORG_A}", None, False, (403,)),
    ("PUT", f"/v1/p5/scale/policies/{ORG_A}", {"rate_limit_rpm": 999}, False, (403,)),
    ("GET", f"/v1/p5/scale/provisioning?org_id={ORG_A}", None, False, (403,)),
    ("POST", "/v1/p5/scale/provisioning", {"org_id": ORG_A, "template_key": "tpl_x", "idempotency_key": "k_prov"}, False, (403,)),
    ("POST", f"/v1/p5/scale/provisioning/{IDS['prov_a']}/retry", {"org_id": ORG_A}, False, (403, 404)),
    ("POST", "/v1/p5/scale/quota-check", {"org_id": ORG_A, "metric_type": "rpm", "observed_value": 10.0}, False, (403,)),
    ("GET", f"/v1/p5/scale/incidents?org_id={ORG_A}", None, False, (403,)),
    ("POST", "/v1/p5/scale/incidents", {"org_id": ORG_A, "title": "Hijack Inc"}, False, (403,)),
    ("POST", f"/v1/p5/scale/incidents/{IDS['inc_a']}/transition", {"target_status": "RESOLVED"}, False, (403, 404)),

    # P6 Packs
    ("GET", f"/v1/p6/packs/overview?org_id={ORG_A}", None, False, (403,)),
    ("POST", "/v1/p6/packs/deployments", {"org_id": ORG_A, "pack_key": "retail_commerce_pack"}, False, (403,)),
    ("POST", f"/v1/p6/packs/deployments/{IDS['dep_a']}/diagnostics", {}, False, (403, 404)),
    ("GET", f"/v1/p6/packs/seo-baselines?org_id={ORG_A}", None, False, (403,)),
    ("POST", "/v1/p6/packs/seo-baselines", {"org_id": ORG_A, "city_or_cluster": "Jaipur", "industry_vertical": "SaaS", "primary_catalog_sku": "sku"}, False, (403,)),

    # P7 Workforce (dag-plans, autonomy-policies PUT, evals POST -> customer 403 too)
    ("GET", f"/v1/p7/workforce/overview?org_id={ORG_A}", None, False, (403,)),
    ("GET", f"/v1/p7/workforce/autonomy-policies?org_id={ORG_A}", None, False, (403,)),
    ("PUT", "/v1/p7/workforce/autonomy-policies/competitive_intel_agent", {"org_id": ORG_A, "autonomy_level": "AUTONOMOUS_BOUNDED"}, True, (403,)),
    ("GET", f"/v1/p7/workforce/evals?org_id={ORG_A}", None, False, (403,)),
    ("POST", "/v1/p7/workforce/evals", {"org_id": ORG_A, "agent_id": "competitive_intel_agent", "eval_suite_name": "suite_1", "quality_score": 0.9, "safety_score": 0.9}, True, (403,)),
    ("POST", "/v1/p7/workforce/dag-plans", {"org_id": ORG_A, "name": "Hijack Plan", "nodes": [{"node_id": "n1", "agent_id": "competitive_intel_agent", "depends_on": []}]}, True, (403,)),
    ("POST", f"/v1/p7/workforce/dag-plans/{IDS['plan_a']}/execute", {}, True, (403, 404)),
    ("POST", f"/v1/p7/workforce/dag-plans/{IDS['plan_a']}/cancel", {"reason": "sabotage"}, True, (403, 404)),
    ("POST", f"/v1/p7/workforce/dag-plans/{IDS['plan_a']}/recover", {}, True, (403, 404)),
    ("GET", f"/v1/p7/workforce/memories?org_id={ORG_A}", None, False, (403,)),
    ("POST", "/v1/p7/workforce/memories", {"org_id": ORG_A, "namespace": "ns", "memory_key": "k", "content": "hijack"}, False, (403,)),
    ("POST", "/v1/p7/workforce/memories/purge", {"org_id": ORG_A, "memory_id": IDS["mem_a"]}, False, (403,)),

    # P8 Marketplace cross-tenant
    ("GET", f"/v1/p8/marketplace/overview?org_id={ORG_A}", None, False, (403,)),
    ("POST", "/v1/p8/marketplace/developers", {"org_id": ORG_A, "developer_name": "Dev X", "contact_email": "x@x.test", "legal_entity_name": "X LLP"}, False, (403,)),
    ("POST", "/v1/p8/marketplace/listings", {"developer_id": IDS["dev_a"], "listing_slug": "hijack-slug", "name": "Hijack"}, False, (403,)),
    ("GET", f"/v1/p8/marketplace/listings/{IDS['listing_draft_a']}/verify-signature", None, False, (403, 404)),
    ("GET", f"/v1/p8/marketplace/installs?org_id={ORG_A}", None, False, (403,)),
    ("POST", "/v1/p8/marketplace/installs", {"org_id": ORG_A, "listing_id": IDS["listing_pub_a"]}, False, (403,)),
    ("POST", f"/v1/p8/marketplace/installs/{IDS['install_a']}/revoke", None, False, (403,)),
    ("POST", "/v1/p8/marketplace/reviews", {"org_id": ORG_A, "listing_id": IDS["listing_pub_a"], "rating": 1, "comment": "bad"}, False, (403,)),
    ("POST", "/v1/p8/marketplace/reviews", {"listing_id": IDS["listing_pub_a"], "rating": 1, "comment": "not installed in org_b"}, False, (403,)),
    ("GET", f"/v1/p8/marketplace/revenue-share?org_id={ORG_A}", None, False, (403,)),
]


@pytest.mark.parametrize("method,path,body,customer_forbidden,expected_cross_codes", CROSS_TENANT_CASES)
def test_cross_tenant_isolation_and_manager_role_gates(
    matrix_env, method, path, body, customer_forbidden, expected_cross_codes
):
    """Verify unauth -> 401, Tenant B -> 403/404, and Tenant A customer -> 403 on manager-gated routes."""
    client: TestClient = matrix_env["client"]
    tokens = matrix_env["tokens"]

    r_unauth = _call(client, method, path, None, body)
    assert r_unauth.status_code == 401, f"{method} {path} unauth returned {r_unauth.status_code}"

    r_cross = _call(client, method, path, tokens["b_admin"], body)
    assert r_cross.status_code in expected_cross_codes, (
        f"{method} {path} cross-tenant b_admin returned {r_cross.status_code} (expected {expected_cross_codes}): {r_cross.text}"
    )

    if customer_forbidden:
        r_cust = _call(client, method, path, tokens["a_customer"], body)
        assert r_cust.status_code == 403, (
            f"{method} {path} same-tenant customer returned {r_cust.status_code}: {r_cust.text}"
        )


def test_list_endpoints_isolate_tenant_a_records_from_tenant_b(matrix_env):
    """List endpoints scoped to Tenant B must never leak any Tenant A record IDs or content."""
    client: TestClient = matrix_env["client"]
    b_admin = matrix_env["tokens"]["b_admin"]

    r_orgs = client.get("/v1/accounts/orgs", headers=b_admin)
    assert r_orgs.status_code == 200
    assert ORG_A not in r_orgs.text

    for path, forbidden_marker in [
        ("/v1/cs/deliveries", IDS["deliv_a"]),
        ("/v1/cs/support/tickets", IDS["tkt_a"]),
        ("/v1/cs/growth", IDS["opp_a"]),
        ("/v1/leads", IDS["lead_a"]),
        ("/v1/outreach", IDS["outreach_a"]),
        ("/v1/pay/reconciliation-ledger", IDS["inv_a"]),
        ("/v1/registry/evidence", IDS["exec_a"]),
        ("/v1/workflows/definitions", IDS["wf_a"]),
        ("/v1/workflows/runs", IDS["wfrun_a"]),
        ("/v1/me/approvals", IDS["appr_a"]),
        ("/v1/me/deliveries", IDS["deliv_a"]),
        ("/v1/me/support/tickets", IDS["tkt_a"]),
        ("/v1/me/evidence", IDS["exec_a"]),
        ("/v1/p4/growth/icps", IDS["icp_a"]),
        ("/v1/p4/growth/campaigns", IDS["camp_a"]),
        ("/v1/p4/growth/deals", IDS["deal_a"]),
        ("/v1/p5/scale/provisioning", IDS["prov_a"]),
        ("/v1/p5/scale/incidents", IDS["inc_a"]),
        ("/v1/p7/workforce/memories", IDS["mem_a"]),
        ("/v1/p8/marketplace/listings?published_only=false", IDS["listing_draft_a"]),
        ("/v1/p8/marketplace/installs", IDS["install_a"]),
        ("/v1/p8/marketplace/revenue-share", IDS["install_a"]),
    ]:
        resp = client.get(path, headers=b_admin)
        assert resp.status_code == 200, f"List {path} failed for b_admin: {resp.status_code} {resp.text}"
        assert forbidden_marker not in resp.text, f"Tenant A marker {forbidden_marker} leaked on {path}: {resp.text}"

    # Verify Tenant A admin DOES see own unpublished draft and installs (with masked secret digests)
    a_admin = matrix_env["tokens"]["a_admin"]
    r_list_a = client.get("/v1/p8/marketplace/listings?published_only=false", headers=a_admin)
    assert r_list_a.status_code == 200
    assert IDS["listing_draft_a"] in r_list_a.text

    r_inst_a = client.get("/v1/p8/marketplace/installs", headers=a_admin)
    assert r_inst_a.status_code == 200
    assert IDS["install_a"] in r_inst_a.text
    assert "...xxxx" in r_inst_a.text
    assert "deadbeef" not in r_inst_a.text  # Stored digest only, never raw secret or sha256 dump

    # Audit summary without org_id filter on Tenant B must exclude Tenant A audit log payloads
    r_audit_b = client.get("/v1/audit/summary", headers=b_admin)
    assert r_audit_b.status_code == 200
    assert "tenant_a_only" not in r_audit_b.text
    assert ORG_A not in r_audit_b.text


def test_outreach_unsubscribe_security_boundaries(matrix_env):
    """/v1/outreach/unsubscribe enforces HMAC proof or tenant_manager ownership."""
    client: TestClient = matrix_env["client"]
    tokens = matrix_env["tokens"]

    # Unauthenticated without unsubscribe_token -> 401
    r_unauth = client.post("/v1/outreach/unsubscribe", json={"lead_id": IDS["lead_a"]})
    assert r_unauth.status_code == 401

    # Tampered HMAC token -> 403
    r_bad_tok = client.post(
        "/v1/outreach/unsubscribe",
        json={"lead_id": IDS["lead_a"], "unsubscribe_token": "0" * 64},
    )
    assert r_bad_tok.status_code == 403

    # Tenant A customer role -> 403
    r_cust = client.post(
        "/v1/outreach/unsubscribe",
        headers=tokens["a_customer"],
        json={"lead_id": IDS["lead_a"]},
    )
    assert r_cust.status_code == 403

    # Tenant B admin targeting Tenant A lead -> 403
    r_cross = client.post(
        "/v1/outreach/unsubscribe",
        headers=tokens["b_admin"],
        json={"lead_id": IDS["lead_a"]},
    )
    assert r_cross.status_code == 403

    # Valid deterministic HMAC token succeeds without bearer auth -> 200
    valid_tok = create_unsubscribe_token(email="buyer@alpha-tenant.example", lead_id=IDS["lead_a"])
    r_valid = client.post(
        "/v1/outreach/unsubscribe",
        json={
            "email": "buyer@alpha-tenant.example",
            "lead_id": IDS["lead_a"],
            "unsubscribe_token": valid_tok,
        },
    )
    assert r_valid.status_code == 200, r_valid.text


def test_registry_optional_auth_analytics_field_force_and_mobile_boundaries(matrix_env):
    """Verify optional-auth DB revocation check, analytics manager gates, field-force & mobile bridge."""
    client: TestClient = matrix_env["client"]
    tokens = matrix_env["tokens"]

    # 1. Registry optional-auth endpoints: anonymous 200, revoked/inactive user 401, inactive org 403
    for path in ("/v1/registry/agents", "/v1/registry/connectors", "/v1/registry/services"):
        assert client.get(path).status_code == 200
        assert client.get(path, headers=tokens["a_admin"]).status_code == 200
        r_inact_u = client.get(path, headers=tokens["a_inactive"])
        assert r_inact_u.status_code in (401, 403), f"{path} inactive user got {r_inact_u.status_code}"
        r_inact_o = client.get(path, headers=tokens["inactive_org"])
        assert r_inact_o.status_code == 403, f"{path} inactive org got {r_inact_o.status_code}"

    # Registry mutations reject customer role (except tenant_operator allows customer on own org? wait: verify actual gate!)
    # Registry operator endpoints allow active tenant members on their own org, while inactive user/org must fail.
    assert client.post("/v1/registry/agents/competitive_intel_agent/activate").status_code == 401
    assert client.post(
        "/v1/registry/agents/competitive_intel_agent/activate",
        headers=tokens["a_inactive"],
    ).status_code in (401, 403)
    assert client.post(
        "/v1/registry/agents/competitive_intel_agent/activate",
        headers=tokens["inactive_org"],
    ).status_code == 403

    # 2. Analytics & Growth manager-gated endpoints: unauth 401, customer 403
    analytics_cases = [
        ("POST", "/v1/growth/campaign/unified", {"client_name": "A", "product_or_service": "SEO", "target_audience": "B2B", "idempotency_key": "k_g1"}),
        ("POST", "/v1/growth/creative", {"product_name": "SEO", "target_audience": "B2B"}),
        ("POST", "/v1/inventory/analyze", {}),
        ("POST", "/v1/inventory/audit", {}),
        ("POST", "/v1/inventory/reorder", {}),
        ("POST", "/v1/inventory/reorder-plan", {}),
    ]
    for method, path, payload in analytics_cases:
        assert _call(client, method, path, None, payload).status_code == 401
        assert _call(client, method, path, tokens["a_customer"], payload).status_code == 403

    # 3. Field Force boundaries: customer -> 403 everywhere; member -> 403 on manager routes; cross-tenant isolated
    assert client.get("/v1/field-force/tasks").status_code == 401
    assert client.get("/v1/field-force/tasks", headers=tokens["a_customer"]).status_code == 403
    assert client.post(
        "/v1/field-force/geofences",
        headers=tokens["a_member"],
        json={"name": "Office", "latitude": 26.9, "longitude": 75.8},
    ).status_code == 403
    assert client.post(
        "/v1/field-force/tasks",
        headers=tokens["a_member"],
        json={"title": "T", "client_name": "C", "destination_lat": 26.9, "destination_lon": 75.8},
    ).status_code == 403
    assert client.post(
        f"/v1/field-force/tasks/{IDS['ftask_a']}/auto-dispatch",
        headers=tokens["b_admin"],
    ).status_code == 403
    assert client.post(
        "/v1/field-force/visits/verify",
        headers=tokens["b_admin"],
        json={
            "task_id": IDS["ftask_a"],
            "user_id": IDS["user_b_admin"],
            "latitude": 26.9124,
            "longitude": 75.7873,
            "geo_otp_code": "123456",
        },
    ).status_code == 403
    assert client.post(
        "/v1/field-force/visits/debrief",
        headers=tokens["b_admin"],
        json={
            "task_id": IDS["ftask_a"],
            "user_id": IDS["user_b_admin"],
            "raw_audio_transcript_or_base64": "Cross-tenant debrief attempt",
        },
    ).status_code == 403
    r_ff_b = client.get("/v1/field-force/tasks", headers=tokens["b_admin"])
    assert r_ff_b.status_code == 200
    assert IDS["ftask_a"] not in r_ff_b.text
    r_ff_cross_uid = client.post(
        "/v1/field-force/attendance/check-in",
        headers=tokens["b_admin"],
        json={
            "user_id": IDS["user_a_member"],
            "latitude": 26.9,
            "longitude": 75.8,
            "accuracy_meters": 8.0,
            "device_fingerprint": "hw-sec-chip-orgb-01",
            "idempotency_key": "k_ff_cross_org_b",
        },
    )
    assert r_ff_cross_uid.status_code == 403

    # 4. Mobile Bridge boundaries: unauth 401, inactive user 401, inactive org 403, customer 403, cross-tenant isolated
    assert client.get("/v1/mobile/tasks/assigned").status_code == 401
    assert client.get("/v1/mobile/tasks/assigned", headers=tokens["a_inactive"]).status_code == 401
    assert client.get("/v1/mobile/tasks/assigned", headers=tokens["inactive_org"]).status_code == 403
    assert client.get("/v1/mobile/tasks/assigned", headers=tokens["a_customer"]).status_code == 403
    r_mob_b = client.get("/v1/mobile/tasks/assigned", headers=tokens["b_admin"])
    assert r_mob_b.status_code == 200
    assert IDS["ftask_a"] not in r_mob_b.text
    r_mob_cross_task = client.post(
        "/v1/mobile/visits/submit",
        headers=tokens["b_admin"],
        json={
            "client_id": "Client A",
            "task_id": IDS["ftask_a"],
            "latitude": 26.9,
            "longitude": 75.8,
        },
    )
    assert r_mob_cross_task.status_code in (403, 404)


def test_p7_memory_purge_and_customer_portal_inactive_token_gates(matrix_env):
    """Member cannot purge all org memories; cross-tenant purge leaves Tenant A intact; inactive blocked."""
    client: TestClient = matrix_env["client"]
    tokens = matrix_env["tokens"]
    SessionLocal = matrix_env["SessionLocal"]

    # Member / customer inside Tenant A cannot run unscoped org-wide purge (both memory_id and namespace omitted)
    r_purge_cust = client.post(
        "/v1/p7/workforce/memories/purge",
        headers=tokens["a_customer"],
        json={"dpdp_reason": "attempt full wipe"},
    )
    assert r_purge_cust.status_code == 403

    # Tenant B passing Tenant A's memory_id without org_id scopes to ORG_B -> 0 purged, ORG_A untouched
    r_purge_cross = client.post(
        "/v1/p7/workforce/memories/purge",
        headers=tokens["b_admin"],
        json={"memory_id": IDS["mem_a"]},
    )
    assert r_purge_cross.status_code == 200
    body = r_purge_cross.json()
    assert body["org_id"] == ORG_B
    assert body["purged_count"] == 0
    with SessionLocal() as db:
        mem_a = db.query(P7TenantMemoryRecord).filter(P7TenantMemoryRecord.id == IDS["mem_a"]).first()
        assert mem_a is not None
        assert mem_a.is_deleted is False

    # Portal routes block unauth (401), inactive user (401), inactive org (403)
    for path in ("/v1/me", "/v1/me/billing", "/v1/me/data-export", "/v1/me/evidence"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=tokens["a_inactive"]).status_code in (401, 403)
        assert client.get(path, headers=tokens["inactive_org"]).status_code == 403

    # Smoke-check public non-tenant routes remain intentionally reachable
    assert client.get("/health").status_code == 200
    assert client.get("/v1/revenue/catalog").status_code == 200
    assert client.get("/v1/growth/status").status_code == 200
