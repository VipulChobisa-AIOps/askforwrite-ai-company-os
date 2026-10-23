"""Autonomous Daily Shift Scheduler & CEO Executive Briefing Service.

Orchestrates the 1-person company's AI employees in automated shifts:
1. outbound_sdr: Discovers SMB leads & generates Trojan-Horse proof-first previews
2. owned_media_seo: Generates & stages SEO drafts for the 4 WordPress authority domains
3. order_fulfillment: Fulfills pending B2C / ASK4 orders automatically
4. watchdog_audit: Executes L1 watchdog scan to verify operational health & SLA compliance

Compiles a unified CEO Executive Briefing for Vipul (L0 Owner).
Seals all shift runs cryptographically into the ECDSA P-256 Merkle TrustBlock ledger.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents.smb_search_source import discover_smb_leads
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    InvoiceRecord,
    LeadRecordRow,
    OrderRecord,
    OrganizationRecord,
    OutreachRecord,
    ShiftRecord,
    TaskRecord,
)
from app.security.trust_chain import seal_task_to_block
from app.services.orders import fulfill_pending_orders
from app.services.outreach import draft_outreach
from app.services.previews import generate_trojan_horse_preview
from app.services.seo import execute_seo_draft
from app.services.watchdog import (
    get_system_control_telemetry,
    run_system_watchdog_scan,
)
from app.services.wordpress_publisher import get_supported_networks

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "autonomous_shift_scheduler"


def run_autonomous_shift(
    db: Session,
    shift_type: str = "full_daily_cycle",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Execute a complete autonomous employee shift across all 4 operational functions."""
    start_time = datetime.now(UTC)
    corr_id = correlation_id or str(uuid.uuid4())
    shift_id = f"shift_{uuid.uuid4().hex[:12]}"
    task_id = str(uuid.uuid4())

    logger.info(f"Starting autonomous shift '{shift_id}' (type={shift_type})...")

    step_results: dict[str, Any] = {}

    # ── 1. Outbound SDR Agent: Discover SMB leads & Generate Trojan-Horse Previews ──
    try:
        discovered = discover_smb_leads(
            vertical="growth_all_in_one",
            region="India",
            limit=2,
        )
        previews_generated = []
        outreach_drafts = []
        for cand in discovered:
            domain = cand.get("domain") or "sahyadrifarms.com"
            # Persist lead if new
            lead = db.query(LeadRecordRow).filter_by(domain=domain).first()
            if not lead:
                lead = LeadRecordRow(
                    id=str(uuid.uuid4()),
                    task_id=str(uuid.uuid4()),
                    company=cand.get("company", "Candidate SMB"),
                    website=cand.get("website", f"https://{domain}"),
                    industry=cand.get("industry", "SMB"),
                    geography=cand.get("geography", "India"),
                    observed_signals=cand.get("observed_signals", []),
                    sources=[{"source": "autonomous_sdr_shift"}],
                    product_match=cand.get("recommended_package", "growth_all_in_one"),
                    fit_score=cand.get("fit_score", 0.95),
                    confidence=cand.get("confidence", 0.92),
                    public_contact_channel=cand.get("public_contact_channel"),
                    recommended_next_step="trojan_horse_preview",
                    do_not_contact=False,
                    status="DISCOVERED",
                    last_checked=datetime.now(UTC),
                )
                db.add(lead)
                db.flush()
            else:
                if not lead.public_contact_channel and cand.get("public_contact_channel"):
                    lead.public_contact_channel = cand.get("public_contact_channel")
                    db.add(lead)
                    db.flush()
                if lead.status not in {"DISCOVERED", "RESEARCHED", "QUALIFIED"}:
                    lead.status = "DISCOVERED"
                    db.add(lead)
                    db.flush()

            preview = generate_trojan_horse_preview(
                db=db,
                company_name=cand.get("company", "Candidate SMB"),
                domain=domain,
                recommended_package=cand.get("recommended_package", "growth_all_in_one"),
                lead_id=lead.id,
                correlation_id=corr_id,
            )
            preview_token = preview.get("preview_token")
            previews_generated.append({
                "company": cand.get("company"),
                "domain": domain,
                "preview_token": preview_token,
                "recommended_package": preview.get("recommended_package"),
            })

            # Stage Trojan-Horse Outreach Draft when contact channel is present
            contact_channel = lead.public_contact_channel or cand.get("public_contact_channel")
            if contact_channel and "@" in contact_channel:
                preview_url = f"/v1/previews/{preview_token}/html"
                existing_outreach = (
                    db.query(OutreachRecord)
                    .filter(OutreachRecord.lead_id == lead.id)
                    .first()
                )
                if existing_outreach:
                    outreach_drafts.append({
                        "outreach_id": existing_outreach.id,
                        "approval_id": existing_outreach.approval_id,
                        "lead_id": lead.id,
                        "company": cand.get("company"),
                        "preview_token": preview_token,
                        "preview_url": preview_url,
                        "status": existing_outreach.status,
                    })
                else:
                    audit = cand.get("seo_geo_audit") or {}
                    gap_score = audit.get("seo_geo_gap_score", 45)
                    gaps_desc = f"SEO/GEO Gap Score: {gap_score}/100"
                    if not audit.get("has_json_ld_schema", True):
                        gaps_desc += " | Missing Schema.org JSON-LD"
                    if not audit.get("has_llms_txt", True):
                        gaps_desc += " | Missing /llms.txt AI Manifest"

                    custom_notes = (
                        f"Live Trojan-Horse Preview: {preview_url} | Detected Gaps: {gaps_desc} | "
                        f"1-Click Checkout: Instant activation enabled via Razorpay & PayPal"
                    )
                    idempotency_key = f"shift-outreach-{shift_id}-{lead.id}"
                    try:
                        outreach_res = draft_outreach(
                            db=db,
                            lead_id=lead.id,
                            org_id=lead.org_id,
                            recipient_email=contact_channel,
                            recipient_name=cand.get("company"),
                            custom_notes=custom_notes,
                            channel="email",
                            idempotency_key=idempotency_key,
                            correlation_id=corr_id,
                            requested_by="autonomous_sdr_shift_worker",
                        )
                        outreach_drafts.append({
                            "outreach_id": outreach_res.get("outreach_id"),
                            "approval_id": outreach_res.get("approval_id"),
                            "lead_id": lead.id,
                            "company": cand.get("company"),
                            "preview_token": preview_token,
                            "preview_url": preview_url,
                            "status": outreach_res.get("status"),
                        })
                    except Exception as outreach_exc:
                        logger.warning(f"Could not draft outreach for lead {lead.id}: {outreach_exc}")

        step_results["outbound_sdr"] = {
            "status": "COMPLETED",
            "leads_discovered_count": len(discovered),
            "previews_generated_count": len(previews_generated),
            "previews": previews_generated,
            "outreach_drafts_staged_count": len(outreach_drafts),
            "outreach_drafts": outreach_drafts,
        }
    except Exception as exc:
        logger.error(f"Outbound SDR step failed: {exc}", exc_info=True)
        step_results["outbound_sdr"] = {"status": "ERROR", "error": str(exc)}

    # ── 2. Owned Media SEO Agent: Generate & Stage Drafts for AskforWrite Network ──
    try:
        networks = get_supported_networks()
        seo_keyword_map = {
            "askforwrite.in": ["Autonomous AI Company OS", "Enterprise AI Agents", "Multi-Agent Systems"],
            "askforwrite.com": ["Enterprise AI Operations", "Autonomous Agent Workflows", "B2B AI Architecture"],
            "ask4write.com": ["AI Solutions Store", "Automated Workforce Packages", "Commercial Agentic Tools"],
            "askforwrite.info": ["AI Architecture Technical Documentation", "Agent API Specifications", "Trust Ledger Security"],
            "shop.ask4write.com": ["Digital AI Toolkits", "Instant Enterprise Automation Templates", "Zero-MDR DirectPay"],
            "node.askforwrite.in": ["Distributed Edge Node AI", "Low-Latency Autonomous API", "Private Node Interconnect"],
        }

        staged_seo_drafts = []
        for net_domain in networks.keys():
            kws = seo_keyword_map.get(net_domain, ["AI Automation", "Company OS"])
            seo_idemp_key = f"shift-seo-{shift_id}-{net_domain}"
            try:
                res = execute_seo_draft(
                    db=db,
                    target_network=net_domain,
                    keywords=kws,
                    idempotency_key=seo_idemp_key,
                    correlation_id=corr_id,
                    agent_id="owned_media_seo_shift_worker",
                )
                staged_seo_drafts.append({
                    "target_network": net_domain,
                    "draft_id": res.get("draft_id"),
                    "status": res.get("status"),
                    "approval_id": res.get("approval_id"),
                })
            except Exception as e:
                staged_seo_drafts.append({
                    "target_network": net_domain,
                    "status": "SKIPPED_OR_EXISTING",
                    "note": str(e),
                })

        step_results["owned_media_seo"] = {
            "status": "COMPLETED",
            "networks_targeted_count": len(networks),
            "staged_drafts": staged_seo_drafts,
        }
    except Exception as exc:
        logger.error(f"Owned Media SEO step failed: {exc}", exc_info=True)
        step_results["owned_media_seo"] = {"status": "ERROR", "error": str(exc)}

    # ── 3. Order Fulfillment Worker: Auto-fulfill pending B2C / ASK4 orders ────────
    try:
        fulfillment_res = fulfill_pending_orders(
            db=db,
            limit=25,
            fulfilled_by=f"shift-worker-{shift_id}",
        )
        step_results["order_fulfillment"] = {
            "status": "COMPLETED",
            "fulfilled_count": fulfillment_res.get("fulfilled_count", 0),
            "orders": fulfillment_res.get("orders", []),
        }
    except Exception as exc:
        logger.error(f"Order Fulfillment step failed: {exc}", exc_info=True)
        step_results["order_fulfillment"] = {"status": "ERROR", "error": str(exc)}

    # ── 4. L1 Watchdog Audit Agent: Scan system health, SLA compliance & spoofing ──
    try:
        watchdog_res = run_system_watchdog_scan(
            db=db,
            stale_minutes=60,
            correlation_id=corr_id,
            agent_id="autonomous_shift_watchdog",
        )
        step_results["watchdog_audit"] = {
            "status": "COMPLETED",
            "health_score": watchdog_res.get("health_score", 100),
            "new_alerts_detected": watchdog_res.get("new_alerts_detected", 0),
            "active_alerts_total": watchdog_res.get("active_alerts_total", 0),
            "chain_valid": watchdog_res.get("chain_valid", True),
        }
    except Exception as exc:
        logger.error(f"Watchdog Audit step failed: {exc}", exc_info=True)
        step_results["watchdog_audit"] = {"status": "ERROR", "error": str(exc)}

    completed_time = datetime.now(UTC)

    # Persist TaskRecord
    task_rec = db.get(TaskRecord, task_id)
    if not task_rec:
        task_rec = TaskRecord(
            id=task_id,
            correlation_id=corr_id,
            objective=f"Autonomous Daily Shift: {shift_type} ({shift_id})",
            status="COMPLETED",
            result=step_results,
        )
        db.add(task_rec)
    else:
        task_rec.objective = f"Autonomous Daily Shift: {shift_type} ({shift_id})"
        task_rec.status = "COMPLETED"
        task_rec.result = step_results

    # Persist AuditLog
    audit_log = AuditLog(
        task_id=task_id,
        correlation_id=corr_id,
        agent_id="autonomous_shift_scheduler",
        capability_name=CAPABILITY_NAME,
        action="run_shift",
        input_payload={"shift_id": shift_id, "shift_type": shift_type},
        output_payload={
            "shift_id": shift_id,
            "steps_completed": list(step_results.keys()),
            "outbound_leads": step_results.get("outbound_sdr", {}).get("leads_discovered_count", 0),
            "orders_fulfilled": step_results.get("order_fulfillment", {}).get("fulfilled_count", 0),
        },
        status="COMPLETED",
    )
    db.add(audit_log)
    db.flush()

    # Seal TrustBlock
    block = seal_task_to_block(
        db=db,
        task_id=task_id,
        capability_name=CAPABILITY_NAME,
        action="run_shift",
        payload={
            "shift_id": shift_id,
            "shift_type": shift_type,
            "started_at": start_time.isoformat(),
            "completed_at": completed_time.isoformat(),
            "step_statuses": {k: v.get("status") for k, v in step_results.items()},
        },
        sealed_by="autonomous_shift_scheduler",
        commit=False,
    )

    # Persist ShiftRecord
    shift_rec = ShiftRecord(
        shift_id=shift_id,
        shift_type=shift_type,
        status="COMPLETED",
        summary={
            "step_results": step_results,
            "duration_seconds": round((completed_time - start_time).total_seconds(), 2),
        },
        trust_block_hash=block.block_hash,
        started_at=start_time,
        completed_at=completed_time,
    )
    db.add(shift_rec)
    db.commit()

    logger.info(f"Autonomous shift '{shift_id}' completed successfully in {round((completed_time - start_time).total_seconds(), 2)}s.")

    return {
        "status": "COMPLETED",
        "shift_id": shift_id,
        "shift_type": shift_type,
        "started_at": start_time.isoformat(),
        "completed_at": completed_time.isoformat(),
        "duration_seconds": round((completed_time - start_time).total_seconds(), 2),
        "steps": step_results,
        "step_results": step_results,
        "trust_block_hash": block.block_hash,
        "block_index": block.index,
        "task_id": task_id,
    }


