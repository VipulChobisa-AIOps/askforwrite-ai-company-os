# AskforWrite AI Company OS — P7 Autonomous Workforce Governance & Budget Controls Report

**Branch:** `fix/audit-tenant-isolation-p8-p7`  
**Execution Context:** Pre-Release P7 Autonomy Governance & Execution Safety Audit (R2)  
**Verification Date:** 2026-11-16  
**Primary Modules:** `app/services/p7_autonomy_workforce.py`, `app/api/v1/p7_workforce.py`, `app/services/execution_guard.py`, `app/agents/llm_client.py`  
**Primary Test Suites:** `tests/test_security_hardening_p7_autonomy.py` (6 tests), `tests/test_p7_autonomous_workforce.py` (4 tests)  
**Overall P7 Status:** **VERIFIED (LOCAL_VERIFIED / SANDBOX_VERIFIED)**  

---

## 1. Executive Summary

This report validates the implementation, architectural controls, and adversarial resilience of the P7 Controlled Autonomous Workforce engine in AskforWrite AI Company OS.

The P7 subsystem provides multi-agent task orchestration under strict governance boundaries:
1. **5-Tier Autonomy Enforcement:** Enforces rigorous progression from `LEVEL_0_OBSERVE` to `LEVEL_4_SUPERVISED_ORCHESTRATION`. Prohibits unrestricted or fully autonomous operation.
2. **Kahn DAG Validation:** Validates delegation Directed Acyclic Graphs (DAGs) using Kahn's topological sort algorithm, preventing cycles, deadlocks, and excessive node depth.
3. **Genuine Blocking Timeout & Partial Persistence:** Executes steps under strict monotonic deadlines. On timeout, reversible steps are compensated, completed irreversible outputs are preserved, and execution state is durably committed to the database.
4. **Three-Way Accounting Separation:** Enforces strict separation between customer billing credits (`credit_cost`), internal execution quotas (`execution_budget_limit`), and provider expenses (`provider_cost_inr`), guaranteeing that internal execution steps are never silently converted into customer billing deductions.

---

## 2. Autonomy Hierarchy & Level Controls

Autonomy levels are defined in `app/services/p7_autonomy_workforce.py:42-57`:

| Autonomy Level | Level Identifier | Permitted Operations | Human-in-the-Loop (HITL) Gate |
| :--- | :--- | :--- | :--- |
| **Level 0** | `LEVEL_0_OBSERVE` | Read-only telemetry and task observation | Autonomous execution strictly blocked (`PermissionError`) |
| **Level 1** | `LEVEL_1_ASSIST` | Suggestion and drafting only | Every execution requires approved `ApprovalRequest` |
| **Level 2** | `LEVEL_2_APPROVAL_GATED` | Plan creation and proposed delegation | Execution paused until tenant manager approval granted |
| **Level 3** | `LEVEL_3_BOUNDED_AUTONOMY` | Execution within predefined credit and time caps | External connectors / side-effects require approval |
| **Level 4** | `LEVEL_4_SUPERVISED_ORCHESTRATION` | Multi-agent DAG execution under active E-stop monitoring | Continuous evaluation auto-pauses on quality/safety dips |

### 2.1 Prohibited Unrestricted Aliases
To prevent accidental or malicious bypassing of governance gates, the system rejects any policy configuration referencing unrestricted execution aliases:
```python
PROHIBITED_UNRESTRICTED_ALIASES = (
    "UNRESTRICTED", "LEVEL_5", "LEVEL_5_UNRESTRICTED", "FULL_AUTONOMOUS", "NO_HITL", "BYPASS_HITL"
)
```
Configuring any prohibited alias immediately raises `ValueError` (`422 Unprocessable Entity`).

---

## 3. DAG Planning, Kahn Validation & Context Handoff

### 3.1 Kahn's Algorithm Topological Sorting
Before any plan is accepted or persisted, `validate_and_order_dag` performs topological analysis:
1. **Cycle Prevention:** Rejects cyclic dependencies (e.g. `A -> B -> C -> A`) with `"Cycle detected in delegation DAG"`.
2. **Unresolved Dependencies:** Validates that every identifier in `depends_on` exists as a defined node in the DAG.
3. **Complexity Bounds:**
   - Maximum nodes per DAG: default `20`, hard ceiling `50`.
   - Maximum execution depth: default `5`, hard ceiling `10`.

### 3.2 Context Handoff & Memory Injection
When a step executes within a plan:
1. **Upstream Outputs:** Outputs from completed dependencies are extracted and injected into the step's input payload under `payload["dependency_outputs"]`.
2. **Tenant Memory Scoping:** Active tenant memories are injected under `payload["tenant_memories"]`. Memories are strictly scoped to `principal.org_id` and filtered by time-to-live (TTL).

---

## 4. Timeout Interruption, Compensation & Idempotent Recovery

```
               [DAG Execution Started (Deadline: T = now + timeout)]
                                      │
                                      ▼
                             [Execute Node 1] ──► COMPLETED (Persisted)
                                      │
                                      ▼
                             [Execute Node 2] ──► COMPLETED (Persisted)
                                      │
                                      ▼
                             [Execute Node 3 (Slow / Blocking)]
                                      │
                                      ▼
                             [Timeout Deadline Reached!]
                                      │
         ┌────────────────────────────┴────────────────────────────┐
         ▼                                                         ▼
[Reversible Completed Steps]                              [Irreversible Completed Steps]
  Marked: COMPENSATED                                       Preserved: COMPLETED
  Compensating handler called                               Node output durable in DB
         │                                                         │
         └────────────────────────────┬────────────────────────────┘
                                      ▼
                       [Durable Execution State Saved]
                       Plan Status: TIMED_OUT / CANCELLED
                                      │
                                      ▼
                       [POST /dag-plans/{id}/recover]
                                      │
                                      ▼
              [Resumes at Node 3 without re-executing Node 1 & 2]
```

