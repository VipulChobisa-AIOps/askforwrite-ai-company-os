# P3 Customer Success Architecture — Retention, Delivery Quality & Repeatable Growth Engine

## 1. Mission & Commercial Lifecycle

P3 extends AskforWrite AI Company OS from first-customer acquisition (P2) into a unified post-sale operating engine capable of consistently onboarding, activating, delivering value for, supporting, retaining, and expanding multiple paying customers — starting with **small and medium-sized digital marketing and SEO agencies in India**.

```
Acquire -> Onboard -> Activate -> Deliver -> Measure Results ->
Support -> Retain -> Renew -> Expand -> Refer
```

Every customer capability reuses existing P0/P1/P2 foundations (`OrganizationRecord`, `TenantSubscriptionRecord`, `CatalogPackage`, `ApprovalRequest`, `AuditLog`, `ExecutionEvidenceRecord`, `WorkflowDefinitionRecord`, `WorkflowRunRecord`, `ConnectorStateRecord`, `p2_payment_reconciliation_queue`, `p2_customer_engagements`) under single-host Render configuration.

---

## 2. Architecture Layers & Service Modules

| Domain Layer | Module File(s) | Key Responsibilities |
|---|---|---|
| **A. Customer Success Management** | `app/services/p3_customer_success.py` | Central `P3CustomerAccountRecord` linked to `OrganizationRecord`, Customer 360 profile aggregator, validated & `AuditLog`-tracked 8-state lifecycle machine (`LEAD` -> `ONBOARDING` -> `ACTIVATION_PENDING` -> `ACTIVE` -> `AT_RISK` -> `SUSPENDED` -> `CHURNED` -> `CLOSED`). |
| **B. Onboarding & Activation Readiness** | `app/services/p3_customer_success.py`, `app/services/provisioning.py` | Configurable SKU templates (`india_seo_agency_pilot`, `india_seo_agency_recurring`, `seo_blog_copilot`) with owner roles, deadlines, blockers, completion evidence, and a strict readiness gate preventing premature `ACTIVE` state. Provisioning atomically creates `ONBOARDING` CS accounts on confirmed payment. |
| **C. Delivery Quality & Outcome Attribution** | `app/services/p3_delivery_health.py` | 9-state delivery quality machine (`NOT_STARTED` .. `ACCEPTED` / `BLOCKED`), structured QA checklist verification (`QUALITY_REVIEW` gate), and strict separation between factual deliverables produced vs external Search Console outcomes (`ATTRIBUTION_REQUIRES_CONNECTED_GSC`). |
| **D. Customer Health & Internal Early Warning** | `app/services/p3_delivery_health.py` | Multi-dimension explainable health scoring (`HEALTHY`, `NEEDS_ATTENTION`, `AT_RISK`, `INSUFFICIENT_DATA` when `<3` evidence dimensions exist) and internal-only `SupervisorAlertRecord` churn/blocker alerts. |
| **E. Org-Scoped Support, HITL & Improvement Loop** | `app/services/p3_support_improvements.py` | Customer portal `/v1/me/support/tickets` + staff `/v1/cs/support/tickets` with strict cross-tenant isolation, docs-grounded AI Support Assistant, mandatory Owner HITL gate (`support_sensitive_external_reply`) on refunds/pricing/legal/access replies, CSAT, and prioritized Improvement Loop (`p3_improvement_items`). |
| **F. Subscription Reliability, Growth HITL & Unit Economics** | `app/services/p3_revenue_growth.py`, `app/api/v1/webhooks.py` | Idempotent 8-state subscription ledger distinguishing `RECURRING_SUBSCRIPTION`, `ONE_TIME_PURCHASE`, `MANAGED_SERVICE_PILOT`, `MANUAL_PAYMENT_PROOF`, and `EXPANSION_PURCHASE`; grace/suspension/recovery flow; HITL-gated refunds (`subscription_pricing_or_refund_action`); catalog-grounded upsell/referrals (`expansion_offer_or_referral`); `ACTUAL`/`ALLOCATED`/`ESTIMATED` cost ledger & monthly spend hard cap (`HTTP 402`). |
| **G. Multi-Tenant Ops, Compliance, Control Centre & Acceptance** | `app/services/p3_ops_compliance_cc.py`, `app/services/workflow_engine.py` | Per-org concurrent workflow ceiling (`P3_MAX_CONCURRENT_RUNS_PER_ORG = 5`), stale run timeout recovery & DLQ retry (`p3_operational_incidents`), live DB latency probe, backup verification drills, secret-redacted DPDP/GDPR portability export, legal-hold & HITL deletion (`customer_offboarding_and_deletion`), isolated Founder Control Centre KPIs, and 12-step P3 Acceptance Checklist. |

---

## 3. Specialized P3 AI Workforce (8 Agents -> 28 Total)

All 8 P3 agents are registered in `app/services/registry.py` (`AGENT_REGISTRY`), enforce tenant entitlement & atomic credit reservation, and log 18-field `ExecutionEvidenceRecord` trails:

1. `cs_onboarding_specialist_agent` — Guides onboarding workflows, surfaces blockers, cannot bypass readiness gate.
2. `cs_manager_agent` — Evaluates Customer Health and dispatches internal churn/blocker alerts only.
3. `service_delivery_coordinator_agent` — Coordinates deliverables and tracks factual vs connected Search Console metrics without fabricating causation.
4. `qa_review_agent` — Executes QA verification checks; cannot rubber-stamp missing artifacts or evidence.
5. `cs_support_specialist_agent` — Triages support tickets against `docs/*.md` and flags sensitive external replies for Owner HITL approval.
6. `renewal_management_agent` — Tracks upcoming renewals and enforces grace-period expirations (`subscription_pricing_or_refund_action` HITL gate on billing/refund changes).
7. `expansion_opportunity_agent` — Identifies catalog-verified upgrades and stages Owner HITL approval (`expansion_offer_or_referral`) before sharing externally.
8. `customer_insights_analyst_agent` — Clusters recurring tickets, revision causes, low CSAT, and onboarding blockers into prioritized `p3_improvement_items` (read & recommend only).

---

## 4. Non-Negotiable Epistemic & Governance Safeguards

1. **Strict Sandbox & Synthetic Data Exclusion:** Control Centre `verified_customer_ops` excludes `is_sandbox` / synthetic test organizations and simulated executions into a separate `simulation_and_test_metrics` block (`EXCLUDED_FROM_LIVE_BUSINESS_KPIS`).
2. **Manual Payment Proof Separation:** Submitting an AFW DirectPay proof (`MANUAL_PAYMENT_PROOF` / `is_provider_confirmed=False`) never sets `recurring_mrr_inr` or marks a subscription as provider-confirmed recurring billing.
3. **No Auto-Executed High-Risk Actions:** Sensitive support replies, refunds/pricing changes, external expansion/referral offers, exceptional budget overrides, and customer offboarding/deletion all create immutable `ApprovalRequest` items and block execution until Owner HITL decision (`APPROVED`).
4. **Honest `INSUFFICIENT_DATA` Defaults:** When `<3` health evidence dimensions exist, when historical CAC lacks `ACTUAL` entries or `<2` verified billing periods for LTV, or when Search Console isn't verified & connected, metrics explicitly return `"INSUFFICIENT_DATA"` or `"ATTRIBUTION_REQUIRES_CONNECTED_GSC"`.
