# API Reference (P1 Workforce, Workflows, Customer Control Center & Governance)

All authenticated endpoints accept `Authorization: Bearer <jwt>` (or `X-API-Key` for owner/manager automation) and support `X-Correlation-ID` propagation. Interactive OpenAPI documentation is served at `/docs` and `/openapi.json`.

---

## 1. Unified Registry, Agents, Connectors & Evidence (`/v1/registry`)

| Method & Path | Auth / Scope | Purpose |
|---|---|---|
| `GET /v1/registry/services` | Optional principal (org overlay if authed) | Discover all 16 services across 9 categories |
| `GET /v1/registry/services/{service_id}` | Optional principal | Retrieve single service contract |
| `GET /v1/registry/agents` | Optional principal (org activation overlay) | List all 13 specialist agents |
| `GET /v1/registry/agents/{agent_id}` | Optional principal | Inspect agent schema, tools, limits, approvals |
| `POST /v1/registry/agents/{agent_id}/activate` | `require_tenant_operator` | Activate agent for tenant after subscription entitlement & limit check |
| `POST /v1/registry/agents/{agent_id}/deactivate` | `require_tenant_operator` | Deactivate agent for tenant |
| `PATCH /v1/registry/agents/{agent_id}/configure` | `require_tenant_operator` | Update model override, mode, custom instructions, intersected tool allowlist |
| `POST /v1/registry/agents/{agent_id}/execute` | `require_tenant_operator` | Execute agent (`SIMULATION`/`SANDBOX`/`PRODUCTION`), atomic credit reserve/commit/refund, evidence write |
| `GET /v1/registry/agents/{agent_id}/history` | `require_tenant_operator` | Tenant-scoped execution history for an agent |
| `GET /v1/registry/connectors` | Optional principal | List all 11 connectors and capability states |
| `POST /v1/registry/connectors/{connector_id}/configure` | `require_tenant_operator` | Save sanitized connector settings (raw secrets masked/redacted) |
| `POST /v1/registry/connectors/{connector_id}/verify` | `require_tenant_operator` | Validate credentials, permissions, and record verification timestamp/errors |
| `GET /v1/registry/evidence` | `get_current_principal` (org-filtered) | Query durable execution evidence records |
| `GET /v1/registry/evidence/{execution_id}` | `get_current_principal` (strict org guard) | Fetch full redacted execution evidence by ID |

---

## 2. Multi-Step Workflow Engine (`/v1/workflows`)

Explicit 8-state FSM: `DRAFT`, `READY`, `RUNNING`, `WAITING_APPROVAL`, `COMPLETED`, `FAILED`, `CANCELLED`, `BLOCKED`.

| Method & Path | Auth / Scope | Purpose |
|---|---|---|
| `POST /v1/workflows/definitions` | `require_tenant_operator` | Create versioned multi-step workflow (`steps_json`, budget, timeout, retries) |
| `GET /v1/workflows/definitions` | `get_current_principal` (org-scoped) | List tenant workflow definitions |
| `POST /v1/workflows/runs` | `get_current_principal` | Instantiate workflow run in `DRAFT` (or validate into `READY`) |
| `GET /v1/workflows/runs` | `get_current_principal` (org-scoped) | List tenant workflow runs |
| `GET /v1/workflows/runs/{run_id}` | `get_current_principal` (org-scoped) | Inspect step results, credits consumed, approval link |
| `POST /v1/workflows/runs/{run_id}/ready` | `get_current_principal` (org-scoped) | Transition `DRAFT` -> `READY` |
| `POST /v1/workflows/runs/{run_id}/start` | `get_current_principal` (org-scoped) | Execute steps sequentially until `WAITING_APPROVAL`, `COMPLETED`, `FAILED`, or `BLOCKED` |
| `POST /v1/workflows/runs/{run_id}/resume` | `get_current_principal` (org-scoped) | Resume `WAITING_APPROVAL` after HITL decision (`APPROVED` / `REJECTED`) |
| `POST /v1/workflows/runs/{run_id}/cancel` | `get_current_principal` (org-scoped) | Transition active/paused run to `CANCELLED` |

---

## 3. Customer Business Control Center (`/v1/me`)

| Method & Path | Auth | Purpose |
|---|---|---|
| `POST /v1/me/business-profile` | Customer JWT | Save 13-field SME profile & generate structured requirements + explainable recommendations |
| `GET /v1/me/business-profile` | Customer JWT | Read tenant business profile, requirements, recommendation, and subscription state |
| `POST /v1/me/business-profile/confirm` | Customer JWT | Explicit customer confirmation gate before activating/billing selection |
| `POST /v1/me/modular-subscription` | Customer JWT | Configure Base Tier + Modules + Extra Agents/Seats + Credit Packs + Customization |
| `GET /v1/me/subscription` | Customer JWT | Current modular subscription contract |
| `POST /v1/me/subscription/upgrade` | Customer JWT | Upgrade tier/modules cleanly |
| `POST /v1/me/subscription/downgrade` | Customer JWT | Downgrade tier/modules cleanly |
| `POST /v1/me/subscription/cancel` | Customer JWT | Cancel immediately or at period end |
| `POST /v1/me/subscription/renew` | Customer JWT | Renew period and reset monthly credit allocation |
| `POST /v1/me/credits/purchase` | Customer JWT | Purchase extra credit packs (`entry_type="TOPUP"`) |
| `GET /v1/me/credits/ledger` | Customer JWT | View atomic credit ledger (`GRANT`, `RESERVE`, `COMMIT`, `REFUND`, `TOPUP`) |
| `GET /v1/me/evidence` | Customer JWT | View tenant execution evidence records |
| `GET /v1/me/analytics` | Customer JWT | View tenant execution counts, origin breakdown, and credit spend |
| `GET /v1/me/billing` | Customer JWT | Combined subscription, ledger, and invoice summary |
| `GET /v1/me/approvals` | Customer JWT | List pending/historical HITL approvals scoped to tenant |
| `POST /v1/me/approvals/{approval_id}/decide` | Customer JWT | Approve or reject tenant HITL gate (`decision`, `reason`/`decision_note`) |
| `POST /v1/me/agents/{agent_key}/control` | Customer JWT | Activate/pause/resume/emergency-stop tenant agent |
| `POST /v1/me/emergency-stop` | Customer JWT | Trigger tenant-scoped emergency stop |
| `GET /v1/me/emergency-stops` | Customer JWT | List active emergency stops for tenant |
| `POST /v1/me/gemini-key` | Customer JWT | Store BYOK Gemini API key securely for tenant |
| `GET /v1/me/capabilities` / `GET /v1/me/usage` / `POST /v1/me/use-service` | Customer JWT | Preserved P0 capability catalog, usage meters, and legacy capability launcher |

---

## 4. Platform Revenue, Watchdog & Webhooks

- `GET /v1/revenue/pricing/contracts` — Public canonical 15+ field pricing contracts (`package_contracts` + `modular_tier_contracts`)
- `GET /v1/revenue/funnel` — Owner-scoped KPIs including `kpis.mrr_by_internal_sku`
- `POST /v1/watchdog/emergency-stop` / `GET /v1/watchdog/emergency-stops` — Platform/agent/tenant/execution circuit breakers
- `POST /v1/watchdog/credibility-audit`, `POST /v1/watchdog/sme-assess`, `POST /v1/watchdog/sme-sandbox-scenario`, `GET /v1/watchdog/connectors`
- `POST /v1/webhooks/payment`, `GET /v1/webhooks/events`, `GET /health`
