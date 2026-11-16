# AskforWrite AI Company OS — Master Roadmap Scorecard (P0–P8)

**Architecture:** `UNIFIED_SINGLE_OS`  
**Live Source Endpoint:** `GET /v1/ops/roadmap-scorecard` (`compute_master_roadmap_scorecard`)  
**Overall Release Readiness:** **`BLOCKED`**  
**Production Cutover Approved:** **`false`**  
**Audit Documentation Index:** All 9 authoritative release audit reports indexed below  

---

## 1. Phase-by-Phase Implementation & Authoritative Verification Scorecard

| Phase | Title | Code / Migration State | Authoritative Verification Status | Notes & Governance Boundaries |
| :--- | :--- | :--- | :--- | :--- |
| **P0** | Core Security, TrustChain & Execution Guards | `COMPLETE_CODE` | `LOCAL_VERIFIED` | Fail-closed auth, tenant scoping, SSRF validation, secret redaction, ECDSA NIST P-256 `TrustChain`. |
| **P1** | Modular SME Workforce & Pricing Catalog | `COMPLETE_CODE` | `LOCAL_VERIFIED` | `MODULAR_SME_TIERS`, `MODULAR_SERVICE_MODULES`, `CATALOG`, `AGENT_REGISTRY`, `CONNECTOR_SPECS`. |
| **P2** | Commercial Revenue OS & Sovereign Settlement | `COMPLETE_CODE` | `LOCAL_VERIFIED` | Razorpay/PayPal webhooks, settlement classification, outreach/claim integrity filters. |
| **P3** | Customer Success, Onboarding & Health Engine | `COMPLETE_CODE` | `LOCAL_AND_E2E_VERIFIED` | Portal onboarding, QA deliverables, renewals, grace periods, responsive Playwright browser E2E checks (4 passed). |
| **P3.1** | Live Verification Registry & Cutover Gate | `COMPLETE_CODE` | **`BLOCKED`** | Blocks cutover (`production_cutover_approved: false`) until all external live staging gates reach `LIVE_VERIFIED`. |
| **P4** | Repeatable Growth & GTM Engine | `COMPLETE_CODE` (`j0e5f6a7b8c9`) | `SANDBOX_VERIFIED` | ICP scoring, provenance market intel, HITL-gated GTM campaigns, `ACTUAL` vs `SANDBOX` funnel analytics. |
| **P5** | Productization, Atomic Ledger & Scale Provisioning | `COMPLETE_CODE` (`k1f6a7b8c9d0`) | `SANDBOX_VERIFIED` | Atomic SQL + `CreditLedgerRecord` `DEBIT` reconciliation, idempotent 9-state provisioning FSM, SLA & quotas. |
| **P6** | Multi-Industry SME Packs & India SEO | `COMPLETE_CODE` (`l2a7b8c9d0e1`) | `SANDBOX_AND_ROADMAP` | 5 SME sector packs (`SANDBOX`/`ROADMAP`, `422` if `verified_live_customers == 0`), integrated diagnostics & JSON-LD SEO. |
| **P7** | Controlled Autonomous Workforce & Evals | `COMPLETE_CODE` (`m3b8c9d0e1f2`) | `LOCAL_VERIFIED` / `SANDBOX_VERIFIED` | Kahn cycle/depth/budget DAG planner, `org_id` TTL memory, 5-level autonomy runtime enforcement, daily/execution budget & LLM metering separation, reversible-only compensation, cooperative timeout cancellation, eval auto-pause. |
| **P8** | Marketplace Ecosystem & Developer SDK | `COMPLETE_CODE` (`n4c9d0e1f2a3`) | `LOCAL_VERIFIED` / `SANDBOX_VERIFIED` | Developer KYB gate, SHA-256 + node-pinned ECDSA P-256 package signing, tenant secret digests & install revocation, PII redaction for non-owners, moderated active-install reviews, third-party executable plugins permanently disabled. |
| **Post-P8 Security Hardening** | Tenant Isolation, P8/P7 Governance & FK Integrity | `COMPLETE_CODE` (`o5d0e1f2a3b4`) | `LOCAL_SECURITY_HARDENED` | Public privilege-escalation closure, single-use org invitations, strict platform vs tenant RBAC split, P2/P4–P8 cross-record ownership & FK constraints, unpooled migration connection prioritization. |
| **Infra & Runtime Readiness** | Render Sizing, Regional Latency & Health Probe | `AUDIT_COMPLETE` | `LOCAL_VERIFIED` / **`BLOCKED`** | Singapore to US East latency (400 ms RTT), Uvicorn 2 workers memory risk (460 MB vs 512 MB limit), `/health` 35.8s timeout root cause diagnosed, `./keys` ephemeral disk rotation analyzed. |
| **Database Parity & Recovery** | Neon PostgreSQL Migration & Backup Drill | `AUDIT_COMPLETE` | `LOCAL_VERIFIED` / **`BLOCKED`** | 26 migrations compile to 2,280 lines offline PostgreSQL DDL (`o5d0e1f2a3b4`), marketplace orphan prechecks documented, live drill blocked pending isolated staging branch. |

