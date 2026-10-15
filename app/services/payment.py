"""Unified payment abstraction layer for AskforWrite Company OS.

Provides a provider-agnostic interface for:
- Customer management (create, retrieve)
- Plan/product management
- Subscription lifecycle (create, cancel, fetch status)
- Webhook signature verification and event normalization
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ── Domain value objects ─────────────────────────────────────────────


class PaymentProvider(str, Enum):
    RAZORPAY = "razorpay"
    PAYPAL = "paypal"


class SubscriptionStatus(str, Enum):
    CREATED = "created"
    AUTHENTICATED = "authenticated"
    ACTIVE = "active"
    PAUSED = "paused"
    HALTED = "halted"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    EXPIRED = "expired"
    PENDING = "pending"


@dataclass(frozen=True)
class CustomerInfo:
    """Normalized customer representation across providers."""
    id: str
    email: str
    name: str
    provider: PaymentProvider
    provider_customer_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanInfo:
    """Normalized plan/product representation across providers."""
    id: str
    name: str
    amount: int  # In smallest currency unit (paise/cents)
    currency: str
    interval: str  # "monthly", "yearly"
    provider: PaymentProvider
    provider_plan_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SubscriptionInfo:
    """Normalized subscription representation across providers."""
    id: str
    customer_id: str
    plan_id: str
    status: SubscriptionStatus
    provider: PaymentProvider
    provider_subscription_id: str
    current_period_start: str | None = None
    current_period_end: str | None = None
    payment_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookEvent:
    """Normalized webhook event from any provider."""
    id: str
    provider: PaymentProvider
    event_type: str  # Normalized: "subscription.activated", "payment.captured", etc.
    raw_event_type: str  # Original provider-specific event type
    resource_id: str  # ID of the subscription/payment
    resource_type: str  # "subscription", "payment", etc.
    data: dict[str, Any] = field(default_factory=dict)


# ── Exceptions ───────────────────────────────────────────────────────


class PaymentError(Exception):
    """Base exception for payment service errors."""


class PaymentProviderError(PaymentError):
    """Raised when the provider API returns an error."""


class PaymentValidationError(PaymentError):
    """Raised when input validation fails."""


class WebhookVerificationError(PaymentError):
    """Raised when webhook signature verification fails."""


# ── Abstract provider interface ──────────────────────────────────────


class PaymentProviderInterface(ABC):
    """Abstract interface that each payment provider must implement."""

    @property
    @abstractmethod
    def provider_name(self) -> PaymentProvider:
        """Return the provider enum value."""

    # ── Customer operations ──────────────────────────────────────

    @abstractmethod
    async def create_customer(
        self,
        email: str,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> CustomerInfo:
        """Create a customer on the payment provider."""

    @abstractmethod
    async def get_customer(self, provider_customer_id: str) -> CustomerInfo:
        """Retrieve customer details from the provider."""

    # ── Plan operations ──────────────────────────────────────────

    @abstractmethod
    async def create_plan(
        self,
        name: str,
        amount: int,
        currency: str,
        interval: str,
        metadata: dict[str, Any] | None = None,
    ) -> PlanInfo:
        """Create a subscription plan on the provider."""

    @abstractmethod
    async def get_plan(self, provider_plan_id: str) -> PlanInfo:
        """Retrieve plan details from the provider."""

    # ── Subscription operations ──────────────────────────────────

    @abstractmethod
    async def create_subscription(
        self,
        customer_id: str,
        plan_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> SubscriptionInfo:
        """Create a new subscription for a customer."""

    @abstractmethod
    async def get_subscription(self, provider_subscription_id: str) -> SubscriptionInfo:
        """Retrieve subscription status from the provider."""

    @abstractmethod
    async def cancel_subscription(
        self,
        provider_subscription_id: str,
        cancel_at_period_end: bool = True,
    ) -> SubscriptionInfo:
        """Cancel a subscription."""

    # ── Webhook operations ───────────────────────────────────────

    @abstractmethod
    async def verify_webhook(
        self,
        payload: bytes,
        headers: dict[str, str],
    ) -> bool:
        """Verify webhook signature authenticity."""

    @abstractmethod
    async def parse_webhook_event(
        self,
        payload: bytes,
        headers: dict[str, str],
    ) -> WebhookEvent:
        """Parse and normalize a webhook payload into a WebhookEvent."""


# ── Factory ──────────────────────────────────────────────────────────


_provider_registry: dict[PaymentProvider, type[PaymentProviderInterface]] = {}


def register_provider(provider: PaymentProvider):
    """Decorator to register a payment provider implementation."""
    def decorator(cls: type[PaymentProviderInterface]):
        _provider_registry[provider] = cls
        logger.info("Registered payment provider: %s -> %s", provider.value, cls.__name__)
        return cls
    return decorator


def get_payment_provider(provider: PaymentProvider | None = None) -> PaymentProviderInterface:
    """Factory: return the configured (or specified) payment provider instance.

    Resolution order:
    1. Explicit ``provider`` argument
    2. ``PAYMENT_PROVIDER`` environment variable  (default ``razorpay``)
    """
    if provider is None:
        env_provider = os.environ.get("PAYMENT_PROVIDER", "razorpay").lower()
        try:
            provider = PaymentProvider(env_provider)
        except ValueError:
            raise PaymentValidationError(
                f"Unknown payment provider '{env_provider}'. "
                f"Available: {[p.value for p in PaymentProvider]}"
            )

    if provider not in _provider_registry:
        raise PaymentValidationError(
            f"Provider '{provider.value}' is not registered. "
            f"Registered: {[p.value for p in _provider_registry]}"
        )

    return _provider_registry[provider]()


def get_all_providers() -> dict[PaymentProvider, PaymentProviderInterface]:
    """Return instances of all registered providers (used for multi-provider webhook handling)."""
    return {p: cls() for p, cls in _provider_registry.items()}
