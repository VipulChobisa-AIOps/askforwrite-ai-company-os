"""PayPal payment provider implementation.

Uses the PayPal REST API v1/v2 via httpx for:
- Product/plan management
- Subscription lifecycle (create, cancel, fetch)
- Webhook signature verification via PayPal's verification endpoint

Environment variables consumed:
    PAYPAL_CLIENT_ID        – OAuth2 client ID
    PAYPAL_CLIENT_SECRET    – OAuth2 client secret
    PAYPAL_WEBHOOK_ID       – Webhook ID for signature verification
    PAYPAL_WEBHOOK_SECRET   – Webhook secret (informational / backup)
    PAYPAL_MODE             – "sandbox" or "live" (default "live")
"""

from __future__ import annotations

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

_PAYPAL_STATUS_MAP: dict[str, SubscriptionStatus] = {
    "APPROVAL_PENDING": SubscriptionStatus.PENDING,
    "APPROVED": SubscriptionStatus.AUTHENTICATED,
    "ACTIVE": SubscriptionStatus.ACTIVE,
    "SUSPENDED": SubscriptionStatus.PAUSED,
    "CANCELLED": SubscriptionStatus.CANCELLED,
    "EXPIRED": SubscriptionStatus.EXPIRED,
}

# ── Event type normalization ─────────────────────────────────────────

_PAYPAL_EVENT_MAP: dict[str, str] = {
    "BILLING.SUBSCRIPTION.CREATED": "subscription.created",
    "BILLING.SUBSCRIPTION.ACTIVATED": "subscription.activated",
    "BILLING.SUBSCRIPTION.UPDATED": "subscription.updated",
    "BILLING.SUBSCRIPTION.EXPIRED": "subscription.expired",
    "BILLING.SUBSCRIPTION.CANCELLED": "subscription.cancelled",
    "BILLING.SUBSCRIPTION.SUSPENDED": "subscription.paused",
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED": "subscription.halted",
    "PAYMENT.SALE.COMPLETED": "payment.captured",
    "PAYMENT.SALE.DENIED": "payment.failed",
    "PAYMENT.SALE.REFUNDED": "payment.refunded",
}

# ── Interval mapping ────────────────────────────────────────────────

_INTERVAL_MAP: dict[str, tuple[str, int]] = {
    "monthly": ("MONTH", 1),
    "yearly": ("YEAR", 1),
    "weekly": ("WEEK", 1),
    "daily": ("DAY", 1),
}