### 4.1 Blocking Timeout Interruption
In `app/services/p7_autonomy_workforce.py:614-617`:
```python
remaining_seconds = deadline - _monotonic()
if remaining_seconds <= 0:
    _compensate_completed(nid, "TIMED_OUT", f"DAG execution exceeded timeout_seconds={eff_timeout}s")
    raise TimeoutError(f"Delegation execution timed out after {eff_timeout}s at node '{nid}'")
```
When a step exceeds the configured timeout:
1. An interrupt signal is delivered to the executing thread.
2. `_compensate_completed` triggers compensating transactions for all reversible predecessor nodes.
3. Irreversible steps are preserved with status `COMPLETED` and note `skipped_irreversible_side_effect`.
4. Node execution states (`node_states_json`) and intermediate outputs (`execution_results_json`) are committed to PostgreSQL, preventing state loss.

### 4.2 Cooperative Cancellation & Idempotent Recovery
- **Cancellation (`/v1/p7/workforce/dag-plans/{id}/cancel`):** Signals `cancel_event.set()`, halts in-flight workers, executes compensating handlers, and transitions plan status to `CANCELLED`.
- **Recovery (`/v1/p7/workforce/dag-plans/{id}/recover`):** Reads the persisted `node_states_json`. Completed nodes are identified, their outputs are restored from `ExecutionEvidenceRecord`, and execution cleanly resumes from the first uncompleted or failed step without re-running prior side-effects.

---

## 5. Three-Way Accounting Separation & Cost Provenance

AskforWrite strictly maintains three independent accounting ledgers:

```
┌────────────────────────────────────────────────────────────────────────┐
│                     THREE-WAY ACCOUNTING SEPARATION                    │
├─────────────────────────┬──────────────────────┬───────────────────────┤
│    CUSTOMER CREDITS     │   EXECUTION UNITS    │   PROVIDER COST INR   │
│  (Billing / Invoicing)  │  (System Quotas)     │  (Vendor Expenditure) │
├─────────────────────────┼──────────────────────┼───────────────────────┤
│ Deducted from customer  │ Metred per-step      │ Tracks raw LLM token  │
│ wallet balance.         │ internally (e.g. 1   │ costs in INR from     │
│ Non-billable P4–P8      │ unit per DAG node).  │ API invoices.         │
│ agents have credit_cost │ Tracks compute quota │ Never converted into  │
│ = 0.                    │ without billing.     │ customer charges.     │
└─────────────────────────┴──────────────────────┴───────────────────────┘
```

### 5.1 Provider Cost Provenance
To eliminate synthetic or fabricated cost reporting, `app/agents/llm_client.py` tags all LLM execution evidence with an explicit provenance enum:
- `TOKEN_USAGE_ESTIMATE`: Calculated from token counts; `actual_provider_cost_inr = None`.
- `LIVE_PROVIDER_REPORTED`: Exact cost parsed from vendor invoice/usage metadata.
- `DETERMINISTIC_FALLBACK_ZERO`: Assigned when no LLM call was executed.

---

## 6. Emergency Stop (E-Stop) & Continuous Evaluation Auto-Pause

1. **Emergency Stop (E-Stop):** Integrated with `app/services/execution_guard.py`. Setting an emergency stop at the tenant or global platform scope immediately raises `ExecutionBlockedError`, preventing any P7 agent from scheduling or executing tasks.
2. **Continuous Evaluation Auto-Pause:** When `run_agent_evaluation` detects that an agent's quality score or safety score drops below `min_eval_threshold` (e.g., `< 0.70`), the agent's autonomy policy is automatically paused (`policy.is_paused = True`). Resuming a paused agent requires platform operator authorization via `POST /v1/p7/workforce/autonomy-policies/{id}/resume`.

---

## 7. Verification Results & Test Evidence

All 10 P7 autonomy and workforce test cases pass cleanly:

```powershell
.\.venv\Scripts\pytest tests/test_security_hardening_p7_autonomy.py tests/test_p7_autonomous_workforce.py -v
```

| Test Name | Targeted Verification | Result | Status |
| :--- | :--- | :--- | :--- |
| `test_p7_three_control_budgets_and_llm_telemetry_metering` | 3-way accounting separation & LLM telemetry | Passed | `LOCAL_VERIFIED` |
| `test_p7_provider_cost_actual_vs_estimated_provenance` | Cost provenance tagging & zero-commingling | Passed | `LOCAL_VERIFIED` |
| `test_p7_genuine_blocking_timeout_partial_persistence_cancel_and_recovery` | Real blocking timeout, partial persistence & recovery | Passed | `LOCAL_VERIFIED` |
| `test_p7_autonomy_level_approval_daily_cap_estop_timeout_and_compensation` | 5 autonomy levels, HITL gates, daily caps & E-stop | Passed | `LOCAL_VERIFIED` |
| `test_p7_dependency_injection_memory_org_spoof_and_role_blocks` | Cross-tenant memory isolation & RBAC boundaries | Passed | `LOCAL_VERIFIED` |
| `test_p7_concurrent_credit_and_execution_budget_enforcement` | Concurrency race condition budget safety | Passed | `LOCAL_VERIFIED` |
| `test_p7_autonomous_workforce.py` (4 tests) | Workforce registry, DAG sorting & execution | Passed | `LOCAL_VERIFIED` |
