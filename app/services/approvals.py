"""Durable owner approval requests and decisions."""

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.agents.policy import approval_required
from app.db.models import (
    ApprovalRequest,
    AuditLog,
    LeadRecordRow,
    ProposalRecord,
    TaskRecord,
)


class ApprovalConflict(Exception):
    """Raised when an approval key or already-decided request conflicts."""


class ApprovalNotFound(Exception):
    """Raised when the referenced task or approval does not exist."""


def _request_hash(
    task_id: str,
    lead_id: str | None,
    proposal_id: str | None,
    action: str,
    detail: dict,
) -> str:
    request = json.dumps(
        {
            "task_id": task_id,
            "lead_id": lead_id,
            "proposal_id": proposal_id,
            "action": action,
            "detail": detail,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(request.encode("utf-8")).hexdigest()


def _approval_payload(
    approval: ApprovalRequest,
    external_action_performed: bool = False,
    auto_executed_action: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "approval_id": approval.id,
        "task_id": approval.task_id,
        "lead_id": approval.lead_id,
        "proposal_id": approval.proposal_id,
        "action": approval.action,
        "status": approval.status,
        "external_action_performed": external_action_performed,
    }
    if auto_executed_action:
        payload["auto_executed_action"] = auto_executed_action
    return payload


def request_approval(
    db: Session,
    task_id: str,
    lead_id: str | None,
    action: str,
    detail: dict,
    idempotency_key: str,
    requested_by: str,
    correlation_id: str,
    proposal_id: str | None = None,
    commit: bool = True,
) -> dict[str, object]:
    key = idempotency_key.strip()
    if not key:
        raise ValueError("idempotency_key must not be empty")
    if not approval_required(action):
        raise ValueError("action does not require owner approval")

    request_hash = _request_hash(task_id, lead_id, proposal_id, action, detail)
    existing = db.query(ApprovalRequest).filter_by(idempotency_key=key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise ApprovalConflict("Idempotency key was already used for another approval")
        return _approval_payload(existing)

    task = db.get(TaskRecord, task_id)
    if task is None:
        raise ApprovalNotFound("Task not found")

    if action == "external_sales_outreach":
        if lead_id is None:
            raise ValueError("lead_id is required for external sales outreach approval")
        lead = db.get(LeadRecordRow, lead_id)
        if lead is None or lead.task_id != task_id:
            raise ApprovalNotFound("Lead not found for this task")
        if lead.do_not_contact or lead.status == "DO_NOT_CONTACT":
            raise ValueError("do-not-contact leads cannot be approved for outreach")
        allowed_outreach_statuses = {"DISCOVERED", "RESEARCHED", "QUALIFIED"}
        if detail and detail.get("allow_follow_up"):
            allowed_outreach_statuses |= {"CONTACTED", "REPLIED"}
        if lead.status not in allowed_outreach_statuses:
            raise ValueError(f"lead status {lead.status} cannot be approved for outreach")
    elif lead_id is not None and db.get(LeadRecordRow, lead_id) is None:
        raise ApprovalNotFound("Lead not found")

    if action == "proposal_delivery":
        # proposal_id is optional at request time; validation occurs later when the proposal exists.
        if proposal_id is not None:
            proposal = db.get(ProposalRecord, proposal_id)
            if proposal is None or proposal.task_id != task_id or proposal.lead_id != lead_id:
                raise ApprovalNotFound("Proposal not found for this task and lead")
            if proposal.status != "AWAITING_APPROVAL":
                raise ValueError("proposal must be awaiting approval")

    approval = ApprovalRequest(
        id=str(uuid4()),
        task_id=task_id,
        lead_id=lead_id,
        proposal_id=proposal_id,
        action=action,
        detail=detail,
        idempotency_key=key,
        request_hash=request_hash,
        status="PENDING",
        requested_by=requested_by,
    )
    db.add(approval)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(ApprovalRequest).filter_by(idempotency_key=key).first()
        if existing:
            if existing.request_hash != request_hash:
                raise ApprovalConflict("Idempotency key was already used for another approval")
            return _approval_payload(existing)
        raise

    db.add(AuditLog(
        task_id=task_id,
        correlation_id=correlation_id,
        agent_id=requested_by,
        capability_name="human_approval",
        action="approval_requested",
        input_payload={
            "approval_id": approval.id,
            "action": action,
            "lead_id": lead_id,
            "proposal_id": proposal_id,
        },
        output_payload={"status": "PENDING"},
        status="COMPLETED",
    ))
    if commit:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
    else:
        db.flush()
    return _approval_payload(approval)


def decide_approval(
    db: Session,
    approval_id: str,
    decision: str,
    decided_by: str = "owner",
    correlation_id: str | None = None,
    decision_note: str | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    effective_corr_id = correlation_id or str(uuid4())
    effective_note = reason or decision_note
    approval = db.query(ApprovalRequest).filter_by(id=approval_id).with_for_update().first()
    if approval is None:
        raise ApprovalNotFound("Approval request not found")
    if decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("decision must be APPROVED or REJECTED")
    if approval.status != "PENDING":
        if approval.status == decision:
            return _approval_payload(approval)
        raise ApprovalConflict(f"Approval request is already {approval.status}")

    lead = db.get(LeadRecordRow, approval.lead_id) if approval.lead_id else None
    if approval.action == "external_sales_outreach" and lead is not None:
        if lead.do_not_contact or lead.status == "DO_NOT_CONTACT":
            raise ApprovalConflict("do-not-contact leads cannot be approved for outreach")
        lead.status = "APPROVED_FOR_OUTREACH" if decision == "APPROVED" else "REJECTED"
    if approval.action == "proposal_delivery" and approval.proposal_id:
        proposal = db.get(ProposalRecord, approval.proposal_id)
        if proposal is None or proposal.status != "AWAITING_APPROVAL":
            raise ApprovalConflict("proposal is no longer awaiting approval")
        proposal.status = decision
        proposal.decided_at = datetime.now(UTC)
        if lead is not None:
            lead.status = "PROPOSAL_APPROVED" if decision == "APPROVED" else "PROPOSAL_REJECTED"

        from app.db.models import P2CommercialProposalRecord, P2ProspectDossierRecord

        p2_prop = (
            db.query(P2CommercialProposalRecord)
            .filter(
                (P2CommercialProposalRecord.approval_id == approval.id)
                | (P2CommercialProposalRecord.proposal_record_id == approval.proposal_id)
            )
            .first()
        )
        if p2_prop:
            p2_prop.status = "APPROVED" if decision == "APPROVED" else "REJECTED"
            if decision == "APPROVED":
                p2_prop.approved_by = decided_by
                p2_prop.approved_at = datetime.now(UTC)
            db.add(p2_prop)
            dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=p2_prop.lead_id).first()
            if dossier:
                dossier.next_action = (
                    "Share approved proposal & verified checkout link with prospect"
                    if decision == "APPROVED"
                    else "Revise rejected proposal before sharing"
                )
                db.add(dossier)

    approval.status = decision
    approval.decided_by = decided_by
    approval.decision_note = effective_note
    approval.decided_at = datetime.now(UTC)

    task = db.get(TaskRecord, approval.task_id) if approval.task_id else None
    if task:
        task.status = "COMPLETED" if decision == "APPROVED" else "REJECTED"

    external_action_performed = False
    auto_executed_action = None

    if decision == "APPROVED":
        from app.db.models import OutreachRecord, SeoDraftRecord

        # 1. Linked Outreach handling
        outreach = (
            db.query(OutreachRecord).filter_by(approval_id=approval.id).first()
            or (db.query(OutreachRecord).filter_by(task_id=approval.task_id).first() if approval.task_id else None)
        )
        if outreach and outreach.status in ("PENDING_APPROVAL", "APPROVED"):
            meta = outreach.metadata_json or {}
            is_p2 = bool(meta.get("p2_commercial"))
            auto_dispatch_p2 = (
                os.getenv("ENABLE_AUTONOMOUS_SALES_AUTO_DISPATCH", "").strip().lower() in ("1", "true", "yes")
                or bool(meta.get("auto_dispatch_on_approval"))
            )
            if is_p2:
                outreach.status = "APPROVED"
                db.add(outreach)
                db.flush()
                from app.db.models import P2ProspectDossierRecord

                if auto_dispatch_p2:
                    from app.services.p2_outreach_pipeline import dispatch_p2_outreach

                    try:
                        disp_res = dispatch_p2_outreach(
                            db,
                            outreach_id=outreach.id,
                            dispatched_by=decided_by,
                            correlation_id=effective_corr_id,
                        )
                        if disp_res.get("external_sent"):
                            external_action_performed = True
                            auto_executed_action = "p2_outreach_dispatched"
                        else:
                            external_action_performed = False
                            auto_executed_action = "p2_outreach_simulated"
                    except Exception as disp_exc:
                        logger.warning("P2 outreach auto-dispatch failed closed for %s: %s", outreach.id, disp_exc)
                        external_action_performed = False
                        auto_executed_action = "p2_outreach_dispatch_failed"
                else:
                    dossier = db.query(P2ProspectDossierRecord).filter_by(lead_id=outreach.lead_id).first()
                    if dossier:
                        dossier.next_action = f"Dispatch approved outreach '{outreach.id}'"
                        db.add(dossier)
                    external_action_performed = False
                    auto_executed_action = "p2_outreach_approved_ready_to_send"
            else:
                from app.services.outreach import dispatch_outreach
                try:
                    disp_res = dispatch_outreach(
                        db=db,
                        outreach_id=outreach.id,
                        correlation_id=effective_corr_id,
                        dispatched_by=decided_by,
                    )
                    if disp_res.get("status") in ("DISPATCHED", "SENT", "SIMULATED_SENT"):
                        external_action_performed = disp_res.get("status") in ("DISPATCHED", "SENT")
                        auto_executed_action = "outreach_dispatched"
                    else:
                        external_action_performed = False
                        auto_executed_action = "outreach_dispatch_failed"
                except Exception as disp_exc:
                    logger.warning("Outreach auto-dispatch failed closed for %s: %s", outreach.id, disp_exc)
                    outreach.status = "FAILED"
                    outreach.error_message = str(disp_exc)[:500]
                    db.add(outreach)
                    external_action_performed = False
                    auto_executed_action = "outreach_dispatch_failed"

        # 2. Linked SEO draft publishing via WordPress Bridge (fail-closed — never mask failures as PUBLISHED)
        seo_draft = (
            db.query(SeoDraftRecord).filter_by(approval_id=approval.id).first()
            or (db.query(SeoDraftRecord).filter_by(task_id=approval.task_id).first() if approval.task_id else None)
        )
        if not seo_draft and approval.detail and "seo_draft_id" in approval.detail:
            seo_draft = db.get(SeoDraftRecord, approval.detail["seo_draft_id"])

        gate_type = getattr(approval, "gate_type", None) or (approval.detail.get("gate_type") if approval.detail else None)
        if seo_draft or gate_type == "live_publishing" or approval.action == "live_publishing":
            if seo_draft:
                if not seo_draft.approval_id:
                    seo_draft.approval_id = approval.id
                    db.add(seo_draft)
                db.flush()
                from app.services.wordpress_publisher import WordPressPublishError, publish_seo_draft_to_wordpress
                try:
                    wp_result = publish_seo_draft_to_wordpress(
                        db=db,
                        draft_id=seo_draft.id,
                        correlation_id=effective_corr_id,
                        published_by=decided_by,
                    )
                    wp_status = wp_result.get("status")
                    if wp_status == "PUBLISHED":
                        external_action_performed = True
                        auto_executed_action = "seo_draft_published"
                    elif wp_status == "SIMULATED":
                        external_action_performed = False
                        auto_executed_action = "seo_draft_simulated"
                    else:
                        external_action_performed = False
                        auto_executed_action = "seo_draft_publish_failed"
                except (WordPressPublishError, RuntimeError):
                    external_action_performed = False
                    auto_executed_action = "seo_draft_publish_failed"
            else:
                external_action_performed = False
                auto_executed_action = "seo_draft_approved_no_draft_found"

        # 3. Linked Marketing Campaign auto-dispatch
        from app.db.models import MarketingCampaignRecord
        campaign = (
            db.query(MarketingCampaignRecord).filter_by(approval_id=approval.id).first()
            or (db.query(MarketingCampaignRecord).filter_by(task_id=approval.task_id).first() if approval.task_id else None)
        )
        if not campaign and approval.detail and "campaign_id" in approval.detail:
            campaign = db.get(MarketingCampaignRecord, approval.detail["campaign_id"])

        if campaign or approval.action in ("external_messaging", "external_publishing_high_risk"):
            if campaign:
                campaign.status = "DISPATCHED"
                campaign.decided_at = datetime.now(UTC)
                db.add(campaign)
            external_action_performed = True
            auto_executed_action = "marketing_campaign_dispatched"

        # 4. Linked Sovereign Payment auto-confirmation & tenant provisioning
        if (
            approval.action == "sovereign_payment_verification"
            and approval.detail
            and "session_id" in approval.detail
        ):
            from app.services.sovereign_pay import confirm_sovereign_payment_by_owner

            confirm_sovereign_payment_by_owner(
                session_id=approval.detail["session_id"],
                db=db,
                decided_by=decided_by,
            )
            external_action_performed = True
            auto_executed_action = "sovereign_payment_provisioned"

        # 5. Cryptographic TrustBlock sealing for approval decision
        try:
            from app.security.trust_chain import seal_task_to_block
            seal_task_to_block(
                db=db,
                task_id=approval.task_id or approval.id,
                capability_name="human_approval",
                action="approval_decided",
                payload={
                    "approval_id": approval.id,
                    "decision": decision,
                    "decided_by": decided_by,
                    "auto_executed_action": auto_executed_action,
                },
                sealed_by=decided_by,
                commit=False,
            )
        except Exception:
            pass

    db.add(AuditLog(
        task_id=approval.task_id,
        correlation_id=effective_corr_id,
        agent_id=decided_by,
        capability_name="human_approval",
        action="approval_decided",
        input_payload={
            "approval_id": approval.id,
            "action": approval.action,
            "proposal_id": approval.proposal_id,
        },
        output_payload={
            "decision": decision,
            "lead_id": approval.lead_id,
            "proposal_id": approval.proposal_id,
            "external_action_performed": external_action_performed,
            "auto_executed_action": auto_executed_action,
        },
        status="COMPLETED",
    ))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _approval_payload(
        approval,
        external_action_performed=external_action_performed,
        auto_executed_action=auto_executed_action,
    )