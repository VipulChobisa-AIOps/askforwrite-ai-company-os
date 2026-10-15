"""AskforWrite Autonomous Field Force Engine API router.

Endpoints for:
- Geofence management (create hubs/client sites, list)
- Zero-Trust attendance check-in (anti-spoofing, speed anomaly check, cryptographic sealing)
- Attendance check-out
- Tamper-evident attendance history & muster
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
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
    require_authenticated_user,
    require_manager,
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


# ── Geofence Management ────────────────────────────────────────────────


@router.post("/geofences", response_model=GeofenceResponse, status_code=status.HTTP_201_CREATED)
def create_geofence_endpoint(
    payload: GeofenceCreate,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Creates a new verified geofence boundary for a client site or branch office."""
    geofence = create_geofence(
        db=db,
        org_id=principal.org_id,
        data=payload,
    )
    return geofence


@router.get("/geofences", response_model=list[GeofenceResponse])
def list_geofences_endpoint(
    principal: APIPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """Lists active geofences configured for the tenant."""
    return list_geofences(db=db, org_id=principal.org_id)


# ── Zero-Trust Presence & Attendance ───────────────────────────────────


@router.post(
    "/attendance/check-in",
    response_model=AttendanceRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
def checkin_endpoint(
    payload: AttendanceCheckInRequest,
    principal: APIPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """Performs zero-trust presence verification and cryptographically seals check-in.

    Validates anti-mock GPS sensors, checks velocity teleportation anomalies,
    verifies geofence boundaries, and seals into the ECDSA P-256 trust chain.
    """
    record = record_attendance_checkin(
        db=db,
        org_id=principal.org_id,
        req=payload,
    )

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
    principal: APIPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """Performs end-of-shift check-out and cryptographic sealing."""
    record = record_attendance_checkout(
        db=db,
        org_id=principal.org_id,
        req=payload,
    )
    return record


@router.get("/attendance/history", response_model=list[AttendanceRecordResponse])
def attendance_history_endpoint(
    user_id: str | None = Query(None, description="Optional user filter"),
    limit: int = Query(50, ge=1, le=200),
    principal: APIPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """Returns append-only attendance records sealed in the ledger."""
    # Members can only view their own records; Managers can view all tenant records
    target_user_id = user_id
    if principal.role == "member":
        target_user_id = principal.subject

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
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Creates a new field service, client visit, or delivery task."""
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
    principal: APIPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """Lists field tasks. Members only see their own assigned tasks."""
    target_user_id = user_id
    if principal.role == "member":
        target_user_id = principal.subject

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
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Autonomously matches the optimal field executive based on real-time GPS proximity and workload."""
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
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ── Dynamic Route Optimizer ───────────────────────────────────────────


@router.post("/routes/optimize", response_model=RouteOptimizationResponse)
def optimize_route_endpoint(
    payload: RouteOptimizationRequest,
    principal: APIPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """Sequences an executive's daily client visits using TSP Nearest-Neighbor with priority weighting.

    Minimizes total travel distance, estimates transit times, and saves up to 30% fuel.
    """
    # Members can only optimize their own route; Managers can optimize any employee
    if principal.role == "member" and principal.subject != payload.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Members may only optimize their own assigned route",
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
    principal: APIPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """Verifies a physical client visit using geo-proximity, client Geo-OTP, and AI Vision inspection."""
    try:
        record = verify_client_visit(
            db=db,
            org_id=principal.org_id,
            req=payload,
        )
        return record
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))


@router.post("/visits/debrief")
def voice_debrief_endpoint(
    payload: VoiceDebriefRequest,
    principal: APIPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """Processes a spoken voice debrief and extracts structured CRM meeting fields."""
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
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/visits", response_model=list[ClientVisitResponse])
def list_visits_endpoint(
    user_id: str | None = Query(None, description="Filter by user"),
    limit: int = Query(50, ge=1, le=200),
    principal: APIPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """Lists completed client visits and their cryptographic proofs."""
    target_user_id = user_id
    if principal.role == "member":
        target_user_id = principal.subject

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
    principal: APIPrincipal = Depends(require_authenticated_user),
):
    """Calculates road-snapped travel distance and eliminates fake indoor stationary GPS jitter."""
    result = calculate_fraud_proof_distance(payload.gps_breadcrumbs)
    return {
        "user_id": payload.user_id,
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
    principal: APIPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """Submits a conveyance and expense claim for automated policy verification and settlement."""
    if principal.role == "member" and principal.subject != payload.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Members may only submit conveyance claims for themselves",
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
    principal: APIPrincipal = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """Lists conveyance claims and audit records."""
    target_user_id = user_id
    if principal.role == "member":
        target_user_id = principal.subject

    return list_conveyance_claims(
        db=db,
        org_id=principal.org_id,
        user_id=target_user_id,
        limit=limit,
    )
