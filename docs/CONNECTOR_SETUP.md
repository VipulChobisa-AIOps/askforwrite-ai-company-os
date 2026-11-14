# Connector Setup & Verification Guide

**Source of Truth:** `app/services/connectors.py` (`CONNECTOR_SPECS`, `CAPABILITY_STATES`, `verify_connector_for_org`, `list_connector_states`)  
**API Endpoints:**
- `GET /v1/registry/connectors`
- `POST /v1/registry/connectors/{connector_id}/configure`
- `POST /v1/registry/connectors/{connector_id}/verify`
- `GET /v1/watchdog/connectors`

---

## 1. Strict Truthfulness Rules

1. **A configured API key does NOT imply `LIVE_VERIFIED`.** Storing or detecting `GEMINI_API_KEY`, `SERPER_API_KEY`, or `SMTP_PASSWORD` only updates configuration readiness.
2. **A successful connection check does NOT prove full business workflow execution.** Functional agent execution and provider responses are recorded separately in `execution_evidence`.
3. **Zero Raw Secrets Leak:** API responses, HTML templates, `AuditLog`, and `ExecutionEvidenceRecord` redact raw secrets via `redact_secrets()` (showing only masked hints like `••••1234` or `[REDACTED_SECRET]`).
4. **Tenant Isolation:** Tenant operators (`require_tenant_operator`) only inspect/configure/verify connectors scoped to their own `org_id`.

---

## 2. Registered Connectors (11)

| `connector_id` | Provider | Category | Auth Type | Notes / Verification Behavior |
|---|---|---|---|---|
| `gemini_api` | Google Gemini API | `ai_models` | `api_key_byok` | Supports platform `GEMINI_API_KEY` or tenant BYOK via `/v1/me/gemini-key`; synthetic/placeholder test keys stay `SIMULATED` |
| `serper_search` | Serper.dev Search API | `lead_discovery` | `api_key` | Uses `SERPER_API_KEY`; falls back explicitly when unset (`SIMULATED` / fallback-marked) |
| `google_places` | Google Maps / Places API | `lead_discovery` | `api_key` | Uses `GOOGLE_PLACES_API_KEY`; falls back explicitly when unset |
| `hostinger_smtp` | Hostinger SMTP (TLS/SSL) | `communications` | `smtp_credentials` | Uses `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`/`SMTP_USERNAME`, `SMTP_PASSWORD`, `OUTREACH_FROM_EMAIL`; blocked in `SIMULATION`/`staging` via simulation sink |
| `wordpress_rest` | WordPress REST API v2 | `seo_content` | `basic_app_password` | Uses `WP_SITE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD`; SSRF-checked and simulation-intercepted in test/staging |
| `razorpay` | Razorpay Subscriptions & Webhooks | `billing` | `api_key_pair_hmac` | Uses `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`; marks `SANDBOX_VERIFIED` with `rzp_test_*` keys |
| `paypal` | PayPal Subscriptions REST | `billing` | `oauth2_client_credentials` | Uses `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `PAYPAL_MODE` (`sandbox`/`live`) |
| `afw_directpay` | AskforWrite Sovereign DirectPay | `billing` | `internal_sovereign_ledger` | Built-in UPI SVG QR + Web3 EVM/Solana + Bank Wire with Owner HITL settlement confirmation (`HUMAN_ASSISTED` / `LOCAL_ENGINE_VERIFIED`) |
| `whatsapp_bridge` | WhatsApp Business Cloud API Bridge | `communications` | `bearer_token_webhook` | Requires external delivery bridge token/webhook configuration (`BLOCKED` / `HUMAN_ASSISTED` when unconfigured) |
| `social_media_bridge` | Omnichannel Social Distribution Bridge | `marketing_campaigns` | `oauth2` | Generates copy locally (`LOCAL_ENGINE_VERIFIED`); live post publishing requires external OAuth delivery credentials |
| `project_api` | AskforWrite Domain Engines & Local ML | `inventory_quality` | `internal_jwt_or_api_key` | Local deterministic Python/numpy/CV analytics engines (`LOCAL_ENGINE_VERIFIED`) |

---

## 3. Exposed Verification Payload per Connector

Every connector record in `connector_states` (`ConnectorStateRecord`) exposes:
1. Configuration status (`connection_status`, `config_summary` without raw secrets)
2. Credential validation check
3. Permission validation check
4. Live vs simulation connection test execution (`POST /v1/registry/connectors/{connector_id}/verify`, optional `live_probe`)
5. Test timestamp (`last_verified_at`)
6. Failure reason (`last_error`)
7. Execution environment (`environment`: `SIMULATION`, `SANDBOX`, `PRODUCTION`)
8. Supported capabilities & capability status (`CAPABILITY_STATES`)
9. Last successful execution reference
