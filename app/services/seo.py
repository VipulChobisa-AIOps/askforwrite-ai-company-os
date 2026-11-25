"""SEO Content Automation Copilot integration."""

import hashlib
import json
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AuditLog, IdempotencyRecord, SeoDraftRecord, TaskRecord
from app.security.trust_chain import seal_task_to_block
from app.services.approvals import request_approval

CAPABILITY_NAME = "seo_blog_copilot"


class SeoConflict(Exception):
    """Raised when an SEO draft fails uniqueness or idempotency constraints."""


def execute_seo_draft(
    db: Session,
    target_network: str,
    keywords: list[str],
    idempotency_key: str,
    correlation_id: str,
    agent_id: str,
    org_id: str | None = None,
    require_live_llm: bool = False,
) -> dict:
    request_hash = hashlib.sha256(json.dumps({"network": target_network, "keywords": keywords}, sort_keys=True).encode()).hexdigest()

    existing = db.query(IdempotencyRecord).filter_by(
        capability_name=CAPABILITY_NAME,
        idempotency_key=idempotency_key,
    ).first()

    if existing:
        if existing.request_hash != request_hash:
            raise SeoConflict("Idempotency key reused with different request payload")
        return existing.response_payload

    # Draft content using LLM with structured SEO/GEO prompt (fail-closed in prod shifts if live LLM unavailable)
    from app.agents.llm_client import generate, get_last_llm_usage, reset_last_llm_usage

    kw_list = [k.strip() for k in keywords if k and k.strip()] or [target_network, "Enterprise AI Automation"]
    primary_kw = kw_list[0]
    secondary_kws = ", ".join(kw_list[1:]) if len(kw_list) > 1 else "Autonomous Operations, GEO Optimization, Cryptographic Trust"
    schema_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": f"{primary_kw}: Authoritative Implementation & ROI Blueprint ({target_network})",
            "keywords": ", ".join(kw_list),
            "publisher": {"@type": "Organization", "name": target_network},
        }
    )
    fallback = (
        f"# {primary_kw}: Strategic Architecture & Implementation Guide for {target_network}\n\n"
        f"**Executive Summary (GEO Citation Block):** Organizations deploying **{primary_kw}** alongside "
        f"{secondary_kws} achieve measurable operational velocity, deterministic quality governance, and "
        f"verifiable audit compliance across {target_network}.\n\n"
        f"## 1. Core Operational Imperatives for {primary_kw}\n"
        f"Modern enterprise teams face structural bottlenecks when scaling {', '.join(kw_list)} manually. "
        f"By combining human-in-the-loop (HITL) governance with deterministic execution pipelines on {target_network}, "
        f"teams eliminate unverified outputs and establish repeatable organic growth.\n\n"
        f"## 2. Key Technical Pillars & Entity Alignment\n"
        + "\n".join(
            f"- **{kw}**: Production-grade workflow integration with real-time telemetry and Schema.org entity grounding."
            for kw in kw_list
        )
        + "\n\n"
        f"## 3. Frequently Asked Questions (AIO / Answer Engine Ready)\n"
        f"**Q: How does {target_network} validate {primary_kw} performance?**\n"
        f"A: Every publication and workflow transition is gated by owner approval and sealed into an immutable NIST P-256 cryptographic ledger.\n\n"
        f"**Q: What are the primary keywords targeted in this cluster?**\n"
        f"A: This topical authority cluster targets {', '.join(kw_list)} with structured semantic headings.\n\n"
        f"```json\n{schema_ld}\n```"
    )
    prompt = (
        f"Write an authoritative, original, practical 1,200+ word SEO and GEO (Generative Engine Optimization) "
        f"article for '{target_network}' targeting primary keyword '{primary_kw}' and secondary keywords: "
        f"{secondary_kws}. Format cleanly with a single H1 title (# Title), concise executive summary, "
        f"4-5 actionable H2 sections with concrete architecture/implementation guidance and bullet checklists, "
        f"a 3-question FAQ section, and a valid Schema.org Article JSON-LD block. Avoid generic fluff or "
        f"unverified ranking/ROI guarantees."
    )
    reset_last_llm_usage()
    content_draft = generate(prompt, max_output_tokens=3072, fallback_text=fallback)
    llm_usage = get_last_llm_usage() or {}
    used_fallback = bool(llm_usage.get("used_fallback", content_draft == fallback))

    if require_live_llm and used_fallback:
        raise ValueError(
            f"Live LLM generation unavailable for '{target_network}'; skipped staging fallback boilerplate draft."
        )

    task_id = str(uuid.uuid4())
    task = TaskRecord(
        id=task_id,
        correlation_id=correlation_id,
        objective=f"SEO Draft for {target_network}",
        status="COMPLETED",
    )
    db.add(task)

    draft = SeoDraftRecord(
        org_id=org_id,
        task_id=task_id,
        target_network=target_network,
        keywords=keywords,
        content=content_draft,
        status="DRAFT"
    )
    db.add(draft)
    db.flush()  # flush to get draft.id

    # Request Owner Approval for LIVE_PUBLISHED (atomic with draft update)
    approval_detail: dict = {
        "seo_draft_id": draft.id,
        "network": target_network,
        "used_fallback": used_fallback,
        "word_count": len(content_draft.split()),
    }
    if org_id:
        approval_detail["org_id"] = org_id
    approval = request_approval(
        db=db,
        task_id=task_id,
        lead_id=None,
        action="live_publishing",
        detail=approval_detail,
        idempotency_key=f"approval_seo_{draft.id}",
        requested_by=agent_id,
        correlation_id=correlation_id,
        commit=False,
    )

    draft.approval_id = approval["approval_id"]
    draft.status = "PENDING_APPROVAL"

    audit = AuditLog(
        task_id=task_id,
        correlation_id=correlation_id,
        agent_id=agent_id,
        capability_name=CAPABILITY_NAME,
        action="generate_draft",
        input_payload={"network": target_network, "keywords": keywords},
        output_payload={"status": draft.status, "approval_id": approval["approval_id"]},
        status="COMPLETED"
    )
    db.add(audit)

    result = {
        "status": draft.status,
        "draft_id": draft.id,
        "approval_id": approval["approval_id"]
    }

    idemp = IdempotencyRecord(
        capability_name=CAPABILITY_NAME,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        task_id=task_id,
        response_payload=result,
    )
    db.add(idemp)
    
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise SeoConflict("Idempotency conflict") from exc

    seal_task_to_block(
        db=db,
        task_id=task_id,
        capability_name=CAPABILITY_NAME,
        action="generate_draft",
        payload=result,
        sealed_by=agent_id,
    )

    return result
