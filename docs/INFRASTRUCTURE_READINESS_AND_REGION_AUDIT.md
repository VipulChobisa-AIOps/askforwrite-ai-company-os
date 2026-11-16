# AskforWrite AI Company OS — Infrastructure Readiness & Regional Architecture Audit

**Branch:** `fix/infra-remediation-from-11b466e` (based on `11b466e`)
**Execution Context:** Infrastructure Remediation, CPU/Memory Profiling, Region Benchmarking, Key Durability & Gateway Reconciliation
**Verification Date:** 2026-11-16
**Local/Staging Config Status:** **REMEDIATED IN REPO (`LOCAL_VERIFIED` / `STAGING_VERIFIED`)**
**Production Cutover Approved:** **`false`** (no production Render or `neondb` mutations performed)

---

## 1. Executive Summary

All core infrastructure risks identified in the release audit were measured empirically and remediated on branch `fix/infra-remediation-from-11b466e` without touching production Render settings or production `neondb`:

1. **Single-Worker Starter Sizing Validated (`UVICORN_WORKERS=1`):** Empirically measured full descendant process trees under live Uvicorn serving `/healthz`, `/readyz`, and `/v1/ops/roadmap-scorecard`: **1 worker uses `156.07 MB` RSS and `8.50s` CPU** (`~356 MB` / `69.5%` headroom on Render Starter 512 MB), whereas **2 workers use `322.09 MB` baseline RSS and `15.83s` CPU** before LLM/PDF workloads or doubled DB pools (`60` max connections vs `30`). Staging (`render.yaml`) and `scripts/start_production.py` default to `UVICORN_WORKERS="1"`.
2. **Empirical Cross-Region Benchmark (`singapore` vs `us-east-2`):** Live queries against isolated Neon projects in `aws-us-east-2` and `aws-ap-southeast-1` confirmed `aws-us-east-2` incurs **`2,019.8 ms` cold connect** and **`384.7 ms` per `SELECT 1`** (**`1,331.3 ms`** per 4 sequential queries) vs `aws-ap-southeast-1` (`912.3 ms` cold, `149.8 ms` single, `561.5 ms` 4-seq) from the APAC host while Render Singapore endpoint TCP connect is **`62.4 ms`**.
3. **Durable ECDSA Signing Keys & Safe Rotation:** Implemented `TRUST_ENGINE_PRIVATE_KEY_PEM`, `TRUST_ENGINE_RETIRED_PUBLIC_KEYS_PEM`, atomic multi-worker file writes, `retired_public_keys.json`, and `rotate_node_keypair()` in `app/security/ecdsa_pki.py` + `app/services/p8_marketplace.py`.
4. **PayPal & Pooled/Direct DB Reconciliation:** Unified `resolve_paypal_mode()` across `payment.py`, `payment_paypal.py`, and `connectors.py` (fails safe to `"sandbox"` unless explicit `PAYPAL_MODE=live`), while separating pooled runtime `DATABASE_URL` from unpooled `DATABASE_URL_UNPOOLED` DDL/backup operations.

---

## 2. Empirical Uvicorn Memory & CPU Measurements (Priority 2)

Measured on full Windows process trees (shim + Uvicorn manager + spawned worker processes) serving `/healthz`, `/readyz`, and `/v1/ops/roadmap-scorecard`:

| Metric | `UVICORN_WORKERS=1` | `UVICORN_WORKERS=2` | Assessment on Render Starter (`512 MB / 0.5 vCPU`) |
| :--- | :--- | :--- | :--- |
| Process Count | `2` (shim + 1 worker) | `4` (shim + manager + 2 workers) | 1 worker eliminates redundant master + 2nd runtime |
| Total Resident Set Size (RSS) | **`156.07 MB`** (`152.75 MB` worker) | **`322.09 MB`** (`29.97` + `138.92` + `149.88 MB`) | 2 workers leave `<190 MB` before heavy LLM/PDF spikes |
| Startup + Request CPU Time | **`8.500 s`** | **`15.828 s`** | 2 workers double cold module-import contention on `0.5 vCPU` |
| Steady-State `/healthz` Mean | **`6.83 ms`** | **`5.81 ms`** | Both well inside Render's `5.0s` deadline |
| Steady-State `/readyz` Mean | **`7.37 ms`** | **`6.88 ms`** | Both well inside Render's `5.0s` deadline |
| Recommended Starter Config | **`UVICORN_WORKERS=1`, `DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=5`** | Upgrade to Standard (`2 GB`) if `2+` workers needed | Configured cleanly on `render.yaml` staging & `start_production.py` |

---

## 3. Regional Latency Benchmark & Architecture Recommendation (Priority 3)

Measured live from APAC/India host against real Neon Postgres 18 instances (`twilight-resonance-00131838` in `aws-us-east-2` and a temporary cleaned-up `afw-bench-sin-tmp` project in `aws-ap-southeast-1`) plus Render Singapore edge (`443`):