@register_provider(PaymentProvider.PAYPAL)
class PayPalProvider(PaymentProviderInterface):
    """PayPal payment provider backed by the REST API via httpx."""

    SANDBOX_URL = "https://api-m.sandbox.paypal.com"
    LIVE_URL = "https://api-m.paypal.com"

    def __init__(self) -> None:
        self._client_id = os.environ.get("PAYPAL_CLIENT_ID", "")
        self._client_secret = os.environ.get("PAYPAL_CLIENT_SECRET", "")
        self._webhook_id = os.environ.get("PAYPAL_WEBHOOK_ID", "")
        mode = os.environ.get("PAYPAL_MODE", "live").lower()
        self._base_url = self.SANDBOX_URL if mode == "sandbox" else self.LIVE_URL
        self._access_token: str | None = None

        if not self._client_id:
            logger.warning("PAYPAL_CLIENT_ID is not configured")

    @property
    def provider_name(self) -> PaymentProvider:
        return PaymentProvider.PAYPAL

    # ── OAuth2 token ─────────────────────────────────────────────

    async def _get_access_token(self) -> str:
        """Obtain an OAuth2 access token (cached until expiry)."""
        if self._access_token:
            return self._access_token

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self._base_url}/v1/oauth2/token",
                    auth=(self._client_id, self._client_secret),
                    data={"grant_type": "client_credentials"},
                    headers={"Accept": "application/json"},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                self._access_token = data["access_token"]
                return self._access_token
            except httpx.HTTPStatusError as exc:
                raise PaymentProviderError(
                    f"PayPal OAuth error {exc.response.status_code}: {exc.response.text}"
                ) from exc

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        token = await self._get_access_token()
        url = f"{self._base_url}{path}"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    json=json_data,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                if response.status_code == 204:
                    return {}
                return response.json()
            except httpx.HTTPStatusError as exc:
                # Token may have expired, retry once
                if exc.response.status_code == 401:
                    self._access_token = None
                    token = await self._get_access_token()
                    retry = await client.request(
                        method=method,
                        url=url,
                        json=json_data,
                        params=params,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        timeout=30.0,
                    )
                    retry.raise_for_status()
                    return retry.json() if retry.status_code != 204 else {}
                body = exc.response.text
                logger.error(
                    "PayPal API error: %s %s -> %d: %s",
                    method, url, exc.response.status_code, body,
                )
                raise PaymentProviderError(
                    f"PayPal error {exc.response.status_code}: {body}"
                ) from exc
            except httpx.RequestError as exc:
                raise PaymentProviderError(
                    f"PayPal connection error: {exc}"
                ) from exc

    # ── Customer ─────────────────────────────────────────────────
    # PayPal does not have a dedicated customer/create API for
    # subscriptions; a subscriber is created inline with the
    # subscription. We return a synthetic customer object.

    async def create_customer(
        self,
        email: str,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> CustomerInfo:
        customer_id = str(uuid.uuid4())
        return CustomerInfo(
            id=customer_id,
            email=email,
            name=name,
            provider=PaymentProvider.PAYPAL,
            provider_customer_id=customer_id,  # Synthetic for PayPal
            metadata=metadata or {},
        )

    async def get_customer(self, provider_customer_id: str) -> CustomerInfo:
        # PayPal subscription holds subscriber info; return a minimal object
        return CustomerInfo(
            id=provider_customer_id,
            email="",
            name="",
            provider=PaymentProvider.PAYPAL,
            provider_customer_id=provider_customer_id,
        )

    # ── Plan (Product + Billing Plan) ────────────────────────────

    async def create_plan(
        self,
        name: str,
        amount: int,
        currency: str,
        interval: str,
        metadata: dict[str, Any] | None = None,
    ) -> PlanInfo:
        # Step 1: Create a catalog product
        product_data = await self._request("POST", "/v1/catalogs/products", json_data={
            "name": name,
            "description": metadata.get("description", name) if metadata else name,
            "type": "SERVICE",
            "category": "SOFTWARE",
        })
        product_id = product_data["id"]

        # Step 2: Create a billing plan linked to the product
        interval_unit, interval_count = _INTERVAL_MAP.get(interval, ("MONTH", 1))

        # Amount is in smallest unit; PayPal expects decimal string
        decimal_amount = f"{amount / 100:.2f}"

        plan_data = await self._request("POST", "/v1/billing/plans", json_data={
            "product_id": product_id,
            "name": name,
            "description": metadata.get("description", name) if metadata else name,
            "status": "ACTIVE",
            "billing_cycles": [
                {
                    "frequency": {
                        "interval_unit": interval_unit,
                        "interval_count": interval_count,
                    },
                    "tenure_type": "REGULAR",
                    "sequence": 1,
                    "total_cycles": 0,  # Infinite
                    "pricing_scheme": {
                        "fixed_price": {
                            "value": decimal_amount,
                            "currency_code": currency.upper(),
                        },
                    },
                },
            ],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "payment_failure_threshold": 3,
            },
        })

        return PlanInfo(
            id=str(uuid.uuid4()),
            name=name,
            amount=amount,
            currency=currency.upper(),
            interval=interval,
            provider=PaymentProvider.PAYPAL,
            provider_plan_id=plan_data["id"],
            metadata={"product_id": product_id, **(metadata or {})},
        )

    async def get_plan(self, provider_plan_id: str) -> PlanInfo:
        data = await self._request("GET", f"/v1/billing/plans/{provider_plan_id}")
        # Extract pricing from first billing cycle
        cycles = data.get("billing_cycles", [])
        amount = 0
        currency = "USD"
        interval = "monthly"
        if cycles:
            pricing = cycles[0].get("pricing_scheme", {}).get("fixed_price", {})
            amount = int(float(pricing.get("value", "0")) * 100)
            currency = pricing.get("currency_code", "USD")
            freq = cycles[0].get("frequency", {})
            unit = freq.get("interval_unit", "MONTH")
            interval_map_reverse = {"MONTH": "monthly", "YEAR": "yearly", "WEEK": "weekly", "DAY": "daily"}
            interval = interval_map_reverse.get(unit, "monthly")

        return PlanInfo(
            id=str(uuid.uuid4()),
            name=data.get("name", ""),
            amount=amount,
            currency=currency,
            interval=interval,
            provider=PaymentProvider.PAYPAL,
            provider_plan_id=data["id"],
            metadata={"product_id": data.get("product_id", "")},
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
            "application_context": {
                "brand_name": "AskforWrite",
                "shipping_preference": "NO_SHIPPING",
                "user_action": "SUBSCRIBE_NOW",
                "return_url": os.environ.get(
                    "PAYPAL_RETURN_URL",
                    "https://askforwrite.in/payment/success",
                ),
                "cancel_url": os.environ.get(
                    "PAYPAL_CANCEL_URL",
                    "https://askforwrite.in/payment/cancel",
                ),
            },
        }
        if metadata:
            payload["custom_id"] = metadata.get("custom_id", customer_id)

        data = await self._request("POST", "/v1/billing/subscriptions", json_data=payload)
        status_str = data.get("status", "APPROVAL_PENDING")

        # Find the approval URL
        payment_url = None
        for link in data.get("links", []):
            if link.get("rel") == "approve":
                payment_url = link.get("href")
                break

        return SubscriptionInfo(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            plan_id=plan_id,
            status=_PAYPAL_STATUS_MAP.get(status_str, SubscriptionStatus.PENDING),
            provider=PaymentProvider.PAYPAL,
            provider_subscription_id=data["id"],
            payment_url=payment_url,
            metadata=data,
        )

    async def get_subscription(self, provider_subscription_id: str) -> SubscriptionInfo:
        data = await self._request(
            "GET",
            f"/v1/billing/subscriptions/{provider_subscription_id}",
        )
        status_str = data.get("status", "APPROVAL_PENDING")
        subscriber = data.get("subscriber", {})
        billing_info = data.get("billing_info", {})

        return SubscriptionInfo(
            id=str(uuid.uuid4()),
            customer_id=subscriber.get("email_address", ""),
            plan_id=data.get("plan_id", ""),
            status=_PAYPAL_STATUS_MAP.get(status_str, SubscriptionStatus.PENDING),
            provider=PaymentProvider.PAYPAL,
            provider_subscription_id=data["id"],
            current_period_start=billing_info.get("last_payment", {}).get("time", ""),
            current_period_end=billing_info.get("next_billing_time", ""),
            metadata=data,
        )

    async def cancel_subscription(
        self,
        provider_subscription_id: str,
        cancel_at_period_end: bool = True,
    ) -> SubscriptionInfo:
        await self._request(
            "POST",
            f"/v1/billing/subscriptions/{provider_subscription_id}/cancel",
            json_data={"reason": "Customer requested cancellation"},
        )
        return SubscriptionInfo(
            id=str(uuid.uuid4()),
            customer_id="",
            plan_id="",
            status=SubscriptionStatus.CANCELLED,
            provider=PaymentProvider.PAYPAL,
            provider_subscription_id=provider_subscription_id,
        )

    # ── Webhook ──────────────────────────────────────────────────

    async def verify_webhook(
        self,
        payload: bytes,
        headers: dict[str, str],
    ) -> bool:
        """Verify via PayPal's webhook verification API endpoint."""
        if not self._webhook_id:
            logger.warning("PAYPAL_WEBHOOK_ID not set; skipping verification")
            return False

        try:
            body = json.loads(payload)
        except json.JSONDecodeError:
            return False

        verification_payload = {
            "auth_algo": headers.get("paypal-auth-algo", ""),
            "cert_url": headers.get("paypal-cert-url", ""),
            "transmission_id": headers.get("paypal-transmission-id", ""),
            "transmission_sig": headers.get("paypal-transmission-sig", ""),
            "transmission_time": headers.get("paypal-transmission-time", ""),
            "webhook_id": self._webhook_id,
            "webhook_event": body,
        }

        try:
            result = await self._request(
                "POST",
                "/v1/notifications/verify-webhook-signature",
                json_data=verification_payload,
            )
            return result.get("verification_status") == "SUCCESS"
        except PaymentProviderError:
            logger.exception("PayPal webhook verification request failed")
            return False

    async def parse_webhook_event(
        self,
        payload: bytes,
        headers: dict[str, str],
    ) -> WebhookEvent:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise PaymentValidationError(f"Invalid JSON payload: {exc}") from exc

        raw_event_type = data.get("event_type", "UNKNOWN")
        event_type = _PAYPAL_EVENT_MAP.get(raw_event_type, raw_event_type)

        resource = data.get("resource", {})
        resource_id = resource.get("id", "")
        resource_type = data.get("resource_type", "unknown")

        return WebhookEvent(
            id=data.get("id", str(uuid.uuid4())),
            provider=PaymentProvider.PAYPAL,
            event_type=event_type,
            raw_event_type=raw_event_type,
            resource_id=resource_id,
            resource_type=resource_type,
            data=data,
        )
