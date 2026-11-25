"""WordPress REST Publisher Bridge for SEO Blog Automation Copilot.

Enforces fail-closed Human-in-the-Loop (HITL) publication integrity (Issue #12):
- Requires a valid, persisted, APPROVED ApprovalRequest explicitly bound to the draft and tenant.
- Rejects missing approval_id, missing approval record, unapproved/revoked/rejected status,
  wrong action/gate, mismatched draft/task, or cross-tenant approvals — both via API and direct calls.
- Distinct status model:
    * PUBLISHED      — ONLY after a verified 200/201 WordPress REST response with a valid post ID and URL.
    * SIMULATED      — When WordPress credentials are unset or external side effects are blocked.
    * PUBLISH_FAILED — On HTTP 4xx/5xx, timeout, network/SSRF error, malformed JSON, missing post ID, or missing URL.
- Idempotent retries: replays stored live publication without duplicate POSTs, and reconciles
  existing WordPress posts by deterministic slug/provider ID after ambiguous network failures.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.db.models import ApprovalRequest, AuditLog, SeoDraftRecord
from app.security.trust_chain import seal_task_to_block

logger = logging.getLogger("afw.company_os.wordpress_publisher")

CAPABILITY_NAME = "seo_blog_copilot"

ALLOWED_PUBLISH_APPROVAL_ACTIONS = frozenset(
    {"live_publishing", "wordpress_publish", "seo_publish", "seo_live_publishing"}
)

SUPPORTED_NETWORKS: dict[str, dict[str, Any]] = {
    "askforwrite.in": {
        "name": "AskforWrite Main Authority Platform",
        "base_url": "https://askforwrite.in",
        "category": "ai-technology",
        "description": "Enterprise autonomous agents and AI Company OS publications.",
        "wp_rest_enabled": False,
    },
    "askforwrite.com": {
        "name": "AskforWrite Global Enterprise Hub",
        "base_url": "https://askforwrite.com",
        "category": "enterprise-ai",
        "description": "Global enterprise solutions, multi-tenant AI operations, and cloud gateway.",
        "wp_rest_enabled": True,
    },
    "ask4write.com": {
        "name": "Ask4Write Brand & Commerce Hub",
        "base_url": "https://ask4write.com",
        "category": "ai-solutions",
        "description": "Commercial AI products, automation packs, and brand portal.",
        "wp_rest_enabled": True,
    },
    "askforwrite.info": {
        "name": "AskforWrite Knowledge Base & Tech Docs",
        "base_url": "https://askforwrite.info",
        "category": "tech-documentation",
        "description": "Knowledge base, API reference, research insights, and technical documentation.",
        "wp_rest_enabled": True,
    },
    "shop.ask4write.com": {
        "name": "AskforWrite Digital Storefront",
        "base_url": "https://shop.ask4write.com",
        "category": "ecommerce",
        "description": "Digital products, AI toolkits, instant templates, and service storefront.",
        "wp_rest_enabled": False,
    },
    "node.askforwrite.in": {
        "name": "AskforWrite Node Infrastructure",
        "base_url": "https://node.askforwrite.in",
        "category": "infrastructure",
        "description": "Distributed node infrastructure, real-time endpoints, and edge services.",
        "wp_rest_enabled": False,
    },
}


class WordPressPublishError(RuntimeError):
    """Structured failure raised when a live WordPress REST publication fails or returns unverifiable data."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "wordpress_publish_failed",
        draft_id: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status = "PUBLISH_FAILED"
        self.error_code = error_code
        self.draft_id = draft_id
        self.http_status = http_status


def get_supported_networks() -> dict[str, dict[str, Any]]:
    """Return catalog of supported WordPress publishing networks."""
    return SUPPORTED_NETWORKS


def get_live_wordpress_networks() -> dict[str, dict[str, Any]]:
    """Return only verified live WordPress REST networks (wp_rest_enabled=True)."""
    return {k: v for k, v in SUPPORTED_NETWORKS.items() if v.get("wp_rest_enabled")}


def _network_env_slug(network: str) -> str:
    cleaned = (network or "").strip().lower()
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[-1].split("/", 1)[0]
    return re.sub(r"[^A-Z0-9]+", "_", cleaned.upper()).strip("_")


