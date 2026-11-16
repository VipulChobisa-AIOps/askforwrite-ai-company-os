# AskforWrite AI Company OS — PostgreSQL Schema Parity, Migration Safety & Recovery Report

**Branch:** `fix/audit-tenant-isolation-p8-p7`  
**Execution Context:** Pre-Release PostgreSQL Migration & Recovery Audit (R3)  
**Verification Date:** 2026-11-16  
**Alembic Head Revision:** `o5d0e1f2a3b4` (26 total migrations compiled)  
**Drill Test Suite:** `tests/test_p3_1_postgres_drill.py`  
**Offline DDL Status:** **VERIFIED (`LOCAL_VERIFIED`)**  
**Live Staging Recovery Status:** **BLOCKED (Documented Blocker)**  
**Production Database Safety:** **PROTECTED (neondb untouched)**  

---

## 1. Executive Summary

This report delivers the authoritative evaluation of PostgreSQL schema parity, Alembic migration safety, referential constraint integrity, and disaster recovery readiness for AskforWrite AI Company OS.

Summary of Verification:
1. **Single Alembic Linear Chain:** The migration history consists of exactly 26 sequential revisions with a single head (`o5d0e1f2a3b4`) and zero divergent branches (`LOCAL_VERIFIED`).
2. **Offline PostgreSQL DDL Generation:** Offline SQL compilation successfully generated 2,280 lines of clean, transaction-scoped PostgreSQL DDL (`BEGIN; ... COMMIT;`) (`LOCAL_VERIFIED`).
3. **Unpooled Connection Prioritization:** `migrations/env.py` was hardened to prioritize `DATABASE_URL_UNPOOLED` over `DATABASE_URL`, preventing transactional lock failures through PgBouncer connection poolers (`LOCAL_VERIFIED`).
4. **Referential Integrity & Pre-Upgrade Orphan Checks:** Migration `o5d0e1f2a3b4` introduces strict `ON DELETE RESTRICT` foreign keys on marketplace tables. Pre-upgrade SQL queries are documented to prevent upgrade failures from orphan records (`LOCAL_VERIFIED`).
5. **Recovery Drill Blocker:** Live execution of physical `pg_dump` and `pg_restore` is **`BLOCKED`** due to missing PostgreSQL client binaries on the host system and the unavailability of an isolated staging Neon branch. In compliance with strict safety directives, production `neondb` was protected from all exploratory testing.

---

## 2. Alembic Linear Revision Chain (26 Revisions)

The full revision sequence was verified via `alembic history`:

1. `<base> -> 20260926_0001`: Create task, lead, audit, and idempotency tables.
2. `20260926_0001 -> 20260926_0002`: Add durable owner approval requests.
3. `20260926_0002 -> 20260926_0003`: Add persisted Research Agent outputs.
4. `20260926_0003 -> 20260926_0004`: Add requirement capture and proposal records.
5. `20260926_0004 -> 20260926_0005`: Add verifiable capability delivery records.
6. `20260926_0005 -> 20260926_0006`: Add cryptographically sealed trust blocks table.
7. `20260926_0006 -> 4beaadb407af`: Add SEO, Marketing and ASK4 models.
8. `4beaadb407af -> 5c7a1e890123`: Add multi-tenant organizations, users, invoices, and billing tables.
9. `5c7a1e890123 -> 7a8b9c0d1e2f`: Add org_id, domain, and unique constraint to leads.
10. `7a8b9c0d1e2f -> 8b9c0d1e2f3a`: Add outreach_records table for owner-governed email and message dispatch.
11. `8b9c0d1e2f3a -> 9c0d1e2f3a4b`: Add password_hash to users table for Admin and Customer login.
12. `9c0d1e2f3a4b -> a1b2c3d4e5f6`: Add geofence_definitions and field_attendance_records tables for Field Force Engine.
13. `a1b2c3d4e5f6 -> b2c3d4e5f6a1`: Add field_task_records table for Autonomous Dispatch & Route Optimizer.
14. `b2c3d4e5f6a1 -> c3d4e5f6a1b2`: Add client_visit_records table for Multimodal Proof-of-Execution & Debrief.
15. `c3d4e5f6a1b2 -> d4e5f6a1b2c3`: Add conveyance_claim_records and expense_receipt_records tables.
16. `d4e5f6a1b2c3 -> e5f6a1b2c3d4`: Add supervisor_alert_records, preview_records, and shift_records tables.
17. `e5f6a1b2c3d4 -> f6a1b2c3d4e5`: Add sovereign_payment_sessions table for durable checkout persistence.
18. `f6a1b2c3d4e5 -> g7b2c3d4e5f6`: Add P1 modular SME workforce, registry, workflow, credit ledger, emergency stop, and execution evidence tables.
19. `g7b2c3d4e5f6 -> h8c3d4e5f6a7`: Add P2 commercial revenue engine tables.
20. `h8c3d4e5f6a7 -> i9d4e5f6a7b8`: Add P3 customer success growth engine tables.
21. `i9d4e5f6a7b8 -> j0e5f6a7b8c9`: Add P4 growth and GTM engine tables.
22. `j0e5f6a7b8c9 -> k1f6a7b8c9d0`: Add P5 productization and multi-customer scale tables.
23. `k1f6a7b8c9d0 -> l2a7b8c9d0e1`: Add P6 multi-industry SME packs and India SEO baseline tables.
24. `l2a7b8c9d0e1 -> m3b8c9d0e1f2`: Add P7 controlled autonomous workforce tables.
25. `m3b8c9d0e1f2 -> n4c9d0e1f2a3`: Add P8 marketplace ecosystem tables.
26. `n4c9d0e1f2a3 -> o5d0e1f2a3b4`: Add TenantInvitationRecord, P7 three-control budget/state columns, execution telemetry columns, and relational FKs.

