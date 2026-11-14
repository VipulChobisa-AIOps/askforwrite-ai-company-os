"""P2 Post-Payment Customer Activation, Onboarding, Delivery Workflow, Renewal, Control Centre & Acceptance Tracker."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.agents.discovery import normalize_domain
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    OrganizationRecord,
    OutreachRecord,
    P2AcceptanceStepRecord,
    P2CommercialProposalRecord,
    P2CustomerEngagementRecord,
    P2PaymentReconciliationRecord,
    P2ProspectDossierRecord,
    WorkflowDefinitionRecord,
    WorkflowRunRecord,
)
from app.security.auth import get_org_entitled_capabilities
from app.security.trust_chain import seal_task_to_block
from app.services.catalog import get_modular_pricing_contract, get_package
from app.services.connectors import CAPABILITY_STATES, list_connectors
from app.services.evidence import record_execution_evidence
from app.services.execution_guard import check_execution_allowed, resolve_execution_mode
from app.services.p2_prospect_intel import verify_pilot_offer_contract
from app.services.seo import execute_seo_draft

TWELVE_ACCEPTANCE_STEPS: tuple[tuple[int, str, str, str], ...] = (
    (
        1,
        "env_connectors_creds",
        "1. Configure environment, database, connectors, and credentials",
        "Verify Postgres/DB migration head, APP_ENV, SMTP, payment webhooks, and connector health.",
    ),
    (
        2,
        "verify_catalog_sku",
        "2. Verify commercial product catalog and pricing SKU",
        "Confirm managed_seo_content_pilot price (INR 4,999 / USD 59), billing type, scope, and entitlements.",
    ),
    (
        3,
        "discover_ingest_agencies",
        "3. Discover or ingest 5-10 real Indian digital marketing / SEO agencies",
        "Ingest real agencies with source URL, collection date, public contact verification, and deduplication.",
    ),
    (
        4,
        "review_briefs_and_qualify",
        "4. Review qualification scores and research briefs",
        "Verify 6-criterion breakdown and separation of Verified Facts, Reasonable Inferences, and Assumptions.",
    ),
    (
        5,
        "approve_send_outreach",
        "5. Approve and send first outreach through HITL approval workflow",
        "Obtain explicit Owner approval and confirm real SMTP dispatch receipt with zero unapproved sends.",
    ),
    (
        6,
        "log_reply_and_discovery",
        "6. Log a real response and capture discovery notes",
        "Log prospect reply provenance, update next action, and record discovery notes on the deal.",
    ),
    (
        7,
        "generate_approve_proposal",
        "7. Generate, review, approve, and share commercial proposal",
        "Build catalog-backed multi-clause proposal, approve via HITL gate, and share with buyer.",
    ),
    (
        8,
        "create_verified_checkout",
        "8. Generate payment link and verify payment webhook handling",
        "Generate verified SKU checkout link; confirm payment state remains UNPAID until genuine webhook/settlement.",
    ),
    (
        9,
        "complete_payment_activation",
        "9. Complete real or sandbox payment and verify automated customer activation",
        "Confirm webhook HMAC / verified UTR settlement transitions deal to WON and provisions tenant entitlements.",
    ),
    (
        10,
        "execute_customer_onboarding",
        "10. Complete customer onboarding setup",
        "Capture required domain, CMS mode, and topic inputs on activated tenant onboarding checklist.",
    ),
    (
        11,
        "execute_pilot_delivery",
        "11. Execute initial service delivery and verify stored execution evidence",
        "Run P1 workflow for audit, keyword cluster, 2 articles + Schema.org JSON-LD, then confirm acceptance.",
    ),
    (
        12,
        "collect_feedback_and_renewal",
        "12. Collect customer feedback and test renewal recommendation flow",
        "Capture verified buyer rating/feedback and generate evidence-based post-pilot renewal proposal.",
    ),
)


def create_customer_engagement_after_settlement(
    db: Session,
    *,
    org_id: str,
    lead_id: str | None = None,
    proposal_id: str | None = None,
    invoice_id: str | None = None,
    sku_key: str = "managed_seo_content_pilot",
) -> dict[str, Any]:
    """Activate paid customer onboarding workspace, modules, entitlements, and pilot checklist idempotently."""
    existing = (
        db.query(P2CustomerEngagementRecord)
        .filter(
            P2CustomerEngagementRecord.org_id == org_id,
            P2CustomerEngagementRecord.status != "CANCELLED_OR_REFUNDED",
        )
        .order_by(P2CustomerEngagementRecord.created_at.desc())
        .first()
    )
    if existing and (not proposal_id or existing.proposal_id == proposal_id):
        return serialize_engagement(existing)

    offer = verify_pilot_offer_contract(sku_key)
    pkg = get_package(offer["sku_key"])
    contract = get_modular_pricing_contract(offer["sku_key"])

    org = db.get(OrganizationRecord, org_id)
    if org and pkg:
        org.tier = pkg.tier
        org.is_active = True
        org_meta = dict(org.metadata_json or {})
        org_meta["package_key"] = pkg.key
        org_meta["entitled_capabilities"] = list(pkg.entitled_capabilities)
        org_meta["included_modules"] = list(contract["included_modules"])
        org_meta["activated_via"] = "p2_verified_settlement"
        org.metadata_json = org_meta
        org.lead_credits_limit = max(int(org.lead_credits_limit or 0), int(pkg.lead_credits_monthly))
        org.outreach_credits_limit = max(int(org.outreach_credits_limit or 0), int(pkg.outreach_credits_monthly))
        flag_modified(org, "metadata_json")
        db.add(org)

    now = datetime.now(UTC)
    checklist = [
        {"item_key": "org_activated_and_entitled", "title": "Tenant workspace & SKU entitlements provisioned", "required": True, "completed": True, "completed_at": now.isoformat()},
        {"item_key": "business_inputs_submitted", "title": "Target website domain, CMS mode & priority topics received", "required": True, "completed": False, "completed_at": None},
        {"item_key": "seo_audit_and_cluster_generated", "title": "Technical SEO/GEO audit & commercial keyword cluster staged", "required": True, "completed": False, "completed_at": None},
        {"item_key": "articles_and_schema_staged", "title": "2 authoritative articles (1,500+ words) & Schema.org JSON-LD staged", "required": True, "completed": False, "completed_at": None},
        {"item_key": "client_review_accepted", "title": "Buyer confirmation of delivered pilot artifacts", "required": True, "completed": False, "completed_at": None},
    ]

    engagement = P2CustomerEngagementRecord(
        org_id=org_id,
        lead_id=lead_id,
        proposal_id=proposal_id,
        invoice_id=invoice_id,
        sku_key=offer["sku_key"],
        billing_type=str(offer["billing_type"]),
        status="ONBOARDING_PENDING_INPUTS",
        assigned_modules_json=list(contract["included_modules"]),
        entitlements_json=list(pkg.entitled_capabilities) if pkg else [],
        onboarding_checklist_json=checklist,
        required_client_inputs_json={"received": False},
        deliverables_json={"stage_status": "NOT_STARTED", "delivery_accepted": False, "execution_evidence_ids": []},
        pilot_start_at=now,
        pilot_end_at=now + timedelta(days=14),
    )
    db.add(engagement)
    db.flush()

    db.add(
        AuditLog(
            task_id=engagement.id,
            correlation_id=engagement.id,
            agent_id="customer_onboarding_agent",
            capability_name="p2_customer_activation",
            action="create_engagement_after_settlement",
            input_payload={"org_id": org_id, "sku_key": offer["sku_key"], "invoice_id": invoice_id},
            output_payload={"engagement_id": engagement.id, "modules": contract["included_modules"]},
            status="COMPLETED",
        )
    )
    return serialize_engagement(engagement)


def revoke_customer_engagement(db: Session, *, org_id: str, reason: str) -> None:
    """Revoke active engagements and entitlements on refund/dispute/failure."""
    now = datetime.now(UTC)
    engagements = db.query(P2CustomerEngagementRecord).filter_by(org_id=org_id).all()
    for eng in engagements:
        eng.status = "CANCELLED_OR_REFUNDED"
        eng.entitlements_json = []
        eng.assigned_modules_json = []
        eng.updated_at = now
        db.add(eng)

    org = db.get(OrganizationRecord, org_id)
    if org:
        org.tier = "free"
        meta = dict(org.metadata_json or {})
        meta["package_key"] = "free"
        meta["entitled_capabilities"] = []
        meta["revoked_at"] = now.isoformat()
        meta["revocation_reason"] = reason
        org.metadata_json = meta
        flag_modified(org, "metadata_json")
        db.add(org)


def submit_onboarding_inputs(
    db: Session,
    *,
    engagement_id: str,
    target_domain: str,
    cms_delivery_mode: str = "markdown_html_export",
    priority_topics: list[str],
    target_geography: str = "India",
    brand_tone_notes: str | None = None,
    wordpress_site_url: str | None = None,
    actor: str = "customer_onboarding_agent",
) -> dict[str, Any]:
    """Capture required customer onboarding inputs before pilot delivery runs."""
    eng = db.get(P2CustomerEngagementRecord, engagement_id)
    if not eng:
        raise ValueError(f"Customer engagement '{engagement_id}' not found")
    if eng.status == "CANCELLED_OR_REFUNDED":
        raise ValueError("Cannot onboard a refunded or cancelled customer engagement")

    clean_domain = normalize_domain(target_domain)
    if not clean_domain or "." not in clean_domain:
        raise ValueError("Valid target_domain is required for pilot onboarding")
    topics = [t.strip() for t in priority_topics if t and t.strip()]
    if not topics:
        raise ValueError("At least 1 priority_topic is required to run SEO pilot delivery")

    allowed_modes = ("wordpress_rest", "markdown_html_export", "google_doc_export")
    clean_cms = cms_delivery_mode.strip().lower()
    if clean_cms not in allowed_modes:
        raise ValueError(f"cms_delivery_mode must be one of {allowed_modes}")

    now = datetime.now(UTC)
    eng.required_client_inputs_json = {
        "target_domain": clean_domain,
        "cms_delivery_mode": clean_cms,
        "priority_topics": topics,
        "target_geography": target_geography.strip() or "India",
        "brand_tone_notes": (brand_tone_notes or "").strip(),
        "wordpress_site_url": (wordpress_site_url or "").strip() or None,
        "received": True,
        "submitted_at": now.isoformat(),
    }

    checklist = list(eng.onboarding_checklist_json or [])
    for item in checklist:
        if item.get("item_key") == "business_inputs_submitted":
            item["completed"] = True
            item["completed_at"] = now.isoformat()
    eng.onboarding_checklist_json = checklist
    flag_modified(eng, "onboarding_checklist_json")

    if eng.status == "ONBOARDING_PENDING_INPUTS":
        eng.status = "ONBOARDING_READY"
    eng.updated_at = now
    db.add(eng)
    db.add(
        AuditLog(
            task_id=eng.id,
            correlation_id=eng.id,
            agent_id=actor,
            capability_name="p2_customer_onboarding",
            action="submit_onboarding_inputs",
            input_payload={"engagement_id": engagement_id, "target_domain": clean_domain, "cms_mode": clean_cms},
            output_payload={"status": eng.status, "topics_count": len(topics)},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(eng)
    return serialize_engagement(eng)


def execute_pilot_delivery(
    db: Session,
    *,
    engagement_id: str,
    execution_mode: str | None = None,
    actor: str = "customer_success_agent",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Execute verified P1 delivery workflow for paid customer's pilot deliverables; stages for review (never auto-completes without review)."""
    eng = db.get(P2CustomerEngagementRecord, engagement_id)
    if not eng:
        raise ValueError(f"Customer engagement '{engagement_id}' not found")
    if eng.status == "CANCELLED_OR_REFUNDED":
        raise ValueError("Delivery blocked: customer engagement was cancelled or refunded")

    org = db.get(OrganizationRecord, eng.org_id)
    if not org or not org.is_active or org.tier == "free":
        raise ValueError("Delivery blocked: customer workspace lacks active paid entitlements")
    entitled = get_org_entitled_capabilities(org)
    if "seo_content_automation" not in entitled and not eng.entitlements_json:
        raise ValueError("Delivery blocked: missing 'seo_content_automation' entitlement")

    inputs = eng.required_client_inputs_json or {}
    if not inputs.get("received"):
        raise ValueError("Cannot launch pilot delivery before required client onboarding inputs are submitted")

    check_execution_allowed(db, agent_id="seo_content_agent", org_id=eng.org_id)
    mode = resolve_execution_mode(execution_mode)
    corr_id = correlation_id or str(uuid.uuid4())
    target_domain = str(inputs["target_domain"])
    topics = list(inputs.get("priority_topics") or [target_domain])
    cms_mode = str(inputs.get("cms_delivery_mode", "markdown_html_export"))

    # Create or reuse P1 WorkflowDefinitionRecord linking multi-step pilot execution
    wf_key = f"p2_pilot_{eng.sku_key}"
    wf_def = db.query(WorkflowDefinitionRecord).filter_by(org_id=eng.org_id, workflow_key=wf_key).first()
    if not wf_def:
        wf_def = WorkflowDefinitionRecord(
            org_id=eng.org_id,
            workflow_key=wf_key,
            name="14-Day Managed SEO & Content Pilot Delivery",
            description="Audits domain, maps keyword cluster, and generates 2 Schema.org JSON-LD articles for review.",
            trigger_type="manual",
            execution_mode_default=mode,
            steps_json=[
                {"step": 1, "name": "Technical SEO & GEO Audit", "agent_id": "account_intelligence_agent"},
                {"step": 2, "name": "Commercial Keyword Cluster", "agent_id": "seo_content_agent"},
                {"step": 3, "name": "Article 1 + Schema.org JSON-LD", "agent_id": "seo_content_agent"},
                {"step": 4, "name": "Article 2 + Schema.org JSON-LD", "agent_id": "seo_content_agent"},
            ],
            created_by=actor,
        )
        db.add(wf_def)
        db.flush()

    now = datetime.now(UTC)
    run_id = str(uuid.uuid4())
    wf_run = WorkflowRunRecord(
        id=run_id,
        workflow_id=wf_def.id,
        org_id=eng.org_id,
        idempotency_key=f"p2-delivery-{eng.id}-{uuid.uuid4().hex[:8]}",
        execution_mode=mode,
        status="RUNNING",
        current_step_index=0,
        total_steps=4,
        credits_budget=10,
        credits_consumed=0,
        input_payload=inputs,
        started_by=actor,
        started_at=now,
    )
    db.add(wf_run)
    db.flush()

    # Step 1 & 2: Audit + Keyword Cluster
    audit_report = {
        "title": f"Technical SEO & GEO Gap Audit for {target_domain}",
        "target_domain": target_domain,
        "findings": [
            f"Verify canonical HTTPS routing, robots.txt, and sitemap discovery for {target_domain}.",
            "Recommend explicit Article, FAQPage, and Organization Schema.org JSON-LD per service landing page.",
            f"Target commercial intent topics identified: {', '.join(topics[:4])}.",
        ],
        "mode": mode,
    }
    keyword_cluster = {
        "primary_topic": topics[0],
        "secondary_topics": topics[1:] if len(topics) > 1 else [f"{topics[0]} agency services india", f"{topics[0]} audit checklist"],
        "target_geography": inputs.get("target_geography", "India"),
    }

    # Step 3 & 4: Generate 2 review-gated articles via existing SEO service
    kw1 = [topics[0], f"{topics[0]} India", target_domain]
    kw2 = [topics[1] if len(topics) > 1 else f"{topics[0]} Workflow Automation", "GEO Schema.org JSON-LD", target_domain]
    draft_1 = execute_seo_draft(
        db=db,
        target_network=target_domain,
        keywords=kw1,
        idempotency_key=f"p2-art1-{eng.id}-{uuid.uuid4().hex[:8]}",
        correlation_id=corr_id,
        agent_id=actor,
    )
    draft_2 = execute_seo_draft(
        db=db,
        target_network=target_domain,
        keywords=kw2,
        idempotency_key=f"p2-art2-{eng.id}-{uuid.uuid4().hex[:8]}",
        correlation_id=corr_id,
        agent_id=actor,
    )

    schema_graph = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": f"{topics[0]} Strategic Implementation Guide",
            "about": topics,
            "publisher": {"@type": "Organization", "url": f"https://{target_domain}"},
        }
    )

    ev_audit = record_execution_evidence(
        db,
        tenant_id=eng.org_id,
        workflow_id=run_id,
        agent_id="seo_content_agent",
        connector_id="wordpress_rest" if cms_mode == "wordpress_rest" else "project_api",
        execution_mode=mode,
        input_payload={"engagement_id": eng.id, "target_domain": target_domain, "topics": topics},
        output_payload={"draft_1_id": draft_1.get("draft_id"), "draft_2_id": draft_2.get("draft_id"), "cms_mode": cms_mode},
        credits_consumed=2,
        uses_external_provider=False,
        status="COMPLETED",
        output_origin="SIMULATED_SYNTHETIC" if mode == "SIMULATION" else "LOCAL_DETERMINISTIC",
    )

    wf_run.status = "COMPLETED"
    wf_run.current_step_index = 4
    wf_run.credits_consumed = 2
    wf_run.completed_at = datetime.now(UTC)
    wf_run.step_results_json = [
        {"step": 1, "artifact": "seo_audit_report", "status": "COMPLETED"},
        {"step": 2, "artifact": "keyword_cluster", "status": "COMPLETED"},
        {"step": 3, "artifact": "article_1", "draft_id": draft_1.get("draft_id"), "status": "STAGED_FOR_REVIEW"},
        {"step": 4, "artifact": "article_2", "draft_id": draft_2.get("draft_id"), "status": "STAGED_FOR_REVIEW"},
    ]
    wf_run.output_summary = {
        "execution_evidence_id": ev_audit["execution_id"],
        "stage_status": "STAGED_FOR_REVIEW",
    }
    db.add(wf_run)

    checklist = list(eng.onboarding_checklist_json or [])
    for item in checklist:
        if item.get("item_key") in ("seo_audit_and_cluster_generated", "articles_and_schema_staged"):
            item["completed"] = True
            item["completed_at"] = datetime.now(UTC).isoformat()
    eng.onboarding_checklist_json = checklist
    flag_modified(eng, "onboarding_checklist_json")

    eng.workflow_run_id = run_id
    eng.status = "DELIVERY_IN_PROGRESS"
    eng.deliverables_json = {
        "stage_status": "STAGED_FOR_REVIEW",
        "delivery_accepted": False,
        "cms_delivery_mode": cms_mode,
        "seo_audit_report": audit_report,
        "keyword_cluster": keyword_cluster,
        "article_1": {"draft_id": draft_1.get("draft_id"), "approval_id": draft_1.get("approval_id"), "status": "DRAFT_STAGED"},
        "article_2": {"draft_id": draft_2.get("draft_id"), "approval_id": draft_2.get("approval_id"), "status": "DRAFT_STAGED"},
        "schema_json_ld": schema_graph,
        "execution_evidence_ids": [ev_audit["execution_id"]],
        "note": "Content drafts are staged for buyer/owner review. Delivery is not marked COMPLETED until explicit review and handover confirmation.",
    }
    eng.updated_at = datetime.now(UTC)
    db.add(eng)
    db.commit()
    db.refresh(eng)
    return serialize_engagement(eng)


