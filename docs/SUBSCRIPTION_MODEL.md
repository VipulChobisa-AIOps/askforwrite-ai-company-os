# Modular Subscription & Credit Architecture

**Source of Truth:** `app/services/catalog.py`, `app/services/billing_ledger.py`  
**Storage Models:** `TenantSubscriptionRecord` (`tenant_subscription_profiles`), `CreditLedgerRecord` (`credit_ledger_records`), `OrganizationRecord` (`organizations`)

---

## 1. Formula

```text
Customer Subscription =
    Base Platform Tier
  + Selected Modules
  + Agent Allowance (+ extra_agents)
  + Usage Credits (+ credit_packs)
  + Integrations (+ integration_addons)
  + Customization (+ customization_level)
```

---

## 2. Canonical Modular SME Tiers (`MODULAR_SME_TIERS`)

| Tier Key | Target SME | Monthly Base (INR / USD) | Included Modules | Agents / Seats | Included Credits (`lead` / `outreach` / `ai_exec`) |
|---|---|---|---|---|---|
| `launch` | Micro-business & solo founders | ₹2,999 / \$39 | `seo` | 2 agents / 2 seats | 50 / 25 / 100 |
| `growth` | Sales/marketing-led SME | ₹7,999 / \$99 | `sales`, `marketing`, `seo` | 5 agents / 5 seats | 250 / 125 / 500 |
| `operations` | Inventory, distribution & field-led SME | ₹8,999 / \$115 | `inventory`, `field_force`, `customer_ops` | 6 agents / 10 seats | 150 / 75 / 600 |
| `business_pro` | Multi-department SME | ₹19,999 / \$249 | All 6 modules | 12 agents / 25 seats | 1,000 / 500 / 2,500 |
| `enterprise` | Regulated & multi-branch enterprise | ₹49,999 / \$599 | All 6 modules | 50 agents / 100 seats | 5,000 / 2,500 / 10,000 |

---

## 3. Add-on Service Modules & Unit Pricing

| Module Key | Name | Monthly Add-on (INR / USD) | Unlocked Agents |
|---|---|---|---|
| `sales` | Sales & CRM Module | ₹2,499 / \$35 | `discovery_sdr_agent`, `sales_closer_agent`, `evidence_research_agent` |
| `marketing` | Marketing & Creative Studio Module | ₹2,999 / \$39 | `pixelbot_marketing_agent` |
| `seo` | SEO, GEO & WordPress Publishing Module | ₹1,999 / \$29 | `seo_geo_copilot_agent` |
| `inventory` | Inventory & Warehouse StockSense Module | ₹3,999 / \$49 | `warehouse_automation` |
| `field_force` | Field Operations & Conveyance Module | ₹3,999 / \$49 | `field_ops_dispatcher_agent` |
| `customer_ops` | Quality Grading, Compliance & Trust Ops Module | ₹3,499 / \$45 | `watchdog_supervisor_agent`, `shift_scheduler_agent` |

Additional composable units in `billing_ledger.py`:
- `EXTRA_AGENT_PRICE`: ₹999 / \$15 per extra agent
- `EXTRA_SEAT_PRICE`: ₹499 / \$8 per extra seat
- `CREDIT_PACK_UNIT`: 100 credits @ ₹1,499 / \$19 (`entry_type = "TOPUP"`)
- `INTEGRATION_ADDON_PRICE`: ₹1,499 / \$19 per custom integration bridge
- `CUSTOMIZATION_LEVELS`: `standard` (₹0 / \$0), `bespoke_workflows` (₹4,999 / \$59), `enterprise_dedicated` (₹14,999 / \$179)

---

## 4. Machine-Readable 15+ Field Package Contract

Served via `GET /v1/revenue/pricing/contracts` (`build_canonical_package_contract`):
`internal_sku`, `billing_type`, `billing_interval` (`monthly` | `annual` | `one_time`), `base_price`, `currency`, `provider_plan_id`, `included_modules`, `entitled_agents`, `agent_execution_limit`, `included_credits`, `credit_costs`, `seat_limit`, `setup_fee`, `support_level`, `customization_allowance`, `renewal_policy`.

`GET /v1/revenue/funnel` resolves active subscriptions and `TenantSubscriptionRecord` rows back to canonical `internal_sku` buckets inside `kpis.mrr_by_internal_sku`.

---

## 5. Atomic Credit Accounting

- `reserve_execution_credits`: Conditional atomic SQL `UPDATE` checks available credits before decrementing/reserving; concurrent attempts cannot double-spend.
- `commit_credit_reservation`: Marks credit consumption committed upon verified execution completion (`COMMIT` ledger row).
- `refund_credit_reservation`: Automatically refunds credits if execution fails or raises `ExecutionBlockedError` (`REFUND` ledger row).
- Subscription lifecycle endpoints: `POST /v1/me/modular-subscription`, `/v1/me/subscription/upgrade`, `/v1/me/subscription/downgrade`, `/v1/me/subscription/cancel`, `/v1/me/subscription/renew`, `/v1/me/credits/purchase`, `GET /v1/me/credits/ledger`.
