"""FastAPI router for Computer Vision Quality Analytics & Produce Grading."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import APIPrincipal, require_manager
from app.services.quality_analytics import (
    CAPABILITY_NAME,
    CLASSES,
    QualityAnalyticsConflict,
    execute_produce_quality_inspection,
    log_quality_uat,
)

router = APIRouter(prefix="/v1/quality", tags=["produce-quality-analytics"])


class QualityInspectRequest(BaseModel):
    preset_or_sample: Literal["unripe", "ripe", "overripe"] = Field(
        default="ripe",
        description="Benchmark synthetic produce sample or physical camera preset",
    )
    crop_variety: str = Field(default="Alphonso Mango", max_length=120)
    batch_lot_id: str | None = Field(default=None, max_length=64)
    custom_matrix: list[list[list[int]]] | None = Field(
        default=None,
        description="Optional RGB 3D pixel matrix (e.g. 224x224x3) for direct camera feed ingestion",
    )
    image_base64: str | None = Field(
        default=None,
        description="Base64-encoded image string (PNG, JPEG, WebP) for direct upload",
    )


class QualityInspectResponse(BaseModel):
    status: str
    task_id: str
    correlation_id: str
    inspection_report: dict[str, Any]


class QualityUATRequest(BaseModel):
    role: str = Field(default="Quality Inspector", max_length=120)
    rating: int = Field(default=5, ge=1, le=5)
    comments: str = Field(default="Inspection results clear and accurate", max_length=2000)


@router.get("/status")
def get_quality_engine_status() -> dict[str, Any]:
    """Return operational telemetry, supported crop classes, and feature extraction dimensions."""
    return {
        "status": "OPERATIONAL",
        "engine": "AskforWrite Produce Vision & Quality Grading AI",
        "capability": CAPABILITY_NAME,
        "classes": CLASSES,
        "feature_extractors": {
            "color_space": "HSV (Hue, Saturation, Value)",
            "histogram_dimensions": 512,
            "texture_descriptors": ["contrast", "dissimilarity", "homogeneity", "energy", "correlation", "asm"],
            "model_ensemble": ["Support Vector Machine (SVM)", "Random Forest (RF)", "Gaussian Naive Bayes (GNB)", "Lightweight PyTorch CNN"],
        },
        "supported_varieties": [
            "Alphonso Mango",
            "Kesar Mango",
            "Banganapalli",
            "Hass Avocado",
            "Cavendish Banana",
        ],
        "cryptographic_ledger": "ECDSA NIST P-256 Merkle TrustBlock Sealing Enabled",
    }


@router.post(
    "/inspect",
    response_model=QualityInspectResponse,
    status_code=status.HTTP_200_OK,
)
def inspect_produce_batch(
    payload: QualityInspectRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-ID"),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> QualityInspectResponse:
    """Execute automated produce quality grading and seal result into cryptographic TrustBlock."""
    try:
        res = execute_produce_quality_inspection(
            db=db,
            preset_or_sample=payload.preset_or_sample,
            custom_image_matrix=payload.custom_matrix,
            image_base64=payload.image_base64,
            batch_lot_id=payload.batch_lot_id,
            crop_variety=payload.crop_variety,
            idempotency_key=idempotency_key,
            correlation_id=x_correlation_id,
            agent_id=principal.subject,
        )
        return QualityInspectResponse(**res)
    except QualityAnalyticsConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Produce inspection failed: {exc}",
        ) from exc


@router.post(
    "/inspect-image",
    response_model=QualityInspectResponse,
    status_code=status.HTTP_200_OK,
)
async def inspect_uploaded_image(
    file: UploadFile = File(..., description="Binary image file (JPEG, PNG, WebP)"),
    crop_variety: str = Form("Alphonso Mango"),
    batch_lot_id: str | None = Form(None),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-ID"),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> QualityInspectResponse:
    """Upload physical produce photograph for 4-model ripeness analysis and TrustBlock sealing."""
    try:
        contents = await file.read()
        res = execute_produce_quality_inspection(
            db=db,
            image_bytes=contents,
            batch_lot_id=batch_lot_id,
            crop_variety=crop_variety,
            idempotency_key=idempotency_key,
            correlation_id=x_correlation_id,
            agent_id=principal.subject,
        )
        return QualityInspectResponse(**res)
    except QualityAnalyticsConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Uploaded image produce inspection failed: {exc}",
        ) from exc


@router.post(
    "/uat",
    status_code=status.HTTP_200_OK,
)
def submit_quality_uat_feedback(
    payload: QualityUATRequest,
    principal: APIPrincipal = Depends(require_manager),
) -> dict[str, Any]:
    """Log quality inspection user acceptance test (UAT) survey feedback."""
    return log_quality_uat(
        role=payload.role,
        rating=payload.rating,
        comments=payload.comments,
        inspector=principal.subject,
    )
