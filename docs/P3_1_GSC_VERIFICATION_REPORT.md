# P3.1 Google Search Console (GSC) Verification Report

**Primary Service:** `app/services/gsc_integration.py`  
**Registry Entry:** `google_search_console` in `app/services/connectors.py` (`CONNECTOR_SPECS`, default state `BLOCKED`)  
**Verification State:** **`SANDBOX_VERIFIED`** (deterministic `MockTransport` + Fernet vault tests) / **`BLOCKED`** in live runtime (`ATTRIBUTION_REQUIRES_CONNECTED_GSC`)

---

## 1. Explicit 5-State Lifecycle Model (`GSC_STATES`)

OAuth authorization alone no longer implies attribution readiness. Every tenant organization tracks exact verification transitions in `ConnectorStateRecord` (`connector_id="google_search_console"`):

1. `OAuth_CONNECTED` — Valid CSRF state + OAuth code exchanged; access and refresh tokens encrypted via Fernet and persisted in `config_json["vault_cipher_payload"]` (stripped from API serialization).
2. `PROPERTY_VERIFIED` — Verified access against Google Webmasters `/webmasters/v3/sites` list matching selected property URL.
3. `DATA_FETCH_VERIFIED` — Live Search Analytics (`searchAnalytics/query`) response retrieved and summarized.
4. `ATTRIBUTION_READY` — Verified impressions/clicks/CTR/position (plus baseline comparison window when supplied) attached to `P3ServiceDeliveryRecord.outcome_metrics_json` with explicit `attribution_evidence_level` (`CORRELATED_BASELINE_OBSERVED`).
5. `BLOCKED` — Unconfigured OAuth env vars, unsafe non-HTTPS redirect URI (outside localhost dev), unverified property, revoked refresh token, or user disconnect.

---

## 2. Ten Verification Controls Covered

1. **OAuth Authorization URL (`build_gsc_oauth_authorization_url`):** Generates Google OAuth 2.0 URL with read-only `https://www.googleapis.com/auth/webmasters.readonly` scope, `access_type=offline`, `prompt=consent`, and HMAC/SHA-256 CSRF state hash (`oauth_state_hash` stripped from API outputs).
2. **Redirect URI & Scope Validation (`_validate_redirect_uri`):** Enforces HTTPS outside local loopback (`localhost` / `127.0.0.1`), rejecting `http://` public redirects (`GSC_INSECURE_REDIRECT_URI`).
3. **Encrypted Token Storage (`_derive_fernet`, `_encrypt_vault_bundle`):** Encrypts `access_token` and `refresh_token` at rest inside `vault_cipher_payload`; `serialize_connector` & `serialize_gsc_state` pop sensitive cipher/state hash fields.
4. **Token Refresh & Expiration Handling (`_refresh_access_token_if_needed`):** Automatically refreshes near-expiry tokens; transitions connector to `BLOCKED` (`GSC_REFRESH_REVOKED`, HTTP `401`) if Google revokes refresh token.
5. **Property Selection:** Supports selecting target `site_url` (`sc-domain:...` or URL prefix).
6. **Property Access Verification (`verify_and_select_gsc_property`):** Rejects unverified or missing permissions against `/webmasters/v3/sites` and moves state to `BLOCKED`.
7. **Actual Search Analytics Retrieval (`fetch_gsc_search_analytics`):** Queries Google Search Console `searchAnalytics/query` endpoint.
8. **Date-Range & Dimension Handling (`_validate_iso_range`):** Validates ISO `YYYY-MM-DD` ranges, chronological order, row limits (`1..5000`), and Search Console dimensions (`query`, `page`, `date`, `country`, `device`).
9. **Attribution Data Persistence:** Persists summarized Search Console observations & baseline delta onto `P3ServiceDeliveryRecord` without overclaiming causation.
10. **Disconnect & Revocation (`disconnect_gsc_account`):** Clears stored vault tokens, invalidates state, and resets connector to `BLOCKED`.

---

## 3. API Routes & Access Control

- **Customer Self-Service (`app/api/v1/customer_portal.py`, tenant JWT scoped):**
  - `GET /v1/me/integrations/gsc/status`
  - `POST /v1/me/integrations/gsc/oauth/url`
  - `POST /v1/me/integrations/gsc/oauth/exchange`
  - `POST /v1/me/integrations/gsc/properties/verify`
  - `POST /v1/me/integrations/gsc/analytics/query`
  - `POST /v1/me/integrations/gsc/disconnect`
- **Platform Operator (`app/api/v1/customer_success.py`, `require_platform_manager`):**
  - `GET /v1/cs/integrations/gsc/{org_id}/status`
  - `POST /v1/cs/integrations/gsc/{org_id}/oauth/url`
  - `POST /v1/cs/integrations/gsc/{org_id}/oauth/exchange`
  - `POST /v1/cs/integrations/gsc/{org_id}/properties/verify`
  - `POST /v1/cs/integrations/gsc/{org_id}/analytics/query`
  - `POST /v1/cs/integrations/gsc/{org_id}/disconnect`

Cross-tenant access (e.g., Tenant B calling `/v1/cs/integrations/gsc/{org_a}/status`) returns HTTP `403`.

---

## 4. Test Coverage & Live Blocker Status

- **Automated Tests (`tests/test_p3_1_gsc_integration.py` — 4/4 passed):**
  - `test_gsc_blocked_when_unconfigured_or_unsafe_redirect`
  - `test_gsc_full_lifecycle_all_5_states_encryption_refresh_and_attribution`
  - `test_gsc_unverified_property_and_revoked_refresh_transition_to_blocked`
  - `test_gsc_api_routes_tenant_isolation_and_registry_listing`
- **Live Environment Inspection (`.env` key-presence audit):**
  - `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, and `GSC_REDIRECT_URI` are **absent** from `.env` (template variables added to `.env.example`).
  - Live Google Search Console property OAuth consent, live token exchange, and live API pull are **`BLOCKED`** (`ATTRIBUTION_REQUIRES_CONNECTED_GSC`) until owner supplies Google Cloud OAuth credentials and authorizes a dedicated verified property.
