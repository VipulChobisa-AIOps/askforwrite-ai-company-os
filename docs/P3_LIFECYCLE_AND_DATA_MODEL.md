# P3 Lifecycle & Data Model Reference

**Alembic Revision Head:** `i9d4e5f6a7b8` (depends on `h8c3d4e5f6a7`)  
**Staff Router Prefix:** `/v1/cs/*` (`app/api/v1/customer_success.py`)  
**Tenant Portal Additions:** `/v1/me/*` (`app/api/v1/customer_portal.py`)

---

## 1. Database Schema (`migrations/versions/i9d4e5f6a7b8_add_p3_customer_success_growth_engine_tables.py`)

| Table Name | SQLAlchemy Model (`app/db/models.py`) | Purpose |
|---|---|---|
| `p3_customer_accounts` | `P3CustomerAccountRecord` | Central CS account anchored to `org_id`: primary contact, human owner, assigned AI agents, `lifecycle_state`, business goals, expected outcomes, readiness flag, renewal date, health snapshot, DPDP/GDPR consent & retention policy. |
| `p3_onboarding_workflows` | `P3OnboardingWorkflowRecord` | Configurable onboarding workflow per `(org_id, sku_key)` tracking tasks, owners, deadlines, completion evidence, active blockers, training sign-off, and activation confirmation audit. |
| `p3_service_deliveries` | `P3ServiceDeliveryRecord` | Delivery management connecting purchased SKUs & `WorkflowRunRecord` to approved scope, inputs, evidence, QA checks, `quality_state`, customer acceptance/revision notes, factual `output_metrics_json`, and verified GSC `outcome_metrics_json`. |
| `p3_support_tickets` | `P3SupportTicketRecord` | Org-scoped support tickets with priority, status FSM, internal staff notes vs customer-visible messages, docs-grounded `ai_triage_json`, SLA response/resolution timestamps, escalation tracking, and CSAT (`1-5` + comment). |
| `p3_subscription_events` | `P3SubscriptionEventRecord` | Idempotent 8-state subscription event log separating `RECURRING_SUBSCRIPTION`, `ONE_TIME_PURCHASE`, `MANAGED_SERVICE_PILOT`, `MANUAL_PAYMENT_PROOF`, and `EXPANSION_PURCHASE`, plus `grace_until`, provider confirmation, and Owner HITL refund approval IDs. |
| `p3_growth_opportunities` | `P3GrowthOpportunityRecord` | Catalog-priced upgrade, add-on, extra seats, and referral opportunities linked to evidence signals and gated by `expansion_offer_or_referral` Owner HITL approval. |
| `p3_unit_economics_entries` | `P3UnitEconomicsEntryRecord` | Service & delivery cost ledger labeled `ACTUAL`, `ALLOCATED`, or `ESTIMATED` across `AI_API_USAGE`, `INFRASTRUCTURE_ALLOCATION`, `HUMAN_DELIVERY`, `SUPPORT_COST`, and `ACQUISITION_COST` with token counts. |
| `p3_customer_cost_budgets` | `P3CustomerCostBudgetRecord` | Per-tenant monthly spend cap (`monthly_cost_limit_inr`), alert threshold, `hard_cap_enforced`, and Owner HITL exception override tracking. |
| `p3_improvement_items` | `P3ImprovementItemRecord` | Deduplicated (`cluster_key`) Improvement Loop backlog prioritized by impact, frequency, business value, effort, and risk (`requires_release_approval=True`). |
| `p3_compliance_requests` | `P3ComplianceRequestRecord` | Secret-redacted DPDP/GDPR data portability exports and legal-hold / Owner HITL offboarding & deletion requests. |
| `p3_operational_incidents` | `P3OperationalIncidentRecord` | Workflow timeout / Dead-Letter Queue (DLQ) recovery incidents, concurrency cap alerts, and database backup & restore drill verification records. |
| `p3_acceptance_steps` | `P3AcceptanceStepRecord` | Persistent 12-step P3 real-world acceptance tracker (`NOT_TESTED` -> `SANDBOX_VERIFIED` -> `LIVE_VERIFIED`). |

---

## 2. State Machines & Validations

### A. Customer Lifecycle States (`CUSTOMER_LIFECYCLE_STATES`)
`LEAD`, `ONBOARDING`, `ACTIVATION_PENDING`, `ACTIVE`, `AT_RISK`, `SUSPENDED`, `CHURNED`, `CLOSED`.
- `ACTIVE` is rejected (`HTTP 409`) unless mandatory onboarding tasks, readiness criteria, and blockers pass `confirm-activation`.
- `CLOSED` is terminal (`{}`). Every transition appends an `AuditLog` entry.

