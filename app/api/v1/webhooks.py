"""Unified payment webhook endpoint.

Handles incoming webhooks from both Razorpay and PayPal:
- Auto-detects the source provider from request headers
- Verifies signature authenticity
- Persists event to audit trail
- Updates local subscription status

Route: POST /v1/webhooks/payment
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.services.payment_paypal

# Ensure provider modules are imported so @register_provider decorators execute
import app.services.payment_razorpay  # noqa: F401
from app.db.database import get_db
from app.db.models import AuditLog, InvoiceRecord, SubscriptionRecord, WebhookEventRecord
from app.security.auth import APIPrincipal, require_manager
from app.services.payment import (
    PaymentProvider,
    PaymentValidationError,
    get_payment_provider,
)
from app.services.provisioning import auto_provision_tenant_on_payment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


# ── Provider detection ───────────────────────────────────────────────


def _detect_provider(headers: dict[str, str]) -> PaymentProvider:
    """Determine the webhook source from HTTP headers.

    Razorpay sends: x-razorpay-signature
    PayPal sends:   paypal-transmission-id, paypal-auth-algo
    """
    if "x-razorpay-signature" in headers:
        return PaymentProvider.RAZORPAY
    if "paypal-transmission-id" in headers or "paypal-auth-algo" in headers:
        return PaymentProvider.PAYPAL
    raise HTTPException(
        status_code=400,
        detail="Unable to determine payment provider from webhook headers",
    )


# ── Status sync mapping ─────────────────────────────────────────────

_SUBSCRIPTION_STATUS_EVENTS: dict[str, str] = {
    "subscription.activated": "active",
    "subscription.authenticated": "authenticated",
    "subscription.charged": "active",
    "subscription.completed": "completed",
    "subscription.cancelled": "cancelled",
    "subscription.halted": "halted",
    "subscription.paused": "paused",
    "subscription.resumed": "active",
    "subscription.pending": "pending",
    "subscription.created": "created",
}


# ── Endpoint ─────────────────────────────────────────────────────────


@router.post("/payment")
async def payment_webhook_endpoint(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Unified webhook receiver for Razorpay and PayPal.

    This endpoint:
    1. Reads the raw request body
    2. Detects the provider from headers
    3. Verifies the webhook signature
    4. Parses and normalizes the event
    5. Persists the event for audit
    6. Updates local subscription status if applicable
    """
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    # Step 1: Detect provider
    provider_enum = _detect_provider(headers)
    provider = get_payment_provider(provider_enum)

    # Step 2: Verify signature
    is_valid = await provider.verify_webhook(raw_body, headers)
    if not is_valid:
        logger.warning(
            "Webhook signature verification failed for provider=%s",
            provider_enum.value,
        )
        raise HTTPException(status_code=401, detail="Webhook signature verification failed")

    # Step 3: Parse event
    try:
        event = await provider.parse_webhook_event(raw_body, headers)
    except PaymentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "Received webhook: provider=%s event=%s resource=%s",
        event.provider.value,
        event.event_type,
        event.resource_id,
    )

    # Step 4: Persist event (idempotent — skip duplicates)
    event_record = WebhookEventRecord(
        provider=event.provider.value,
        provider_event_id=event.id,
        event_type=event.event_type,
        raw_event_type=event.raw_event_type,
        resource_id=event.resource_id,
        resource_type=event.resource_type,
        payload=event.data,
        processed=False,
    )
    db.add(event_record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.info("Duplicate webhook event %s — skipping", event.id)
        return {"status": "duplicate", "event_id": event.id}

    # Step 5: Update subscription status if this is a subscription event
    new_status = _SUBSCRIPTION_STATUS_EVENTS.get(event.event_type)
    if new_status and event.resource_id:
        sub_record = db.query(SubscriptionRecord).filter_by(
            provider=event.provider.value,
            provider_subscription_id=event.resource_id,
        ).first()

        if sub_record:
            old_status = sub_record.status
            sub_record.status = new_status
            sub_record.updated_at = datetime.now(UTC)
            logger.info(
                "Subscription %s status: %s -> %s",
                sub_record.id, old_status, new_status,
            )
        else:
            logger.warning(
                "Webhook references unknown subscription %s (provider=%s)",
                event.resource_id,
                event.provider.value,
            )

    # Step 6: Audit log
    correlation_id = str(uuid.uuid4())
    audit = AuditLog(
        task_id=correlation_id,
        correlation_id=correlation_id,
        agent_id="webhook",
        capability_name="payment_webhook",
        action=event.event_type,
        input_payload={
            "provider": event.provider.value,
            "event_type": event.raw_event_type,
            "resource_id": event.resource_id,
        },
        output_payload={"status": "processed", "new_status": new_status},
        status="COMPLETED",
    )
    db.add(audit)

    # Auto-provision tenant if confirmed payment or activated subscription
    provision_result = auto_provision_tenant_on_payment(db=db, event=event)

    # Step 6b: Handle refund, dispute, settlement, and failed payment lifecycle transitions
    raw_ev = (event.raw_event_type or event.event_type or "").lower()
    if any(k in raw_ev for k in ("refund", "dispute", "settlement", "failed", "denied")):
        from sqlalchemy.orm.attributes import flag_modified

        inv = None
        if event.resource_id:
            inv = (
                db.query(InvoiceRecord)
                .filter(
                    (InvoiceRecord.provider_payment_id == event.resource_id)
                    | (InvoiceRecord.provider_invoice_id == event.resource_id)
                )
                .first()
            )
        if inv:
            meta = dict(inv.metadata_json or {})
            if "refund" in raw_ev:
                inv.status = "refunded"
                meta["settlement_status"] = "REFUND_COMPLETED" if "processed" in raw_ev or "completed" in raw_ev else "REFUND_INITIATED"
                meta["refund_event_id"] = event.id
            elif "dispute" in raw_ev:
                inv.status = "disputed"
                meta["settlement_status"] = "DISPUTED"
            elif "settlement" in raw_ev:
                meta["settlement_status"] = "SETTLED"
                meta["settled_event_id"] = event.id
            elif "failed" in raw_ev or "denied" in raw_ev:
                inv.status = "failed"
                meta["settlement_status"] = "PAYMENT_FAILED"
            inv.metadata_json = meta
            flag_modified(inv, "metadata_json")

    # Mark event as processed
    event_record.processed = True
    db.commit()

    resp_payload: dict[str, object] = {
        "status": "processed",
        "provider": event.provider.value,
        "event_type": event.event_type,
        "resource_id": event.resource_id,
    }
    if provision_result:
        resp_payload["provisioning"] = provision_result

    return resp_payload


@router.get("/events")
async def list_webhook_events(
    provider: str | None = None,
    event_type: str | None = None,
    limit: int = 50,
    _principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    """List recent webhook events (for debugging/audit)."""
    query = db.query(WebhookEventRecord).order_by(WebhookEventRecord.created_at.desc())

    if provider:
        query = query.filter(WebhookEventRecord.provider == provider)
    if event_type:
        query = query.filter(WebhookEventRecord.event_type == event_type)

    records = query.limit(limit).all()
    return {
        "count": len(records),
        "events": [
            {
                "id": r.id,
                "provider": r.provider,
                "event_type": r.event_type,
                "raw_event_type": r.raw_event_type,
                "resource_id": r.resource_id,
                "resource_type": r.resource_type,
                "processed": r.processed,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    }
