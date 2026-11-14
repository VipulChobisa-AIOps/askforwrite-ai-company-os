# P2 Commercial Architecture — First Customer Acquisition & Revenue Engine

## 1. Mission & Commercial Boundary

P2 turns AskforWrite AI Company OS into an evidence-backed customer acquisition and revenue operating engine focused on one clear segment and one verified entry offer:

- **Target Segment:** Small and medium-sized digital marketing and SEO agencies in India.
- **Verified Entry Offer:** `managed_seo_content_pilot` — *AskforWrite Managed SEO & Content Pilot (14-Day)*
  - **Catalog Price:** INR 4,999 / USD 59
  - **Billing Type & Interval:** `managed_pilot_14d` / `14_days`
  - **Entitled Capabilities:** `seo_content_automation`, `evidence_research`, `trust_ledger_audit`
  - **Included Credits:** `50` lead credits, `25` outreach credits, `100` AI execution credits
  - **Explicit Non-Guarantees:** No #1 search ranking guarantee, no ROI/revenue multiple guarantee, and automatic recurring renewal is disabled (`auto_charge_disabled=True`).

---

## 2. End-to-End 12-Stage Commercial Journey

```
Prospect -> Research -> Qualification -> Owner Approval -> Outreach -> Response ->
Discovery -> Proposal -> Payment -> Customer Activation -> Service Delivery -> Renewal
```

The system exposes explicit, audit-logged state transitions across all 12 P2 pipeline statuses:
`NEW`, `RESEARCHING`, `QUALIFIED`, `DISQUALIFIED`, `APPROVAL_PENDING`, `CONTACTED`, `RESPONDED`, `DISCOVERY`, `PROPOSAL_PENDING`, `WON`, `LOST`, `DO_NOT_CONTACT`.

---

## 3. Core Architecture & Reused P0/P1 Foundations

| Module | Implementation File(s) | Key Responsibilities |
|---|---|---|
| **A. Prospect Intelligence** | `app/services/p2_prospect_intel.py` | Curated real agency intake, live website inspection, configured live discovery gate (`BLOCKED` in simulation/unverified), domain + normalized company identity deduplication, strict rejection of synthetic fixtures, source URL + collection date provenance. |
| **B. 6-Criterion Qualification** | `app/services/p2_prospect_intel.py` | Configurable scoring rubric across `icp_fit`, `need_evidence`, `activity_website_quality`, `service_fit`, `contact_validity`, and `evidence_freshness` (0–100 scale) with supporting evidence citations. |
| **C. Account Intelligence Brief** | `app/services/p2_prospect_intel.py` | Generates structured briefs separating **Verified Facts**, **Reasonable Inferences**, and **Unverified Assumptions**, plus recommended discovery questions and first-contact guidance. |
| **D. Honesty-Validated & HITL Outreach** | `app/services/p2_outreach_pipeline.py`, `app/services/suppression.py` | Regex honesty validator rejecting invented calls/guarantees/discounts/false urgency, DB-backed suppression (`p2_suppression_entries`), duplicate draft block, rate limits, mandatory Owner HITL `ApprovalRequest`, and strict separation of `SENT` (`LIVE_PROVIDER_VERIFIED`) vs `SIMULATED_SENT` (`SIMULATED_SYNTHETIC`). |
| **E. Sales Pipeline & Discovery** | `app/services/p2_outreach_pipeline.py` | Response logging (`response_history_json` + `ConversationRecord`), sentiment-triggered opt-out suppression, discovery note capture, and `AuditLog` status tracking. |
| **F. Catalog-Verified Structured Proposals** | `app/services/p2_proposal_settlement.py` | 8-clause proposals priced directly from `app/services/catalog.py`, gated by Owner `proposal_delivery` HITL approval before sharing or checkout generation. |
| **G. Payment-to-Activation Settlement** | `app/services/p2_proposal_settlement.py`, `app/api/v1/webhooks.py`, `app/services/sovereign_pay.py` | Generating checkout never marks `WON` or activates a workspace. Only signed webhook confirmation (`payment.captured`) or verified AFW DirectPay settlement (`verify_sovereign_payment` + `confirm_sovereign_payment_by_owner`) activates tenant entitlements and reconciles cleanly with idempotency, retry queueing, and refund/dispute revocation. |
| **H. Onboarding, Workflow Delivery & Renewal** | `app/services/p2_customer_ops.py` | Mandatory client onboarding inputs, P1 `WorkflowDefinitionRecord` / `WorkflowRunRecord` execution staging drafts without auto-completing, explicit handover confirmation, post-pilot feedback, and non-auto-charging renewal recommendations. |
| **I. Control Centre & 12-Step Acceptance** | `app/services/p2_customer_ops.py`, `app/dashboard/` | Strictly isolates `verified_commercial_metrics` from `simulation_and_test_metrics`, displays live connector capability states, and persists the 12-step real-world verification checklist (`NOT_TESTED` / `SANDBOX_VERIFIED` / `LIVE_VERIFIED`). |

---

## 4. Truthfulness, Epistemic Hygiene & Safety Invariants

1. **Zero Simulated Revenue or Live Sends:** `SIMULATED_SENT` outreach runs never increment `verified_commercial_metrics.outreach_sent`. Checkout links never increment `verified_payments` or `verified_revenue_inr`.
2. **Owner Authority Preserved:** Both outbound sales emails (`external_sales_outreach`) and commercial proposals (`proposal_delivery`) require explicit Owner HITL approval (`POST /v1/approvals/{approval_id}/decision`).
3. **Host Retention:** Preserves Render Blueprint deployment (`render.yaml`), PostgreSQL + Alembic schema history (`h8c3d4e5f6a7`), ECDSA NIST P-256 Trust Chain sealing, and all P0/P1 routes.
