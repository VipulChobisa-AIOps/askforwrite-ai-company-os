"""Unit tests for Commercial Catalog and Tenant Provisioning Engine."""

import unittest
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import (
    AuditLog,
    CustomerRecord,
    InvoiceRecord,
    OrganizationRecord,
    UserRecord,
)
from app.services.catalog import (
    build_payment_link,
    get_all_packages,
    get_package,
)
from app.services.payment import PaymentProvider, WebhookEvent
from app.services.provisioning import auto_provision_tenant_on_payment


class TestCatalogService(unittest.TestCase):
    """Tests for catalog definitions and payment link generation."""

    def test_catalog_package_integrity(self):
        packages = get_all_packages()
        self.assertEqual(len(packages), 14)

        expected_keys = {
            "seo_blog_copilot",
            "marketing_suite",
            "field_force",
            "trust_engine",
            "mango_quality_analytics",
            "bike_rebalance_analytics",
            "warehouse_automation",
            "ask4_academic_order",
            "pixel_ai_pack",
            "company_os_starter",
            "company_os_pro",
            "company_os_enterprise",
            "growth_all_in_one",
            "all_access",
        }
        actual_keys = {pkg.key for pkg in packages}
        self.assertEqual(actual_keys, expected_keys)

        for pkg in packages:
            self.assertIn(pkg.category, ("modular_tool", "master_bundle", "b2c_one_off"))
            self.assertGreater(pkg.price_inr, 0)
            self.assertGreater(pkg.price_usd, 0)
            self.assertTrue(len(pkg.key_features) > 0)
            self.assertTrue(len(pkg.deliverables) > 0)
            self.assertTrue(len(pkg.entitled_capabilities) > 0)
            if pkg.category != "b2c_one_off":
                self.assertGreater(pkg.lead_credits_monthly, 0)
                self.assertGreater(pkg.outreach_credits_monthly, 0)
            else:
                self.assertGreaterEqual(pkg.lead_credits_monthly, 0)
                self.assertGreaterEqual(pkg.outreach_credits_monthly, 0)

    def test_get_package(self):
        pkg = get_package("field_force")
        self.assertIsNotNone(pkg)
        self.assertEqual(pkg.name, "AskforWrite Field Operations Automation Suite")
        self.assertEqual(pkg.price_inr, 3999)
        self.assertEqual(pkg.price_usd, 49)

        missing = get_package("non_existent_key")
        self.assertIsNone(missing)

    def test_build_payment_link_razorpay(self):
        link = build_payment_link(
            package_key="seo_blog_copilot",
            customer_email="buyer@test.com",
            company="Acme Publishing",
            provider="razorpay",
        )
        self.assertIn("amount=199900", link)
        self.assertIn("notes_package=seo_blog_copilot", link)
        self.assertIn("notes_company=Acme+Publishing", link)

    def test_build_payment_link_paypal(self):
        link = build_payment_link(
            package_key="field_force",
            customer_email="buyer@test.com",
            company="Globex Logistics",
            provider="paypal",
        )
        self.assertIn("/49USD?memo=", link)
        self.assertIn("Globex+Logistics", link)

    def test_build_payment_link_fallback_package(self):
        # Invalid package key falls back to company_os_starter (7999 INR / 99 USD)
        link = build_payment_link(
            package_key="unknown_tool",
            company="Test Corp",
            provider="razorpay",
        )
        self.assertIn("amount=799900", link)
        self.assertIn("notes_package=company_os_starter", link)


