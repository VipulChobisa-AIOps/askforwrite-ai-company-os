# SME Customer Onboarding Guide

This walkthrough describes the complete P1 SME journey through the **Business Control Center** (`/app` or API `/v1/me/*`, `/v1/registry/*`, `/v1/workflows/*`).

---

## Step 1: Register / Sign In & Create 13-Field Business Profile

- Register via `POST /v1/auth/register` (`role: "customer"`), receiving a tenant-scoped JWT and `org_id`.
- Open **Business Profile** in the Control Center and submit all 13 structured fields via `POST /v1/me/business-profile`:
  1. `business_name` & `industry`
  2. `description`
  3. `location`
  4. `website` & `contact_info`
  5. `company_size` & `employee_count`
  6. `products_and_services`
  7. `customer_segments`
  8. `sales_channels`
  9. `current_software`
  10. `operational_pain_points`
  11. `business_objectives`
  12. `required_automations`
  13. `expected_monthly_volume` (+ optional `currency`)

The Requirement Engine creates persisted `StructuredRequirementRecord` rows and returns an explainable recommendation (`recommendation.recommended_tier`, `recommended_modules`, `recommended_agents`, `required_connectors`, `suggested_workflows`, `estimated_monthly_credits`, `limitations`, and per-module `explanations`).

---

## Step 2: Explicit Selection & Confirmation Gate

Recommendations do **not** auto-activate or auto-bill (`profile.selection_confirmed == false`, `recommendation.requires_explicit_confirmation == true`).
Confirm explicitly via `POST /v1/me/business-profile/confirm` (choosing `base_plan_key`, `selected_modules`, and `activate_selection: true/false`), or compose custom capacity via `POST /v1/me/modular-subscription`.

---

## Step 3: Activate Agents & Connect Tools

1. Open **AI Workforce** -> activate entitled agents (`POST /v1/registry/agents/{agent_id}/activate`) and optionally restrict allowed tools (`PATCH /v1/registry/agents/{agent_id}/configure`).
2. Open **Connected Tools** -> inspect capability states (`SIMULATED`, `LOCAL_ENGINE_VERIFIED`, `SANDBOX_VERIFIED`, `LIVE_VERIFIED`, `HUMAN_ASSISTED`, `BLOCKED`) and run `POST /v1/registry/connectors/{connector_id}/verify`.

---

## Step 4: Execute Tasks & Coordinate Multi-Step Workflows

- **Single Agent Run:** Use **Agent Run Console** (`POST /v1/registry/agents/{agent_id}/execute`), selecting `SIMULATION` (Dry Run) or permitted `SANDBOX`/`PRODUCTION` mode.
- **Multi-Step Workflow:** Use **Workflow Builder** (`POST /v1/workflows/definitions`, `POST /v1/workflows/runs`, `/ready`, `/start`). Any `approval_gate` step pauses in `WAITING_APPROVAL` and writes a tenant-scoped `ApprovalRequest` until approved/rejected in **Approvals** (`/v1/me/approvals/{id}/decide`) and resumed via `/v1/workflows/runs/{run_id}/resume`.

---

## Step 5: Audit Execution Evidence & Usage Ledger

- Inspect every execution in **Tasks & Execution History** (`/v1/me/evidence`, `/v1/registry/evidence/{execution_id}`) with explicit output origin pills (`LIVE_PROVIDER_VERIFIED`, `LOCAL_DETERMINISTIC`, `SANDBOX_VERIFIED`, `HUMAN_ASSISTED`, `SIMULATED_SYNTHETIC`, `BLOCKED`).
- Inspect real-time balances and transactions in **Subscription & Billing** (`/v1/me/billing`, `/v1/me/credits/ledger`).
