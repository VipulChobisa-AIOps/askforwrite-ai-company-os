# Hostinger Business Web Hosting & Cloud OS Deployment Guide

Comprehensive step-by-step operational manual for connecting your 4 Hostinger WordPress properties (`askforwrite.in`, `theaiscene.in`, `careersathi.in`, `edutechguide.in`) to the autonomous **AskforWrite AI Company OS** backend and PWA Portal.

---

## Architecture Overview

```
                                      ┌──────────────────────────────────────────────────────────┐
                                      │              Hostinger DNS Zone Editor                    │
                                      │   CNAME: os.askforwrite.in  ──>  Render / Cloud Host      │
                                      └────────────────────────────┬─────────────────────────────┘
                                                                   │
                                                                   ▼
       ┌─────────────────────────────────────────────────────────────────────────────────────────┐
       │                       AskforWrite AI Company OS (Render / Docker Cloud)                 │
       │                   https://os.askforwrite.in (FastAPI + NIST P-256 Ledger)               │
       ├─────────────────────────────────┬──────────────────────────────────┬────────────────────┤
       │       24/7 AI Sales Closer       │          AFW DirectPay           │ Installable PWA    │
       │  /dashboard/widget.js (0% drop) │ /v1/pay/checkout (UPI/Card/USDC) │ /dashboard/        │
       └────────────────┬────────────────┴────────────────┬─────────────────┴──────────┬─────────┘
                        │                                 │                            │
                        ▼                                 ▼                            ▼
  ┌──────────────────────────────────────────────────────────────┐          ┌──────────────────────┐
  │         4x Hostinger WordPress Sites (Bridge Plugin)          │          │ 1-Click Installation │
  │    • askforwrite.in          • careersathi.in                │          │ • Android (Chrome)   │
  │    • theaiscene.in           • edutechguide.in               │          │ • Windows / macOS    │
  │  Features: Auto Widget Injection | [afw_directpay] | /llms.txt │          │   Desktop Standalone │
  └──────────────────────────────────────────────────────────────┘          └──────────────────────┘
```

---

## Step 1: Add CNAME Record in Hostinger hPanel DNS Zone Editor

Link your custom subdomain `os.askforwrite.in` to your cloud deployment instance (Render, Railway, or VPS).

