# AskforWrite AI Company OS — Render Runtime & Healthcheck Remediation Report

**Branch:** `fix/infra-remediation-from-11b466e` (based on preserved security checkpoint `11b466e`)
**Execution Context:** Render Runtime Stability & Healthcheck Timeout Remediation
**Verification Date:** 2026-11-16
**Code Remediation Status:** **IMPLEMENTED & `LOCAL_VERIFIED` / `STAGING_VERIFIED` (against Neon `afw_staging` & `afw_restore_drill`)**
**Live Render Deploy Verification:** **`BLOCKED`** (no push/deploy to Render performed)

---

## 1. Root Cause of Historical 35.8–36.2s `/health` Timeouts

1. `GET /health` in `app/main.py` previously injected `db: Session = Depends(get_db)`.
2. FastAPI executed `Depends(get_db)` **before** entering the handler, blocking on SQLAlchemy `QueuePool.get()` (`pool_timeout=30`s) plus `psycopg` `connect_timeout=5`s + cross-region DNS/TLS (`~0.8`s) = **`35.8–36.2` seconds** whenever Neon compute suspended or the pool saturated.
3. `SET LOCAL statement_timeout = 3000` only ran after connection acquisition, so it never bounded stalled connection checkout.
4. `app/middleware.py` (`LLMContextMiddleware`) also lazy-imported `app.agents.llm_client` inside HTTP `dispatch()` on cold requests, and `RateLimitMiddleware` applied per-IP/header throttling evenly without exempting health probes.

---

## 2. Implemented Remediation (`app/main.py`, `app/middleware.py`, `render.yaml`)

1. **Zero-Dependency Liveness Probe (`GET /healthz`):**
   - Executes zero database or external network calls and responds immediately with HTTP `200` `{"status": "alive", ...}`.
   - `render.yaml` staging service (`askforwrite-ai-company-os-staging`) is configured with `healthCheckPath: /healthz` so Render never kills an active FastAPI process during database cold starts.
2. **Strictly Bounded Readiness & Health Probes (`GET /readyz` and `GET /health`):**
   - Removed blocking `Depends(get_db)` from both routes.
   - Added `_probe_database_bounded()` bounded cleanly by `HEALTHCHECK_DB_TIMEOUT_SECONDS` (`3.5`s default, clamped to `[0.25, 4.0]`s so responses always complete inside Render's `5.0`s deadline).
   - Uses a `ThreadPoolExecutor` timeout around `engine.connect()` (`_probe_engine_sync`) for normal pooled reuse (avoiding a 6-RTT cold TCP+TLS+SCRAM handshake on every request while still aborting pool contention strictly within the `3.5`s deadline) or `_probe_postgres_isolated_sync` when runtime `DATABASE_URL` overrides are active.
   - Preserves `app.dependency_overrides[get_db]` compatibility (`inspect.isgenerator(res)` ensures `MagicMock` session mocks are handled properly).
   - **Never masks dependency failures:** Returns HTTP `503 Service Unavailable` with `"status": "not_ready"` (`/readyz`) or `"status": "unhealthy"` (`/health`), `"database": "degraded"`, and explicit `"database_error"` (`"probe_timeout"` or exception class name).
3. **Middleware & Startup Pool Warmup Hardening:**
   - `LLMContextMiddleware` and `RateLimitMiddleware` skip heavy lazy `llm_client` imports and rate-limit buckets on `/healthz`, `/readyz`, and `/health`.
   - `lifespan()` in `app/main.py` warms a single pooled DB connection (`SELECT 1`) cleanly even when `AFW_SKIP_WORKER_DDL=1` is active under `scripts/start_production.py`.
4. **Live Cross-Continent Discovery During Neon Staging Testing:**
   - Empirical testing against Neon `aws-us-east-2` proved a cold unpooled cross-continent `psycopg.connect()` took `2,017–2,020 ms`, triggering an honest `503` under a `2.0s` unpooled probe. With `QueuePool` warmup + `3.5s` bound, live Neon `/healthz` (`200`), `/readyz` (`200`, `1,634.7 ms` from India), and `/health` (`200`, `1,629.3 ms`) passed reliably while still failing closed well under `5.0s` when PostgreSQL hangs.

---

## 3. Empirical Verification Evidence

| Check | Target | Measured Result | Verification Tag |
| :--- | :--- | :--- | :--- |
| Zero-DB Liveness Under Broken DB | `GET /healthz` (`test_infra_remediation_readiness.py`) | HTTP `200`, warm `<100 ms` (`6.83 ms` under Uvicorn); `/readyz` & `/health` return `503` | `LOCAL_VERIFIED` |
| Hung TCP Socket PostgreSQL Blackhole | `GET /readyz` & `GET /health` (`HEALTHCHECK_DB_TIMEOUT_SECONDS=1.0`) | Both return HTTP `503` (`probe_timeout`) in `<3.0s` (`~1.0s`, strictly `<5.0s`) | `LOCAL_VERIFIED` |
| Degraded DB Mock Compatibility | `test_22_database_degraded_health_returns_503` | HTTP `503`, `database: "degraded"` | `LOCAL_VERIFIED` |
| Live Neon Staging Health (`afw_staging` & `afw_restore_drill`) | `GET /healthz`, `GET /readyz`, `GET /health` | All `200 OK` against PostgreSQL 18 (`o5d0e1f2a3b4`) | `STAGING_VERIFIED` |
| Live Render Deployed Container | `https://os.askforwrite.com/healthz` / Staging Render URL | Not pushed/deployed per restriction | `BLOCKED` |
