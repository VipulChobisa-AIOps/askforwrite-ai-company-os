"""Digital Asset & Content QA Benchmark Router + Public Verification Receipt Endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import DigitalQAProtocolRecord, DigitalQAReportRecord
from app.security.auth import APIPrincipal, get_current_principal, require_tenant_admin
from app.services.digital_qa import (
    create_qa_protocol,
    evaluate_and_record_digital_qa,
    render_qa_receipt_html,
    serialize_qa_report,
    sign_off_digital_qa_receipt,
    verify_qa_receipt,
)

router = APIRouter(prefix="/v1/digital-qa", tags=["digital-qa"])


class QAProtocolCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    min_score: int = Field(default=80, ge=50, le=100)
    min_word_count: int = Field(default=600, ge=100, le=10000)
    max_word_count: int = Field(default=4500, ge=500, le=20000)
    require_schema_ld: bool = True
    require_faq: bool = True
    require_live_llm: bool = True
    brand_voice: str = Field(default="authoritative, truthful, non-promotional", max_length=250)
    mandatory_terms: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    banned_slop_phrases: list[str] = Field(default_factory=list)
    is_default: bool = True


class QAEvaluateRequest(BaseModel):
    title: str = Field(default="", max_length=300)
    content: str = Field(..., min_length=20)
    keywords: list[str] = Field(default_factory=list)
    target_url: str | None = Field(default=None, max_length=2048)
    draft_id: str | None = Field(default=None, max_length=36)
    protocol_id: str | None = Field(default=None, max_length=36)
    used_fallback: bool = False


class QASignOffRequest(BaseModel):
    review_notes: str = Field(default="Human editorial & factual verification completed.", max_length=2000)
    target_url: str | None = Field(default=None, max_length=2048)


@router.post("/protocols", status_code=status.HTTP_201_CREATED)
def create_protocol_endpoint(
    payload: QAProtocolCreateRequest,
    principal: APIPrincipal = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a configurable Digital QA Brand & Anti-Slop Protocol for the organization."""
    rec = create_qa_protocol(
        db=db,
        org_id=principal.org_id,
        name=payload.name,
        min_score=payload.min_score,
        min_word_count=payload.min_word_count,
        max_word_count=payload.max_word_count,
        require_schema_ld=payload.require_schema_ld,
        require_faq=payload.require_faq,
        require_live_llm=payload.require_live_llm,
        brand_voice=payload.brand_voice,
        mandatory_terms=payload.mandatory_terms,
        forbidden_terms=payload.forbidden_terms,
        banned_slop_phrases=payload.banned_slop_phrases,
        is_default=payload.is_default,
    )
    return {
        "protocol_id": rec.id,
        "org_id": rec.org_id,
        "name": rec.name,
        "min_score": rec.min_score,
        "min_word_count": rec.min_word_count,
        "max_word_count": rec.max_word_count,
        "require_schema_ld": rec.require_schema_ld,
        "require_faq": rec.require_faq,
        "require_live_llm": rec.require_live_llm,
        "brand_voice": rec.brand_voice,
        "mandatory_terms": rec.mandatory_terms_json or [],
        "forbidden_terms": rec.forbidden_terms_json or [],
        "banned_slop_phrases": rec.banned_slop_phrases_json or [],
        "is_default": rec.is_default,
    }


@router.get("/protocols")
def list_protocols_endpoint(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    q = db.query(DigitalQAProtocolRecord)
    if not principal.is_platform_operator:
        q = q.filter(DigitalQAProtocolRecord.org_id == principal.org_id)
    rows = q.order_by(DigitalQAProtocolRecord.created_at.desc()).limit(50).all()
    return {
        "protocols": [
            {
                "protocol_id": r.id,
                "org_id": r.org_id,
                "name": r.name,
                "min_score": r.min_score,
                "min_word_count": r.min_word_count,
                "max_word_count": r.max_word_count,
                "require_schema_ld": r.require_schema_ld,
                "require_faq": r.require_faq,
                "require_live_llm": r.require_live_llm,
                "brand_voice": r.brand_voice,
                "mandatory_terms": r.mandatory_terms_json or [],
                "forbidden_terms": r.forbidden_terms_json or [],
                "is_default": r.is_default,
            }
            for r in rows
        ]
    }


@router.post("/evaluate", status_code=status.HTTP_200_OK)
def evaluate_content_endpoint(
    payload: QAEvaluateRequest,
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Evaluate a digital content deliverable against the organization's QA Benchmark Protocol."""
    return evaluate_and_record_digital_qa(
        db=db,
        org_id=principal.org_id,
        content=payload.content,
        title=payload.title,
        keywords=payload.keywords,
        target_url=payload.target_url,
        draft_id=payload.draft_id,
        protocol_id=payload.protocol_id,
        used_fallback=payload.used_fallback,
        actor=principal.subject,
    )


@router.get("/reports")
def list_reports_endpoint(
    limit: int = Query(default=25, ge=1, le=100),
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    q = db.query(DigitalQAReportRecord)
    if not principal.is_platform_operator:
        q = q.filter(DigitalQAReportRecord.org_id == principal.org_id)
    rows = q.order_by(DigitalQAReportRecord.created_at.desc()).limit(limit).all()
    return {"reports": [serialize_qa_report(r) for r in rows]}


@router.post("/reports/{receipt_id}/sign-off", status_code=status.HTTP_200_OK)
def sign_off_receipt_endpoint(
    receipt_id: str,
    payload: QASignOffRequest,
    principal: APIPrincipal = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record human editorial sign-off and seal a client-verifiable ECDSA Human-Review Receipt."""
    try:
        return sign_off_digital_qa_receipt(
            db=db,
            receipt_id=receipt_id,
            reviewer=principal.email or principal.subject,
            review_notes=payload.review_notes,
            target_url=payload.target_url,
            org_id=None if principal.is_platform_operator else principal.org_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/receipts/{receipt_id}")
def get_public_qa_receipt(
    receipt_id: str,
    request: Request,
    format: str = Query(default="auto", pattern="^(auto|json|html)$"),
    db: Session = Depends(get_db),
):
    """Publicly verify a signed Digital QA & Human-Review Receipt (JSON or printable HTML certificate)."""
    verified = verify_qa_receipt(db, receipt_id)
    if not verified:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Receipt '{receipt_id}' not found")

    accept = (request.headers.get("accept") or "").lower()
    wants_html = format == "html" or (format == "auto" and "text/html" in accept and "application/json" not in accept)
    if wants_html:
        return HTMLResponse(content=render_qa_receipt_html(verified), status_code=200)
    return JSONResponse(content=verified, status_code=200)