| Target Endpoint | Probe Method | Cold Connect (ms) | Mean RTT / Query (ms) | 4 Sequential Queries (ms) | Verification Tag |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Render Singapore (`askforwrite-ai-company-os.onrender.com:443`) | TCP Connect | — | **`62.38 ms`** (`min 47.70 ms`) | — | `LOCAL_VERIFIED` |
| AWS Singapore (`ap-southeast-1:443`) | TCP Connect | — | **`142.74 ms`** | — | `LOCAL_VERIFIED` |
| Neon Singapore (`aws-ap-southeast-1`, ephemeral, deleted) | Postgres Pooled | **`912.27 ms`** | **`149.81 ms`** (`SELECT 1`) | **`561.47 ms`** | `STAGING_VERIFIED` |
| AWS US East 2 (`us-east-2:443`) | TCP Connect | — | **`330.10 ms`** | — | `LOCAL_VERIFIED` |
| Neon US East 2 (`aws-us-east-2`, `afw_staging` pooled) | Postgres Pooled | **`2,019.79 ms`** | **`384.67 ms`** (`SELECT 1`) | **`1,331.34 ms`** | `STAGING_VERIFIED` |
| Neon US East 2 (`aws-us-east-2`, `afw_staging` unpooled) | Postgres Direct | **`2,010.42 ms`** | **`369.20 ms`** (`SELECT 1`) | **`1,369.42 ms`** | `STAGING_VERIFIED` |

### Architectural Recommendation
- **Cross-region penalty:** Keep-warm `aws-us-east-2` queries add `~210–240 ms` per SQL round-trip from Singapore (`>1.3s` per 4-query API request, and `~2.0s` cold TLS+SCRAM connect).
- **Recommended Architecture (Best Long-Term Performance for Indian/APAC Users):** Provision production Neon PostgreSQL in **AWS Singapore (`aws-ap-southeast-1`)** co-located with Render **`singapore`** (`<5 ms` Render-to-Neon DB RTT; `~48–62 ms` user-to-Render RTT).
- **Lowest-Friction Alternative (If Keeping Existing Neon `us-east-2`):** Move Render compute (`askforwrite-ai-company-os` + staging) to **Render Ohio/US-East** so Render <-> Neon operates within `us-east-2` (`<3 ms` DB RTT per query).

---

## 4. Durable ECDSA Signing Keys & Safe Rotation (Priority 4)

Implemented in `app/security/ecdsa_pki.py` and `app/services/p8_marketplace.py`:
- **Environment-Injected Primary Key (`TRUST_ENGINE_PRIVATE_KEY_PEM`):** Supports single-line escaped `\n` PEM secrets in Render/cloud env vars, verifies consistency against optional `TRUST_ENGINE_PUBLIC_KEY_PEM`, and works across multiple stateless containers/redeployments (`durable: true`, `multi_instance_safe: true`).
- **Atomic Worker-Safe Disk Persistence (`TRUST_ENGINE_KEYS_DIR`):** Uses exclusive creation lockfile + `tempfile.mkstemp` + `0o600` chmod + `os.replace`, preventing worker startup races.
- **Zero-Downtime Key Rotation (`rotate_node_keypair()`):** Archives the outgoing public key into `retired_public_keys.json` and emits JSON compatible with `TRUST_ENGINE_RETIRED_PUBLIC_KEYS_PEM`. Both `TrustBlock` verification and `p8_marketplace.verify_listing_signature()` (`is_trusted_node_public_key()`) verify signatures made before and after rotation while still rejecting untrusted attacker keys (`LOCAL_VERIFIED` & `STAGING_VERIFIED`).

---

## 5. PayPal Sandbox/Live & Pooled/Direct DB Reconciliation (Priority 5)

- **PayPal Reconciliation (`resolve_paypal_mode()`):** Eliminated code drift where `payment.py` and `payment_paypal.py` previously defaulted to `"live"` while `connectors.py` defaulted to `"sandbox"`. All three modules now call `resolve_paypal_mode()`, failing safe to `"sandbox"` unless `PAYPAL_MODE=live` is explicitly configured. Production `render.yaml` `PAYPAL_MODE: sandbox` remains untouched pending explicit owner authorization.
- **Pooled vs Unpooled DB Connections:** Added `normalize_database_url()`, `is_pooled_database_url()`, `get_unpooled_database_url()`, and `get_database_topology_summary()` in `app/db/database.py`. Web traffic uses pooled `DATABASE_URL`; Alembic (`migrations/env.py`, `scripts/start_production.py`) and `pg_dump`/`pg_restore` prioritize direct unpooled `DATABASE_URL_UNPOOLED`. Both `DATABASE_URL` and `DATABASE_URL_UNPOOLED` are declared in `render.yaml` staging.