### B. Delivery Quality States (`DELIVERY_QUALITY_STATES`)
`NOT_STARTED`, `IN_PROGRESS`, `WAITING_FOR_INPUT`, `WAITING_FOR_APPROVAL`, `QUALITY_REVIEW`, `DELIVERED`, `REVISION_REQUESTED`, `ACCEPTED`, `BLOCKED`.
- `QUALITY_REVIEW -> DELIVERED` requires passing `qa-review` checks without blocking defects.
- Search Console outcomes remain locked (`ATTRIBUTION_REQUIRES_CONNECTED_GSC`) until the tenant verifies/connects `google_search_console` with baseline data.

### C. Support Ticket Statuses & Subscription States
- **Support Tickets:** `OPEN`, `TRIAGED`, `IN_PROGRESS`, `WAITING_FOR_CUSTOMER`, `ESCALATED`, `RESOLVED`, `CLOSED`.
- **Subscriptions (`SUBSCRIPTION_STATES`):** `PENDING`, `TRIALING`, `ACTIVE`, `PAST_DUE`, `PAUSED`, `CANCELLED`, `EXPIRED`, `REFUNDED`.

---

## 3. API Endpoint Reference (`/v1/cs/*` & `/v1/me/*`)

### Staff & Founder Operations (`/v1/cs/*`)
| Group | Endpoints |
|---|---|
| **Control Centre & Customer 360** | `GET /v1/cs/control-centre`, `GET /v1/cs/customers`, `POST /v1/cs/customers/{org_id}/ensure`, `GET /v1/cs/customers/{org_id}`, `POST /v1/cs/customers/{org_id}/lifecycle`, `PATCH /v1/cs/customers/{org_id}/profile` |
| **Onboarding & Readiness** | `GET /v1/cs/customers/{org_id}/onboarding`, `PATCH /v1/cs/customers/{org_id}/onboarding/tasks/{task_key}`, `POST /v1/cs/customers/{org_id}/onboarding/confirm-activation` |
| **Delivery, QA & Health** | `GET /v1/cs/deliveries`, `POST /v1/cs/deliveries`, `POST /v1/cs/deliveries/{delivery_id}/transition`, `POST /v1/cs/deliveries/{delivery_id}/qa-review`, `POST /v1/cs/deliveries/{delivery_id}/metrics`, `GET /v1/cs/customers/{org_id}/health`, `POST /v1/cs/customers/{org_id}/health/alerts` |
| **Support & Improvement Loop** | `GET /v1/cs/support/tickets`, `POST /v1/cs/support/tickets`, `POST /v1/cs/support/tickets/{ticket_id}/transition`, `POST /v1/cs/support/tickets/{ticket_id}/messages`, `POST /v1/cs/support/tickets/{ticket_id}/ai-assist`, `POST /v1/cs/support/tickets/{ticket_id}/csat`, `POST /v1/cs/improvements/synthesize`, `GET /v1/cs/improvements`, `PATCH /v1/cs/improvements/{item_id}` |
| **Subscriptions, Growth & Unit Economics** | `GET /v1/cs/subscriptions/reliability`, `POST /v1/cs/subscriptions/{org_id}/events`, `POST /v1/cs/subscriptions/{org_id}/payment-failure`, `POST /v1/cs/subscriptions/enforce-grace`, `POST /v1/cs/subscriptions/{org_id}/restore`, `POST /v1/cs/subscriptions/{org_id}/refund`, `POST /v1/cs/subscriptions/{org_id}/plan-change`, `POST /v1/cs/growth/{org_id}/evaluate`, `GET /v1/cs/growth`, `POST /v1/cs/growth/opportunities/{opp_id}/share`, `PUT /v1/cs/unit-economics/{org_id}/budget`, `POST /v1/cs/unit-economics/{org_id}/costs`, `GET /v1/cs/unit-economics/{org_id}` |
| **Compliance, Ops Readiness & Acceptance** | `PATCH /v1/cs/compliance/{org_id}/consent-retention`, `POST /v1/cs/compliance/{org_id}/export`, `POST /v1/cs/compliance/{org_id}/offboard-delete`, `GET /v1/cs/ops/readiness`, `POST /v1/cs/ops/workflows/scan-timeouts`, `POST /v1/cs/ops/dlq/{incident_id}/retry`, `POST /v1/cs/ops/backup-drill`, `GET /v1/cs/acceptance`, `POST /v1/cs/acceptance/{step_number}` |

### Customer Self-Service Portal (`/v1/me/*`, JWT Tenant-Scoped)
- `GET /v1/me/onboarding`, `PATCH /v1/me/onboarding/tasks/{task_key}`
- `GET /v1/me/deliveries`, `POST /v1/me/deliveries/{delivery_id}/respond`
- `GET /v1/me/support/tickets`, `POST /v1/me/support/tickets`, `POST /v1/me/support/tickets/{ticket_id}/messages`, `POST /v1/me/support/tickets/{ticket_id}/csat`
- `GET /v1/me/data-export`, `PATCH /v1/me/consent-preferences`
