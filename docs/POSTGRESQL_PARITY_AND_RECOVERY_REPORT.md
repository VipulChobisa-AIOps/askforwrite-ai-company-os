# AskforWrite AI Company OS — PostgreSQL Schema Parity, Migration Safety & Recovery Report

**Branch:** `fix/infra-remediation-from-11b466e` (based on `11b466e`)
**Execution Context:** PostgreSQL 18 Schema Parity & Physical Backup/Restore Verification
**Verification Date:** 2026-11-16
**Alembic Head Revision:** `o5d0e1f2a3b4` (`26` total migrations verified offline and live on staging Neon)
**Drill Test Suite:** `tests/test_p3_1_postgres_drill.py` (`5 passed`)
**Staging Recovery Status:** **`STAGING_VERIFIED`** (on isolated Neon project `twilight-resonance-00131838`, `afw_staging` -> `afw_restore_drill`)
**Production Database Safety:** **PROTECTED (`neondb` untouched; `production_cutover_approved: false`)**

---

## 1. Executive Summary

- **Single Alembic Head & Offline DDL (`LOCAL_VERIFIED`):** All `26` linear revisions compile cleanly to PostgreSQL DDL at single head `o5d0e1f2a3b4` (`alembic upgrade head --sql`, `0` errors).
- **Live Isolated Neon Staging Migrations (`STAGING_VERIFIED`):** Installed PostgreSQL `18.7` client tools (`psql`, `pg_dump`, `pg_restore`) locally, created isolated Neon project `twilight-resonance-00131838` (`afw_staging`, PG `18`), verified database identity (`afw_staging`), executed all **26 Alembic migrations** from empty schema using `DATABASE_URL_UNPOOLED`, and passed marketplace orphan prechecks (`0|0|0`).
- **Physical Backup & Restore Parity (`STAGING_VERIFIED`):** Executed `scripts/pg_backup_restore_drill.py --confirm-isolated-branch --jobs 8` from `afw_staging` to `afw_restore_drill` (`261,595` byte custom dump in `57.56s`; `pg_restore --jobs=8` in `251.99s`; total RTO `289.83s`), verifying `100%` parity across all `82` tables, `394` indexes, `11` foreign keys, `39` core table row counts, tenant isolation, `TrustBlock` chain validity (`3` blocks), P8 ECDSA signature validity, and `/healthz` (`200`), `/readyz` (`200`), `/health` (`200`).
- **Production `neondb` Protection (`LIVE_VERIFIED` untouched):** Zero reads, writes, or migrations ran against production `hidden-salad-98219484` / `neondb`.

---

## 2. Migration `o5d0e1f2a3b4` Safety & Constraint Audit

Verified both in offline DDL and live in `pg_constraint` on Neon `afw_restore_drill`:

| Constraint Name | Table | Action | Safety Assessment |
| :--- | :--- | :--- | :--- |
| `fk_tenant_invitations_org_id` | `tenant_invitations` | `CASCADE` (`c`) | Deletes org invitations only when parent org is removed |
| `fk_tenant_invitations_invited_by_user_id` | `tenant_invitations` | `SET NULL` (`n`) | Preserves invitation audit history if inviter removed |
| `fk_p4_campaigns_icp_id`, `fk_p4_deals_*`, `fk_p4_intel_icp_id` (`5` FKs) | `p4_*` | `SET NULL` (`n`) | Paired with `_cleanup_nullable_p4_orphans()` (nullifies dangling FK fields only; zero row deletion) |
| `fk_p8_listings_developer_id` | `p8_marketplace_listings` | `RESTRICT` (`r`) | Blocks deleting developers with active listings; precheck returns `0` |
| `fk_p8_installs_listing_id` | `p8_tenant_installs` | `RESTRICT` (`r`) | Blocks deleting listings with tenant installs; precheck returns `0` |
| `fk_p8_reviews_listing_id`, `fk_p8_reviews_install_id` | `p8_marketplace_reviews` | `CASCADE` (`c`) | Cleans reviews tied to deleted listing/install; precheck returns `0` |

---

## 3. Drill Tool Hardening (`scripts/pg_backup_restore_drill.py`)

- Added `DRILL_SOURCE_URL` / `DRILL_TARGET_URL` environment variable support and `DATABASE_URL_UNPOOLED` lookup priority so credentials never appear in CLI arguments.
- Upgraded `inspect_database_state()` to query core table row counts in one `UNION ALL` round trip plus PostgreSQL index/foreign-key counts (`table_count`, `index_count`, `foreign_key_count`).
- Added `--jobs` (`default=8`) parallel restore and `600s` dump/restore timeouts after empirical discovery that single-transaction/sequential restore across WAN RTT hits Neon's 5.5m connection limit.
- Updated `verify_app_health_against_target()` to run FastAPI `lifespan()` warmup cleanly (`AFW_SKIP_WORKER_DDL=1`) and validate `/healthz`, `/readyz`, and `/health` (`"healthy"`/`"ok"`).

*(Full step-by-step staging outputs and runbook are recorded in [`NEON_CONNECTION_AND_RECOVERY_REPORT.md`](./NEON_CONNECTION_AND_RECOVERY_REPORT.md).)*
