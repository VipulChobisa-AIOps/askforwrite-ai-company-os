# Service Catalog Documentation

**Sources of Truth:** `app/services/registry.py` (`SERVICE_CATEGORIES`, `SERVICE_REGISTRY`) & `app/services/catalog.py` (`CATALOG`, `MODULAR_SME_TIERS`, `MODULAR_SERVICE_MODULES`)

Do **not** maintain separate hardcoded frontend service lists. Both backend execution and `/app` dashboard rendering (`cwHydrateRegistry`) consume `/v1/registry/services`, `/v1/registry/agents`, and `/v1/registry/connectors`.

---

## 1. Service Categories (9 Categories)

1. `lead_discovery` — Sales & CRM Lead Discovery
2. `research_intelligence` — Business Intelligence & Research
3. `sales_proposals` — Sales & Proposals
4. `seo_content` — SEO & Content Publishing
5. `marketing_campaigns` — Marketing & Social Media
6. `customer_support` — Customer Management & Support
7. `field_operations` — Field Force & Operations
8. `inventory_quality` — Inventory, Warehouse & Specialized Analytics
9. `governance_trust` — Trust & Governance

---

## 2. Unified Service Registry (16 Services)

| `service_id` | Category | Entitlement Key | Default Status | Mapped Agents | Required Connectors |
|---|---|---|---|---|---|
| `lead_discovery` | `lead_discovery` | `lead_discovery` | `SIMULATED` | `discovery_sdr_agent`, `ceo_manager_agent` | `serper_search`, `google_places`, `project_api` |
| `evidence_research` | `research_intelligence` | `evidence_research` | `LOCAL_ENGINE_VERIFIED` | `research_analyst_agent` | `serper_search`, `gemini_api`, `project_api` |
| `ask4_academic_order` | `research_intelligence` | `ask4_academic_order` | `LOCAL_ENGINE_VERIFIED` | `academic_research_agent` | `gemini_api`, `project_api` |
| `sales_capture` | `sales_proposals` | `sales_capture` | `HUMAN_ASSISTED` | `sales_proposal_agent` | `hostinger_smtp`, `razorpay`, `afw_directpay` |
| `managed_seo_content_pilot` | `seo_content` | `managed_seo_content_pilot` | `LOCAL_ENGINE_VERIFIED` | `seo_content_agent` | `gemini_api`, `wordpress_rest` |
| `seo_blog_copilot` | `seo_content` | `seo_blog_copilot` | `LOCAL_ENGINE_VERIFIED` | `seo_content_agent` | `gemini_api`, `wordpress_rest` |
| `wordpress_publisher` | `seo_content` | `wordpress_publisher` | `SIMULATED` | `seo_content_agent` | `wordpress_rest` |
| `marketing_suite` | `marketing_campaigns` | `marketing_suite` | `LOCAL_ENGINE_VERIFIED` | `marketing_creative_agent` | `social_media_bridge`, `gemini_api` |
| `pixel_ai_pack` | `marketing_campaigns` | `pixel_ai_pack` | `LOCAL_ENGINE_VERIFIED` | `marketing_creative_agent` | `gemini_api`, `social_media_bridge` |
| `growth_all_in_one` | `marketing_campaigns` | `growth_all_in_one` | `LOCAL_ENGINE_VERIFIED` | `ceo_manager_agent`, `marketing_creative_agent`, `seo_content_agent` | `gemini_api`, `wordpress_rest`, `social_media_bridge` |
| `support_followup` | `customer_support` | `support_followup` | `HUMAN_ASSISTED` | `support_followup_agent` | `whatsapp_bridge`, `hostinger_smtp`, `project_api` |
| `field_force` | `field_operations` | `field_force` | `LOCAL_ENGINE_VERIFIED` | `field_ops_agent` | `project_api`, `whatsapp_bridge` |
| `warehouse_automation` | `inventory_quality` | `warehouse_automation` | `LOCAL_ENGINE_VERIFIED` | `warehouse_stocksense_agent` | `project_api` |
| `mango_quality_analytics` | `inventory_quality` | `mango_quality_analytics` | `LOCAL_ENGINE_VERIFIED` | `quality_vision_agent` | `project_api` |
| `bike_rebalance_analytics` | `inventory_quality` | `bike_rebalance_analytics` | `LOCAL_ENGINE_VERIFIED` | `mobility_rebalance_agent` | `project_api` |
| `trust_engine` | `governance_trust` | `trust_engine` | `LOCAL_ENGINE_VERIFIED` | `trust_governance_agent` | `project_api` |

