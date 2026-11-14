# AskforWrite AI Company OS — Master Roadmap Scorecard (P0–P8)

**Architecture:** `UNIFIED_SINGLE_OS`  
**Live Source Endpoint:** `GET /v1/ops/roadmap-scorecard` (`compute_master_roadmap_scorecard`)  
**Overall Release Readiness:** **`BLOCKED`**  
**Production Cutover Approved:** **`false`**

---

## 1. Phase-by-Phase Implementation & Honest Verification Scorecard

| Phase | Title | Code / Migration State | Authoritative Verification Status | Notes & Boundaries |
| :--- | :--- | :--- | :--- | :--- |
| **P0** | Core Security, TrustChain & Execution Guards | `COMPLETE_CODE` | `LOCAL_VERIFIED` | Fail-closed auth, tenant scoping, SSRF validation, secret redaction, ECDSA P-256 `TrustChain`. |
| **P1** | Modular SME Workforce & Pricing Catalog | `COMPLETE_CODE` | `LOCAL_VERIFIED` | `MODULAR_SME_TIERS`, `MODULAR_SERVICE_MODULES`, `CATALOG`, `AGENT_REGISTRY`, `CONNECTOR_SPECS`. |
| **P2** | Commercial Revenue OS & Sovereign Settlement | `COMPLETE_CODE` | `LOCAL_VERIFIED` | Razorpay/PayPal webhooks, settlement classification, outreach/claim integrity filters. |
| **P3** | Customer Success, Onboarding & Health Engine | `COMPLETE_CODE` | `LOCAL_AND_E2E_VERIFIED` | Portal onboarding, QA deliverables, renewals, grace periods, responsive Playwright E2E checks. |
| **P3.1** | Live Verification Registry & Cutover Gate | `COMPLETE_CODE` | **`BLOCKED`** | Blocks cutover (`production_cutover_approved: false`) until all external gates reach `LIVE_VERIFIED`. |
| **P4** | Repeatable Growth & GTM Engine | `COMPLETE_CODE` (`j0e5f6a7b8c9`) | `SANDBOX_VERIFIED` | ICP scoring, provenance market intel, HITL-gated GTM campaigns, `ACTUAL` vs `SANDBOX` funnel analytics. |
| **P5** | Productization, Atomic Ledger & Scale Provisioning | `COMPLETE_CODE` (`k1f6a7b8c9d0`) | `SANDBOX_VERIFIED` | Atomic SQL + `CreditLedgerRecord` `DEBIT` reconciliation, idempotent 9-state provisioning FSM, SLA & quotas. |
| **P6** | Multi-Industry SME Packs & India SEO | `COMPLETE_CODE` (`l2a7b8c9d0e1`) | `SANDBOX_AND_ROADMAP` | 5 SME sector packs (`SANDBOX`/`ROADMAP`, `422` if `verified_live_customers == 0`), integrated diagnostics & JSON-LD SEO. |
| **P7** | Controlled Autonomous Workforce & Evals | `COMPLETE_CODE` (`m3b8c9d0e1f2`) | `SANDBOX_VERIFIED` | Kahn cycle/depth/budget DAG planner, `org_id` TTL/DPDP memory, 5-level autonomy, eval auto-pause. |
| **P8** | Marketplace Ecosystem & Developer SDK | `COMPLETE_CODE` (`n4c9d0e1f2a3`) | `SANDBOX_VERIFIED` | Developer KYB gate, SHA-256 + ECDSA P-256 package signing, tenant secret digests, moderated reviews, `SANDBOX`/`ACTUAL` rev-share. |

---

## 2. Preserved P3.1 Production Cutover Blockers

Production release remains strictly **`BLOCKED`** (`GET /v1/cs/release-readiness` and `GET /v1/ops/roadmap-scorecard` both return `overall_release_readiness: "BLOCKED"` and `production_cutover_approved: false`) until all live external gates below are completed and recorded with non-mock evidence:

1. **`ATTRIBUTION_REQUIRES_CONNECTED_GSC`** — `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `GSC_REDIRECT_URI`, and verified live Google Search Console property authorization remain unconfigured/unverified in live Google Cloud / Render.
2. **`POSTGRES_BACKUP_RESTORE_UNVERIFIED`** — Real PostgreSQL `pg_dump` / `pg_restore` drill against an isolated scratch Neon branch (`DATABASE_URL_UNPOOLED`) has not been executed (`pg_dump`/`pg_restore`/`psql` missing on the Windows dev host).
3. **`RAZORPAY_LIVE_SETTLEMENT_NOT_TESTED`** — Live low-value Razorpay charge + separate merchant UTR payout settlement requires explicit owner authorization (`SANDBOX_VERIFIED` locally; live transaction `NOT_TESTED`).
4. **`PAYPAL_LIVE_PAYOUT_NOT_TESTED`** — Live low-value PayPal order capture + separate payout settlement requires explicit owner authorization (`SANDBOX_VERIFIED` locally; live transaction `NOT_TESTED`).
5. **`RENDER_RUNTIME_NOT_LIVE_VERIFIED`** — Live `/health` verification, Render runtime log inspection, and live environment parity check against production/staging Render dashboards require owner verification.
6. **`STAGING_DEPLOYMENT_SMOKE_NOT_TESTED`** — Isolated Render staging deployment (`askforwrite-ai-company-os-staging`, `ENABLE_EXTERNAL_SIDE_EFFECTS=false`) and staging browser smoke tests remain pending.