def resolve_wordpress_target(network: str) -> tuple[str, str, str]:
    """Resolve (site_url, username, app_password) for a target network.

    Checks per-site variables first (WP_SITE_URL_<SLUG>, WP_USERNAME_<SLUG>, WP_APP_PASSWORD_<SLUG>,
    e.g. WP_USERNAME_ASKFORWRITE_COM) and falls back cleanly to global WP_SITE_URL / WP_USERNAME / WP_APP_PASSWORD.
    """
    norm_net = (network or "").strip().lower()
    if "://" in norm_net:
        norm_net = norm_net.split("://", 1)[-1].split("/", 1)[0]
    slug = _network_env_slug(norm_net)

    site_url_specific = os.getenv(f"WP_SITE_URL_{slug}", "").strip() if slug else ""
    user_specific = os.getenv(f"WP_USERNAME_{slug}", "").strip() if slug else ""
    pass_specific = os.getenv(f"WP_APP_PASSWORD_{slug}", "").strip() if slug else ""

    if user_specific and pass_specific:
        default_base = str((SUPPORTED_NETWORKS.get(norm_net) or {}).get("base_url") or "")
        site_url = site_url_specific or default_base or os.getenv("WP_SITE_URL", "").strip() or os.getenv("WP_BASE_URL", "").strip()
        return site_url, user_specific, pass_specific

    wp_site_url = (site_url_specific or os.getenv("WP_SITE_URL") or os.getenv("WP_BASE_URL") or "").strip()
    wp_username = (user_specific or os.getenv("WP_USERNAME") or "").strip()
    wp_app_password = (pass_specific or os.getenv("WP_APP_PASSWORD") or "").strip()
    return wp_site_url, wp_username, wp_app_password


def _inline_markdown_to_html(text: str) -> str:
    """Convert inline Markdown (**bold**, *italic*, `code`, [label](url)) into safe HTML."""
    escaped = html.escape(text, quote=False)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}" rel="noopener noreferrer">{m.group(1)}</a>',
        escaped,
    )
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
    return escaped


def render_wordpress_html(content: str) -> str:
    """Convert Markdown SEO drafts into clean, Gutenberg-ready WordPress HTML.

    - Strips duplicate leading H1 heading (WordPress renders post title as H1).
    - Converts ##/### headings, bullet/numbered lists, paragraphs, and inline emphasis to semantic HTML.
    - Converts fenced ```json Schema.org JSON-LD blocks into valid <script type="application/ld+json"> tags.
    - Passes through pre-rendered HTML documents unchanged.
    """
    raw = (content or "").strip()
    if not raw:
        return ""
    if raw.startswith("<") and any(tag in raw.lower() for tag in ("<p", "<h2", "<h3", "<article", "<section", "<div")):
        return raw

    json_ld_scripts: list[str] = []

    def _extract_json_block(match: re.Match[str]) -> str:
        body = match.group(1).strip()
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and "@context" in parsed and "@type" in parsed:
                safe_json = json.dumps(parsed, ensure_ascii=False).replace("</", "<\\/")
                json_ld_scripts.append(f'<script type="application/ld+json">{safe_json}</script>')
                return ""
        except Exception:
            pass
        return f"<pre><code>{html.escape(body)}</code></pre>"

    stripped = re.sub(r"```(?:json|ld\+json)\s*\n(.*?)```", _extract_json_block, raw, flags=re.DOTALL | re.IGNORECASE)

    out_parts: list[str] = []
    in_ul = False
    in_ol = False
    para_buf: list[str] = []
    h1_skipped = False

    def _flush_para() -> None:
        if para_buf:
            joined = " ".join(para_buf).strip()
            if joined:
                out_parts.append(f"<p>{_inline_markdown_to_html(joined)}</p>")
            para_buf.clear()

    def _close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out_parts.append("</ul>")
            in_ul = False
        if in_ol:
            out_parts.append("</ol>")
            in_ol = False

    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line:
            _flush_para()
            _close_lists()
            continue
        if line.startswith("<pre><code>"):
            _flush_para()
            _close_lists()
            out_parts.append(line)
            continue
        if line.startswith("# ") and not h1_skipped:
            # WordPress already renders the post title as the page H1
            h1_skipped = True
            _flush_para()
            _close_lists()
            continue
        if line.startswith("### "):
            _flush_para()
            _close_lists()
            out_parts.append(f"<h3>{_inline_markdown_to_html(line[4:].strip())}</h3>")
            continue
        if line.startswith("## "):
            _flush_para()
            _close_lists()
            out_parts.append(f"<h2>{_inline_markdown_to_html(line[3:].strip())}</h2>")
            continue
        if line.startswith("# "):
            _flush_para()
            _close_lists()
            out_parts.append(f"<h2>{_inline_markdown_to_html(line[2:].strip())}</h2>")
            continue
        ul_m = re.match(r"^[-*]\s+(.+)$", line)
        if ul_m:
            _flush_para()
            if in_ol:
                out_parts.append("</ol>")
                in_ol = False
            if not in_ul:
                out_parts.append("<ul>")
                in_ul = True
            out_parts.append(f"<li>{_inline_markdown_to_html(ul_m.group(1).strip())}</li>")
            continue
        ol_m = re.match(r"^\d+\.\s+(.+)$", line)
        if ol_m:
            _flush_para()
            if in_ul:
                out_parts.append("</ul>")
                in_ul = False
            if not in_ol:
                out_parts.append("<ol>")
                in_ol = True
            out_parts.append(f"<li>{_inline_markdown_to_html(ol_m.group(1).strip())}</li>")
            continue
        _close_lists()
        para_buf.append(line)

    _flush_para()
    _close_lists()
    out_parts.extend(json_ld_scripts)
    return "\n".join(out_parts)


