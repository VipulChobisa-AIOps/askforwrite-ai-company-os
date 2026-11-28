"""FieldGuard Phase 2: Org Expense Policies, Multi-Day Tour Plans, Manager Claim Adjudication & Finance Payout Exports.

Implements:
1. Per-org & employee-grade Travel/DA/Lodging/Conveyance Policy CRUD.
2. Multi-day outstation Tour Plans with manager approval, advance tracking & ECDSA-sealed Tour Settlement Voucher.
3. Append-only ECDSA-sealed Manager Review Queue (`APPROVE | PARTIAL_APPROVE | REJECT`) preserving claim immutability.
4. 1-Click Monthly Reimbursement Finance Exports: CSV, Tally XML, ICICI NEFT Bulk & HDFC NEFT Bulk with batch hash.
"""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
import xml.sax.saxutils as xml_utils
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    ConveyanceClaimRecord,
    ConveyanceClaimReviewRecord,
    FieldExpensePolicyRecord,
    FieldTourPlanRecord,
    UserRecord,
)
from app.schemas.field_force import (
    ConveyanceClaimReviewRequest,
    FieldExpensePolicyUpsert,
    FieldTourPlanApproveRequest,
    FieldTourPlanCreate,
)
from app.security.trust_chain import seal_task_to_block
from app.services.field_conveyance import enrich_claim_with_review


# ── 1. Per-Org & Grade Travel/Conveyance Policy Management ────────────


def upsert_expense_policy(
    db: Session,
    *,
    org_id: str | None,
    req: FieldExpensePolicyUpsert,
) -> FieldExpensePolicyRecord:
    """Create or update an organization's grade-specific travel & conveyance policy."""
    norm_grade = req.grade.strip().upper()
    existing = (
        db.query(FieldExpensePolicyRecord)
        .filter(
            FieldExpensePolicyRecord.org_id == org_id,
            FieldExpensePolicyRecord.grade == norm_grade,
        )
        .first()
    )
    if existing is None:
        existing = FieldExpensePolicyRecord(
            id=str(uuid.uuid4()),
            org_id=org_id,
            grade=norm_grade,
        )
        db.add(existing)

    existing.two_wheeler_rate_inr = req.two_wheeler_rate_inr
    existing.four_wheeler_rate_inr = req.four_wheeler_rate_inr
    existing.public_transit_rate_inr = req.public_transit_rate_inr
    existing.daily_auto_approve_limit_inr = req.daily_auto_approve_limit_inr
    existing.max_daily_distance_km = req.max_daily_distance_km
    existing.tier1_da_inr = req.tier1_da_inr
    existing.tier2_da_inr = req.tier2_da_inr
    existing.tier3_da_inr = req.tier3_da_inr
    existing.tier1_hotel_cap_inr = req.tier1_hotel_cap_inr
    existing.tier2_hotel_cap_inr = req.tier2_hotel_cap_inr
    existing.tier3_hotel_cap_inr = req.tier3_hotel_cap_inr
    existing.fuel_max_inr_per_km = req.fuel_max_inr_per_km
    existing.require_ocr_above_inr = req.require_ocr_above_inr
    existing.is_active = True
    existing.updated_at = datetime.now(UTC)

    db.commit()
    db.refresh(existing)
    return existing


def list_expense_policies(
    db: Session,
    *,
    org_id: str | None,
) -> list[FieldExpensePolicyRecord]:
    query = db.query(FieldExpensePolicyRecord).filter(FieldExpensePolicyRecord.is_active.is_(True))
    if org_id is not None:
        query = query.filter(FieldExpensePolicyRecord.org_id == org_id)
    return query.order_by(FieldExpensePolicyRecord.grade.asc()).all()


# ── 2. Multi-Day Outstation Tour Plans & End-of-Trip Settlement ───────