1. Log in to [Hostinger hPanel](https://hpanel.hostinger.com/).
2. Navigate to **Websites** -> Select **`askforwrite.in`** -> Click **Manage**.
3. In the left-hand search bar, type **DNS Zone Editor** (or scroll to **Advanced -> DNS Zone Editor**).
4. In the **Manage DNS records** card, fill out the form:
   - **Type**: Select `CNAME` from the dropdown.
   - **Name**: Enter `os` (Hostinger automatically appends `.askforwrite.in`).
   - **Target**: Enter your Render web service hostname (e.g. `askforwrite-ai-company-os.onrender.com` or your VPS reverse-proxy address).
   - **TTL**: Select `300` (5 minutes) or leave default `14400`.
5. Click **Add Record**.
6. **DNS Propagation Verification**:
   Open PowerShell or Terminal and run:
   ```powershell
   nslookup os.askforwrite.in
   ```
   *Expected Response:* Shows the alias mapping directly to your cloud instance.

---

## Step 2: Upload Hostinger WordPress Bridge Plugin

Upload `askforwrite-ai-os-bridge.php` to all 4 WordPress properties.

### Option A: Direct WordPress Admin Upload (Zip file)
1. Zip the plugin file or folder:
   - On Windows, right-click `hostinger_deploy` -> **Send to** -> **Compressed (zipped) folder**, naming it `askforwrite-ai-os-bridge.zip`.
2. In your WordPress Admin panel (`https://askforwrite.in/wp-admin`):
   - Go to **Plugins** -> **Add New Plugin**.
   - Click **Upload Plugin** at the top of the page.
   - Click **Choose File**, select `askforwrite-ai-os-bridge.zip`, and click **Install Now**.
   - Click **Activate Plugin**.
3. Repeat for:
   - `https://theaiscene.in/wp-admin`
   - `https://careersathi.in/wp-admin`
   - `https://edutechguide.in/wp-admin`

### Option B: Hostinger hPanel File Manager
1. In Hostinger hPanel, go to **Files -> File Manager**.
2. Open `public_html/wp-content/plugins/`.
3. Create a new folder named `askforwrite-ai-os-bridge`.
4. Upload `hostinger_deploy/askforwrite-ai-os-bridge.php` into that folder.
5. Go to your WordPress Admin -> **Plugins -> Installed Plugins** and click **Activate**.

### Verification of Plugin Features
- **24/7 AI Sales Closer Widget**: Visit any public post or page on your WordPress site; the bottom-right floating chat bubble appears automatically.
- **2026 GEO/AIO Manifest**: Visit `https://askforwrite.in/llms.txt`. You will receive a clean plain-text Markdown specification with verified knowledge graph triples for SearchGPT, Perplexity, and Gemini.
- **AFW DirectPay Shortcode**: Add `[afw_directpay package="growth_all_in_one"]` to any WordPress post or page to render a high-converting 0%-fee UPI/Card checkout button.

---

## Step 3: Generate WordPress Application Password (`WP_APP_PASSWORD`)

To enable the Autonomous SEO Copilot and Content Agent to publish staged articles and update Schema graphs automatically, generate an Application Password.

1. In WordPress Admin (`https://askforwrite.in/wp-admin`):
   - Go to **Users** -> **Profile** (or **All Users** -> Edit your admin user `vipul`).
2. Scroll down to the **Application Passwords** section.
3. In the **New Application Password Name** field, type:
   ```text
   AskforWrite AI Company OS
   ```
4. Click **Add New Application Password**.
5. Copy the generated 24-character string (formatted like `xxxx xxxx xxxx xxxx xxxx xxxx`).
6. Paste it into your backend environment configuration:
   - In `.env` or Render Dashboard Environment Variables:
     ```env
     WP_BASE_URL=https://askforwrite.in
     WP_USERNAME=vipul
     WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx
     ```

---

## Step 4: Install Android App & Windows Desktop PWA

The Executive Command Portal and Customer Portal are now installable Progressive Web Apps with offline caching.

### On Android (Chrome / Brave / Edge)
1. Open Google Chrome on your Android smartphone.
2. Navigate to `https://os.askforwrite.in/dashboard/`.
3. You will see an instant prompt banner or can tap the **three dots menu (⋮)** in the top right.
4. Tap **"Install app"** or **"Add to Home screen"**.
5. Confirm by tapping **Install**.
6. The **AFW OS** icon will be pinned to your Android Home Screen and App Drawer with native full-screen standalone display, biometric/touch responsiveness, and offline telemetry caching.

### On Windows / Mac Desktop (Chrome / Edge)
1. Open Google Chrome or Microsoft Edge on your computer.
2. Navigate to `https://os.askforwrite.in/dashboard/`.
3. Look at the right side of the address bar for the **Install App icon** (computer monitor with a down arrow) or click the glowing **"Install App"** button in the dashboard top navigation bar.
4. Click **Install**.
5. The dashboard will instantly launch in a dedicated borderless desktop application window with taskbar pinning and auto-updating offline shell.

---

## Step 5: Render 1-Click Cloud Deployment

Deploy the backend engine to Render using the included blueprint:

1. Push your changes to GitHub:
   ```bash
   git add .
   git commit -m "feat: Add Hostinger WordPress Bridge and PWA Suite"
   git push origin main
   ```
2. Log in to [Render.com](https://dashboard.render.com/).
3. Click **Blueprints** -> **New Blueprint Instance**.
4. Connect the repository `VipulChobisa-AIOps/askforwrite-ai-company-os`.
5. Render detects `render.yaml` automatically and provisions:
   - High-performance PostgreSQL database (`askforwrite-db`).
   - Production Docker container (`askforwrite-ai-company-os`).
   - Health check monitoring on `/health`.
6. Under **Custom Domains** on Render, add `os.askforwrite.in` and verify the CNAME certificate.

---

## Troubleshooting & Verification Checklist

| Component | Target URL | Expected Result |
| :--- | :--- | :--- |
| **Backend Health** | `https://os.askforwrite.in/health` | `HTTP 200 {"status": "healthy"}` |
| **PWA Manifest** | `https://os.askforwrite.in/dashboard/manifest.json` | `HTTP 200` valid JSON with `AFW OS` |
| **Service Worker** | `https://os.askforwrite.in/dashboard/sw.js` | `HTTP 200` valid Javascript file |
| **DirectPay Checkout** | `https://os.askforwrite.in/v1/pay/checkout?package=growth_all_in_one` | Responsive 0%-fee QR & Web3 checkout |
| **WordPress Widget** | `https://askforwrite.in` | Floating AI Closer in `wp_footer` |
| **2026 AI Crawlers** | `https://askforwrite.in/llms.txt` | Markdown entity specification |

*Need support or custom agent extensions? Contact Vipul Choubisa via the AskforWrite Executive Command Portal.*