---

## 2. Nine Authoritative Release Audit Reports Index

The following 9 audit reports in `docs/` provide the definitive empirical evidence, root cause analyses, and runbooks for AskforWrite AI Company OS:

1. **`docs/SECURITY_HARDENING_AUDIT_REPORT.md`**  
   *Scope:* Full 388 APIRoute authorization classification (204 tenant, 123 platform, 56 public, 5 optional auth), cross-tenant isolation across 7 domains, zero secret exposures, diff integrity audit, static analysis & linter results (`LOCAL_VERIFIED`).
2. **`docs/TENANT_ISOLATION_VERIFICATION_REPORT.md`**  
   *Scope:* 5-tier role hierarchy, fail-closed active user/org checks, Field Force cross-tenant auto-dispatch remediation, P7 memory purge scoping, P8 install secret masking, public signup privilege restriction (`LOCAL_VERIFIED`).
3. **`docs/P7_AUTONOMY_GOVERNANCE_REPORT.md`**  
   *Scope:* 5-level autonomy policy enforcement (`LEVEL_0_OBSERVE` to `LEVEL_4_SUPERVISED_ORCHESTRATION`), prohibited unrestricted aliases, Kahn DAG topological sorting, genuine blocking timeout interruption, partial persistence, cooperative cancellation, idempotent recovery, 3-way accounting separation (customer credits vs execution units vs provider cost INR) (`LOCAL_VERIFIED`).
4. **`docs/P8_MARKETPLACE_SECURITY_REPORT.md`**  
   *Scope:* Developer KYB profiles, PII masking, draft listing privacy, canonical manifest ECDSA NIST P-256 signing and public key pinning, install secret masking (`••••last4`), install revocation, verified reviews, third-party executable code permanently disabled (`LOCAL_VERIFIED`).
5. **`docs/POSTGRESQL_PARITY_AND_RECOVERY_REPORT.md`**  
   *Scope:* 26 linear migration revisions ending at `o5d0e1f2a3b4`, 2,280 lines offline PostgreSQL DDL compilation, migration `o5d0e1f2a3b4` data safety review, mandatory pre-upgrade marketplace orphan checks, live staging backup/restore drill blocker documentation (`LOCAL_VERIFIED` / `BLOCKED`).
6. **`docs/INFRASTRUCTURE_READINESS_AND_REGION_AUDIT.md`**  
   *Scope:* Render Singapore vs Neon US East 2 latency investigation (400.6 ms measured RTT), regional relocation alternatives, `UVICORN_WORKERS=2` memory analysis (94 MB heap + 460 MB RSS vs 512 MB Starter limit), `PAYPAL_MODE=sandbox` safety audit, `./keys` ephemeral container storage risk & persistence options (`LOCAL_VERIFIED` / `BLOCKED`).
