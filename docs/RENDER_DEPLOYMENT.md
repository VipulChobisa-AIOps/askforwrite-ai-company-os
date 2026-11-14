# Render Cloud Deployment Guide

AskforWrite AI Company OS keeps **Render** (`render.yaml`) as its primary cloud hosting platform. Do not delete or migrate `render.yaml`.

---

## 1. Configured Render Blueprint Services (`render.yaml`)

`render.yaml` defines two Docker web services in the `singapore` region with `healthCheckPath: /health`:

1. **Production Service:** `askforwrite-ai-company-os`
   - `runtime: docker`, `dockerfilePath: ./Dockerfile`, `plan: starter`, `region: singapore`
   - Custom domain target: `os.askforwrite.com`
   - `APP_ENV=production`, `ENABLE_EXTERNAL_SIDE_EFFECTS="true"`, `PAYMENT_PROVIDER=sovereign_direct`, `UVICORN_WORKERS="2"`
   - Generated secrets (`generateValue: true`): `MANAGER_API_KEY`, `OWNER_API_KEY`, `JWT_SECRET_KEY`, `SECRET_KEY`, `ASK4_WEBHOOK_SECRET`, `RAZORPAY_WEBHOOK_SECRET`
   - Manual Render secrets (`sync: false`): `DATABASE_URL`, `NEON_DATABASE_URL`, `GEMINI_API_KEY`, `SERPER_API_KEY`, `SMTP_PASSWORD`, `WP_APP_PASSWORD`

2. **Isolated Staging & Sandbox Service:** `askforwrite-ai-company-os-staging`
   - `runtime: docker`, `dockerfilePath: ./Dockerfile`, `plan: starter`, `region: singapore`
   - `APP_ENV=staging`, `ENABLE_EXTERNAL_SIDE_EFFECTS="false"`, `PAYMENT_MODE=sandbox`, `SMTP_MODE=sandbox_sink`
   - Requires a separate staging `DATABASE_URL` (`sync: false`) so staging tests never mutate production data.

---

## 2. Database Migration Pre-Deploy Step

Before routing live traffic on a new release, apply additive Alembic migrations to the target PostgreSQL database:

```bash
alembic upgrade head
# Expected revision: g7b2c3d4e5f6 (from f6a1b2c3d4e5)
```

---

## 3. Post-Deploy Verification Checklist

1. Verify `GET https://<service-host>/health` returns HTTP `200` and confirm `alembic current` shows `g7b2c3d4e5f6 (head)`.
2. Verify `/app` loads the pre-auth login gate immediately with updated PWA Service Worker cache (`afw-os-shell-v4.0-p1-workforce`).
3. Keep `ENABLE_EXTERNAL_SIDE_EFFECTS=false`, `PAYMENT_MODE=sandbox`, and `SMTP_MODE=sandbox_sink` on `askforwrite-ai-company-os-staging`.
4. Never infer `LIVE_VERIFIED` for connectors until real credentials (`GEMINI_API_KEY`, `SERPER_API_KEY`, `SMTP_PASSWORD`, `WP_APP_PASSWORD`) are set in the Render Dashboard and verified cleanly.