def get_ceo_daily_briefing(db: Session) -> dict[str, Any]:
    """Compile the CEO Daily Executive Briefing for Vipul (L0 Owner)."""
    now = datetime.now(UTC)

    # 1. Total revenue & orders calculation
    total_orders = db.query(OrderRecord).count()
    fulfilled_orders = db.query(OrderRecord).filter_by(status="FULFILLED").count()
    confirmed_orders = db.query(OrderRecord).filter_by(status="CONFIRMED").count()

    inr_orders_sum = (
        db.query(func.coalesce(func.sum(OrderRecord.amount), 0.0))
        .filter(OrderRecord.currency == "INR")
        .scalar()
    ) or 0.0

    usd_orders_sum = (
        db.query(func.coalesce(func.sum(OrderRecord.amount), 0.0))
        .filter(OrderRecord.currency == "USD")
        .scalar()
    ) or 0.0

    paid_invoices_inr = (
        db.query(func.coalesce(func.sum(InvoiceRecord.amount), 0))
        .filter(InvoiceRecord.status == "paid", InvoiceRecord.currency == "INR")
        .scalar()
    ) or 0
    # InvoiceRecord amount is in paise
    inr_invoices_total = paid_invoices_inr / 100.0

    paid_invoices_usd = (
        db.query(func.coalesce(func.sum(InvoiceRecord.amount), 0))
        .filter(InvoiceRecord.status == "paid", InvoiceRecord.currency == "USD")
        .scalar()
    ) or 0
    usd_invoices_total = paid_invoices_usd / 100.0

    total_revenue_inr = round(float(inr_orders_sum) + float(inr_invoices_total), 2)
    total_revenue_usd = round(float(usd_orders_sum) + float(usd_invoices_total), 2)

    # 2. Multi-tenant and Lead counts
    active_tenants = db.query(OrganizationRecord).filter_by(is_active=True).count()
    total_tenants = db.query(OrganizationRecord).count()
    total_leads = db.query(LeadRecordRow).count()
    qualified_leads = db.query(LeadRecordRow).filter(LeadRecordRow.status.in_(("QUALIFIED", "CONTACTED", "CONVERTED"))).count()

    # 3. Governance: HITL Approvals
    pending_approvals = db.query(ApprovalRequest).filter_by(status="PENDING").count()
    total_approvals = db.query(ApprovalRequest).count()

    # 4. System Watchdog Telemetry
    telemetry = get_system_control_telemetry(db)
    health_score = telemetry.get("health_score", 100)
    active_alerts = telemetry.get("active_alerts_total", 0)

    # 5. Latest Shift Execution Summary
    latest_shift = (
        db.query(ShiftRecord)
        .order_by(ShiftRecord.started_at.desc())
        .first()
    )
    shift_summary = None
    if latest_shift:
        shift_summary = {
            "shift_id": latest_shift.shift_id,
            "shift_type": latest_shift.shift_type,
            "status": latest_shift.status,
            "started_at": latest_shift.started_at.isoformat() if latest_shift.started_at else None,
            "completed_at": latest_shift.completed_at.isoformat() if latest_shift.completed_at else None,
            "summary": latest_shift.summary,
            "trust_block_hash": latest_shift.trust_block_hash,
        }

    # 6. Synthesized Executive Narrative
    exec_narrative = (
        f"AskforWrite Company AI OS is operating with a {health_score}/100 system health score. "
        f"The 1-person autonomous enterprise currently oversees {active_tenants} active tenant organizations, "
        f"₹{total_revenue_inr:,} in domestic revenue, and ${total_revenue_usd:,} in international revenue. "
        f"There are {pending_approvals} human-in-the-loop decisions awaiting owner approval. "
        f"Autonomous shifts are actively discovering SMB leads, staging WordPress publications, and fulfilling customer orders."
    )

    return {
        "title": "AskforWrite AI Company OS — CEO Executive Daily Digest",
        "owner": "Vipul Choubisa",
        "role": "L0 Owner & CEO",
        "briefing_timestamp": now.isoformat(),
        "executive_summary": exec_narrative,
        "revenue": {
            "total_revenue_inr": total_revenue_inr,
            "total_revenue_usd": total_revenue_usd,
            "total_orders": total_orders,
            "fulfilled_orders": fulfilled_orders,
            "confirmed_orders": confirmed_orders,
        },
        "tenants": {
            "active_tenants": active_tenants,
            "total_tenants": total_tenants,
            "total_leads": total_leads,
            "qualified_leads": qualified_leads,
        },
        "governance": {
            "pending_hitl_approvals": pending_approvals,
            "total_approvals": total_approvals,
        },
        "watchdog": {
            "health_score": health_score,
            "active_alerts": active_alerts,
            "chain_valid": telemetry.get("chain_valid", True),
        },
        "latest_shift": shift_summary,
    }


