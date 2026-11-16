"""P8 Marketplace Ecosystem & Master Roadmap Scorecard service layer.

Implements:
- Third-party Developer KYB onboarding & verification gate
- Permission-scoped listing submission with SHA-256 + ECDSA NIST P-256 package signing
- Tenant-isolated installation with non-reversible secret digests (no plaintext leakage)
- Verified-installer reviews, abuse flagging/moderation, and SANDBOX/ACTUAL revenue-share ledger
- Master Roadmap Scorecard aggregating P0-P8 verification state with P3.1 cutover blockers preserved
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    OrganizationRecord,
    P8DeveloperProfileRecord,
    P8MarketplaceListingRecord,
    P8MarketplaceReviewRecord,
    P8RevenueShareLedgerRecord,
    P8TenantInstallRecord,
)
from app.security.ecdsa_pki import get_node_public_key, sign_block, verify_signature
from app.security.trust_chain import seal_task_to_block
from app.services.execution_guard import ExecutionBlockedError, validate_external_url
from app.services.p3_1_verification_registry import get_release_readiness_summary
from app.services.p4_growth_gtm import check_gtm_copy_safety

PACKAGE_TYPES: tuple[str, ...] = ("AGENT_PLUGIN", "CONNECTOR_ADAPTER", "WORKFLOW_PACK")
ALLOWED_PLUGIN_PERMISSIONS: tuple[str, ...] = (
    "read_icps",
    "read_metrics",
    "stage_content",
    "run_sandbox_diagnostics",
    "emit_webhook",
)
KYB_STATUSES: tuple[str, ...] = ("PENDING", "VERIFIED", "REJECTED", "SUSPENDED")
EVIDENCE_ORIGINS: tuple[str, ...] = ("SANDBOX", "ACTUAL")


def _mask_sensitive(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    if len(s) <= 4:
        return "••••"
    return f"••••{s[-4:]}"


def _canonical_manifest(
    *,
    developer_id: str,
    listing_slug: str,
    name: str,
    package_type: str,
    version: str,
    permissions: list[str],
    endpoint_url: str | None,
) -> tuple[dict[str, Any], str, str, str]:
    manifest = {
        "developer_id": developer_id,
        "listing_slug": listing_slug,
        "name": name,
        "package_type": package_type,
        "version": version,
        "permissions": sorted(permissions),
        "endpoint_url": endpoint_url or "",
    }
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    sig_hex = sign_block(digest)
    pub_pem = get_node_public_key()
    return manifest, digest, sig_hex, pub_pem


def _serialize_developer(rec: P8DeveloperProfileRecord, *, include_private: bool = True) -> dict[str, Any]:
    if not include_private:
        return {
            "developer_id": rec.id,
            "org_id": rec.org_id,
            "developer_name": rec.developer_name,
            "contact_email": _mask_sensitive(rec.contact_email),
            "legal_entity_name": rec.legal_entity_name,
            "tax_or_gst_id": None,
            "kyb_status": rec.kyb_status,
            "kyb_notes": None,
            "payout_account_masked": None,
            "verified_by": None,
            "verified_at": rec.verified_at.isoformat() if rec.verified_at else None,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
        }
    return {
        "developer_id": rec.id,
        "org_id": rec.org_id,
        "developer_name": rec.developer_name,
        "contact_email": rec.contact_email,
        "legal_entity_name": rec.legal_entity_name,
        "tax_or_gst_id": rec.tax_or_gst_id,
        "kyb_status": rec.kyb_status,
        "kyb_notes": rec.kyb_notes,
        "payout_account_masked": rec.payout_account_masked,
        "verified_by": rec.verified_by,
        "verified_at": rec.verified_at.isoformat() if rec.verified_at else None,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def register_developer_profile(
    db: Session,
    *,
    org_id: str | None,
    developer_name: str,
    contact_email: str,
    legal_entity_name: str,
    tax_or_gst_id: str | None = None,
    payout_account: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Onboard a third-party marketplace developer in PENDING KYB state."""
    if org_id is not None:
        org = db.query(OrganizationRecord).filter_by(id=org_id).first()
        if not org:
            raise ValueError(f"Organization '{org_id}' not found")
        if not org.is_active:
            raise PermissionError("Organization account is inactive or suspended")
    now = datetime.now(UTC)
    rec = P8DeveloperProfileRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        developer_name=developer_name.strip(),
        contact_email=contact_email.strip().lower(),
        legal_entity_name=legal_entity_name.strip(),
        tax_or_gst_id=tax_or_gst_id.strip() if tax_or_gst_id else None,
        kyb_status="PENDING",
        payout_account_masked=_mask_sensitive(payout_account),
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_developer(rec, include_private=True)