7. **`docs/RENDER_RUNTIME_AND_HEALTHCHECK_REPORT.md`**  
   *Scope:* Root cause diagnosis of historical 35.8–36.2s `/health` timeouts (`pool_timeout=30` + `connect_timeout=5` in `get_db` vs Render 5s deadline), two-tier `/healthz` liveness vs `/health` readiness pattern, strict 2s database probe timeout recommendation (`LOCAL_VERIFIED`).
8. **`docs/NEON_CONNECTION_AND_RECOVERY_REPORT.md`**  
   *Scope:* Connection string topology (pooled `DATABASE_URL` for web traffic vs unpooled `DATABASE_URL_UNPOOLED` for migrations/DDL), `migrations/env.py` unpooled prioritization, marketplace orphan-record prechecks, physical backup/restore drill blocker documentation, strict production `neondb` protection (`LOCAL_VERIFIED` / `BLOCKED`).
9. **`docs/MASTER_ROADMAP_SCORECARD.md`**  
   *Scope:* Master release roadmap, phase-by-phase implementation status, index of all 9 audit reports, and authoritative production cutover gate status (`BLOCKED`).

---

## 3. Preserved P3.1 Production Cutover Blockers

Production release remains strictly **`BLOCKED`** (`GET /v1/cs/release-readiness` and `GET /v1/ops/roadmap-scorecard` both return `overall_release_readiness: "BLOCKED"` and `production_cutover_approved: false`) until all live external gates below are completed and verified by system owners:

1. **`POSTGRES_BACKUP_RESTORE_UNVERIFIED`** — Real PostgreSQL physical `pg_dump` and `pg_restore` drill against an isolated scratch Neon branch (`DATABASE_URL_UNPOOLED`) has not been executed (`pg_dump`/`pg_restore`/`psql` missing on the Windows dev host; staging credentials not provided; production `neondb` must never be used).
2. **`INFRASTRUCTURE_REGION_AND_MEMORY_ACTION_REQUIRED`** — Render Singapore to Neon US East 2 latency (400 ms RTT) must be resolved via regional relocation (Option A: Render to US East; Option B: Neon to Singapore), and `UVICORN_WORKERS` must be set to `1` on Starter plan to avoid 460 MB / 512 MB OOM crashes.
3. **`RENDER_HEALTHCHECK_REMEDIATION_REQUIRED`** — Healthcheck configuration must adopt lightweight process liveness (`healthCheckPath: /healthz`) or strict 2.0s DB probe timeout to guarantee response within Render's 5.0-second deadline.
4. **`SIGNING_KEY_PERSISTENCE_REQUIRED`** — Authoritative ECDSA signing keys in `./keys` must be persisted via Render persistent disk or `TRUST_ENGINE_PRIVATE_KEY_PEM` environment variable so keys survive container redeployments.
5. **`ATTRIBUTION_REQUIRES_CONNECTED_GSC`** — Google Search Console OAuth client (`GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `GSC_REDIRECT_URI`) and property attribution remain unconfigured in live Google Cloud.
6. **`RAZORPAY_LIVE_SETTLEMENT_NOT_TESTED`** — Live low-value Razorpay transaction + separate merchant UTR payout settlement requires explicit owner authorization (`SANDBOX_VERIFIED` locally; live transaction `NOT_TESTED`).
7. **`PAYPAL_LIVE_PAYOUT_NOT_TESTED`** — Live low-value PayPal order capture + separate payout settlement requires explicit owner authorization (`SANDBOX_VERIFIED` locally; live transaction `NOT_TESTED`).
8. **`RENDER_RUNTIME_NOT_LIVE_VERIFIED`** — Live `/health` verification, Render runtime log inspection, and live environment parity check against production/staging Render dashboards require owner verification.
9. **`STAGING_DEPLOYMENT_SMOKE_NOT_TESTED`** — Isolated Render staging deployment (`askforwrite-ai-company-os-staging`, `ENABLE_EXTERNAL_SIDE_EFFECTS=false`) and staging browser smoke tests remain pending.
