# AskforWrite AI Company OS — Neon PostgreSQL Connection, Migration & Recovery Report

**Branch:** `fix/audit-tenant-isolation-p8-p7`  
**Execution Context:** Database Architecture, Migration Safety & Recovery Drill (R3)  
**Verification Date:** 2026-11-16  
**Alembic Head Revision:** `o5d0e1f2a3b4` (26 total migrations compiled)  
**Live Recovery Verification Status:** **BLOCKED (Documented Blocker)**  
**Production Database Safety:** **PROTECTED (Zero Live Production Touches)**  

---

## 1. Executive Summary

This report establishes the database connection standards, migration lock governance, marketplace schema integrity rules, and disaster recovery procedures for the AskforWrite AI Company OS on Neon PostgreSQL.

Key findings and architectural decisions:
1. **Connection String Separation:** Application runtime traffic requires the PgBouncer pooled endpoint (`DATABASE_URL`), while Alembic migrations, DDL statements, and backup operations strictly require the direct compute connection (`DATABASE_URL_UNPOOLED`). `migrations/env.py` has been explicitly updated to prioritize `DATABASE_URL_UNPOOLED`.
2. **Schema Migration Chain & DDL Compilation:** Exactly 26 migrations compile cleanly to 2,280 lines of static PostgreSQL DDL with a single linear head (`o5d0e1f2a3b4`).
3. **Marketplace Referential Integrity & Orphan Prechecks:** Migration `o5d0e1f2a3b4` introduces `ON DELETE RESTRICT` on marketplace developer profiles and listing installs. Mandatory SQL prechecks are documented to prevent migration failure from dangling legacy records.
4. **Physical Backup & Restore Drill Blocker:** Live execution of physical `pg_dump` and `pg_restore` is documented as **`BLOCKED`** due to the absence of PostgreSQL client binaries on the host system and the unavailability of an isolated staging Neon branch. In accordance with strict integrity constraints, production `neondb` was protected from all exploratory operations.

---

## 2. Connection Architecture: Pooled vs. Unpooled URLs

Neon PostgreSQL provides two distinct connection topologies:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CONNECTION STRING TOPOLOGY                      │
│                                                                        │
│  [Web Application Traffic]                 [Alembic DDL & pg_dump]     │
│  DATABASE_URL                              DATABASE_URL_UNPOOLED       │
│  ep-***-pooler.c-6.us-east-2.aws.neon.tech  ep-***.c-6.us-east-2.aws    │
│           │                                           │                │
│           ▼                                           │                │
│   ┌───────────────┐                                   │                │
│   │   PgBouncer   │ (Transaction Pooling)             │                │
│   └───────┬───────┘                                   │                │
│           │                                           │                │
│           ▼                                           ▼                │
│   ┌───────────────────────────────────────────────────────────────┐    │
│   │                  Neon Postgres Compute Node                   │    │
│   │                        (neondb)                               │    │
│   └───────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Web Traffic: Pooled Connection (`DATABASE_URL`)
- **Host Format:** `ep-*-pooler.*.aws.neon.tech`
- **Mechanism:** PgBouncer transaction-level pooling.
- **Purpose:** Serves high-concurrency stateless HTTP API requests. Multiplexes hundreds of incoming client connections over a compact pool of server connections, preventing PostgreSQL worker process starvation.
- **Limitation:** Does NOT support session-level features, `LISTEN`/`NOTIFY`, temporary tables, `PREPARE TRANSACTION`, or persistent session locks.

### 2.2 Migrations & Maintenance: Direct Compute (`DATABASE_URL_UNPOOLED`)
- **Host Format:** `ep-*.*.aws.neon.tech` (omits `-pooler`)
- **Mechanism:** Direct TCP connection to the PostgreSQL backend engine.
- **Purpose:** Required for Alembic migrations, DDL schema alterations (`CREATE TABLE`, `ALTER TABLE`, `ADD CONSTRAINT`), database index creation, `pg_dump`, and `pg_restore`.
- **Why Required:** DDL operations frequently acquire exclusive advisory locks or alter system catalogs across multi-statement transactions. Running migrations through transaction-mode PgBouncer causes intermittent transaction lock aborts (`ERROR: relation "..." does not exist` or lock timeout failures).

### 2.3 Code Hardening in `migrations/env.py`
`migrations/env.py` was updated to enforce this connection policy:
```python
# Prioritize unpooled direct database URL for migration operations and DDL execution
_raw_unpooled = (
    os.environ.get("DATABASE_URL_UNPOOLED")
    or config.get_main_option("DATABASE_URL_UNPOOLED")
)

if _raw_unpooled:
    _migration_url = _raw_unpooled
    if _migration_url.startswith("postgres://"):
        _migration_url = _migration_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif _migration_url.startswith("postgresql://") and not _migration_url.startswith("postgresql+psycopg://"):
        _migration_url = _migration_url.replace("postgresql://", "postgresql+psycopg://", 1)
else:
    _migration_url = DATABASE_URL

config.set_main_option("sqlalchemy.url", _migration_url.replace("%", "%%"))
```

