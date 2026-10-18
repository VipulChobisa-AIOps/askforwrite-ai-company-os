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
| **Sovereign Pay** | `POST /v1/pay/create-session` | Public |
| **Checkout UI** | `GET /v1/pay/{session_id}/checkout` | Public |
| **Direct Checkout** | `GET /v1/pay/checkout` | Public |
| **Verify Payment** | `POST /v1/pay/{session_id}/verify` | Public |
| **Autonomous Shifts** | `POST /v1/scheduler/run-shift` | Manager |
| **Shift Briefing** | `GET /v1/scheduler/briefing` | Manager |
| **Shift Status** | `GET /v1/scheduler/status` | Manager |
| **SEO/GEO Audit** | `POST /v1/growth/audit-domain` | Manager |
| **Growth Full Suite** | `POST /v1/growth/run-full-suite` | Manager |
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

All protected endpoints require `X-API-Key` header. Send `X-Correlation-ID` to trace requests.
Swagger UI: `http://localhost:8000/docs`

## Revenue & Autonomous Shift Flow

```
Live SMB Discovery (Keyless DuckDuckGo / Zero-Mock Directory)
  → Live Website SEO/GEO Gap Audit (Schema, /llms.txt, OpenGraph)
  → Trojan Horse Preview Generation (Interactive Pitch + DirectPay Links)
  → Outbound SDR Dispatch (Hostinger SMTP /contact@askforwrite.in)
  → AFW DirectPay Checkout (0% Fee: Instant UPI QR, Bank Wire, Web3 USDC)
  → ECDSA NIST P-256 Merkle Block Sealed in Trust Chain
  → Instant Auto-Provisioning (Tenant Org + User + Invoice Dispatch)
```

Supports **AFW DirectPay** (Sovereign Zero-Fee: UPI, Wire, Polygon/Base/Solana USDC) alongside legacy **Razorpay** and **PayPal** fallbacks.

## Tests & Quality Verification

```powershell
python -m unittest discover -s tests -v
```

**325 / 325 tests passing (100% green)** across all 27 test modules with `0` ruff linting errors.

## Configuration

See [`.env.example`](.env.example) and [`.env.production.example`](.env.production.example) for all environment variables.
See [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) and [`RAILWAY_DEPLOYMENT.md`](RAILWAY_DEPLOYMENT.md) for full deployment instructions.

## Production Checklist

- [x] 325/325 tests passing (100% green)
- [x] AFW DirectPay Sovereign Rails (UPI, ICICI Bank Wire, Web3 USDC)
- [x] ECDSA NIST P-256 Merkle Block Ledger verification
- [x] Autonomous 24/7 SDR Shift Scheduler with zero-mock lead discovery
- [x] 2026 SEO, GEO & AIO growth and gap audit engine
- [x] Hostinger SSL SMTP outbound dispatch (info@askforwrite.in / contact@askforwrite.in)
- [x] Legacy Razorpay & PayPal payment gateway fallback
- [x] Webhook signature verification (HMAC-SHA256)
- [x] Auto-provisioning on payment verification
- [x] Owner HITL approval gates on all external actions
- [x] Local self-custodial wallet vault (.sovereign_wallets.json, git-ignored)
- [x] Alembic migrations verified
- [ ] Production Cloud / Reverse Proxy deployment (Railway / Docker)