"""Automated multi-tenant customer provisioning and onboarding engine.

Executed automatically when a Razorpay or PayPal payment/subscription is captured:
1. Auto-creates OrganizationRecord (tenant workspace)
2. Auto-creates UserRecord (admin account)
3. Generates InvoiceRecord (paid receipt)
4. Sends automated Welcome & Onboarding Email with access credentials via EmailDispatcher
"""

from __future__ import annotations

import logging
import re
import secrets
import uuid

from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    CustomerRecord,
    InvoiceRecord,
    OrganizationRecord,
    UserRecord,
)
from app.security.auth import hash_password
from app.services.catalog import CATALOG, get_package
from app.services.email_dispatcher import get_email_dispatcher
from app.services.payment import WebhookEvent

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", text.lower().strip())
    slug = re.sub(r"[\s_-]+", "-", cleaned).strip("-")
    return slug or "org"


def auto_provision_tenant_on_payment(
    db: Session,
    event: WebhookEvent,
) -> dict[str, object] | None:
    """Extract payment data, provision tenant organization and user, and dispatch welcome email."""
    # Only provision on confirmed capture / active subscription events
    valid_events = {
        "payment.captured",
        "subscription.activated",
        "subscription.charged",
        "PAYMENT.CAPTURE.COMPLETED",
        "BILLING.SUBSCRIPTION.ACTIVATED",
    }
    if event.event_type not in valid_events and event.raw_event_type not in valid_events:
        return None

    email = None
    customer_name = "Valued Client"
    company_name = None
    package_key = "company_os_starter"
    amount = 0.0
    currency = "INR"

    # Razorpay payload extraction
    if event.provider.value == "razorpay":
        payload_container = event.data.get("payload", {})
        payload_data = payload_container.get("payment", {}).get("entity", {})
        if not payload_data:
            payload_data = payload_container.get("subscription", {}).get("entity", {})
        if not payload_data:
            payload_data = event.data.get("payment", {}).get("entity", {}) or event.data.get("subscription", {}).get("entity", {})
        
        email = payload_data.get("email")
        contact = payload_data.get("contact", "")
        notes = payload_data.get("notes", {}) or {}
        company_name = notes.get("notes_company") or notes.get("company")
        package_key = notes.get("notes_package") or notes.get("package") or "company_os_starter"
        raw_amt = payload_data.get("amount", 0)
        amount = float(raw_amt) / 100.0 if raw_amt else 0.0
        currency = payload_data.get("currency", "INR")

    # PayPal payload extraction
    elif event.provider.value == "paypal":
        resource = event.data.get("resource", {})
        payer = resource.get("payer", {})
        email = payer.get("email_address")
        name_dict = payer.get("name", {})
        first_name = name_dict.get("given_name", "")
        last_name = name_dict.get("surname", "")
        customer_name = f"{first_name} {last_name}".strip() or "Valued Client"
        amount_dict = resource.get("amount", {})
        amount = float(amount_dict.get("value", 0.0))
        currency = amount_dict.get("currency_code", "USD")

    if not email or "@" not in email:
        logger.info("Webhook event %s did not contain customer email for auto-provisioning", event.id)
        return None

    email = email.lower().strip()

    # Determine company name from email domain if not provided in notes
    if not company_name:
        domain_part = email.split("@")[1].split(".")[0]
        company_name = f"{domain_part.capitalize()} Operations"

    # Check if a user with this email already exists
    existing_user = db.query(UserRecord).filter_by(email=email).first()
    if existing_user:
        logger.info("User %s already exists in org %s. Skipping duplicate provisioning.", email, existing_user.org_id)
        return {
            "status": "already_provisioned",
            "org_id": existing_user.org_id,
            "user_id": existing_user.id,
            "email": email,
        }

    # Lookup catalog package for entitlements
    pkg = get_package(package_key) or CATALOG["company_os_starter"]

    # 1. Create Organization
    base_slug = _slugify(company_name)
    slug = base_slug
    counter = 1
    while db.query(OrganizationRecord).filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    org_id = str(uuid.uuid4())
    org = OrganizationRecord(
        id=org_id,
        name=company_name,
        slug=slug,
        tier=pkg.tier,
        lead_credits_limit=pkg.lead_credits_monthly,
        lead_credits_used=0,
        outreach_credits_limit=pkg.outreach_credits_monthly,
        outreach_credits_used=0,
        is_active=True,
        metadata_json={
            "package_key": pkg.key,
            "package_name": pkg.name,
            "category": pkg.category,
            "entitled_capabilities": list(pkg.entitled_capabilities),
            "payment_provider": event.provider.value,
        },
    )
    db.add(org)

    # 2. Create User
    user_id = str(uuid.uuid4())
    temp_password = f"AFW-{secrets.token_urlsafe(6)}"
    user = UserRecord(
        id=user_id,
        org_id=org_id,
        email=email,
        full_name=customer_name,
        role="admin",
        password_hash=hash_password(temp_password),
        is_active=True,
        metadata_json={"temp_password": temp_password},
    )
    db.add(user)

    # 3. Create Customer and Invoice Records
    customer = db.query(CustomerRecord).filter_by(
        provider=event.provider.value,
        email=email,
    ).first()
    if not customer:
        customer = CustomerRecord(
            id=str(uuid.uuid4()),
            org_id=org_id,
            email=email,
            name=customer_name,
            provider=event.provider.value,
            provider_customer_id=f"cust_{uuid.uuid4().hex[:12]}",
        )
        db.add(customer)
        db.flush()

    invoice_id = str(uuid.uuid4())
    provider_inv_id = f"inv_{uuid.uuid4().hex[:12]}"
    amount_units = int(amount * 100) if amount > 0 else int((pkg.price_inr if currency == "INR" else pkg.price_usd) * 100)

    invoice = InvoiceRecord(
        id=invoice_id,
        org_id=org_id,
        customer_id=customer.id,
        provider=event.provider.value,
        provider_invoice_id=provider_inv_id,
        provider_payment_id=event.resource_id,
        amount=amount_units,
        currency=currency,
        status="paid",
        metadata_json={
            "customer_email": email,
            "package_key": pkg.key,
            "event_id": event.id,
        },
    )
    db.add(invoice)

    # 4. Dispatch Welcome Email via EmailDispatcher
    welcome_subject = f"Welcome to AskforWrite AI Company OS — Your {pkg.name} Access"
    welcome_body = (
        f"Hi {customer_name},\n\n"
        f"Thank you for your payment! Your dedicated workspace for {company_name} is now active.\n\n"
        f"Subscription Summary:\n"
        f"• Package: {pkg.name}\n"
        f"• Type: {pkg.category.replace('_', ' ').title()}\n"
        f"• Monthly Lead Discovery Credits: {pkg.lead_credits_monthly}\n"
        f"• Monthly Outreach Credits: {pkg.outreach_credits_monthly}\n"
        f"• Invoice Reference: {provider_inv_id}\n\n"
        f"Your Access Details:\n"
        f"• Portal URL: https://os.askforwrite.com/login\n"
        f"• Email: {email}\n"
        f"• Temporary Passkey: {temp_password}\n\n"
        f"You can begin using your specialist capabilities immediately.\n\n"
        f"Best regards,\n"
        f"The AskforWrite AI Team"
    )

    try:
        dispatcher = get_email_dispatcher()
        dispatcher.send(
            recipient_email=email,
            subject=welcome_subject,
            body_text=welcome_body,
        )
        logger.info("Dispatched welcome onboarding email to %s", email)
    except Exception as exc:
        logger.error("Failed to send welcome email to %s: %s", email, exc)

    # 5. Audit Log
    db.add(
        AuditLog(
            task_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            agent_id="provisioning_engine",
            capability_name="customer_onboarding",
            action="tenant_auto_provisioned",
            input_payload={"email": email, "package_key": pkg.key, "provider": event.provider.value},
            output_payload={"org_id": org_id, "user_id": user_id, "invoice_id": invoice_id},
            status="COMPLETED",
        )
    )
    db.commit()

    return {
        "status": "provisioned",
        "org_id": org_id,
        "user_id": user_id,
        "email": email,
        "package_key": pkg.key,
        "temp_password": temp_password,
    }
