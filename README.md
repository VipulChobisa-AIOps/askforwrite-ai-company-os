# AskforWrite AI Company OS

Production-grade Company Operating System with autonomous multi-agent fleet,
cryptographic trust ledger, HITL governance, and commercial revenue engine.

## Architecture

| Layer | Component |
|---|---|
| **L0 — Human Authority** | Owner HITL approvals for all external actions |
| **L1 — Orchestrator** | Manager/CEO Agent (LangGraph state machine) |
| **L2 — Specialist Agents** | Discovery, Research, Sales, Marketing, SEO, Revenue, Outreach, Delivery |
| **L3 — Revenue Engine** | Lead diagnosis → tailored pitch → Razorpay/PayPal checkout → auto-provisioning |
| **L4 — Data Layer** | SQLite (dev) / PostgreSQL (prod) with SHA-256 cryptographic trust chain |

## Quick Start

### Desktop Application (Recommended)
```powershell
# Automated Setup Wizard
.\Setup_Wizard.bat
```

### From Source
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
Copy-Item .env.example .env
# Fill in secrets in .env
uvicorn app.main:app --reload --port 8000
```

### Docker Production
```bash
cp .env.production.example .env
# Fill in all REQUIRED values
docker compose -f docker-compose.prod.yml up -d
```

## Key API Endpoints

| Category | Endpoint | Auth |
|---|---|---|
| **Health** | `GET /health` | None |
| **Project Status** | `GET /v1/project/status` | Manager |
| **Capabilities** | `GET /v1/capabilities` | Manager |
| **Discovery** | `POST /v1/discovery/execute` | Manager |
| **Research** | `POST /v1/research/execute` | Manager |
| **Sales** | `POST /v1/sales/execute` | Manager |
| **Approvals** | `POST /v1/approvals` | Owner |
| **Delivery** | `POST /v1/delivery/execute` | Manager |
| **Leads** | `POST /v1/leads/discover` | Manager |
| **Outreach** | `POST /v1/outreach/draft` | Manager |
| **Revenue** | `POST /v1/revenue/diagnose` | Manager |
| **Webhooks** | `POST /v1/webhooks/{provider}` | System (HMAC) |
| **Subscriptions** | `GET /v1/subscriptions` | Manager |

All endpoints require `X-API-Key` header. Send `X-Correlation-ID` to trace requests.
Swagger UI: `http://localhost:8000/docs`

## Revenue Engine Flow

```
Lead Discovery → Pain Diagnosis → Commercial Pitch (with checkout link)
  → Owner HITL Approval → Email Dispatch → Payment Webhook
  → Auto-Provisioning (Org + User + Invoice)
```

Supports **Razorpay** (INR) and **PayPal** (USD) dual-gateway.

## Tests

```powershell
$env:APP_ENV="development"; python -m pytest tests/ -v
```

**119/119 tests passing** across 15 test modules.

## Configuration

See [`.env.production.example`](.env.production.example) for all environment variables.
See [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) for full production deployment instructions.

## Production Checklist

- [x] 119/119 tests passing
- [x] Razorpay & PayPal payment gateway integration
- [x] SMTP email dispatch (info@askforwrite.in)
- [x] Webhook signature verification (HMAC-SHA256)
- [x] Auto-provisioning on payment capture
- [x] Owner HITL approval gates on all external actions
- [x] Cryptographic trust chain (SHA-256 block integrity)
- [x] Docker Compose production configuration
- [x] Alembic migrations ready
- [ ] DNS + HTTPS (reverse proxy)
- [ ] Register webhook URLs in Razorpay/PayPal dashboards