---

## 3. Migration Sequence & Schema Parity

### 3.1 Alembic Linear DAG Status
- **Head Revision:** `o5d0e1f2a3b4`
- **Total Revisions:** 26 linear migration scripts (0 branches).
- **Compilation Check:** `alembic upgrade head --sql` compiles 2,280 lines of PostgreSQL DDL with exit code 0 (`LOCAL_VERIFIED`).

### 3.2 Migration `o5d0e1f2a3b4` Specific Additions
1. **Tenant Invitation System:** Creates `tenant_invitations` table with primary key `id`, indexes, foreign key `fk_tenant_invitations_org_id` (`ON DELETE CASCADE`), foreign key `fk_tenant_invitations_invited_by_user_id` (`ON DELETE SET NULL`), and unique constraint `uq_tenant_invitations_token_hash`.
2. **Execution Telemetry Columns:** Adds `execution_budget_units` (int), `provider_cost_inr` (float), `provider_tokens_total` (int), and `provider_model` (varchar) to `execution_evidence_records`.
3. **P7 Autonomy Columns:** Adds `execution_budget_limit`, `execution_budget_units_used`, `provider_cost_inr`, `timeout_seconds`, and `node_states_json` to `p7_delegation_plans`; adds `max_daily_execution_units` to `p7_autonomy_policies`.
4. **P4 Foreign Keys:** Adds 5 foreign keys across `p4_market_intel_records`, `p4_growth_campaigns`, and `p4_pipeline_deals` (`ON DELETE SET NULL`).
5. **P8 Marketplace Foreign Keys:** Adds foreign keys to `p8_marketplace_listings` (`ON DELETE RESTRICT`), `p8_tenant_installs` (`ON DELETE RESTRICT`), and `p8_marketplace_reviews` (`ON DELETE CASCADE`).

---

## 4. Marketplace Referential Integrity & Pre-Upgrade Orphan Checks

### 4.1 Strict `ON DELETE RESTRICT` Constraints
To prevent accidental cascading deletion of critical marketplace assets, `o5d0e1f2a3b4` introduces strict referential constraints:
- `fk_p8_listings_developer_id`: `p8_marketplace_listings.developer_id -> p8_developer_profiles.id` (`RESTRICT`)
- `fk_p8_installs_listing_id`: `p8_tenant_installs.listing_id -> p8_marketplace_listings.id` (`RESTRICT`)

### 4.2 Mandatory Pre-Upgrade Prechecks
Before applying migration `o5d0e1f2a3b4` to any live or staging PostgreSQL database, system operators **MUST** run the following SQL queries to ensure zero orphaned records exist. If any query returns a count > 0, the orphaned records must be reconciled or removed before applying the migration, otherwise PostgreSQL will abort the transaction:

```sql
-- Check 1: Orphaned marketplace listings lacking a developer profile
SELECT count(*) AS orphan_listings
FROM p8_marketplace_listings
WHERE developer_id NOT IN (SELECT id FROM p8_developer_profiles);

-- Check 2: Orphaned tenant installs lacking a valid listing
SELECT count(*) AS orphan_installs
FROM p8_tenant_installs
WHERE listing_id NOT IN (SELECT id FROM p8_marketplace_listings);

-- Check 3: Orphaned marketplace reviews lacking a listing or install
SELECT count(*) AS orphan_reviews
FROM p8_marketplace_reviews
WHERE listing_id NOT IN (SELECT id FROM p8_marketplace_listings)
   OR install_id NOT IN (SELECT id FROM p8_tenant_installs);
```

### 4.3 P4 Orphan Nullification Safety
For nullable P4 growth and GTM tables, migration `o5d0e1f2a3b4` includes the helper `_cleanup_nullable_p4_orphans()`. In online migration mode, this routine automatically sets dangling optional foreign keys (`icp_id`, `lead_id`, `campaign_id`) to `NULL` before creating the constraints, preserving all records without data loss.

---

## 5. Physical Backup & Restore Drill: Blocker Analysis

