# Railway Deployment Guide — AskforWrite AI Company OS

This guide walks you through deploying **AskforWrite AI Company OS** to [Railway](https://railway.com) with PostgreSQL in under 5 minutes.

---

## 1. Prerequisites
- A [Railway account](https://railway.com)
- Your GitHub repository: `https://github.com/VipulChobisa-AIOps/askforwrite-ai-company-os`
- Your API keys and secrets

---

## 2. One-Click / Dashboard Setup

### Step 1: Create a New Project on Railway
1. Open [Railway Dashboard](https://railway.com/dashboard).
2. Click **New Project** → **Deploy from GitHub repo**.
3. Select `VipulChobisa-AIOps/askforwrite-ai-company-os`.

### Step 2: Add a Managed PostgreSQL Database
1. In the same Railway project canvas, click **New** → **Database** → **Add PostgreSQL**.
2. Railway creates a managed PostgreSQL instance and sets `DATABASE_URL` automatically.

### Step 3: Link PostgreSQL to `os_gateway`
1. Click on the `askforwrite-ai-company-os` service card.
2. Go to **Variables** tab.
3. Click **Add Reference** → select `Postgres` → choose `DATABASE_URL`.
   - Railway will set `${{Postgres.DATABASE_URL}}`.
   - The application automatically normalizes `postgres://` or `postgresql://` into `postgresql+psycopg://`.

### Step 4: Configure Production Environment Variables
In the **Variables** tab of the `os_gateway` service, add the following:

#### Core Application (Required)
```env
APP_ENV=production
MANAGER_API_KEY=YOUR_GEN_KEY_MIN_32_CHARS
OWNER_API_KEY=YOUR_GEN_KEY_MIN_32_CHARS
```
*Generate secure 32+ char keys in terminal with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`*

#### Observability & Monitoring
```env
SENTRY_DSN=https://your-dsn@sentry.io/project-id   # Optional (for real-time error tracking)
SENTRY_TRACES_SAMPLE_RATE=0.2
LOG_LEVEL=INFO
```

#### Allowed Origins (CORS)
```env
ALLOWED_ORIGINS=https://dashboard.askforwrite.in,https://your-custom-domain.com
```

#### Payment Gateways & Revenue Engine
```env
PAYMENT_PROVIDER=razorpay
RAZORPAY_KEY_ID=rzp_live_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
RAZORPAY_PAYMENT_LINK=https://razorpay.me/@askforwrite

PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_WEBHOOK_ID=...
PAYPAL_WEBHOOK_SECRET=...
PAYPAL_MODE=live
PAYPAL_PAYMENT_LINK=https://paypal.me/ask4write
```

#### Outbound SMTP (Owner-HITL gated outreach)
```env
OUTREACH_DISPATCH_PROVIDER=smtp
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=587
SMTP_USERNAME=info@askforwrite.in
SMTP_PASSWORD=...
OUTREACH_FROM_EMAIL=info@askforwrite.in
```

#### AI Agents (Gemini & LangSmith)
```env
GOOGLE_API_KEY=AIzaSy...
GEMINI_MODEL=gemini-2.0-flash
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=askforwrite-company-os
```

---

## 3. Verify Deployment & Startup

On deployment, `scripts/start_production.py` automatically:
1. Validates all environment variables and secrets.
2. Executes Alembic migrations (`alembic upgrade head`) to construct all 25 tables.
3. Seeds the ECDSA NIST P-256 cryptographic **Genesis Trust Block**.
4. Spawns Uvicorn with structured JSON logging on `$PORT`.

### Check Health:
Railway provides an automatic public domain (e.g., `https://askforwrite-os-production.up.railway.app`).

Verify with:
```bash
curl https://<your-railway-domain>/health
```
Expected output:
```json
{"status": "healthy", "capability": "offline_discovery", "database": "connected"}
```

Visit the interactive docs:
- Swagger UI: `https://<your-railway-domain>/docs`
- Owner Dashboard: `https://<your-railway-domain>/dashboard/`

---

## 4. Custom Domain & SSL (Auto-HTTPS)

1. In Railway service settings, click **Networking** → **Generate Domain** or **Custom Domain**.
2. Enter your desired domain (e.g. `api.askforwrite.in`).
3. Add the displayed CNAME record to your DNS provider (Cloudflare, Hostinger, GoDaddy).
4. Railway automatically provisions a free Let's Encrypt SSL certificate and enforces HTTPS.

---

## 5. Webhook Registration

Register your public Railway URL in your payment merchant dashboards:

| Provider | Webhook URL | Events to Subscribe |
|---|---|---|
| **Razorpay** | `https://<domain>/v1/webhooks/razorpay` | `payment.captured`, `order.paid`, `subscription.activated` |
| **PayPal** | `https://<domain>/v1/webhooks/paypal` | `PAYMENT.CAPTURE.COMPLETED`, `BILLING.SUBSCRIPTION.ACTIVATED` |

---

## 6. Continuous Deployment via GitHub Actions

Every commit pushed to the `main` branch automatically:
1. Runs the test suite (166 tests).
2. Verifies Docker image building.
3. If you add `RAILWAY_TOKEN` to your GitHub Repo Secrets (under Settings → Secrets and variables → Actions), it triggers an automated zero-downtime deployment.
