# AskforWrite AI Company OS — Production Desktop Deployment Guide

This guide details how to install, configure, deploy, and operate the **AskforWrite AI Company OS** as a Windows Desktop application with complete Setup Wizard.

---

## 1. Overview & Architecture

The application is bundled into a self-contained desktop system with:
- **Desktop Control Center & Setup Wizard** (`AskforWrite_Company_OS.exe` / `desktop_app.py`):
  - Graphical interface for configuring environment secrets, database settings, and AI models.
  - One-click schema creation and Genesis Trust Block seeding.
  - Server control (Start, Stop, Restart Uvicorn with live streaming log console).
  - Multi-Agent Orchestrator interface (interactive LangGraph agent testing with Gemini and LangSmith telemetry).
  - Cryptographic Trust Ledger validator (checks SHA-256 block hash integrity across the ledger).
- **FastAPI Enterprise Gateway** (`app/main.py`):
  - Offline discovery, grounded research, requirement capture, durable owner approvals.
  - Cryptographic trust chain (`TrustBlock`) recording every state transition.
  - Role-based authorization (`manager` vs `owner` HITL control).
- **AI Agent Fleet** (`app/agents/`):
  - LangGraph state machine with automatic fallback between Gemini models (`gemini-2.5-flash` / `gemini-3.5-flash`).
  - LangSmith tracing integration.

---

## 2. Desktop Quick Start

### Option A: Using the Automated Setup Wizard
1. Double-click **`Setup_Wizard.bat`** in the `os_gateway` directory.
2. The wizard will automatically:
   - Verify Python environment and compiled binaries.
   - Set up `.env` from template if not present.
   - Synchronize the database schema and seed the Genesis Trust Block.
   - Create a desktop shortcut (**`AskforWrite AI Company OS.lnk`**) on your Windows Desktop.
   - Launch the Control Center.

### Option B: Running the Compiled Standalone Executable
- Navigate to `dist\AskforWrite_Company_OS\` and double-click **`AskforWrite_Company_OS.exe`**.

### Option C: Running from Source / Terminal
```powershell
.venv\Scripts\Activate.ps1
python desktop_app.py
```

---

## 3. Configuration & Setup Steps (In the GUI Wizard)

When you open the Desktop Application, navigate to the **🛠️ Setup Wizard & Credentials** tab:

1. **Step 1: Environment & Port**
   - **APP_ENV**: Set to `development` for local standalone use, or `production` when connecting to PostgreSQL.
   - **APP_PORT**: Defaults to `8000`.
   - **ALLOWED_ORIGINS**: Configure allowed frontend origins (e.g. `http://localhost:3000`).

2. **Step 2: Database Configuration**
   - Click **"Use Embedded SQLite (Recommended)"** for zero-dependency desktop operation (`sqlite:///./company_os.db`).
   - Click **"Initialize Database & Genesis Trust Block"** to create all tables and verify the cryptographic genesis block.

3. **Step 3: Security & Role-Based API Keys**
   - Click **"🎲 Generate Key"** for **MANAGER_API_KEY** (used for automated agents and capabilities).
   - Click **"🎲 Generate Key"** for **OWNER_API_KEY** (used for Human-In-The-Loop approvals and governance).

4. **Step 4: AI Engine (Gemini) & LangSmith Telemetry**
   - Enter your `GOOGLE_API_KEY`.
   - Click **"🧪 Test AI Key"** to verify connection to Gemini.
   - Enter your `LANGSMITH_API_KEY` and set `LANGSMITH_TRACING=true` to enable execution tracing.
   - Click **"💾 Save Configuration (.env)"**.

---

## 4. Operating the Gateway

### Starting the Server
1. Go to the **⚡ Server & Live Console** tab.
2. Click **▶ Start Server**.
3. The status badge will switch to green **● SERVER ACTIVE (PORT 8000)**.
4. Click **📖 Open API Docs (Swagger)** to access `http://127.0.0.1:8000/docs` in your browser.
5. All live requests and logs stream in real-time inside the console.

