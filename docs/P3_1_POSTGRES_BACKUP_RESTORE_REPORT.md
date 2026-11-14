# P3.1 PostgreSQL Backup & Restore Verification Report

**Drill Tool:** `scripts/pg_backup_restore_drill.py`  
**Drill Test Suite:** `tests/test_p3_1_postgres_drill.py` (`5/5` local harness tests passed)  
**Production Database Drill State:** **`BLOCKED`** (`restore_tested: false`)  
**Drill Harness Unit State:** **`LOCAL_VERIFIED`**

---

## 1. Configured Production Database Inspection (Redacted)

Running `python scripts/pg_backup_restore_drill.py --check-only --json` (read-only preflight, zero DB mutations) inspected `.env:DATABASE_URL`:

```json
{
  "verification_status": "BLOCKED",
  "restore_tested": false,
  "source_origin": ".env:DATABASE_URL",
  "source_db": {
    "configured": true,
    "scheme": "postgresql",
    "host": "ep-fragrant-sun-b4pkm5df-pooler.c-6.us-east-2.aws.neon.tech",
    "port": null,
    "database": "neondb",
    "masked_url": "postgresql://***:***@ep-fragrant-sun-b4pkm5df-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=***"
  },
  "binaries": {
    "pg_dump": null,
    "pg_restore": null,
    "psql": null
  },
  "blockers": [
    "Missing PostgreSQL client binaries on PATH: pg_dump, pg_restore."
  ]
}
```

No database usernames, passwords, tokens, or connection query parameters are ever printed or persisted.

---

## 2. Implemented Safety Guards & Verification Scope

`scripts/pg_backup_restore_drill.py` enforces strict non-destructive safeguards:
1. **`mask_database_url`:** Redacts userinfo (`***:***`) and query parameters (`?sslmode=***`) on all outputs and records.
2. **`validate_target_isolation`:** Raises `DrillSafetyError` if `--target-url` matches `--source-url`, shares the same host/database, or points to a managed production host (`neon.tech`, `render.com`, `askforwrite.com`, `rds.amazonaws.com`) without `--confirm-isolated-branch` AND a distinct database name.
3. **End-to-End Restore Verification Pipeline (when PostgreSQL binaries & isolated target exist):**
   - Executes `pg_dump --format=custom --no-owner --no-privileges` into a temporary file and computes SHA-256 checksum + byte size.
   - Executes `pg_restore` against the isolated target PostgreSQL database.
   - Compares `alembic_version`, table count, `distinct_organizations`, and core row counts across verified `models.py` tables (`alembic_version`, `organizations`, `customer_records`, `subscription_records`, `invoice_records`, `workflow_definitions`, `connector_states`, `p2_customer_engagements`, `p3_customer_accounts`, `p3_onboarding_workflows`, `p3_service_deliveries`, `p3_support_tickets`).
   - Optionally runs a FastAPI `/health` check bound to the restored target URL (`verify_app_health_against_target`) and computes measured RTO/RPO, optionally posting non-secret evidence to `POST /v1/cs/ops/backup-drill`.

---

## 3. Drill Test Suite (`tests/test_p3_1_postgres_drill.py`)

Verified locally with synthetic inputs and mocked binaries (`5/5` passed):
- `test_mask_database_url_redacts_credentials_and_query_params`
- `test_validate_target_isolation_blocks_same_or_production_targets`
- `test_compare_source_and_target_parity_checks`
- `test_run_preflight_reports_blocked_when_pg_binaries_missing`
- `test_execute_drill_with_mocked_binaries_and_inspected_states`

---

## 4. Exact Production Blocker & Operator Recovery Command

A live dump + restore of Neon PostgreSQL (`neondb`) could **not** execute on this Windows host because PostgreSQL client tools (`pg_dump`, `pg_restore`, `psql`) are not installed on `PATH` (and Docker/WSL Linux runtimes are unavailable here).

Once run from an environment with PostgreSQL 16+ client binaries (`pg_dump` / `pg_restore`) and an isolated local or Neon scratch target database:

```bash
python scripts/pg_backup_restore_drill.py \
  --source-url "$DATABASE_URL_UNPOOLED" \
  --target-url "postgresql://postgres:postgres@127.0.0.1:5432/askforwrite_drill_restore" \
  --json
```