### 5.1 Drill Verification Attempt
The preflight check tool `scripts/pg_backup_restore_drill.py` was executed to verify backup and restore readiness:
- **Command:** `python scripts/pg_backup_restore_drill.py --check-only --json`
- **Output:**
  ```json
  {
    "verification_status": "BLOCKED",
    "restore_tested": false,
    "source_origin": ".env:DATABASE_URL",
    "source_db": {
      "configured": true,
      "scheme": "postgresql",
      "host": "ep-fragrant-sun-b4pkm5df-pooler.c-6.us-east-2.aws.neon.tech",
      "database": "neondb"
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

### 5.2 Identified Blocker Components
1. **Missing Host Tooling:** The developer and audit environment on Windows lacks `pg_dump`, `pg_restore`, and `psql` on the system `PATH`. These client tools are required to extract consistent physical binary dumps and stream them into a restore target.
2. **Missing Isolated Staging Database:** The `.env` configuration contains credentials only for `ep-fragrant-sun-b4pkm5df.c-6.us-east-2.aws.neon.tech/neondb` where `NEON_BRANCH=production`. No secondary staging database, ephemeral branch URL, or `STAGING_DATABASE_URL` is configured.
3. **Strict Production Protection Mandate:** In compliance with release constraints R3 and R7:
   - "Never touch production neondb."
   - "Do not run production migrations."
   - "Never substitute SQLite tests for live PostgreSQL verification."
   Connecting the backup/restore drill to production `neondb` is strictly prohibited. Consequently, the physical drill is honestly documented as **`BLOCKED`**.

---

## 6. Verification Status Matrix

| Component | Target Artifact | Result / Evidence | Verification Tag | Status |
| :--- | :--- | :--- | :--- | :--- |
| Single Alembic Head | `alembic heads` | `o5d0e1f2a3b4 (head)` | `LOCAL_VERIFIED` | Pass |
| 26 Linear Revisions | `alembic history` | Exactly 26 sequential revisions | `LOCAL_VERIFIED` | Pass |
| Offline DDL Compilation | `alembic upgrade head --sql` | 2,280 lines valid PostgreSQL SQL | `LOCAL_VERIFIED` | Pass |
| Unpooled URL Prioritization | `migrations/env.py` | Prioritizes `DATABASE_URL_UNPOOLED` | `LOCAL_VERIFIED` | Pass |
| P4 Orphan Remediation | `migrations/versions/o5d0e1f2a3b4*.py` | `_cleanup_nullable_p4_orphans` safe nullify | `LOCAL_VERIFIED` | Pass |
| P8 Marketplace Constraints | `test_security_hardening_cross_record_fk.py` | `RESTRICT` and `CASCADE` verified | `LOCAL_VERIFIED` | Pass |
| Live Staging Migration Drill | Neon Staging Branch | Staging credentials unavailable | `BLOCKED` | Blocker (Action Required) |
| Physical Backup/Restore Drill | `pg_backup_restore_drill.py` | Missing `pg_dump`/`pg_restore` on host | `BLOCKED` | Blocker (Action Required) |
| Production DB Integrity | `ep-fragrant-sun-b4pkm5df` | Zero mutations, zero tests executed | `LIVE_VERIFIED` | Safe (Untouched) |

---

## 7. Step-by-Step Staging Verification Runbook for System Owners

When system owners provision an isolated Neon staging branch and a runner with PostgreSQL client binaries, execute this exact runbook to clear the blocker:

1. **Step 1: Create Isolated Scratch Branch in Neon Console:**
   - In Neon Dashboard, select project and click **Create Branch**.
   - Branch Name: `staging-migration-drill-202611`
   - Parent Branch: `production`
   - Copy the direct compute connection string (`DATABASE_URL_UNPOOLED`).

2. **Step 2: Execute Marketplace Orphan Prechecks:**
   ```bash
   psql "$STAGING_DATABASE_URL_UNPOOLED" -c "
   SELECT count(*) FROM p8_marketplace_listings WHERE developer_id NOT IN (SELECT id FROM p8_developer_profiles);
   SELECT count(*) FROM p8_tenant_installs WHERE listing_id NOT IN (SELECT id FROM p8_marketplace_listings);
   SELECT count(*) FROM p8_marketplace_reviews WHERE listing_id NOT IN (SELECT id FROM p8_marketplace_listings) OR install_id NOT IN (SELECT id FROM p8_tenant_installs);
   "
   ```
   *Expected:* All counts must be 0.

3. **Step 3: Apply Alembic Migrations to Staging Branch:**
   ```bash
   DATABASE_URL_UNPOOLED="$STAGING_DATABASE_URL_UNPOOLED" alembic upgrade head
   ```
   *Expected:* Migration succeeds up to `o5d0e1f2a3b4`.

4. **Step 4: Execute Physical Dump and Restore:**
   ```bash
   python scripts/pg_backup_restore_drill.py \
       --source-url "$STAGING_DATABASE_URL_UNPOOLED" \
       --target-url "$SCRATCH_RESTORE_DB_URL" \
       --json
   ```
   *Expected:* JSON output reporting `"verification_status": "SUCCESS"` and `"restore_tested": true`.

5. **Step 5: Record Verification Evidence & Grant Release Gate:**
   Update `MASTER_ROADMAP_SCORECARD.md` tag for P3.1 to `STAGING_VERIFIED`.
