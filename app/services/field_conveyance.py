"""Fraud-Proof Conveyance & Expense Audit Service for AskforWrite FieldGuard Engine.

Implements:
1. GPS stationary jitter filtering & impossible-velocity rejection.
2. Optional OSRM / Google Routes road-snapping with explicit distance_method disclosure.
3. Per-org & employee-grade configurable rates, DA, hotel lodging caps, and auto-approve limits.
4. Real Gemini Vision multimodal Receipt OCR (1 AI Credit; never fakes is_verified=True).
5. Cross-claim duplicate receipt fraud detection (exact SHA-256, perceptual dHash, and merchant+invoice+amount).
6. Durable content-addressed receipt image persistence & ECDSA audit sealing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.parse
import urllib.request
import uuid
from datetime import UTC
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    ConveyanceClaimRecord,
    ConveyanceClaimReviewRecord,
    ExpenseReceiptRecord,
    FieldExpensePolicyRecord,
    FieldTourPlanRecord,
)
from app.schemas.field_force import (
    ConveyanceClaimSubmitRequest,
    GpsBreadcrumb,
)
from app.security.trust_chain import seal_task_to_block
from app.services.field_evidence_storage import (
    decode_base64_image,
    hamming_distance_hex,
    inspect_image_integrity,
    persist_evidence_bytes,
)
from app.services.field_presence import calculate_haversine_distance

logger = logging.getLogger(__name__)

RATE_PER_KM = {
    "TWO_WHEELER": 4.50,
    "FOUR_WHEELER": 10.00,
    "PUBLIC_TRANSIT": 2.50,
}

ROAD_CURVATURE_FACTOR = 1.18
STATIONARY_JITTER_METERS = 25.0
MAX_ALLOWABLE_SPEED_KMH = 140.0
DAILY_AUTO_APPROVE_LIMIT = 2000.0
PHASH_DUPLICATE_MAX_HAMMING = 8
OCR_AMOUNT_TOLERANCE_INR = 5.0
OCR_MIN_CONFIDENCE = 0.75


def get_effective_expense_policy(
    db: Session,
    org_id: str | None,
    grade: str = "DEFAULT",
) -> dict[str, Any]:
    """Return active org+grade travel/conveyance policy, falling back to DEFAULT grade then platform defaults."""
    norm_grade = (grade or "DEFAULT").strip().upper()
    policy: FieldExpensePolicyRecord | None = None
    if org_id:
        policy = (
            db.query(FieldExpensePolicyRecord)
            .filter(
                FieldExpensePolicyRecord.org_id == org_id,
                FieldExpensePolicyRecord.grade == norm_grade,
                FieldExpensePolicyRecord.is_active.is_(True),
            )
            .first()
        )
        if policy is None and norm_grade != "DEFAULT":
            policy = (
                db.query(FieldExpensePolicyRecord)
                .filter(
                    FieldExpensePolicyRecord.org_id == org_id,
                    FieldExpensePolicyRecord.grade == "DEFAULT",
                    FieldExpensePolicyRecord.is_active.is_(True),
                )
                .first()
            )
    if policy is None:
        return {
            "policy_id": None,
            "grade": norm_grade,
            "rates": dict(RATE_PER_KM),
            "daily_auto_approve_limit_inr": DAILY_AUTO_APPROVE_LIMIT,
            "max_daily_distance_km": 250.0,
            "da_caps": {"TIER_1": 800.0, "TIER_2": 600.0, "TIER_3": 450.0},
            "hotel_caps": {"TIER_1": 3500.0, "TIER_2": 2200.0, "TIER_3": 1500.0},
            "fuel_max_inr_per_km": 15.0,
            "require_ocr_above_inr": 200.0,
        }
    return {
        "policy_id": policy.id,
        "grade": policy.grade,
        "rates": {
            "TWO_WHEELER": float(policy.two_wheeler_rate_inr),
            "FOUR_WHEELER": float(policy.four_wheeler_rate_inr),
            "PUBLIC_TRANSIT": float(policy.public_transit_rate_inr),
        },
        "daily_auto_approve_limit_inr": float(policy.daily_auto_approve_limit_inr),
        "max_daily_distance_km": float(policy.max_daily_distance_km),
        "da_caps": {
            "TIER_1": float(policy.tier1_da_inr),
            "TIER_2": float(policy.tier2_da_inr),
            "TIER_3": float(policy.tier3_da_inr),
        },
        "hotel_caps": {
            "TIER_1": float(policy.tier1_hotel_cap_inr),
            "TIER_2": float(policy.tier2_hotel_cap_inr),
            "TIER_3": float(policy.tier3_hotel_cap_inr),
        },
        "fuel_max_inr_per_km": float(policy.fuel_max_inr_per_km),
        "require_ocr_above_inr": float(policy.require_ocr_above_inr),
    }


def _try_osrm_road_snap_km(points: list[GpsBreadcrumb]) -> float | None:
    """Optional road-network distance via configured OSRM server (never called unless OSRM_BASE_URL is set)."""
    osrm_base = (os.environ.get("OSRM_BASE_URL") or "").strip().rstrip("/")
    if not osrm_base or len(points) < 2:
        return None
    # Downsample to <= 50 waypoints for URL safety
    step = max(1, len(points) // 50)
    sampled = points[::step]
    if sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    coords = ";".join(f"{p.longitude:.6f},{p.latitude:.6f}" for p in sampled)
    url = f"{osrm_base}/route/v1/driving/{coords}?overview=false"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AskforWrite-FieldGuard/2.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        routes = data.get("routes") or []
        if routes and routes[0].get("distance") is not None:
            return round(float(routes[0]["distance"]) / 1000.0, 2)
    except Exception as exc:
        logger.debug("OSRM road-snap skipped (%s); falling back to Haversine curvature estimate.", exc)
    return None


def calculate_fraud_proof_distance(
    breadcrumbs: list[GpsBreadcrumb],
    *,
    use_road_snap: bool = False,
) -> dict[str, Any]:
    """Filters stationary drift, detects anomalies, and computes legitimate road distance."""
    if len(breadcrumbs) < 2:
        return {
            "raw_gps_distance_km": 0.0,
            "verified_road_distance_km": 0.0,
            "jitter_filtered_km": 0.0,
            "distance_method": "HAVERSINE_CURVATURE_ESTIMATE",
            "discrepancy_flags": ["INSUFFICIENT_BREADCRUMBS"],
        }

    sorted_points = sorted(breadcrumbs, key=lambda b: b.timestamp)
    raw_dist_m = 0.0
    filtered_dist_m = 0.0
    discrepancy_flags: list[str] = []
    legitimate_points: list[GpsBreadcrumb] = [sorted_points[0]]

    for i in range(1, len(sorted_points)):
        p1 = sorted_points[i - 1]
        p2 = sorted_points[i]

        leg_m = calculate_haversine_distance(p1.latitude, p1.longitude, p2.latitude, p2.longitude)
        raw_dist_m += leg_m

        t1 = p1.timestamp.replace(tzinfo=UTC) if p1.timestamp.tzinfo is None else p1.timestamp.astimezone(UTC)
        t2 = p2.timestamp.replace(tzinfo=UTC) if p2.timestamp.tzinfo is None else p2.timestamp.astimezone(UTC)
        elapsed_sec = max((t2 - t1).total_seconds(), 1.0)
        leg_speed_kmh = (leg_m / 1000.0) / (elapsed_sec / 3600.0)

        if leg_m < STATIONARY_JITTER_METERS and elapsed_sec > 10.0:
            continue

        if leg_speed_kmh > MAX_ALLOWABLE_SPEED_KMH:
            discrepancy_flags.append(f"VELOCITY_ANOMALY: {leg_speed_kmh:.1f} km/h on leg {i}")
            continue

        filtered_dist_m += leg_m
        legitimate_points.append(p2)

    raw_km = round(raw_dist_m / 1000.0, 2)
    filtered_km = round(filtered_dist_m / 1000.0, 2)
    jitter_km = round(max(raw_km - filtered_km, 0.0), 2)

    distance_method = "HAVERSINE_CURVATURE_ESTIMATE"
    verified_road_km = round(filtered_km * ROAD_CURVATURE_FACTOR, 2)
    if use_road_snap and filtered_km > 0.0:
        snapped = _try_osrm_road_snap_km(legitimate_points)
        if snapped is not None and snapped >= 0.0:
            verified_road_km = snapped
            distance_method = "OSRM_ROAD_SNAPPED"

    return {
        "raw_gps_distance_km": raw_km,
        "verified_road_distance_km": verified_road_km,
        "jitter_filtered_km": jitter_km,
        "distance_method": distance_method,
        "discrepancy_flags": list(set(discrepancy_flags)),
    }


def _check_duplicate_receipt(
    db: Session,
    *,
    org_id: str | None,
    receipt_hash: str,
    perceptual_hash: str | None,
    merchant_name: str | None,
    invoice_number: str | None,
    amount: float,
    batch_hashes: set[str],
    batch_phashes: list[str],
) -> list[str]:
    """Detect exact hash duplicates, visually similar re-photographed bills (pHash), and invoice collisions."""
    flags: list[str] = []

    if receipt_hash in batch_hashes:
        flags.append("DUPLICATE_RECEIPT_EXACT_HASH: duplicate receipt submitted within same claim")
    else:
        q = db.query(ExpenseReceiptRecord).filter(ExpenseReceiptRecord.receipt_hash == receipt_hash)
        if org_id is not None:
            q = q.filter(ExpenseReceiptRecord.org_id == org_id)
        existing_exact = q.first()
        if existing_exact is not None:
            flags.append(
                f"DUPLICATE_RECEIPT_EXACT_HASH: already claimed on claim {existing_exact.claim_id[:8]}"
            )

    if perceptual_hash:
        for prev_phash in batch_phashes:
            if hamming_distance_hex(perceptual_hash, prev_phash) <= PHASH_DUPLICATE_MAX_HAMMING:
                flags.append("DUPLICATE_RECEIPT_SUSPECTED: visually identical receipt inside same claim")
                break
        else:
            pq = db.query(ExpenseReceiptRecord).filter(ExpenseReceiptRecord.perceptual_hash.is_not(None))
            if org_id is not None:
                pq = pq.filter(ExpenseReceiptRecord.org_id == org_id)
            for prev in pq.order_by(ExpenseReceiptRecord.created_at.desc()).limit(500).all():
                dist = hamming_distance_hex(perceptual_hash, prev.perceptual_hash)
                if dist <= PHASH_DUPLICATE_MAX_HAMMING:
                    flags.append(
                        f"DUPLICATE_RECEIPT_SUSPECTED: visual pHash match (hamming={dist}) with claim {prev.claim_id[:8]}"
                    )
                    break

    if invoice_number and invoice_number.strip():
        norm_inv = invoice_number.strip().upper()
        iq = db.query(ExpenseReceiptRecord).filter(ExpenseReceiptRecord.invoice_number == norm_inv)
        if org_id is not None:
            iq = iq.filter(ExpenseReceiptRecord.org_id == org_id)
        for prev in iq.limit(20).all():
            same_amt = abs(float(prev.amount) - float(amount)) <= 1.0
            same_merch = (
                not merchant_name
                or not prev.merchant_name
                or prev.merchant_name.strip().lower() == merchant_name.strip().lower()
            )
            if same_amt and same_merch:
                flags.append(
                    f"DUPLICATE_RECEIPT_INVOICE_MATCH: invoice {norm_inv} already claimed on claim {prev.claim_id[:8]}"
                )
                break

    return flags


def _run_receipt_vision_ocr(
    db: Session,
    *,
    org_id: str | None,
    image_bytes: bytes,
    mime_type: str,
    category: str,
) -> tuple[dict[str, Any] | None, str]:
    """Run real Gemini Vision structured OCR on a receipt image (metered at 1 AI Credit when org-backed)."""
    from app.agents.llm_client import generate_multimodal_json, set_request_llm_context
    from app.services.billing_ledger import (
        DailySpendCapExceededError,
        InsufficientAICreditsError,
        commit_ai_credit_reservation,
        refund_ai_credit_reservation,
        reserve_ai_credits,
    )

    reservation_id: str | None = None
    if org_id:
        try:
            res = reserve_ai_credits(
                db=db,
                org_id=org_id,
                action_key="field_receipt_ocr",
                idempotency_key=f"field-ocr-{uuid.uuid4().hex}",
                created_by="fieldguard_ocr",
            )
            reservation_id = res.get("reservation_id")
            set_request_llm_context(gemini_key=None, is_owner=False, managed_ai_authorized=True)
        except (InsufficientAICreditsError, DailySpendCapExceededError):
            return None, "AI_CREDITS_INSUFFICIENT_MANUAL_REVIEW"
        except Exception as exc:
            logger.debug("AI credit reservation skipped for OCR (%s)", exc)

    prompt = (
        f"Extract structured fields from this Indian business expense receipt (category: {category}). "
        "Return strict JSON with keys: "
        '{"merchant_name": string|null, "gstin": string|null, "invoice_no": string|null, '
        '"bill_date": "YYYY-MM-DD"|null, "total_amount": number|null, '
        '"fuel_liters": number|null, "ocr_confidence": number between 0 and 1}. '
        "Never guess or invent unreadable values; use null and lower ocr_confidence if blurry or unreadable."
    )
    extracted = generate_multimodal_json(
        prompt,
        image_bytes=image_bytes,
        mime_type=mime_type,
        system_instruction="You are a forensic accounting OCR extractor. Output strict JSON only.",
    )
    if extracted is None:
        if org_id and reservation_id:
            try:
                refund_ai_credit_reservation(db, org_id=org_id, reservation_id=reservation_id, reason="ocr_unavailable")
            except Exception:
                pass
        return None, "UNVERIFIED_MANUAL_REVIEW_REQUIRED"

    if org_id and reservation_id:
        try:
            commit_ai_credit_reservation(db, reservation_id=reservation_id)
        except Exception:
            pass
    return extracted, str(extracted.get("_provider_model") or "gemini_vision")


def _evaluate_receipt(
    db: Session,
    *,
    org_id: str | None,
    claim_id: str,
    claim_date: str,
    verified_road_km: float,
    policy: dict[str, Any],
    item: Any,
    batch_hashes: set[str],
    batch_phashes: list[str],
) -> tuple[ExpenseReceiptRecord, list[str]]:
    """Verify a single receipt with real Pillow inspection, Vision OCR, policy caps, and duplicate checks."""
    flags: list[str] = []
    raw_ref = item.receipt_base64_or_hash
    image_bytes, mime_type = decode_base64_image(raw_ref)

    perceptual_hash: str | None = None
    storage_uri: str | None = None
    ocr_extracted: dict[str, Any] = {}
    ocr_confidence: float | None = None
    ocr_provider = "UNVERIFIED_OPAQUE_REFERENCE"
    is_verified = False
    extracted_merchant = item.merchant_name
    extracted_invoice = item.invoice_number.strip().upper() if item.invoice_number else None
    extracted_gstin = item.gstin.strip().upper() if item.gstin else None

    if image_bytes is not None and mime_type is not None:
        receipt_hash = hashlib.sha256(image_bytes).hexdigest()
        img_check = inspect_image_integrity(image_bytes)
        perceptual_hash = img_check.get("perceptual_hash")
        ocr_extracted["image_integrity"] = {
            "valid_image": img_check["valid_image"],
            "width": img_check["width"],
            "height": img_check["height"],
            "format": img_check["format"],
            "laplacian_variance": img_check["laplacian_variance"],
            "flags": img_check["flags"],
        }
        if not img_check["valid_image"]:
            flags.append(f"LOW_IMAGE_QUALITY: invalid or corrupt receipt image ({item.category})")
        else:
            # Persist durably
            stored = persist_evidence_bytes(
                org_id=org_id,
                category=f"receipts_{item.category.lower()}",
                image_bytes=image_bytes,
                mime_type=mime_type,
            )
            storage_uri = stored["storage_uri"]

            if any(f.startswith(("BLANK_OR_SOLID", "LOW_IMAGE_QUALITY_BLURRY", "LOW_RESOLUTION")) for f in img_check["flags"]):
                flags.append(f"LOW_IMAGE_QUALITY: receipt image too blurry or low resolution ({item.category})")

            # Run real Gemini Vision OCR
            vision_json, provider_name = _run_receipt_vision_ocr(
                db,
                org_id=org_id,
                image_bytes=image_bytes,
                mime_type=mime_type,
                category=item.category,
            )
            ocr_provider = provider_name
            if vision_json is not None:
                ocr_extracted["vision_ocr"] = vision_json
                conf = float(vision_json.get("ocr_confidence") or 0.0)
                ocr_confidence = round(conf, 3)
                if vision_json.get("merchant_name"):
                    extracted_merchant = str(vision_json["merchant_name"])[:200]
                if vision_json.get("invoice_no"):
                    extracted_invoice = str(vision_json["invoice_no"]).strip().upper()[:100]
                if vision_json.get("gstin"):
                    extracted_gstin = str(vision_json["gstin"]).strip().upper()[:32]

                if conf < OCR_MIN_CONFIDENCE:
                    flags.append(f"LOW_IMAGE_QUALITY: OCR confidence {conf:.2f} below {OCR_MIN_CONFIDENCE:.2f}")

                ocr_amount = vision_json.get("total_amount")
                if ocr_amount is not None:
                    delta = abs(float(ocr_amount) - float(item.amount))
                    if delta > OCR_AMOUNT_TOLERANCE_INR:
                        flags.append(
                            f"OCR_AMOUNT_MISMATCH: claimed ₹{item.amount:.2f} vs OCR ₹{float(ocr_amount):.2f} (delta ₹{delta:.2f})"
                        )

                ocr_date = vision_json.get("bill_date")
                if ocr_date and str(ocr_date).strip() != claim_date:
                    flags.append(f"OCR_DATE_MISMATCH: OCR bill date {ocr_date} vs claim date {claim_date}")

                if conf >= OCR_MIN_CONFIDENCE and not any(f.startswith(("OCR_", "LOW_IMAGE_QUALITY")) for f in flags):
                    is_verified = True
            else:
                ocr_extracted["vision_ocr_status"] = provider_name
                flags.append(f"OCR_MANUAL_REVIEW_REQUIRED: live vision OCR not completed ({provider_name})")
    else:
        receipt_hash = hashlib.sha256(raw_ref.encode("utf-8")).hexdigest()
        ocr_threshold = float(policy.get("require_ocr_above_inr", 200.0))
        if float(item.amount) > ocr_threshold:
            ocr_provider = "MISSING_RECEIPT_IMAGE_ABOVE_THRESHOLD"
            ocr_extracted = {
                "merchant_claimed": item.merchant_name,
                "ocr_status": "UNVERIFIED_IMAGE_REQUIRED",
                "threshold_inr": ocr_threshold,
            }
            flags.append(
                f"OCR_IMAGE_REQUIRED: ₹{item.amount:.2f} exceeds ₹{ocr_threshold:.0f} petty-cash threshold without receipt photo"
            )
        else:
            ocr_provider = "BELOW_THRESHOLD_PETTY_CASH_EXEMPT"
            ocr_extracted = {
                "merchant_claimed": item.merchant_name,
                "ocr_status": "BELOW_THRESHOLD_EXEMPT",
                "threshold_inr": ocr_threshold,
            }
            is_verified = False  # Honest: exempt from mandatory OCR, not Vision-verified

    # Cross-claim duplicate checks
    dup_flags = _check_duplicate_receipt(
        db,
        org_id=org_id,
        receipt_hash=receipt_hash,
        perceptual_hash=perceptual_hash,
        merchant_name=extracted_merchant,
        invoice_number=extracted_invoice,
        amount=item.amount,
        batch_hashes=batch_hashes,
        batch_phashes=batch_phashes,
    )
    if dup_flags:
        is_verified = False
        flags.extend(dup_flags)

    batch_hashes.add(receipt_hash)
    if perceptual_hash:
        batch_phashes.append(perceptual_hash)

    # Declared date mismatch
    if item.receipt_date and item.receipt_date != claim_date:
        flags.append(f"RECEIPT_DATE_MISMATCH: {item.category} ({item.receipt_date} vs {claim_date})")

    # Category policy caps (Fuel, Hotel lodging, Daily Allowance)
    if item.category == "FUEL":
        fuel_max = float(policy.get("fuel_max_inr_per_km", 15.0))
        if item.amount > (verified_road_km * fuel_max):
            flags.append(f"EXCESSIVE_FUEL_CLAIM: ₹{item.amount} for {verified_road_km}km")
    elif item.category == "HOTEL":
        tier = (item.city_tier or "TIER_2").upper()
        hotel_cap = float(policy.get("hotel_caps", {}).get(tier, 2200.0))
        if item.amount > hotel_cap:
            flags.append(f"HOTEL_CAP_EXCEEDED: ₹{item.amount:.2f} exceeds {tier} limit ₹{hotel_cap:.2f}")
    elif item.category == "DAILY_ALLOWANCE":
        tier = (item.city_tier or "TIER_2").upper()
        da_cap = float(policy.get("da_caps", {}).get(tier, 600.0))
        if item.amount > da_cap:
            flags.append(f"DA_CAP_EXCEEDED: ₹{item.amount:.2f} exceeds {tier} limit ₹{da_cap:.2f}")

    rec = ExpenseReceiptRecord(
        id=str(uuid.uuid4()),
        claim_id=claim_id,
        org_id=org_id,
        category=item.category,
        amount=item.amount,
        merchant_name=extracted_merchant,
        receipt_date=item.receipt_date,
        receipt_hash=receipt_hash,
        perceptual_hash=perceptual_hash,
        invoice_number=extracted_invoice,
        gstin=extracted_gstin,
        ocr_confidence=ocr_confidence,
        ocr_provider=ocr_provider,
        storage_uri=storage_uri,
        ocr_extracted_data=ocr_extracted,
        is_verified=is_verified,
    )
    return rec, flags


def submit_conveyance_and_expense_claim(
    db: Session,
    org_id: str | None,
    req: ConveyanceClaimSubmitRequest,
) -> ConveyanceClaimRecord:
    """Evaluates mileage against org policy, runs real Vision OCR + duplicate checks, and seals into ledger."""
    policy = get_effective_expense_policy(db, org_id, grade=getattr(req, "employee_grade", "DEFAULT"))

    # Optional Tour Plan linkage validation
    tour_plan_id = getattr(req, "tour_plan_id", None)
    if tour_plan_id:
        tour = db.get(FieldTourPlanRecord, tour_plan_id)
        if not tour:
            raise ValueError(f"Tour plan {tour_plan_id} not found")
        if org_id is not None and tour.org_id != org_id:
            raise PermissionError("Tour plan belongs to another organization")

    dist_info = calculate_fraud_proof_distance(
        req.gps_breadcrumbs,
        use_road_snap=bool(getattr(req, "use_road_snap", False)),
    )
    rate = float(policy["rates"].get(req.transport_mode, 4.50))
    conveyance_amt = round(dist_info["verified_road_distance_km"] * rate, 2)

    claim_id = str(uuid.uuid4())
    discrepancy_flags = list(dist_info["discrepancy_flags"])

    if dist_info["verified_road_distance_km"] > float(policy["max_daily_distance_km"]):
        discrepancy_flags.append(
            f"EXCESSIVE_DAILY_DISTANCE: {dist_info['verified_road_distance_km']}km > {policy['max_daily_distance_km']}km policy cap"
        )

    total_expenses = 0.0
    receipt_count = 0
    receipt_records: list[ExpenseReceiptRecord] = []
    batch_hashes: set[str] = set()
    batch_phashes: list[str] = []

    if req.receipts:
        for r in req.receipts:
            receipt_count += 1
            total_expenses += float(r.amount)
            rec, r_flags = _evaluate_receipt(
                db,
                org_id=org_id,
                claim_id=claim_id,
                claim_date=req.claim_date,
                verified_road_km=dist_info["verified_road_distance_km"],
                policy=policy,
                item=r,
                batch_hashes=batch_hashes,
                batch_phashes=batch_phashes,
            )
            discrepancy_flags.extend(r_flags)
            receipt_records.append(rec)

    grand_total = round(conveyance_amt + total_expenses, 2)
    auto_approve_limit = float(policy["daily_auto_approve_limit_inr"])
    if not discrepancy_flags and grand_total <= auto_approve_limit:
        claim_status = "AUTO_APPROVED"
    else:
        claim_status = "FLAGGED_FOR_REVIEW"

    trust_block_hash = None
    if claim_status == "AUTO_APPROVED":
        try:
            seal_payload = {
                "claim_id": claim_id,
                "user_id": req.user_id,
                "tour_plan_id": tour_plan_id,
                "claim_date": req.claim_date,
                "road_distance_km": dist_info["verified_road_distance_km"],
                "distance_method": dist_info["distance_method"],
                "conveyance_amount": conveyance_amt,
                "expenses_amount": round(total_expenses, 2),
                "grand_total": grand_total,
                "status": claim_status,
            }
            sealed_block = seal_task_to_block(
                db=db,
                task_id=claim_id,
                capability_name="conveyance_settlement",
                action="expense_claim_auto_settled",
                payload=seal_payload,
                sealed_by="AFW-EXPENSE-SETTLEMENT-ENGINE",
                commit=False,
            )
            trust_block_hash = sealed_block.block_hash
        except Exception:
            pass

    claim = ConveyanceClaimRecord(
        id=claim_id,
        org_id=org_id,
        user_id=req.user_id,
        claim_date=req.claim_date,
        transport_mode=req.transport_mode,
        raw_gps_distance_km=dist_info["raw_gps_distance_km"],
        verified_road_distance_km=dist_info["verified_road_distance_km"],
        jitter_filtered_km=dist_info["jitter_filtered_km"],
        rate_per_km=rate,
        total_conveyance_amount=conveyance_amt,
        total_expenses_amount=round(total_expenses, 2),
        grand_total_amount=grand_total,
        receipt_count=receipt_count,
        status=claim_status,
        discrepancy_flags=discrepancy_flags,
        trust_block_hash=trust_block_hash,
        tour_plan_id=tour_plan_id,
        distance_method=dist_info["distance_method"],
        metadata_json={"notes": req.notes, "policy_grade": policy["grade"]} if req.notes else {"policy_grade": policy["grade"]},
    )

    db.add(claim)
    if receipt_records:
        db.add_all(receipt_records)
    db.commit()
    db.refresh(claim)
    return claim


def submit_conveyance_claim(
    db: Session,
    req: Any,
    org_id: str | None = None,
) -> ConveyanceClaimRecord:
    """Submits a direct mobile conveyance claim with org-configurable policy and odometer checks."""
    policy = get_effective_expense_policy(db, org_id, grade=getattr(req, "employee_grade", "DEFAULT"))

    vtype_raw = getattr(req, "vehicle_type", "bike").strip().lower()
    if vtype_raw in ("car", "four_wheeler", "4w"):
        transport_mode = "FOUR_WHEELER"
    elif vtype_raw in ("public_transit", "bus", "metro", "train"):
        transport_mode = "PUBLIC_TRANSIT"
    else:
        transport_mode = "TWO_WHEELER"

    rate = float(policy["rates"].get(transport_mode, 4.50))
    raw_km = round(float(req.distance_km), 2)
    discrepancy_flags: list[str] = []

    start_odo = getattr(req, "start_odometer_reading", None)
    end_odo = getattr(req, "end_odometer_reading", None)
    if start_odo is not None and end_odo is not None:
        odo_diff = round(float(end_odo) - float(start_odo), 2)
        if odo_diff < 0 or abs(odo_diff - raw_km) > max(5.0, raw_km * 0.25):
            discrepancy_flags.append(f"ODOMETER_MISMATCH: claimed {raw_km}km vs odometer {odo_diff}km")

    max_dist = float(policy["max_daily_distance_km"])
    if raw_km > max_dist:
        discrepancy_flags.append(f"EXCESSIVE_DAILY_DISTANCE: {raw_km}km > {max_dist}km")

    conveyance_amt = round(raw_km * rate, 2)
    claim_id = str(uuid.uuid4())
    auto_limit = float(policy["daily_auto_approve_limit_inr"])
    claim_status = "AUTO_APPROVED" if (not discrepancy_flags and conveyance_amt <= auto_limit) else "FLAGGED_FOR_REVIEW"

    trust_block_hash = None
    if claim_status == "AUTO_APPROVED":
        try:
            sealed_block = seal_task_to_block(
                db=db,
                task_id=claim_id,
                capability_name="conveyance_settlement",
                action="mobile_conveyance_claim_settled",
                payload={
                    "claim_id": claim_id,
                    "user_id": req.user_id,
                    "claim_date": req.date,
                    "road_distance_km": raw_km,
                    "grand_total": conveyance_amt,
                    "status": claim_status,
                },
                sealed_by="AFW-EXPENSE-SETTLEMENT-ENGINE",
                commit=False,
            )
            trust_block_hash = sealed_block.block_hash
        except Exception:
            pass

    claim = ConveyanceClaimRecord(
        id=claim_id,
        org_id=org_id,
        user_id=req.user_id,
        claim_date=req.date,
        transport_mode=transport_mode,
        raw_gps_distance_km=raw_km,
        verified_road_distance_km=raw_km,
        jitter_filtered_km=0.0,
        rate_per_km=rate,
        total_conveyance_amount=conveyance_amt,
        total_expenses_amount=0.0,
        grand_total_amount=conveyance_amt,
        receipt_count=1 if getattr(req, "receipt_photo_url", None) else 0,
        status=claim_status,
        discrepancy_flags=discrepancy_flags,
        trust_block_hash=trust_block_hash,
        tour_plan_id=getattr(req, "tour_plan_id", None),
        distance_method="MOBILE_ODOMETER_REPORTED",
        metadata_json={"purpose": getattr(req, "purpose", ""), "policy_grade": policy["grade"]},
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


def enrich_claim_with_review(
    db: Session,
    claim: ConveyanceClaimRecord,
) -> dict[str, Any]:
    """Build API payload resolving latest append-only manager adjudication without mutating claim rows."""
    latest_review = (
        db.query(ConveyanceClaimReviewRecord)
        .filter(ConveyanceClaimReviewRecord.claim_id == claim.id)
        .order_by(ConveyanceClaimReviewRecord.reviewed_at.desc())
        .first()
    )
    if latest_review is not None:
        if latest_review.decision == "APPROVE":
            eff_status = "MANUALLY_APPROVED"
            eff_payout = float(latest_review.approved_amount_inr)
        elif latest_review.decision == "PARTIAL_APPROVE":
            eff_status = "PARTIALLY_APPROVED"
            eff_payout = float(latest_review.approved_amount_inr)
        else:
            eff_status = "REJECTED"
            eff_payout = 0.0
        review_dict: dict[str, Any] | None = {
            "id": latest_review.id,
            "decision": latest_review.decision,
            "approved_amount_inr": latest_review.approved_amount_inr,
            "reviewer_email": latest_review.reviewer_email,
            "reason": latest_review.reason,
            "trust_block_hash": latest_review.trust_block_hash,
            "reviewed_at": latest_review.reviewed_at.isoformat() if latest_review.reviewed_at else None,
        }
    else:
        eff_status = claim.status
        eff_payout = float(claim.grand_total_amount) if claim.status == "AUTO_APPROVED" else 0.0
        review_dict = None

    return {
        "id": claim.id,
        "org_id": claim.org_id,
        "user_id": claim.user_id,
        "claim_date": claim.claim_date,
        "transport_mode": claim.transport_mode,
        "raw_gps_distance_km": claim.raw_gps_distance_km,
        "verified_road_distance_km": claim.verified_road_distance_km,
        "jitter_filtered_km": claim.jitter_filtered_km,
        "rate_per_km": claim.rate_per_km,
        "total_conveyance_amount": claim.total_conveyance_amount,
        "total_expenses_amount": claim.total_expenses_amount,
        "grand_total_amount": claim.grand_total_amount,
        "receipt_count": claim.receipt_count,
        "status": claim.status,
        "discrepancy_flags": list(claim.discrepancy_flags or []),
        "trust_block_hash": claim.trust_block_hash,
        "tour_plan_id": claim.tour_plan_id,
        "distance_method": claim.distance_method or "HAVERSINE_CURVATURE_ESTIMATE",
        "effective_status": eff_status,
        "effective_payout_amount": round(eff_payout, 2),
        "latest_review": review_dict,
        "created_at": claim.created_at,
    }


def list_conveyance_claims(
    db: Session,
    org_id: str | None,
    user_id: str | None = None,
    tour_plan_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Lists conveyance claims enriched with effective manager adjudication state."""
    query = db.query(ConveyanceClaimRecord)
    if org_id:
        query = query.filter(ConveyanceClaimRecord.org_id == org_id)
    if user_id:
        query = query.filter(ConveyanceClaimRecord.user_id == user_id)
    if tour_plan_id:
        query = query.filter(ConveyanceClaimRecord.tour_plan_id == tour_plan_id)

    claims = query.order_by(ConveyanceClaimRecord.created_at.desc()).limit(limit).all()
    return [enrich_claim_with_review(db, c) for c in claims]
