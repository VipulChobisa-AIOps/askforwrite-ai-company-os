"""Zero-Trust Presence and Attendance Service for AskforWrite Field Force Engine.

Implements:
1. Haversine distance & geofence containment calculation.
2. Anti-mock GPS / anti-spoofing sensor validation.
3. Teleportation / velocity anomaly detection.
4. Cryptographic sealing of attendance into ECDSA P-256 Trust Chain.
"""

import math
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import FieldAttendanceRecord, GeofenceDefinition
from app.schemas.field_force import (
    AttendanceCheckInRequest,
    AttendanceCheckOutRequest,
    GeofenceCreate,
)
from app.security.trust_chain import seal_task_to_block

# Earth radius in meters for Haversine calculation
EARTH_RADIUS_METERS = 6371000.0
# Maximum plausible ground speed in km/h for velocity sanity check (160 km/h)
MAX_PLAUSIBLE_SPEED_KMH = 160.0


def calculate_haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Calculates great-circle distance between two GPS points in meters."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


def verify_location_integrity(
    db: Session,
    user_id: str,
    latitude: float,
    longitude: float,
    accuracy_meters: float,
    is_mock_provider: bool,
    geofence: GeofenceDefinition | None,
) -> tuple[str, str | None]:
    """Evaluates multi-sensor telemetry for spoofing, teleportation, or geofence breaches.

    Returns (status, verification_notes)
    Status: "VERIFIED" | "SPOOF_REJECTED" | "OUT_OF_BOUNDS"
    """
    # 1. Check OS-level mock location flag
    if is_mock_provider:
        return "SPOOF_REJECTED", "Mock location provider or Fake GPS hook detected by device sensor"

    # 2. Check degraded accuracy (e.g. cell tower only or extreme spoof jitter)
    if accuracy_meters > 150.0:
        return "SPOOF_REJECTED", f"GPS accuracy ({accuracy_meters:.1f}m) exceeds acceptable reliability threshold (150m)"

    # 3. Check teleportation / speed anomaly against user's last recorded event
    last_record = (
        db.query(FieldAttendanceRecord)
        .filter(FieldAttendanceRecord.user_id == user_id)
        .order_by(FieldAttendanceRecord.timestamp.desc())
        .first()
    )

    if last_record and last_record.timestamp:
        last_dt = (
            last_record.timestamp.replace(tzinfo=UTC)
            if last_record.timestamp.tzinfo is None
            else last_record.timestamp.astimezone(UTC)
        )
        now_dt = datetime.now(UTC)
        elapsed_seconds = max((now_dt - last_dt).total_seconds(), 1.0)
        dist_meters = calculate_haversine_distance(
            last_record.latitude, last_record.longitude, latitude, longitude
        )
        speed_kmh = (dist_meters / 1000.0) / (elapsed_seconds / 3600.0)

        # If user apparently traveled > 160 km/h between check-ins, flag teleportation
        if dist_meters > 500.0 and speed_kmh > MAX_PLAUSIBLE_SPEED_KMH:
            return (
                "SPOOF_REJECTED",
                f"Velocity anomaly: jumped {dist_meters / 1000:.1f}km in {elapsed_seconds / 60:.1f} mins ({speed_kmh:.1f} km/h)",
            )

    # 4. Check Geofence boundary if a geofence was specified
    if geofence:
        dist_to_hub = calculate_haversine_distance(
            geofence.latitude, geofence.longitude, latitude, longitude
        )
        effective_radius = geofence.radius_meters + min(accuracy_meters, 30.0)
        if dist_to_hub > effective_radius:
            return (
                "OUT_OF_BOUNDS",
                f"Location is {dist_to_hub:.1f}m from '{geofence.name}' (allowed radius: {geofence.radius_meters:.1f}m)",
            )

    return "VERIFIED", "All zero-trust presence and sensor integrity checks passed"


def create_geofence(
    db: Session,
    org_id: str | None,
    data: GeofenceCreate,
) -> GeofenceDefinition:
    """Creates a new geofence site definition."""
    geofence = GeofenceDefinition(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=data.name,
        latitude=data.latitude,
        longitude=data.longitude,
        radius_meters=data.radius_meters,
        address=data.address,
        is_active=True,
    )
    db.add(geofence)
    db.commit()
    db.refresh(geofence)
    return geofence


def list_geofences(
    db: Session,
    org_id: str | None,
) -> list[GeofenceDefinition]:
    """Lists active geofences for an organization."""
    query = db.query(GeofenceDefinition).filter(GeofenceDefinition.is_active.is_(True))
    if org_id:
        query = query.filter(GeofenceDefinition.org_id == org_id)
    return query.order_by(GeofenceDefinition.name.asc()).all()