### Running Multi-Agent Tests
1. Go to the **🤖 Multi-Agent Fleet & Diagnostics** tab.
2. Click **⚡ Run LangGraph AI Cycle (Gemini + Agents)**:
   - Watches the Manager Agent plan, Discovery Agent evaluate prospect fit, Sales Agent draft proposals, and pauses at the mandatory Owner HITL approval gate.
3. Click **🛡️ Verify Cryptographic Trust Ledger**:
   - Audits all SHA-256 blocks for tampering and reports verified chain integrity.
4. Click **🔄 Run Full E2E Integration Suite**:
   - Executes the 7-step full system integration cycle.

---

## 5. Building an Inno Setup Windows Installer

If you wish to distribute a single setup wizard installer (`Setup_AskforWrite_Company_OS.exe`):
1. Install [Inno Setup 6](https://jrsoftware.org/isdl.php).
2. Right-click `installer_script.iss` and select **Compile**.
3. The installer executable will be generated in `dist_installer\Setup_AskforWrite_Company_OS.exe`.

---

## 6. Commercial Revenue Engine & Webhook Configuration

The **Company OS Revenue Engine** converts prospects into paying customers through an autonomous diagnosis, tailored commercial pitch, and automated multi-tenant customer provisioning.

### 6.1 Webhook Endpoints
Configure your payment provider dashboards to deliver webhook events to the following URLs:

| Provider | Webhook URL | Required Header | Verification |
|---|---|---|---|
| **Razorpay** | `POST https://<your-domain>/v1/webhooks/razorpay` | `X-Razorpay-Signature` | HMAC-SHA256 (`RAZORPAY_KEY_SECRET` or `RAZORPAY_WEBHOOK_SECRET`) |
| **PayPal** | `POST https://<your-domain>/v1/webhooks/paypal` | `paypal-transmission-sig` | PayPal REST API verification endpoint / Transmission ID |

### 6.2 Supported Events & Auto-Provisioning
When an event of type `payment.captured` or `payment.sale.completed` is received:
1. Webhook signature is cryptographically validated.
2. The payment record is logged in `WebhookEventRecord` for idempotency and audit.
3. The customer organization is auto-provisioned (`OrganizationRecord`, `UserRecord`, `CustomerRecord`).
4. An `InvoiceRecord` is automatically generated with currency, amount, and `paid` status.

### 6.3 Owner HITL Outbound Outreach
Outreach messages are subject to strict Human-In-The-Loop authorization:
1. **Drafting**: The agent diagnoses the prospect, identifies the best-fit modular tool, generates a pitch with an embedded Razorpay or PayPal checkout link, and stores the outreach in `drafted` state.
2. **Approval Gate**: The Owner reviews and approves via `POST /v1/outreach/{outreach_id}/approve` (requires `OWNER_API_KEY`).
3. **Dispatch**: Once approved, the outreach is dispatched via SMTP (`POST /v1/outreach/{outreach_id}/dispatch`).

---

## 7. Production Checklist

Before switching `APP_ENV=production`:
- [ ] Set `APP_ENV=production` in `.env`.
- [ ] Configure PostgreSQL database connection (`DATABASE_URL=postgresql+psycopg://...`).
- [ ] Run Alembic migrations: `alembic upgrade head`.
- [ ] Set `MANAGER_API_KEY` and `OWNER_API_KEY` (minimum 32 random characters).
- [ ] Add production domain to `ALLOWED_ORIGINS`.
- [ ] Configure `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET`.
- [ ] Configure `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, and `PAYPAL_WEBHOOK_ID`.
- [ ] Set `OUTREACH_DISPATCH_PROVIDER=smtp` and supply SMTP credentials.
- [ ] Verify health status endpoint: `GET /health` returns `{"status": "healthy", "database": "connected"}`.
- [ ] Verify capability registry: `GET /v1/capabilities`.

