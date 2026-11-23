# AskforWrite AI Company OS — Security Hardening & Pre-Commit Verification Report

**Branch:** `fix/infra-remediation-from-11b466e` (branched cleanly over preserved checkpoint `11b466e` on `fix/audit-tenant-isolation-p8-p7`)
**Base Commit:** `c159655` -> Checkpoint `11b466e` (preserved)
**Route Inventory Tracked:** [docs/route_authorization_inventory.json](route_authorization_inventory.json) (390 total APIRoutes: +`/healthz`, +`/readyz`)
**Overall Release Readiness:** **`BLOCKED`**
**Production Cutover Approved:** **`false`**

> **Canonical Reconciliation Addendum (2026-11-23 — Audit against `main`):**
> - **Credential Exposure Correction:** The historical diff scan below (Section 1 item 3 / Section 5.1) missed literal `OWNER_API_KEY` and `MANAGER_API_KEY` values that were already present in `render.yaml` (both production and staging blocks). Both literals have now been replaced with `sync: false` in `render.yaml`. Those previously committed values **must be treated as compromised**, revoked and rotated in Render Dashboard, and checked against access logs before production cutover.
> - **P0 Code Remediations Applied on `main`:** Issue #12 (WordPress fail-closed HITL approval + distinct `PUBLISHED`/`SIMULATED`/`PUBLISH_FAILED` states + idempotent reconciliation), Issue #14 (Field Force `delivery_field_force` entitlement + tenant scope + canonical `principal.user_id` ownership on every route), Issue #15 (provisioning fail-closed with zero `company_os_starter` fallbacks across DirectPay/Razorpay/PayPal), Issue #13 (minor-unit refund regression coverage), and Bandit `B104`/`B310` remediation (`0` Medium/High findings).
> - **Database Status Alignment:** Both isolated Neon staging (`afw_staging` -> `afw_restore_drill`) AND read-only production Neon `neondb` (`ep-fragrant-sun-b4pkm5df.c-6.us-east-2.aws.neon.tech/neondb` -> isolated local PostgreSQL 18.7 `127.0.0.1:55432/askforwrite_prod_restore_drill`) have passed **`LIVE_VERIFIED`** backup/restore parity (`2026-11-23T14:29:04Z`: `82` tables, `405` indexes, `11` FKs, `alembic_version=p6e1f2a3b4c5`, `5` orgs / `5` users, `dump_bytes=406,329`, drill `dump_sha256=a8c7ef74f0fb68b8b75db5f61636210a4e67cc58284fa50f54a21b7280ccf9dc`, archived git-ignored backup `backups/prod_neondb_verified_20261123.dump` `sha256=93b539aa503aa44a70551bc250b94afd55439af9dbcb5fc86143a14e9f295fe9`, `dump_seconds=91.64s`, `restore_seconds=2.99s`, `rto_seconds=24.73s`, `mismatches=[]`, FastAPI `/healthz`/`/readyz`/`/health` = `200`).
> - **Hardcoded Auth Backdoor Eliminated & Web3 Gated:** Hardcoded legacy `sovereign_authorities` keys were deleted from `app/security/auth.py` (covered by permanent `401` regression tests) and `ENABLE_WEB3_STABLECOIN_RAIL=false` fails closed in production pending CA/FEMA/GST/VDA review.
> - **Release Cutover Status:** Remains **`BLOCKED`** (`production_cutover_approved: false`) until Render Dashboard secret rotation (`OWNER_API_KEY`, `MANAGER_API_KEY`, `TRUST_ENGINE_PRIVATE_KEY_PEM`), live staging deployment & health/RBAC/E2E verification, and real-money `₹1` settlement + first paying `₹4,999` customer acceptance (Issue #25) complete.

---

## 1. Executive Summary

This report delivers the comprehensive security audit and verification for AskforWrite AI Company OS across preserved security checkpoint `11b466e` (`fix/audit-tenant-isolation-p8-p7`) and infrastructure remediation branch `fix/infra-remediation-from-11b466e`. All trust boundaries, authentication flows, role-based access control (RBAC), multi-tenant route isolation, P7 autonomous execution governance, P8 marketplace isolation, infrastructure health probes, and Neon staging database recovery have undergone rigorous adversarial testing and empirical verification.

Key Findings & Verification Status:
1. **Full API Route Authorization Matrix (390 Routes):** All 390 `APIRoute`s across the FastAPI gateway (including `GET /v1/ops/roadmap-scorecard`, `GET /healthz`, and `GET /readyz`) were extracted and classified into 204 Tenant-Scoped, 123 Platform-Only, 58 Public, and 5 Optional-Auth endpoints. Exported to machine-readable format at `docs/route_authorization_inventory.json` (`LOCAL_VERIFIED`).
2. **Cross-Tenant Isolation Across 7 Critical Domains:** Strict tenant isolation was verified across Commercial, Customer Success, Field Force, Mobile Bridge, Marketplace, Billing, and Agent Execution. An initial cross-tenant auto-dispatch gap identified in Field Force was fully remediated with `403 Forbidden` checks (`LOCAL_VERIFIED`).
3. **Secret Scanning & Diff Hygiene:** Automated secret scanning across the full Git diff against base commit `c159655` and all tracked files revealed **zero exposed credentials, private keys, or tokens**. Zero existing security assertions were weakened or deleted (`LOCAL_VERIFIED`).
4. **Code Quality & Syntax Validation:** Root packaging import hygiene was resolved, achieving 0 errors on `ruff check .` across the entire repository. All dashboard JavaScript files pass `node --check` syntax validation (`LOCAL_VERIFIED`).
5. **PostgreSQL Migration & Staging Recovery (`STAGING_VERIFIED`):** Installed PostgreSQL `18.7` CLI binaries locally, provisioned isolated Neon project `twilight-resonance-00131838` (`afw_staging` -> `afw_restore_drill`), executed all `26` migrations (`o5d0e1f2a3b4`), verified `0|0|0` marketplace orphans, and passed parallel `pg_dump` / `pg_restore` parity verification (`82` tables, `394` indexes, `11` FKs, tenant isolation). Production `neondb` remains untouched.
6. **Infra Remediation Verified (`LOCAL_VERIFIED`):** Implemented `/healthz`, bounded `/readyz` & `/health`, middleware health bypass, durable ECDSA env/rotation (`app/security/ecdsa_pki.py`), and PayPal fail-safe `"sandbox"` mode reconciliation (`tests/test_infra_remediation_readiness.py`).
7. **Release Cutover Gate:** Production cutover remains **`BLOCKED`** (`production_cutover_approved: false`) pending Render staging deploy/smoke, GSC OAuth, and owner-authorized live payment settlement verification.

---

## 2. Hardening Domains & Verification Evidence

| Domain | Key Verification Artifact | Coverage Summary | Verification Tag | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Route Authorization Matrix** | `tests/test_security_hardening_route_matrix.py` | 240 parameterized cases across platform-only, tenant-manager, field-force, mobile, customer-portal, P4-P8, registry optional auth, and public routes | `LOCAL_VERIFIED` | Pass (240 passed) |
| **Auth & Invitation Lifecycle** | `tests/test_security_hardening_auth_roles.py` | 7 tests covering public signup rules, first-owner bootstrap, invitation expiry (`410`), wrong email (`403`), approval replay (`409`), inactive fail-closed | `LOCAL_VERIFIED` | Pass (7 passed) |
| **P7 Autonomy Governance** | `tests/test_security_hardening_p7_autonomy.py` | 6 tests covering Kahn DAG validation, genuine blocking timeout, `/cancel`, `/recover`, partial persistence, concurrency limits, cost provenance | `LOCAL_VERIFIED` | Pass (6 passed) |
| **P8 Marketplace Security** | `tests/test_security_hardening_p8_marketplace.py` | 3 tests covering developer ownership, PII redaction, ECDSA NIST P-256 signature pinning, install secret masking (`••••last4`), review privacy | `LOCAL_VERIFIED` | Pass (3 passed) |
| **Cross-Record FK Integrity** | `tests/test_security_hardening_cross_record_fk.py` | 4 tests verifying P4/P8 foreign key constraints, `ON DELETE RESTRICT` and `CASCADE` behaviors, cross-tenant rejection | `LOCAL_VERIFIED` | Pass (4 passed) |
| **Field Force Multi-Tenancy** | `tests/test_field_*.py` (4 suites) | 18 tests covering task auto-dispatch, geofence verification, visit verification, voice debrief, conveyance claims | `LOCAL_VERIFIED` | Pass (18 passed) |
| **Mobile Bridge Security** | `tests/test_mobile_and_security.py` | 12 tests verifying mobile user authentication, token expiry, active org check, customer role rejection (`403`) | `LOCAL_VERIFIED` | Pass (12 passed) |
| **PostgreSQL Offline DDL** | `alembic upgrade head --sql` | 26 revisions ending at `o5d0e1f2a3b4`, PostgreSQL transactional DDL | `LOCAL_VERIFIED` | Pass (Exit code 0) |
| **Staging Live Migration & Recovery Drill** | `scripts/pg_backup_restore_drill.py` + Neon `afw_staging` | 26 migrations, `0|0|0` orphans, `pg_dump`/`pg_restore --jobs=8`, `82` tables / `394` indexes / `11` FKs parity, tenant isolation, `/healthz` `/readyz` `/health` = `200` | `STAGING_VERIFIED` | Pass (`restore_tested: true`) |
| **Infra Health, ECDSA Rotation & PayPal** | `tests/test_infra_remediation_readiness.py` | `/healthz`, blackhole PG timeout `<3s`, env + rotated keys, PayPal fail-safe `"sandbox"`, `render.yaml` staging 1-worker | `LOCAL_VERIFIED` | Pass |

---

### 3. Route Authorization Matrix Breakdown (390 APIRoutes)

FastAPI routes are mounted in `app/main.py` via 33 included subrouters and top-level routes (`+ /healthz`, `+ /readyz` -> `58` public routes, `390` total):

```
┌────────────────────────────────────────────────────────────────────────┐
│                   TOTAL APIRoutes: 390 Endpoints                       │
├───────────────────┬───────────────────┬────────────────┬───────────────┤
│   TENANT-SCOPED   │   PLATFORM-ONLY   │     PUBLIC     │ OPTIONAL-AUTH │
│    204 Routes     │    123 Routes     │   58 Routes    │   5 Routes    │
│      (52.3%)      │      (31.5%)      │    (14.9%)     │    (1.3%)     │
└───────────────────┴───────────────────┴────────────────┴───────────────┘
```

### 3.1 Categorization Rules & Dependencies
1. **`TENANT_SCOPED` (204 routes):**
   - Protected by `require_tenant_admin`, `require_tenant_manager`, `require_tenant_operator`, `require_field_member`, `get_mobile_user`, `require_subscription_owner`.
   - Requires valid Bearer JWT. Enforces `enforce_tenant_access(principal, target_org_id)`. Cross-tenant calls return `403 Forbidden` or `404 Not Found`. Customer role calling staff/field endpoints returns `403`. Inactive user or organization fails closed (`401`/`403`).
2. **`PLATFORM_ONLY` (123 routes):**
   - Protected by `require_owner` or `require_manager`. Requires platform operator API key (`OWNER_API_KEY` / `MANAGER_API_KEY`).
   - Tenant tokens (including Tenant Admins) calling platform endpoints return `403 Forbidden` because `principal.is_platform_operator` is `False`. Anonymous calls return `401 Unauthorized`.
3. **`PUBLIC` (58 routes):**
   - Public liveness, readiness, and status endpoints (`/healthz`, `/readyz`, `/health`, `/robots.txt`, `/sitemap.xml`, `/llms.txt`).
   - Public auth endpoints (`/v1/auth/login`, `/v1/auth/register`, `/v1/auth/signup`, `/v1/auth/invitations/accept`).
   - Cryptographic token-protected routes (`/v1/outreach/unsubscribe` with HMAC, `/v1/webhooks/payment` with signature, `/v1/previews/{token}`).
   - Sovereign DirectPay public checkout sessions and MSME statutory legal disclosures.
4. **`OPTIONAL_AUTH` (5 routes):**
   - Catalog discovery (`/v1/registry/services`, `/v1/registry/agents`, etc.).
   - Uses `get_optional_principal`. Anonymous requests view public specifications. If an `Authorization` header is passed, the token is strictly validated; expired, revoked, or inactive tokens fail closed with `401` or `403`.

---

## 4. Multi-Tenant Cross-Domain Isolation Verification

Verification confirmed strict isolation across the 7 critical operational domains:

1. **Commercial Revenue Engine (25 routes):** All 25 routes are platform-only. Tenant tokens return `403 Forbidden`.
2. **Customer Success Engine (55 routes):** 30 routes are platform-only (`403` for tenants); 25 routes are tenant-scoped, filtering queries by `principal.org_id` and requiring tenant manager/admin role.
3. **Field Force Engine (15 routes):** Requires `require_field_member` or `require_tenant_manager`. Remediated auto-dispatch, geofence, and visit verification to enforce `org_id` ownership and reject cross-org `user_id` inputs with `403`. Customer role rejected with `403`.
4. **Mobile Bridge (7 routes):** Requires `get_mobile_user`. Authenticates against DB `UserRecord`, enforces `user.org_id == payload['org_id']`, rejects `customer` role with `403`, and scopes tasks/conveyance to `user.org_id`.
5. **Marketplace Ecosystem (16 routes):** Listings, installs, and reviews enforce developer and tenant ownership. Draft listings are inaccessible cross-tenant (`403`/`404`). Secrets stored during install are masked in API responses (`••••last4`) and never expose raw values or full digests. Third-party executable plugins remain permanently disabled.
6. **Billing & Subscriptions (6 routes):** Subscriptions enforce `require_subscription_owner`. Account credit topup/consumption enforces `require_tenant_admin` + `enforce_tenant_access`. Customer credits and provider expenditures are maintained on separate ledgers and never commingled.
7. **Agent Execution (Workflows & P7 Autonomy):** Agent runs and workflow definitions require `require_tenant_operator` and are strictly scoped to `principal.org_id`. P7 autonomy policies, DAG plans, and memories are isolated by `org_id`. Memory purge fail-closed scopes strictly to `principal.org_id` (`purged_count == 0` if attempting to purge another tenant's memory).

---

## 5. Secret Scanning & Git Diff Audit

### 5.1 Secret Scanning
An automated regex scan across the full diff against base commit `c159655` and all tracked repository files verified:
- RSA / EC / DSA / OpenSSH private keys: **0 matches**
- Google / Gemini API keys (`AIza*`): **0 matches**
- Razorpay live keys (`rzp_live_*`): **0 matches**
- GitHub tokens (`ghp_*`): **0 matches**
- Neon API tokens (`neon_*`): **0 matches**
- AWS access keys (`AKIA*`): **0 matches**
- `.gitignore` explicitly excludes `.env`, `.env.production`, `.sovereign_wallets.json`, `keys/`, `*.pem`, `*.key`. None of these files are tracked or staged.

### 5.2 Test Diff Integrity Audit
Inspected `git diff c159655 -- tests/` across all 18 modified test files:
- All changes strictly strengthened security assertions:
  * Public registration tests assert `403 Forbidden` for privileged roles.
  * Insecure `"owner"` or global `"admin"` roles on tenant test users were replaced with scoped `"tenant_admin"`.
  * `test_p3_1_postgres_drill.py` hardened target validation requiring approved staging host and database name, blocking accidental production targeting.
  * `PGPASSWORD` hygiene verified to prevent credentials leaking into subprocess command lines or logs.
- **Verdict:** Zero security assertions were weakened or deleted relative to base commit `c159655`.

---

## 6. Static Analysis & Linter Verification

1. **Ruff Linting:**
   - Fixed 4 unused import errors in root scripts (`desktop_app.py`, `package_desktop_app.py`, `run_server.py`).
   - Ran `ruff check .` across the entire repository: **All checks passed (0 errors)** (`LOCAL_VERIFIED`).
2. **JavaScript Syntax Validation:**
   - `node --check app/dashboard/dashboard.js` -> Exit code 0 (`LOCAL_VERIFIED`)
   - `node --check app/dashboard/sw.js` -> Exit code 0 (`LOCAL_VERIFIED`)
   - `node --check app/dashboard/widget.js` -> Exit code 0 (`LOCAL_VERIFIED`)

---

## 7. Release Cutover Gate Decision

| Release Requirement | Verification Result | Gate Status |
| :--- | :--- | :--- |
| R1 Route Authorization Matrix | 390 routes audited and cataloged in `docs/route_authorization_inventory.json` | `LOCAL_VERIFIED` |
| R1 Cross-Tenant Isolation | 7 critical domains verified; 0 cross-tenant leakages | `LOCAL_VERIFIED` |
| R1 Secret Hygiene | 0 secrets in git diff or tracked files | `LOCAL_VERIFIED` |
| R2 P7 Autonomy Governance | DAG validation, blocking timeouts, 3-way accounting verified | `LOCAL_VERIFIED` |
| R2 P8 Marketplace Security | ECDSA signing, durable env/rotation, secret masking, plugins disabled | `LOCAL_VERIFIED` |
| R3 PostgreSQL Live Staging Drill | 26 migrations (`o5d0e1f2a3b4`) + `pg_dump`/`pg_restore` parity on Neon `twilight-resonance-00131838` (`neondb` untouched) | **`STAGING_VERIFIED`** |
| R4 Render & Infra Remediation | `/healthz`, bounded `/readyz`/`/health`, ECDSA rotation, PayPal reconciliation, staging 1-worker & region benchmarks | `LOCAL_VERIFIED` (`BLOCKED` on live Render) |
| R5 Test Suite | Full pytest + Playwright browser E2E verification on `fix/infra-remediation-from-11b466e` | Verified Clean |
| **Final Release Cutover Status** | **BLOCKED (Production Cutover Approved: false)** | **`BLOCKED`** |
