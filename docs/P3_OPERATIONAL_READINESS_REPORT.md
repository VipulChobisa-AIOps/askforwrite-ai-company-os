# P3 Operational Readiness Report — Multi-Tenant Scale, Recovery & Production Constraints

**Alembic Revision:** `i9d4e5f6a7b8 (head)`  
**Readiness Module:** `app/services/p3_ops_compliance_cc.py`  
**Staff Telemetry Endpoint:** `GET /v1/cs/ops/readiness`

---

## 1. Multi-Tenant Reliability Controls Implemented & Verified

| Control | Implementation | Configurable Env / Constant | Sandbox Verification |
|---|---|---|---|
| **Per-Org Workflow Concurrency Ceiling** | `check_and_enforce_workflow_concurrency()` in `app/services/workflow_engine.py` (`start_workflow_run`) counts `READY` / `RUNNING` runs per `org_id`; blocks saturated orgs with internal `SupervisorAlertRecord` without starving other tenants. | `P3_MAX_CONCURRENT_RUNS_PER_ORG` (default `5`) | `test_05` verifies saturating `org-sandbox-demo` leaves `org-live-jaipur` isolated and responsive. |
| **Workflow Timeout Detection & DLQ** | `scan_timed_out_workflows_and_queue_dlq()` detects stale `RUNNING` runs older than timeout threshold, transitions them to `FAILED`, creates `P3OperationalIncidentRecord` (`WORKFLOW_TIMEOUT`), and supports idempotent retry (`retry_dlq_workflow_run`: `FAILED -> READY`). | `P3_WORKFLOW_TIMEOUT_SECONDS` (default `900`s) | `test_05` verifies stale `wf-run-stale-1` transitions `RUNNING -> FAILED -> DLQ -> READY`. |
| **Automatic Failure Capture** | `start_workflow_run` in `app/services/workflow_engine.py` wraps unhandled step exceptions with `move_failed_run_to_dlq()` (`DEAD_LETTER_JOB`). | Enabled globally | Verified in code path + DLQ incident serialization. |
| **Database Latency & Health Probe** | `probe_database_performance()` executes live `SELECT 1`, measures round-trip `latency_ms`, and reports `HEALTHY` vs `DEGRADED`. | `P3_DB_LATENCY_DEGRADED_MS` (default `500.0`ms) | `test_05` verifies `database_health.status == "HEALTHY"`. |
| **Backup & Restore Verification Ledger** | `record_backup_verification_drill()` stores recovery drill evidence (`target_scope`, `restore_tested`, `rpo_minutes`, `rto_seconds`, `evidence_ref`) in `p3_operational_incidents` + `AuditLog`. | Owner API `POST /v1/cs/ops/backup-drill` | `test_05` verifies `latest_backup_drill.status == "RECOVERED"`. |
| **Parallel Read Stability** | Multi-threaded requests across `/v1/cs/control-centre`, `/v1/cs/ops/readiness`, and `/v1/cs/customers/{org_id}/health`. | Thread-safe request scoping | `test_05` executes parallel `Thread` reads with `0` HTTP errors. |
| **Per-Tenant Spend Hard Cap** | `record_unit_economics_cost()` enforces `monthly_cost_limit_inr` when `hard_cap_enforced=True`, raising `CostBudgetExceededError` -> `HTTP 402 Payment Required` unless Owner HITL override is active. | Default `2000.0` INR/mo | `test_04` confirms `300` INR accepted and additional `350` INR over `500` INR cap blocked with `HTTP 402`. |

---

## 2. Metrics Isolation Guarantee (Control Centre)

`get_p3_customer_ops_control_centre()` (`GET /v1/cs/control-centre`) enforces two strictly non-overlapping top-level blocks:

- **`verified_customer_ops`**: Counts ONLY non-sandbox organizations (`_is_sandbox_org(org) == False`), non-synthetic `P2ProspectDossierRecord` (`is_synthetic == False`), paid `InvoiceRecord` rows, and provider-confirmed `RECURRING_SUBSCRIPTION` events (`is_provider_confirmed == True`). When `<2` billing periods or zero confirmed recurring subscriptions exist, `verified_arr_inr` returns `"INSUFFICIENT_DATA"`.
- **`simulation_and_test_metrics`**: Counts synthetic prospects (`is_synthetic == True`), sandbox organizations, `SIMULATION` `ExecutionEvidenceRecord` rows, and `SIMULATION` `WorkflowRunRecord` rows under `"exclusion_policy": "EXCLUDED_FROM_LIVE_BUSINESS_KPIS"`.

---

## 3. Honest Production Readiness Gaps (Not Executed Locally)

1. **Managed PostgreSQL Backup/Restore Against Render:** `record_backup_verification_drill()` logs verified restore drills into PostgreSQL/SQLite; executing an actual pg_dump/snapshot restore test against the live Render PostgreSQL database instance requires Render CLI/dashboard access and has **not** been run in this local development environment.
2. **External Connector Live Checks (`google_search_console`, `razorpay`, `paypal`, `hostinger_smtp`):** Connector matrix entries reflect stored `ConnectorStateRecord` status. External Search Console API quota/attribution and live Render webhook/SMTP deliveries were **not** exercised over public internet in this session.
3. **Process-Level Background Worker:** Render deployment keeps the existing single FastAPI gateway (`render.yaml`). Timeout scanning (`/v1/cs/ops/workflows/scan-timeouts`) and grace-period enforcement (`/v1/cs/subscriptions/enforce-grace`) are idempotent endpoints/agent actions ready to be triggered by scheduler/cron; no external Celery/Redis cluster was added.
