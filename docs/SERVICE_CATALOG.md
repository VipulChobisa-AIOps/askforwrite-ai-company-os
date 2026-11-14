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

## 3. Preserved Legacy & Pilot SKUs (`CATALOG`)

| SKU Key | INR Price | USD Price |
|---|---|---|
| `ask4_academic_order` | ₹999 | \$15 |
| `pixel_ai_pack` | ₹1,499 | \$19 |
| `seo_blog_copilot` | ₹1,999 | \$29 |
| `marketing_suite` | ₹2,999 | \$39 |
| `field_force` | ₹3,999 | \$49 |
| `mango_quality_analytics` | ₹3,999 | \$49 |
| `bike_rebalance_analytics` | ₹3,999 | \$49 |
| `managed_seo_content_pilot` | ₹4,999 | \$59 |
| `warehouse_automation` | ₹4,999 | \$59 |
| `trust_engine` | ₹4,999 | \$69 |
| `company_os_starter` | ₹7,999 | \$99 |
| `growth_all_in_one` | ₹9,999 | \$129 |
| `company_os_pro` | ₹19,999 | \$249 |
| `company_os_enterprise` | ₹49,999 | \$499 |
| `all_access` | ₹59,999 | \$599 |

Note: Not every SKU is automatically an auto-renewing SaaS plan. Single engagements (`managed_seo_content_pilot`, `ask4_academic_order`, `pixel_ai_pack`) and one-time payments preserve explicit `billing_type` distinctions in `build_canonical_package_contract()`.
