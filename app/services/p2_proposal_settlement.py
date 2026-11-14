"""P2 Structured Commercial Proposals & Verified Payment-to-Activation Settlement Engine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import (
    ApprovalRequest,
    AuditLog,
    LeadRecordRow,
    P2CommercialProposalRecord,
    P2PaymentReconciliationRecord,
    P2ProspectDossierRecord,
    ProposalRecord,
    TaskRecord,
    UserRecord,
)
from app.services.approvals import request_approval
from app.services.catalog import CATALOG, build_payment_link, get_package
from app.services.evidence import record_execution_evidence
from app.services.execution_guard import resolve_execution_mode
from app.services.p2_customer_ops import create_customer_engagement_after_settlement, revoke_customer_engagement
from app.services.p2_prospect_intel import verify_pilot_offer_contract
from app.services.sovereign_pay import create_sovereign_pay_session


def create_structured_proposal(
    db: Session,
    *,
    lead_id: str,
    sku_key: str = "managed_seo_content_pilot",
    currency: str = "INR",
    tax_rate_percent: float = 0.0,
    custom_problem_statement: str | None = None,
    custom_scope_notes: str | None = None,
    actor: str = "sales_proposal_agent",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Generate a structured multi-clause proposal strictly verified against catalog pricing and gated by HITL."""
    lead = db.get(LeadRecordRow, lead_id)
    dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=lead_id).first()
    if not lead or not dossier:
        raise ValueError(f"P2 prospect dossier not found for lead '{lead_id}'")
    if lead.do_not_contact or dossier.pipeline_status == "DO_NOT_CONTACT":
        raise ValueError("Cannot create commercial proposal for DO_NOT_CONTACT lead")
    if dossier.pipeline_status == "DISQUALIFIED":
        raise ValueError("Cannot create proposal for DISQUALIFIED lead")

    clean_curr = (currency or "INR").upper().strip()
    if clean_curr not in ("INR", "USD"):
        raise ValueError("Only INR and USD currencies are supported")
    if tax_rate_percent < 0.0 or tax_rate_percent > 28.0:
        raise ValueError("tax_rate_percent must be between 0.0 and 28.0")

    offer = verify_pilot_offer_contract(sku_key)
    pkg = CATALOG[offer["sku_key"]]
    base_amount = float(pkg.price_inr if clean_curr == "INR" else pkg.price_usd)
    tax_amount = round(base_amount * (tax_rate_percent / 100.0), 2)
    total_amount = round(base_amount + tax_amount, 2)

    problem = (
        custom_problem_statement.strip()
        if custom_problem_statement and custom_problem_statement.strip()
        else (
            dossier.research_brief_json.get("evidence_backed_opportunity")
            or f"Manual SEO audit and content drafting bottlenecks reducing turnaround capacity at {lead.company}."
        )
    )
    scope_summary = (
        f"{pkg.description}"
        + (f" Additional agreed pilot notes: {custom_scope_notes.strip()}" if custom_scope_notes and custom_scope_notes.strip() else "")
    )

    exclusions_and_limits = [
        "Excludes paid advertising spend, backlink purchasing, PR outreach, or website redesign/development.",
        "Excludes guaranteed search ranking positions (#1 ranking) or guaranteed traffic/ROI outcomes.",
        "Includes up to 2 content revision rounds within the 14-day pilot window.",
        "Automatic monthly subscription billing is NOT enabled; post-pilot continuation requires separate mutual agreement.",
    ]

    schedule = [
        {"phase": "Days 1-2", "milestone": "Onboarding & target domain/topic intake", "owner": "Buyer & AskforWrite"},
        {"phase": "Days 3-5", "milestone": "Technical SEO/GEO audit & commercial keyword cluster delivery", "owner": "AskforWrite"},
        {"phase": "Days 6-10", "milestone": "2 long-form authoritative articles + Schema.org JSON-LD drafted", "owner": "AskforWrite"},
        {"phase": "Days 11-14", "milestone": "Buyer review, CMS draft staging / Markdown export & pilot handover", "owner": "Mutual"},
    ]

    pricing = {
        "sku_key": pkg.key,
        "sku_name": pkg.name,
        "billing_type": offer["billing_type"],
        "billing_interval": offer["billing_interval"],
        "base_amount": base_amount,
        "discount_amount": 0.0,
        "tax_type": "GST" if clean_curr == "INR" else "Applicable Taxes",
        "tax_rate_percent": tax_rate_percent,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "currency": clean_curr,
        "pricing_verified_from_catalog": True,
    }

    payment_terms = {
        "payment_schedule": "100% pilot fee upfront prior to tenant activation and delivery start",
        "supported_methods": ["Razorpay (INR UPI/Cards/Netbanking)", "PayPal (USD)", "AFW DirectPay (Zero-fee UPI / Bank Wire / USDC)"],
        "invoice_currency": clean_curr,
        "post_pilot_renewal": "Manual conversion opt-in only after 14-day pilot completion",
    }

    client_responsibilities = [
        "Provide target website domain URL and primary service/audience focus within 2 business days.",
        "Confirm CMS delivery preference (WordPress REST staging credentials or Markdown/HTML export).",
        "Review and provide consolidation feedback on delivered drafts within the pilot window.",
    ]

    provider_responsibilities = [
        "Execute structured technical SEO/GEO audit grounded in public site signals.",
        "Deliver 1 commercial keyword cluster map and 2 human-reviewed 1,500+ word articles with Schema.org JSON-LD.",
        "Maintain cryptographically signed NIST P-256 TrustBlock execution evidence for delivery milestones.",
        "Protect client data under BYOK / tenant isolation controls without using private data across tenants.",
    ]

    acceptance_cancellation = {
        "acceptance_criteria": (
            "Pilot is accepted upon delivery and client confirmation of the SEO/GEO audit, keyword cluster, "
            "and 2 review-ready articles (with Schema.org JSON-LD) in the agreed format."
        ),
        "cancellation_and_refund_terms": (
            "Full refund eligible if requested prior to onboarding kickoff/delivery execution start, or in case of "
            "verified failure to deliver stated pilot artifacts within 14 days excluding buyer input delays."
        ),
        "valid_until_days": 14,
    }

    corr_id = correlation_id or str(uuid.uuid4())
    task_id = lead.task_id or str(uuid.uuid4())
    if not db.get(TaskRecord, task_id):
        db.add(
            TaskRecord(
                id=task_id,
                correlation_id=corr_id,
                objective=f"Commercial Proposal for {lead.company} ({pkg.key})",
                status="IN_PROGRESS",
            )
        )
        db.flush()

    prop_rec_id = str(uuid.uuid4())
    p2_prop_id = str(uuid.uuid4())
    title = f"{pkg.name} Proposal for {lead.company}"

    legacy_prop = ProposalRecord(
        id=prop_rec_id,
        task_id=task_id,
        requirement_id=None,
        lead_id=lead_id,
        title=title,
        summary=scope_summary,
        scope=offer["deliverables"],
        pricing_model=f"catalog:{pkg.key}:{clean_curr}:{total_amount}",
        status="AWAITING_APPROVAL",
    )
    db.add(legacy_prop)
    db.flush()

    approval_resp = request_approval(
        db=db,
        task_id=task_id,
        lead_id=lead_id,
        proposal_id=prop_rec_id,
        action="proposal_delivery",
        detail={
            "p2_proposal_id": p2_prop_id,
            "proposal_record_id": prop_rec_id,
            "company": lead.company,
            "sku_key": pkg.key,
            "currency": clean_curr,
            "total_amount": total_amount,
            "billing_type": offer["billing_type"],
        },
        idempotency_key=f"appr-p2-prop-{p2_prop_id}",
        requested_by=actor,
        correlation_id=corr_id,
        commit=False,
    )
    approval_id = str(approval_resp["approval_id"])
    legacy_prop.approval_id = approval_id

    p2_prop = P2CommercialProposalRecord(
        id=p2_prop_id,
        proposal_record_id=prop_rec_id,
        lead_id=lead_id,
        org_id=dossier.org_id,
        sku_key=pkg.key,
        title=title,
        customer_problem=problem,
        scope_summary=scope_summary,
        deliverables_json=offer["deliverables"],
        exclusions_limitations_json=exclusions_and_limits,
        implementation_schedule_json=schedule,
        pricing_json=pricing,
        payment_terms_json=payment_terms,
        client_responsibilities_json=client_responsibilities,
        provider_responsibilities_json=provider_responsibilities,
        acceptance_cancellation_terms_json=acceptance_cancellation,
        status="AWAITING_OWNER_APPROVAL",
        approval_id=approval_id,
        created_by=actor,
    )
    db.add(p2_prop)

    dossier.pipeline_status = "PROPOSAL_PENDING"
    dossier.recommended_sku = pkg.key
    dossier.commercial_value_inr = float(pkg.price_inr)
    dossier.currency = clean_curr
    dossier.next_action = f"Owner review & HITL approval required before sharing proposal '{p2_prop_id}'"
    dossier.updated_at = datetime.now(UTC)
    db.add(dossier)

    record_execution_evidence(
        db,
        tenant_id=dossier.org_id or "__platform__",
        agent_id="sales_proposal_agent",
        connector_id="project_api",
        execution_mode=resolve_execution_mode(None),
        input_payload={"lead_id": lead_id, "sku_key": pkg.key, "currency": clean_curr},
        output_payload={"proposal_id": p2_prop_id, "approval_id": approval_id, "total_amount": total_amount},
        approval_id=approval_id,
        uses_external_provider=False,
        status="COMPLETED",
        output_origin="HUMAN_ASSISTED",
    )
    db.add(
        AuditLog(
            task_id=task_id,
            correlation_id=corr_id,
            agent_id=actor,
            capability_name="p2_proposal_generator",
            action="create_structured_proposal",
            input_payload={"lead_id": lead_id, "sku_key": pkg.key, "total_amount": total_amount},
            output_payload={"proposal_id": p2_prop_id, "approval_id": approval_id},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(p2_prop)
    return serialize_p2_proposal(p2_prop)


def _ensure_proposal_approved(db: Session, proposal: P2CommercialProposalRecord) -> ApprovalRequest:
    if not proposal.approval_id:
        raise ValueError("Proposal lacks a linked Owner ApprovalRequest")
    approval = db.get(ApprovalRequest, proposal.approval_id)
    if not approval:
        raise ValueError(f"Approval '{proposal.approval_id}' not found")
    if approval.status != "APPROVED":
        raise ValueError(
            f"Proposal '{proposal.id}' cannot be shared or billed before explicit Owner approval (status: {approval.status})"
        )
    if proposal.status not in ("APPROVED", "SHARED"):
        proposal.status = "APPROVED"
        proposal.approved_by = approval.decided_by or "owner"
        proposal.approved_at = approval.decided_at or datetime.now(UTC)
        db.add(proposal)
    return approval


def share_approved_proposal(
    db: Session,
    *,
    proposal_id: str,
    channel: str = "email_and_portal_link",
    actor: str = "owner",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Share an Owner-approved structured proposal and record sharing audit metadata."""
    proposal = db.get(P2CommercialProposalRecord, proposal_id)
    if not proposal:
        raise ValueError(f"Commercial proposal '{proposal_id}' not found")

    approval = _ensure_proposal_approved(db, proposal)
    now = datetime.now(UTC)
    proposal.status = "SHARED"
    proposal.shared_at = now
    proposal.shared_channel = channel
    if not proposal.checkout_url:
        lead = db.get(LeadRecordRow, proposal.lead_id)
        proposal.checkout_url = build_payment_link(
            package_key=proposal.sku_key,
            company=lead.company if lead else "Client",
            provider="afw_directpay",
        )
    proposal.updated_at = now
    db.add(proposal)

    dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=proposal.lead_id).first()
    if dossier:
        dossier.next_action = "Await prospect review and verified payment confirmation"
        dossier.updated_at = now
        db.add(dossier)

    db.add(
        AuditLog(
            task_id=proposal.proposal_record_id or proposal.id,
            correlation_id=correlation_id or str(uuid.uuid4()),
            agent_id=actor,
            capability_name="p2_proposal_generator",
            action="share_approved_proposal",
            input_payload={"proposal_id": proposal_id, "channel": channel, "approval_id": approval.id},
            output_payload={"status": "SHARED", "checkout_url": proposal.checkout_url},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(proposal)
    return serialize_p2_proposal(proposal)


def initiate_proposal_checkout(
    db: Session,
    *,
    proposal_id: str,
    provider: str = "afw_directpay",
    customer_email: str | None = None,
    customer_name: str | None = None,
    preferred_rail: str = "upi_direct",
    actor: str = "owner",
) -> dict[str, Any]:
    """Generate verified-SKU checkout session/link for an approved proposal WITHOUT marking paid or won."""
    proposal = db.get(P2CommercialProposalRecord, proposal_id)
    if not proposal:
        raise ValueError(f"Commercial proposal '{proposal_id}' not found")
    _ensure_proposal_approved(db, proposal)

    lead = db.get(LeadRecordRow, proposal.lead_id)
    dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=proposal.lead_id).first()
    pkg = get_package(proposal.sku_key)
    if not pkg:
        raise ValueError(f"Verified catalog SKU '{proposal.sku_key}' missing")

    email = (customer_email or (lead.public_contact_channel if lead else "") or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("A valid buyer customer_email is required to create a checkout session")

    company = lead.company if lead else (customer_name or "Agency Client")
    pricing = proposal.pricing_json or {}
    currency = str(pricing.get("currency", "INR")).upper()
    expected_amount = float(pricing.get("base_amount") or (pkg.price_inr if currency == "INR" else pkg.price_usd))

    clean_provider = provider.strip().lower()
    checkout_ref: str
    checkout_url: str
    extra_meta: dict[str, Any] = {"proposal_id": proposal.id, "lead_id": proposal.lead_id, "customer_email": email, "company_name": company}

    if clean_provider in ("afw_directpay", "sovereign_pay", "sovereign_direct"):
        session = create_sovereign_pay_session(
            package_key=pkg.key,
            company_name=company,
            customer_email=email,
            currency=currency,
            preferred_rail=preferred_rail,
            customer_name=customer_name or company,
            db=db,
        )
        checkout_ref = session.session_id
        checkout_url = session.checkout_url
        extra_meta["upi_uri"] = session.upi_uri
        extra_meta["bank_wire_invoice"] = session.bank_wire_invoice
    else:
        checkout_ref = f"chk_{clean_provider}_{uuid.uuid4().hex[:14]}"
        checkout_url = build_payment_link(
            package_key=pkg.key,
            customer_email=email,
            company=company,
            provider=clean_provider,
        )

    proposal.checkout_session_id = checkout_ref
    proposal.checkout_url = checkout_url
    proposal.updated_at = datetime.now(UTC)
    db.add(proposal)

    recon = P2PaymentReconciliationRecord(
        proposal_id=proposal.id,
        lead_id=proposal.lead_id,
        org_id=proposal.org_id,
        provider=clean_provider,
        checkout_reference=checkout_ref,
        expected_sku=pkg.key,
        expected_amount=expected_amount,
        received_amount=0.0,
        currency=currency,
        verification_state="CHECKOUT_CREATED",
        metadata_json=extra_meta,
    )
    db.add(recon)

    if dossier:
        dossier.payment_status = "CHECKOUT_CREATED"
        dossier.next_action = "Await genuine payment confirmation webhook or verified UTR settlement before activating customer"
        dossier.updated_at = datetime.now(UTC)
        db.add(dossier)

    db.commit()
    db.refresh(recon)
    return {
        "reconciliation_id": recon.id,
        "proposal_id": proposal.id,
        "lead_id": proposal.lead_id,
        "provider": clean_provider,
        "checkout_reference": checkout_ref,
        "checkout_url": checkout_url,
        "expected_sku": pkg.key,
        "expected_amount": expected_amount,
        "currency": currency,
        "payment_status": "CHECKOUT_CREATED",
        "customer_activated": False,
        "warning": "Checkout link creation NEVER activates a customer or records paid revenue; verified settlement is required.",
    }


def _find_matching_dossier_for_payment(
    db: Session,
    *,
    email: str | None,
    company_name: str | None,
    checkout_ref: str | None,
    lead_id: str | None = None,
) -> tuple[P2ProspectDossierRecord | None, P2CommercialProposalRecord | None, P2PaymentReconciliationRecord | None]:
    recon = None
    if checkout_ref:
        recon = (
            db.query(P2PaymentReconciliationRecord)
            .filter(
                (P2PaymentReconciliationRecord.checkout_reference == checkout_ref)
                | (P2PaymentReconciliationRecord.provider_event_id == checkout_ref)
            )
            .order_by(P2PaymentReconciliationRecord.created_at.desc())
            .first()
        )
    proposal = db.get(P2CommercialProposalRecord, recon.proposal_id) if recon and recon.proposal_id else None
    target_lead_id = lead_id or (recon.lead_id if recon else None) or (proposal.lead_id if proposal else None)

    dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=target_lead_id).first() if target_lead_id else None
    if not dossier and email and "@" in email:
        email_domain = email.strip().lower().split("@", 1)[1].removeprefix("www.")
        dossier = db.query(P2ProspectDossierRecord).filter_by(normalized_domain=email_domain).first()
    if not dossier and company_name:
        from app.services.p2_prospect_intel import normalize_company_identity

        norm_co = normalize_company_identity(company_name)
        dossier = db.query(P2ProspectDossierRecord).filter_by(normalized_company_key=norm_co).first()

    if not proposal and dossier:
        proposal = (
            db.query(P2CommercialProposalRecord)
            .filter_by(lead_id=dossier.lead_id)
            .order_by(P2CommercialProposalRecord.created_at.desc())
            .first()
        )
    if not recon and proposal:
        recon = (
            db.query(P2PaymentReconciliationRecord)
            .filter_by(proposal_id=proposal.id)
            .order_by(P2PaymentReconciliationRecord.created_at.desc())
            .first()
        )
    return dossier, proposal, recon


def reconcile_verified_payment(
    db: Session,
    *,
    provider: str,
    provider_event_id: str,
    checkout_reference: str | None,
    package_key: str,
    received_amount: float,
    currency: str,
    email: str | None,
    company_name: str | None,
    provisioning_result: dict[str, Any] | None,
    verification_mode: str = "WEBHOOK_HMAC_VERIFIED",
) -> dict[str, Any] | None:
    """Safely reconcile a verified payment event -> WON + Customer Engagement + Retry queue on failure."""
    # Idempotency guard via provider_event_id
    existing_evt = db.query(P2PaymentReconciliationRecord).filter_by(provider_event_id=provider_event_id).first()
    if existing_evt and existing_evt.verification_state == "ACTIVATION_COMPLETED":
        return {
            "status": "ALREADY_ACTIVATED",
            "reconciliation_id": existing_evt.id,
            "activated_org_id": existing_evt.activated_org_id,
            "activation_id": existing_evt.activation_id,
        }

    dossier, proposal, recon = _find_matching_dossier_for_payment(
        db,
        email=email,
        company_name=company_name,
        checkout_ref=checkout_reference,
    )

    if not recon:
        pkg = get_package(package_key)
        expected_amt = float((pkg.price_inr if currency.upper() == "INR" else pkg.price_usd) if pkg else received_amount)
        recon = P2PaymentReconciliationRecord(
            proposal_id=proposal.id if proposal else None,
            lead_id=dossier.lead_id if dossier else None,
            org_id=dossier.org_id if dossier else None,
            provider=provider,
            checkout_reference=checkout_reference or provider_event_id,
            provider_event_id=provider_event_id,
            expected_sku=package_key,
            expected_amount=expected_amt,
            received_amount=received_amount,
            currency=currency.upper(),
            verification_state="WEBHOOK_VERIFIED",
            metadata_json={"verification_mode": verification_mode, "email": email, "company_name": company_name},
        )
        db.add(recon)
    else:
        recon.provider_event_id = provider_event_id
        recon.received_amount = received_amount
        meta = dict(recon.metadata_json or {})
        meta["verification_mode"] = verification_mode
        if email:
            meta["email"] = email
        if company_name:
            meta["company_name"] = company_name
        recon.metadata_json = meta
        flag_modified(recon, "metadata_json")

    prov_status = str((provisioning_result or {}).get("status", ""))
    activated_org_id = (provisioning_result or {}).get("org_id")
    invoice_id = (provisioning_result or {}).get("invoice_id")

    if not provisioning_result or prov_status in ("unknown_package_withheld", "unsupported_currency_withheld", "underpaid_withheld"):
        recon.verification_state = "RETRY_NEEDED"
        recon.last_error = f"Provisioning withheld ({prov_status or 'missing_org_id'}); customer not activated."
        if dossier:
            dossier.payment_status = "PENDING_VERIFICATION"
            dossier.next_action = f"Review payment reconciliation queue '{recon.id}': {recon.last_error}"
            db.add(dossier)
        db.add(recon)
        db.commit()
        return {
            "status": "RETRY_NEEDED",
            "reconciliation_id": recon.id,
            "reason": recon.last_error,
            "customer_activated": False,
        }

    # Resolve org_id when user already existed in provisioning
    if not activated_org_id and email:
        usr = db.query(UserRecord).filter_by(email=email.strip().lower()).first()
        if usr:
            activated_org_id = usr.org_id

    if not activated_org_id:
        recon.verification_state = "RETRY_NEEDED"
        recon.last_error = "Payment verified but tenant org_id missing; queued for deterministic retry."
        db.add(recon)
        db.commit()
        return {"status": "RETRY_NEEDED", "reconciliation_id": recon.id, "customer_activated": False}

    engagement = create_customer_engagement_after_settlement(
        db,
        org_id=str(activated_org_id),
        lead_id=dossier.lead_id if dossier else None,
        proposal_id=proposal.id if proposal else None,
        invoice_id=str(invoice_id) if invoice_id else None,
        sku_key=package_key,
    )

    now = datetime.now(UTC)
    recon.verification_state = "ACTIVATION_COMPLETED"
    recon.activated_org_id = str(activated_org_id)
    recon.invoice_id = str(invoice_id) if invoice_id else None
    recon.activation_id = engagement["engagement_id"]
    recon.last_error = None
    recon.updated_at = now
    db.add(recon)

    if dossier:
        dossier.pipeline_status = "WON"
        dossier.payment_status = "PAID_VERIFIED"
        dossier.activation_status = "ACTIVATED"
        dossier.activated_org_id = str(activated_org_id)
        dossier.next_action = "Collect required client inputs in Onboarding Checklist and launch Pilot Delivery workflow"
        dossier.updated_at = now
        db.add(dossier)
        lead = db.get(LeadRecordRow, dossier.lead_id)
        if lead:
            lead.status = "WON"
            db.add(lead)

    db.commit()
    return {
        "status": "ACTIVATION_COMPLETED",
        "reconciliation_id": recon.id,
        "activated_org_id": str(activated_org_id),
        "engagement_id": engagement["engagement_id"],
        "customer_activated": True,
    }


def record_payment_failure_or_refund(
    db: Session,
    *,
    event_kind: str,
    checkout_reference: str | None = None,
    provider_event_id: str | None = None,
    org_id: str | None = None,
    reason: str = "Payment failed or refunded via gateway webhook",
) -> dict[str, Any]:
    """Handle payment failure, refund, or dispute cleanly without granting or preserving unpaid access."""
    clean_kind = event_kind.strip().lower()
    recon = None
    if checkout_reference:
        recon = (
            db.query(P2PaymentReconciliationRecord)
            .filter(
                (P2PaymentReconciliationRecord.checkout_reference == checkout_reference)
                | (P2PaymentReconciliationRecord.provider_event_id == checkout_reference)
            )
            .order_by(P2PaymentReconciliationRecord.created_at.desc())
            .first()
        )
    if not recon and org_id:
        recon = (
            db.query(P2PaymentReconciliationRecord)
            .filter_by(activated_org_id=org_id)
            .order_by(P2PaymentReconciliationRecord.created_at.desc())
            .first()
        )

    now = datetime.now(UTC)
    new_state = "REFUNDED" if "refund" in clean_kind else ("DISPUTED" if "dispute" in clean_kind else "FAILED")
    if recon:
        recon.verification_state = new_state
        recon.last_error = reason
        recon.updated_at = now
        db.add(recon)

    target_org_id = org_id or (recon.activated_org_id if recon else None)
    if target_org_id and new_state in ("REFUNDED", "DISPUTED"):
        revoke_customer_engagement(db, org_id=target_org_id, reason=reason)
        dossier = db.query(P2ProspectDossierRecord).filter_by(activated_org_id=target_org_id).first()
        if dossier:
            dossier.payment_status = new_state
            dossier.activation_status = "REVOKED"
            dossier.pipeline_status = "LOST"
            dossier.next_action = f"Access revoked due to {new_state.lower()}: {reason[:120]}"
            dossier.updated_at = now
            db.add(dossier)
    elif recon and recon.lead_id:
        dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=recon.lead_id).first()
        if dossier:
            dossier.payment_status = "FAILED"
            dossier.next_action = f"Follow up on failed payment and re-send verified checkout link: {reason[:100]}"
            dossier.updated_at = now
            db.add(dossier)

    db.commit()
    return {
        "status": new_state,
        "reconciliation_id": recon.id if recon else None,
        "org_id": target_org_id,
        "revoked": bool(target_org_id and new_state in ("REFUNDED", "DISPUTED")),
    }


def retry_reconciliation_entry(db: Session, *, reconciliation_id: str, actor: str = "owner") -> dict[str, Any]:
    """Deterministically retry a queued payment reconciliation entry if payment metadata is now valid."""
    recon = db.get(P2PaymentReconciliationRecord, reconciliation_id)
    if not recon:
        raise ValueError(f"Reconciliation entry '{reconciliation_id}' not found")
    if recon.verification_state == "ACTIVATION_COMPLETED":
        return {"status": "ALREADY_ACTIVATED", "reconciliation_id": recon.id, "activated_org_id": recon.activated_org_id}
    if recon.verification_state in ("FAILED", "REFUNDED", "DISPUTED"):
        raise ValueError(f"Cannot activate reconciliation '{recon.id}' in terminal state '{recon.verification_state}'")
    if recon.received_amount <= 0 or recon.received_amount < (recon.expected_amount * 0.95):
        recon.retry_count += 1
        recon.last_error = (
            f"Retry blocked: verified received_amount ({recon.received_amount} {recon.currency}) is below "
            f"expected_amount ({recon.expected_amount} {recon.currency})."
        )
        db.add(recon)
        db.commit()
        return {"status": "RETRY_BLOCKED_UNVERIFIED_AMOUNT", "reconciliation_id": recon.id, "reason": recon.last_error}

    from app.services.payment import PaymentProvider, WebhookEvent
    from app.services.provisioning import auto_provision_tenant_on_payment

    meta = recon.metadata_json or {}
    email = meta.get("email")
    if not email:
        recon.retry_count += 1
        recon.last_error = "Missing buyer email in reconciliation metadata"
        db.add(recon)
        db.commit()
        return {"status": "RETRY_NEEDED", "reconciliation_id": recon.id, "reason": recon.last_error}

    prov_event = WebhookEvent(
        id=recon.provider_event_id or f"retry_{recon.id}",
        provider=PaymentProvider.AFW_DIRECTPAY,
        event_type="sovereign.payment.verified",
        raw_event_type="sovereign.payment.verified",
        resource_id=recon.checkout_reference,
        resource_type="payment",
        data={
            "email": email,
            "company_name": meta.get("company_name") or "Pilot Customer",
            "package_key": recon.expected_sku,
            "amount": recon.received_amount,
            "currency": recon.currency,
        },
    )
    prov_res = auto_provision_tenant_on_payment(db=db, event=prov_event)
    recon.retry_count += 1
    db.flush()
    return reconcile_verified_payment(
        db,
        provider=recon.provider,
        provider_event_id=recon.provider_event_id or f"retry_{recon.id}",
        checkout_reference=recon.checkout_reference,
        package_key=recon.expected_sku,
        received_amount=recon.received_amount,
        currency=recon.currency,
        email=email,
        company_name=meta.get("company_name"),
        provisioning_result=prov_res,
        verification_mode=f"RETRY_BY_{actor}",
    ) or {"status": "RETRY_FAILED", "reconciliation_id": recon.id}


def serialize_p2_proposal(p: P2CommercialProposalRecord) -> dict[str, Any]:
    return {
        "proposal_id": p.id,
        "proposal_record_id": p.proposal_record_id,
        "lead_id": p.lead_id,
        "org_id": p.org_id,
        "sku_key": p.sku_key,
        "title": p.title,
        "customer_problem": p.customer_problem,
        "scope_summary": p.scope_summary,
        "deliverables": p.deliverables_json or [],
        "exclusions_and_limitations": p.exclusions_limitations_json or [],
        "implementation_schedule": p.implementation_schedule_json or [],
        "pricing": p.pricing_json or {},
        "payment_terms": p.payment_terms_json or {},
        "client_responsibilities": p.client_responsibilities_json or [],
        "provider_responsibilities": p.provider_responsibilities_json or [],
        "acceptance_and_cancellation_terms": p.acceptance_cancellation_terms_json or {},
        "status": p.status,
        "approval_id": p.approval_id,
        "shared_at": p.shared_at.isoformat() if p.shared_at else None,
        "shared_channel": p.shared_channel,
        "checkout_session_id": p.checkout_session_id,
        "checkout_url": p.checkout_url,
        "created_by": p.created_by,
        "approved_by": p.approved_by,
        "approved_at": p.approved_at.isoformat() if p.approved_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