---

## 3. Canonical Commercial Catalog SKUs (`app/services/catalog.py`)

All landing pages, checkout sessions, invoices, provisioning, and entitlements consume **`app/services/catalog.py`** as the single source of truth. One-time purchases and the 14-day pilot are strictly separated from auto-renewing monthly subscriptions via `billing_type` in `build_canonical_package_contract()`.

### 3.1 One-Time Purchases & Managed Pilot (Non-Renewing)

| SKU Key | Product Name | Billing Type | INR Price | USD Price |
|---|---|---|---|---|
| `ask4_academic_order` | ASK4 Academic Research & Order Fulfillment (Single) | `one_time_purchase` | ₹999 | \$15 |
| `pixel_ai_pack` | Pixel AI Visual Creative Pack (20 Visuals) | `one_time_purchase` | ₹1,499 | \$19 |
| `managed_seo_content_pilot` | Managed SEO & Content Pilot (14-Day) | `managed_pilot_14d` | ₹4,999 | \$59 |

### 3.2 Modular Specialist Tools (Monthly Subscriptions)

| SKU Key | Product Name | Cluster | Billing Type | INR / mo | USD / mo |
|---|---|---|---|---|---|
| `seo_blog_copilot` | AskforWrite SEO Blog Copilot | Cluster 1 (Content & Creative) | `recurring_subscription` | ₹1,999 | \$29 |
| `marketing_suite` | PixelBot Omnichannel Marketing Suite | Cluster 1 (Content & Creative) | `recurring_subscription` | ₹2,499 | \$35 |
| `field_force` | Field Operations Automation Suite | Cluster 3 (Operations & Vertical AI) | `recurring_subscription` | ₹3,999 | \$49 |
| `mango_quality_analytics` | AgriTech Produce Vision & Quality Grading AI | Cluster 3 (Operations & Vertical AI) | `recurring_subscription` | ₹3,999 | \$49 |
| `bike_rebalance_analytics` | Urban Mobility & Spatio-Temporal Logistics AI | Cluster 3 (Operations & Vertical AI) | `recurring_subscription` | ₹3,999 | \$49 |
| `warehouse_automation` | StockSense Warehouse & Inventory AI | Cluster 3 (Operations & Vertical AI) | `recurring_subscription` | ₹3,999 | \$49 |
| `trust_engine` | AFW 2030 Cryptographic Trust Engine | Cluster 4 (Governance & Trust) | `recurring_subscription` | ₹3,999 | \$49 |

### 3.3 Clustered Monthly Subscription Tiers (`MODULAR_SME_TIERS` & Master Bundles — 20% Off Annual)

| Tier Alias | Canonical SKU Key | Included Clusters | Monthly (INR / USD) | Annual Equiv. (-20%) | Lead / Outreach Credits (mo) |
|---|---|---|---|---|---|
| `launch` / `starter` | `company_os_starter` | Cluster 1 (Content, SEO & Creative) | ₹2,999 / \$39 | ₹2,399 / \$31 | 50 / 25 |
| `growth` | `growth_all_in_one` | Cluster 1 + Cluster 2 (Sales & AI Closer) | ₹6,999 / \$89 | ₹5,599 / \$71 | 300 / 150 |
| `operations` | `operations_suite` | Cluster 3 (Field/Warehouse/CV/Mobility) + Cluster 4 (Trust) | ₹9,999 / \$129 | ₹7,999 / \$103 | 200 / 100 |
| `business_pro` / `pro` | `company_os_pro` | All 4 Clusters (Full Company OS) | ₹17,999 / \$229 | ₹14,399 / \$183 | 1,200 / 600 |
| `enterprise` | `company_os_enterprise` | All 4 Clusters + Dedicated Sovereign Scale | ₹44,999 / \$549 | ₹35,999 / \$439 | 5,000 / 2,500 |
| `all_access` | `all_access` | Unrestricted Master Suite (All Modules) | ₹44,999 / \$549 | — | 10,000 / 5,000 |

Note: Not every SKU is an auto-renewing SaaS plan. Single engagements (`managed_seo_content_pilot`, `ask4_academic_order`, `pixel_ai_pack`) preserve explicit non-renewing `billing_type` contracts in `build_canonical_package_contract()`. Payment webhooks fail closed if package metadata is missing or unrecognized — provisioning never silently falls back to `company_os_starter`.
