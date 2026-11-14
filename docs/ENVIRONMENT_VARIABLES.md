# Environment Variable Reference

Variables verified in `render.yaml`, `.env.example`, `.env.production.example`, `app/services/execution_guard.py`, `app/services/email_dispatcher.py`, and `app/services/wordpress_publisher.py`. Never commit real secret values to Git or return raw keys in API responses or logs.

---

## 1. Application, Database & Security

| Variable | Description | Default / Example |
|---|---|---|
| `APP_ENV` | Runtime mode (`development`, `staging`, `simulation`, `production`) | `development` |
| `APP_PORT` | HTTP server port | `8000` |
| `UVICORN_WORKERS` | Uvicorn worker processes | `2` (Render) / `4` (`.env.example`) |
| `LOG_LEVEL` | Logging verbosity (`INFO`, `DEBUG`, etc.) | `INFO` |
| `PYTHONUNBUFFERED` | Unbuffered stdout logs | `1` |
| `DATABASE_URL` | SQLAlchemy DB URL (PostgreSQL in prod/staging, SQLite local dev) | `sqlite:///./company_os.db` |
| `NEON_DATABASE_URL` | Optional Neon PostgreSQL connection string (`render.yaml`) | *(Sync: false / Render secret)* |
| `ALLOW_SQLITE_PRODUCTION` | Local SQLite override flag | `true` (local dev template only) |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_PORT` | Docker Compose PostgreSQL parameters | `askforwrite_os` / `askforwrite` / `5432` |
| `OWNER_API_KEY` | Platform owner master API key (`generateValue: true` on Render) | *(Secret)* |
| `MANAGER_API_KEY` | Platform manager API key (`generateValue: true` on Render) | *(Secret)* |
| `JWT_SECRET_KEY` | JWT signing secret (`generateValue: true` on Render) | *(Secret)* |
| `SECRET_KEY` / `AUTH_SECRET_KEY` | App signing / session secret (`generateValue: true` on Render) | *(Secret)* |
| `ALLOWED_ORIGINS` | Comma-separated CORS origin whitelist | `https://os.askforwrite.com,...` |

---

## 2. Execution Mode, Simulation & Side-Effect Guards

| Variable | Description | Values / Effect |
|---|---|---|
| `ENABLE_EXTERNAL_SIDE_EFFECTS` | Master toggle for outbound SMTP, WP, live HTTP | `true` (prod), `false` (Render staging) |
| `SIMULATION_ONLY` | Forces simulation interception across dispatchers & guard | `true` / `false` |
| `DEFAULT_EXECUTION_MODE` | Default mode when caller omits mode | `SIMULATION`, `SANDBOX`, `PRODUCTION` |
| `ALLOW_LIVE_IN_TEST` | Explicitly must stay unset/`false` in automated pytest runs | `false` |
| `PAYMENT_MODE` | Payment gateway environment mode (Render staging) | `sandbox` |
| `SMTP_MODE` | Email sink behavior in staging (`render.yaml`) | `sandbox_sink` |

---

## 3. AI, Search, Email & CMS Connectors

| Variable | Provider / Usage |
|---|---|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Google Gemini platform key (`GEMINI_MODEL`, default `gemini-2.0-flash`) |
| `SERPER_API_KEY` | Serper.dev search API key (optional; explicit fallback if unset) |
| `GOOGLE_PLACES_API_KEY` | Google Maps / Places discovery API key (optional) |
| `OUTREACH_DISPATCH_PROVIDER` | `smtp` or `mock` (auto-overridden to mock/sink if staging/simulation) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `OUTREACH_FROM_EMAIL` | Hostinger SMTP credentials (`smtp.hostinger.com`, `465`, `info@askforwrite.in`) |
| `WP_SITE_URL`, `WP_BASE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD` | WordPress REST v2 publisher credentials (`https://askforwrite.in`) |

---

## 4. Payments, Webhooks & Domain Bridges

| Variable | Provider / Usage |
|---|---|
| `PAYMENT_PROVIDER` | `sovereign_direct`, `sovereign`, `razorpay`, `paypal` |
| `AFW_MERCHANT_UPI_VPA`, `AFW_MERCHANT_NAME`, `AFW_MERCHANT_EVM_WALLET`, `AFW_MERCHANT_SOL_WALLET`, `WEB3_RPC_URL` | AFW DirectPay UPI & Web3 settlement addresses |
| `AFW_BANK_BENEFICIARY`, `AFW_BANK_NAME`, `AFW_BANK_ACCOUNT_NUMBER`, `AFW_BANK_ACCOUNT_TYPE`, `AFW_BANK_IFSC`, `AFW_BANK_SWIFT`, `AFW_BANK_BRANCH` | Direct bank wire details |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `RAZORPAY_PAYMENT_LINK` | Razorpay subscription & HMAC webhook verification |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `PAYPAL_WEBHOOK_SECRET`, `PAYPAL_MODE`, `PAYPAL_PAYMENT_LINK` | PayPal REST subscriptions (`sandbox` / `live`) |
| `ASK4_WEBHOOK_SECRET` | ASK4 Academic integration HMAC webhook secret |
| `FIELD_FORCE_BASE_URL`, `FIELD_FORCE_SERVICE_TOKEN` | Native Field Force service bridge |
| `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | Optional LangSmith telemetry tracing |
