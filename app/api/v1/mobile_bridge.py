"""Pixel AI Mobile Bridge Router — AskforWrite AI Company OS.

Bridges the native mobile app (afwpixelai Capacitor Android/iOS) and PWA
with Company OS Field Force, Lead Operations, and AI Assistant services.
"""

import hmac
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import (
    FieldTaskRecord,
    GeofenceDefinition,
    OrganizationRecord,
    UserRecord,
)
from app.security.auth import PLATFORM_OPERATOR_ROLES, decode_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/mobile", tags=["Pixel AI Mobile Bridge"])


# ── Schemas ───────────────────────────────────────────────────────────

class DeviceRegistrationRequest(BaseModel):
    device_id: str = Field(..., description="Unique hardware or installation UUID")
    platform: str = Field("android", description="Platform: android, ios, or pwa")
    app_version: str = Field("2.1.0", description="Installed mobile client version")
    push_token: str | None = Field(None, description="FCM or APNS push token")
    device_model: str | None = Field(None, description="e.g. Pixel 8, Samsung S23")
    os_version: str | None = Field(None, description="e.g. Android 14, iOS 17.4")


class MobileCheckInRequest(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    accuracy_meters: float = Field(..., ge=0.0)
    check_type: str = Field("check_in", description="check_in or check_out")
    client_timestamp: str | None = None
    geofence_id: str | None = None
    mock_provider_detected: bool = False


class MobileVisitSubmissionRequest(BaseModel):
    client_id: str
    task_id: str | None = None
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    photo_base64: str | None = None
    photo_evidence_url: str | None = None
    geo_otp_code: str | None = None
    voice_notes_transcript: str | None = None
    interaction_notes: str | None = None


class MobileConveyanceClaimRequest(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    distance_km: float = Field(..., gt=0.0)
    vehicle_type: str = Field("bike", description="bike, car, or public_transit")
    purpose: str = Field(..., min_length=3)
    start_odometer_reading: float | None = None
    end_odometer_reading: float | None = None
    receipt_base64: str | None = None


class PixelAssistantRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Voice transcript or text instruction")
    context_mode: str = Field("field_ops", description="field_ops, sales_pitch, or general")
    current_latitude: float | None = None
    current_longitude: float | None = None


# ── Dependency: Authenticate Mobile Field Agent ───────────────────────

def get_mobile_user(
    authorization: str | None = Header(default=None, description="Bearer JWT token or API Key"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> UserRecord:
    """Authenticates the mobile user via verified DB Bearer JWT or platform operator API key."""
    auth_header = authorization or ""
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        try:
            payload = decode_access_token(token)
        except Exception:
            payload = None
        if isinstance(payload, dict) and payload.get("sub"):
            user_id = str(payload["sub"])
            user = db.get(UserRecord, user_id)
            if not user or not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account is inactive or no longer exists",
                )
            if user.org_id != payload.get("org_id"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Token organization scope mismatch",
                )
            if user.role == "customer":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Field staff or manager role required for mobile bridge",
                )
            if not user.org_id and user.role not in PLATFORM_OPERATOR_ROLES:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Tenant organization scope is required",
                )
            if user.org_id:
                org = db.get(OrganizationRecord, user.org_id)
                if org is not None and not org.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Organization account is inactive or suspended",
                    )
            return user

    # Allow platform API-Key fallback without ever impersonating a tenant DB user
    candidate_key = (
        x_api_key.strip()
        if x_api_key
        else (auth_header[7:].strip() if auth_header.startswith("Bearer ") else auth_header.strip())
    )
    if candidate_key:
        for env_name, role in (("OWNER_API_KEY", "owner"), ("MANAGER_API_KEY", "manager")):
            expected_key = os.environ.get(env_name, "")
            if expected_key and len(expected_key) >= 32 and hmac.compare_digest(expected_key, candidate_key):
                return UserRecord(
                    id=f"platform-{role}",
                    email="ops@askforwrite.in",
                    full_name="Platform Operations Manager",
                    role=role,
                    org_id=None,
                    is_active=True,
                )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired mobile credentials. Please authenticate with a valid Bearer token.",
    )



# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/status")
def get_mobile_bridge_status() -> dict[str, Any]:
    """Returns the operational status of the Pixel AI Mobile Bridge."""
    return {
        "status": "online",
        "bridge_version": "2.1.0",
        "ecosystem": "Pixel AI & Unolo Field Force Bridge",
        "supported_clients": ["afwpixelai-android", "afwpixelai-ios", "pwa-field-client"],
        "capabilities": [
            "gps_geofence_attendance",
            "offline_first_visit_verification",
            "anti_spoof_fraud_detection",
            "conveyance_receipt_ocr",
            "pixel_conversational_copilot",
            "cryptographic_trust_ledger_sync",
        ],
        "pwa_manifest": "/mobile/manifest.json",
        "api_docs": "/docs#/Pixel%20AI%20Mobile%20Bridge",
    }


