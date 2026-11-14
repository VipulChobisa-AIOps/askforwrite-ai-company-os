# Simulation Environment & Test Execution Guide

**Execution Guard Module:** `app/services/execution_guard.py`

---

## 1. Execution Modes & Side-Effect Lock

Three explicit execution modes exist across agent and workflow execution:
- `SIMULATION` (default in `pytest` and staging)
- `SANDBOX` (isolated test credentials, no production mutations)
- `PRODUCTION` (requires live environment with external side effects enabled)

`is_external_side_effect_blocked()` returns `True` when:
- `ENABLE_EXTERNAL_SIDE_EFFECTS` is `"0"`, `"false"`, or `"no"`, OR
- `SIMULATION_ONLY` is `"1"`, `"true"`, or `"yes"`, OR
- `APP_ENV` is `"staging"`, `"test"`, `"testing"`, or `"simulation"`, OR
- Running under `pytest`/`unittest` without `ALLOW_LIVE_IN_TEST=true`.

When blocked:
1. Attempting `execution_mode="PRODUCTION"` returns `HTTP 403` (`SIMULATION_MODE_LOCK`).
2. Outbound `SmtpEmailDispatcher` (`APP_ENV` staging/simulation or `ENABLE_EXTERNAL_SIDE_EFFECTS=false` or `SIMULATION_ONLY=true`) and `get_email_dispatcher()` redirect into `record_simulated_dispatch(...)` (`_SIMULATION_DISPATCH_SINK`) without opening any SMTP socket.
3. WordPress publishing (`publish_seo_draft_to_wordpress`) intercepts into `WORDPRESS_SIMULATED_REST` + `record_simulated_dispatch("wordpress_rest", ...)` without issuing HTTP `POST`.
4. Outbound HTTP URL checks pass through `validate_external_url()` rejecting `localhost`, `127.0.0.1`, `169.254.169.254`, private RFC1918 ranges, `.local` hosts, and non-HTTP(S) schemes (`file://`, etc.).
5. Four-level emergency stop (`execution`, `agent`, `tenant`, `platform`) halts further execution while preserving existing audit & evidence logs.

---

## 2. Running Tests, Linting & Frontend Checks

Run all commands from the `os_gateway` directory:

```powershell
# 1. P1 Modular SME Workforce suite (Test Areas A-O)
.\.venv\Scripts\python.exe -m pytest tests\test_p1_modular_sme_workforce.py -v --tb=short

# 2. P0 Zero-Mock & Credibility + Auth + Email Dispatcher tests
.\.venv\Scripts\python.exe -m pytest tests\test_system_credibility_zero_mock.py tests\test_byok_and_auth_gate.py tests\test_email_dispatcher.py -v

# 3. Full automated regression suite
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short

# 4. Ruff linter
.\.venv\Scripts\python.exe -m ruff check app tests migrations

# 5. Dashboard JavaScript syntax check
node --check app\dashboard\dashboard.js

# 6. Database migrations check
.\.venv\Scripts\alembic.exe current
```

> **Browser E2E Note:** Playwright is not installed in the current `.venv` environment; frontend validation covers `node --check`, static HTML/CSS/JS contract checks, and FastAPI `TestClient` API integration tests rather than headless browser UI automation.