def create_tour_plan(
    db: Session,
    *,
    org_id: str | None,
    user_id: str,
    req: FieldTourPlanCreate,
) -> FieldTourPlanRecord:
    """Submit a multi-day business tour plan for manager approval."""
    if req.end_date < req.start_date:
        raise ValueError("Tour end_date cannot be earlier than start_date")

    tour = FieldTourPlanRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        title=req.title.strip(),
        purpose=req.purpose.strip(),
        start_date=req.start_date,
        end_date=req.end_date,
        cities_json=[c.model_dump() for c in req.cities],
        client_targets_json=list(req.client_targets),
        estimated_budget_inr=round(float(req.estimated_budget_inr), 2),
        advance_requested_inr=round(float(req.advance_requested_inr), 2),
        advance_approved_inr=0.0,
        status="SUBMITTED",
    )
    db.add(tour)
    db.commit()
    db.refresh(tour)
    return tour


def list_tour_plans(
    db: Session,
    *,
    org_id: str | None,
    user_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[FieldTourPlanRecord]:
    query = db.query(FieldTourPlanRecord)
    if org_id is not None:
        query = query.filter(FieldTourPlanRecord.org_id == org_id)
    if user_id is not None:
        query = query.filter(FieldTourPlanRecord.user_id == user_id)
    if status:
        query = query.filter(FieldTourPlanRecord.status == status.strip().upper())
    return query.order_by(FieldTourPlanRecord.created_at.desc()).limit(limit).all()


def approve_tour_plan(
    db: Session,
    *,
    org_id: str | None,
    tour_id: str,
    reviewer_subject: str,
    req: FieldTourPlanApproveRequest,
) -> FieldTourPlanRecord:
    """Manager approves or rejects a tour plan & sets approved travel advance, sealed in ECDSA chain."""
    tour = db.get(FieldTourPlanRecord, tour_id)
    if not tour:
        raise ValueError(f"Tour plan {tour_id} not found")
    if org_id is not None and tour.org_id != org_id:
        raise PermissionError("Tour plan belongs to another organization")
    if tour.status == "SETTLED":
        raise ValueError("Tour plan is already settled")

    now = datetime.now(UTC)
    if req.decision == "APPROVE":
        tour.status = "APPROVED"
        tour.advance_approved_inr = round(
            float(req.advance_approved_inr if req.advance_approved_inr is not None else tour.advance_requested_inr),
            2,
        )
    else:
        tour.status = "REJECTED"
        tour.advance_approved_inr = 0.0

    tour.approved_by = reviewer_subject
    tour.approved_at = now
    tour.approval_notes = req.notes
    tour.updated_at = now

    try:
        seal_task_to_block(
            db=db,
            task_id=tour.id,
            capability_name="field_tour_governance",
            action=f"tour_plan_{req.decision.lower()}",
            payload={
                "tour_id": tour.id,
                "user_id": tour.user_id,
                "decision": req.decision,
                "advance_approved_inr": tour.advance_approved_inr,
                "approved_by": reviewer_subject,
            },
            sealed_by="AFW-FIELDGUARD-TOUR-ENGINE",
            commit=False,
        )
    except Exception:
        pass

    db.commit()
    db.refresh(tour)
    return tour


def settle_tour_plan(
    db: Session,
    *,
    org_id: str | None,
    tour_id: str,
    settled_by: str,
) -> dict[str, Any]:
    """Generate a single ECDSA-sealed Tour Settlement Voucher reconciling all linked claims vs travel advance."""
    tour = db.get(FieldTourPlanRecord, tour_id)
    if not tour:
        raise ValueError(f"Tour plan {tour_id} not found")
    if org_id is not None and tour.org_id != org_id:
        raise PermissionError("Tour plan belongs to another organization")
    if tour.status == "REJECTED":
        raise ValueError("Cannot settle a rejected tour plan")

    claims_q = db.query(ConveyanceClaimRecord).filter(ConveyanceClaimRecord.tour_plan_id == tour.id)
    if org_id is not None:
        claims_q = claims_q.filter(ConveyanceClaimRecord.org_id == org_id)
    linked_claims = claims_q.order_by(ConveyanceClaimRecord.claim_date.asc()).all()

    enriched = [enrich_claim_with_review(db, c) for c in linked_claims]
    total_km = round(sum(c["verified_road_distance_km"] for c in enriched), 2)
    total_claimed = round(sum(c["grand_total_amount"] for c in enriched), 2)
    total_approved = round(sum(c["effective_payout_amount"] for c in enriched), 2)
    pending_review_count = sum(1 for c in enriched if c["effective_status"] == "FLAGGED_FOR_REVIEW")

    if pending_review_count > 0:
        raise ValueError(
            f"Cannot settle tour: {pending_review_count} linked claim(s) still require manager review"
        )

    advance_paid = round(float(tour.advance_approved_inr or 0.0), 2)
    net_payable = round(total_approved - advance_paid, 2)
    settlement_direction = (
        "PAYABLE_TO_EMPLOYEE" if net_payable > 0 else ("RECOVERABLE_FROM_EMPLOYEE" if net_payable < 0 else "EXACT_SETTLED")
    )

    voucher = {
        "voucher_id": f"TSV-{tour.id[:8].upper()}",
        "tour_id": tour.id,
        "title": tour.title,
        "user_id": tour.user_id,
        "start_date": tour.start_date,
        "end_date": tour.end_date,
        "cities": tour.cities_json,
        "claims_count": len(enriched),
        "total_verified_road_km": total_km,
        "total_claimed_inr": total_claimed,
        "total_approved_inr": total_approved,
        "advance_paid_inr": advance_paid,
        "net_settlement_inr": net_payable,
        "settlement_direction": settlement_direction,
        "settled_by": settled_by,
        "settled_at": datetime.now(UTC).isoformat(),
    }

    trust_hash = None
    try:
        block = seal_task_to_block(
            db=db,
            task_id=tour.id,
            capability_name="field_tour_settlement",
            action="tour_settlement_voucher_sealed",
            payload=voucher,
            sealed_by="AFW-FIELDGUARD-TOUR-ENGINE",
            commit=False,
        )
        trust_hash = block.block_hash
    except Exception:
        pass

    tour.status = "SETTLED"
    tour.settlement_summary_json = voucher
    tour.settlement_trust_block_hash = trust_hash
    tour.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(tour)

    voucher["trust_block_hash"] = trust_hash
    return voucher


# ── 3. Append-Only Manager Claim Review Queue ─────────────────────────


def review_conveyance_claim(
    db: Session,
    *,
    org_id: str | None,
    claim_id: str,
    reviewer_user_id: str | None,
    reviewer_email: str,
    req: ConveyanceClaimReviewRequest,
) -> ConveyanceClaimReviewRecord:
    """Adjudicate a conveyance claim (APPROVE, PARTIAL_APPROVE, REJECT) via append-only ECDSA-sealed record."""
    claim = db.get(ConveyanceClaimRecord, claim_id)
    if not claim:
        raise ValueError(f"Conveyance claim {claim_id} not found")
    if org_id is not None and claim.org_id != org_id:
        raise PermissionError("Conveyance claim belongs to another organization")

    claimed_amt = round(float(claim.grand_total_amount), 2)
    if req.decision == "APPROVE":
        approved_amt = claimed_amt
    elif req.decision == "REJECT":
        approved_amt = 0.0
    else:  # PARTIAL_APPROVE
        if req.approved_amount_inr is None:
            raise ValueError("approved_amount_inr is required for PARTIAL_APPROVE")
        approved_amt = round(float(req.approved_amount_inr), 2)
        if approved_amt <= 0.0 or approved_amt >= claimed_amt:
            raise ValueError(
                f"PARTIAL_APPROVE amount (₹{approved_amt}) must be > 0 and < claimed amount (₹{claimed_amt})"
            )

    review_id = str(uuid.uuid4())
    reviewed_at = datetime.now(UTC)

    trust_hash = None
    try:
        block = seal_task_to_block(
            db=db,
            task_id=review_id,
            capability_name="conveyance_manager_review",
            action=f"claim_{req.decision.lower()}",
            payload={
                "review_id": review_id,
                "claim_id": claim.id,
                "user_id": claim.user_id,
                "decision": req.decision,
                "claimed_amount_inr": claimed_amt,
                "approved_amount_inr": approved_amt,
                "reviewer_email": reviewer_email,
                "reason": req.reason,
                "reviewed_at": reviewed_at.isoformat(),
            },
            sealed_by="AFW-FIELDGUARD-REVIEW-ENGINE",
            commit=False,
        )
        trust_hash = block.block_hash
    except Exception:
        pass

    review = ConveyanceClaimReviewRecord(
        id=review_id,
        claim_id=claim.id,
        org_id=claim.org_id,
        decision=req.decision,
        claimed_amount_inr=claimed_amt,
        approved_amount_inr=approved_amt,
        reviewer_user_id=reviewer_user_id,
        reviewer_email=reviewer_email,
        reason=req.reason.strip(),
        trust_block_hash=trust_hash,
        reviewed_at=reviewed_at,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


# ── 4. Monthly Finance Payout Exports (CSV / Tally XML / ICICI & HDFC NEFT) ──


def export_monthly_reimbursements(
    db: Session,
    *,
    org_id: str | None,
    month: str,  # YYYY-MM
    export_format: str = "csv",
) -> dict[str, Any]:
    """Generate CFO-ready monthly payout export grouped by employee with cryptographic audit digest."""
    q = db.query(ConveyanceClaimRecord).filter(ConveyanceClaimRecord.claim_date.startswith(month))
    if org_id is not None:
        q = q.filter(ConveyanceClaimRecord.org_id == org_id)
    claims = q.order_by(ConveyanceClaimRecord.claim_date.asc()).all()

    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "user_id": "",
            "employee_name": "",
            "employee_email": "",
            "claims_count": 0,
            "total_verified_km": 0.0,
            "approved_conveyance_inr": 0.0,
            "approved_expenses_inr": 0.0,
            "net_payout_inr": 0.0,
            "claim_ids": [],
        }
    )

    approved_statuses = {"AUTO_APPROVED", "MANUALLY_APPROVED", "PARTIALLY_APPROVED"}
    for c in claims:
        enriched = enrich_claim_with_review(db, c)
        if enriched["effective_status"] not in approved_statuses or enriched["effective_payout_amount"] <= 0:
            continue
        row = grouped[c.user_id]
        row["user_id"] = c.user_id
        row["claims_count"] += 1
        row["total_verified_km"] = round(row["total_verified_km"] + float(c.verified_road_distance_km), 2)
        row["approved_conveyance_inr"] = round(row["approved_conveyance_inr"] + float(c.total_conveyance_amount), 2)
        row["approved_expenses_inr"] = round(row["approved_expenses_inr"] + float(c.total_expenses_amount), 2)
        row["net_payout_inr"] = round(row["net_payout_inr"] + float(enriched["effective_payout_amount"]), 2)
        row["claim_ids"].append(c.id)

    # Enrich employee names/emails from UserRecord
    rows = []
    for uid, row in sorted(grouped.items()):
        user = db.get(UserRecord, uid)
        row["employee_name"] = user.full_name if user else uid
        row["employee_email"] = user.email if user else ""
        rows.append(row)

    total_payout_inr = round(sum(r["net_payout_inr"] for r in rows), 2)
    canonical_digest_input = f"{org_id or 'platform'}|{month}|{total_payout_inr:.2f}|" + ",".join(
        f"{r['user_id']}:{r['net_payout_inr']:.2f}" for r in rows
    )
    audit_batch_sha256 = hashlib.sha256(canonical_digest_input.encode("utf-8")).hexdigest()

    fmt = export_format.strip().lower()
    if fmt == "tally_xml":
        vouchers_xml: list[str] = []
        voucher_date = f"{month.replace('-', '')}28"
        for r in rows:
            emp = xml_utils.escape(r["employee_name"])
            narr = xml_utils.escape(
                f"FieldGuard Conveyance & Tour Reimbursement {month} ({r['claims_count']} claims, {r['total_verified_km']} km) | AuditSHA256:{audit_batch_sha256[:16]}"
            )
            amt = f"{r['net_payout_inr']:.2f}"
            vouchers_xml.append(
                f"""    <TALLYMESSAGE xmlns:UDF="TallyUDF">
      <VOUCHER VCHTYPE="Journal" ACTION="Create">
        <DATE>{voucher_date}</DATE>
        <VOUCHERTYPENAME>Journal</VOUCHERTYPENAME>
        <NARRATION>{narr}</NARRATION>
        <ALLLEDGERENTRIES.LIST>
          <LEDGERNAME>Field Conveyance &amp; Travel Expense</LEDGERNAME>
          <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
          <AMOUNT>-{amt}</AMOUNT>
        </ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST>
          <LEDGERNAME>{emp} - Reimbursement Payable</LEDGERNAME>
          <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
          <AMOUNT>{amt}</AMOUNT>
        </ALLLEDGERENTRIES.LIST>
      </VOUCHER>
    </TALLYMESSAGE>"""
            )
        content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<ENVELOPE>\n"
            "  <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>\n"
            "  <BODY>\n"
            "    <IMPORTDATA>\n"
            "      <REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME></REQUESTDESC>\n"
            "      <REQUESTDATA>\n"
            + "\n".join(vouchers_xml)
            + "\n      </REQUESTDATA>\n"
            "    </IMPORTDATA>\n"
            "  </BODY>\n"
            f"  <!-- AFW-FIELDGUARD-AUDIT-SHA256: {audit_batch_sha256} -->\n"
            "</ENVELOPE>\n"
        )
        return {
            "content": content,
            "media_type": "application/xml",
            "filename": f"fieldguard_tally_{month}.xml",
            "audit_batch_sha256": audit_batch_sha256,
            "employee_count": len(rows),
            "total_payout_inr": total_payout_inr,
        }

    buf = io.StringIO()
    writer = csv.writer(buf)
    if fmt == "neft_icici":
        writer.writerow([
            "TRANSACTION_TYPE",
            "BENEFICIARY_NAME",
            "BENEFICIARY_EMAIL",
            "AMOUNT_INR",
            "PAYMENT_NARRATION",
            "CLAIMS_COUNT",
            "AUDIT_BATCH_SHA256",
        ])
        for r in rows:
            writer.writerow([
                "NEFT",
                r["employee_name"],
                r["employee_email"],
                f"{r['net_payout_inr']:.2f}",
                f"AFW FIELD REIMB {month}",
                r["claims_count"],
                audit_batch_sha256[:16],
            ])
        fname = f"fieldguard_icici_neft_{month}.csv"
    elif fmt == "neft_hdfc":
        writer.writerow([
            "Transaction Type",
            "Beneficiary Code",
            "Beneficiary Name",
            "Instrument Amount",
            "Payment Details 1",
            "Beneficiary Email",
            "Audit Hash",
        ])
        for r in rows:
            writer.writerow([
                "N",
                r["user_id"][:12],
                r["employee_name"],
                f"{r['net_payout_inr']:.2f}",
                f"FIELD REIMB {month}",
                r["employee_email"],
                audit_batch_sha256[:16],
            ])
        fname = f"fieldguard_hdfc_neft_{month}.csv"
    else:
        writer.writerow([
            "employee_user_id",
            "employee_name",
            "employee_email",
            "month",
            "approved_claims_count",
            "total_verified_road_km",
            "conveyance_inr",
            "expenses_inr",
            "net_payout_inr",
            "audit_batch_sha256",
        ])
        for r in rows:
            writer.writerow([
                r["user_id"],
                r["employee_name"],
                r["employee_email"],
                month,
                r["claims_count"],
                f"{r['total_verified_km']:.2f}",
                f"{r['approved_conveyance_inr']:.2f}",
                f"{r['approved_expenses_inr']:.2f}",
                f"{r['net_payout_inr']:.2f}",
                audit_batch_sha256,
            ])
        fname = f"fieldguard_reimbursements_{month}.csv"

    return {
        "content": buf.getvalue(),
        "media_type": "text/csv",
        "filename": fname,
        "audit_batch_sha256": audit_batch_sha256,
        "employee_count": len(rows),
        "total_payout_inr": total_payout_inr,
    }