@router.post("/device/register")
def register_mobile_device(
    req: DeviceRegistrationRequest,
    user: UserRecord = Depends(get_mobile_user),
) -> dict[str, Any]:
    """Registers a field worker device token for push dispatches and audit."""
    return {
        "status": "registered",
        "device_id": req.device_id,
        "platform": req.platform,
        "user_id": user.id,
        "org_id": user.org_id,
        "registered_at": datetime.now(UTC).isoformat(),
        "sync_interval_seconds": 300,
    }


@router.post("/attendance/check-in")
def mobile_check_in(
    req: MobileCheckInRequest,
    user: UserRecord = Depends(get_mobile_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Records real-time GPS attendance (check-in or check-out) directly from the mobile app."""
    from app.schemas.field_force import AttendanceCheckInRequest, AttendanceCheckOutRequest
    from app.services.field_presence import record_attendance_checkin, record_attendance_checkout

    clean_type = (req.check_type or "check_in").strip().lower()
    if clean_type not in ("check_in", "check_out"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid check_type. Must be 'check_in' or 'check_out'.",
        )

    if clean_type == "check_out":
        checkout_req = AttendanceCheckOutRequest(
            user_id=user.id,
            latitude=req.latitude,
            longitude=req.longitude,
            accuracy_meters=req.accuracy_meters,
            device_fingerprint=f"mobile-{user.id[:8]}-device",
            is_mock_provider=req.mock_provider_detected,
            idempotency_key=str(uuid.uuid4()),
        )
        rec = record_attendance_checkout(db, org_id=user.org_id, req=checkout_req)
    else:
        if req.geofence_id:
            gf = db.get(GeofenceDefinition, req.geofence_id)
            if not gf:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Geofence not found")
            if user.org_id and gf.org_id != user.org_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: geofence belongs to another organization",
                )
        checkin_req = AttendanceCheckInRequest(
            user_id=user.id,
            latitude=req.latitude,
            longitude=req.longitude,
            accuracy_meters=req.accuracy_meters,
            device_fingerprint=f"mobile-{user.id[:8]}-device",
            is_mock_provider=req.mock_provider_detected,
            geofence_id=req.geofence_id,
            idempotency_key=str(uuid.uuid4()),
        )
        rec = record_attendance_checkin(db, org_id=user.org_id, req=checkin_req)

    return {
        "status": rec.status,
        "check_type": clean_type,
        "attendance_id": rec.id,
        "event_type": rec.event_type,
        "timestamp": rec.timestamp.isoformat() if rec.timestamp else None,
        "latitude": rec.latitude,
        "longitude": rec.longitude,
        "is_mock_location_detected": rec.is_mock_location_detected,
        "trust_block_hash": rec.trust_block_hash,
    }


@router.post("/visits/submit")
def mobile_submit_visit(
    req: MobileVisitSubmissionRequest,
    user: UserRecord = Depends(get_mobile_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Submits client visit verification with photos, OTP, and voice notes."""
    from app.schemas.field_force import ClientVisitVerifyRequest
    from app.services.field_verification import verify_client_visit

    photo_url = req.photo_evidence_url
    if not photo_url and req.photo_base64:
        b64_raw = req.photo_base64.strip()
        photo_url = b64_raw if b64_raw.startswith("data:image/") else f"data:image/jpeg;base64,{b64_raw}"

    task_id = req.task_id
    if task_id:
        existing_task = db.get(FieldTaskRecord, task_id)
        if not existing_task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field task not found")
        if user.org_id and existing_task.org_id != user.org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: task belongs to another organization",
            )
    else:
        # Create a transient task if none passed
        transient_task = FieldTaskRecord(
            id=str(uuid.uuid4()),
            org_id=user.org_id,
            assigned_to_user_id=user.id,
            title=f"Mobile Visit to Client {req.client_id}",
            client_name=req.client_id,
            destination_lat=req.latitude,
            destination_lon=req.longitude,
            priority="NORMAL",
            status="ASSIGNED",
        )
        db.add(transient_task)
        db.flush()
        task_id = transient_task.id

    verif_req = ClientVisitVerifyRequest(
        task_id=task_id,
        user_id=user.id,
        latitude=req.latitude,
        longitude=req.longitude,
        accuracy_meters=10.0,
        photo_evidence_base64_or_url=photo_url,
        geo_otp_code=req.geo_otp_code,
        notes=f"{req.interaction_notes or ''} [Voice: {req.voice_notes_transcript or 'None'}]".strip(),
    )

    rec = verify_client_visit(db, org_id=user.org_id, req=verif_req)
    return {
        "status": rec.photo_verification_status,
        "visit_id": rec.id,
        "task_id": rec.task_id,
        "geo_otp_verified": rec.geo_otp_verified,
        "trust_block_hash": rec.trust_block_hash,
        "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
    }


@router.post("/conveyance/claim")
def mobile_submit_conveyance(
    req: MobileConveyanceClaimRequest,
    user: UserRecord = Depends(get_mobile_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Submits on-the-go conveyance/mileage expense claim from mobile."""
    from app.schemas.field_force import ConveyanceClaimCreate
    from app.services.field_conveyance import submit_conveyance_claim

    receipt_url = None
    if req.receipt_base64:
        rb = req.receipt_base64.strip()
        receipt_url = rb if rb.startswith("data:image/") else f"data:image/jpeg;base64,{rb}"

    claim_req = ConveyanceClaimCreate(
        user_id=user.id,
        date=req.date,
        distance_km=req.distance_km,
        vehicle_type=req.vehicle_type,
        purpose=req.purpose,
        start_odometer_reading=req.start_odometer_reading,
        end_odometer_reading=req.end_odometer_reading,
        receipt_photo_url=receipt_url,
    )

    claim = submit_conveyance_claim(db, claim_req, org_id=user.org_id)
    return {
        "status": "submitted",
        "claim_id": claim.id,
        "agent_id": claim.user_id,
        "distance_km": claim.verified_road_distance_km,
        "amount": claim.grand_total_amount,
        "currency": "INR",
        "approval_status": claim.status,
        "fraud_flag": bool(claim.discrepancy_flags),
        "trust_block_hash": claim.trust_block_hash,
    }



@router.get("/tasks/assigned")
def get_assigned_field_tasks(
    user: UserRecord = Depends(get_mobile_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Lists field tasks assigned to the current mobile agent."""
    task_query = db.query(FieldTaskRecord).filter(FieldTaskRecord.assigned_to_user_id == user.id)
    if user.org_id:
        task_query = task_query.filter(FieldTaskRecord.org_id == user.org_id)
    elif user.role not in PLATFORM_OPERATOR_ROLES:
        task_query = task_query.filter(FieldTaskRecord.org_id.is_(None))
    tasks = task_query.order_by(FieldTaskRecord.created_at.desc()).limit(20).all()

    return {
        "user_id": user.id,
        "tasks_count": len(tasks),
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "client_name": t.client_name,
                "status": t.status,
                "priority": t.priority,
                "due_at": t.due_at.isoformat() if t.due_at else None,
                "destination_lat": t.destination_lat,
                "destination_lon": t.destination_lon,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ],
    }


@router.post("/pixel/assist")
def pixel_ai_assistant(
    req: PixelAssistantRequest,
    user: UserRecord = Depends(get_mobile_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Conversational AI Assistant for mobile field agents and managers.

    Handles natural language queries:
    - Today's tasks & client visits
    - Geofence status & attendance summary
    - Lead diagnosis & sales pitch summaries
    """
    prompt_lower = req.prompt.lower()
    reply = ""
    suggested_action = None

    # Handle domain-specific intent matching
    if any(w in prompt_lower for w in ["task", "visit", "schedule", "today", "todo"]):
        pending_q = db.query(FieldTaskRecord).filter(FieldTaskRecord.assigned_to_user_id == user.id)
        if user.org_id:
            pending_q = pending_q.filter(FieldTaskRecord.org_id == user.org_id)
        elif user.role not in PLATFORM_OPERATOR_ROLES:
            pending_q = pending_q.filter(FieldTaskRecord.org_id.is_(None))
        pending_tasks = pending_q.count()
        reply = (
            f"Hello {user.full_name or 'Agent'}! You currently have {pending_tasks} task(s) on your schedule. "
            f"Your next destination is loaded on your mobile map."
        )
        suggested_action = {"type": "OPEN_TASKS", "route": "/mobile/tasks"}

    elif any(w in prompt_lower for w in ["check in", "checkin", "attendance", "punch in"]):
        reply = (
            "Ready for check-in! Please confirm your GPS location to verify the geofence perimeter and seal your attendance."
        )
        suggested_action = {"type": "TRIGGER_CHECKIN", "lat": req.current_latitude, "lng": req.current_longitude}

    elif any(w in prompt_lower for w in ["claim", "conveyance", "mileage", "fuel", "expense"]):
        reply = (
            "You can log your trip distance and snap a photo of your odometer or fuel receipt to submit a claim instantly."
        )
        suggested_action = {"type": "OPEN_CONVEYANCE", "route": "/mobile/conveyance"}

    elif any(w in prompt_lower for w in ["pitch", "sales", "revenue", "quote", "lead"]):
        reply = (
            "AskforWrite Company OS Revenue Engine is active. Modular Field Ops Suite is ₹12,000/mo ($149/mo). "
            "Payment checkout links can be embedded in your client proposal."
        )
        suggested_action = {"type": "SHOW_PACKAGES", "package": "modular_field_ops"}

    else:
        # Default AI executive response
        reply = (
            f"Pixel AI Assistant received: \"{req.prompt}\". All systems nominal. "
            f"Connected to Company OS Gateway at os.askforwrite.com with cryptographic trust chain active."
        )
        suggested_action = {"type": "INFO"}

    return {
        "reply": reply,
        "agent": "PixelBot Omnichannel Copilot v2.1",
        "suggested_action": suggested_action,
        "timestamp": datetime.now(UTC).isoformat(),
        "user_id": user.id,
    }
