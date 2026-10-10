"""Unit tests for the unified payment layer.

Covers:
- Payment abstraction (factory, provider resolution)
- Razorpay provider (customer, plan, subscription, webhook)
- PayPal provider (customer, plan, subscription, webhook)
- Subscription router endpoints
- Webhook endpoint with both providers
"""

import asyncio
import hashlib
import hmac
import json
import os
import unittest
import uuid
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import (
    CustomerRecord,
    SubscriptionRecord,
    WebhookEventRecord,
)
from app.main import app
from app.security.auth import APIPrincipal, get_current_principal
from app.services.payment import (
    CustomerInfo,
    PaymentProvider,
    PaymentValidationError,
    PlanInfo,
    SubscriptionInfo,
    SubscriptionStatus,
    get_payment_provider,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _run(coro):
    """Run a coroutine synchronously (Python 3.14 compatible)."""
    return asyncio.run(coro)


def _make_transport() -> httpx.ASGITransport:
    return httpx.ASGITransport(app=app)


# ── Test base class (endpoint tests) ────────────────────────────────


class PaymentTestBase(unittest.TestCase):
    """Common setup: in-memory SQLite, auth override."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

        def override_get_db():
            session = self.session_factory()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_principal] = lambda: APIPrincipal(
            subject="test-manager",
            role="manager",
        )

    def tearDown(self):
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)

    def _get(self, url: str, **kwargs):
        async def _do():
            async with httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test"
            ) as client:
                return await client.get(url, **kwargs)
        return _run(_do())

    def _post(self, url: str, **kwargs):
        async def _do():
            async with httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test"
            ) as client:
                return await client.post(url, **kwargs)
        return _run(_do())


# ── Payment abstraction tests ────────────────────────────────────────


class TestPaymentFactory(unittest.TestCase):

    def test_get_razorpay_provider(self):
        p = get_payment_provider(PaymentProvider.RAZORPAY)
        self.assertEqual(p.provider_name, PaymentProvider.RAZORPAY)

    def test_get_paypal_provider(self):
        p = get_payment_provider(PaymentProvider.PAYPAL)
        self.assertEqual(p.provider_name, PaymentProvider.PAYPAL)

    def test_default_provider_via_env_razorpay(self):
        with patch.dict(os.environ, {"PAYMENT_PROVIDER": "razorpay"}):
            p = get_payment_provider()
            self.assertEqual(p.provider_name, PaymentProvider.RAZORPAY)

    def test_default_provider_via_env_paypal(self):
        with patch.dict(os.environ, {"PAYMENT_PROVIDER": "paypal"}):
            p = get_payment_provider()
            self.assertEqual(p.provider_name, PaymentProvider.PAYPAL)

    def test_invalid_provider_raises(self):
        with self.assertRaises(PaymentValidationError):
            with patch.dict(os.environ, {"PAYMENT_PROVIDER": "stripe"}):
                get_payment_provider()


# ── Razorpay provider tests ─────────────────────────────────────────


class TestRazorpayProvider(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        os.environ["RAZORPAY_KEY_ID"] = "rzp_test_key"
        os.environ["RAZORPAY_KEY_SECRET"] = "test_secret_rzp"

    def tearDown(self):
        os.environ.pop("RAZORPAY_KEY_ID", None)
        os.environ.pop("RAZORPAY_KEY_SECRET", None)

    async def test_create_customer(self):
        p = get_payment_provider(PaymentProvider.RAZORPAY)
        data = {"id": "cust_test123", "email": "test@example.com", "name": "Test User", "notes": {}}
        with patch.object(p, "_request", new_callable=AsyncMock, return_value=data):
            customer = await p.create_customer("test@example.com", "Test User")
        self.assertEqual(customer.provider_customer_id, "cust_test123")
        self.assertEqual(customer.provider, PaymentProvider.RAZORPAY)

    async def test_create_plan(self):
        p = get_payment_provider(PaymentProvider.RAZORPAY)
        data = {"id": "plan_test456", "notes": {}}
        with patch.object(p, "_request", new_callable=AsyncMock, return_value=data):
            plan = await p.create_plan("Pro Plan", 99900, "INR", "monthly")
        self.assertEqual(plan.provider_plan_id, "plan_test456")
        self.assertEqual(plan.amount, 99900)
        self.assertEqual(plan.currency, "INR")

    async def test_create_subscription(self):
        p = get_payment_provider(PaymentProvider.RAZORPAY)
        data = {"id": "sub_test789", "status": "created", "short_url": "https://rzp.io/test", "notes": {}}
        with patch.object(p, "_request", new_callable=AsyncMock, return_value=data):
            sub = await p.create_subscription("cust_test123", "plan_test456")
        self.assertEqual(sub.provider_subscription_id, "sub_test789")
        self.assertEqual(sub.status, SubscriptionStatus.CREATED)
        self.assertEqual(sub.payment_url, "https://rzp.io/test")

    async def test_get_subscription(self):
        p = get_payment_provider(PaymentProvider.RAZORPAY)
        data = {"id": "sub_test789", "status": "active", "customer_id": "cust_test123", "plan_id": "plan_test456", "notes": {}}
        with patch.object(p, "_request", new_callable=AsyncMock, return_value=data):
            sub = await p.get_subscription("sub_test789")
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE)

    async def test_cancel_subscription(self):
        p = get_payment_provider(PaymentProvider.RAZORPAY)
        data = {"id": "sub_test789", "status": "cancelled", "notes": {}}
        with patch.object(p, "_request", new_callable=AsyncMock, return_value=data):
            sub = await p.cancel_subscription("sub_test789")
        self.assertEqual(sub.status, SubscriptionStatus.CANCELLED)

    async def test_verify_webhook_valid(self):
        p = get_payment_provider(PaymentProvider.RAZORPAY)
        payload = b'{"event":"subscription.activated"}'
        sig = hmac.new(b"test_secret_rzp", payload, hashlib.sha256).hexdigest()
        result = await p.verify_webhook(payload, {"x-razorpay-signature": sig})
        self.assertTrue(result)

    async def test_verify_webhook_invalid_sig(self):
        p = get_payment_provider(PaymentProvider.RAZORPAY)
        result = await p.verify_webhook(b'{}', {"x-razorpay-signature": "wrong"})
        self.assertFalse(result)

    async def test_verify_webhook_missing_header(self):
        p = get_payment_provider(PaymentProvider.RAZORPAY)
        result = await p.verify_webhook(b'{}', {})
        self.assertFalse(result)

    async def test_parse_webhook_subscription_event(self):
        p = get_payment_provider(PaymentProvider.RAZORPAY)
        payload = json.dumps({
            "event": "subscription.activated",
            "event_id": "evt_123",
            "payload": {"subscription": {"entity": {"id": "sub_test789", "status": "active"}}},
        }).encode()
        event = await p.parse_webhook_event(payload, {})
        self.assertEqual(event.event_type, "subscription.activated")
        self.assertEqual(event.resource_id, "sub_test789")
        self.assertEqual(event.resource_type, "subscription")

    async def test_parse_webhook_payment_event(self):
        p = get_payment_provider(PaymentProvider.RAZORPAY)
        payload = json.dumps({
            "event": "payment.captured",
            "event_id": "evt_pay_123",
            "payload": {"payment": {"entity": {"id": "pay_test456"}}},
        }).encode()
        event = await p.parse_webhook_event(payload, {})
        self.assertEqual(event.event_type, "payment.captured")
        self.assertEqual(event.resource_type, "payment")
        self.assertEqual(event.resource_id, "pay_test456")

    async def test_parse_webhook_invalid_json(self):
        p = get_payment_provider(PaymentProvider.RAZORPAY)
        with self.assertRaises(PaymentValidationError):
            await p.parse_webhook_event(b"not json", {})


# ── PayPal provider tests ────────────────────────────────────────────


class TestPayPalProvider(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        os.environ["PAYPAL_CLIENT_ID"] = "test_client_id"
        os.environ["PAYPAL_CLIENT_SECRET"] = "test_client_secret"
        os.environ["PAYPAL_WEBHOOK_ID"] = "test_webhook_id"
        os.environ["PAYPAL_MODE"] = "sandbox"

    def tearDown(self):
        for k in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID", "PAYPAL_MODE"):
            os.environ.pop(k, None)

    async def test_create_customer_is_synthetic(self):
        p = get_payment_provider(PaymentProvider.PAYPAL)
        customer = await p.create_customer("test@example.com", "Test User")
        self.assertEqual(customer.email, "test@example.com")
        self.assertEqual(customer.provider, PaymentProvider.PAYPAL)
        uuid.UUID(customer.id)  # valid UUID

    async def test_create_customer_with_metadata(self):
        p = get_payment_provider(PaymentProvider.PAYPAL)
        meta = {"custom_id": "plan-pro"}
        customer = await p.create_customer("user@example.com", "User", metadata=meta)
        self.assertEqual(customer.metadata, meta)

    async def test_create_plan(self):
        p = get_payment_provider(PaymentProvider.PAYPAL)
        results = iter([{"id": "PROD-test123"}, {"id": "P-test456"}])

        async def mock_req(*a, **kw):
            return next(results)

        with patch.object(p, "_request", side_effect=mock_req):
            plan = await p.create_plan("Pro Plan", 99900, "INR", "monthly")
        self.assertEqual(plan.provider_plan_id, "P-test456")
        self.assertEqual(plan.amount, 99900)

    async def test_create_subscription(self):
        p = get_payment_provider(PaymentProvider.PAYPAL)
        data = {
            "id": "I-test789",
            "status": "APPROVAL_PENDING",
            "links": [{"rel": "approve", "href": "https://www.paypal.com/approve"}],
        }
        with patch.object(p, "_request", new_callable=AsyncMock, return_value=data):
            sub = await p.create_subscription("cust-local", "P-test456")
        self.assertEqual(sub.provider_subscription_id, "I-test789")
        self.assertEqual(sub.status, SubscriptionStatus.PENDING)
        self.assertEqual(sub.payment_url, "https://www.paypal.com/approve")

    async def test_get_subscription_active(self):
        p = get_payment_provider(PaymentProvider.PAYPAL)
        data = {
            "id": "I-test789",
            "status": "ACTIVE",
            "plan_id": "P-test456",
            "subscriber": {"email_address": "test@example.com"},
            "billing_info": {
                "last_payment": {"time": "2024-01-01T00:00:00Z"},
                "next_billing_time": "2024-02-01T00:00:00Z",
            },
        }
        with patch.object(p, "_request", new_callable=AsyncMock, return_value=data):
            sub = await p.get_subscription("I-test789")
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE)

    async def test_cancel_subscription(self):
        p = get_payment_provider(PaymentProvider.PAYPAL)
        with patch.object(p, "_request", new_callable=AsyncMock, return_value={}):
            sub = await p.cancel_subscription("I-test789")
        self.assertEqual(sub.status, SubscriptionStatus.CANCELLED)

    async def test_parse_webhook_subscription_event(self):
        p = get_payment_provider(PaymentProvider.PAYPAL)
        payload = json.dumps({
            "id": "WH-test123",
            "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
            "resource_type": "subscription",
            "resource": {"id": "I-test789"},
        }).encode()
        event = await p.parse_webhook_event(payload, {})
        self.assertEqual(event.event_type, "subscription.activated")
        self.assertEqual(event.resource_id, "I-test789")
        self.assertEqual(event.provider, PaymentProvider.PAYPAL)

    async def test_parse_webhook_payment_event(self):
        p = get_payment_provider(PaymentProvider.PAYPAL)
        payload = json.dumps({
            "id": "WH-pay-123",
            "event_type": "PAYMENT.SALE.COMPLETED",
            "resource_type": "sale",
            "resource": {"id": "SALE-001"},
        }).encode()
        event = await p.parse_webhook_event(payload, {})
        self.assertEqual(event.event_type, "payment.captured")
        self.assertEqual(event.raw_event_type, "PAYMENT.SALE.COMPLETED")

    async def test_parse_webhook_invalid_json(self):
        p = get_payment_provider(PaymentProvider.PAYPAL)
        with self.assertRaises(PaymentValidationError):
            await p.parse_webhook_event(b"not json", {})

    async def test_verify_webhook_success(self):
        p = get_payment_provider(PaymentProvider.PAYPAL)
        payload = json.dumps({"event_type": "BILLING.SUBSCRIPTION.ACTIVATED"}).encode()
        headers = {
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-url": "https://api.paypal.com/cert",
            "paypal-transmission-id": "tx-123",
            "paypal-transmission-sig": "sig-123",
            "paypal-transmission-time": "2024-01-01T00:00:00Z",
        }
        with patch.object(p, "_request", new_callable=AsyncMock, return_value={"verification_status": "SUCCESS"}):
            result = await p.verify_webhook(payload, headers)
        self.assertTrue(result)

    async def test_verify_webhook_failure(self):
        p = get_payment_provider(PaymentProvider.PAYPAL)
        payload = json.dumps({"event_type": "BILLING.SUBSCRIPTION.ACTIVATED"}).encode()
        headers = {
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-url": "https://api.paypal.com/cert",
            "paypal-transmission-id": "tx-123",
            "paypal-transmission-sig": "bad",
            "paypal-transmission-time": "2024-01-01T00:00:00Z",
        }
        with patch.object(p, "_request", new_callable=AsyncMock, return_value={"verification_status": "FAILURE"}):
            result = await p.verify_webhook(payload, headers)
        self.assertFalse(result)

    async def test_verify_webhook_no_webhook_id(self):
        os.environ.pop("PAYPAL_WEBHOOK_ID", None)
        p = get_payment_provider(PaymentProvider.PAYPAL)
        result = await p.verify_webhook(b'{}', {})
        self.assertFalse(result)


# ── Subscription router tests ───────────────────────────────────────


class TestSubscriptionEndpoints(PaymentTestBase):

    def test_create_customer(self):
        mock_customer = CustomerInfo(
            id="cust-local-id",
            email="test@example.com",
            name="Test User",
            provider=PaymentProvider.RAZORPAY,
            provider_customer_id="cust_rzp_123",
        )
        with patch("app.api.v1.subscriptions.get_payment_provider") as mock_factory:
            mock_p = AsyncMock()
            mock_p.create_customer.return_value = mock_customer
            mock_factory.return_value = mock_p
            resp = self._post(
                "/v1/subscriptions/customers",
                json={"email": "test@example.com", "name": "Test User", "provider": "razorpay"},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["provider"], "razorpay")
        self.assertEqual(data["provider_customer_id"], "cust_rzp_123")

        session = self.session_factory()
        customer = session.query(CustomerRecord).first()
        self.assertIsNotNone(customer)
        self.assertEqual(customer.email, "test@example.com")
        session.close()

    def test_create_customer_bad_provider(self):
        resp = self._post(
            "/v1/subscriptions/customers",
            json={"email": "test@example.com", "name": "Test", "provider": "stripe"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_create_plan(self):
        mock_plan = PlanInfo(
            id="plan-local-id",
            name="Pro Plan",
            amount=99900,
            currency="INR",
            interval="monthly",
            provider=PaymentProvider.RAZORPAY,
            provider_plan_id="plan_rzp_456",
        )
        with patch("app.api.v1.subscriptions.get_payment_provider") as mock_factory:
            mock_p = AsyncMock()
            mock_p.create_plan.return_value = mock_plan
            mock_factory.return_value = mock_p
            resp = self._post(
                "/v1/subscriptions/plans",
                json={"name": "Pro Plan", "amount": 99900, "currency": "INR", "interval": "monthly", "provider": "razorpay"},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["provider_plan_id"], "plan_rzp_456")

    def test_create_subscription(self):
        session = self.session_factory()
        session.add(CustomerRecord(
            id="cust-local-id", email="test@example.com", name="Test User",
            provider="razorpay", provider_customer_id="cust_rzp_123",
        ))
        session.commit()
        session.close()

        mock_sub = SubscriptionInfo(
            id="sub-local-id", customer_id="cust_rzp_123", plan_id="plan_test",
            status=SubscriptionStatus.CREATED, provider=PaymentProvider.RAZORPAY,
            provider_subscription_id="sub_rzp_789",
            payment_url="https://rzp.io/test",
        )
        with patch("app.api.v1.subscriptions.get_payment_provider") as mock_factory:
            mock_p = AsyncMock()
            mock_p.create_subscription.return_value = mock_sub
            mock_factory.return_value = mock_p
            resp = self._post(
                "/v1/subscriptions/create",
                json={"customer_id": "cust-local-id", "plan_id": "plan_test", "provider": "razorpay"},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertIn("rzp.io", data["payment_url"])  # specific URL preferred over fallback

        session = self.session_factory()
        sub = session.query(SubscriptionRecord).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.status, "created")
        session.close()

    def test_create_subscription_missing_customer(self):
        resp = self._post(
            "/v1/subscriptions/create",
            json={"customer_id": "nonexistent", "plan_id": "plan_test", "provider": "razorpay"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_get_subscription(self):
        session = self.session_factory()
        session.add(SubscriptionRecord(
            id="sub-1", customer_id="cust-1", plan_id="plan-1",
            provider="razorpay", provider_subscription_id="sub_rzp_1", status="created",
        ))
        session.commit()
        session.close()

        mock_sub = SubscriptionInfo(
            id="sub-1", customer_id="cust_rzp_1", plan_id="plan-1",
            status=SubscriptionStatus.ACTIVE, provider=PaymentProvider.RAZORPAY,
            provider_subscription_id="sub_rzp_1",
        )
        with patch("app.api.v1.subscriptions.get_payment_provider") as mock_factory:
            mock_p = AsyncMock()
            mock_p.get_subscription.return_value = mock_sub
            mock_factory.return_value = mock_p
            resp = self._get("/v1/subscriptions/sub-1")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "active")
        self.assertTrue(data["synced"])

    def test_get_subscription_not_found(self):
        resp = self._get("/v1/subscriptions/nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_list_customer_subscriptions(self):
        session = self.session_factory()
        session.add(SubscriptionRecord(
            id="sub-1", customer_id="cust-1", plan_id="plan-1",
            provider="razorpay", provider_subscription_id="sub_rzp_1", status="active",
        ))
        session.add(SubscriptionRecord(
            id="sub-2", customer_id="cust-1", plan_id="plan-2",
            provider="paypal", provider_subscription_id="I-pptest", status="cancelled",
        ))
        session.commit()
        session.close()

        resp = self._get("/v1/subscriptions/customer/cust-1")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)
        statuses = {s["status"] for s in data["subscriptions"]}
        self.assertIn("active", statuses)
        self.assertIn("cancelled", statuses)

    def test_cancel_subscription_requires_owner(self):
        """Manager role cannot cancel — needs owner."""
        session = self.session_factory()
        session.add(SubscriptionRecord(
            id="sub-cancel", customer_id="cust-1",
            provider="razorpay", provider_subscription_id="sub_rzp_cancel", status="active",
        ))
        session.commit()
        session.close()

        resp = self._post(
            "/v1/subscriptions/sub-cancel/cancel",
            json={"cancel_at_period_end": True},
        )
        self.assertEqual(resp.status_code, 403)

    def test_cancel_subscription_as_owner(self):
        app.dependency_overrides[get_current_principal] = lambda: APIPrincipal(
            subject="test-owner", role="owner"
        )
        session = self.session_factory()
        session.add(SubscriptionRecord(
            id="sub-cancel2", customer_id="cust-1",
            provider="razorpay", provider_subscription_id="sub_rzp_cancel2", status="active",
        ))
        session.commit()
        session.close()

        mock_sub = SubscriptionInfo(
            id="sub-cancel2", customer_id="cust-1", plan_id="",
            status=SubscriptionStatus.CANCELLED, provider=PaymentProvider.RAZORPAY,
            provider_subscription_id="sub_rzp_cancel2",
        )
        with patch("app.api.v1.subscriptions.get_payment_provider") as mock_factory:
            mock_p = AsyncMock()
            mock_p.cancel_subscription.return_value = mock_sub
            mock_factory.return_value = mock_p
            resp = self._post(
                "/v1/subscriptions/sub-cancel2/cancel",
                json={"cancel_at_period_end": True},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "cancelled")


# ── Webhook endpoint tests ──────────────────────────────────────────


class TestWebhookEndpoint(PaymentTestBase):

    def _rzp_sig(self, payload: str, secret: str) -> str:
        return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def test_razorpay_webhook_activates_subscription(self):
        session = self.session_factory()
        session.add(SubscriptionRecord(
            id="sub-wh-1", customer_id="cust-1",
            provider="razorpay", provider_subscription_id="sub_rzp_wh", status="created",
        ))
        session.commit()
        session.close()

        secret = "rzp_wh_secret"
        payload = json.dumps({
            "event": "subscription.activated",
            "event_id": "evt_unique_rzp_1",
            "payload": {"subscription": {"entity": {"id": "sub_rzp_wh"}}},
        })
        sig = self._rzp_sig(payload, secret)

        with patch.dict(os.environ, {"RAZORPAY_KEY_SECRET": secret}):
            resp = self._post(
                "/v1/webhooks/payment",
                content=payload,
                headers={"x-razorpay-signature": sig, "content-type": "application/json"},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "processed")
        self.assertEqual(data["provider"], "razorpay")
        self.assertEqual(data["event_type"], "subscription.activated")

        session = self.session_factory()
        sub = session.query(SubscriptionRecord).filter_by(id="sub-wh-1").first()
        self.assertEqual(sub.status, "active")
        evt = session.query(WebhookEventRecord).filter_by(provider_event_id="evt_unique_rzp_1").first()
        self.assertIsNotNone(evt)
        self.assertTrue(evt.processed)
        session.close()

    def test_razorpay_webhook_payment_captured(self):
        secret = "rzp_wh_secret"
        payload = json.dumps({
            "event": "payment.captured",
            "event_id": "evt_pay_captured_1",
            "payload": {"payment": {"entity": {"id": "pay_test_001"}}},
        })
        sig = self._rzp_sig(payload, secret)

        with patch.dict(os.environ, {"RAZORPAY_KEY_SECRET": secret}):
            resp = self._post(
                "/v1/webhooks/payment",
                content=payload,
                headers={"x-razorpay-signature": sig, "content-type": "application/json"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["event_type"], "payment.captured")

    def test_webhook_invalid_signature_returns_401(self):
        with patch.dict(os.environ, {"RAZORPAY_KEY_SECRET": "real_secret"}):
            resp = self._post(
                "/v1/webhooks/payment",
                content=json.dumps({"event": "subscription.activated", "event_id": "x"}),
                headers={"x-razorpay-signature": "invalid", "content-type": "application/json"},
            )
        self.assertEqual(resp.status_code, 401)

    def test_webhook_unknown_provider_returns_400(self):
        resp = self._post(
            "/v1/webhooks/payment",
            content=b"{}",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_webhook_duplicate_event_skipped(self):
        session = self.session_factory()
        session.add(WebhookEventRecord(
            provider="razorpay",
            provider_event_id="evt_dup_99",
            event_type="subscription.activated",
            raw_event_type="subscription.activated",
            resource_id="sub_rzp_dup",
            resource_type="subscription",
            payload={},
            processed=True,
        ))
        session.commit()
        session.close()

        secret = "rzp_dup_secret"
        payload = json.dumps({
            "event": "subscription.activated",
            "event_id": "evt_dup_99",
            "payload": {"subscription": {"entity": {"id": "sub_rzp_dup"}}},
        })
        sig = self._rzp_sig(payload, secret)

        with patch.dict(os.environ, {"RAZORPAY_KEY_SECRET": secret}):
            resp = self._post(
                "/v1/webhooks/payment",
                content=payload,
                headers={"x-razorpay-signature": sig, "content-type": "application/json"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "duplicate")

    def test_list_webhook_events(self):
        session = self.session_factory()
        for i, (prov, evt_id, etype) in enumerate([
            ("razorpay", "evt_list_rzp_1", "subscription.activated"),
            ("paypal", "WH-pp-list-1", "subscription.cancelled"),
        ]):
            session.add(WebhookEventRecord(
                provider=prov, provider_event_id=evt_id,
                event_type=etype, raw_event_type=etype,
                resource_id=f"res-{i}", resource_type="subscription",
                payload={}, processed=True,
            ))
        session.commit()
        session.close()

        resp = self._get("/v1/webhooks/events")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)

    def test_list_webhook_events_filter_by_provider(self):
        session = self.session_factory()
        for prov, evt_id in [("razorpay", "evt_f_rzp"), ("paypal", "evt_f_pp")]:
            session.add(WebhookEventRecord(
                provider=prov, provider_event_id=evt_id,
                event_type="subscription.activated", raw_event_type="x",
                resource_id="r", resource_type="subscription",
                payload={}, processed=False,
            ))
        session.commit()
        session.close()

        resp = self._get("/v1/webhooks/events", params={"provider": "paypal"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["events"][0]["provider"], "paypal")


if __name__ == "__main__":
    unittest.main()