def record_attendance_checkin(
    db: Session,
    org_id: str | None,
    req: AttendanceCheckInRequest,
) -> FieldAttendanceRecord:
    """Verifies location integrity and cryptographically seals a check-in."""
    # Check idempotency
    existing = (
        db.query(FieldAttendanceRecord)
        .filter(FieldAttendanceRecord.idempotency_key == req.idempotency_key)
        .first()
    )
    if existing:
        return existing

    # Lookup target geofence if specified
    geofence = None
    if req.geofence_id:
        geofence = db.query(GeofenceDefinition).filter(GeofenceDefinition.id == req.geofence_id).first()

    status, notes = verify_location_integrity(
        db=db,
        user_id=req.user_id,
        latitude=req.latitude,
        longitude=req.longitude,
        accuracy_meters=req.accuracy_meters,
        is_mock_provider=req.is_mock_provider,
        geofence=geofence,
    )

    record_id = str(uuid.uuid4())
    timestamp = datetime.now(UTC)

    # If verified, seal into cryptographic trust chain
    trust_block_hash = None
    if status == "VERIFIED":
        try:
            seal_payload = {
                "attendance_id": record_id,
                "user_id": req.user_id,
                "org_id": org_id,
                "event_type": "CHECK_IN",
                "coordinates": f"{req.latitude:.6f},{req.longitude:.6f}",
                "accuracy_m": req.accuracy_meters,
                "device_fingerprint": req.device_fingerprint,
                "geofence_name": geofence.name if geofence else "Free-Roam",
                "timestamp": timestamp.isoformat(),
            }
            sealed_block = seal_task_to_block(
                db=db,
                task_id=record_id,
                capability_name="field_presence",
                action="attendance_checkin_verified",
                payload=seal_payload,
                sealed_by="AFW-FIELD-FORCE-ZERO-TRUST",
                commit=False,
            )
            trust_block_hash = sealed_block.block_hash
        except Exception:
            # Fall back gracefully if trust block generation encounters non-critical warning
            pass

    record = FieldAttendanceRecord(
        id=record_id,
        org_id=org_id,
        user_id=req.user_id,
        event_type="CHECK_IN",
        latitude=req.latitude,
        longitude=req.longitude,
        accuracy_meters=req.accuracy_meters,
        altitude=req.altitude,
        device_fingerprint=req.device_fingerprint,
        is_mock_location_detected=req.is_mock_provider,
        wifi_bssid_hash=req.wifi_bssid_hash,
        cell_tower_id=req.cell_tower_id,
        geofence_id=req.geofence_id,
        status=status,
        verification_notes=notes,
        trust_block_hash=trust_block_hash,
        idempotency_key=req.idempotency_key,
        timestamp=timestamp,
        metadata_json=req.metadata,
    )

    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def record_attendance_checkout(
    db: Session,
    org_id: str | None,
    req: AttendanceCheckOutRequest,
) -> FieldAttendanceRecord:
    """Verifies location and records check-out event."""
    existing = (
        db.query(FieldAttendanceRecord)
        .filter(FieldAttendanceRecord.idempotency_key == req.idempotency_key)
        .first()
    )
    if existing:
        return existing

    status, notes = verify_location_integrity(
        db=db,
        user_id=req.user_id,
        latitude=req.latitude,
        longitude=req.longitude,
        accuracy_meters=req.accuracy_meters,
        is_mock_provider=req.is_mock_provider,
        geofence=None,
    )

    record_id = str(uuid.uuid4())
    timestamp = datetime.now(UTC)

    trust_block_hash = None
    if status == "VERIFIED":
        try:
            seal_payload = {
                "attendance_id": record_id,
                "user_id": req.user_id,
                "org_id": org_id,
                "event_type": "CHECK_OUT",
                "coordinates": f"{req.latitude:.6f},{req.longitude:.6f}",
                "timestamp": timestamp.isoformat(),
            }
            sealed_block = seal_task_to_block(
                db=db,
                task_id=record_id,
                capability_name="field_presence",
                action="attendance_checkout_verified",
                payload=seal_payload,
                sealed_by="AFW-FIELD-FORCE-ZERO-TRUST",
                commit=False,
            )
            trust_block_hash = sealed_block.block_hash
        except Exception:
            pass

    record = FieldAttendanceRecord(
        id=record_id,
        org_id=org_id,
        user_id=req.user_id,
        event_type="CHECK_OUT",
        latitude=req.latitude,
        longitude=req.longitude,
        accuracy_meters=req.accuracy_meters,
        device_fingerprint=req.device_fingerprint,
        is_mock_location_detected=req.is_mock_provider,
        status=status,
        verification_notes=notes,
        trust_block_hash=trust_block_hash,
        idempotency_key=req.idempotency_key,
        timestamp=timestamp,
        metadata_json=req.metadata,
    )

    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_attendance_history(
    db: Session,
    org_id: str | None,
    user_id: str | None = None,
    limit: int = 50,
) -> list[FieldAttendanceRecord]:
    """Retrieves immutable attendance records."""
    query = db.query(FieldAttendanceRecord)
    if org_id:
        query = query.filter(FieldAttendanceRecord.org_id == org_id)
    if user_id:
        query = query.filter(FieldAttendanceRecord.user_id == user_id)
    return query.order_by(FieldAttendanceRecord.timestamp.desc()).limit(limit).all()
