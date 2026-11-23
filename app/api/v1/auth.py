"""Authentication API router for Admin and Customer login accounts.

Provides:
- POST /v1/auth/login: Role-separated login for Admin vs Customer/Buyer
- POST /v1/auth/register: Customer / team user onboarding with password hashing
- GET /v1/auth/me: Returns current user profile, organization info, and credit balance
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.database import get_db
from app.db.models import ApprovalRequest, AuditLog, OrganizationRecord, TenantInvitationRecord, UserRecord
from app.security.auth import (
    INVITABLE_TENANT_ROLES,
    PUBLIC_FORBIDDEN_ROLES,
    TENANT_ADMIN_ROLES,
    APIPrincipal,
    create_access_token,
    get_current_principal,
    hash_password,
    revoke_token,
    verify_password,
)
from app.services.catalog import CATALOG, build_payment_link, get_package
from app.services.email_dispatcher import get_email_dispatcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["authentication"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=250, description="User email address")
    password: str = Field(min_length=6, max_length=128)
    portal: Literal["customer", "admin", "auto"] = Field(
        default="auto",
        description="Target portal: 'admin' checks for admin/owner privileges; 'customer' for buyer/member portal",
    )


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    full_name: str
    role: str
    org_id: str
    org_name: str | None = None
    org_tier: str | None = None
    portal_access: dict[str, bool]


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=250, description="User email address")
    password: str = Field(min_length=6, max_length=128)
    full_name: str = Field(min_length=2, max_length=250)
    company_name: str | None = Field(default=None, min_length=2, max_length=200)
    role: str = Field(
        default="customer",
        max_length=32,
        description="Requested role for public registration ('customer' or 'member' only)",
    )
    invite_token: str | None = Field(
        default=None,
        max_length=256,
        description="Optional single-use invitation token to join an existing organization",
    )
    gemini_api_key: str | None = Field(default=None, max_length=256)


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256, description="Single-use organization invitation secret")
    password: str | None = Field(default=None, min_length=6, max_length=128)
    full_name: str | None = Field(default=None, min_length=2, max_length=250)


class SignupRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=200, description="Company or Organization name")
    email: str = Field(min_length=3, max_length=250, description="Customer primary admin email")
    password: str = Field(min_length=6, max_length=128, description="Secure account password")
    full_name: str = Field(min_length=2, max_length=250, description="Full name of the account owner")
    package_key: str = Field(default="company_os_starter", description="Selected package from Catalog")
    payment_provider: Literal["afw_directpay", "sovereign_direct", "razorpay", "paypal"] = "afw_directpay"
    gemini_api_key: str | None = Field(default=None, max_length=256)


class SignupResponse(BaseModel):
    status: str
    user_id: str
    email: str
    full_name: str
    role: str
    org_id: str
    org_name: str
    org_slug: str
    tier: str
    package_name: str
    lead_credits_limit: int
    outreach_credits_limit: int
    checkout_url: str
    access_token: str | None = None
    token_type: str = "bearer"



class UserProfileResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: str
    org_id: str
    org_name: str
    tier: str
    lead_credits_remaining: int
    outreach_credits_remaining: int
    is_active: bool


# ── Helpers ──────────────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "org"


# ── Endpoints ────────────────────────────────────────────────────────────────


def _normalize_dt_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _validate_and_lock_invitation(
    db: Session,
    raw_token: str,
    email_clean: str | None = None,
) -> tuple[TenantInvitationRecord, OrganizationRecord, ApprovalRequest | None]:
    token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
    inv = db.query(TenantInvitationRecord).filter_by(token_hash=token_hash).first()
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid organization invitation token")
    if inv.status == "EXPIRED":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Organization invitation has expired")
    if inv.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invitation is no longer active (status={inv.status})",
        )
    if _normalize_dt_utc(inv.expires_at) < datetime.now(UTC):
        inv.status = "EXPIRED"
        db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Organization invitation has expired")
    if email_clean and inv.email.lower().strip() != email_clean:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invitation email does not match registering account email",
        )
    if inv.invited_role not in INVITABLE_TENANT_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invitation role is invalid")
    appr: ApprovalRequest | None = None
    if inv.invited_role == "tenant_admin":
        if not inv.approval_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant administrator grant requires an approved governance ApprovalRequest",
            )
        appr = db.get(ApprovalRequest, inv.approval_id)
        if not appr or appr.status != "APPROVED":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant administrator grant approval is missing or not APPROVED",
            )
        detail = appr.detail or {}
        if detail.get("consumed_by_user_id") or (
            detail.get("consumed_by_invitation_id") and detail.get("consumed_by_invitation_id") != inv.id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tenant administrator approval has already been consumed",
            )
        if detail.get("org_id") != inv.org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant administrator approval does not match target organization",
            )
    org = db.get(OrganizationRecord, inv.org_id)
    if not org or not org.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Target organization is inactive or unavailable",
        )
    return inv, org, appr


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login_user(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Authenticate user with email and password and issue a signed Bearer token."""
    email_clean = payload.email.lower().strip()
    user = db.query(UserRecord).filter(UserRecord.email == email_clean).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive or suspended",
        )

    # Validate password
    if not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    org = db.get(OrganizationRecord, user.org_id)
    if not org or not org.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization account is inactive or pending payment verification",
        )

    if user.org_id and user.role in {"owner", "platform_admin", "platform_owner"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid role scope on tenant account",
        )

    # Portal role validation
    is_admin = user.role in {"tenant_admin", "admin"}
    is_customer = user.role in {"customer", "member", "tenant_admin", "admin", "executive"}

    if payload.portal == "admin" and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for this portal",
        )

    org_name = org.name
    org_tier = org.tier

    user_meta = user.metadata_json if isinstance(user.metadata_json, dict) else {}
    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        org_id=user.org_id,
        password_hash=user.password_hash,
        token_version=int(user_meta.get("token_version") or 0),
    )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        org_id=user.org_id,
        org_name=org_name,
        org_tier=org_tier,
        portal_access={
            "admin": is_admin,
            "customer": is_customer,
        },
    )


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Register a least-privileged public customer account or join an existing org via verified invitation."""
    requested_role = (payload.role or "customer").strip().lower()
    if requested_role in PUBLIC_FORBIDDEN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Self-assignment of privileged roles ('admin', 'tenant_admin', 'manager', 'owner', "
                "'platform_admin') is forbidden on public registration."
            ),
        )
    if requested_role not in {"customer", "member"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Public registration supports only 'customer' or 'member' roles",
        )

    email_clean = payload.email.lower().strip()
    existing = db.query(UserRecord).filter(UserRecord.email == email_clean).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{email_clean}' already exists",
        )

    now = datetime.now(UTC)
    inv: TenantInvitationRecord | None = None
    inv_appr: ApprovalRequest | None = None
    if payload.invite_token and payload.invite_token.strip():
        inv, org, inv_appr = _validate_and_lock_invitation(db, payload.invite_token, email_clean=email_clean)
        assigned_role = inv.invited_role
    else:
        if not payload.company_name or not payload.company_name.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_name is required when registering without an invitation token",
            )
        slug_base = _slugify(payload.company_name)
        slug = f"{slug_base}-{str(uuid.uuid4())[:6]}"
        meta = {
            "package_key": "free",
            "entitled_capabilities": [],
            "subscription_status": "FREE_TIER",
        }
        if payload.gemini_api_key and payload.gemini_api_key.strip():
            meta["gemini_api_key"] = payload.gemini_api_key.strip()
        org = OrganizationRecord(
            name=payload.company_name.strip(),
            slug=slug,
            tier="free",
            lead_credits_limit=20,
            lead_credits_used=0,
            outreach_credits_limit=10,
            outreach_credits_used=0,
            is_active=True,
            metadata_json=meta,
        )
        db.add(org)
        db.flush()
        assigned_role = requested_role

    pwd_hash = hash_password(payload.password)
    user = UserRecord(
        org_id=org.id,
        email=email_clean,
        full_name=payload.full_name.strip(),
        role=assigned_role,
        password_hash=pwd_hash,
        is_active=True,
    )
    db.add(user)
    db.flush()

    if inv is not None:
        inv.status = "ACCEPTED"
        inv.accepted_by_user_id = user.id
        inv.accepted_at = now
        if inv_appr is not None:
            inv_appr.detail = {
                **dict(inv_appr.detail or {}),
                "consumed_by_user_id": user.id,
                "consumed_at": now.isoformat(),
            }
            flag_modified(inv_appr, "detail")

    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id="auth_gateway",
            capability_name="tenant_identity",
            action="invitation_accepted_on_register" if inv is not None else "public_user_registered",
            input_payload={
                "email": email_clean,
                "requested_role": requested_role,
                "invited": inv is not None,
            },
            output_payload={"org_id": org.id, "user_id": user.id, "granted_role": assigned_role},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(user)

    user_meta = user.metadata_json if isinstance(user.metadata_json, dict) else {}
    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        org_id=user.org_id,
        password_hash=user.password_hash,
        token_version=int(user_meta.get("token_version") or 0),
    )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        org_id=org.id,
        org_name=org.name,
        org_tier=org.tier,
        portal_access={
            "admin": user.role in TENANT_ADMIN_ROLES,
            "customer": True,
        },
    )


@router.post("/invitations/accept", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def accept_invitation(payload: AcceptInvitationRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Accept a single-use organization invitation (creates or binds user within invited tenant)."""
    now = datetime.now(UTC)
    inv, org, inv_appr = _validate_and_lock_invitation(db, payload.token)
    email_clean = inv.email.lower().strip()
    user = db.query(UserRecord).filter(UserRecord.email == email_clean).first()

    if user is None:
        if not payload.password or not payload.full_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="password and full_name are required when accepting an invitation as a new user",
            )
        user = UserRecord(
            org_id=org.id,
            email=email_clean,
            full_name=payload.full_name.strip(),
            role=inv.invited_role,
            password_hash=hash_password(payload.password),
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
        if user.org_id != org.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Existing account belongs to a different organization",
            )
        if not payload.password or not user.password_hash or not verify_password(payload.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid password is required to accept role invitation for existing account",
            )
        user.role = inv.invited_role

    inv.status = "ACCEPTED"
    inv.accepted_by_user_id = user.id
    inv.accepted_at = now
    if inv_appr is not None:
        inv_appr.detail = {
            **dict(inv_appr.detail or {}),
            "consumed_by_user_id": user.id,
            "consumed_at": now.isoformat(),
        }
        flag_modified(inv_appr, "detail")
    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id="auth_gateway",
            capability_name="tenant_identity",
            action="invitation_accepted",
            input_payload={"invitation_id": inv.id, "email": email_clean},
            output_payload={"org_id": org.id, "user_id": user.id, "granted_role": user.role},
            status="COMPLETED",
        )
    )
    db.commit()
    db.refresh(user)

    user_meta = user.metadata_json if isinstance(user.metadata_json, dict) else {}
    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        org_id=user.org_id,
        password_hash=user.password_hash,
        token_version=int(user_meta.get("token_version") or 0),
    )
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        org_id=org.id,
        org_name=org.name,
        org_tier=org.tier,
        portal_access={"admin": user.role in TENANT_ADMIN_ROLES, "customer": True},
    )


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup_customer(payload: SignupRequest, db: Session = Depends(get_db)) -> SignupResponse:
    """Self-serve new organization onboarding with server-assigned tenant_admin bootstrap only when verified/active."""
    email_clean = payload.email.lower().strip()
    existing = db.query(UserRecord).filter(UserRecord.email == email_clean).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{email_clean}' already exists",
        )

    # Lookup catalog package for entitlements & pricing
    pkg = get_package(payload.package_key) or CATALOG["company_os_starter"]

    # Create Organization with package entitlements
    slug_base = _slugify(payload.company_name)
    slug = f"{slug_base}-{str(uuid.uuid4())[:6]}"
    app_env = os.environ.get("APP_ENV", "development").casefold()
    is_active_initial = True if app_env != "production" else (pkg.price_inr == 0 and pkg.price_usd == 0)

    meta = {
        "package_key": pkg.key,
        "package_name": pkg.name,
        "category": pkg.category,
        "entitled_capabilities": list(pkg.entitled_capabilities),
        "payment_provider": payload.payment_provider,
        "subscription_status": "ACTIVE" if is_active_initial else "PENDING_PAYMENT",
    }
    if payload.gemini_api_key and payload.gemini_api_key.strip():
        meta["gemini_api_key"] = payload.gemini_api_key.strip()

    org = OrganizationRecord(
        name=payload.company_name.strip(),
        slug=slug,
        tier=pkg.tier,
        lead_credits_limit=pkg.lead_credits_monthly,
        lead_credits_used=0,
        outreach_credits_limit=pkg.outreach_credits_monthly,
        outreach_credits_used=0,
        is_active=is_active_initial,
        metadata_json=meta,
    )
    db.add(org)
    db.flush()

    # First verified owner creating a genuinely new org with zero existing admins receives org-scoped tenant_admin;
    # unpaid production PENDING_PAYMENT signups start as inactive 'customer' until payment verification promotes them.
    existing_admins = (
        db.query(UserRecord)
        .filter(UserRecord.org_id == org.id, UserRecord.role.in_(list(TENANT_ADMIN_ROLES)))
        .count()
    )
    if is_active_initial and existing_admins == 0:
        assigned_role = "tenant_admin"
        user_active = True
        signup_status = "registered"
        audit_action = "first_owner_tenant_admin_bootstrap"
    else:
        assigned_role = "customer"
        user_active = False
        signup_status = "PENDING_PAYMENT"
        audit_action = "customer_signup_pending_payment"

    pwd_hash = hash_password(payload.password)
    user = UserRecord(
        org_id=org.id,
        email=email_clean,
        full_name=payload.full_name.strip(),
        role=assigned_role,
        password_hash=pwd_hash,
        is_active=user_active,
        metadata_json={"first_owner_candidate": True},
    )
    db.add(user)
    db.flush()

    # Generate immediate checkout payment link
    checkout_url = build_payment_link(
        package_key=pkg.key,
        customer_email=email_clean,
        company=payload.company_name.strip(),
        provider=payload.payment_provider,
    )

    # Audit log: preserve customer_signed_up plus explicit first-owner admin grant record
    db.add(AuditLog(
        task_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
        agent_id="customer_portal",
        capability_name="customer_onboarding",
        action="customer_signed_up",
        input_payload={"email": email_clean, "package_key": pkg.key, "company": payload.company_name},
        output_payload={"org_id": org.id, "user_id": user.id, "tier": pkg.tier, "granted_role": assigned_role},
        status="COMPLETED",
    ))
    if assigned_role == "tenant_admin":
        db.add(AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id="customer_portal",
            capability_name="tenant_identity",
            action=audit_action,
            input_payload={"email": email_clean, "org_id": org.id},
            output_payload={"user_id": user.id, "granted_role": assigned_role},
            status="COMPLETED",
        ))

    db.commit()
    db.refresh(user)

    # Dispatch welcome onboarding email
    try:
        dispatcher = get_email_dispatcher()
        dispatcher.send(
            recipient_email=email_clean,
            subject=f"Welcome to AskforWrite — {pkg.name} Setup",
            body_text=(
                f"Hi {payload.full_name},\n\n"
                f"Thank you for signing up for AskforWrite Company OS!\n\n"
                f"Your dedicated workspace '{payload.company_name}' is ready:\n"
                f"• Selected Plan: {pkg.name}\n"
                f"• Monthly Discovery Credits: {pkg.lead_credits_monthly}\n"
                f"• Monthly Outreach Credits: {pkg.outreach_credits_monthly}\n\n"
                f"To activate all production capabilities, please complete your checkout:\n"
                f"{checkout_url}\n\n"
                f"Best regards,\n"
                f"AskforWrite Operations"
            ),
        )
    except Exception as exc:
        logger.error("Failed to dispatch onboarding email to %s: %s", email_clean, exc)

    token = (
        create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
            org_id=user.org_id,
        )
        if is_active_initial
        else None
    )

    return SignupResponse(
        status=signup_status,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        org_id=org.id,
        org_name=org.name,
        org_slug=org.slug,
        tier=org.tier,
        package_name=pkg.name,
        lead_credits_limit=org.lead_credits_limit,
        outreach_credits_limit=org.outreach_credits_limit,
        checkout_url=checkout_url,
        access_token=token,
        token_type="bearer",
    )


