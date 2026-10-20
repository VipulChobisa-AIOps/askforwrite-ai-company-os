"""Legal & Statutory Compliance Router — Terms of Service, Privacy Policy, MSME Declaration.

Firm Legal Entity: ASKFORWRITE
Enterprise Category: Micro, Small & Medium Enterprise (MSME), Government of India
Udyam Registration Number: UDYAM-RJ-14-0018404
Copyright: © 2026 ASKFORWRITE (UDYAM-RJ-14-0018404). All Rights Reserved.
Registered Jurisdiction: Udaipur, Rajasthan, India - 313001

Provides publicly accessible endpoints (no auth required):
- GET /legal/tos           — Terms of Service & Enterprise Agreement
- GET /legal/privacy       — Privacy Policy & Strict BYOK Data Protection
- GET /legal/declaration   — Statutory MSME Declaration & Registration Verification
- GET /legal/refund-policy — Sovereign Settlement, Refund & Cancellation Policy
- GET /legal/all           — Bundled legal dataset for dashboard modal integration
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/legal", tags=["legal"])

# ── Effective Dates & Enterprise Metadata ─────────────────────────────────────

_TOS_EFFECTIVE = date(2026, 10, 14)
_PRIVACY_EFFECTIVE = date(2026, 10, 14)
_DECLARATION_EFFECTIVE = date(2026, 10, 14)
_REFUND_EFFECTIVE = date(2026, 10, 14)

COMPANY_METADATA = {
    "legal_name": "ASKFORWRITE",
    "trade_name": "ASKFORWRITE",
    "category": "Micro, Small & Medium Enterprise (MSME)",
    "udyam_registration": "UDYAM-RJ-14-0018404",
    "ministry": "Ministry of Micro, Small and Medium Enterprises, Government of India",
    "jurisdiction": "Udaipur, Rajasthan, India - 313001",
    "primary_website": "https://os.askforwrite.com",
    "legal_email": "legal@askforwrite.in",
    "privacy_email": "privacy@askforwrite.in",
    "compliance_email": "compliance@askforwrite.in",
    "billing_email": "billing@askforwrite.in",
    "copyright": "© 2026 ASKFORWRITE (UDYAM-RJ-14-0018404). All Rights Reserved.",
}

# ── 1. Terms of Service & Enterprise Agreement ───────────────────────────────

TERMS_OF_SERVICE = {
    "title": "AskforWrite AI Company OS — Terms of Service & Enterprise Agreement",
    "effective_date": str(_TOS_EFFECTIVE),
    "company": "ASKFORWRITE",
    "enterprise_type": "MSME Registered Enterprise (Government of India)",
    "udyam_registration": "UDYAM-RJ-14-0018404",
    "registered_office": "Udaipur, Rajasthan, India - 313001",
    "contact": "legal@askforwrite.in",
    "copyright": "© 2026 ASKFORWRITE (UDYAM-RJ-14-0018404). All Rights Reserved.",
    "sections": [
        {
            "heading": "1. Acceptance of Terms & Statutory Entity",
            "body": (
                "By accessing, registering on, or operating within the AskforWrite AI Company OS platform "
                "(the \"Service\"), hosted on os.askforwrite.com and affiliated subdomains, you enter into a legally "
                "binding contract with ASKFORWRITE, a registered Micro, Small & Medium Enterprise (MSME) under "
                "Government of India Udyam Registration Number UDYAM-RJ-14-0018404. If you do not agree to these terms, "
                "you are prohibited from accessing or using the Service. These terms apply uniformly to organization owners, "
                "commercial tenants, enterprise clients, administrators, and field personnel."
            ),
        },
        {
            "heading": "2. Description of Autonomous Multi-Agent Service",
            "body": (
                "AskforWrite AI Company OS provides an enterprise autonomous workspace orchestrating AI agents across "
                "lead discovery, research synthesis, proposal drafting, human-in-the-loop (HITL) approval governance, "
                "field force telematics verification, and direct commercial settlements. All actions modifying tenant status "
                "or dispatching external communications are cryptographically signed and sealed into an immutable "
                "ECDSA NIST P-256 Merkle Trust Ledger."
            ),
        },
        {
            "heading": "3. Strict Bring-Your-Own-Key (BYOK) Gemini API Isolation",
            "body": (
                "To prevent commercial quota contention and protect tenant autonomy, commercial tenants and customers "
                "are required to supply their own Google Gemini API key (\"BYOK\"). Tenant requests operate strictly on the "
                "tenant's supplied key and never consume, hammer, or draw down the Owner's server quota. If a commercial "
                "tenant executes an AI request without configuring a BYOK key, the system executes a zero-cost deterministic "
                "rule-based fallback. ASKFORWRITE charges zero markup or surcharge on tenant LLM token usage."
            ),
        },
        {
            "heading": "4. User Accounts, Credentials & Role Separation",
            "body": (
                "Accounts are partitioned by cryptographic Organization IDs (tenants). You are solely responsible for safeguarding "
                "your API keys, JWT bearer tokens, and passwords. Any activity conducted under your credentials is your legal "
                "responsibility. In the event of suspected unauthorized access, you must notify security@askforwrite.in immediately. "
                "Owner Command Center access requires authorized 32-character API key authentication and remains restricted to "
                "verified company managers."
            ),
        },
        {
            "heading": "5. Data Ownership, Provenance & Cryptographic Trust Ledger",
            "body": (
                "Each organization retains 100% legal ownership over its proprietary business inputs, prospect records, "
                "and analytical outputs. ASKFORWRITE processes data strictly to fulfill contracted service execution. "
                "Every milestone, order fulfillment, and attendance verification is hashed and appended to a tamper-evident "
                "Merkle DAG trust chain, providing exportable proof of data provenance under Section 65B of the Indian Evidence Act."
            ),
        },
        {
            "heading": "6. Sovereign DirectPay & Subscription Settlements",
            "body": (
                "Service plans (including Growth All-in-One, Company OS Starter, and Modular Operations) are billed in advance. "
                "Settlements processed via AFW DirectPay (NPCI UPI to ask4write@icici, ICICI Bank wire, or Web3 USDC) "
                "are direct zero-fee peer-to-merchant settlements. Verified transactions immediately seal a NIST P-256 block "
                "and auto-provision tenant capabilities with an immutable proforma receipt."
            ),
        },
        {
            "heading": "7. Acceptable Use Policy",
            "body": (
                "You agree not to use the Service to: (a) send unlawful, harassing, or unsolicited bulk email; (b) spoof GPS, "
                "biometrics, or visit proof in field operations; (c) reverse-engineer or decompile platform agent architectures; "
                "(d) bypass rate limits or compromise tenant cryptographic isolation; (e) utilize the platform for any activity "
                "violating the laws of India or the laws of your operating jurisdiction."
            ),
        },
        {
            "heading": "8. Intellectual Property & Copyright Notice",
            "body": (
                "All platform code, design interfaces, mathematical optimization algorithms, multi-agent coordination state machines, "
                "trademarks, and logos are the sole intellectual property of ASKFORWRITE (UDYAM-RJ-14-0018404). Unauthorized reproduction, "
                "mirroring, or commercial redistribution without prior written consent is strictly prohibited and subject to civil and "
                "criminal remedies under the Copyright Act, 1957."
            ),
        },
        {
            "heading": "9. Limitation of Liability",
            "body": (
                "To the maximum extent permitted by applicable law, ASKFORWRITE's cumulative liability for any dispute arising out "
                "of or relating to the Service shall not exceed the aggregate fees actually paid by the tenant in the three (3) months "
                "immediately preceding the event giving rise to liability. In no event shall ASKFORWRITE be liable for indirect, punitive, "
                "special, or consequential damages."
            ),
        },
        {
            "heading": "10. Governing Law & Dispute Resolution",
            "body": (
                "These Terms are governed by and construed in accordance with the laws of the Republic of India, including the "
                "Information Technology Act, 2000, and the Micro, Small and Medium Enterprises Development (MSMED) Act, 2006. "
                "Any dispute or claim shall be subject to the exclusive jurisdiction of the competent courts and MSME Conciliation "
                "Tribunals in Udaipur, Rajasthan, India."
            ),
        },
    ],
}

# ── 2. Privacy Policy & BYOK Data Protection Declaration ──────────────────────

PRIVACY_POLICY = {
    "title": "AskforWrite AI Company OS — Privacy Policy & Data Protection Declaration",
    "effective_date": str(_PRIVACY_EFFECTIVE),
    "company": "ASKFORWRITE",
    "enterprise_type": "MSME Registered Enterprise (Government of India)",
    "udyam_registration": "UDYAM-RJ-14-0018404",
    "registered_office": "Udaipur, Rajasthan, India - 313001",
    "contact": "privacy@askforwrite.in",
    "copyright": "© 2026 ASKFORWRITE (UDYAM-RJ-14-0018404). All Rights Reserved.",
    "sections": [
        {
            "heading": "1. Data Collection Scope",
            "body": (
                "We collect: (a) Account Identifiers: Name, company name, work email address, and PBKDF2/bcrypt-hashed credentials; "
                "(b) Organizational Metadata: Tenant slug, subscription tier, and entitled capability SKUs; "
                "(c) Field Telematics: Device coordinates, geofence timestamps, and cryptographic visit proof images/OTP verifications; "
                "(d) Payment References: Bank UTR numbers, transaction hashes, and invoice metadata (no credit card numbers are ever stored); "
                "(e) Cryptographic Audit Blocks: SHA-256 and ECDSA signatures ensuring tamper-evident provenance."
            ),
        },
        {
            "heading": "2. Strict BYOK Gemini Key Privacy & Zero-Retention Guarantee",
            "body": (
                "When you supply a Bring-Your-Own-Key (BYOK) Gemini API key (via request headers or your Customer Portal), "
                "it is treated as strictly confidential tenant property. It is: (a) stored encrypted in tenant metadata and masked in "
                "all API responses (e.g. AIza••••••••••••••••1a2b); (b) never printed in application logs or shared with any third party; "
                "(c) never accessible to other tenants; (d) never used to power any system-wide operations; (e) purged immediately upon "
                "tenant self-service removal or account deletion. ASKFORWRITE never trains machine learning models on tenant data."
            ),
        },
        {
            "heading": "3. Tenant Isolation & Multi-Tenant Architecture",
            "body": (
                "All customer records are partitioned strictly by organization ID (`org_id`). Database queries enforce tenant-scoped "
                "foreign key filters. Row-level data is inaccessible to unauthorized tenants. API rate-limiting dynamically protects "
                "each tenant from noisy-neighbor interference."
            ),
        },
        {
            "heading": "4. Data Retention, Portability & Right to Erasure",
            "body": (
                "Tenant operational data is retained for the active subscription period plus a 90-day grace period, after which it is "
                "permanently purged upon request. Under the Digital Personal Data Protection Act, 2023 (DPDPA), users have the absolute "
                "right to access, rectify, export (via GET /v1/audit/export in JSON/CSV), or delete their personal data by contacting "
                "privacy@askforwrite.in."
            ),
        },
        {
            "heading": "5. Subprocessors & Third-Party Processors",
            "body": (
                "We utilize strictly vetted subprocessors under bilateral data protection standards: "
                "(a) Google Cloud / Google AI (Gemini inference via tenant BYOK key); "
                "(b) ICICI Bank & Sovereign DirectPay (payment settlement verification); "
                "(c) Sentry & LangSmith (error telemetry and optional trace telemetry with PII scrubbed); "
                "(d) Redis Labs / In-Memory (sliding-window rate limiting)."
            ),
        },
        {
            "heading": "6. Security Infrastructure & Compliance",
            "body": (
                "Platform security controls include: TLS 1.3 encryption in transit; AES-256 encryption at rest; "
                "ECDSA NIST P-256 cryptographic audit sealing; strict Content-Security-Policy, HSTS, and X-Frame-Options headers; "
                "and automated rate limiting on all authentication and approval endpoints."
            ),
        },
        {
            "heading": "7. Data Grievance Officer & Statutory Contact",
            "body": (
                "In accordance with the Information Technology Act, 2000, and the Digital Personal Data Protection Act, 2023, "
                "the details of the Data Grievance Officer are: "
                "Name: Vipul Kumar Chobisa | Firm: ASKFORWRITE (UDYAM-RJ-14-0018404) | "
                "Email: compliance@askforwrite.in | Address: Udaipur Bus Stand, Udaipur, Rajasthan, India - 313001. "
                "All grievances are acknowledged within 24 hours and resolved within statutory timeframes."
            ),
        },
    ],
}

# ── 3. Statutory MSME Enterprise Declaration ─────────────────────────────────

MSME_DECLARATION = {
    "title": "ASKFORWRITE — Statutory MSME Enterprise Declaration & Legal Identity",
    "effective_date": str(_DECLARATION_EFFECTIVE),
    "firm_legal_name": "ASKFORWRITE",
    "trade_name": "ASKFORWRITE",
    "enterprise_type": "Micro Enterprise (Services)",
    "udyam_registration_number": "UDYAM-RJ-14-0018404",
    "issuing_ministry": "Ministry of Micro, Small and Medium Enterprises, Government of India",
    "national_industry_classification_codes": [
        {"code": "6201", "description": "Computer programming activities"},
        {"code": "6202", "description": "Computer consultancy and computer facilities management activities"},
        {"code": "6209", "description": "Other information technology and computer service activities"},
    ],
    "registered_office": {
        "locality": "Udaipur Bus Stand",
        "city": "Udaipur",
        "district": "Udaipur",
        "state": "Rajasthan",
        "country": "India",
        "pincode": "313001",
    },
    "banking_and_settlement_coordinates": {
        "bank_name": "ICICI Bank Ltd",
        "beneficiary_name": "Vipul Kumar Chobisa / ASKFORWRITE",
        "account_type": "Saving Account",
        "ifsc_code": "ICIC0006940",
        "branch": "Udaipur Bus Stand, Udaipur, Rajasthan, India - 313001",
        "merchant_upi_vpa": "ask4write@icici",
    },
    "statutory_protections": (
        "As a formally registered MSME under the MSMED Act, 2006, ASKFORWRITE is entitled to statutory protections "
        "regarding timely payment of buyer dues (Section 15 & 16) and mandatory interest on delayed payments. "
        "All invoices issued by ASKFORWRITE bear statutory Udyam identifier UDYAM-RJ-14-0018404."
    ),
    "compliance_officer": {
        "name": "Vipul Kumar Chobisa",
        "designation": "Proprietor & Principal Compliance Officer",
        "email": "compliance@askforwrite.in",
        "phone_inquiries": "support@askforwrite.in",
    },
    "copyright": "© 2026 ASKFORWRITE (UDYAM-RJ-14-0018404). All Rights Reserved.",
}

# ── 4. Refund, Cancellation & Settlement Policy ──────────────────────────────

REFUND_POLICY = {
    "title": "AskforWrite AI Company OS — Refund, Cancellation & Settlement Policy",
    "effective_date": str(_REFUND_EFFECTIVE),
    "company": "ASKFORWRITE",
    "enterprise_type": "MSME Registered Enterprise (UDYAM-RJ-14-0018404)",
    "contact": "billing@askforwrite.in",
    "copyright": "© 2026 ASKFORWRITE (UDYAM-RJ-14-0018404). All Rights Reserved.",
    "sections": [
        {
            "heading": "1. Subscription Cancellations",
            "body": (
                "You may cancel your monthly or annual subscription at any time directly through the Customer Portal "
                "or by emailing billing@askforwrite.in. Upon cancellation, your workspace remains active until the end of "
                "the current paid billing period, with zero automated renewal charges thereafter."
            ),
        },
        {
            "heading": "2. 7-Day Money-Back Guarantee for Unutilized Plans",
            "body": (
                "If you are not completely satisfied with AskforWrite AI Company OS, you may request a full refund within "
                "seven (7) days of initial package payment, provided that you have consumed less than 20% of your plan's "
                "monthly credit allocation (discovery credits, outreach dispatches, or AI tokens). Refunds are issued "
                "back to the original settlement method (UPI or Bank Account) within 5 to 7 business days."
            ),
        },
        {
            "heading": "3. Sovereign DirectPay & Instant Provisioning",
            "body": (
                "AFW DirectPay payments made via UPI (ask4write@icici), NEFT/RTGS bank wire, or Web3 USDC are direct settlements. "
                "If a payment verification fails due to an erroneous reference code or duplicate submission, our automated "
                "reconciliation watchdog flags the transaction for manual review and confirmation by the billing administrator "
                "within 12 hours."
            ),
        },
        {
            "heading": "4. Dispute Resolution & Grievances",
            "body": (
                "For any billing discrepancy or payment concern, please contact billing@askforwrite.in with your transaction "
                "reference number. Under the MSMED Act, 2006, commercial payment disputes may also be addressed via the MSME "
                "Samadhaan conciliation mechanism in Udaipur, Rajasthan."
            ),
        },
    ],
}


# ── Plain-Text Formatter ──────────────────────────────────────────────────────

def _to_plain_text(doc: dict[str, Any]) -> str:
    lines = [
        doc.get("title", "Legal Document"),
        "=" * len(doc.get("title", "Legal Document")),
        f"Entity: {doc.get('company', COMPANY_METADATA['legal_name'])}",
        f"MSME Udyam Registration: {doc.get('udyam_registration', COMPANY_METADATA['udyam_registration'])}",
        f"Effective: {doc.get('effective_date', '2026-10-14')}",
        f"Jurisdiction: {COMPANY_METADATA['jurisdiction']}",
        "",
    ]
    for section in doc.get("sections", []):
        lines.append(section["heading"])
        lines.append("-" * len(section["heading"]))
        lines.append(section["body"])
        lines.append("")

    lines.append(doc.get("copyright", COMPANY_METADATA["copyright"]))
    lines.append(f"Official Contact: {doc.get('contact', COMPANY_METADATA['legal_email'])}")
    return "\n".join(lines)


# ── Public Endpoints ──────────────────────────────────────────────────────────

@router.get(
    "/tos",
    summary="Terms of Service & Enterprise Agreement",
    operation_id="get_terms_of_service",
)
def get_terms_of_service(
    format: str = Query(default="json", pattern="^(json|text)$", description="Response format: json or text"),
) -> Any:
    """Return the AskforWrite AI Company OS Terms of Service.

    Includes MSME Udyam Registration (UDYAM-RJ-14-0018404) statutory details,
    Strict BYOK Gemini isolation clause, and intellectual property copyright.
    """
    if format == "text":
        return PlainTextResponse(_to_plain_text(TERMS_OF_SERVICE))
    return TERMS_OF_SERVICE


@router.get(
    "/privacy",
    summary="Privacy Policy & BYOK Data Protection",
    operation_id="get_privacy_policy",
)
def get_privacy_policy(
    format: str = Query(default="json", pattern="^(json|text)$", description="Response format: json or text"),
) -> Any:
    """Return the AskforWrite AI Company OS Privacy Policy.

    Includes strict BYOK Gemini key zero-retention guarantee, multi-tenant isolation,
    and DPDPA 2023 statutory compliance.
    """
    if format == "text":
        return PlainTextResponse(_to_plain_text(PRIVACY_POLICY))
    return PRIVACY_POLICY


@router.get(
    "/declaration",
    summary="Statutory MSME Enterprise Declaration",
    operation_id="get_msme_declaration",
)
def get_msme_declaration(
    format: str = Query(default="json", pattern="^(json|text)$", description="Response format: json or text"),
) -> Any:
    """Return official MSME Enterprise Declaration under Udyam Registration UDYAM-RJ-14-0018404."""
    if format == "text":
        text_lines = [
            MSME_DECLARATION["title"],
            "=" * len(MSME_DECLARATION["title"]),
            f"Firm Legal Name: {MSME_DECLARATION['firm_legal_name']}",
            f"Enterprise Category: {MSME_DECLARATION['enterprise_type']}",
            f"Udyam Registration Number: {MSME_DECLARATION['udyam_registration_number']}",
            f"Issuing Ministry: {MSME_DECLARATION['issuing_ministry']}",
            f"Jurisdiction: {MSME_DECLARATION['registered_office']['city']}, {MSME_DECLARATION['registered_office']['state']}, India",
            f"Effective: {MSME_DECLARATION['effective_date']}",
            "",
            "Statutory Protections:",
            MSME_DECLARATION["statutory_statutes"],
            "",
            MSME_DECLARATION["copyright"],
        ]
        return PlainTextResponse("\n".join(text_lines))
    return MSME_DECLARATION


@router.get(
    "/refund-policy",
    summary="Refund, Cancellation & Settlement Policy",
    operation_id="get_refund_policy",
)
def get_refund_policy(
    format: str = Query(default="json", pattern="^(json|text)$", description="Response format: json or text"),
) -> Any:
    """Return the AskforWrite AI Company OS Refund & Cancellation Policy."""
    if format == "text":
        return PlainTextResponse(_to_plain_text(REFUND_POLICY))
    return REFUND_POLICY


@router.get(
    "/all",
    summary="Bundled Legal Documents & MSME Declarations",
    operation_id="get_all_legal_documents",
)
def get_all_legal_documents() -> dict[str, Any]:
    """Return all statutory legal declarations, terms, privacy, and refund policies in a single payload."""
    return {
        "metadata": COMPANY_METADATA,
        "terms_of_service": TERMS_OF_SERVICE,
        "privacy_policy": PRIVACY_POLICY,
        "msme_declaration": MSME_DECLARATION,
        "refund_policy": REFUND_POLICY,
    }
