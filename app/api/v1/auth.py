"""Authentication API router for Admin and Customer login accounts.

Provides:
- POST /v1/auth/login: Role-separated login for Admin vs Customer/Buyer
- POST /v1/auth/register: Customer / team user onboarding with password hashing
- GET /v1/auth/me: Returns current user profile, organization info, and credit balance
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import AuditLog, OrganizationRecord, UserRecord
from app.security.auth import (
    APIPrincipal,
    create_access_token,
    get_current_principal,
    hash_password,
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
    company_name: str = Field(min_length=2, max_length=200)
    role: Literal["admin", "customer", "member"] = "admin"
    gemini_api_key: str | None = Field(default=None, max_length=256)


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
    org_id: str
    org_name: str
    org_slug: str
    tier: str
    package_name: str
    lead_credits_limit: int
    outreach_credits_limit: int
    checkout_url: str
    access_token: str
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

    # Portal role validation
    is_admin = user.role in {"owner", "admin"}
    is_customer = user.role in {"customer", "member", "admin", "owner"}

    if payload.portal == "admin" and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for this portal",
        )

    org = db.get(OrganizationRecord, user.org_id)
    org_name = org.name if org else None
    org_tier = org.tier if org else None

    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        org_id=user.org_id,
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
    """Register a new customer organization and primary admin account."""
    email_clean = payload.email.lower().strip()
    existing = db.query(UserRecord).filter(UserRecord.email == email_clean).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{email_clean}' already exists",
        )

    # Create Organization
    slug_base = _slugify(payload.company_name)
    slug = f"{slug_base}-{str(uuid.uuid4())[:6]}"
    meta = {}
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

    # Create User
    pwd_hash = hash_password(payload.password)
    user = UserRecord(
        org_id=org.id,
        email=email_clean,
        full_name=payload.full_name.strip(),
        role=payload.role,
        password_hash=pwd_hash,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        org_id=user.org_id,
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
            "admin": user.role in {"owner", "admin"},
            "customer": True,
        },
    )


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup_customer(payload: SignupRequest, db: Session = Depends(get_db)) -> SignupResponse:
    """Self-serve customer onboarding with catalog plan selection and direct checkout URL."""
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
    meta = {
        "package_key": pkg.key,
        "package_name": pkg.name,
        "category": pkg.category,
        "entitled_capabilities": list(pkg.entitled_capabilities),
        "payment_provider": payload.payment_provider,
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
        is_active=True,
        metadata_json=meta,
    )
    db.add(org)
    db.flush()

    # Create Primary Admin User
    pwd_hash = hash_password(payload.password)
    user = UserRecord(
        org_id=org.id,
        email=email_clean,
        full_name=payload.full_name.strip(),
        role="admin",
        password_hash=pwd_hash,
        is_active=True,
    )
    db.add(user)

    # Generate immediate checkout payment link
    checkout_url = build_payment_link(
        package_key=pkg.key,
        customer_email=email_clean,
        company=payload.company_name.strip(),
        provider=payload.payment_provider,
    )

    # Audit log
    db.add(AuditLog(
        task_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
        agent_id="customer_portal",
        capability_name="customer_onboarding",
        action="customer_signed_up",
        input_payload={"email": email_clean, "package_key": pkg.key, "company": payload.company_name},
        output_payload={"org_id": org.id, "user_id": user.id, "tier": pkg.tier},
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

    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        org_id=user.org_id,
    )

    return SignupResponse(
        status="registered",
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
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
