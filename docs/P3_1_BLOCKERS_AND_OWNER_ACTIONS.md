# P3.1 Blockers & Owner Actions Required

Every real blocker observed during P3.1 verification is listed below. Nothing in this repository has been marked `LIVE_VERIFIED` while these blockers remain open.

---

## Summary of Active Production Blockers

| # | Blocker Key | Current State | Evidence / Observed Cause | Required Owner Action |
|---|---|---|---|---|
| **1** | `ATTRIBUTION_REQUIRES_CONNECTED_GSC` | `BLOCKED` | `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `GSC_REDIRECT_URI`, `GSC_TOKEN_ENCRYPTION_KEY` are absent from `.env` and `render.yaml`; no live Search Console property authorized | Create Google Cloud OAuth 2.0 Web Client with read-only Search Console scope, set HTTPS `GSC_REDIRECT_URI`, populate env vars in Render & `.env`, authorize a verified property, and run live `searchAnalytics/query` check |
| **2** | `POSTGRES_BACKUP_RESTORE_UNVERIFIED` | **`STAGING_VERIFIED`** (Prod `neondb`: Untouched) | PostgreSQL `18.7` CLI tools installed; isolated Neon project `twilight-resonance-00131838` (`afw_staging` -> `afw_restore_drill`) verified all `26` migrations (`o5d0e1f2a3b4`), `0|0|0` orphans, `pg_dump`/`pg_restore --jobs=8` (`82` tables, `394` indexes, `11` FKs), tenant isolation, and `/healthz`/`/readyz`/`/health` = `200` | During authorized release window, run pre-upgrade orphan SQL on `neondb` and apply `alembic upgrade head` using `DATABASE_URL_UNPOOLED` |
| **3** | `RENDER_RUNTIME_NOT_LIVE_VERIFIED` | `LOCAL_VERIFIED` (Live Render: `BLOCKED`) | Code fixes (`/healthz`, bounded `/readyz`/`/health`, `UVICORN_WORKERS=1` staging, `TRUST_ENGINE_PRIVATE_KEY_PEM` + rotation) implemented & tested locally; live Render not deployed/pushed yet | Push/deploy `fix/infra-remediation-from-11b466e` to Render staging, co-locate region (Render US-East or Neon Singapore), inject `TRUST_ENGINE_PRIVATE_KEY_PEM` & `DATABASE_URL_UNPOOLED`, and verify live `/healthz` + `/readyz` |
| **4** | `RAZORPAY_LIVE_SETTLEMENT_NOT_TESTED` | `SANDBOX_VERIFIED` (Live: `NOT_TESTED`) | `.env` has `rzp_live_` credentials, but no live low-value charge/refund or UTR merchant settlement was executed (strictly gated on explicit owner authorization) | Authorize one low-value live Razorpay transaction, verify signed `payment.captured` (`CAPTURED_PENDING_SETTLEMENT`), confirm separate Razorpay UTR payout (`SETTLED_TO_MERCHANT`), and test controlled low-value refund reconciliation |
| **5** | `PAYPAL_LIVE_PAYOUT_NOT_TESTED` | `SANDBOX_VERIFIED` (Live: `NOT_TESTED`) | Local `.env` has `PAYPAL_MODE=live` while `render.yaml` keeps `PAYPAL_MODE: sandbox` (reconciled via `resolve_paypal_mode()`); no live PayPal checkout capture or merchant payout settlement has been run | Authorize one low-value live PayPal order capture, verify webhook verification (`verify-webhook-signature`), confirm separate payout batch settlement (`SETTLED_TO_MERCHANT`), and verify ledger reconciliation |
| **6** | `STAGING_DEPLOYMENT_SMOKE_NOT_TESTED` | `LOCAL_VERIFIED` (Staging: `NOT_TESTED`) | Playwright desktop/mobile E2E suite runs locally on ephemeral synthetic SQLite (`tests/e2e/test_dashboard_e2e.py`); staging Render service (`askforwrite-ai-company-os-staging`) has not been E2E-tested | Deploy `fix/infra-remediation-from-11b466e` branch to Render staging (`ENABLE_EXTERNAL_SIDE_EFFECTS=false`) and execute Playwright + API smoke verification against staging URL |

---

## Explicit Non-Negotiable Release Rule

Until Blockers **1–6** transition honestly to `LIVE_VERIFIED` (with non-mock evidence persisted in `p3_operational_incidents` / `p3_acceptance_steps` / `/v1/cs/release-readiness`), `GET /v1/cs/release-readiness` continues to report `overall_release_readiness: "BLOCKED"` and `production_cutover_approved: false`.
