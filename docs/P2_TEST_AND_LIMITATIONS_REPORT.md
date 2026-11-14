# P2 Test, Verification & Honest Limitations Report

**Branch:** `feat/p2-first-customer-revenue-engine`  
**Alembic Revision:** `h8c3d4e5f6a7 (head)`  
**Primary Offer Verified:** `managed_seo_content_pilot` — *AskforWrite Managed SEO & Content Pilot (14-Day)* (`INR 4,999` / `USD 59`, `billing_type="managed_pilot_14d"`, `billing_interval="14_days"`)

---

## 1. Executed Checks & Verified Results

All checks below ran cleanly after the final P2 implementation and test edits:

| Check | Exact Command | Observed Result |
|---|---|---|
| **Alembic Migration State** | `.venv\Scripts\alembic.exe current` | `h8c3d4e5f6a7 (head)` |
| **Migration Parity Tests** | `.venv\Scripts\pytest.exe tests\test_migrations.py -v` | `6 passed in 0.88s` (includes `test_p2_commercial_migration_upgrade_and_downgrade_parity` verifying all 6 P2 tables) |
| **Static Analysis (Lint)** | `.venv\Scripts\ruff.exe check app tests migrations` | `All checks passed!` |
| **Dashboard JS Syntax** | `node --check app\dashboard\dashboard.js` | Exited with code `0` |
| **P2 Revenue Engine Suite** | `.venv\Scripts\pytest.exe tests\test_p2_revenue_engine.py -v` | `4 passed in 5.97s` |
| **Full Repository Test Suite** | `.venv\Scripts\pytest.exe tests -q --tb=short` | `448 passed in 170.42s (0:02:50)` (`0` failed, `0` skipped) |

### What `tests/test_p2_revenue_engine.py` Verified in Sandbox Mode

1. **`test_01_catalog_offer_contract_and_prospect_dedup_qualification`**
   - Verifies `managed_seo_content_pilot` commercial contract (`INR 4,999` / `USD 59`, `managed_pilot_14d`, capabilities, credit allocations).
   - Verifies prospect intake rejects synthetic/fixture domains/emails, deduplicates across normalized domain and normalized company identity, and generates deterministic 6-criterion qualification scores (`icp_fit`, `need_evidence`, `activity_website_quality`, `service_fit`, `contact_validity`, `evidence_freshness`).
2. **`test_02_brief_outreach_honesty_hitl_simulation_separation_and_suppression`**
   - Verifies Account Intelligence Brief separates verified facts from inferences and unverified assumptions.
   - Verifies outreach integrity guard blocks fabricated claims (`"We guarantee #1 Google ranking within 14 days"`, `"50% off expires today"`).
   - Verifies HITL approval gate via `/v1/approvals/{id}/decision`, confirms simulation dispatch (`MockEmailDispatcher` / `SIMULATED_SENT`) stays strictly separated from verified live outreach KPIs, and validates persistent opt-out suppression (`p2_suppression_entries` / `/v1/outreach/unsubscribe`).
3. **`test_03_end_to_end_discovery_proposal_settlement_onboarding_delivery_and_renewal`**
   - Exercises the complete 12-stage journey in-sandbox: prospect -> brief -> response & discovery -> 8-clause proposal -> Owner HITL approval -> proposal share -> AFW DirectPay proof submission (`/v1/pay/{session_id}/verify`) + Owner settlement confirmation (`/v1/pay/{session_id}/confirm-owner`) -> tenant provisioning & engagement activation -> client onboarding inputs -> pilot delivery staging -> human-reviewed delivery completion -> post-pilot feedback & manual renewal evaluation (`auto_charge_disabled=True`).
4. **`test_04_razorpay_webhook_settlement_idempotency_retry_and_refund_revocation`**
   - Verifies Razorpay HMAC-signed `payment.captured` webhook at `/v1/webhooks/payment` provisions tenant `managed_seo_content_pilot`, completes `p2_reconciliation` (`ACTIVATION_COMPLETED`), safely ignores duplicate webhook replay (`{"status": "duplicate"}`), and revokes tenant tier (`free`), entitled capabilities (`[]`), and delivery access (`HTTP 422`) upon signed `refund.processed` webhook.

---

## 2. Honest Capability Boundaries & Runtime Limitations