@router.get("/me", response_model=UserProfileResponse, status_code=status.HTTP_200_OK)

def get_current_user_profile(
    principal: APIPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    """Get profile and subscription credit balances for the authenticated user."""
    user = None
    if principal.user_id:
        user = db.get(UserRecord, principal.user_id)
    elif principal.email:
        user = db.query(UserRecord).filter(UserRecord.email == principal.email).first()

    if not user:
        # Fallback for API key principals (e.g. system owner)
        return UserProfileResponse(
            user_id="system-principal",
            email=principal.subject,
            full_name=principal.subject.capitalize(),
            role=principal.role,
            org_id="system-org",
            org_name="AskforWrite OS Master",
            tier="enterprise",
            lead_credits_remaining=9999,
            outreach_credits_remaining=9999,
            is_active=True,
        )

    org = db.get(OrganizationRecord, user.org_id)
    org_name = org.name if org else "Default Organization"
    tier = org.tier if org else "free"
    leads_rem = max(0, (org.lead_credits_limit - org.lead_credits_used)) if org else 0
    outreach_rem = max(0, (org.outreach_credits_limit - org.outreach_credits_used)) if org else 0

    return UserProfileResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        org_id=user.org_id,
        org_name=org_name,
        tier=tier,
        lead_credits_remaining=leads_rem,
        outreach_credits_remaining=outreach_rem,
        is_active=user.is_active,
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout_endpoint(
    authorization: str | None = Header(default=None),
    principal: APIPrincipal = Depends(get_current_principal),
) -> dict[str, str]:
    """Revoke the current bearer authentication token."""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        revoke_token(token)
    return {"status": "logged_out", "message": "Token revoked successfully"}
