"""Multi-tenant Prospecting and Lead Management API router.

Endpoints for:
- Discovery: run qualified prospect searches with quota enforcement and domain deduplication
- Listing: filter and retrieve organization leads with fit scores and lifecycle states
- Enrichment: live website scraping to extract titles, headings, and public contact channels
- Lifecycle: advance lead status (DISCOVERED -> QUALIFIED -> CONTACTED -> CONVERTED)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.agents.discovery import normalize_domain
from app.agents.sources import (
    LiveEnrichmentLeadSource,
    OfflineSignalProvider,
    fetch_and_enrich_website,
)
from app.db.database import get_db
from app.db.models import AuditLog, LeadRecordRow, OrganizationRecord
from app.schemas.lead import (
    LeadDiscoverRequest,
    LeadEnrichRequest,
    LeadListResponse,
    LeadResponse,
    LeadUpdateRequest,
)
from app.security.auth import APIPrincipal, enforce_tenant_access, require_manager
from app.services.discovery import IdempotencyConflict, execute_discovery

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/leads", tags=["leads"])


@router.post("/discover", status_code=status.HTTP_200_OK)
def discover_leads(
    payload: LeadDiscoverRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Execute customer discovery with organizational quota checking and domain deduplication."""
    # Enforce tenant boundary
    target_org_id = payload.org_id or principal.org_id
    if principal.org_id and payload.org_id and principal.org_id != payload.org_id:
        enforce_tenant_access(principal, payload.org_id)

    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="X-Correlation-ID is too long",
        )

    provider = LiveEnrichmentLeadSource() if payload.live_source else OfflineSignalProvider()


    try:
        return execute_discovery(
            db=db,
            objective=payload.objective,
            limit=payload.limit,
            idempotency_key=payload.idempotency_key,
            correlation_id=correlation_id,
            agent_id=principal.subject,
            org_id=payload.org_id,
            provider=provider,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        error_msg = str(exc)
        if "quota" in error_msg.lower() or "limit" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=error_msg,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_msg,
        ) from exc


@router.get("", response_model=LeadListResponse)
def list_leads(
    org_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    min_fit: float = Query(default=0.0, ge=0.0, le=1.0),
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> LeadListResponse:
    """List and filter leads with multi-tenant scoping and search."""
    # Scope to principal org if tenant-bound
    effective_org_id = org_id
    if principal.org_id:
        enforce_tenant_access(principal, org_id)
        effective_org_id = principal.org_id

    query = db.query(LeadRecordRow).filter(LeadRecordRow.fit_score >= min_fit)

    if effective_org_id:
        query = query.filter(LeadRecordRow.org_id == effective_org_id)
    if status_filter:
        query = query.filter(LeadRecordRow.status == status_filter)
    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            (LeadRecordRow.company.ilike(search_pattern))
            | (LeadRecordRow.website.ilike(search_pattern))
            | (LeadRecordRow.domain.ilike(search_pattern))
        )

    total = query.count()
    leads = query.order_by(LeadRecordRow.fit_score.desc()).offset(offset).limit(limit).all()

    credits_remaining = None
    if effective_org_id:
        org = db.get(OrganizationRecord, effective_org_id)
        if org:
            credits_remaining = max(0, org.lead_credits_limit - org.lead_credits_used)

    return LeadListResponse(
        count=len(leads),
        total=total,
        leads=[LeadResponse.model_validate(lead) for lead in leads],
        credits_remaining=credits_remaining,
    )


