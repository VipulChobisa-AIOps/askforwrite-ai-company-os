# Phase P7 — Controlled Autonomous Workforce

**Branch:** `feat/p7-controlled-autonomous-workforce`
**Migration:** `m3b8c9d0e1f2` (`down_revision="l2a7b8c9d0e1"`)

## Objectives Delivered
1. **Multi-Agent Delegation DAG Planner & Executor (`p7_delegation_plans`)**
   - Uses Kahn topological sorting and longest-path depth analysis to reject cycles, missing nodes, excessive chain depths (`max_depth`), and credit budget overruns (`credit_budget`).
   - Executes validated DAGs cleanly through `execute_registered_agent(...)` in `AGENT_REGISTRY` and seals completion to `TrustChain`.
2. **Tenant-Isolated Persistent Memory (`p7_tenant_memories`)**
   - Strictly scoped per non-nullable `org_id`, with automatic `redact_secrets` sanitization, provenance fields (`source_type`, `source_ref`), TTL expiry filtering, and DPDP compliance erasure (`/v1/p7/workforce/memories/purge`).
3. **5-Level Bounded Autonomy Governance (`p7_autonomy_policies`)**
   - Supports only `LEVEL_0_OBSERVE`, `LEVEL_1_ASSIST`, `LEVEL_2_APPROVAL_GATED`, `LEVEL_3_BOUNDED_AUTONOMY`, and `LEVEL_4_SUPERVISED_ORCHESTRATION`.
   - Permanently rejects unrestricted autonomy levels or attempts to disable `requires_hitl_for_external` (`422`).
4. **Continuous Agent Evaluation & Auto-Pause (`p7_agent_eval_runs`)**
   - Any evaluation run falling below quality or safety thresholds automatically flips `is_paused=True` on the agent's autonomy policy (`auto_paused_triggered=True`), blocking DAG execution (`403`) until reviewed and explicitly resumed by an Owner.
5. **Agents & UI**
   - Registered `autonomy_orchestrator_agent` and `eval_governance_agent` in `AGENT_REGISTRY`.
   - Wired `#nav-p7-autonomy` / `#page-p7-autonomy` in `app/dashboard/index.html` and `p7LoadControlCentre` in `app/dashboard/dashboard.js`.

## Verification Scope Notes
- Verified against isolated SQLite FastAPI TestClient suites (`SIMULATION` mode); `PRODUCTION` DAG execution remains blocked under sandbox guards.
- P3.1 production cutover status remains `BLOCKED`.
