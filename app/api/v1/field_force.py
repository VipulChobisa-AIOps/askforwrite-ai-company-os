"""AskforWrite Autonomous Field Force Engine API router.

Enforces paid entitlement (`delivery_field_force`), tenant scope (`org_id`),
and canonical `principal.user_id` member ownership on EVERY endpoint (Issue #14).

Endpoints for:
- Geofence management (create hubs/client sites, list)
- Zero-Trust attendance check-in & check-out (anti-spoofing, velocity checks, cryptographic sealing)
- Tamper-evident attendance history & muster
- Field tasks, autonomous dispatch, dynamic route optimization
- Client visit verification, voice debrief, visit history
- Fraud-proof conveyance calculation, claim submission, and claim listing
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import UserRecord
from app.schemas.field_force import (
    AttendanceCheckInRequest,
    AttendanceCheckOutRequest,
    AttendanceRecordResponse,
    ClientVisitResponse,
    ClientVisitVerifyRequest,
    ConveyanceCalculateRequest,
    ConveyanceClaimResponse,
    ConveyanceClaimSubmitRequest,
    FieldTaskCreate,
    FieldTaskResponse,
    GeofenceCreate,
    GeofenceResponse,
    RouteOptimizationRequest,
    RouteOptimizationResponse,
    VoiceDebriefRequest,
)
from app.security.auth import (
    APIPrincipal,
    check_tenant_entitlement,
    require_tenant_manager,
    require_tenant_member,
)
from app.services.field_conveyance import (
    calculate_fraud_proof_distance,
    list_conveyance_claims,
    submit_conveyance_and_expense_claim,
)
from app.services.field_dispatch import (
    auto_dispatch_task,
    create_field_task,
    list_field_tasks,
    optimize_route_sequence,
)
from app.services.field_presence import (
    create_geofence,
    get_attendance_history,
    list_geofences,
    record_attendance_checkin,
    record_attendance_checkout,
)
from app.services.field_verification import (
    list_client_visits,
    process_voice_debrief,
    verify_client_visit,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/field-force", tags=["field-force"])


def require_field_member(
    principal: APIPrincipal = Depends(require_tenant_member),
) -> APIPrincipal:
    """Reject customer-only accounts from internal field-force operational routes."""
    if not principal.is_platform_operator and principal.role == "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Field staff or manager role required for field-force operations",
        )
    return principal


def _require_canonical_member_user_id(principal: APIPrincipal) -> str:
    """Return canonical principal.user_id for member ownership/filtering (never fall back to email-like subject)."""
    if not principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Canonical user_id claim is required for member field-force operations",
        )
    return principal.user_id


def _enforce_member_self_ownership(
    principal: APIPrincipal,
    candidate_user_id: str | None,
    *,
    action_description: str,
) -> str | None:
    """Enforce that non-manager members only act on or query their own canonical principal.user_id."""
    if principal.role != "member" or principal.is_platform_operator:
        return candidate_user_id
    canonical_uid = _require_canonical_member_user_id(principal)
    if candidate_user_id is not None and candidate_user_id != canonical_uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Members may only {action_description} for their own user_id",
        )
    return canonical_uid


def _ensure_target_user_in_org(db: Session, principal: APIPrincipal, candidate_user_id: str | None) -> None:
    """Block tenant principals from referencing a user account belonging to a different organization."""
    if not candidate_user_id or not principal.org_id:
        return
    target_user = db.get(UserRecord, candidate_user_id)
    if target_user is not None and target_user.org_id != principal.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: target user belongs to another organization",
        )


def _authorize_field_read(
    db: Session,
    principal: APIPrincipal,
    requested_user_id: str | None,
    *,
    action_description: str,
) -> str | None:
    """Shared guard for all Field Force read/list routes: entitlement + tenant scope + canonical member ownership."""
    check_tenant_entitlement(principal, "delivery_field_force", db)
    _ensure_target_user_in_org(db, principal, requested_user_id)
    return _enforce_member_self_ownership(
        principal,
        requested_user_id,
        action_description=action_description,
    )


# ── Geofence Management ────────────────────────────────────────────────


@router.post("/geofences", response_model=GeofenceResponse, status_code=status.HTTP_201_CREATED)
def create_geofence_endpoint(
    payload: GeofenceCreate,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
):
    """Creates a new verified geofence boundary for a client site or branch office."""
    check_tenant_entitlement(principal, "delivery_field_force", db)
    geofence = create_geofence(
        db=db,
        org_id=principal.org_id,
        data=payload,
    )
    return geofence


@router.get("/geofences", response_model=list[GeofenceResponse])
def list_geofences_endpoint(
    principal: APIPrincipal = Depends(require_field_member),
    db: Session = Depends(get_db),
):
    """Lists active geofences configured for the tenant."""
    check_tenant_entitlement(principal, "delivery_field_force", db)
    return list_geofences(db=db, org_id=principal.org_id)


# ── Zero-Trust Presence & Attendance ───────────────────────────────────


@router.post(
    "/attendance/check-in",
    response_model=AttendanceRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
def checkin_endpoint(
    payload: AttendanceCheckInRequest,
    principal: APIPrincipal = Depends(require_field_member),
    db: Session = Depends(get_db),
):
    """Performs zero-trust presence verification and cryptographically seals check-in."""
    check_tenant_entitlement(principal, "delivery_field_force", db)
    _ensure_target_user_in_org(db, principal, payload.user_id)
    if principal.role == "member" and not principal.is_platform_operator:
        payload.user_id = _enforce_member_self_ownership(
            principal,
            payload.user_id,
            action_description="record attendance check-in",
        ) or _require_canonical_member_user_id(principal)
    elif principal.user_id:
        payload.user_id = principal.user_id

    try:
        record = record_attendance_checkin(
            db=db,
            org_id=principal.org_id,
            req=payload,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if record.status == "SPOOF_REJECTED":
        logger.warning(
            "Spoofing attempt detected for user %s: %s",
            payload.user_id,
            record.verification_notes,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "SPOOFING_DETECTED",
                "message": record.verification_notes,
                "attendance_id": record.id,
            },
        )
    elif record.status == "OUT_OF_BOUNDS":
        logger.warning(
            "Out of bounds check-in for user %s: %s",
            payload.user_id,
            record.verification_notes,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "OUT_OF_BOUNDS",
                "message": record.verification_notes,
                "attendance_id": record.id,
            },
        )

    return record


@router.post(
    "/attendance/check-out",
    response_model=AttendanceRecordResponse,
    status_code=status.HTTP_200_OK,
)
def checkout_endpoint(
    payload: AttendanceCheckOutRequest,
    principal: APIPrincipal = Depends(require_field_member),
    db: Session = Depends(get_db),
):
    """Performs end-of-shift check-out and cryptographic sealing."""
    check_tenant_entitlement(principal, "delivery_field_force", db)
    _ensure_target_user_in_org(db, principal, payload.user_id)
    if principal.role == "member" and not principal.is_platform_operator:
        payload.user_id = _enforce_member_self_ownership(
            principal,
            payload.user_id,
            action_description="record attendance check-out",
        ) or _require_canonical_member_user_id(principal)
    elif principal.user_id:
        payload.user_id = principal.user_id

    try:
        record = record_attendance_checkout(
            db=db,
            org_id=principal.org_id,
            req=payload,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return record


@router.get("/attendance/history", response_model=list[AttendanceRecordResponse])
def attendance_history_endpoint(
    user_id: str | None = Query(None, description="Optional user filter"),
    limit: int = Query(50, ge=1, le=200),
    principal: APIPrincipal = Depends(require_field_member),
    db: Session = Depends(get_db),
):
    """Returns append-only attendance records sealed in the ledger."""
    target_user_id = _authorize_field_read(
        db,
        principal,
        user_id,
        action_description="view attendance history",
    )
    return get_attendance_history(
        db=db,
        org_id=principal.org_id,
        user_id=target_user_id,
        limit=limit,
    )


# ── Field Task & Autonomous Dispatch ──────────────────────────────────


@router.post("/tasks", response_model=FieldTaskResponse, status_code=status.HTTP_201_CREATED)
def create_task_endpoint(
    payload: FieldTaskCreate,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
):
    """Creates a new field service, client visit, or delivery task."""
    check_tenant_entitlement(principal, "delivery_field_force", db)
    _ensure_target_user_in_org(db, principal, payload.assigned_to_user_id)
    return create_field_task(
        db=db,
        org_id=principal.org_id,
        data=payload,
    )


@router.get("/tasks", response_model=list[FieldTaskResponse])
def list_tasks_endpoint(
    user_id: str | None = Query(None, description="Filter by assigned user"),
    task_status: str | None = Query(None, alias="status", description="Filter by task status"),
    limit: int = Query(50, ge=1, le=200),
    principal: APIPrincipal = Depends(require_field_member),
    db: Session = Depends(get_db),
):
    """Lists field tasks. Members only see their own assigned tasks by canonical user_id."""
    target_user_id = _authorize_field_read(
        db,
        principal,
        user_id,
        action_description="list field tasks",
    )
    return list_field_tasks(
        db=db,
        org_id=principal.org_id,
        user_id=target_user_id,
        status=task_status,
        limit=limit,
    )


@router.post("/tasks/{task_id}/auto-dispatch")
def auto_dispatch_endpoint(
    task_id: str,
    principal: APIPrincipal = Depends(require_tenant_manager),
    db: Session = Depends(get_db),
):
    """Autonomously matches the optimal field executive based on real-time GPS proximity and workload."""
    check_tenant_entitlement(principal, "delivery_field_force", db)
    try:
        task, telemetry = auto_dispatch_task(
            db=db,
            org_id=principal.org_id,
            task_id=task_id,
        )
        return {
            "status": "DISPATCHED",
            "task_id": task.id,
            "assigned_to": task.assigned_to_user_id,
            "telemetry": telemetry,
        }
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ── Dynamic Route Optimizer ───────────────────────────────────────────


@router.post("/routes/optimize", response_model=RouteOptimizationResponse)
def optimize_route_endpoint(
    payload: RouteOptimizationRequest,
    principal: APIPrincipal = Depends(require_field_member),
    db: Session = Depends(get_db),
):
    """Sequences an executive's daily client visits using TSP Nearest-Neighbor with priority weighting."""
    check_tenant_entitlement(principal, "delivery_field_force", db)
    _ensure_target_user_in_org(db, principal, payload.user_id)
    _enforce_member_self_ownership(
        principal,
        payload.user_id,
        action_description="optimize routes",
    )
    return optimize_route_sequence(
        db=db,
        org_id=principal.org_id,
        req=payload,
    )