@router.get("/{lead_id}", response_model=LeadResponse)
def get_lead(
    lead_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Retrieve full details of a single lead."""
    lead = db.get(LeadRecordRow, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    if lead.org_id:
        enforce_tenant_access(principal, lead.org_id)
    return LeadResponse.model_validate(lead)


@router.patch("/{lead_id}", response_model=LeadResponse)
def update_lead(
    lead_id: str,
    payload: LeadUpdateRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Update lead status lifecycle, recommended next step, or contact channel."""
    lead = db.get(LeadRecordRow, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    if lead.org_id:
        enforce_tenant_access(principal, lead.org_id)


    if payload.status is not None:
        lead.status = payload.status
    if payload.recommended_next_step is not None:
        lead.recommended_next_step = payload.recommended_next_step
    if payload.public_contact_channel is not None:
        lead.public_contact_channel = payload.public_contact_channel
    if payload.do_not_contact is not None:
        lead.do_not_contact = payload.do_not_contact
        if payload.do_not_contact:
            lead.status = "DO_NOT_CONTACT"

    lead.last_checked = datetime.now(UTC)
    db.add(lead)

    db.add(
        AuditLog(
            task_id=lead.task_id or str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id=principal.subject,
            capability_name="customer_discovery",
            action="update_lead_status",
            input_payload={"lead_id": lead_id, **payload.model_dump(exclude_unset=True)},
            output_payload={"status": lead.status, "do_not_contact": lead.do_not_contact},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(lead)
    return LeadResponse.model_validate(lead)


@router.post("/enrich", status_code=status.HTTP_200_OK)
def enrich_lead(
    payload: LeadEnrichRequest,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Perform real-time web scraping and signal enrichment on a company domain or URL."""
    domain = normalize_domain(payload.website)
    if not domain:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid website or domain URL",
        )

    org: OrganizationRecord | None = None
    if payload.org_id:
        org = db.get(OrganizationRecord, payload.org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization '{payload.org_id}' not found",
            )
        if org.lead_credits_used >= org.lead_credits_limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Lead credits quota exceeded ({org.lead_credits_used}/{org.lead_credits_limit}).",
            )

    # Scrape website metadata
    metadata = fetch_and_enrich_website(payload.website)
    title = str(metadata.get("title") or domain)
    company_name = title.split(" - ")[0].split(" | ")[0].strip() or domain
    emails = metadata.get("emails", [])
    contact = emails[0] if emails else None
    
    signals = []
    if metadata.get("description"):
        signals.append(f"overview: {metadata['description']}")
    for h in metadata.get("headings", [])[:3]:
        signals.append(f"heading: {h}")
    if not signals:
        signals.append(f"live website verified: {domain}")

    # Check if lead already exists in DB for this org
    existing: LeadRecordRow | None = None
    if payload.org_id:
        existing = db.query(LeadRecordRow).filter(
            LeadRecordRow.org_id == payload.org_id,
            LeadRecordRow.domain == domain,
        ).first()

    if existing:
        existing.observed_signals = signals
        if contact:
            existing.public_contact_channel = contact
        existing.last_checked = datetime.now(UTC)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        lead_data = LeadResponse.model_validate(existing)
        is_new = False
    else:
        # Create new lead and deduct 1 credit if org is attached
        lead_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        new_lead = LeadRecordRow(
            id=lead_id,
            org_id=payload.org_id,
            domain=domain,
            task_id=task_id,
            company=company_name,
            website=payload.website,
            industry="Technology & Services",
            geography="Global",
            observed_signals=signals,
            sources=[{"url": payload.website, "metadata": metadata, "data_mode": "live_enrichment"}],
            product_match=None,
            fit_score=0.75,
            confidence=0.8,
            public_contact_channel=contact,
            recommended_next_step="owner_review_required_before_contact",
            do_not_contact=False,
            status="QUALIFIED",
            last_checked=datetime.now(UTC),
        )
        db.add(new_lead)
        if org:
            org.lead_credits_used += 1
            db.add(org)
        db.commit()
        db.refresh(new_lead)
        lead_data = LeadResponse.model_validate(new_lead)
        is_new = True

    return {
        "status": "COMPLETED",
        "is_new": is_new,
        "domain": domain,
        "metadata": metadata,
        "lead": lead_data.model_dump(),
        "credits_remaining": (org.lead_credits_limit - org.lead_credits_used) if org else None,
    }


@router.delete("/{lead_id}", status_code=status.HTTP_200_OK)
def delete_lead(
    lead_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Delete a lead record."""
    lead = db.get(LeadRecordRow, lead_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    db.delete(lead)
    db.commit()
    return {"deleted": True, "lead_id": lead_id}