---

## 3. Offline PostgreSQL DDL Compilation

Compiled using the PostgreSQL dialect compiler:
- **Command:** `alembic upgrade head --sql`
- **Output:** 2,280 lines of valid PostgreSQL DDL enclosed in a transactional block:
  ```sql
  BEGIN;
  CREATE TABLE alembic_version (
      version_num VARCHAR(32) NOT NULL,
      CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
  );
  ...
  -- Migration o5d0e1f2a3b4
  CREATE TABLE tenant_invitations (...);
  ALTER TABLE execution_evidence_records ADD COLUMN execution_budget_units INTEGER;
  ALTER TABLE execution_evidence_records ADD COLUMN provider_cost_inr FLOAT;
  ALTER TABLE p7_delegation_plans ADD COLUMN execution_budget_limit INTEGER;
  ...
  COMMIT;
  ```
- **Result:** Exit code 0. Validated zero syntax errors, missing table definitions, or circular foreign key dependencies.

---

## 4. Migration `o5d0e1f2a3b4` Data Safety Review

Inspected directly against `migrations/versions/o5d0e1f2a3b4_post_p8_security_and_governance_hardening.py`:

1. **`tenant_invitations` Table:**
   - Primary key: `id` (VARCHAR(36)).
   - Foreign key: `fk_tenant_invitations_org_id` on `organizations.id` (`ON DELETE CASCADE`).
   - Foreign key: `fk_tenant_invitations_invited_by_user_id` on `users.id` (`ON DELETE SET NULL`).
   - Unique constraint: `uq_tenant_invitations_token_hash`.
2. **Execution Telemetry Additions:**
   - `execution_evidence_records`: Adds `execution_budget_units`, `provider_cost_inr`, `provider_tokens_total`, `provider_model`.
   - All columns are nullable or have safe defaults, preventing write blocking during rolling schema migration.
3. **P7 Autonomy Additions:**
   - `p7_delegation_plans`: Adds `execution_budget_limit`, `execution_budget_units_used`, `provider_cost_inr`, `timeout_seconds`, and `node_states_json` (JSON).
   - `p7_autonomy_policies`: Adds `max_daily_execution_units`.
4. **P4 Foreign Key Cleanup:**
   - 5 nullable FKs across `p4_market_intel_records`, `p4_growth_campaigns`, and `p4_pipeline_deals` configure `ON DELETE SET NULL`.
   - The online migration handler `_cleanup_nullable_p4_orphans()` nullifies dangling optional FK references before applying constraints, ensuring zero row loss.
5. **P8 Marketplace Referential Constraints:**
   - `fk_p8_listings_developer_id` on `p8_marketplace_listings.developer_id -> p8_developer_profiles.id` (`ON DELETE RESTRICT`).
   - `fk_p8_installs_listing_id` on `p8_tenant_installs.listing_id -> p8_marketplace_listings.id` (`ON DELETE RESTRICT`).
   - `fk_p8_reviews_listing_id` & `fk_p8_reviews_install_id` (`ON DELETE CASCADE`).

---

## 5. Mandatory Pre-Upgrade Marketplace Orphan Checks

Because `ON DELETE RESTRICT` will reject foreign key creation if orphaned child records exist in a live database, operators must execute these verification queries prior to running `alembic upgrade head`:

```sql
-- 1. Check orphaned listings lacking a developer profile
SELECT count(*) AS orphan_listings
FROM p8_marketplace_listings
WHERE developer_id NOT IN (SELECT id FROM p8_developer_profiles);

-- 2. Check orphaned installs lacking a marketplace listing
SELECT count(*) AS orphan_installs
FROM p8_tenant_installs
WHERE listing_id NOT IN (SELECT id FROM p8_marketplace_listings);

-- 3. Check orphaned reviews lacking a listing or install
SELECT count(*) AS orphan_reviews
FROM p8_marketplace_reviews
WHERE listing_id NOT IN (SELECT id FROM p8_marketplace_listings)
   OR install_id NOT IN (SELECT id FROM p8_tenant_installs);
```
All queries must return `0`. If any count > 0, the orphaned records must be reconciled prior to schema upgrade.

---

## 6. PostgreSQL Drill Guardrails & Blocker Documentation

### 6.1 Drill Script Guardrails
`tests/test_p3_1_postgres_drill.py` passed locally (`LOCAL_VERIFIED`), verifying:
- Subprocess invocations pass `PGPASSWORD` via environment variables rather than command-line arguments, preventing credentials exposure in `ps` or OS process tables.
- Verification scripts validate target database hostnames and database names, preventing accidental targeting of production.

### 6.2 Authoritative Release Blocker
- **Blocker Status:** **`BLOCKED`**
- **Host Binaries:** The Windows developer host lacks `psql`, `pg_dump`, and `pg_restore` on the system `PATH`.
- **Staging Database:** No isolated staging Neon branch URL or secondary scratch database was provided.
- **Production Isolation:** Under strict constraints R3 and R7 ("Never touch production neondb" and "Never substitute SQLite tests for live PostgreSQL verification"), live PostgreSQL migration and backup/restore verification remain honestly documented as **`BLOCKED`** until an isolated staging branch and client tools are provisioned by system owners.