# ── Multimodal Proof-of-Execution & Visit Debrief ──────────────────────


@router.post(
    "/visits/verify",
    response_model=ClientVisitResponse,
    status_code=status.HTTP_201_CREATED,
)
def verify_visit_endpoint(
    payload: ClientVisitVerifyRequest,
    principal: APIPrincipal = Depends(require_field_member),
    db: Session = Depends(get_db),
):
    """Verifies a physical client visit using geo-proximity, client Geo-OTP, and AI Vision inspection."""
    check_tenant_entitlement(principal, "delivery_field_force", db)
    _ensure_target_user_in_org(db, principal, payload.user_id)
    _enforce_member_self_ownership(
        principal,
        payload.user_id,
        action_description="verify client visits",
    )
    try:
        record = verify_client_visit(
            db=db,
            org_id=principal.org_id,
            req=payload,
        )
        return record
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))


@router.post("/visits/debrief")
def voice_debrief_endpoint(
    payload: VoiceDebriefRequest,
    principal: APIPrincipal = Depends(require_field_member),
    db: Session = Depends(get_db),
):
    """Processes a spoken voice debrief and extracts structured CRM meeting fields."""
    check_tenant_entitlement(principal, "delivery_field_force", db)
    _ensure_target_user_in_org(db, principal, payload.user_id)
    _enforce_member_self_ownership(
        principal,
        payload.user_id,
        action_description="submit voice debriefs",
    )
    try:
        visit, result = process_voice_debrief(
            db=db,
            org_id=principal.org_id,
            req=payload,
        )
        return {
            "status": "DEBRIEF_SYNTHESIZED",
            "visit_id": visit.id,
            "task_id": payload.task_id,
            "structured_crm_data": result["crm_debrief"],
        }
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/visits", response_model=list[ClientVisitResponse])
def list_visits_endpoint(
    user_id: str | None = Query(None, description="Filter by user"),
    limit: int = Query(50, ge=1, le=200),
    principal: APIPrincipal = Depends(require_field_member),
    db: Session = Depends(get_db),
):
    """Lists completed client visits and their cryptographic proofs."""
    target_user_id = _authorize_field_read(
        db,
        principal,
        user_id,
        action_description="list client visits",
    )
    return list_client_visits(
        db=db,
        org_id=principal.org_id,
        user_id=target_user_id,
        limit=limit,
    )


