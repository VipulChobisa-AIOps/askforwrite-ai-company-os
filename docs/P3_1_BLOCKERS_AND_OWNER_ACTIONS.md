# P3.1 Blockers & Owner Actions Required

Every real blocker observed during P3.1 verification is listed below. Nothing in this repository has been marked `LIVE_VERIFIED` while these blockers remain open.

---

## Summary of Active Production Blockers

| # | Blocker Key | Current State | Evidence / Observed Cause | Required Owner Action |
|---|---|---|---|---|
| **1** | `ATTRIBUTION_REQUIRES_CONNECTED_GSC` | `BLOCKED` | `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `GSC_REDIRECT_URI`, `GSC_TOKEN_ENCRYPTION_KEY` are absent from `.env` and `render.yaml`; no live Search Console property authorized | Create Google Cloud OAuth 2.0 Web Client with read-only Search Console scope, set HTTPS `GSC_REDIRECT_URI`, populate env vars in Render & `.env`, authorize a verified property, and run live `searchAnalytics/query` check |
| **2** | `POSTGRES_BACKUP_RESTORE_UNVERIFIED` | `BLOCKED` (`restore_tested: false`) | `scripts/pg_backup_restore_drill.py --check-only --json` confirmed missing `pg_dump`, `pg_restore`, and `psql` on current Windows host (`DATABASE_URL` points to Neon `neondb`) | Install PostgreSQL 16+ client tools on an ops runner / Docker container and run `scripts/pg_backup_restore_drill.py` using `DATABASE_URL_UNPOOLED` into an isolated target database (or separate scratch Neon branch with `--confirm-isolated-branch`) and record result via `POST /v1/cs/ops/backup-drill` |
| **3** | `RENDER_RUNTIME_NOT_LIVE_VERIFIED` | `BLOCKED` | Both `https://os.askforwrite.com/health` (`36.2s`) and `https://askforwrite-ai-company-os.onrender.com/health` (`35.8s`) raised `TimeoutError` on read; Render dashboard logs & live runtime env vars are not accessible without Render API/dashboard login | Check Render Web Service instance status (suspended/sleeping/starter cold-start/port bind), inspect Render runtime logs & live env parity against `.env` (`PAYMENT_PROVIDER`, `PAYPAL_MODE`, `RAZORPAY_*`, `GSC_*`, `DATABASE_URL`), verify `200 OK` on `/health`, and run Playwright staging/live smoke against the staging Render URL |
| **4** | `RAZORPAY_LIVE_SETTLEMENT_NOT_TESTED` | `SANDBOX_VERIFIED` (Live: `NOT_TESTED`) | `.env` has `rzp_live_` credentials, but no live low-value charge/refund or UTR merchant settlement was executed (strictly gated on explicit owner authorization) | Authorize one low-value live Razorpay transaction, verify signed `payment.captured` (`CAPTURED_PENDING_SETTLEMENT`), confirm separate Razorpay UTR payout (`SETTLED_TO_MERCHANT`), and test controlled low-value refund reconciliation |
| **5** | `PAYPAL_LIVE_PAYOUT_NOT_TESTED` | `SANDBOX_VERIFIED` (Live: `NOT_TESTED`) | `.env` has `PAYPAL_MODE=live` credentials, but no live PayPal checkout capture or merchant payout settlement has been run | Authorize one low-value live PayPal order capture, verify webhook verification (`verify-webhook-signature`), confirm separate payout batch settlement (`SETTLED_TO_MERCHANT`), and verify ledger reconciliation |
| **6** | `STAGING_DEPLOYMENT_SMOKE_NOT_TESTED` | `LOCAL_VERIFIED` (Staging: `NOT_TESTED`) | Playwright desktop/mobile E2E suite runs locally on ephemeral synthetic SQLite (`tests/e2e/test_dashboard_e2e.py`); staging Render service (`askforwrite-ai-company-os-staging`) has not been E2E-tested | Deploy `feat/p3.1-production-verification-readiness` branch to Render staging (`ENABLE_EXTERNAL_SIDE_EFFECTS=false`) and execute Playwright + API smoke verification against staging URL |

---

## Explicit Non-Negotiable Release Rule

Until Blockers **1–6** transition honestly to `LIVE_VERIFIED` (with non-mock evidence persisted in `p3_operational_incidents` / `p3_acceptance_steps` / `/v1/cs/release-readiness`), `GET /v1/cs/release-readiness` continues to report `overall_release_readiness: "BLOCKED"` and `production_cutover_approved: false`.
