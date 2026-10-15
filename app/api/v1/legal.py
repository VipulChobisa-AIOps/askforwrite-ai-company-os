"""Legal pages router — Terms of Service and Privacy Policy.

Provides publicly accessible endpoints (no auth required):
- GET /legal/tos      — Terms of Service
- GET /legal/privacy  — Privacy Policy

Both endpoints return structured JSON (for embedding in customer UIs)
and also support plain-text rendering for scraping/SEO.

Update document content in the DOCUMENTS dict below before going live.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/legal", tags=["legal"])

# ── Document Content ──────────────────────────────────────────────────────────

_TOS_EFFECTIVE = date(2026, 10, 14)
_PRIVACY_EFFECTIVE = date(2026, 10, 14)

TERMS_OF_SERVICE = {
    "title": "AskforWrite AI Company OS — Terms of Service",
    "effective_date": str(_TOS_EFFECTIVE),
    "company": "AskforWrite Technologies",
    "contact": "legal@askforwrite.in",
    "sections": [
        {
            "heading": "1. Acceptance of Terms",
            "body": (
                "By accessing or using the AskforWrite AI Company OS platform (the \"Service\"), "
                "you agree to be bound by these Terms of Service. If you do not agree to these terms, "
                "you may not use the Service. These terms apply to all users including field agents, "
                "administrators, and organization owners."
            ),
        },
        {
            "heading": "2. Description of Service",
            "body": (
                "AskforWrite AI Company OS is a B2B SaaS platform providing AI-powered field force management, "
                "lead discovery, sales orchestration, revenue generation, and outreach capabilities. "
                "The platform operates with Human-in-the-Loop (HITL) governance, meaning certain actions "
                "require explicit Owner authorization before execution."
            ),
        },
        {
            "heading": "3. User Accounts and Security",
            "body": (
                "You are responsible for maintaining the confidentiality of your API keys, bearer tokens, "
                "and login credentials. You must notify us immediately at security@askforwrite.in if you "
                "suspect any unauthorized access to your account. AskforWrite is not liable for losses "
                "resulting from unauthorized use of your credentials."
            ),
        },
        {
            "heading": "4. Data Ownership and Privacy",
            "body": (
                "You retain ownership of all data you upload or generate through the Service. "
                "AskforWrite processes your data solely to provide the contracted services. "
                "We do not sell, rent, or share your business data with third parties except as "
                "required by law or to operate core payment providers (Razorpay, PayPal). "
                "See our Privacy Policy for full details."
            ),
        },
        {
            "heading": "5. Subscription and Billing",
            "body": (
                "Subscriptions are billed monthly in advance. Credit quotas (lead discovery credits, "
                "outreach credits) reset at the start of each billing cycle. Unused credits do not roll over. "
                "Refund requests must be submitted within 7 days of payment to billing@askforwrite.in. "
                "AskforWrite reserves the right to suspend accounts with overdue payments after 7 days notice."
            ),
        },
        {
            "heading": "6. Acceptable Use",
            "body": (
                "You agree not to use the Service to: (a) send spam or unsolicited communications; "
                "(b) violate any applicable laws or regulations; (c) impersonate any person or entity; "
                "(d) reverse-engineer or attempt to extract the source code of the platform; "
                "(e) exceed API rate limits in a manner that degrades service for other users."
            ),
        },
        {
            "heading": "7. Limitation of Liability",
            "body": (
                "To the maximum extent permitted by law, AskforWrite's total liability for any claim "
                "arising from use of the Service shall not exceed the amount paid by you in the 3 months "
                "preceding the claim. AskforWrite is not liable for indirect, incidental, or consequential damages."
            ),
        },
        {
            "heading": "8. Governing Law",
            "body": (
                "These Terms are governed by the laws of India. Any disputes shall be resolved by "
                "arbitration in Jaipur, Rajasthan, under the Arbitration and Conciliation Act, 1996."
            ),
        },
        {
            "heading": "9. Modifications",
            "body": (
                "AskforWrite reserves the right to modify these Terms at any time. We will notify active "
                "subscribers 14 days before material changes take effect via email. Continued use after "
                "the effective date constitutes acceptance of the updated Terms."
            ),
        },
    ],
}

PRIVACY_POLICY = {
    "title": "AskforWrite AI Company OS — Privacy Policy",
    "effective_date": str(_PRIVACY_EFFECTIVE),
    "company": "AskforWrite Technologies",
    "contact": "privacy@askforwrite.in",
    "sections": [
        {
            "heading": "1. Information We Collect",
            "body": (
                "We collect: (a) Account information — name, email, company name, role; "
                "(b) Usage data — API calls, credit consumption, feature usage, timestamps; "
                "(c) Field data — GPS coordinates, attendance records, visit verifications submitted by agents; "
                "(d) Payment data — processed via Razorpay/PayPal; we store only invoice references, "
                "not card numbers; (e) Communication logs — outreach emails sent through our dispatch engine."
            ),
        },
        {
            "heading": "2. How We Use Your Data",
            "body": (
                "We use your data to: (a) Provide and improve the Service; (b) Process billing and issue invoices; "
                "(c) Send service-critical notifications (password resets, quota warnings, billing receipts); "
                "(d) Generate AI-driven insights within your organization's private workspace; "
                "(e) Maintain the cryptographic audit trail for compliance and governance."
            ),
        },
        {
            "heading": "3. Data Isolation and Multi-Tenancy",
            "body": (
                "All customer data is scoped to your organization (tenant) by org_id. "
                "No data from one organization is accessible to another. "
                "Owner and Manager API keys are isolated per organization. "
                "The cryptographic trust ledger is per-organization and tamper-evident."
            ),
        },
        {
            "heading": "4. Data Retention",
            "body": (
                "We retain your data for the duration of your subscription plus 90 days after termination, "
                "after which it is permanently deleted. Audit logs are retained for 7 years for legal compliance. "
                "You may request early deletion by contacting privacy@askforwrite.in."
            ),
        },
        {
            "heading": "5. Third-Party Services",
            "body": (
                "We use the following third-party processors: Razorpay (India payments), PayPal (global payments), "
                "SendGrid/SMTP (email delivery), Sentry (error monitoring), LangSmith (AI observability). "
                "Each provider has their own data processing agreements. We do not use your data for "
                "training third-party AI models."
            ),
        },
        {
            "heading": "6. Your Rights",
            "body": (
                "Under applicable data protection laws, you have the right to: (a) Access your personal data; "
                "(b) Correct inaccurate data; (c) Request deletion ('right to be forgotten'); "
                "(d) Export your data in machine-readable format (use GET /v1/audit/export); "
                "(e) Object to processing for marketing purposes. "
                "Submit requests to privacy@askforwrite.in with subject 'Data Rights Request'."
            ),
        },
        {
            "heading": "7. Security Measures",
            "body": (
                "We implement: ECDSA P-256 cryptographic signing for all audit blocks; "
                "bcrypt password hashing with work factor 12; TLS 1.3 in transit; "
                "tenant-aware rate limiting; API key-based role separation (Owner vs Manager vs Customer); "
                "structured JSON logging with Sentry error tracking; "
                "PostgreSQL with connection pooling in production."
            ),
        },
        {
            "heading": "8. Contact",
            "body": (
                "For privacy-related inquiries: privacy@askforwrite.in. "
                "For security vulnerabilities: security@askforwrite.in. "
                "Registered address: AskforWrite Technologies, Jaipur, Rajasthan, India."
            ),
        },
    ],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_plain_text(doc: dict) -> str:
    lines = [doc["title"], "=" * len(doc["title"]), f"Effective: {doc['effective_date']}", ""]
    for section in doc.get("sections", []):
        lines.append(section["heading"])
        lines.append("-" * len(section["heading"]))
        lines.append(section["body"])
        lines.append("")
    lines.append(f"Contact: {doc['contact']}")
    return "\n".join(lines)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/tos",
    summary="Terms of Service",
    operation_id="get_terms_of_service",
)
def get_terms_of_service(
    format: str = Query(default="json", pattern="^(json|text)$", description="Response format: json or text"),
):
    """Return the AskforWrite AI Company OS Terms of Service.

    Supports JSON (for embedding in customer UI) and plain-text (for SEO/scraping).
    No authentication required — this is a public endpoint.
    """
    if format == "text":
        return PlainTextResponse(_to_plain_text(TERMS_OF_SERVICE))
    return TERMS_OF_SERVICE


@router.get(
    "/privacy",
    summary="Privacy Policy",
    operation_id="get_privacy_policy",
)
def get_privacy_policy(
    format: str = Query(default="json", pattern="^(json|text)$", description="Response format: json or text"),
):
    """Return the AskforWrite AI Company OS Privacy Policy.

    Supports JSON (for embedding in customer UI) and plain-text (for SEO/scraping).
    No authentication required — this is a public endpoint.
    """
    if format == "text":
        return PlainTextResponse(_to_plain_text(PRIVACY_POLICY))
    return PRIVACY_POLICY