# ── Fraud-Proof Conveyance & Expense Auto-Settlement ───────────────────


@router.post("/conveyance/calculate")
def calculate_conveyance_endpoint(
    payload: ConveyanceCalculateRequest,
    principal: APIPrincipal = Depends(require_field_member),
    db: Session = Depends(get_db),
):
    """Calculates road-snapped travel distance and eliminates fake indoor stationary GPS jitter."""
    check_tenant_entitlement(principal, "delivery_field_force", db)
    _ensure_target_user_in_org(db, principal, payload.user_id)
    effective_user_id = _enforce_member_self_ownership(
        principal,
        payload.user_id,
        action_description="calculate conveyance distance",
    )
    result = calculate_fraud_proof_distance(payload.gps_breadcrumbs)
    return {
        "user_id": effective_user_id or payload.user_id,
        "claim_date": payload.claim_date,
        "transport_mode": payload.transport_mode,
        "distance_telemetry": result,
    }


@router.post(
    "/conveyance/submit",
    response_model=ConveyanceClaimResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_conveyance_endpoint(
    payload: ConveyanceClaimSubmitRequest,
    principal: APIPrincipal = Depends(require_field_member),
    db: Session = Depends(get_db),
):
    """Submits a conveyance and expense claim for automated policy verification and settlement."""
    check_tenant_entitlement(principal, "delivery_field_force", db)
    _ensure_target_user_in_org(db, principal, payload.user_id)
    _enforce_member_self_ownership(
        principal,
        payload.user_id,
        action_description="submit conveyance claims",
    )
    claim = submit_conveyance_and_expense_claim(
        db=db,
        org_id=principal.org_id,
        req=payload,
    )
    return claim


@router.get("/conveyance/claims", response_model=list[ConveyanceClaimResponse])
def list_conveyance_endpoint(
    user_id: str | None = Query(None, description="Filter by user"),
    limit: int = Query(50, ge=1, le=200),
    principal: APIPrincipal = Depends(require_field_member),
    db: Session = Depends(get_db),
):
    """Lists conveyance claims and audit records."""
    target_user_id = _authorize_field_read(
        db,
        principal,
        user_id,
        action_description="list conveyance claims",
    )
    return list_conveyance_claims(
        db=db,
        org_id=principal.org_id,
        user_id=target_user_id,
        limit=limit,
    )
