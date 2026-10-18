"""Trojan-Horse Proof-First Public Preview API Router.

Endpoints for:
- POST /v1/previews/generate: Generate tailored proof-of-value preview and checkout links
- GET  /v1/previews/{preview_token}: Public JSON retrieval of preview details
- GET  /v1/previews/{preview_token}/html: Public conversion-optimized HTML landing page
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.security.auth import APIPrincipal, require_manager
from app.services.previews import (
    generate_trojan_horse_preview,
    get_preview_by_token,
    render_preview_html,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/previews", tags=["Trojan-Horse Previews"])


class PreviewGenerateRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=250, description="Target company or prospect name")
    domain: str = Field(min_length=2, max_length=250, description="Website domain or URL")
    recommended_package: str = Field(default="growth_all_in_one", description="Recommended catalog SKU")
    lead_id: str | None = Field(default=None, max_length=36, description="Optional associated lead ID")


@router.post("/generate", status_code=status.HTTP_200_OK)
def generate_preview_endpoint(
    payload: PreviewGenerateRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate a Trojan-Horse proof-first preview with tailored audit, benchmarks, payment links, and TrustBlock."""
    correlation_id = x_correlation_id or str(uuid.uuid4())
    try:
        return generate_trojan_horse_preview(
            db=db,
            company_name=payload.company_name,
            domain=payload.domain,
            recommended_package=payload.recommended_package,
            lead_id=payload.lead_id,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        logger.error(f"Error generating preview: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Preview generation failed: {exc}",
        ) from exc


@router.get("/{preview_token}")
def get_preview_json_endpoint(
    preview_token: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Publicly accessible JSON endpoint returning preview details and 1-click checkout links."""
    preview = get_preview_by_token(db=db, preview_token=preview_token, increment_view=True)
    if not preview:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preview with token '{preview_token}' not found",
        )

    return {
        "status": "COMPLETED",
        "preview_token": preview.preview_token,
        "company_name": preview.company_name,
        "domain": preview.domain,
        "recommended_package": preview.recommended_package,
        "custom_audit": preview.custom_audit,
        "sample_deliverable": preview.sample_deliverable,
        "benchmarks": preview.benchmarks,
        "payment_links": preview.payment_links,
        "views_count": preview.views_count,
        "trust_block_hash": preview.trust_block_hash,
        "created_at": preview.created_at.isoformat() if preview.created_at else None,
        "updated_at": preview.updated_at.isoformat() if preview.updated_at else None,
    }


@router.get("/{preview_token}/html", response_class=HTMLResponse)
def get_preview_html_endpoint(
    preview_token: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Publicly accessible HTML landing page displaying audit, sample deliverable, trust badge, and buy buttons."""
    preview = get_preview_by_token(db=db, preview_token=preview_token, increment_view=True)
    if not preview:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preview with token '{preview_token}' not found",
        )

    html_content = render_preview_html(preview)
    return HTMLResponse(content=html_content, status_code=status.HTTP_200_OK)