def _normalize_org(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _validate_verified_post_id(raw_id: Any) -> int | str | None:
    """Return a verified non-boolean post ID (int > 0 or non-empty string), else None."""
    if raw_id is None or isinstance(raw_id, bool):
        return None
    if isinstance(raw_id, int):
        return raw_id if raw_id > 0 else None
    if isinstance(raw_id, str):
        cleaned = raw_id.strip()
        if not cleaned:
            return None
        if cleaned.isdigit():
            val = int(cleaned)
            return val if val > 0 else None
        return cleaned
    return None


def _validate_canonical_url(raw_url: Any) -> str | None:
    """Return a verified HTTP(S) canonical URL with a valid host, else None."""
    if not isinstance(raw_url, str):
        return None
    cleaned = raw_url.strip()
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return cleaned


def _enforce_hitl_approval_fail_closed(
    db: Session,
    draft: SeoDraftRecord,
    *,
    caller_org_id: str | None = None,
) -> ApprovalRequest:
    """Fail-closed HITL verification shared by both the API route and direct service callers."""
    draft_id_str = str(draft.id)
    draft_org = _normalize_org(getattr(draft, "org_id", None))
    caller_org = _normalize_org(caller_org_id)

    if caller_org is not None and draft_org is not None and caller_org != draft_org:
        raise PermissionError(
            f"SEO Draft '{draft_id_str}' belongs to tenant '{draft_org}', not caller tenant '{caller_org}'."
        )
    if caller_org is not None and draft_org is None:
        raise PermissionError(
            f"SEO Draft '{draft_id_str}' is not scoped to caller tenant '{caller_org}'."
        )

    if (draft.status or "").upper() in {"REJECTED", "REVOKED"}:
        raise PermissionError(
            f"SEO Draft '{draft_id_str}' cannot be published because draft status is '{draft.status}'."
        )

    approval_id = (draft.approval_id or "").strip()
    if not approval_id:
        raise PermissionError(
            f"SEO Draft '{draft_id_str}' cannot be published: missing required approval_id. Owner HITL approval is mandatory."
        )

    approval = db.get(ApprovalRequest, approval_id)
    if approval is None:
        raise PermissionError(
            f"SEO Draft '{draft_id_str}' cannot be published: referenced approval '{approval_id}' was not found."
        )

    if (approval.status or "").upper() != "APPROVED":
        raise PermissionError(
            f"Owner approval required: SEO Draft '{draft_id_str}' cannot be published because approval '{approval_id}' status is '{approval.status}' (APPROVED required)."
        )

    detail = approval.detail if isinstance(approval.detail, dict) else {}
    action_norm = (approval.action or "").strip().lower()
    gate_type = str(detail.get("gate_type") or "").strip().lower()
    if action_norm not in ALLOWED_PUBLISH_APPROVAL_ACTIONS and gate_type != "live_publishing":
        raise PermissionError(
            f"SEO Draft '{draft_id_str}' cannot be published: approval '{approval_id}' is for action '{approval.action}', not WordPress publishing."
        )

    # Strict draft binding check: prevent reusing another draft's approval
    detail_draft_id = detail.get("seo_draft_id") or detail.get("draft_id")
    if detail_draft_id is not None:
        if str(detail_draft_id).strip() != draft_id_str:
            raise PermissionError(
                f"SEO Draft '{draft_id_str}' cannot be published: approval '{approval_id}' is bound to draft '{detail_draft_id}'."
            )
    else:
        # When detail does not name a draft ID explicitly, task_id MUST exist and match exactly
        if not approval.task_id or not draft.task_id or str(approval.task_id) != str(draft.task_id):
            raise PermissionError(
                f"SEO Draft '{draft_id_str}' cannot be published: approval '{approval_id}' is not bound to this draft or task."
            )

    # Also enforce task_id agreement whenever both are populated
    if approval.task_id and draft.task_id and str(approval.task_id) != str(draft.task_id):
        raise PermissionError(
            f"SEO Draft '{draft_id_str}' cannot be published: approval '{approval_id}' task '{approval.task_id}' does not match draft task '{draft.task_id}'."
        )

    # Strict tenant binding check: reject any cross-tenant or mismatched tenant approval
    approval_org = _normalize_org(detail.get("org_id"))
    if draft_org != approval_org:
        raise PermissionError(
            f"SEO Draft '{draft_id_str}' cannot be published: cross-tenant approval mismatch "
            f"(draft org='{draft_org}', approval org='{approval_org}')."
        )
    if caller_org is not None and approval_org != caller_org:
        raise PermissionError(
            f"SEO Draft '{draft_id_str}' cannot be published: approval '{approval_id}' does not belong to caller tenant '{caller_org}'."
        )

    return approval


def _record_publish_failure(
    db: Session,
    draft: SeoDraftRecord,
    *,
    approval_id: str,
    network: str,
    title: str,
    slug: str,
    corr_id: str,
    published_by: str,
    idempotency_key: str,
    error_code: str,
    error_message: str,
    http_status: int | None = None,
    response_excerpt: str | None = None,
) -> None:
    """Persist PUBLISH_FAILED state + AuditLog without ever marking the draft PUBLISHED."""
    now = datetime.now(UTC)
    failure_meta: dict[str, Any] = {
        "status": "PUBLISH_FAILED",
        "mode": "WORDPRESS_REST_LIVE",
        "approval_id": approval_id,
        "network": network,
        "slug": slug,
        "idempotency_key": idempotency_key,
        "error_code": error_code,
        "error": error_message,
        "http_status": http_status,
        "failed_at": now.isoformat(),
    }
    if response_excerpt:
        failure_meta["response_excerpt"] = response_excerpt[:400]

    draft.status = "PUBLISH_FAILED"
    draft.decided_at = now
    draft.publish_metadata = failure_meta
    db.add(draft)

    audit = AuditLog(
        task_id=draft.task_id or str(draft.id),
        correlation_id=corr_id,
        agent_id=published_by,
        capability_name=CAPABILITY_NAME,
        action="wordpress_publish",
        input_payload={
            "draft_id": str(draft.id),
            "approval_id": approval_id,
            "network": network,
            "idempotency_key": idempotency_key,
        },
        output_payload=failure_meta,
        status="FAILED",
    )
    db.add(audit)
    db.commit()


def _reconcile_existing_wordpress_post(
    *,
    endpoint: str,
    slug: str,
    stored_post_id: str | None,
    auth: tuple[str, str],
    http_client: Any | None,
) -> tuple[int | str, str, dict[str, Any]] | None:
    """Look up an existing WordPress post by stored provider ID or deterministic slug before POSTing."""
    import httpx

    get_fn = http_client.get if (http_client is not None and hasattr(http_client, "get")) else (
        None if http_client is not None else httpx.get
    )
    if get_fn is None:
        return None

    # 1. Check by stored provider_post_id if available
    if stored_post_id:
        try:
            r = get_fn(f"{endpoint}/{stored_post_id}", auth=auth, timeout=10.0)
            if r.status_code == 200:
                payload = r.json()
                if isinstance(payload, dict):
                    pid = _validate_verified_post_id(payload.get("id"))
                    link = _validate_canonical_url(payload.get("link"))
                    if pid is not None and link is not None:
                        return pid, link, payload
        except Exception:
            pass

    # 2. Reconcile by deterministic slug across any status (prevents duplicates after timeout)
    try:
        r = get_fn(endpoint, auth=auth, params={"slug": slug, "status": "any"}, timeout=10.0)
        if r.status_code == 200:
            items = r.json()
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("slug") or "").strip().lower() == slug.lower():
                        pid = _validate_verified_post_id(item.get("id"))
                        link = _validate_canonical_url(item.get("link"))
                        if pid is not None and link is not None:
                            return pid, link, item
    except Exception:
        pass

    return None


