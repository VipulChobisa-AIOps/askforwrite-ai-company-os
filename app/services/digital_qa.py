"""Digital Asset & Content QA Benchmark Engine and Signed Human-Review Receipts.

Provides configurable brand-voice & anti-slop QA protocols for SEO/content deliverables:
1. Enforces hard fail on canned/fallback boilerplate when require_live_llm=True.
2. Detects AI-slop cliches, forbidden brand terms, missing mandatory terms.
3. Validates SEO/GEO structure (single H1, H2 depth, word count bounds, FAQ section, keyword coverage).
4. Parses and validates Schema.org JSON-LD blocks.
5. Extracts unsupported numeric/superlative claims for mandatory human source verification.
6. Seals every QA report & Human Editorial Sign-Off into the ECDSA NIST P-256 linear hash-chain
   and renders a client-shareable HTML/JSON Verification Certificate.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog, DigitalQAProtocolRecord, DigitalQAReportRecord, TrustBlock
from app.security.ecdsa_pki import verify_signature
from app.security.trust_chain import seal_task_to_block

DEFAULT_BANNED_SLOP_PHRASES: tuple[str, ...] = (
    "in today's fast-paced",
    "in today’s fast-paced",
    "ever-evolving landscape",
    "delve into",
    "rich tapestry",
    "game-changer",
    "unleash the power",
    "navigating the complexities",
    "cutting-edge landscape",
    "holistic synergy",
)

_UNSUPPORTED_SUPERLATIVE_RE = re.compile(
    r"\b(#1\s+(?:google\s+)?ranking|guaranteed\s+(?:roi|traffic|rankings?|revenue)|100%\s+guaranteed|best\s+in\s+the\s+world|proven\s+to\s+(?:double|triple|10x))\b",
    re.IGNORECASE,
)
_NUMERIC_CLAIM_RE = re.compile(
    r"(?:₹\s?[\d,]+(?:\.\d+)?|\$\s?[\d,]+(?:\.\d+)?|\b\d+(?:\.\d+)?%|\b\d+(?:\.\d+)?x\b)",
    re.IGNORECASE,
)
_MD_LINK_RE = re.compile(r"\[[^\]]+\]\(https?://[^\s)]+\)|https?://\S+", re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_LD_SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>\s*(\{.*?\})\s*</script>',
    re.DOTALL | re.IGNORECASE,
)


def create_qa_protocol(
    db: Session,
    *,
    org_id: str | None,
    name: str,
    min_score: int = 80,
    min_word_count: int = 600,
    max_word_count: int = 4500,
    require_schema_ld: bool = True,
    require_faq: bool = True,
    require_live_llm: bool = True,
    brand_voice: str = "authoritative, truthful, non-promotional",
    mandatory_terms: list[str] | None = None,
    forbidden_terms: list[str] | None = None,
    banned_slop_phrases: list[str] | None = None,
    is_default: bool = True,
) -> DigitalQAProtocolRecord:
    """Create and persist a configurable Digital QA Benchmark protocol for an organization."""
    if is_default and org_id:
        db.query(DigitalQAProtocolRecord).filter(
            DigitalQAProtocolRecord.org_id == org_id,
            DigitalQAProtocolRecord.is_default.is_(True),
        ).update({"is_default": False})

    rec = DigitalQAProtocolRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=name.strip(),
        min_score=max(50, min(100, int(min_score))),
        min_word_count=max(100, int(min_word_count)),
        max_word_count=max(500, int(max_word_count)),
        require_schema_ld=bool(require_schema_ld),
        require_faq=bool(require_faq),
        require_live_llm=bool(require_live_llm),
        brand_voice=brand_voice.strip() or "authoritative, truthful, non-promotional",
        mandatory_terms_json=[t.strip() for t in (mandatory_terms or []) if t and t.strip()],
        forbidden_terms_json=[t.strip() for t in (forbidden_terms or []) if t and t.strip()],
        banned_slop_phrases_json=[p.strip() for p in (banned_slop_phrases or []) if p and p.strip()],
        is_default=bool(is_default),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def get_effective_qa_protocol(
    db: Session,
    *,
    org_id: str | None,
    protocol_id: str | None = None,
) -> dict[str, Any]:
    """Resolve explicit protocol_id -> org default protocol -> standard AskforWrite Anti-Slop baseline."""
    rec: DigitalQAProtocolRecord | None = None
    if protocol_id:
        rec = db.get(DigitalQAProtocolRecord, protocol_id)
        if rec and org_id and rec.org_id and rec.org_id != org_id:
            rec = None
    if rec is None and org_id:
        rec = (
            db.query(DigitalQAProtocolRecord)
            .filter(
                DigitalQAProtocolRecord.org_id == org_id,
                DigitalQAProtocolRecord.is_default.is_(True),
            )
            .order_by(DigitalQAProtocolRecord.updated_at.desc())
            .first()
        )
    if rec is not None:
        return {
            "protocol_id": rec.id,
            "name": rec.name,
            "min_score": rec.min_score,
            "min_word_count": rec.min_word_count,
            "max_word_count": rec.max_word_count,
            "require_schema_ld": rec.require_schema_ld,
            "require_faq": rec.require_faq,
            "require_live_llm": rec.require_live_llm,
            "brand_voice": rec.brand_voice,
            "mandatory_terms": list(rec.mandatory_terms_json or []),
            "forbidden_terms": list(rec.forbidden_terms_json or []),
            "banned_slop_phrases": list(dict.fromkeys(list(DEFAULT_BANNED_SLOP_PHRASES) + list(rec.banned_slop_phrases_json or []))),
        }

    return {
        "protocol_id": None,
        "name": "AskforWrite Standard Anti-Slop SEO/GEO Protocol v1",
        "min_score": 80,
        "min_word_count": 600,
        "max_word_count": 4500,
        "require_schema_ld": True,
        "require_faq": True,
        "require_live_llm": True,
        "brand_voice": "authoritative, truthful, non-promotional",
        "mandatory_terms": [],
        "forbidden_terms": [],
        "banned_slop_phrases": list(DEFAULT_BANNED_SLOP_PHRASES),
    }


def _extract_valid_json_ld(content: str) -> tuple[bool, list[str], str | None]:
    """Extract and parse JSON-LD blocks from markdown fences or HTML script tags."""
    candidates = _JSON_FENCE_RE.findall(content) + _LD_SCRIPT_RE.findall(content)
    if not candidates:
        return False, [], "No Schema.org JSON-LD block found"

    found_types: list[str] = []
    for raw in candidates:
        try:
            parsed = json.loads(raw)
        except Exception as exc:
            return False, [], f"Invalid JSON-LD syntax: {exc}"
        ctx = str(parsed.get("@context") or "").lower()
        if "schema.org" not in ctx:
            continue
        if "@type" in parsed:
            found_types.append(str(parsed["@type"]))
        elif "@graph" in parsed and isinstance(parsed["@graph"], list):
            for node in parsed["@graph"]:
                if isinstance(node, dict) and node.get("@type"):
                    found_types.append(str(node["@type"]))

    if not found_types:
        return False, [], "JSON block found but missing valid schema.org @context / @type"
    return True, found_types, None


def _extract_flagged_claims(content: str) -> list[dict[str, Any]]:
    """Identify numeric/financial claims and unsupported superlatives lacking inline citations."""
    # Strip JSON-LD fences before scanning prose sentences
    prose = _JSON_FENCE_RE.sub("", content)
    prose = _LD_SCRIPT_RE.sub("", prose)
    sentences = re.split(r"(?<=[.!?])\s+|\n+", prose)
    flagged: list[dict[str, Any]] = []

    for sent in sentences:
        clean = sent.strip()
        if not clean or clean.startswith("#"):
            continue
        has_source = bool(_MD_LINK_RE.search(clean))
        sup_match = _UNSUPPORTED_SUPERLATIVE_RE.search(clean)
        if sup_match:
            flagged.append({
                "severity": "HIGH",
                "type": "UNSUPPORTED_SUPERLATIVE_OR_GUARANTEE",
                "matched": sup_match.group(0),
                "sentence": clean[:240],
                "status": "REQUIRES_REMOVAL_OR_PROOF",
            })
            continue
        num_match = _NUMERIC_CLAIM_RE.search(clean)
        if num_match and not has_source:
            flagged.append({
                "severity": "MEDIUM",
                "type": "UNSOURCED_NUMERIC_CLAIM",
                "matched": num_match.group(0),
                "sentence": clean[:240],
                "status": "REQUIRES_HUMAN_SOURCE_CHECK",
            })
    return flagged[:25]


def evaluate_digital_qa(
    *,
    content: str,
    title: str = "",
    keywords: list[str] | None = None,
    protocol: dict[str, Any],
    used_fallback: bool = False,
) -> dict[str, Any]:
    """Deterministically evaluate a digital article/deliverable against a QA protocol."""
    text = (content or "").strip()
    text_lower = text.lower()
    prose_only = _JSON_FENCE_RE.sub("", text)
    words = re.findall(r"\b\w+\b", prose_only)
    word_count = len(words)

    score = 100
    defects: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}
    hard_fail = False

    # 1. Live LLM Anti-Slop Origin Gate
    if protocol.get("require_live_llm", True) and used_fallback:
        hard_fail = True
        score -= 40
        defects.append({
            "code": "FALLBACK_BOILERPLATE_BLOCKED",
            "severity": "CRITICAL",
            "message": "Draft was generated via deterministic fallback boilerplate instead of a live LLM.",
        })
    checks["live_llm_origin"] = {"passed": not (protocol.get("require_live_llm", True) and used_fallback), "used_fallback": used_fallback}

    # 2. Banned AI-Slop Cliché Scan
    slop_hits = [p for p in protocol.get("banned_slop_phrases", DEFAULT_BANNED_SLOP_PHRASES) if p.lower() in text_lower]
    if slop_hits:
        penalty = min(30, len(slop_hits) * 8)
        score -= penalty
        defects.append({
            "code": "AI_SLOP_PHRASES_DETECTED",
            "severity": "HIGH" if len(slop_hits) >= 2 else "MEDIUM",
            "message": f"Detected AI-slop cliche phrases: {', '.join(slop_hits[:5])}",
            "matches": slop_hits,
        })
    checks["anti_slop_lexicon"] = {"passed": len(slop_hits) == 0, "matches": slop_hits}

    # 3. Brand Protocol: Mandatory & Forbidden Terms
    mandatory = [t for t in protocol.get("mandatory_terms", []) if t]
    missing_mandatory = [t for t in mandatory if t.lower() not in text_lower]
    if missing_mandatory:
        score -= min(20, len(missing_mandatory) * 7)
        defects.append({
            "code": "MISSING_MANDATORY_BRAND_TERMS",
            "severity": "MEDIUM",
            "message": f"Missing mandatory brand terms: {', '.join(missing_mandatory)}",
            "missing": missing_mandatory,
        })

    forbidden = [t for t in protocol.get("forbidden_terms", []) if t]
    forbidden_hits = [t for t in forbidden if t.lower() in text_lower]
    if forbidden_hits:
        hard_fail = True
        score -= min(30, len(forbidden_hits) * 15)
        defects.append({
            "code": "FORBIDDEN_BRAND_TERM_VIOLATION",
            "severity": "CRITICAL",
            "message": f"Contains forbidden brand/competitor terms: {', '.join(forbidden_hits)}",
            "matches": forbidden_hits,
        })
    checks["brand_terminology"] = {
        "passed": not missing_mandatory and not forbidden_hits,
        "missing_mandatory": missing_mandatory,
        "forbidden_hits": forbidden_hits,
    }

    # 4. Structural SEO / GEO Hierarchy & Word Count
    h1_matches = re.findall(r"(?m)^#\s+.+$", text)
    h2_matches = re.findall(r"(?m)^##\s+.+$", text)
    min_w = int(protocol.get("min_word_count", 600))
    max_w = int(protocol.get("max_word_count", 4500))

    if len(h1_matches) != 1:
        score -= 10
        defects.append({
            "code": "H1_STRUCTURE_INVALID",
            "severity": "MEDIUM",
            "message": f"Expected exactly 1 H1 heading, found {len(h1_matches)}.",
        })
    if len(h2_matches) < 3:
        score -= 10
        defects.append({
            "code": "INSUFFICIENT_H2_DEPTH",
            "severity": "MEDIUM",
            "message": f"Expected at least 3 H2 sections for GEO topical depth, found {len(h2_matches)}.",
        })
    if word_count < min_w:
        score -= 15
        defects.append({
            "code": "WORD_COUNT_BELOW_BENCHMARK",
            "severity": "HIGH",
            "message": f"Word count ({word_count}) is below protocol minimum ({min_w}).",
        })
    elif word_count > max_w:
        score -= 5
        defects.append({
            "code": "WORD_COUNT_ABOVE_BENCHMARK",
            "severity": "LOW",
            "message": f"Word count ({word_count}) exceeds protocol maximum ({max_w}).",
        })

    checks["seo_structure"] = {
        "passed": len(h1_matches) == 1 and len(h2_matches) >= 3 and min_w <= word_count <= max_w,
        "h1_count": len(h1_matches),
        "h2_count": len(h2_matches),
        "word_count": word_count,
        "target_range": [min_w, max_w],
    }

    # 5. Keyword Coverage
    kw_list = [k.strip() for k in (keywords or []) if k and k.strip()]
    kw_hits = [k for k in kw_list if k.lower() in text_lower]
    kw_missing = [k for k in kw_list if k.lower() not in text_lower]
    if kw_list and not kw_hits:
        score -= 10
        defects.append({
            "code": "PRIMARY_KEYWORDS_MISSING",
            "severity": "MEDIUM",
            "message": f"None of the target keywords appeared in content: {', '.join(kw_list)}",
        })
    checks["keyword_coverage"] = {
        "passed": len(kw_missing) == 0 if kw_list else True,
        "covered": kw_hits,
        "missing": kw_missing,
    }

    # 6. FAQ / AI Answer Engine Block
    has_faq = bool(re.search(r"(?i)(frequently asked questions|\bfaq\b|\*\*q:)", text))
    if protocol.get("require_faq", True) and not has_faq:
        score -= 10
        defects.append({
            "code": "MISSING_FAQ_AIO_BLOCK",
            "severity": "MEDIUM",
            "message": "Missing FAQ / direct-answer block required for AI Search (GEO/AIO) citation readiness.",
        })
    checks["aio_faq_block"] = {"passed": (not protocol.get("require_faq", True)) or has_faq, "present": has_faq}

    # 7. Schema.org JSON-LD Validation
    schema_ok, schema_types, schema_err = _extract_valid_json_ld(text)
    if protocol.get("require_schema_ld", True) and not schema_ok:
        score -= 15
        defects.append({
            "code": "INVALID_OR_MISSING_SCHEMA_LD",
            "severity": "HIGH",
            "message": schema_err or "Valid Schema.org JSON-LD markup is required by protocol.",
        })
    checks["schema_json_ld"] = {
        "passed": (not protocol.get("require_schema_ld", True)) or schema_ok,
        "types": schema_types,
        "error": schema_err,
    }

    # 8. Factual Claim & Superlative Hygiene
    flagged_claims = _extract_flagged_claims(text)
    high_claims = [c for c in flagged_claims if c["severity"] == "HIGH"]
    if high_claims:
        hard_fail = True
        score -= min(25, len(high_claims) * 12)
        defects.append({
            "code": "UNSUPPORTED_GUARANTEE_OR_SUPERLATIVE",
            "severity": "CRITICAL",
            "message": f"Found {len(high_claims)} unsupported ranking/ROI guarantee or superlative claim(s) that must be removed.",
        })
    checks["claim_hygiene"] = {
        "passed": len(high_claims) == 0,
        "critical_superlatives": len(high_claims),
        "claims_needing_human_citation": len([c for c in flagged_claims if c["severity"] == "MEDIUM"]),
    }

    final_score = max(0, min(100, int(score)))
    min_score = int(protocol.get("min_score", 80))
    passed = (not hard_fail) and (final_score >= min_score)

    inferred_title = title.strip() or (h1_matches[0].lstrip("#").strip() if h1_matches else "Untitled Digital Deliverable")
    return {
        "title": inferred_title[:300],
        "overall_score": final_score,
        "min_score_required": min_score,
        "passed": passed,
        "hard_fail": hard_fail,
        "protocol_name": protocol.get("name"),
        "protocol_id": protocol.get("protocol_id"),
        "checks": checks,
        "defects": defects,
        "flagged_claims": flagged_claims,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def evaluate_and_record_digital_qa(
    db: Session,
    *,
    org_id: str | None,
    content: str,
    title: str = "",
    keywords: list[str] | None = None,
    target_url: str | None = None,
    draft_id: str | None = None,
    task_id: str | None = None,
    protocol_id: str | None = None,
    used_fallback: bool = False,
    output_origin: str | None = None,
    actor: str = "digital_qa_agent",
    commit: bool = True,
) -> dict[str, Any]:
    """Run Digital QA evaluation, persist DigitalQAReportRecord, and seal into ECDSA linear hash-chain."""
    protocol = get_effective_qa_protocol(db, org_id=org_id, protocol_id=protocol_id)
    result = evaluate_digital_qa(
        content=content,
        title=title,
        keywords=keywords,
        protocol=protocol,
        used_fallback=used_fallback,
    )

    origin = output_origin or ("SIMULATED_SYNTHETIC" if used_fallback else "LIVE_PROVIDER_VERIFIED")
    receipt_id = f"QA-{uuid.uuid4().hex[:12].upper()}"
    report_id = str(uuid.uuid4())
    effective_task_id = task_id or report_id

    block = seal_task_to_block(
        db=db,
        task_id=effective_task_id,
        capability_name="digital_qa_benchmark",
        action="digital_qa_evaluated",
        payload={
            "receipt_id": receipt_id,
            "org_id": org_id,
            "draft_id": draft_id,
            "title": result["title"],
            "content_sha256": result["content_sha256"],
            "overall_score": result["overall_score"],
            "passed": result["passed"],
            "output_origin": origin,
            "protocol_name": protocol["name"],
        },
        sealed_by=actor,
        commit=False,
    )

    rec = DigitalQAReportRecord(
        id=report_id,
        receipt_id=receipt_id,
        org_id=org_id,
        protocol_id=protocol.get("protocol_id"),
        draft_id=draft_id,
        task_id=effective_task_id,
        title=result["title"],
        target_url=target_url,
        content_sha256=result["content_sha256"],
        overall_score=result["overall_score"],
        passed=result["passed"],
        output_origin=origin,
        checks_json=result["checks"],
        defects_json=result["defects"],
        flagged_claims_json=result["flagged_claims"],
        trust_block_index=block.index,
        trust_block_hash=block.block_hash,
        trust_signature=block.signature,
    )
    db.add(rec)
    db.add(
        AuditLog(
            task_id=effective_task_id[:36],
            correlation_id=str(uuid.uuid4()),
            agent_id=actor,
            capability_name="digital_qa_benchmark",
            action="digital_qa_evaluated",
            input_payload={"draft_id": draft_id, "protocol_id": protocol.get("protocol_id"), "org_id": org_id},
            output_payload={"receipt_id": receipt_id, "overall_score": result["overall_score"], "passed": result["passed"]},
            status="COMPLETED" if result["passed"] else "FLAGGED",
        )
    )
    if commit:
        db.commit()
        db.refresh(rec)
    else:
        db.flush()

    return serialize_qa_report(rec)


def sign_off_digital_qa_receipt(
    db: Session,
    *,
    receipt_id: str,
    reviewer: str,
    review_notes: str = "",
    target_url: str | None = None,
    org_id: str | None = None,
) -> dict[str, Any]:
    """Attach human editorial review sign-off to a Digital QA report and seal a final ECDSA receipt block."""
    rec = db.query(DigitalQAReportRecord).filter_by(receipt_id=receipt_id.strip()).first()
    if not rec:
        raise ValueError(f"Digital QA receipt '{receipt_id}' not found")
    if org_id and rec.org_id and rec.org_id != org_id:
        raise PermissionError("Digital QA receipt belongs to another organization")
    if not rec.passed:
        raise ValueError(
            f"Cannot issue human-review sign-off for failed Digital QA report '{receipt_id}' (score={rec.overall_score}). Resolve defects and re-evaluate first."
        )

    now = datetime.now(UTC)
    rec.human_reviewer = reviewer.strip()
    rec.human_reviewed_at = now
    rec.review_notes = review_notes.strip() or "Human editorial & factual verification completed."
    if target_url:
        rec.target_url = target_url.strip()

    block = seal_task_to_block(
        db=db,
        task_id=rec.task_id or rec.id,
        capability_name="digital_qa_benchmark",
        action="digital_qa_human_review_signed",
        payload={
            "receipt_id": rec.receipt_id,
            "content_sha256": rec.content_sha256,
            "overall_score": rec.overall_score,
            "output_origin": rec.output_origin,
            "human_reviewer": rec.human_reviewer,
            "human_reviewed_at": now.isoformat(),
            "review_notes": rec.review_notes,
            "target_url": rec.target_url,
        },
        sealed_by=f"HUMAN-REVIEWER:{rec.human_reviewer}",
        commit=False,
    )
    rec.trust_block_index = block.index
    rec.trust_block_hash = block.block_hash
    rec.trust_signature = block.signature
    db.commit()
    db.refresh(rec)
    return serialize_qa_report(rec)


def verify_qa_receipt(db: Session, receipt_id: str) -> dict[str, Any] | None:
    """Publicly verify a Digital QA receipt against the ECDSA NIST P-256 linear hash-chain."""
    rec = db.query(DigitalQAReportRecord).filter_by(receipt_id=receipt_id.strip()).first()
    if not rec:
        return None
    block = (
        db.query(TrustBlock).filter_by(index=rec.trust_block_index).first()
        if rec.trust_block_index is not None
        else None
    )
    sig_valid = False
    hash_match = False
    if block and rec.trust_block_hash and rec.trust_signature:
        hash_match = block.block_hash == rec.trust_block_hash
        sig_valid = bool(verify_signature(block.public_key, block.block_hash, block.signature))

    data = serialize_qa_report(rec)
    data["cryptographic_verification"] = {
        "ledger_type": "ECDSA NIST P-256 SHA-256 Linear Hash-Chain",
        "block_found": block is not None,
        "block_index": rec.trust_block_index,
        "block_hash_matches": hash_match,
        "ecdsa_signature_valid": sig_valid,
        "verified": bool(block is not None and hash_match and sig_valid),
    }
    return data


def serialize_qa_report(rec: DigitalQAReportRecord) -> dict[str, Any]:
    return {
        "id": rec.id,
        "receipt_id": rec.receipt_id,
        "org_id": rec.org_id,
        "protocol_id": rec.protocol_id,
        "draft_id": rec.draft_id,
        "task_id": rec.task_id,
        "title": rec.title,
        "target_url": rec.target_url,
        "content_sha256": rec.content_sha256,
        "overall_score": rec.overall_score,
        "passed": rec.passed,
        "output_origin": rec.output_origin,
        "checks": rec.checks_json or {},
        "defects": rec.defects_json or [],
        "flagged_claims": rec.flagged_claims_json or [],
        "human_reviewer": rec.human_reviewer,
        "human_reviewed_at": rec.human_reviewed_at.isoformat() if rec.human_reviewed_at else None,
        "review_notes": rec.review_notes,
        "trust_block_index": rec.trust_block_index,
        "trust_block_hash": rec.trust_block_hash,
        "trust_signature": rec.trust_signature,
        "receipt_url": f"/v1/digital-qa/receipts/{rec.receipt_id}",
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def render_qa_receipt_html(verified_receipt: dict[str, Any]) -> str:
    """Render a clean, client-shareable printable HTML Human-Review & Digital QA Verification Receipt."""
    rid = html.escape(str(verified_receipt.get("receipt_id") or ""))
    title = html.escape(str(verified_receipt.get("title") or ""))
    score = int(verified_receipt.get("overall_score") or 0)
    passed = bool(verified_receipt.get("passed"))
    origin = html.escape(str(verified_receipt.get("output_origin") or ""))
    sha = html.escape(str(verified_receipt.get("content_sha256") or ""))
    reviewer = html.escape(str(verified_receipt.get("human_reviewer") or "Pending Human Editor Sign-Off"))
    reviewed_at = html.escape(str(verified_receipt.get("human_reviewed_at") or "—"))
    notes = html.escape(str(verified_receipt.get("review_notes") or "—"))
    crypto = verified_receipt.get("cryptographic_verification") or {}
    crypto_ok = bool(crypto.get("verified"))
    block_idx = crypto.get("block_index")
    block_hash = html.escape(str(verified_receipt.get("trust_block_hash") or ""))
    badge_bg = "#16a34a" if (passed and crypto_ok) else "#dc2626"
    badge_label = "VERIFIED HUMAN-REVIEWED DELIVERABLE" if (passed and verified_receipt.get("human_reviewer") and crypto_ok) else ("QA PASSED — PENDING HUMAN SIGN-OFF" if passed else "QA FAILED")

    checks_rows = []
    for k, v in (verified_receipt.get("checks") or {}).items():
        ok = bool(v.get("passed")) if isinstance(v, dict) else bool(v)
        checks_rows.append(
            f"<tr><td>{html.escape(k.replace('_', ' ').title())}</td>"
            f"<td style='font-weight:700;color:{'#16a34a' if ok else '#dc2626'}'>{'PASS' if ok else 'FAIL'}</td></tr>"
        )
    checks_html = "\n".join(checks_rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Digital QA Verification Receipt — {rid} | AskforWrite</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; background:#0f172a; color:#e2e8f0; margin:0; padding:32px 16px; }}
    .card {{ max-width:760px; margin:0 auto; background:#1e293b; border:1px solid #334155; border-radius:14px; padding:28px; box-shadow:0 20px 45px rgba(0,0,0,.35); }}
    .badge {{ display:inline-block; background:{badge_bg}; color:#fff; font-size:12px; font-weight:700; letter-spacing:.06em; padding:6px 12px; border-radius:999px; }}
    h1 {{ margin:14px 0 6px; font-size:22px; color:#f8fafc; }}
    .meta {{ color:#94a3b8; font-size:13px; margin-bottom:20px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:18px 0; }}
    .box {{ background:#0f172a; border:1px solid #334155; border-radius:10px; padding:12px; }}
    .box .lbl {{ font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:.05em; }}
    .box .val {{ font-size:18px; font-weight:700; margin-top:4px; color:#38bdf8; }}
    table {{ width:100%; border-collapse:collapse; margin-top:14px; font-size:14px; }}
    th, td {{ text-align:left; padding:10px 8px; border-bottom:1px solid #334155; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; word-break:break-all; color:#cbd5e1; background:#0f172a; padding:10px; border-radius:8px; margin-top:8px; }}
  </style>
</head>
<body>
  <div class="card">
    <span class="badge">{badge_label}</span>
    <h1>{title}</h1>
    <div class="meta">Receipt ID: <strong>{rid}</strong> &bull; Issuer: AskforWrite AI Company OS &bull; Ledger: ECDSA NIST P-256 Linear Hash-Chain</div>
    <div class="grid">
      <div class="box"><div class="lbl">Digital QA Score</div><div class="val">{score} / 100</div></div>
      <div class="box"><div class="lbl">Output Origin</div><div class="val" style="font-size:13px;">{origin}</div></div>
      <div class="box"><div class="lbl">Human Reviewer</div><div class="val" style="font-size:14px;">{reviewer}</div></div>
      <div class="box"><div class="lbl">Chain Verification</div><div class="val" style="color:{'#22c55e' if crypto_ok else '#ef4444'}">{'VALID' if crypto_ok else 'INVALID'} (#{block_idx})</div></div>
    </div>
    <h3>Protocol Benchmark Checks</h3>
    <table><thead><tr><th>Check</th><th>Result</th></tr></thead><tbody>{checks_html}</tbody></table>
    <h3>Human Editorial Review Sign-Off</h3>
    <div class="meta">Reviewed At: {reviewed_at}<br/>Notes: {notes}</div>
    <h3>Cryptographic Proof (SHA-256 Linear Hash-Chain + ECDSA NIST P-256)</h3>
    <div class="mono">Content SHA-256: {sha}<br/>Trust Block Hash: {block_hash}</div>
  </div>
</body>
</html>"""