def get_scheduler_status(db: Session) -> dict[str, Any]:
    """Retrieve the operational status of the autonomous shift scheduler and employee roster."""
    latest_shift = (
        db.query(ShiftRecord)
        .order_by(ShiftRecord.started_at.desc())
        .first()
    )

    total_shifts_run = db.query(ShiftRecord).count()

    return {
        "status": "OPERATIONAL",
        "scheduler_mode": "autonomous_periodic",
        "total_shifts_executed": total_shifts_run,
        "last_shift": {
            "shift_id": latest_shift.shift_id,
            "shift_type": latest_shift.shift_type,
            "status": latest_shift.status,
            "started_at": latest_shift.started_at.isoformat() if latest_shift.started_at else None,
            "completed_at": latest_shift.completed_at.isoformat() if latest_shift.completed_at else None,
        } if latest_shift else None,
        "employee_roster": {
            "outbound_sdr": {
                "name": "Outbound SDR AI Agent",
                "role": "SMB discovery & Trojan-Horse preview creation",
                "status": "READY",
            },
            "owned_media_seo": {
                "name": "Owned Media Publisher Copilot",
                "role": "4-site WordPress topical authority article staging",
                "status": "READY",
            },
            "order_fulfillment": {
                "name": "Automated B2C / ASK4 Fulfillment Worker",
                "role": "Batch deliverable synthesis & milestone completion",
                "status": "READY",
            },
            "watchdog_audit": {
                "name": "L1 System Watchdog & Anti-Spoofing Auditor",
                "role": "24/7 SLA compliance, alert detection & telemetry scoring",
                "status": "READY",
            },
        },
        "supported_shift_types": [
            "full_daily_cycle",
            "outbound_sdr_only",
            "seo_publishing_only",
            "watchdog_audit_only",
        ],
    }
