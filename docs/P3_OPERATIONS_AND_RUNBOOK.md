# P3 Operations & Founder Runbook

This runbook guides daily Customer Success, delivery quality assurance, support triage, billing reliability, unit economics, and compliance operations in `/app` under **P3 Customer Success & Growth**.

---

## 1. Customer Onboarding & Readiness Gate

1. **Automatic Post-Payment Setup:** When payment verification succeeds in `app/services/provisioning.py`, `ensure_customer_account(..., initial_state="ONBOARDING")` creates/links `P3CustomerAccountRecord` atomically within the provisioning transaction.
2. **Configurable Templates (`ONBOARDING_TEMPLATES`):**
   - `india_seo_agency_pilot` (`managed_seo_content_pilot`)
   - `india_seo_agency_recurring` (`launch`, `growth`, `pro`, `enterprise`, `growth_all_in_one`, `company_os_starter`, `company_os_pro`, `company_os_enterprise`)
   - `seo_blog_copilot`
3. **Strict Activation Rule:** Do NOT mark a customer `ACTIVE` upon registration or payment alone. Every mandatory task (`required_for_activation=True`), connector verification, and training item must be completed with zero unresolved blockers before `POST /v1/cs/customers/{org_id}/onboarding/confirm-activation` transitions the account to `ACTIVE`.

---

## 2. Service Delivery, QA Gate & Honest SEO Outcome Attribution

1. Create a delivery engagement record (`POST /v1/cs/deliveries`) recording original customer requirement, approved scope, owner, assigned agent, and linked `workflow_run_id`.
2. Run QA verification (`POST /v1/cs/deliveries/{delivery_id}/qa-review`) during `QUALITY_REVIEW` before transitioning to `DELIVERED`. Any defect or failed check routes cleanly to `REVISION_REQUESTED`.
3. **Outcome Attribution Guard:** When recording metrics (`POST /v1/cs/deliveries/{delivery_id}/metrics`):
   - Factual production metrics (articles produced, staging URLs, technical issues addressed) are stored under `output_metrics_json`.
   - External search outcomes (Search Console impressions, clicks, rankings) remain blocked/flagged `ATTRIBUTION_REQUIRES_CONNECTED_GSC` unless `google_search_console` is verified/connected with baseline telemetry.
4. Customers respond via self-service `POST /v1/me/deliveries/{delivery_id}/respond` (`ACCEPTED` or `REVISION_REQUESTED`).

---

## 3. Customer Health Engine & Early-Warning Alerts

- Evaluate health via `GET /v1/cs/customers/{org_id}/health`:
  - Returns `INSUFFICIENT_DATA` whenever `<3` verifiable evidence dimensions exist rather than inventing a score.
  - Otherwise scores `HEALTHY`, `NEEDS_ATTENTION`, or `AT_RISK` with explicit dimension weights, timestamps, and `data_freshness`.
- Generate internal early-warning alerts (`POST /v1/cs/customers/{org_id}/health/alerts`) into `SupervisorAlertRecord`. Alerts stay **internal only** and never auto-email customers.

---

## 4. Org-Scoped Support, HITL Guard & Improvement Loop

1. Customers manage their own workspace tickets via `/v1/me/support/tickets` and submit CSAT (`1-5`) via `/v1/me/support/tickets/{id}/csat`. Cross-tenant access returns `HTTP 403`.
2. Run docs-grounded AI triage via `POST /v1/cs/support/tickets/{id}/ai-assist` (`_retrieve_authorized_docs` scanning `docs/*.md`).
3. **Sensitive Reply HITL Gate (`support_sensitive_external_reply`):** Customer-visible staff replies containing refunds, discounts, guarantees, legal clauses, or access resets queue a `PENDING` `ApprovalRequest` (`status="APPROVAL_REQUIRED"`, `customer_message_sent=False`) until Owner approval is recorded.
4. Run `POST /v1/cs/improvements/synthesize` to deduplicate recurring support issues, revision causes, low CSAT, and onboarding blockers into `p3_improvement_items` (`requires_release_approval=True`).

---

## 5. Subscription Reliability, Refunds, Expansion & Unit Economics

- **Manual Proofs Never Become MRR:** `MANUAL_PAYMENT_PROOF` (`is_provider_confirmed=False`) and `ONE_TIME_PURCHASE` / `MANAGED_SERVICE_PILOT` events never count toward `verified_recurring_mrr_inr`.
- **Grace Period & Suspension:** `POST /v1/cs/subscriptions/{org_id}/payment-failure` starts a `PAST_DUE` grace window; `POST /v1/cs/subscriptions/enforce-grace` suspends expired tenants to `tier="free"` and transitions the CS account to `SUSPENDED` until `POST /v1/cs/subscriptions/{org_id}/restore` recovers verified payment.
- **Refunds & Growth HITL:** Refunds (`subscription_pricing_or_refund_action`) and sharing catalog-priced upsells/referrals (`expansion_offer_or_referral`) always pause for Owner `ApprovalRequest` decision.
- **Unit Economics & Cost Caps:** Every recorded cost carries a mandatory quality label (`ACTUAL`, `ALLOCATED`, or `ESTIMATED`). Exceeding `monthly_cost_limit_inr` when `hard_cap_enforced=True` returns `HTTP 402 Payment Required` unless an Owner-approved exception override is attached. Historical CAC/LTV reports `INSUFFICIENT_DATA` without `ACTUAL` acquisition costs and `>=2` verified billing periods.

---

## 6. Privacy Compliance (DPDP / GDPR) & Ops Readiness

- **Data Portability Export:** `POST /v1/cs/compliance/{org_id}/export` and tenant self-service `GET /v1/me/data-export` redact `password_hash`, API keys, tokens, connector secrets, and internal staff notes.
- **Offboarding & Deletion:** `POST /v1/cs/compliance/{org_id}/offboard-delete` is blocked whenever `retention_policy_json.legal_hold=True`, and otherwise requires an approved `customer_offboarding_and_deletion` Owner `ApprovalRequest` before deactivating the tenant (`OrganizationRecord.is_active=False`).
- **DLQ & Backup Drills:** Run `POST /v1/cs/ops/workflows/scan-timeouts` to move stale `RUNNING` workflows to `FAILED` + `p3_operational_incidents`, retry with `POST /v1/cs/ops/dlq/{incident_id}/retry`, and record verified restore evidence via `POST /v1/cs/ops/backup-drill`.
