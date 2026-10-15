"""Razorpay payment provider implementation.

Uses the official ``razorpay`` Python SDK for:
- Customer creation / retrieval
- Plan management
- Subscription lifecycle
- Webhook signature verification (HMAC-SHA256)

Environment variables consumed:
    RAZORPAY_KEY_ID          – API key (public)
    RAZORPAY_KEY_SECRET      – API secret (private, used for HMAC)
    RAZORPAY_ACCOUNT_ID      – Merchant account ID (informational)
    RAZORPAY_WEBHOOK_SECRET  – Webhook verification secret (optional override)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from typing import Any

import httpx

from app.services.payment import (
    CustomerInfo,
    PaymentProvider,
    PaymentProviderError,
    PaymentProviderInterface,
    PaymentValidationError,
    PlanInfo,
    SubscriptionInfo,
    SubscriptionStatus,
    WebhookEvent,
    register_provider,
)

logger = logging.getLogger(__name__)

# ── Status mapping ───────────────────────────────────────────────────

_RAZORPAY_STATUS_MAP: dict[str, SubscriptionStatus] = {
    "created": SubscriptionStatus.CREATED,
    "authenticated": SubscriptionStatus.AUTHENTICATED,
    "active": SubscriptionStatus.ACTIVE,
    "paused": SubscriptionStatus.PAUSED,
    "halted": SubscriptionStatus.HALTED,
    "cancelled": SubscriptionStatus.CANCELLED,
    "completed": SubscriptionStatus.COMPLETED,
    "expired": SubscriptionStatus.EXPIRED,
    "pending": SubscriptionStatus.PENDING,
}

# ── Event type normalization ─────────────────────────────────────────

_RAZORPAY_EVENT_MAP: dict[str, str] = {
    "subscription.authenticated": "subscription.authenticated",
    "subscription.activated": "subscription.activated",
    "subscription.charged": "subscription.charged",
    "subscription.completed": "subscription.completed",
    "subscription.updated": "subscription.updated",
    "subscription.pending": "subscription.pending",
    "subscription.halted": "subscription.halted",
    "subscription.cancelled": "subscription.cancelled",
    "subscription.paused": "subscription.paused",
    "subscription.resumed": "subscription.resumed",
    "payment.authorized": "payment.authorized",
    "payment.captured": "payment.captured",
    "payment.failed": "payment.failed",
}


@register_provider(PaymentProvider.RAZORPAY)
class RazorpayProvider(PaymentProviderInterface):
    """Razorpay payment provider backed by the REST API via httpx."""

    BASE_URL = "https://api.razorpay.com/v1"

    def __init__(self) -> None:
        self._key_id = os.environ.get("RAZORPAY_KEY_ID", "")
        self._key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
        self._webhook_secret = os.environ.get(
            "RAZORPAY_WEBHOOK_SECRET",
            self._key_secret,  # Fallback to key secret for webhook verification
        )
        if not self._key_id:
            logger.warning("RAZORPAY_KEY_ID is not configured")

    @property
    def provider_name(self) -> PaymentProvider:
        return PaymentProvider.RAZORPAY

    # ── HTTP helpers ─────────────────────────────────────────────

    def _auth(self) -> tuple[str, str]:
        return (self._key_id, self._key_secret)

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    auth=self._auth(),
                    json=json_data,
                    params=params,
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text
                logger.error(
                    "Razorpay API error: %s %s -> %d: %s",
                    method, url, exc.response.status_code, body,
                )
                raise PaymentProviderError(
                    f"Razorpay error {exc.response.status_code}: {body}"
                ) from exc
            except httpx.RequestError as exc:
                raise PaymentProviderError(
                    f"Razorpay connection error: {exc}"
                ) from exc

    # ── Customer ─────────────────────────────────────────────────

    async def create_customer(
        self,
        email: str,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> CustomerInfo:
        payload: dict[str, Any] = {
            "name": name,
            "email": email,
            "fail_existing": 0,  # Return existing customer instead of error
        }
        if metadata:
            payload["notes"] = metadata

        data = await self._request("POST", "/customers", json_data=payload)
        return CustomerInfo(
            id=str(uuid.uuid4()),
            email=data.get("email", email),
            name=data.get("name", name),
            provider=PaymentProvider.RAZORPAY,
            provider_customer_id=data["id"],
            metadata=data.get("notes", {}),
        )

    async def get_customer(self, provider_customer_id: str) -> CustomerInfo:
        data = await self._request("GET", f"/customers/{provider_customer_id}")
        return CustomerInfo(
            id=str(uuid.uuid4()),
            email=data.get("email", ""),
            name=data.get("name", ""),
            provider=PaymentProvider.RAZORPAY,
            provider_customer_id=data["id"],
            metadata=data.get("notes", {}),
        )

    # ── Plan ─────────────────────────────────────────────────────

    async def create_plan(
        self,
        name: str,
        amount: int,
        currency: str,
        interval: str,
        metadata: dict[str, Any] | None = None,
    ) -> PlanInfo:
        # Razorpay uses period/interval mapping
        period_map = {
            "monthly": ("monthly", 1),
            "yearly": ("yearly", 1),
            "weekly": ("weekly", 1),
            "daily": ("daily", 1),
        }
        period, count = period_map.get(interval, ("monthly", 1))

        payload: dict[str, Any] = {
            "period": period,
            "interval": count,
            "item": {
                "name": name,
                "amount": amount,
                "currency": currency.upper(),
            },
        }
        if metadata:
            payload["notes"] = metadata

        data = await self._request("POST", "/plans", json_data=payload)
        return PlanInfo(
            id=str(uuid.uuid4()),
            name=name,
            amount=amount,
            currency=currency.upper(),
            interval=interval,
            provider=PaymentProvider.RAZORPAY,
            provider_plan_id=data["id"],
            metadata=data.get("notes", {}),
        )

    async def get_plan(self, provider_plan_id: str) -> PlanInfo:
        data = await self._request("GET", f"/plans/{provider_plan_id}")
        item = data.get("item", {})
        return PlanInfo(
            id=str(uuid.uuid4()),
            name=item.get("name", ""),
            amount=item.get("amount", 0),
            currency=item.get("currency", "INR"),
            interval=data.get("period", "monthly"),
            provider=PaymentProvider.RAZORPAY,
            provider_plan_id=data["id"],
            metadata=data.get("notes", {}),
        )

    # ── Subscription ─────────────────────────────────────────────

    async def create_subscription(
        self,
        customer_id: str,
        plan_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> SubscriptionInfo:
        payload: dict[str, Any] = {
            "plan_id": plan_id,
            "total_count": 120,  # Max billing cycles
            "quantity": 1,
            "customer_id": customer_id,
        }
        if metadata:
            payload["notes"] = metadata

        data = await self._request("POST", "/subscriptions", json_data=payload)
        status_str = data.get("status", "created")

        return SubscriptionInfo(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            plan_id=plan_id,
            status=_RAZORPAY_STATUS_MAP.get(status_str, SubscriptionStatus.CREATED),
            provider=PaymentProvider.RAZORPAY,
            provider_subscription_id=data["id"],
            current_period_start=str(data.get("current_start", "")),
            current_period_end=str(data.get("current_end", "")),
            payment_url=data.get("short_url"),
            metadata=data.get("notes", {}),
        )

    async def get_subscription(self, provider_subscription_id: str) -> SubscriptionInfo:
        data = await self._request("GET", f"/subscriptions/{provider_subscription_id}")
        status_str = data.get("status", "created")

        return SubscriptionInfo(
            id=str(uuid.uuid4()),
            customer_id=data.get("customer_id", ""),
            plan_id=data.get("plan_id", ""),
            status=_RAZORPAY_STATUS_MAP.get(status_str, SubscriptionStatus.CREATED),
            provider=PaymentProvider.RAZORPAY,
            provider_subscription_id=data["id"],
            current_period_start=str(data.get("current_start", "")),
            current_period_end=str(data.get("current_end", "")),
            payment_url=data.get("short_url"),
            metadata=data.get("notes", {}),
        )

    async def cancel_subscription(
        self,
        provider_subscription_id: str,
        cancel_at_period_end: bool = True,
    ) -> SubscriptionInfo:
        payload = {"cancel_at_cycle_end": 1 if cancel_at_period_end else 0}
        data = await self._request(
            "POST",
            f"/subscriptions/{provider_subscription_id}/cancel",
            json_data=payload,
        )
        status_str = data.get("status", "cancelled")

        return SubscriptionInfo(
            id=str(uuid.uuid4()),
            customer_id=data.get("customer_id", ""),
            plan_id=data.get("plan_id", ""),
            status=_RAZORPAY_STATUS_MAP.get(status_str, SubscriptionStatus.CANCELLED),
            provider=PaymentProvider.RAZORPAY,
            provider_subscription_id=data["id"],
            metadata=data.get("notes", {}),
        )

    # ── Webhook ──────────────────────────────────────────────────

    async def verify_webhook(
        self,
        payload: bytes,
        headers: dict[str, str],
    ) -> bool:
        signature = headers.get("x-razorpay-signature", "")
        if not signature or not self._webhook_secret:
            return False

        expected = hmac.new(
            self._webhook_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def parse_webhook_event(
        self,
        payload: bytes,
        headers: dict[str, str],
    ) -> WebhookEvent:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise PaymentValidationError(f"Invalid JSON payload: {exc}") from exc

        raw_event_type = data.get("event", "unknown")
        event_type = _RAZORPAY_EVENT_MAP.get(raw_event_type, raw_event_type)

        # Extract the entity from the payload
        entity_data = data.get("payload", {})
        resource_type = "unknown"
        resource_id = ""

        if "subscription" in entity_data:
            resource_type = "subscription"
            entity = entity_data["subscription"].get("entity", {})
            resource_id = entity.get("id", "")
        elif "payment" in entity_data:
            resource_type = "payment"
            entity = entity_data["payment"].get("entity", {})
            resource_id = entity.get("id", "")

        return WebhookEvent(
            id=data.get("event_id", str(uuid.uuid4())),
            provider=PaymentProvider.RAZORPAY,
            event_type=event_type,
            raw_event_type=raw_event_type,
            resource_id=resource_id,
            resource_type=resource_type,
            data=data,
        )