def publish_seo_draft_to_wordpress(
    db: Session,
    draft_id: int | str,
    correlation_id: str | None = None,
    published_by: str = "seo-wordpress-publisher",
    http_client: Any | None = None,
    caller_org_id: str | None = None,
) -> dict[str, Any]:
    """Publish an approved SeoDraftRecord to WordPress with fail-closed HITL and verified delivery.

    Statuses returned & persisted on SeoDraftRecord:
    - PUBLISHED: Verified 200/201 WordPress REST live response with valid post ID and canonical URL
                 (or idempotent replay / reconciliation of an already-published live post).
    - SIMULATED: Live credentials unset or external side effects blocked by execution guard.
                 Never marked as PUBLISHED and never assigned a live provider_post_id.
    - PUBLISH_FAILED: Persisted on HTTP 4xx/5xx, timeout, network error, malformed JSON, missing ID,
                      or missing canonical URL, and raises WordPressPublishError.
    """
    draft = db.query(SeoDraftRecord).filter_by(id=str(draft_id)).first()
    if not draft:
        raise ValueError(f"SeoDraftRecord '{draft_id}' not found")

    # 1. Fail-closed HITL & tenant verification (enforced identically for API & direct calls)
    approval = _enforce_hitl_approval_fail_closed(db, draft, caller_org_id=caller_org_id)

    network = (draft.target_network or "askforwrite.in").strip().lower()
    if "://" in network:
        network = network.split("://")[-1].split("/")[0]

    # Extract title & deterministic slug (include short draft hash suffix to avoid cross-draft slug collisions)
    title = None
    if draft.content:
        for line in draft.content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped.lstrip("# ").strip()
                break
    if not title:
        keywords_str = ", ".join(draft.keywords) if draft.keywords else "AI Operations"
        title = f"Autonomous Operational Guide: {keywords_str}"

    base_slug = re.sub(r"[^\w\s-]", "", title.lower()).strip()
    base_slug = re.sub(r"[\s_-]+", "-", base_slug)[:48].strip("-") or "article"
    draft_tag = hashlib.sha256(str(draft.id).encode()).hexdigest()[:8]
    slug = f"{base_slug}-{draft_tag}"

    corr_id = correlation_id or str(uuid.uuid4())
    wp_idemp_key = hashlib.sha256(
        f"wp-publish:{draft.id}:{approval.id}:{network}".encode()
    ).hexdigest()[:32]

    # 2. Idempotent short-circuit for already-verified LIVE publications (zero duplicate WordPress POSTs)
    existing_post_id = _validate_verified_post_id(draft.provider_post_id)
    existing_url = _validate_canonical_url(draft.canonical_url)
    if draft.status == "PUBLISHED" and existing_post_id is not None and existing_url is not None:
        meta = dict(draft.publish_metadata or {})
        return {
            "status": "PUBLISHED",
            "live_published": True,
            "is_simulated": False,
            "idempotent_replay": True,
            "reconciled": bool(meta.get("reconciled", False)),
            "draft_id": str(draft.id),
            "approval_id": approval.id,
            "network": network,
            "title": title,
            "slug": str(meta.get("slug") or slug),
            "url": existing_url,
            "canonical_url": existing_url,
            "post_id": existing_post_id,
            "provider_post_id": str(existing_post_id),
            "mode": "WORDPRESS_REST_LIVE",
            "delivery_verification": "LIVE_WORDPRESS_REST",
            "idempotency_key": wp_idemp_key,
            "response_metadata": meta,
            "published_at": draft.decided_at.isoformat() if draft.decided_at else None,
            "block_hash": meta.get("block_hash"),
        }

    # 3. Determine execution mode: per-site or global live credentials + side-effect guard
    wp_site_url, wp_username, wp_app_password = resolve_wordpress_target(network)

    from app.services.execution_guard import (
        is_external_side_effect_blocked,
        record_simulated_dispatch,
        validate_external_url,
    )

    has_live_creds = bool(wp_site_url and wp_username and wp_app_password)
    blocked_by_guard = is_external_side_effect_blocked()

    # 4. Simulated path (credentials unset OR side effects blocked) -> SIMULATED (NEVER PUBLISHED)
    if not has_live_creds or blocked_by_guard:
        if has_live_creds and blocked_by_guard:
            record_simulated_dispatch(
                "wordpress_rest",
                wp_site_url,
                {
                    "draft_id": str(draft.id),
                    "approval_id": approval.id,
                    "title": title,
                    "slug": slug,
                    "idempotency_key": wp_idemp_key,
                },
            )
            delivery_verification = "SIMULATED_SIDE_EFFECTS_BLOCKED"
        else:
            delivery_verification = "SIMULATED_CREDENTIALS_UNSET"

        sim_post_id = int(hashlib.sha256(f"{draft.id}-{network}".encode()).hexdigest()[:6], 16)
        sim_url = f"https://{network}/articles/{slug}"

        # Idempotent replay if already simulated for the same approval & still simulated
        if draft.status == "SIMULATED" and isinstance(draft.publish_metadata, dict):
            prev = dict(draft.publish_metadata)
            if prev.get("idempotency_key") == wp_idemp_key:
                return {
                    "status": "SIMULATED",
                    "live_published": False,
                    "is_simulated": True,
                    "idempotent_replay": True,
                    "draft_id": str(draft.id),
                    "approval_id": approval.id,
                    "network": network,
                    "title": title,
                    "slug": slug,
                    "url": None,
                    "canonical_url": None,
                    "simulated_url": prev.get("simulated_url", sim_url),
                    "post_id": None,
                    "provider_post_id": None,
                    "simulated_post_id": prev.get("simulated_post_id", sim_post_id),
                    "mode": "WORDPRESS_SIMULATED_REST",
                    "delivery_verification": delivery_verification,
                    "idempotency_key": wp_idemp_key,
                    "response_metadata": prev,
                    "published_at": None,
                    "simulated_at": draft.decided_at.isoformat() if draft.decided_at else None,
                    "block_hash": prev.get("block_hash"),
                }

        now = datetime.now(UTC)
        sim_meta = {
            "status": "SIMULATED",
            "mode": "WORDPRESS_SIMULATED_REST",
            "is_simulated": True,
            "live_published": False,
            "approval_id": approval.id,
            "network": network,
            "title": title,
            "slug": slug,
            "simulated_url": sim_url,
            "simulated_post_id": sim_post_id,
            "delivery_verification": delivery_verification,
            "idempotency_key": wp_idemp_key,
            "simulated_at": now.isoformat(),
        }
        draft.status = "SIMULATED"
        draft.decided_at = now
        draft.publish_metadata = sim_meta
        db.add(draft)

        audit = AuditLog(
            task_id=draft.task_id or str(draft.id),
            correlation_id=corr_id,
            agent_id=published_by,
            capability_name=CAPABILITY_NAME,
            action="wordpress_publish",
            input_payload={
                "draft_id": str(draft.id),
                "approval_id": approval.id,
                "network": network,
                "idempotency_key": wp_idemp_key,
            },
            output_payload=sim_meta,
            status="SIMULATED",
        )
        db.add(audit)
        db.commit()

        block = seal_task_to_block(
            db=db,
            task_id=draft.task_id or str(draft.id),
            capability_name=CAPABILITY_NAME,
            action="wordpress_publish",
            payload=sim_meta,
            sealed_by=published_by,
        )
        sim_meta["block_hash"] = block.block_hash
        draft.publish_metadata = sim_meta
        db.add(draft)
        db.commit()

        return {
            "status": "SIMULATED",
            "live_published": False,
            "is_simulated": True,
            "idempotent_replay": False,
            "draft_id": str(draft.id),
            "approval_id": approval.id,
            "network": network,
            "title": title,
            "slug": slug,
            "url": None,
            "canonical_url": None,
            "simulated_url": sim_url,
            "post_id": None,
            "provider_post_id": None,
            "simulated_post_id": sim_post_id,
            "mode": "WORDPRESS_SIMULATED_REST",
            "delivery_verification": delivery_verification,
            "idempotency_key": wp_idemp_key,
            "response_metadata": sim_meta,
            "published_at": None,
            "simulated_at": now.isoformat(),
            "block_hash": block.block_hash,
        }

    # 5. Live WordPress REST publishing path (strict URL validation, reconciliation & response verification)
    try:
        validate_external_url(wp_site_url)
    except Exception as exc:
        _record_publish_failure(
            db,
            draft,
            approval_id=approval.id,
            network=network,
            title=title,
            slug=slug,
            corr_id=corr_id,
            published_by=published_by,
            idempotency_key=wp_idemp_key,
            error_code="unsafe_target_url",
            error_message=str(exc),
        )
        raise WordPressPublishError(
            f"WordPress target URL blocked: {exc}",
            error_code="unsafe_target_url",
            draft_id=str(draft.id),
        ) from exc

    import httpx

    endpoint = f"{wp_site_url.rstrip('/')}/wp-json/wp/v2/posts"
    auth = (wp_username, wp_app_password)

    reconciled = False
    verified_post_id: int | str | None = None
    verified_url: str | None = None
    provider_payload: dict[str, Any] = {}
    http_status: int = 200

    # Reconcile prior attempt on retry (if previous attempt failed/timed out or saved a provider ID)
    if draft.status == "PUBLISH_FAILED" or draft.provider_post_id:
        found = _reconcile_existing_wordpress_post(
            endpoint=endpoint,
            slug=slug,
            stored_post_id=draft.provider_post_id,
            auth=auth,
            http_client=http_client,
        )
        if found is not None:
            verified_post_id, verified_url, provider_payload = found
            reconciled = True
            http_status = 200

    if not reconciled:
        wp_publish_status = os.getenv("WP_PUBLISH_STATUS", "publish").strip().lower()
        if wp_publish_status not in ("publish", "draft", "pending"):
            wp_publish_status = "publish"
        rendered_content = render_wordpress_html(draft.content or "")
        post_kwargs: dict[str, Any] = {
            "auth": auth,
            "headers": {"Idempotency-Key": wp_idemp_key},
            "json": {
                "title": title,
                "content": rendered_content,
                "status": wp_publish_status,
                "slug": slug,
            },
            "timeout": 10.0,
        }
        try:
            if http_client is not None:
                resp = http_client.post(endpoint, **post_kwargs)
            else:
                resp = httpx.post(endpoint, **post_kwargs)
        except httpx.TimeoutException as exc:
            _record_publish_failure(
                db,
                draft,
                approval_id=approval.id,
                network=network,
                title=title,
                slug=slug,
                corr_id=corr_id,
                published_by=published_by,
                idempotency_key=wp_idemp_key,
                error_code="wordpress_timeout",
                error_message=f"WordPress REST request timed out: {exc}",
            )
            logger.error("Live WordPress publish timeout for draft %s: %s", draft.id, exc)
            raise WordPressPublishError(
                f"Live WordPress publish timed out: {exc}",
                error_code="wordpress_timeout",
                draft_id=str(draft.id),
            ) from exc
        except Exception as exc:
            _record_publish_failure(
                db,
                draft,
                approval_id=approval.id,
                network=network,
                title=title,
                slug=slug,
                corr_id=corr_id,
                published_by=published_by,
                idempotency_key=wp_idemp_key,
                error_code="wordpress_network_error",
                error_message=f"WordPress REST transport error: {exc}",
            )
            logger.error("Live WordPress publish transport error for draft %s: %s", draft.id, exc)
            raise WordPressPublishError(
                f"Live WordPress publish error: {exc}",
                error_code="wordpress_network_error",
                draft_id=str(draft.id),
            ) from exc

        http_status = int(resp.status_code)
        if http_status not in (200, 201):
            err_excerpt = getattr(resp, "text", "") or ""
            _record_publish_failure(
                db,
                draft,
                approval_id=approval.id,
                network=network,
                title=title,
                slug=slug,
                corr_id=corr_id,
                published_by=published_by,
                idempotency_key=wp_idemp_key,
                error_code=f"wordpress_http_{http_status}",
                error_message=f"WordPress REST returned HTTP {http_status}",
                http_status=http_status,
                response_excerpt=err_excerpt,
            )
            logger.error("Live WordPress publish HTTP %s for draft %s: %s", http_status, draft.id, err_excerpt[:300])
            raise WordPressPublishError(
                f"Live WordPress publish failed ({http_status}): {err_excerpt[:300]}",
                error_code=f"wordpress_http_{http_status}",
                draft_id=str(draft.id),
                http_status=http_status,
            )

        # Parse and strictly validate JSON payload
        try:
            raw_json = resp.json()
        except Exception as exc:
            err_excerpt = getattr(resp, "text", "") or ""
            _record_publish_failure(
                db,
                draft,
                approval_id=approval.id,
                network=network,
                title=title,
                slug=slug,
                corr_id=corr_id,
                published_by=published_by,
                idempotency_key=wp_idemp_key,
                error_code="wordpress_malformed_json",
                error_message=f"WordPress returned non-JSON response: {exc}",
                http_status=http_status,
                response_excerpt=err_excerpt,
            )
            raise WordPressPublishError(
                f"Live WordPress publish returned malformed JSON: {exc}",
                error_code="wordpress_malformed_json",
                draft_id=str(draft.id),
                http_status=http_status,
            ) from exc

        if not isinstance(raw_json, dict):
            _record_publish_failure(
                db,
                draft,
                approval_id=approval.id,
                network=network,
                title=title,
                slug=slug,
                corr_id=corr_id,
                published_by=published_by,
                idempotency_key=wp_idemp_key,
                error_code="wordpress_invalid_payload",
                error_message="WordPress JSON response must be an object containing post id and link.",
                http_status=http_status,
            )
            raise WordPressPublishError(
                "Live WordPress publish returned non-object JSON payload.",
                error_code="wordpress_invalid_payload",
                draft_id=str(draft.id),
                http_status=http_status,
            )

        verified_post_id = _validate_verified_post_id(raw_json.get("id"))
        verified_url = _validate_canonical_url(raw_json.get("link"))
        if verified_post_id is None:
            _record_publish_failure(
                db,
                draft,
                approval_id=approval.id,
                network=network,
                title=title,
                slug=slug,
                corr_id=corr_id,
                published_by=published_by,
                idempotency_key=wp_idemp_key,
                error_code="wordpress_missing_post_id",
                error_message="WordPress response did not include a valid post id.",
                http_status=http_status,
            )
            raise WordPressPublishError(
                "Live WordPress response missing verifiable post id.",
                error_code="wordpress_missing_post_id",
                draft_id=str(draft.id),
                http_status=http_status,
            )

        if verified_url is None:
            # Persist provider_post_id for reconciliation even if link was missing, while keeping status PUBLISH_FAILED
            draft.provider_post_id = str(verified_post_id)
            _record_publish_failure(
                db,
                draft,
                approval_id=approval.id,
                network=network,
                title=title,
                slug=slug,
                corr_id=corr_id,
                published_by=published_by,
                idempotency_key=wp_idemp_key,
                error_code="wordpress_missing_canonical_url",
                error_message="WordPress response did not include a valid canonical link URL.",
                http_status=http_status,
            )
            raise WordPressPublishError(
                "Live WordPress response missing verifiable canonical URL (link).",
                error_code="wordpress_missing_canonical_url",
                draft_id=str(draft.id),
                http_status=http_status,
            )

        provider_payload = raw_json

    # 6. Verified LIVE publication: persist provider ID, canonical URL, metadata, AuditLog & TrustBlock
    now = datetime.now(UTC)
    response_metadata: dict[str, Any] = {
        "status": "PUBLISHED",
        "mode": "WORDPRESS_REST_LIVE",
        "http_status": http_status,
        "approval_id": approval.id,
        "network": network,
        "provider_post_id": str(verified_post_id),
        "canonical_url": verified_url,
        "provider_status": provider_payload.get("status", "publish"),
        "slug": str(provider_payload.get("slug") or slug),
        "idempotency_key": wp_idemp_key,
        "reconciled": reconciled,
        "verified_at": now.isoformat(),
    }

    draft.status = "PUBLISHED"
    draft.provider_post_id = str(verified_post_id)
    draft.canonical_url = verified_url
    draft.publish_metadata = response_metadata
    draft.decided_at = now
    db.add(draft)

    audit_payload = {
        "draft_id": str(draft.id),
        "approval_id": approval.id,
        "network": network,
        "title": title,
        "slug": response_metadata["slug"],
        "url": verified_url,
        "canonical_url": verified_url,
        "post_id": verified_post_id,
        "provider_post_id": str(verified_post_id),
        "mode": "WORDPRESS_REST_LIVE",
        "is_simulated": False,
        "live_published": True,
        "reconciled": reconciled,
        "delivery_verification": "LIVE_WORDPRESS_REST",
        "idempotency_key": wp_idemp_key,
        "response_metadata": response_metadata,
        "status": "PUBLISHED",
    }
    audit = AuditLog(
        task_id=draft.task_id or str(draft.id),
        correlation_id=corr_id,
        agent_id=published_by,
        capability_name=CAPABILITY_NAME,
        action="wordpress_publish",
        input_payload={
            "draft_id": str(draft.id),
            "approval_id": approval.id,
            "network": network,
            "idempotency_key": wp_idemp_key,
        },
        output_payload=audit_payload,
        status="COMPLETED",
    )
    db.add(audit)
    db.commit()

    block = seal_task_to_block(
        db=db,
        task_id=draft.task_id or str(draft.id),
        capability_name=CAPABILITY_NAME,
        action="wordpress_publish",
        payload=audit_payload,
        sealed_by=published_by,
    )
    response_metadata["block_hash"] = block.block_hash
    draft.publish_metadata = response_metadata
    db.add(draft)
    db.commit()

    return {
        "status": "PUBLISHED",
        "live_published": True,
        "is_simulated": False,
        "idempotent_replay": False,
        "reconciled": reconciled,
        "draft_id": str(draft.id),
        "approval_id": approval.id,
        "network": network,
        "title": title,
        "slug": response_metadata["slug"],
        "url": verified_url,
        "canonical_url": verified_url,
        "post_id": verified_post_id,
        "provider_post_id": str(verified_post_id),
        "mode": "WORDPRESS_REST_LIVE",
        "delivery_verification": "LIVE_WORDPRESS_REST",
        "idempotency_key": wp_idemp_key,
        "response_metadata": response_metadata,
        "published_at": now.isoformat(),
        "block_hash": block.block_hash,
    }
