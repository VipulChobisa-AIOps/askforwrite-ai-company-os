"""Subscription management API router.

Provides endpoints for:
- Creating customers
- Creating plans
- Managing subscriptions (create, get, cancel)
- Listing subscriptions for a customer

All operations delegate to the unified payment abstraction layer,
which routes to Razorpay or PayPal based on configuration.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import app.services.payment_paypal

# Ensure provider modules are imported so @register_provider decorators execute
import app.services.payment_razorpay  # noqa: F401
from app.db.database import get_db
from app.db.models import (
    AuditLog,
    CustomerRecord,
    SubscriptionRecord,
)
from app.security.auth import APIPrincipal, require_manager, require_owner
from app.services.payment import (
    PaymentError,
    PaymentProvider,
    PaymentProviderError,
    get_payment_provider,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/subscriptions", tags=["subscriptions"])

# ── Payment links ────────────────────────────────────────────────────

_PAYMENT_LINKS: dict[str, str] = {
    "razorpay": os.environ.get("RAZORPAY_PAYMENT_LINK", "https://razorpay.me/@askforwrite"),
    "paypal": os.environ.get("PAYPAL_PAYMENT_LINK", "https://paypal.me/ask4write"),
}


def _payment_link(provider: str, sub_payment_url: str | None = None) -> str:
    """Return the most specific payment URL available.

    Razorpay generates a per-subscription short URL — prefer that.
    PayPal returns an approval URL — prefer that.
    Fall back to the static payment page link.
    """
    return sub_payment_url or _PAYMENT_LINKS.get(provider, "")


# ── Request / response schemas ───────────────────────────────────────


class CreateCustomerRequest(BaseModel):
    email: str = Field(..., description="Customer email address")
    name: str = Field(..., description="Customer full name")
    provider: str = Field(
        default="razorpay",
        description="Payment provider: 'razorpay' or 'paypal'",
    )
    org_id: str | None = Field(default=None, description="Optional organization ID for multi-tenant billing")
    metadata: dict | None = Field(default=None, description="Additional metadata")


class CreatePlanRequest(BaseModel):
    name: str = Field(..., description="Plan name")
    amount: int = Field(..., gt=0, description="Amount in smallest currency unit (paise/cents)")
    currency: str = Field(default="INR", description="Currency code")
    interval: str = Field(default="monthly", description="Billing interval: monthly, yearly, weekly, daily")
    provider: str = Field(default="razorpay", description="Payment provider")
    metadata: dict | None = Field(default=None, description="Additional metadata")


class CreateSubscriptionRequest(BaseModel):
    customer_id: str = Field(..., description="Internal customer ID (from create_customer)")
    plan_id: str = Field(..., description="Provider plan ID")
    provider: str = Field(default="razorpay", description="Payment provider")
    org_id: str | None = Field(default=None, description="Optional organization ID for multi-tenant billing")
    metadata: dict | None = Field(default=None, description="Additional metadata")


class CancelSubscriptionRequest(BaseModel):
    cancel_at_period_end: bool = Field(
        default=True,
        description="If true, subscription ends at current billing cycle",
    )


# ── Helper ───────────────────────────────────────────────────────────


def _resolve_provider(provider_str: str) -> PaymentProvider:
    try:
        return PaymentProvider(provider_str.lower())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown provider '{provider_str}'. Use 'razorpay' or 'paypal'.",
        )


# ── Endpoints ────────────────────────────────────────────────────────


@router.post("/customers")
async def create_customer_endpoint(
    payload: CreateCustomerRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    """Create a customer on the payment provider and persist locally."""
    correlation_id = x_correlation_id or str(uuid.uuid4())

    provider_enum = _resolve_provider(payload.provider)
    provider = get_payment_provider(provider_enum)

    try:
        customer_info = await provider.create_customer(
            email=payload.email,
            name=payload.name,
            metadata=payload.metadata,
        )
    except PaymentProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PaymentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Persist locally
    record = CustomerRecord(
        id=customer_info.id,
        org_id=payload.org_id,
        email=customer_info.email,
        name=customer_info.name,
        provider=customer_info.provider.value,
        provider_customer_id=customer_info.provider_customer_id,
        metadata_json=customer_info.metadata,
    )
    db.add(record)

    audit = AuditLog(
        task_id=correlation_id,
        correlation_id=correlation_id,
        agent_id=principal.subject,
        capability_name="payment",
        action="create_customer",
        input_payload={"email": payload.email, "provider": payload.provider},
        output_payload={"customer_id": customer_info.id, "provider_customer_id": customer_info.provider_customer_id},
        status="COMPLETED",
    )
    db.add(audit)
    db.commit()

    return {
        "status": "created",
        "customer_id": customer_info.id,
        "provider": customer_info.provider.value,
        "provider_customer_id": customer_info.provider_customer_id,
        "email": customer_info.email,
        "name": customer_info.name,
    }


@router.post("/plans")
async def create_plan_endpoint(
    payload: CreatePlanRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    """Create a billing plan on the payment provider."""
    correlation_id = x_correlation_id or str(uuid.uuid4())

    provider_enum = _resolve_provider(payload.provider)
    provider = get_payment_provider(provider_enum)

    try:
        plan_info = await provider.create_plan(
            name=payload.name,
            amount=payload.amount,
            currency=payload.currency,
            interval=payload.interval,
            metadata=payload.metadata,
        )
    except PaymentProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PaymentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    audit = AuditLog(
        task_id=correlation_id,
        correlation_id=correlation_id,
        agent_id=principal.subject,
        capability_name="payment",
        action="create_plan",
        input_payload={"name": payload.name, "amount": payload.amount, "provider": payload.provider},
        output_payload={"plan_id": plan_info.provider_plan_id},
        status="COMPLETED",
    )
    db.add(audit)
    db.commit()

    return {
        "status": "created",
        "plan_id": plan_info.id,
        "provider": plan_info.provider.value,
        "provider_plan_id": plan_info.provider_plan_id,
        "name": plan_info.name,
        "amount": plan_info.amount,
        "currency": plan_info.currency,
        "interval": plan_info.interval,
    }


@router.post("/create")
async def create_subscription_endpoint(
    payload: CreateSubscriptionRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    """Create a new subscription for a customer."""
    correlation_id = x_correlation_id or str(uuid.uuid4())

    # Verify customer exists locally
    customer = db.query(CustomerRecord).filter_by(id=payload.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer {payload.customer_id} not found")

    provider_enum = _resolve_provider(payload.provider)
    provider = get_payment_provider(provider_enum)

    try:
        sub_info = await provider.create_subscription(
            customer_id=customer.provider_customer_id,
            plan_id=payload.plan_id,
            metadata=payload.metadata,
        )
    except PaymentProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PaymentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Persist locally
    target_org_id = payload.org_id or getattr(customer, "org_id", None)
    record = SubscriptionRecord(
        id=sub_info.id,
        org_id=target_org_id,
        customer_id=payload.customer_id,
        plan_id=payload.plan_id,
        provider=sub_info.provider.value,
        provider_subscription_id=sub_info.provider_subscription_id,
        status=sub_info.status.value,
        current_period_start=sub_info.current_period_start,
        current_period_end=sub_info.current_period_end,
        payment_url=sub_info.payment_url,
        metadata_json=sub_info.metadata,
    )
    db.add(record)

    audit = AuditLog(
        task_id=correlation_id,
        correlation_id=correlation_id,
        agent_id=principal.subject,
        capability_name="payment",
        action="create_subscription",
        input_payload={"customer_id": payload.customer_id, "plan_id": payload.plan_id},
        output_payload={"subscription_id": sub_info.id, "status": sub_info.status.value},
        status="COMPLETED",
    )
    db.add(audit)
    db.commit()

    return {
        "status": sub_info.status.value,
        "subscription_id": sub_info.id,
        "provider": sub_info.provider.value,
        "provider_subscription_id": sub_info.provider_subscription_id,
        "payment_url": _payment_link(sub_info.provider.value, sub_info.payment_url),
        "customer_id": payload.customer_id,
        "plan_id": payload.plan_id,
    }


@router.get("/{subscription_id}")
async def get_subscription_endpoint(
    subscription_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    """Retrieve subscription status (syncs with provider)."""
    record = db.query(SubscriptionRecord).filter_by(id=subscription_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Subscription not found")

    provider_enum = _resolve_provider(record.provider)
    provider = get_payment_provider(provider_enum)

    try:
        sub_info = await provider.get_subscription(record.provider_subscription_id)
    except PaymentProviderError as exc:
        # Return local data if provider is unreachable
        logger.warning("Provider unavailable, returning cached data: %s", exc)
        return {
            "subscription_id": record.id,
            "provider": record.provider,
            "status": record.status,
            "customer_id": record.customer_id,
            "plan_id": record.plan_id,
            "synced": False,
        }

    # Update local record
    record.status = sub_info.status.value
    record.current_period_start = sub_info.current_period_start
    record.current_period_end = sub_info.current_period_end
    record.updated_at = datetime.now(UTC)
    db.commit()

    return {
        "subscription_id": record.id,
        "provider": record.provider,
        "provider_subscription_id": record.provider_subscription_id,
        "status": sub_info.status.value,
        "customer_id": record.customer_id,
        "plan_id": record.plan_id,
        "current_period_start": sub_info.current_period_start,
        "current_period_end": sub_info.current_period_end,
        "payment_url": record.payment_url,
        "synced": True,
    }


@router.post("/{subscription_id}/cancel")
async def cancel_subscription_endpoint(
    subscription_id: str,
    payload: CancelSubscriptionRequest,
    x_correlation_id: str | None = Header(default=None),
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    """Cancel a subscription (owner-only)."""
    correlation_id = x_correlation_id or str(uuid.uuid4())

    record = db.query(SubscriptionRecord).filter_by(id=subscription_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Subscription not found")

    provider_enum = _resolve_provider(record.provider)
    provider = get_payment_provider(provider_enum)

    try:
        sub_info = await provider.cancel_subscription(
            provider_subscription_id=record.provider_subscription_id,
            cancel_at_period_end=payload.cancel_at_period_end,
        )
    except PaymentProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PaymentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    record.status = sub_info.status.value
    record.updated_at = datetime.now(UTC)

    audit = AuditLog(
        task_id=correlation_id,
        correlation_id=correlation_id,
        agent_id=principal.subject,
        capability_name="payment",
        action="cancel_subscription",
        input_payload={"subscription_id": subscription_id, "cancel_at_period_end": payload.cancel_at_period_end},
        output_payload={"status": sub_info.status.value},
        status="COMPLETED",
    )
    db.add(audit)
    db.commit()

    return {
        "status": sub_info.status.value,
        "subscription_id": record.id,
        "provider": record.provider,
        "message": "Subscription cancelled"
            + (" at period end" if payload.cancel_at_period_end else " immediately"),
    }


@router.get("/customer/{customer_id}")
async def list_customer_subscriptions(
    customer_id: str,
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    """List all subscriptions for a customer."""
    records = db.query(SubscriptionRecord).filter_by(customer_id=customer_id).all()
    return {
        "customer_id": customer_id,
        "count": len(records),
        "subscriptions": [
            {
                "subscription_id": r.id,
                "provider": r.provider,
                "provider_subscription_id": r.provider_subscription_id,
                "status": r.status,
                "plan_id": r.plan_id,
                "payment_url": r.payment_url,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    }
