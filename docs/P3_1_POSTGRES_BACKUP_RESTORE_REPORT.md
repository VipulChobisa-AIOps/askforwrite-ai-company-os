# P3.1 PostgreSQL Backup & Restore Verification Report

**Drill Tool:** `scripts/pg_backup_restore_drill.py`
**Drill Test Suite:** `tests/test_p3_1_postgres_drill.py` (`5/5` unit harness tests passed, `LOCAL_VERIFIED`)
**Staging PostgreSQL Drill State:** **`STAGING_VERIFIED`** (`restore_tested: true`, `parity_verified: true` on isolated Neon PG 18 project `twilight-resonance-00131838`)
**Production Database Safety:** **UNTOUCHED** (`neondb` on `hidden-salad-98219484` never targeted)

---

## 1. Local Tooling & Isolated Staging Target

- **Installed Local Client Binaries:** `psql (PostgreSQL) 18.7`, `pg_dump (PostgreSQL) 18.7`, `pg_restore (PostgreSQL) 18.7` (`C:\Users\vipul\tools\pgsql\bin`).
- **Isolated Neon Project:** `twilight-resonance-00131838` (`aws-us-east-2`), with source `afw_staging` (`o5d0e1f2a3b4`, seeded multi-tenant data + `TrustBlock` + P8 signed listing) and restore target `afw_restore_drill`.

---

## 2. Verified Live Staging Drill Output (Redacted)

Executed `scripts/pg_backup_restore_drill.py --confirm-isolated-branch --approved-staging-host ep-green-base-be5j3cxl.c-9.us-east-2.aws.neon.tech --approved-staging-db afw_restore_drill --jobs 8 --json` with `DRILL_SOURCE_URL` / `DRILL_TARGET_URL` env vars (exit code `0`):

- **`restore_tested`:** `true`
- **`dump_bytes` / `dump_sha256`:** `261595` bytes (`054d58e76907541cfc33de1b4ec610ca7eb1072ab2f31010871855a49f6c0118`)
- **`dump_seconds` / `restore_seconds` / `rto_seconds`:** `57.556 s` / `251.986 s` / `289.828 s`
- **`parity` (`afw_staging` vs `afw_restore_drill`):**
  - `table_count`: `82 == 82`
  - `index_count`: `394 == 394`
  - `foreign_key_count`: `11 == 11`
  - `alembic_version`: `"o5d0e1f2a3b4" == "o5d0e1f2a3b4"`
  - `distinct_organizations`: `2 == 2` (`mismatches: []`)
- **Target App Probes (`afw_restore_drill`):** `/healthz` = `200`, `/readyz` = `200`, `/health` = `200` (`"status": "healthy"`, `"database": "connected"`).
- **Post-Restore Integrity (`afw_restore_drill`):** `org_stage_a` (`1` lead) vs `org_stage_b` (`1` lead) isolated cleanly; `TrustChain` (`3` blocks, `chain_valid: true`); P8 ECDSA listing signature `verified: true`.

---

## 3. Production Cutover Note

Production cutover (`production_cutover_approved`) remains `false` until live Render staging deployment, Google Search Console OAuth, and owner-authorized live payment settlement verification complete.