| Subsystem / Integration | Verification Classification | Current Scope & Constraints |
|---|---|---|
| **P2 Commercial State Machine, Qualification, Epistemic Briefs, Honesty Validator, Proposals, Reconciliation & Engagement Ops** | `LOCAL_ENGINE_VERIFIED` & `SANDBOX_VERIFIED` | Verified locally across 448 passing pytest cases against isolated in-memory SQLite (`tests/test_p2_revenue_engine.py`) and local PostgreSQL Alembic head (`h8c3d4e5f6a7`). |
| **AFW DirectPay (`afw_directpay`) Proof + Owner Confirmation** | `HUMAN_ASSISTED` / `SANDBOX_VERIFIED` | Bank/UPI/Web3 UTR settlement still requires manual bank reconciliation by the founder before calling `POST /v1/pay/{session_id}/confirm-owner`. |
| **Razorpay Webhook Verification (`razorpay`)** | `SANDBOX_VERIFIED` (Signed payload tests) | Webhook HMAC verification (`X-Razorpay-Signature`), idempotency, provisioning, and full-refund revocation are tested with signed synthetic Razorpay events. **Live Razorpay API checkout/payment capture with live INR money movement (`LIVE_VERIFIED`) has NOT been tested in this offline environment.** |
| **PayPal (`paypal`)** | `NOT_TESTED` (Live gateway) | Live PayPal sandbox/production API capture and webhook signature verification with live PayPal credentials were **not** executed against PayPal's remote servers in this session. |
| **Outbound Email (`hostinger_smtp`)** | `SIMULATED` in dev/staging / `NOT_TESTED` against live SMTP server | In test/staging (`APP_ENV=development`), `MockEmailDispatcher` records `SIMULATED_SENT` cleanly and does **not** increment live outreach KPIs. Sending a live email through production Hostinger SMTP credentials (`SENT`, `external_sent: true`) has **not** been executed in this session. |
| **Live Prospect Discovery (`serper_search`, `google_places`)** | `NOT_TESTED` (Live external API keys) | `prospect_discovery_agent` uses `check_connector_execution_allowed()` and blocks unverified connectors in production. Live remote Serper/Google Places queries depend on valid production API keys (`SERPER_API_KEY`, `GOOGLE_PLACES_API_KEY`). |
| **P2 Browser UI E2E (`app/dashboard/index.html`, `app/dashboard/dashboard.js`)** | Syntax verified (`node --check`), **browser DOM/Playwright E2E NOT run** | `node --check app\dashboard\dashboard.js` passed (`exit 0`). Automated headless browser clicks (Playwright/Selenium) were not executed because `playwright` is not installed in the environment. Manual click-through in `/app` under the *P2 Commercial Revenue OS* tab is required during pre-launch UAT. |
| **Real-World Commercial Execution (Steps 1–12)** | `NOT_TESTED` (Live buyer cycle) | `p2_acceptance_checklist_steps` starts at `NOT_TESTED` on fresh databases. No live prospect has yet received a live outreach email or paid INR 4,999 in production. |

---

## 3. Manual Production Prerequisites Before First Real Customer

Before executing Step 6 (`send_live_outreach`) or Step 9 (`verify_real_payment`) with real buyers on Render (`askforwrite-ai-company-os`):

1. Confirm database migration head `h8c3d4e5f6a7` in production PostgreSQL (`alembic upgrade head`).
2. Configure production secrets cleanly on Render (`APP_ENV=production`, `ALLOW_LIVE_SIDE_EFFECTS=true`, strong `OWNER_API_KEY`, `SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD`/`OUTREACH_FROM_EMAIL`, and `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`/`RAZORPAY_WEBHOOK_SECRET` and/or UPI/bank details for `afw_directpay`).
3. Verify `hostinger_smtp`, `razorpay`/`afw_directpay`, and any enabled discovery connectors in `/v1/registry/connectors/{id}/verify` until production connectors report `LIVE_VERIFIED`.
4. Perform a visual smoke walkthrough of `/app` -> **P2 Commercial Revenue OS** (`1. Prospects & Briefs` through `5. 12-Step Acceptance Checklist`) and update each real-world checklist step (`POST /v1/commercial/acceptance-checklist/{step_number}`) only as genuine external proof is collected.
