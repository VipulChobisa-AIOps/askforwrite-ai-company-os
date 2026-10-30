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

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.agents.discovery import normalize_domain
from app.agents.smb_search_source import discover_smb_leads
from app.agents.sources import (
    LiveEnrichmentLeadSource,
    OfflineSignalProvider,
    fetch_and_enrich_website,
    is_safe_public_url,
)
from app.db.database import get_db
from app.db.models import AuditLog, LeadRecordRow, OrganizationRecord, TaskRecord
from app.schemas.lead import (
    LeadDiscoverRequest,
    LeadEnrichRequest,
    LeadListResponse,
    LeadResponse,
    LeadUpdateRequest,
    SmbLeadDiscoverRequest,
)
from app.security.auth import APIPrincipal, enforce_tenant_access, require_manager
from app.security.trust_chain import seal_task_to_block
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
            org_id=target_org_id,
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=error_msg,
        ) from exc


@router.post("/discover-smb", status_code=status.HTTP_200_OK)
def discover_smb_leads_endpoint(
    payload: SmbLeadDiscoverRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Execute high-converting SMB lead discovery across the 8 catalog verticals.

    Persists discovered SMB leads, diagnoses their pain points, recommends the exact catalog SKU,
    logs an AuditLog, and seals a TrustBlock.
    """
    target_org_id = payload.org_id or principal.org_id
    if principal.org_id and payload.org_id and principal.org_id != payload.org_id:
        enforce_tenant_access(principal, payload.org_id)

    correlation_id = x_correlation_id or str(uuid.uuid4())
    if len(correlation_id) > 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="X-Correlation-ID is too long",
        )

    task_id = str(uuid.uuid4())
    discovered_raw = discover_smb_leads(
        vertical=payload.vertical,
        region=payload.region,
        limit=payload.limit,
    )

    persisted_leads: list[dict[str, object]] = []
    for item in discovered_raw:
        domain = item.get("domain") or normalize_domain(item.get("website", ""))
        existing = None
        if target_org_id and domain:
            existing = (
                db.query(LeadRecordRow)
                .filter(
                    LeadRecordRow.org_id == target_org_id,
                    LeadRecordRow.domain == domain,
                )
                .first()
            )
        elif domain:
            existing = (
                db.query(LeadRecordRow)
                .filter(
                    LeadRecordRow.org_id.is_(None),
                    LeadRecordRow.domain == domain,
                )
                .first()
            )

        if existing:
            existing.observed_signals = item.get("observed_signals", [])
            existing.product_match = item.get("recommended_package")
            existing.fit_score = item.get("fit_score", 0.90)
            existing.confidence = item.get("confidence", 0.90)
            existing.last_checked = datetime.now(UTC)
            db.add(existing)
            lead_record_dict = {
                **item,
                "lead_id": existing.id,
                "is_existing": True,
            }
            persisted_leads.append(lead_record_dict)
        else:
            lead_id = str(uuid.uuid4())
            new_lead = LeadRecordRow(
                id=lead_id,
                org_id=target_org_id,
                domain=domain,
                task_id=task_id,
                company=item.get("company", "Candidate SMB"),
                website=item.get("website", f"https://{domain}"),
                industry=item.get("industry", "SMB"),
                geography=item.get("geography", payload.region),
                observed_signals=item.get("observed_signals", []),
                sources=[{"source": s} for s in item.get("sources", ["curated_smb_regional_directory"])],
                product_match=item.get("recommended_package"),
                fit_score=item.get("fit_score", 0.90),
                confidence=item.get("confidence", 0.90),
                public_contact_channel=item.get("public_contact_channel"),
                recommended_next_step="trojan_horse_preview",
                do_not_contact=False,
                status="DISCOVERED",
                last_checked=datetime.now(UTC),
            )
            db.add(new_lead)
            lead_record_dict = {
                **item,
                "lead_id": lead_id,
                "is_existing": False,
            }
            persisted_leads.append(lead_record_dict)

    task_record = TaskRecord(
        id=task_id,
        correlation_id=correlation_id,
        objective=f"SMB Lead Discovery: {payload.vertical} in {payload.region}",
        status="COMPLETED",
        result={
            "vertical": payload.vertical,
            "region": payload.region,
            "leads_count": len(persisted_leads),
        },
    )
    db.add(task_record)

    audit_log = AuditLog(
        task_id=task_id,
        correlation_id=correlation_id,
        agent_id=principal.subject,
        capability_name="smb_lead_discovery",
        action="discover_smb",
        input_payload={
            "vertical": payload.vertical,
            "region": payload.region,
            "limit": payload.limit,
            "org_id": target_org_id,
        },
        output_payload={
            "leads_count": len(persisted_leads),
            "lead_ids": [l["lead_id"] for l in persisted_leads],
            "vertical": payload.vertical,
        },
        status="COMPLETED",
    )
    db.add(audit_log)
    db.flush()

    block = seal_task_to_block(
        db=db,
        task_id=task_id,
        capability_name="smb_lead_discovery",
        action="discover_smb",
        payload={
            "vertical": payload.vertical,
            "region": payload.region,
            "leads_count": len(persisted_leads),
            "correlation_id": correlation_id,
        },
        sealed_by=principal.subject or "smb_search_source",
        commit=True,
    )

    return {
        "status": "COMPLETED",
        "task_id": task_id,
        "correlation_id": correlation_id,
        "vertical": payload.vertical,
        "region": payload.region,
        "leads_count": len(persisted_leads),
        "leads": persisted_leads,
        "block_hash": block.block_hash,
    }


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
    if principal.org_id:
        enforce_tenant_access(principal, lead.org_id or "__platform__")
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
    if principal.org_id:
        enforce_tenant_access(principal, lead.org_id or "__platform__")


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
    """Perform real-time web scraping and signal enrichment on a company domain, URL, or lead record."""
    target_lead: LeadRecordRow | None = None
    target_website: str | None = payload.website

    if not target_website:
        candidate_id = payload.lead_id or (payload.lead_ids[0] if payload.lead_ids else None)
        if candidate_id:
            target_lead = db.get(LeadRecordRow, candidate_id)
            if not target_lead:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Lead '{candidate_id}' not found")
            if principal.org_id:
                enforce_tenant_access(principal, target_lead.org_id or "__platform__")
            target_website = target_lead.website

    if not target_website:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Must provide website, lead_id, or lead_ids to enrich",
        )

    domain = normalize_domain(target_website)
    if not domain or not is_safe_public_url(target_website):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid or unsafe website/domain URL",
        )

    org: OrganizationRecord | None = None
    target_org_id = payload.org_id or principal.org_id or (target_lead.org_id if target_lead else None)
    if target_org_id:
        enforce_tenant_access(principal, target_org_id)
        org = db.get(OrganizationRecord, target_org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization '{target_org_id}' not found",
            )
        if org.lead_credits_used >= org.lead_credits_limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Lead credits quota exceeded ({org.lead_credits_used}/{org.lead_credits_limit}).",
            )

    # Scrape website metadata
    metadata = fetch_and_enrich_website(target_website)
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
    existing: LeadRecordRow | None = target_lead
    if not existing and target_org_id:
        existing = db.query(LeadRecordRow).filter(
            LeadRecordRow.org_id == target_org_id,
            LeadRecordRow.domain == domain,
        ).first()

    if existing:
        existing.observed_signals = signals
        if contact and not existing.public_contact_channel:
            existing.public_contact_channel = contact
        existing.last_checked = datetime.now(UTC)
        db.add(existing)
        if org:
            org.lead_credits_used += 1
            db.add(org)
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
            org_id=target_org_id,
            domain=domain,
            task_id=task_id,
            company=company_name,
            website=target_website,
            industry="Technology & Services",
            geography="Global",
            observed_signals=signals,
            sources=[{"url": target_website, "metadata": metadata, "data_mode": "live_enrichment"}],
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
    if principal.org_id:
        enforce_tenant_access(principal, lead.org_id or "__platform__")
    db.delete(lead)
    db.commit()
    return {"deleted": True, "lead_id": lead_id}
