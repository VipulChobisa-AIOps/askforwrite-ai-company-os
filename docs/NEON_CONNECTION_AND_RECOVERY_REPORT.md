# AskforWrite AI Company OS — Neon PostgreSQL Connection, Migration & Recovery Report

**Branch:** `fix/infra-remediation-from-11b466e` (based on `11b466e`)
**Execution Context:** Live Isolated Neon PostgreSQL 18 Migration & Physical Recovery Drill
**Verification Date:** 2026-11-16
**Alembic Head Revision:** `o5d0e1f2a3b4` (`26` revisions verified end-to-end on Neon Postgres 18)
**Staging Recovery Drill Status:** **`STAGING_VERIFIED`** (PostgreSQL `18.7` binaries + Neon `twilight-resonance-00131838`)
**Production Database Safety:** **PROTECTED (`neondb` on `hidden-salad-98219484` untouched)**

---

## 1. Isolated Neon Staging & PostgreSQL 18 Tooling Provisioned

- **PostgreSQL Client Binaries Installed (`LOCAL_VERIFIED`):** Installed official PostgreSQL `18.7` CLI binaries (`psql`, `pg_dump`, `pg_restore`) matching Neon server version `18` at `C:\Users\vipul\tools\pgsql\bin` (configured on User `PATH`).
- **Isolated Staging Project Provisioned (`STAGING_VERIFIED`):** Created dedicated Neon project `twilight-resonance-00131838` (`afw-staging-infra-gate`, branch `br-fancy-mouse-be6rkl59`, region `aws-us-east-2`, PostgreSQL `18`) with two isolated databases:
  - Source staging database: `afw_staging` (`ep-green-base-be5j3cxl.c-9.us-east-2.aws.neon.tech/afw_staging`)
  - Target restore database: `afw_restore_drill` (`ep-green-base-be5j3cxl.c-9.us-east-2.aws.neon.tech/afw_restore_drill`)
- **Identity Verification Precheck:** Verified `psql` identity query returned `afw_staging|afw_staging_owner|PostgreSQL 18.x` before running any DDL. Production `hidden-salad-98219484` / `neondb` was never connected to or modified.

---

## 2. Pooled vs Direct Connection Architecture

- **Application Web Traffic (`DATABASE_URL`):** Routes through Neon PgBouncer `-pooler` (`ep-...-pooler.c-9.us-east-2.aws.neon.tech`) for connection multiplexing.
- **Migrations, DDL & Physical Backups (`DATABASE_URL_UNPOOLED`):** Routes directly to Neon compute (`ep-....c-9.us-east-2.aws.neon.tech`), enforced in `migrations/env.py`, logged clearly in `scripts/start_production.py`, and inspected via `app/db/database.py:get_database_topology_summary()`.
- **Drill Credential Hygiene:** `scripts/pg_backup_restore_drill.py` supports `DRILL_SOURCE_URL` and `DRILL_TARGET_URL` environment variables so database passwords never appear in CLI arguments or process exceptions, while stripping passwords into `PGPASSWORD` before invoking `pg_dump`/`pg_restore`.

---

## 3. Live 26-Migration Execution & Marketplace Prechecks (`STAGING_VERIFIED`)

1. Executed `alembic upgrade head` against empty `afw_staging` using `DATABASE_URL_UNPOOLED`:
   - Applied all **26 linear revisions** from empty schema cleanly through `o5d0e1f2a3b4 (head)`.
2. Verified `alembic current` == `o5d0e1f2a3b4 (head)`.
3. Executed marketplace orphan precheck SQL queries via `psql`:
   - `orphan_listings = 0`, `orphan_installs = 0`, `orphan_reviews = 0` (`0|0|0`).
4. Seeded representative multi-tenant organizations (`org_stage_a`, `org_stage_b`), users, leads, TrustChain genesis + sealed blocks (`3` blocks total), and an ECDSA-signed P8 marketplace listing, confirming FastAPI `/healthz` (`200`), `/readyz` (`200`), and `/health` (`200`) against Neon `afw_staging`.

---

## 4. Physical `pg_dump` / `pg_restore` Drill Results (`STAGING_VERIFIED`)

During testing against Neon US East 2 across WAN latency, single-transaction restore (`pg_restore -1`) encountered a `330.25s` Neon proxy/idle disconnect mid-index creation. Upgrading `scripts/pg_backup_restore_drill.py` to support parallel `pg_restore --jobs=8` (`timeout=600`) and single-RTT `UNION ALL` table/index/FK inspection resolved the bottleneck cleanly:

- **Command Executed:** `scripts/pg_backup_restore_drill.py --confirm-isolated-branch --approved-staging-host ep-green-base-be5j3cxl.c-9.us-east-2.aws.neon.tech --approved-staging-db afw_restore_drill --jobs 8 --json` (using `DRILL_SOURCE_URL` / `DRILL_TARGET_URL`)
- **Dump Size & Integrity:** `261,595` bytes (`sha256`: `054d58e76907541cfc33de1b4ec610ca7eb1072ab2f31010871855a49f6c0118`) in **`57.556 s`**
- **Parallel Restore (`--jobs=8`):** **`251.986 s`** (RTO total **`289.828 s`**, exit code `0`, `restore_tested: true`)
- **Catalog & Data Parity (`afw_staging` vs `afw_restore_drill`):**
  - Tables: `82 == 82`
  - Indexes: `394 == 394`
  - Foreign Keys: `11 == 11` (`RESTRICT` on `fk_p8_listings_developer_id` and `fk_p8_installs_listing_id`; `CASCADE` on `fk_p8_reviews_*` and `fk_tenant_invitations_org_id`; `SET NULL` on `p4_*` & `invited_by_user_id`)
  - Alembic Version: `o5d0e1f2a3b4 == o5d0e1f2a3b4`
  - All `39` core table row counts matched (`"parity_verified": true`, `"mismatches": []`)
- **Post-Restore Functional & Tenant Isolation Verification:**
  - Verified `org_stage_a` (`1` lead) and `org_stage_b` (`1` lead) isolation directly on restored `afw_restore_drill`.
  - Verified `TrustChain` (`3` blocks, `chain_valid: true`) and P8 ECDSA signature (`verified: true`) on `afw_restore_drill`.
  - Verified FastAPI startup + `/healthz` (`200`), `/readyz` (`200`), `/health` (`200`, `1,629.28 ms` cross-region probe) against `afw_restore_drill`.

---

## 5. Remaining Scope for Production Cutover

- Staging migration parity and physical backup/restore are now **`STAGING_VERIFIED`** on isolated Neon PostgreSQL 18 (`twilight-resonance-00131838`).
- Production `neondb` (`hidden-salad-98219484`) remains strictly untouched until the owner authorizes production deployment and completes Render/GSC/payment gates (`production_cutover_approved: false`).
