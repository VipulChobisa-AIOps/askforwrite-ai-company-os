# Capability Truthfulness Matrix

**Status Vocabulary (`app/services/connectors.py`):**  
`LIVE_VERIFIED` · `LOCAL_ENGINE_VERIFIED` · `SANDBOX_VERIFIED` · `HUMAN_ASSISTED` · `SIMULATED` · `BLOCKED` · `ROADMAP`

**Output Provenance (`app/services/evidence.py`):**  
`LIVE_PROVIDER_VERIFIED` · `LOCAL_DETERMINISTIC` · `SANDBOX_VERIFIED` · `HUMAN_ASSISTED` · `SIMULATED_SYNTHETIC` · `BLOCKED`

> A configured key or passing unit test does **not** upgrade an integration to `LIVE_VERIFIED`. Only verified external provider execution in a non-simulated environment earns `LIVE_VERIFIED`.

---

## 1. Registered Services (16)

| Service ID | Category | Current Registry State | Provenance / Condition |
|---|---|---|---|
| `evidence_research` | `research_intelligence` | `LOCAL_ENGINE_VERIFIED` | Local synthesis + optional live search/Gemini enrichment |
| `ask4_academic_order` | `research_intelligence` | `LOCAL_ENGINE_VERIFIED` | Local academic synthesis & BibTeX engine |
| `managed_seo_content_pilot` | `seo_content` | `LOCAL_ENGINE_VERIFIED` | Local generation + HITL review (`wordpress_rest` needed for live publish) |
| `seo_blog_copilot` | `seo_content` | `LOCAL_ENGINE_VERIFIED` | Local SEO/GEO draft & schema generator |
| `marketing_suite` | `marketing_campaigns` | `LOCAL_ENGINE_VERIFIED` | Local multi-channel campaign copy & script engine |
| `pixel_ai_pack` | `marketing_campaigns` | `LOCAL_ENGINE_VERIFIED` | Structured visual prompt/spec pack (image diffusion key optional) |
| `growth_all_in_one` | `marketing_campaigns` | `LOCAL_ENGINE_VERIFIED` | Bundled SEO + Marketing execution engine |
| `field_force` | `field_operations` | `LOCAL_ENGINE_VERIFIED` | Anti-spoof telemetry, route optimization & conveyance ledger |
| `warehouse_automation` | `inventory_quality` | `LOCAL_ENGINE_VERIFIED` | Pareto ABC, EOQ/ROP & dead-stock deterministic calculator |
| `mango_quality_analytics` | `inventory_quality` | `LOCAL_ENGINE_VERIFIED` | HSV + GLCM computer vision grading engine |
| `bike_rebalance_analytics` | `inventory_quality` | `LOCAL_ENGINE_VERIFIED` | OLS demand forecasting & station rebalance optimization |
| `trust_engine` | `governance_trust` | `LOCAL_ENGINE_VERIFIED` | Local NIST P-256 ECDSA Merkle DAG seal & verification |
| `sales_capture` | `sales_proposals` | `HUMAN_ASSISTED` | Proposals & payments require HITL approval / confirmation |
| `support_followup` | `customer_support` | `HUMAN_ASSISTED` | External customer messages gated by HITL approval |
| `lead_discovery` | `lead_discovery` | `SIMULATED` | Uses synthetic fallback unless `SERPER_API_KEY` / live search verified |
| `wordpress_publisher` | `seo_content` | `SIMULATED` | Intercepted as `WORDPRESS_SIMULATED_REST` unless live WP creds + `PRODUCTION` |

---

## 2. External Connectors & Production Blockers (11)

| Connector ID | Current Test / Local State | Blocker for `LIVE_VERIFIED` Production Use |
|---|---|---|
| `project_api` | `LOCAL_ENGINE_VERIFIED` | Built-in local Python/ML engines operational |
| `afw_directpay` | `HUMAN_ASSISTED` | Live bank/Web3 receipt settlement relies on Founder confirmation / live `WEB3_RPC_URL` |
| `gemini_api` | `SIMULATED` | Valid non-placeholder `GEMINI_API_KEY` in `PRODUCTION` |
| `serper_search` | `SIMULATED` | Valid live `SERPER_API_KEY` in `PRODUCTION` |
| `google_places` | `SIMULATED` | Valid live `GOOGLE_PLACES_API_KEY` in `PRODUCTION` |
| `hostinger_smtp` | `SIMULATED` | Live `SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD` + SPF/DKIM/DMARC inbox test in `PRODUCTION` |
| `wordpress_rest` | `SIMULATED` | Live `WP_SITE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD` on non-blocked host |
| `razorpay` | `SANDBOX_VERIFIED` / `BLOCKED` | Valid live `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` |
| `paypal` | `SANDBOX_VERIFIED` / `BLOCKED` | Valid `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID` |
| `whatsapp_bridge` | `BLOCKED` / `HUMAN_ASSISTED` | Configured WhatsApp Cloud API bearer token & verified webhook bridge |
| `social_media_bridge` | `BLOCKED` / `ROADMAP` | External OAuth app tokens for LinkedIn/Meta/X auto-posting |