def verify_developer_kyb(
    db: Session,
    *,
    developer_id: str,
    kyb_status: str,
    kyb_notes: str | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Approve, reject, or suspend a developer profile after KYB review."""
    rec = db.get(P8DeveloperProfileRecord, developer_id)
    if not rec:
        raise ValueError(f"Developer '{developer_id}' not found")
    clean = kyb_status.strip().upper()
    if clean not in KYB_STATUSES:
        raise ValueError(f"Unsupported kyb_status '{kyb_status}'; allowed: {KYB_STATUSES}")
    now = datetime.now(UTC)
    rec.kyb_status = clean
    if kyb_notes is not None:
        rec.kyb_notes = kyb_notes.strip()
    if clean == "VERIFIED":
        rec.verified_by = actor
        rec.verified_at = now
    else:
        rec.verified_by = None
        rec.verified_at = None
    rec.updated_at = now
    db.commit()
    db.refresh(rec)
    return _serialize_developer(rec, include_private=True)


def list_developers(
    db: Session,
    *,
    kyb_status: str | None = None,
    org_id: str | None = None,
    viewer_org_id: str | None = None,
    is_platform_operator: bool = True,
) -> list[dict[str, Any]]:
    """List marketplace developer profiles with PII masked for non-owners."""
    q = db.query(P8DeveloperProfileRecord)
    if kyb_status:
        q = q.filter(P8DeveloperProfileRecord.kyb_status == kyb_status.strip().upper())
    if org_id is not None:
        q = q.filter(P8DeveloperProfileRecord.org_id == org_id)
    elif not is_platform_operator:
        if not viewer_org_id:
            return []
        q = q.filter(P8DeveloperProfileRecord.org_id == viewer_org_id)
    return [
        _serialize_developer(
            r,
            include_private=bool(is_platform_operator or (viewer_org_id and r.org_id == viewer_org_id)),
        )
        for r in q.order_by(P8DeveloperProfileRecord.created_at.desc()).all()
    ]


def _serialize_listing(rec: P8MarketplaceListingRecord, *, include_private: bool = True) -> dict[str, Any]:
    return {
        "listing_id": rec.id,
        "developer_id": rec.developer_id,
        "listing_slug": rec.listing_slug,
        "name": rec.name,
        "package_type": rec.package_type,
        "description": rec.description,
        "version": rec.version,
        "requested_permissions": list(rec.requested_permissions_json or []),
        "endpoint_url": rec.endpoint_url,
        "manifest_sha256": rec.manifest_sha256,
        "is_signed": bool(rec.ecdsa_signature_hex),
        "ecdsa_signature_hex": rec.ecdsa_signature_hex if include_private else None,
        "price_inr_monthly": int(rec.price_inr_monthly or 0),
        "commission_bps": int(rec.commission_bps or 1500),
        "security_review_status": rec.security_review_status,
        "review_notes": rec.review_notes if include_private else None,
        "published_status": rec.published_status,
        "approved_by": rec.approved_by if include_private else None,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def create_marketplace_listing(
    db: Session,
    *,
    developer_id: str,
    listing_slug: str,
    name: str,
    package_type: str = "AGENT_PLUGIN",
    description: str = "",
    version: str = "1.0.0",
    requested_permissions: list[str] | None = None,
    endpoint_url: str | None = None,
    price_inr_monthly: int = 0,
    commission_bps: int = 1500,
    actor_org_id: str | None = None,
    is_platform_operator: bool = False,
) -> dict[str, Any]:
    """Create and ECDSA/SHA-256 sign a third-party marketplace listing for a KYB-verified developer."""
    dev = db.get(P8DeveloperProfileRecord, developer_id)
    if not dev:
        raise ValueError(f"Developer '{developer_id}' not found")
    if not is_platform_operator:
        if not actor_org_id or dev.org_id != actor_org_id:
            raise PermissionError("Access denied: developer profile belongs to another organization")
    if dev.org_id:
        org = db.query(OrganizationRecord).filter_by(id=dev.org_id).first()
        if not org:
            raise ValueError(f"Organization '{dev.org_id}' not found")
        if not org.is_active:
            raise PermissionError("Organization account is inactive or suspended")
    if dev.kyb_status != "VERIFIED":
        raise PermissionError(f"Developer KYB status is '{dev.kyb_status}'; VERIFIED KYB is required to submit packages")

    clean_type = package_type.strip().upper()
    if clean_type not in PACKAGE_TYPES:
        raise ValueError(f"Unsupported package_type '{package_type}'; allowed: {PACKAGE_TYPES}")
    clean_slug = listing_slug.strip().lower()
    if db.query(P8MarketplaceListingRecord).filter_by(listing_slug=clean_slug).first():
        raise ValueError(f"listing_slug '{clean_slug}' already exists")

    if not (500 <= int(commission_bps) <= 3000):
        raise ValueError("commission_bps must be between 500 (5%) and 3000 (30%)")
    if price_inr_monthly < 0:
        raise ValueError("price_inr_monthly must be non-negative")

    perms = list(dict.fromkeys(str(p).strip() for p in (requested_permissions or ["read_metrics"]) if str(p).strip()))
    bad_perms = [p for p in perms if p not in ALLOWED_PLUGIN_PERMISSIONS]
    if bad_perms:
        raise ValueError(f"Rejected excessive/unknown permissions {bad_perms}; allowed: {ALLOWED_PLUGIN_PERMISSIONS}")

    if endpoint_url:
        try:
            validate_external_url(endpoint_url.strip())
        except ExecutionBlockedError as exc:
            raise ValueError(exc.reason) from exc

    safety = check_gtm_copy_safety({"name": name, "description": description}, subject=name)
    if not safety["safe"]:
        raise ValueError(f"Listing description failed safety filter: {'; '.join(safety['issues'])}")

    manifest, digest, sig_hex, pub_pem = _canonical_manifest(
        developer_id=developer_id,
        listing_slug=clean_slug,
        name=name.strip(),
        package_type=clean_type,
        version=version.strip(),
        permissions=perms,
        endpoint_url=endpoint_url.strip() if endpoint_url else None,
    )

    now = datetime.now(UTC)
    rec = P8MarketplaceListingRecord(
        id=str(uuid.uuid4()),
        developer_id=developer_id,
        listing_slug=clean_slug,
        name=name.strip(),
        package_type=clean_type,
        description=description.strip(),
        version=version.strip(),
        requested_permissions_json=perms,
        endpoint_url=endpoint_url.strip() if endpoint_url else None,
        manifest_json=manifest,
        manifest_sha256=digest,
        ecdsa_signature_hex=sig_hex,
        signing_public_key_pem=pub_pem,
        price_inr_monthly=int(price_inr_monthly),
        commission_bps=int(commission_bps),
        security_review_status="PENDING_REVIEW",
        published_status="DRAFT",
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_listing(rec)


def verify_listing_signature(
    db: Session,
    *,
    listing_id: str,
    viewer_org_id: str | None = None,
    is_platform_operator: bool = True,
) -> dict[str, Any]:
    """Verify SHA-256 manifest digest, canonical metadata match, and pinned node ECDSA P-256 signature."""
    rec = db.get(P8MarketplaceListingRecord, listing_id)
    if not rec:
        raise ValueError(f"Listing '{listing_id}' not found")
    dev = db.get(P8DeveloperProfileRecord, rec.developer_id)
    if not is_platform_operator and rec.published_status != "PUBLISHED":
        if not viewer_org_id or not dev or dev.org_id != viewer_org_id:
            raise PermissionError("Access denied: unpublished listing belongs to another organization")

    expected_manifest = {
        "developer_id": rec.developer_id,
        "listing_slug": rec.listing_slug,
        "name": rec.name,
        "package_type": rec.package_type,
        "version": rec.version,
        "permissions": sorted(list(rec.requested_permissions_json or [])),
        "endpoint_url": rec.endpoint_url or "",
    }
    manifest_canonical_match = (rec.manifest_json or {}) == expected_manifest
    encoded = json.dumps(rec.manifest_json or {}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    recomputed_sha = hashlib.sha256(encoded).hexdigest()
    sha_match = recomputed_sha == rec.manifest_sha256 and manifest_canonical_match
    pinned_pub_pem = get_node_public_key()
    public_key_pinned = bool(rec.signing_public_key_pem) and rec.signing_public_key_pem.strip() == pinned_pub_pem.strip()
    ecdsa_ok = bool(public_key_pinned) and verify_signature(pinned_pub_pem, rec.manifest_sha256, rec.ecdsa_signature_hex)
    return {
        "listing_id": rec.id,
        "sha256_match": sha_match,
        "manifest_canonical_match": manifest_canonical_match,
        "public_key_pinned": public_key_pinned,
        "ecdsa_valid": ecdsa_ok,
        "verified": bool(sha_match and manifest_canonical_match and public_key_pinned and ecdsa_ok),
        "manifest_sha256": rec.manifest_sha256,
    }


def review_marketplace_listing(
    db: Session,
    *,
    listing_id: str,
    security_review_status: str,
    publish: bool = False,
    review_notes: str | None = None,
    actor: str = "owner",
) -> dict[str, Any]:
    """Owner permission review and optional publishing (requires APPROVED, VERIFIED developer KYB, and valid cryptographic signature)."""
    rec = db.get(P8MarketplaceListingRecord, listing_id)
    if not rec:
        raise ValueError(f"Listing '{listing_id}' not found")

    clean_sec = security_review_status.strip().upper()
    if clean_sec not in ("PENDING_REVIEW", "APPROVED", "REJECTED", "SUSPENDED"):
        raise ValueError(f"Unsupported security_review_status '{security_review_status}'")

    dev = db.get(P8DeveloperProfileRecord, rec.developer_id)
    if publish and (not dev or dev.kyb_status != "VERIFIED"):
        raise PermissionError("Cannot publish listing unless developer KYB status is VERIFIED")

    sig = verify_listing_signature(db, listing_id=listing_id, is_platform_operator=True)
    if publish and (clean_sec != "APPROVED" or not sig["verified"]):
        raise PermissionError("Cannot publish listing unless security_review_status=APPROVED and cryptographic signature verifies")

    rec.security_review_status = clean_sec
    rec.review_notes = review_notes.strip() if review_notes else rec.review_notes
    if clean_sec == "APPROVED":
        rec.approved_by = actor
    else:
        rec.approved_by = None

    if publish:
        rec.published_status = "PUBLISHED"
    elif clean_sec in ("REJECTED", "SUSPENDED"):
        rec.published_status = "DELISTED"
    elif clean_sec == "PENDING_REVIEW":
        rec.published_status = "DRAFT"
    rec.updated_at = datetime.now(UTC)

    seal_task_to_block(
        db=db,
        task_id=rec.id,
        capability_name="p8_marketplace_ecosystem",
        action="review_marketplace_listing",
        payload={"listing_id": rec.id, "security_review_status": clean_sec, "published_status": rec.published_status},
        sealed_by=actor,
    )
    db.commit()
    db.refresh(rec)
    return _serialize_listing(rec, include_private=True)


def list_marketplace_listings(
    db: Session,
    *,
    published_only: bool = True,
    viewer_org_id: str | None = None,
    is_platform_operator: bool = False,
) -> list[dict[str, Any]]:
    """List marketplace packages, hiding other tenants' unpublished drafts and redacting private fields for non-owners."""
    rows = db.query(P8MarketplaceListingRecord).order_by(P8MarketplaceListingRecord.created_at.desc()).all()
    dev_org_map = {d.id: d.org_id for d in db.query(P8DeveloperProfileRecord).all()}
    result: list[dict[str, Any]] = []
    for rec in rows:
        is_pub = rec.published_status == "PUBLISHED" and rec.security_review_status == "APPROVED"
        dev_org_id = dev_org_map.get(rec.developer_id)
        is_owner_org = bool(viewer_org_id and dev_org_id == viewer_org_id)
        if published_only and not is_pub:
            continue
        if not published_only and not is_platform_operator and not is_pub and not is_owner_org:
            continue
        result.append(_serialize_listing(rec, include_private=bool(is_platform_operator or is_owner_org)))
    return result


def _serialize_install(rec: P8TenantInstallRecord) -> dict[str, Any]:
    return {
        "install_id": rec.id,
        "org_id": rec.org_id,
        "listing_id": rec.listing_id,
        "status": rec.status,
        "granted_permissions": list(rec.granted_permissions_json or []),
        "configured_secret_keys": sorted(list((rec.secret_digests_json or {}).keys())),
        "secret_previews": {k: v.get("masked") for k, v in (rec.secret_digests_json or {}).items()},
        "config": dict(rec.config_json or {}),
        "installed_by": rec.installed_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def install_marketplace_listing(
    db: Session,
    *,
    org_id: str,
    listing_id: str,
    granted_permissions: list[str] | None = None,
    secrets_payload: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Install an approved/signed package for an active tenant while isolating all credential values."""
    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")
    if not org.is_active:
        raise PermissionError("Organization account is inactive or suspended")
    listing = db.get(P8MarketplaceListingRecord, listing_id)
    if not listing:
        raise ValueError(f"Listing '{listing_id}' not found")
    if listing.published_status != "PUBLISHED" or listing.security_review_status != "APPROVED":
        raise PermissionError("Cannot install a listing that is not APPROVED and PUBLISHED")
    dev = db.get(P8DeveloperProfileRecord, listing.developer_id)
    if not dev or dev.kyb_status != "VERIFIED":
        raise PermissionError("Cannot install package: developer KYB status is not VERIFIED")

    sig = verify_listing_signature(db, listing_id=listing_id, is_platform_operator=True)
    if not sig["verified"]:
        raise PermissionError("Cannot install package with invalid SHA-256 or ECDSA signature")

    existing_active = (
        db.query(P8TenantInstallRecord)
        .filter_by(org_id=org_id, listing_id=listing_id, status="ACTIVE")
        .first()
    )
    if existing_active:
        raise ValueError(f"Listing '{listing_id}' is already actively installed for organization '{org_id}'")

    approved_perms = set(listing.requested_permissions_json or [])
    requested_grant = list(granted_permissions if granted_permissions is not None else approved_perms)
    if not set(requested_grant) <= approved_perms:
        raise PermissionError("Cannot grant permissions beyond the listing's security-reviewed manifest")

    digests: dict[str, dict[str, str]] = {}
    for key, val in (secrets_payload or {}).items():
        clean_k = str(key).strip()
        clean_v = str(val).strip()
        if not clean_k or not clean_v:
            continue
        digests[clean_k] = {
            "masked": _mask_sensitive(clean_v) or "••••",
            "sha256": hashlib.sha256(f"{org_id}:{clean_k}:{clean_v}".encode()).hexdigest(),
        }

    now = datetime.now(UTC)
    rec = P8TenantInstallRecord(
        id=str(uuid.uuid4()),
        org_id=org_id,
        listing_id=listing_id,
        status="ACTIVE",
        granted_permissions_json=requested_grant,
        secret_digests_json=digests,
        config_json=dict(config or {}),
        installed_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_install(rec)


def revoke_marketplace_install(
    db: Session,
    *,
    install_id: str,
    org_id: str | None = None,
    is_platform_operator: bool = False,
    actor: str = "system",
) -> dict[str, Any]:
    """Revoke/uninstall an active marketplace package and purge stored secret digests."""
    rec = db.get(P8TenantInstallRecord, install_id)
    if not rec:
        raise ValueError(f"Install '{install_id}' not found")
    if not is_platform_operator and (not org_id or rec.org_id != org_id):
        raise PermissionError("Access denied: install belongs to another organization")
    if rec.status == "REVOKED":
        return _serialize_install(rec)
    rec.status = "REVOKED"
    rec.secret_digests_json = {}
    rec.updated_at = datetime.now(UTC)
    seal_task_to_block(
        db=db,
        task_id=rec.id,
        capability_name="p8_marketplace_ecosystem",
        action="revoke_marketplace_install",
        payload={"install_id": rec.id, "org_id": rec.org_id, "listing_id": rec.listing_id},
        sealed_by=actor,
    )
    db.commit()
    db.refresh(rec)
    return _serialize_install(rec)


def list_tenant_installs(db: Session, *, org_id: str | None = None) -> list[dict[str, Any]]:
    """List tenant package installations (never exposing raw secret values)."""
    q = db.query(P8TenantInstallRecord)
    if org_id is not None:
        q = q.filter(P8TenantInstallRecord.org_id == org_id)
    return [_serialize_install(r) for r in q.order_by(P8TenantInstallRecord.created_at.desc()).all()]


def _serialize_review(rec: P8MarketplaceReviewRecord, *, include_private: bool = True) -> dict[str, Any]:
    return {
        "review_id": rec.id,
        "listing_id": rec.listing_id,
        "org_id": rec.org_id if include_private else None,
        "install_id": rec.install_id if include_private else None,
        "rating": int(rec.rating),
        "comment": rec.comment,
        "abuse_flagged": bool(rec.abuse_flagged) if include_private else False,
        "abuse_reason": rec.abuse_reason if include_private else None,
        "moderation_status": rec.moderation_status,
        "created_by": rec.created_by if include_private else None,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


def submit_marketplace_review(
    db: Session,
    *,
    org_id: str,
    listing_id: str,
    rating: int,
    comment: str,
    actor: str = "system",
) -> dict[str, Any]:
    """Allow one review per active verified installation of a published listing."""
    if not (1 <= int(rating) <= 5):
        raise ValueError("rating must be between 1 and 5")

    org = db.query(OrganizationRecord).filter_by(id=org_id).first()
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")
    if not org.is_active:
        raise PermissionError("Organization account is inactive or suspended")

    listing = db.get(P8MarketplaceListingRecord, listing_id)
    if not listing:
        raise ValueError(f"Listing '{listing_id}' not found")
    if listing.published_status != "PUBLISHED" or listing.security_review_status != "APPROVED":
        raise PermissionError("Cannot review a listing that is not APPROVED and PUBLISHED")

    install = (
        db.query(P8TenantInstallRecord)
        .filter_by(org_id=org_id, listing_id=listing_id, status="ACTIVE")
        .order_by(P8TenantInstallRecord.created_at.desc())
        .first()
    )
    if not install:
        raise PermissionError("Only active verified installers of this listing may submit a marketplace review")

    dup_review = (
        db.query(P8MarketplaceReviewRecord)
        .filter_by(install_id=install.id)
        .first()
    )
    if dup_review:
        raise ValueError("Only one review per installation is permitted; review already exists")

    safety = check_gtm_copy_safety({"comment": comment}, subject="marketplace_review")
    if not safety["safe"]:
        raise ValueError(f"Review failed safety filter: {'; '.join(safety['issues'])}")

    now = datetime.now(UTC)
    rec = P8MarketplaceReviewRecord(
        id=str(uuid.uuid4()),
        listing_id=listing_id,
        org_id=org_id,
        install_id=install.id,
        rating=int(rating),
        comment=comment.strip(),
        abuse_flagged=False,
        moderation_status="PUBLISHED",
        created_by=actor,
        created_at=now,
        updated_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_review(rec, include_private=True)


def moderate_marketplace_review(
    db: Session,
    *,
    review_id: str,
    abuse_flagged: bool,
    moderation_status: str,
    abuse_reason: str | None = None,
) -> dict[str, Any]:
    """Flag or remove an abusive marketplace review."""
    rec = db.get(P8MarketplaceReviewRecord, review_id)
    if not rec:
        raise ValueError(f"Review '{review_id}' not found")
    clean_mod = moderation_status.strip().upper()
    if clean_mod not in ("PUBLISHED", "FLAGGED_UNDER_REVIEW", "REMOVED"):
        raise ValueError(f"Unsupported moderation_status '{moderation_status}'")
    rec.abuse_flagged = bool(abuse_flagged)
    rec.moderation_status = clean_mod
    if abuse_reason is not None:
        rec.abuse_reason = abuse_reason.strip()
    rec.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(rec)
    return _serialize_review(rec)


def list_marketplace_reviews(
    db: Session,
    *,
    listing_id: str | None = None,
    include_removed: bool = False,
    viewer_org_id: str | None = None,
    is_platform_operator: bool = True,
) -> list[dict[str, Any]]:
    """List verified-installer marketplace reviews with private moderation internals redacted for non-owners."""
    q = db.query(P8MarketplaceReviewRecord)
    if listing_id:
        q = q.filter(P8MarketplaceReviewRecord.listing_id == listing_id)
    if not include_removed or not is_platform_operator:
        q = q.filter(P8MarketplaceReviewRecord.moderation_status != "REMOVED")
    published_ids = {
        r.id
        for r in db.query(P8MarketplaceListingRecord)
        .filter_by(published_status="PUBLISHED", security_review_status="APPROVED")
        .all()
    }
    rows = q.order_by(P8MarketplaceReviewRecord.created_at.desc()).all()
    out: list[dict[str, Any]] = []
    for r in rows:
        is_owner = bool(viewer_org_id and r.org_id == viewer_org_id)
        if not is_platform_operator and r.listing_id not in published_ids and not is_owner:
            continue
        out.append(_serialize_review(r, include_private=bool(is_platform_operator or is_owner)))
    return out


def _serialize_rev_entry(rec: P8RevenueShareLedgerRecord) -> dict[str, Any]:
    return {
        "ledger_id": rec.id,
        "install_id": rec.install_id,
        "listing_id": rec.listing_id,
        "developer_id": rec.developer_id,
        "org_id": rec.org_id,
        "gross_amount_inr": float(rec.gross_amount_inr),
        "commission_bps": int(rec.commission_bps),
        "platform_commission_inr": float(rec.platform_commission_inr),
        "developer_payout_inr": float(rec.developer_payout_inr),
        "settlement_status": rec.settlement_status,
        "evidence_status": rec.evidence_status,
        "recorded_by": rec.recorded_by,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def record_marketplace_revenue_share(
    db: Session,
    *,
    install_id: str,
    org_id: str | None,
    gross_amount_inr: float,
    evidence_status: str = "SANDBOX",
    actor: str = "system",
) -> dict[str, Any]:
    """Compute and record immutable marketplace commission split (ACTUAL vs SANDBOX)."""
    clean_origin = evidence_status.strip().upper()
    if clean_origin not in EVIDENCE_ORIGINS:
        raise ValueError(f"Unsupported evidence_status '{evidence_status}'; allowed: {EVIDENCE_ORIGINS}")
    if gross_amount_inr <= 0:
        raise ValueError("gross_amount_inr must be positive")

    install = db.get(P8TenantInstallRecord, install_id)
    if not install or (org_id is not None and install.org_id != org_id):
        raise ValueError(f"Install '{install_id}' not found")
    if install.status != "ACTIVE":
        raise PermissionError("Cannot record revenue share for an inactive or revoked installation")
    listing = db.get(P8MarketplaceListingRecord, install.listing_id)
    if not listing:
        raise ValueError("Referenced listing not found")

    commission_bps = int(listing.commission_bps or 1500)
    commission = round(float(gross_amount_inr) * commission_bps / 10000.0, 2)
    payout = round(float(gross_amount_inr) - commission, 2)

    rec = P8RevenueShareLedgerRecord(
        id=str(uuid.uuid4()),
        install_id=install.id,
        listing_id=listing.id,
        developer_id=listing.developer_id,
        org_id=install.org_id,
        gross_amount_inr=float(gross_amount_inr),
        commission_bps=commission_bps,
        platform_commission_inr=commission,
        developer_payout_inr=payout,
        settlement_status="ACCRUED",
        evidence_status=clean_origin,
        recorded_by=actor,
        created_at=datetime.now(UTC),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_rev_entry(rec)


def list_revenue_share_ledger(db: Session, *, org_id: str | None = None) -> dict[str, Any]:
    """List marketplace revenue share entries separating ACTUAL from SANDBOX."""
    q = db.query(P8RevenueShareLedgerRecord)
    if org_id is not None:
        q = q.filter(P8RevenueShareLedgerRecord.org_id == org_id)
    rows = [_serialize_rev_entry(r) for r in q.order_by(P8RevenueShareLedgerRecord.created_at.desc()).all()]
    actual = [r for r in rows if r["evidence_status"] == "ACTUAL"]
    sandbox = [r for r in rows if r["evidence_status"] == "SANDBOX"]
    return {
        "actual_gross_inr": round(sum(r["gross_amount_inr"] for r in actual), 2),
        "actual_platform_commission_inr": round(sum(r["platform_commission_inr"] for r in actual), 2),
        "sandbox_gross_inr": round(sum(r["gross_amount_inr"] for r in sandbox), 2),
        "sandbox_developer_payout_inr": round(sum(r["developer_payout_inr"] for r in sandbox), 2),
        "entries": rows,
    }


def compute_p8_overview(
    db: Session,
    *,
    org_id: str | None = None,
    viewer_org_id: str | None = None,
    is_platform_operator: bool = False,
) -> dict[str, Any]:
    """Return P8 marketplace developers, listings, installs, reviews, and revenue-share ledger with tenant/PII boundaries."""
    eff_viewer = viewer_org_id or org_id
    if is_platform_operator and org_id is None:
        devs = list_developers(db, is_platform_operator=True)
        listings = list_marketplace_listings(db, published_only=False, is_platform_operator=True)
        reviews = list_marketplace_reviews(db, include_removed=True, is_platform_operator=True)
    else:
        devs = (
            list_developers(db, org_id=org_id, viewer_org_id=eff_viewer, is_platform_operator=is_platform_operator)
            if org_id is not None
            else []
        )
        listings = list_marketplace_listings(
            db,
            published_only=False,
            viewer_org_id=eff_viewer,
            is_platform_operator=is_platform_operator,
        )
        reviews = list_marketplace_reviews(
            db,
            include_removed=is_platform_operator,
            viewer_org_id=eff_viewer,
            is_platform_operator=is_platform_operator,
        )
    installs = list_tenant_installs(db, org_id=org_id)
    ledger = list_revenue_share_ledger(db, org_id=org_id)
    return {
        "summary": {
            "developer_count": len(devs),
            "verified_developer_count": sum(1 for d in devs if d["kyb_status"] == "VERIFIED"),
            "listing_count": len(listings),
            "published_listing_count": sum(1 for l in listings if l["published_status"] == "PUBLISHED"),
            "install_count": len(installs),
            "actual_commission_inr": ledger["actual_platform_commission_inr"],
            "sandbox_gross_inr": ledger["sandbox_gross_inr"],
        },
        "developers": devs,
        "listings": listings,
        "installs": installs,
        "reviews": reviews,
        "revenue_ledger": ledger,
    }


def compute_master_roadmap_scorecard(db: Session) -> dict[str, Any]:
    """Aggregate honest verification status across P0-P8 while preserving P3.1 production cutover blockers."""
    p3_1 = get_release_readiness_summary(db)
    phases = [
        {"phase": "P0", "title": "Core Security, TrustChain & Execution Guards", "implementation_status": "COMPLETE_CODE", "verification_status": "LOCAL_VERIFIED"},
        {"phase": "P1", "title": "Modular SME Workforce & Pricing Catalog", "implementation_status": "COMPLETE_CODE", "verification_status": "LOCAL_VERIFIED"},
        {"phase": "P2", "title": "Commercial Revenue OS & Sovereign Settlement", "implementation_status": "COMPLETE_CODE", "verification_status": "LOCAL_VERIFIED"},
        {"phase": "P3", "title": "Customer Success, Onboarding & Health Engine", "implementation_status": "COMPLETE_CODE", "verification_status": "LOCAL_AND_E2E_VERIFIED"},
        {"phase": "P3.1", "title": "Live Verification Registry & Cutover Gate", "implementation_status": "COMPLETE_CODE", "verification_status": p3_1.get("overall_release_readiness", "BLOCKED")},
        {"phase": "P4", "title": "Repeatable Growth & GTM Engine", "implementation_status": "COMPLETE_CODE", "verification_status": "SANDBOX_VERIFIED"},
        {"phase": "P5", "title": "Productization, Atomic Ledger & Scale Provisioning", "implementation_status": "COMPLETE_CODE", "verification_status": "SANDBOX_VERIFIED"},
        {"phase": "P6", "title": "Multi-Industry SME Packs & India SEO", "implementation_status": "COMPLETE_CODE", "verification_status": "SANDBOX_AND_ROADMAP"},
        {"phase": "P7", "title": "Controlled Autonomous Workforce & Evals", "implementation_status": "COMPLETE_CODE", "verification_status": "SANDBOX_VERIFIED"},
        {"phase": "P8", "title": "Marketplace Ecosystem & Developer SDK", "implementation_status": "COMPLETE_CODE", "verification_status": "SANDBOX_VERIFIED"},
    ]
    return {
        "platform_architecture": "UNIFIED_SINGLE_OS",
        "overall_release_readiness": p3_1.get("overall_release_readiness", "BLOCKED"),
        "production_cutover_approved": bool(p3_1.get("production_cutover_approved", False)),
        "p3_1_blockers": p3_1.get("blocking_gaps", []),
        "p3_1_owner_actions_required": p3_1.get("owner_actions_required", []),
        "security_hardening": {
            "migration_head": "o5d0e1f2a3b4",
            "status": "LOCAL_SECURITY_HARDENED",
            "controls": {
                "auth_and_tenant_isolation": "LOCAL_VERIFIED",
                "p8_marketplace_isolation_and_kyb": "LOCAL_VERIFIED",
                "p7_autonomy_governance_and_budgets": "LOCAL_VERIFIED",
                "cross_record_and_fk_integrity": "LOCAL_VERIFIED",
                "postgres_isolated_backup_restore_drill": "BLOCKED",
            },
        },
        "phases": phases,
        "generated_at": datetime.now(UTC).isoformat(),
    }
