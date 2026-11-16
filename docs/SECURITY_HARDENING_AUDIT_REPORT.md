# AskforWrite AI Company OS — Security Hardening & Pre-Commit Verification Report

**Branch:** `fix/audit-tenant-isolation-p8-p7` (local working tree; not pushed, merged, or deployed)  
**Base Commit:** `c159655` (`feat(p8): add KYB developer marketplace, ECDSA package signing, secret isolation, revenue ledger, and P0-P8 master scorecard`)  
**Route Inventory Tracked:** [docs/route_authorization_inventory.json](route_authorization_inventory.json) (388 total APIRoutes)  
**Overall Release Readiness:** **`BLOCKED`**  
**Production Cutover Approved:** **`false`**  

---

## 1. Executive Summary

This report delivers the comprehensive security audit and pre-commit verification for AskforWrite AI Company OS on branch `fix/audit-tenant-isolation-p8-p7`. All trust boundaries, authentication flows, role-based access control (RBAC), multi-tenant route isolation, P7 autonomous execution governance, P8 marketplace isolation, and database schema parity have undergone rigorous adversarial testing and empirical verification.

Key Findings & Verification Status:
1. **Full API Route Authorization Matrix (388 Routes):** All 388 `APIRoute`s across the FastAPI gateway (387 application endpoints plus `GET /v1/ops/roadmap-scorecard`) were extracted and classified into 204 Tenant-Scoped, 123 Platform-Only, 56 Public, and 5 Optional-Auth endpoints. Exported to machine-readable format at `docs/route_authorization_inventory.json` (`LOCAL_VERIFIED`).
2. **Cross-Tenant Isolation Across 7 Critical Domains:** Strict tenant isolation was verified across Commercial, Customer Success, Field Force, Mobile Bridge, Marketplace, Billing, and Agent Execution. An initial cross-tenant auto-dispatch gap identified in Field Force was fully remediated with `403 Forbidden` checks (`LOCAL_VERIFIED`).
3. **Secret Scanning & Diff Hygiene:** Automated secret scanning across the full Git diff against base commit `c159655` and all tracked files revealed **zero exposed credentials, private keys, or tokens**. Zero existing security assertions were weakened or deleted (`LOCAL_VERIFIED`).
4. **Code Quality & Syntax Validation:** Root packaging import hygiene was resolved, achieving 0 errors on `ruff check .` across the entire repository. All dashboard JavaScript files pass `node --check` syntax validation (`LOCAL_VERIFIED`).
5. **PostgreSQL Migration & Parity:** Exactly 26 migrations compile cleanly to 2,280 lines of offline PostgreSQL DDL (`o5d0e1f2a3b4`). `migrations/env.py` prioritizes `DATABASE_URL_UNPOOLED` (`LOCAL_VERIFIED`).
6. **Release Cutover Gate:** Production release remains strictly **`BLOCKED`** pending the isolated staging Neon PostgreSQL migration and backup/restore drill. Production `neondb` remains completely untouched.

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
| **PostgreSQL Offline DDL** | `alembic upgrade head --sql` | 26 revisions ending at `o5d0e1f2a3b4`, compiling 2,280 lines of PostgreSQL transactional DDL | `LOCAL_VERIFIED` | Pass (Exit code 0) |
| **Staging Live Migration Drill** | `scripts/pg_backup_restore_drill.py` | Staging branch credentials and host binaries (`pg_dump`/`pg_restore`) unavailable | `BLOCKED` | Blocker (Documented) |

---

## 3. Route Authorization Matrix Breakdown (388 APIRoutes)

FastAPI routes are mounted in `app/main.py` via 33 included subrouters and 48 top-level routes:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   TOTAL APIRoutes: 388 Endpoints                       │
├───────────────────┬───────────────────┬────────────────┬───────────────┤
│   TENANT-SCOPED   │   PLATFORM-ONLY   │     PUBLIC     │ OPTIONAL-AUTH │
│    204 Routes     │    123 Routes     │   56 Routes    │   5 Routes    │
│      (52.6%)      │      (31.7%)      │    (14.4%)     │    (1.3%)     │
└───────────────────┴───────────────────┴────────────────┴───────────────┘
```

### 3.1 Categorization Rules & Dependencies
1. **`TENANT_SCOPED` (204 routes):**
   - Protected by `require_tenant_admin`, `require_tenant_manager`, `require_tenant_operator`, `require_field_member`, `get_mobile_user`, `require_subscription_owner`.
   - Requires valid Bearer JWT. Enforces `enforce_tenant_access(principal, target_org_id)`. Cross-tenant calls return `403 Forbidden` or `404 Not Found`. Customer role calling staff/field endpoints returns `403`. Inactive user or organization fails closed (`401`/`403`).
2. **`PLATFORM_ONLY` (123 routes):**
   - Protected by `require_owner` or `require_manager`. Requires platform operator API key (`OWNER_API_KEY` / `MANAGER_API_KEY`).
   - Tenant tokens (including Tenant Admins) calling platform endpoints return `403 Forbidden` because `principal.is_platform_operator` is `False`. Anonymous calls return `401 Unauthorized`.
3. **`PUBLIC` (56 routes):**
   - Public status endpoints (`/health`, `/robots.txt`, `/sitemap.xml`, `/llms.txt`).
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
| R1 Route Authorization Matrix | 388 routes audited and cataloged in `docs/route_authorization_inventory.json` | `LOCAL_VERIFIED` |
| R1 Cross-Tenant Isolation | 7 critical domains verified; 0 cross-tenant leakages | `LOCAL_VERIFIED` |
| R1 Secret Hygiene | 0 secrets in git diff or tracked files | `LOCAL_VERIFIED` |
| R2 P7 Autonomy Governance | DAG validation, blocking timeouts, 3-way accounting verified | `LOCAL_VERIFIED` |
| R2 P8 Marketplace Security | ECDSA signing, secret masking, plugins disabled | `LOCAL_VERIFIED` |
| R3 PostgreSQL Offline DDL | 26 revisions compile to 2,280 lines DDL; unpooled URL prioritized | `LOCAL_VERIFIED` |
| R3 PostgreSQL Staging Drill | Live migration and physical backup/restore drill | **`BLOCKED`** |
| R4 Render Readiness | Regional latency, worker memory, and health check diagnosed | `LOCAL_VERIFIED` |
| R5 Test Suite | 770/770 tests pass (766 unit + 4 browser E2E) | `LOCAL_VERIFIED` |
| **Final Release Cutover Status** | **BLOCKED (Production Cutover Approved: false)** | **`BLOCKED`** |