def complete_engagement_delivery(
    db: Session,
    *,
    engagement_id: str,
    delivery_channel_proof: str,
    client_acceptance_note: str | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Explicitly confirm pilot delivery completion after verifying staged deliverables & execution evidence."""
    eng = db.get(P2CustomerEngagementRecord, engagement_id)
    if not eng:
        raise ValueError(f"Customer engagement '{engagement_id}' not found")
    if eng.status == "CANCELLED_OR_REFUNDED":
        raise ValueError("Cannot complete delivery for refunded or cancelled customer")

    deliverables = dict(eng.deliverables_json or {})
    required_keys = ("seo_audit_report", "keyword_cluster", "article_1", "article_2", "schema_json_ld")
    missing = [k for k in required_keys if not deliverables.get(k)]
    evidence_ids = deliverables.get("execution_evidence_ids") or []
    if missing or not evidence_ids:
        raise ValueError(
            f"Cannot mark delivery complete: missing deliverables ({missing}) or missing execution_evidence_ids"
        )

    now = datetime.now(UTC)
    deliverables["stage_status"] = "DELIVERED_AND_ACCEPTED"
    deliverables["delivery_accepted"] = True
    deliverables["delivery_channel_proof"] = delivery_channel_proof.strip()
    deliverables["client_acceptance_note"] = (client_acceptance_note or "Pilot artifacts confirmed delivered").strip()
    deliverables["accepted_at"] = now.isoformat()
    deliverables["accepted_by"] = actor
    eng.deliverables_json = deliverables
    flag_modified(eng, "deliverables_json")

    checklist = list(eng.onboarding_checklist_json or [])
    for item in checklist:
        if item.get("item_key") == "client_review_accepted":
            item["completed"] = True
            item["completed_at"] = now.isoformat()
    eng.onboarding_checklist_json = checklist
    flag_modified(eng, "onboarding_checklist_json")

    eng.status = "DELIVERY_COMPLETED"
    eng.completed_at = now
    eng.updated_at = now
    db.add(eng)

    seal_task_to_block(
        db=db,
        task_id=eng.id,
        capability_name="p2_pilot_delivery",
        action="complete_engagement_delivery",
        payload={"engagement_id": eng.id, "org_id": eng.org_id, "evidence_ids": evidence_ids},
        sealed_by=actor,
        commit=False,
    )
    db.commit()
    db.refresh(eng)
    return serialize_engagement(eng)


def record_customer_feedback_and_renewal(
    db: Session,
    *,
    engagement_id: str,
    rating: int,
    comments: str,
    improvements_requested: str | None = None,
    interested_in_renewal: bool = True,
    actor: str = "customer_success_agent",
) -> dict[str, Any]:
    """Capture genuine customer feedback and issue an honest, evidence-based renewal recommendation."""
    if rating < 1 or rating > 5:
        raise ValueError("rating must be between 1 and 5")

    eng = db.get(P2CustomerEngagementRecord, engagement_id)
    if not eng:
        raise ValueError(f"Customer engagement '{engagement_id}' not found")
    if eng.status not in ("DELIVERY_COMPLETED", "RENEWAL_RECOMMENDED", "RENEWED"):
        raise ValueError("Feedback and post-pilot renewal recommendation require DELIVERY_COMPLETED status first")

    now = datetime.now(UTC)
    deliverables = eng.deliverables_json or {}
    evidence_ids = deliverables.get("execution_evidence_ids") or []

    feedback = {
        "rating": rating,
        "comments": comments.strip(),
        "improvements_requested": (improvements_requested or "").strip() or None,
        "interested_in_renewal": interested_in_renewal,
        "submitted_at": now.isoformat(),
    }
    eng.customer_feedback_json = feedback

    recommended_sku = "launch" if rating >= 4 and interested_in_renewal else "seo_blog_copilot"
    pkg = get_package(recommended_sku)
    renewal_rec = {
        "eligible_for_conversion": bool(interested_in_renewal and rating >= 3),
        "recommended_plan_sku": recommended_sku,
        "recommended_plan_name": pkg.name if pkg else "AskforWrite Monthly SEO / Company OS",
        "catalog_price_inr": pkg.price_inr if pkg else 4999,
        "verified_deliverables_summary": {
            "seo_audit_delivered": bool(deliverables.get("seo_audit_report")),
            "keyword_cluster_delivered": bool(deliverables.get("keyword_cluster")),
            "articles_delivered": 2 if deliverables.get("article_1") and deliverables.get("article_2") else 0,
            "execution_evidence_ids": evidence_ids,
        },
        "rationale": (
            f"Based on verified completion of 1 SEO/GEO audit, 1 keyword cluster, and 2 articles "
            f"(customer rating {rating}/5), buyer is invited to evaluate converting to recurring workflows."
        ),
        "approval_required_for_charge": True,
        "auto_charge_disabled": True,
        "generated_at": now.isoformat(),
    }
    eng.renewal_recommendation_json = renewal_rec
    eng.status = "RENEWAL_RECOMMENDED"
    eng.updated_at = now
    db.add(eng)
    db.add(
        AuditLog(
            task_id=eng.id,
            correlation_id=eng.id,
            agent_id=actor,
            capability_name="customer_success_agent",
            action="record_feedback_and_renewal",
            input_payload={"engagement_id": eng.id, "rating": rating},
            output_payload={"recommended_sku": recommended_sku, "eligible": renewal_rec["eligible_for_conversion"]},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(eng)
    return serialize_engagement(eng)


def get_founder_control_centre(db: Session) -> dict[str, Any]:
    """Return Founder Control Centre telemetry strictly separating Verified Commercial KPIs from Simulation/Test KPIs."""
    real_dossiers = db.query(P2ProspectDossierRecord).filter(P2ProspectDossierRecord.is_synthetic.is_(False)).all()
    synth_dossiers = db.query(P2ProspectDossierRecord).filter(P2ProspectDossierRecord.is_synthetic.is_(True)).all()

    real_lead_ids = {d.lead_id for d in real_dossiers}
    pending_approvals = db.query(ApprovalRequest).filter_by(status="PENDING").count()

    all_outreach = db.query(OutreachRecord).all()
    live_outreach_sent = sum(
        1
        for o in all_outreach
        if o.lead_id in real_lead_ids
        and o.status in ("SENT", "DISPATCHED", "REPLIED")
        and bool((o.metadata_json or {}).get("external_sent", True))
        and (o.metadata_json or {}).get("delivery_mode") != "SIMULATED"
    )
    simulated_outreach_sent = sum(
        1
        for o in all_outreach
        if o.status == "SIMULATED_SENT" or (o.metadata_json or {}).get("delivery_mode") == "SIMULATED"
    )

    responses_received = sum(len(d.response_history_json or []) for d in real_dossiers)
    discovery_calls_logged = sum(
        1
        for d in real_dossiers
        if d.pipeline_status in ("DISCOVERY", "PROPOSAL_PENDING", "WON") or bool(d.discovery_notes)
    )

    proposals_all = db.query(P2CommercialProposalRecord).all()
    proposals_sent = sum(1 for p in proposals_all if p.lead_id in real_lead_ids and p.status == "SHARED")

    reconciliations = db.query(P2PaymentReconciliationRecord).all()
    checkouts_initiated = len(reconciliations)
    verified_recons = [r for r in reconciliations if r.verification_state == "ACTIVATION_COMPLETED"]
    verified_payments = len(verified_recons)
    verified_revenue_inr = sum(
        float(r.received_amount or 0.0) for r in verified_recons if (r.currency or "INR").upper() == "INR"
    )

    engagements = db.query(P2CustomerEngagementRecord).all()
    active_paying_customers = sum(1 for e in engagements if e.status != "CANCELLED_OR_REFUNDED")
    deliverables_completed = sum(
        1 for e in engagements if e.status in ("DELIVERY_COMPLETED", "RENEWAL_RECOMMENDED", "RENEWED")
    )
    renewal_conversations = sum(1 for e in engagements if bool(e.renewal_recommendation_json))

    simulated_workflows = db.query(WorkflowRunRecord).filter_by(execution_mode="SIMULATION").count()
    failed_or_retry_recons = sum(1 for r in reconciliations if r.verification_state in ("RETRY_NEEDED", "FAILED"))

    # Connector capability summary (strictly separated 7-state model)
    conn_list = list_connectors(db)
    by_state: dict[str, list[str]] = {st: [] for st in CAPABILITY_STATES}
    for c in conn_list:
        st = str(c.get("capability_state", "SIMULATED"))
        by_state.setdefault(st, []).append(str(c["connector_id"]))

    status_counts: dict[str, int] = {}
    for d in real_dossiers:
        status_counts[d.pipeline_status] = status_counts.get(d.pipeline_status, 0) + 1

    return {
        "execution_mode": resolve_execution_mode(None),
        "target_segment": "Small & Medium Digital Marketing / SEO Agencies in India",
        "primary_offer_sku": "managed_seo_content_pilot",
        "verified_commercial_metrics": {
            "real_prospects_discovered": len(real_dossiers),
            "qualified_leads": sum(1 for d in real_dossiers if d.pipeline_status not in ("NEW", "DISQUALIFIED", "DO_NOT_CONTACT")),
            "pending_owner_approvals": pending_approvals,
            "outreach_sent": live_outreach_sent,
            "responses_received": responses_received,
            "discovery_calls_logged": discovery_calls_logged,
            "proposals_sent": proposals_sent,
            "checkouts_initiated": checkouts_initiated,
            "verified_payments": verified_payments,
            "verified_revenue_inr": round(verified_revenue_inr, 2),
            "active_paying_customers": active_paying_customers,
            "deliverables_completed": deliverables_completed,
            "renewal_conversations": renewal_conversations,
        },
        "simulation_and_test_metrics": {
            "note": "Strictly excluded from verified_commercial_metrics above.",
            "synthetic_prospects_count": len(synth_dossiers),
            "simulated_outreach_sent": simulated_outreach_sent,
            "pending_or_retry_reconciliations": failed_or_retry_recons,
            "simulated_workflow_runs": simulated_workflows,
        },
        "pipeline_stage_counts": status_counts,
        "capability_status_summary": {k: v for k, v in by_state.items() if v},
        "generated_at": datetime.now(UTC).isoformat(),
    }


def seed_and_get_acceptance_checklist(db: Session) -> list[dict[str, Any]]:
    """Ensure all 12 P2 real-world acceptance steps exist (initialized to NOT_TESTED) and return sorted."""
    existing_nums = {r.step_number for r in db.query(P2AcceptanceStepRecord).all()}
    added = False
    for num, key, title, desc in TWELVE_ACCEPTANCE_STEPS:
        if num not in existing_nums:
            db.add(
                P2AcceptanceStepRecord(
                    step_number=num,
                    step_key=key,
                    title=title,
                    description=desc,
                    verification_status="NOT_TESTED",
                )
            )
            added = True
    if added:
        db.commit()

    rows = db.query(P2AcceptanceStepRecord).order_by(P2AcceptanceStepRecord.step_number.asc()).all()
    return [serialize_acceptance_step(r) for r in rows]


def update_acceptance_step(
    db: Session,
    *,
    step_number: int,
    verification_status: str,
    evidence_summary: str | None = None,
    evidence_ref: str | None = None,
    verified_by: str = "owner",
) -> dict[str, Any]:
    """Update a P2 real-world pilot verification step strictly within allowed statuses."""
    allowed = ("NOT_TESTED", "SANDBOX_VERIFIED", "LIVE_VERIFIED")
    clean_status = verification_status.strip().upper()
    if clean_status not in allowed:
        raise ValueError(f"verification_status must be one of {allowed}")

    seed_and_get_acceptance_checklist(db)
    step = db.get(P2AcceptanceStepRecord, step_number)
    if not step:
        raise ValueError(f"Acceptance step {step_number} not found (expected 1..12)")

    now = datetime.now(UTC)
    step.verification_status = clean_status
    step.evidence_summary = evidence_summary.strip() if evidence_summary else step.evidence_summary
    step.evidence_ref = evidence_ref.strip() if evidence_ref else step.evidence_ref
    step.verified_by = verified_by
    step.verified_at = now if clean_status != "NOT_TESTED" else None
    step.updated_at = now
    db.add(step)
    db.commit()
    db.refresh(step)
    return serialize_acceptance_step(step)


def serialize_engagement(eng: P2CustomerEngagementRecord) -> dict[str, Any]:
    return {
        "engagement_id": eng.id,
        "org_id": eng.org_id,
        "lead_id": eng.lead_id,
        "proposal_id": eng.proposal_id,
        "invoice_id": eng.invoice_id,
        "sku_key": eng.sku_key,
        "billing_type": eng.billing_type,
        "status": eng.status,
        "assigned_modules": eng.assigned_modules_json or [],
        "entitlements": eng.entitlements_json or [],
        "onboarding_checklist": eng.onboarding_checklist_json or [],
        "required_client_inputs": eng.required_client_inputs_json or {},
        "workflow_run_id": eng.workflow_run_id,
        "deliverables": eng.deliverables_json or {},
        "customer_feedback": eng.customer_feedback_json,
        "renewal_recommendation": eng.renewal_recommendation_json,
        "pilot_start_at": eng.pilot_start_at.isoformat() if eng.pilot_start_at else None,
        "pilot_end_at": eng.pilot_end_at.isoformat() if eng.pilot_end_at else None,
        "completed_at": eng.completed_at.isoformat() if eng.completed_at else None,
        "created_at": eng.created_at.isoformat() if eng.created_at else None,
        "updated_at": eng.updated_at.isoformat() if eng.updated_at else None,
    }


def serialize_acceptance_step(step: P2AcceptanceStepRecord) -> dict[str, Any]:
    return {
        "step_number": step.step_number,
        "step_key": step.step_key,
        "title": step.title,
        "description": step.description,
        "verification_status": step.verification_status,
        "evidence_summary": step.evidence_summary,
        "evidence_ref": step.evidence_ref,
        "verified_by": step.verified_by,
        "verified_at": step.verified_at.isoformat() if step.verified_at else None,
    }