class TestProvisioningService(unittest.TestCase):
    """Tests for automated tenant onboarding on payment webhooks."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.db = self.session_factory()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)

    @patch("app.services.provisioning.get_email_dispatcher")
    def test_auto_provision_razorpay_payment_captured(self, mock_dispatcher_fn):
        mock_dispatcher = MagicMock()
        mock_dispatcher_fn.return_value = mock_dispatcher

        event = WebhookEvent(
            id="evt_test_rzp_01",
            provider=PaymentProvider.RAZORPAY,
            event_type="payment.captured",
            raw_event_type="payment.captured",
            resource_type="payment",
            resource_id="pay_H12345678",
            data={
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_H12345678",
                            "email": "sarah.connor@cyberdyne.io",
                            "contact": "+919876543210",
                            "amount": 299900,
                            "currency": "INR",
                            "notes": {
                                "notes_company": "Cyberdyne Systems",
                                "notes_package": "marketing_suite",
                            },
                        }
                    }
                }
            },
        )

        result = auto_provision_tenant_on_payment(self.db, event)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "provisioned")
        self.assertEqual(result["email"], "sarah.connor@cyberdyne.io")
        self.assertEqual(result["package_key"], "marketing_suite")

        # Verify DB records
        org = self.db.query(OrganizationRecord).filter_by(id=result["org_id"]).first()
        self.assertIsNotNone(org)
        self.assertEqual(org.name, "Cyberdyne Systems")
        self.assertEqual(org.tier, "modular_marketing")
        self.assertEqual(org.lead_credits_limit, 50)
        self.assertEqual(org.outreach_credits_limit, 25)

        user = self.db.query(UserRecord).filter_by(id=result["user_id"]).first()
        self.assertIsNotNone(user)
        self.assertEqual(user.email, "sarah.connor@cyberdyne.io")
        self.assertEqual(user.role, "admin")
        self.assertTrue(user.is_active)

        invoice = self.db.query(InvoiceRecord).filter_by(org_id=org.id).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.amount, 299900)
        self.assertEqual(invoice.currency, "INR")
        self.assertEqual(invoice.status, "paid")

        customer = self.db.query(CustomerRecord).filter_by(org_id=org.id).first()
        self.assertIsNotNone(customer)
        self.assertEqual(customer.email, "sarah.connor@cyberdyne.io")

        audit = self.db.query(AuditLog).filter_by(action="tenant_auto_provisioned").first()
        self.assertIsNotNone(audit)

        # Verify welcome email was dispatched
        mock_dispatcher.send.assert_called_once()
        call_kwargs = mock_dispatcher.send.call_args[1]
        self.assertEqual(call_kwargs["recipient_email"], "sarah.connor@cyberdyne.io")
        self.assertIn("PixelBot Omnichannel Marketing Suite", call_kwargs["subject"])

    @patch("app.services.provisioning.get_email_dispatcher")
    def test_auto_provision_paypal_payment_completed(self, mock_dispatcher_fn):
        mock_dispatcher = MagicMock()
        mock_dispatcher_fn.return_value = mock_dispatcher

        event = WebhookEvent(
            id="evt_test_paypal_01",
            provider=PaymentProvider.PAYPAL,
            event_type="PAYMENT.CAPTURE.COMPLETED",
            raw_event_type="PAYMENT.CAPTURE.COMPLETED",
            resource_type="capture",
            resource_id="cap_987654321",
            data={
                "resource": {
                    "id": "cap_987654321",
                    "payer": {
                        "email_address": "john.doe@enterprise-corp.com",
                        "name": {
                            "given_name": "John",
                            "surname": "Doe",
                        },
                    },
                    "amount": {
                        "value": "99.00",
                        "currency_code": "USD",
                    },
                }
            },
        )

        result = auto_provision_tenant_on_payment(self.db, event)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "provisioned")
        self.assertEqual(result["email"], "john.doe@enterprise-corp.com")

        org = self.db.query(OrganizationRecord).filter_by(id=result["org_id"]).first()
        self.assertIsNotNone(org)
        self.assertEqual(org.name, "Enterprise-corp Operations")
        self.assertEqual(org.tier, "starter")

        inv = self.db.query(InvoiceRecord).filter_by(org_id=org.id).first()
        self.assertEqual(inv.currency, "USD")
        self.assertEqual(inv.amount, 9900)

    def test_auto_provision_skips_duplicate_user(self):
        # Create user in advance
        org = OrganizationRecord(
            id="org-existing-01",
            name="Existing Co",
            slug="existing-co",
            tier="starter",
            is_active=True,
        )
        user = UserRecord(
            id="user-existing-01",
            org_id="org-existing-01",
            email="already_exists@company.com",
            full_name="Existing User",
            role="admin",
            password_hash="fake-hash",
            is_active=True,
        )
        self.db.add(org)
        self.db.add(user)
        self.db.commit()

        event = WebhookEvent(
            id="evt_test_dup",
            provider=PaymentProvider.RAZORPAY,
            event_type="payment.captured",
            raw_event_type="payment.captured",
            resource_type="payment",
            resource_id="pay_dup123",
            data={
                "payload": {
                    "payment": {
                        "entity": {
                            "email": "already_exists@company.com",
                            "amount": 799900,
                            "currency": "INR",
                        }
                    }
                }
            },
        )

        result = auto_provision_tenant_on_payment(self.db, event)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "already_provisioned")
        self.assertEqual(result["org_id"], "org-existing-01")
        self.assertEqual(result["user_id"], "user-existing-01")

    def test_auto_provision_ignores_unsupported_events(self):
        event = WebhookEvent(
            id="evt_test_failed",
            provider=PaymentProvider.RAZORPAY,
            event_type="payment.failed",
            raw_event_type="payment.failed",
            resource_type="payment",
            resource_id="pay_fail001",
            data={},
        )
        result = auto_provision_tenant_on_payment(self.db, event)
        self.assertIsNone(result)

    def test_auto_provision_handles_missing_email(self):
        event = WebhookEvent(
            id="evt_test_no_email",
            provider=PaymentProvider.RAZORPAY,
            event_type="payment.captured",
            raw_event_type="payment.captured",
            resource_type="payment",
            resource_id="pay_no_email",
            data={
                "payload": {
                    "payment": {
                        "entity": {
                            "amount": 799900,
                            # missing email
                        }
                    }
                }
            },
        )
        result = auto_provision_tenant_on_payment(self.db, event)
        self.assertIsNone(result)

    def test_auto_provision_handles_slug_collisions(self):
        # Create first organization with slug "acme-operations"
        org1 = OrganizationRecord(
            id=str(uuid.uuid4()),
            name="Acme Operations",
            slug="acme-operations",
            tier="starter",
            is_active=True,
        )
        self.db.add(org1)
        self.db.commit()

        # Provision second organization with same company name
        event = WebhookEvent(
            id="evt_test_collision",
            provider=PaymentProvider.RAZORPAY,
            event_type="payment.captured",
            raw_event_type="payment.captured",
            resource_type="payment",
            resource_id="pay_col01",
            data={
                "payload": {
                    "payment": {
                        "entity": {
                            "email": "client2@acme.com",
                            "notes": {"notes_company": "Acme Operations"},
                            "amount": 799900,
                        }
                    }
                }
            },
        )

        with patch("app.services.provisioning.get_email_dispatcher"):
            result = auto_provision_tenant_on_payment(self.db, event)

        org2 = self.db.query(OrganizationRecord).filter_by(id=result["org_id"]).first()
        self.assertIsNotNone(org2)
        self.assertEqual(org2.slug, "acme-operations-1")
