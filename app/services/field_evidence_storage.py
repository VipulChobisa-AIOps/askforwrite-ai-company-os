"""FieldGuard Evidence Storage, Real Pillow Image Integrity, EXIF Forensics & Perceptual Deduplication.

Replaces hardcoded photo/OCR stubs with verifiable binary inspection:
- Safe base64/data-URI decoding & Pillow format verification
- 64-bit difference hash (dHash) for cross-claim duplicate receipt detection (even after re-compression/cropping)
- Real Laplacian edge-variance sharpness check (catches blank/black/blurred frames)
- Real EXIF metadata & GPS coordinate cross-check (catches old gallery photos / spoofed locations)
- Durable artifact persistence (S3/R2 when FIELD_EVIDENCE_S3_BUCKET is set, else content-addressed local volume)
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image, ImageFilter, ImageStat

from app.services.field_presence import calculate_haversine_distance

logger = logging.getLogger(__name__)

_DATA_URI_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", re.DOTALL)
_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def decode_base64_image(raw_payload: str | None) -> tuple[bytes | None, str | None]:
    """Decode a data-URI or raw base64 image payload into (image_bytes, mime_type).

    Returns (None, None) when the input is an opaque hash/URL reference rather than binary image data.
    """
    if not raw_payload or not isinstance(raw_payload, str):
        return None, None
    cleaned = raw_payload.strip()
    if not cleaned or cleaned.startswith(("http://", "https://", "s3://", "local://")):
        return None, None

    mime_hint: str | None = None
    b64_body = cleaned
    match = _DATA_URI_RE.match(cleaned)
    if match:
        mime_hint = match.group(1).lower()
        b64_body = match.group(2).strip()
    else:
        # Heuristic: plain opaque hash strings (like "receipt-img-sample-valid-hash-00129")
        # should NOT be mis-decoded as images unless they carry valid image magic bytes after b64 decode.
        if len(b64_body) < 64 or " " in b64_body:
            return None, None

    try:
        raw_bytes = base64.b64decode(b64_body, validate=False)
    except Exception:
        return None, None

    if not raw_bytes or len(raw_bytes) < 16:
        return None, None

    # Verify image magic bytes (JPEG, PNG, WEBP, GIF)
    detected_mime: str | None = None
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        detected_mime = "image/jpeg"
    elif raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        detected_mime = "image/png"
    elif raw_bytes.startswith(b"RIFF") and len(raw_bytes) >= 12 and raw_bytes[8:12] == b"WEBP":
        detected_mime = "image/webp"
    elif raw_bytes.startswith((b"GIF87a", b"GIF89a")):
        detected_mime = "image/gif"

    if detected_mime is None:
        return None, None

    return raw_bytes, detected_mime or mime_hint


def compute_dhash_64(img: Image.Image) -> str:
    """Compute a 64-bit difference perceptual hash (dHash) as a 16-character hex string."""
    gray = img.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
    pixels = list(gray.tobytes())
    bits = 0
    for row in range(8):
        row_start = row * 9
        for col in range(8):
            left = pixels[row_start + col]
            right = pixels[row_start + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def hamming_distance_hex(hash_a: str | None, hash_b: str | None) -> int:
    """Compute Hamming distance between two 16-char 64-bit hex perceptual hashes."""
    if not hash_a or not hash_b:
        return 64
    try:
        return (int(hash_a, 16) ^ int(hash_b, 16)).bit_count()
    except ValueError:
        return 64


def _rational_to_float(val: Any) -> float:
    if isinstance(val, tuple) and len(val) == 2 and val[1]:
        return float(val[0]) / float(val[1])
    return float(val)


def _dms_to_decimal(dms: Any, ref: str | None) -> float | None:
    try:
        deg = _rational_to_float(dms[0])
        minutes = _rational_to_float(dms[1])
        sec = _rational_to_float(dms[2])
        decimal = deg + (minutes / 60.0) + (sec / 3600.0)
        if ref and str(ref).upper() in ("S", "W"):
            decimal = -decimal
        return round(decimal, 6)
    except Exception:
        return None


def _extract_exif_forensics(img: Image.Image) -> dict[str, Any]:
    """Extract capture timestamp, camera make/model, and GPS coordinates from EXIF if present."""
    exif_out: dict[str, Any] = {
        "has_exif": False,
        "capture_datetime": None,
        "camera_model": None,
        "exif_latitude": None,
        "exif_longitude": None,
    }
    try:
        raw_exif = img.getexif()
        if not raw_exif:
            return exif_out
        tag_map = {ExifTags.TAGS.get(k, str(k)): v for k, v in raw_exif.items()}
        if tag_map:
            exif_out["has_exif"] = True

        # Check DateTimeOriginal inside EXIF SubIFD (0x8769) or top-level DateTime
        dt_str = tag_map.get("DateTimeOriginal") or tag_map.get("DateTime")
        try:
            sub_ifd = raw_exif.get_ifd(0x8769)
            if sub_ifd:
                sub_tags = {ExifTags.TAGS.get(k, str(k)): v for k, v in sub_ifd.items()}
                dt_str = sub_tags.get("DateTimeOriginal") or sub_tags.get("DateTimeDigitized") or dt_str
        except Exception:
            pass
        if isinstance(dt_str, str) and dt_str.strip():
            exif_out["capture_datetime"] = dt_str.strip()

        make = str(tag_map.get("Make") or "").strip()
        model = str(tag_map.get("Model") or "").strip()
        if make or model:
            exif_out["camera_model"] = f"{make} {model}".strip()

        # GPS IFD (0x8825)
        try:
            gps_ifd = raw_exif.get_ifd(0x8825)
        except Exception:
            gps_ifd = None
        if gps_ifd:
            gps_tags = {ExifTags.GPSTAGS.get(k, str(k)): v for k, v in gps_ifd.items()}
            lat_dms = gps_tags.get("GPSLatitude")
            lat_ref = gps_tags.get("GPSLatitudeRef")
            lon_dms = gps_tags.get("GPSLongitude")
            lon_ref = gps_tags.get("GPSLongitudeRef")
            if lat_dms and lon_dms:
                exif_out["exif_latitude"] = _dms_to_decimal(lat_dms, lat_ref)
                exif_out["exif_longitude"] = _dms_to_decimal(lon_dms, lon_ref)
    except Exception as exc:
        logger.debug("EXIF parse skipped: %s", exc)
    return exif_out


def inspect_image_integrity(
    image_bytes: bytes,
    *,
    claimed_latitude: float | None = None,
    claimed_longitude: float | None = None,
    max_exif_age_hours: float = 24.0,
    max_exif_gps_drift_meters: float = 500.0,
) -> dict[str, Any]:
    """Run real Pillow image integrity, sharpness variance, perceptual hashing, and EXIF checks."""
    sha256_hex = hashlib.sha256(image_bytes).hexdigest()
    flags: list[str] = []

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.load()
            width, height = img.size
            img_format = (img.format or "UNKNOWN").upper()
            dhash = compute_dhash_64(img)
            exif_info = _extract_exif_forensics(img)

            # Edge variance (Laplacian proxy) + intensity variance to reject blank/solid/corrupt frames
            gray = img.convert("L")
            gray_stat = ImageStat.Stat(gray)
            intensity_stddev = round(float(gray_stat.stddev[0]), 2) if gray_stat.stddev else 0.0

            edges = gray.filter(ImageFilter.FIND_EDGES)
            edge_stat = ImageStat.Stat(edges)
            laplacian_variance = round(float(edge_stat.var[0]), 2) if edge_stat.var else 0.0
    except Exception as exc:
        return {
            "valid_image": False,
            "sha256": sha256_hex,
            "perceptual_hash": None,
            "width": 0,
            "height": 0,
            "format": "CORRUPT",
            "intensity_stddev": 0.0,
            "laplacian_variance": 0.0,
            "exif": {},
            "flags": [f"CORRUPT_IMAGE_PAYLOAD: {type(exc).__name__}"],
        }

    if width < 32 or height < 32:
        flags.append(f"LOW_RESOLUTION_IMAGE: {width}x{height}")

    if intensity_stddev < 3.0 and laplacian_variance < 5.0:
        flags.append("BLANK_OR_SOLID_FRAME_DETECTED")
    elif laplacian_variance < 18.0:
        flags.append(f"LOW_IMAGE_QUALITY_BLURRY: variance={laplacian_variance}")

    if not exif_info.get("has_exif"):
        flags.append("NO_EXIF_METADATA_SCREENSHOT_RISK")
    else:
        dt_raw = exif_info.get("capture_datetime")
        if dt_raw:
            try:
                captured = datetime.strptime(dt_raw, "%Y:%m:%d %H:%M:%S").replace(tzinfo=UTC)
                age_hours = abs((datetime.now(UTC) - captured).total_seconds()) / 3600.0
                if age_hours > max_exif_age_hours:
                    flags.append(f"STALE_PHOTO_EXIF: captured {age_hours:.1f}h ago ({dt_raw})")
            except ValueError:
                pass

        exif_lat = exif_info.get("exif_latitude")
        exif_lon = exif_info.get("exif_longitude")
        if (
            exif_lat is not None
            and exif_lon is not None
            and claimed_latitude is not None
            and claimed_longitude is not None
        ):
            drift_m = calculate_haversine_distance(claimed_latitude, claimed_longitude, exif_lat, exif_lon)
            exif_info["exif_gps_drift_meters"] = round(drift_m, 1)
            if drift_m > max_exif_gps_drift_meters:
                flags.append(f"EXIF_GPS_MISMATCH: photo GPS is {drift_m:.0f}m away from claimed visit coordinates")

    return {
        "valid_image": True,
        "sha256": sha256_hex,
        "perceptual_hash": dhash,
        "width": width,
        "height": height,
        "format": img_format,
        "intensity_stddev": intensity_stddev,
        "laplacian_variance": laplacian_variance,
        "exif": exif_info,
        "flags": flags,
    }


def _safe_segment(val: str | None, fallback: str) -> str:
    cleaned = _SAFE_SEGMENT_RE.sub("_", (val or "").strip()).strip("_")
    return cleaned[:64] if cleaned else fallback


def persist_evidence_bytes(
    *,
    org_id: str | None,
    category: str,
    image_bytes: bytes,
    mime_type: str,
) -> dict[str, str]:
    """Durably store receipt/photo evidence in S3/R2 (if configured) or content-addressed local directory."""
    sha256_hex = hashlib.sha256(image_bytes).hexdigest()
    ext = _MIME_TO_EXT.get(mime_type.lower(), "bin")
    safe_org = _safe_segment(org_id, "platform")
    safe_cat = _safe_segment(category, "evidence")
    object_key = f"field_evidence/{safe_org}/{safe_cat}/{sha256_hex}.{ext}"

    s3_bucket = (os.environ.get("FIELD_EVIDENCE_S3_BUCKET") or "").strip()
    if s3_bucket:
        try:
            import boto3  # type: ignore[import-untyped]

            endpoint_url = (os.environ.get("FIELD_EVIDENCE_S3_ENDPOINT") or "").strip() or None
            client = boto3.client("s3", endpoint_url=endpoint_url)
            client.put_object(
                Bucket=s3_bucket,
                Key=object_key,
                Body=image_bytes,
                ContentType=mime_type,
            )
            return {
                "storage_backend": "s3",
                "storage_uri": f"s3://{s3_bucket}/{object_key}",
                "sha256": sha256_hex,
            }
        except Exception as exc:
            logger.warning("S3 evidence upload failed (%s); falling back to durable local store.", exc)

    base_dir = Path(os.environ.get("FIELD_EVIDENCE_STORAGE_DIR", "./keys/field_evidence")).resolve()
    target = (base_dir / safe_org / safe_cat / f"{sha256_hex}.{ext}").resolve()
    # Path-traversal defense
    if not str(target).startswith(str(base_dir)):
        raise ValueError("Invalid evidence storage path")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(image_bytes)
    return {
        "storage_backend": "local_content_addressed",
        "storage_uri": f"local://{object_key}",
        "sha256": sha256_hex,
    }
