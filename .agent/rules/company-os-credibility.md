# Company OS UI, Auth-Gate, P0 Truthfulness & Zero-Mock Credibility Rules

1. **Auth-Gate First Paint, Fail-Closed Shell & Chrome Autofill Isolation (`P0-B`):**
   - `#auth-gate-overlay` MUST default to `style="display:flex"` in HTML and `#sidebar` / `#main-content` MUST remain hidden (`visibility: hidden`) until authenticated.
   - `init()` MUST return immediately before `fetchAll()` when `checkAuthGate()` is `false`, and any HTTP `401` response MUST immediately clear credentials and lock the shell.
   - API keys and bearer tokens in the DOM MUST use `type="text"` with `.masked-secret-input` (`-webkit-text-security: disc`) and `autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-form-type="other"` to prevent Google Chrome account popups.

2. **Render Cloud Paid Compute, Staging Isolation & PWA Cache Busting (`P0-A` / `P0-C`):**
   - Preserve `render.yaml` (`askforwrite-ai-company-os`) on paid compute (`plan: starter` — never `free`, which spins down and blocks SMTP 465/587) plus isolated `askforwrite-ai-company-os-staging` (`ENABLE_EXTERNAL_SIDE_EFFECTS=false`).
   - Service Worker (`sw.js`) MUST use versioned cache names (`afw-os-shell-v3.5-truthfulness`) and network-first strategy for `/dashboard/` so stale login/JS shells are never served.

3. **Strict Truthfulness & Demo/Live Separation (`Section 2 & 7`):**
   - Never silently invoke `loadDemoData()` when `/health` or backend API calls fail, and never render fake success messages or checkout links in UI `catch` blocks (`Inbound Closer`, `PixelBot`, `Field Force`).
   - Every capability and connector MUST report one of the 7 standard truthfulness states (`LIVE_VERIFIED`, `LOCAL_ENGINE_VERIFIED`, `SANDBOX_VERIFIED`, `HUMAN_ASSISTED`, `SIMULATED`, `BLOCKED`, `ROADMAP`). If `fallback_used=True` or external credentials are missing, status MUST NEVER claim `LIVE_VERIFIED`.
   - Every execution MUST emit the 15-field `evidence` envelope (`execution_id`, `tenant_id`, `agent_id`, `tool_id`, `mode`, `provider`, `input_reference`, `fallback_used`, `external_request_id`, `started_at`, `completed_at`, `result_status`, `credits_consumed`, `approval_id`, `evidence_reference`).

4. **Company OS Command Dock & Modular SME Architecture (`Section 3, 5, 6 & 9`):**
   - Every commercial service tool and specialist AI agent MUST have a dedicated icon/logo launcher button (`.os-service-tool-btn`) or "Call Agent" card (`data-call-agent`), plus the interactive `#agent-run-console`.
   - All releases MUST pass `POST /v1/watchdog/credibility-audit` (16/16 subsystems, `failure_rate_pct == 0.0`), `POST /v1/watchdog/sme-sandbox-scenario` (12/12 Jaipur SME steps), and `tests/test_system_credibility_zero_mock.py`.
