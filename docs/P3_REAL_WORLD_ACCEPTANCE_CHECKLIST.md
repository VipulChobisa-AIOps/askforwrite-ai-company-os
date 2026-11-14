# P3 Real-World Acceptance Checklist (12 Steps)

Tracked persistently in `p3_acceptance_steps` (`app/services/p3_ops_compliance_cc.py`), exposed via `GET /v1/cs/acceptance` and `POST /v1/cs/acceptance/{step_number}`, and rendered inside `/app` under **P3 Customer Success & Growth -> Tab 5: Growth, Unit Econ & Acceptance**.

Statuses strictly distinguish:
- `NOT_TESTED` — Default initial state on fresh/upgraded databases.
- `SANDBOX_VERIFIED` — Verified inside local automated/staging harness with deterministic checks.
- `LIVE_VERIFIED` — Verified against a genuine paying non-sandbox customer on Render production with immutable proof.

---

## Acceptance Steps (`P3_ACCEPTANCE_BLUEPRINT`)

| # | Step Key | Title | Verification Requirement |
|---|---|---|---|
| **1** | `p3_step_01_customer_profile_created` | Customer Profile & Lifecycle Created | Create real non-sandbox P3 customer account linked to organization, owner, package entitlements, and goals. |
| **2** | `p3_step_02_onboarding_completed` | Onboarding Workflow & Training Completed | Complete all required onboarding tasks, credentials, training, and blockers for purchased service SKU. |
| **3** | `p3_step_03_connectors_authorized` | Required Connectors Authorized & Verified | Verify organization-scoped connector configuration and credentials prior to service activation. |
| **4** | `p3_step_04_workflow_executed` | Initial Service Workflow Executed | Execute customer service workflow inside tenant concurrency and budget limits with `ExecutionEvidence`. |
| **5** | `p3_step_05_deliverable_verified_accepted` | Deliverable QA Reviewed & Customer Accepted | Complete QA checklist and record customer acceptance (or controlled revision loop) on real deliverables. |
| **6** | `p3_step_06_health_score_evaluated` | Customer Health Score & Alerts Evaluated | Compute multi-dimension Customer Health score with evidence freshness and trigger internal alerts if needed. |
| **7** | `p3_step_07_support_ticket_resolved` | Support Ticket Triaged, Resolved & CSAT Captured | Open org-scoped ticket, run AI triage (HITL-gated for sensitive replies), resolve, and record CSAT rating. |
| **8** | `p3_step_08_renewal_or_payment_handled` | Renewal, Grace Period or Settlement Handled | Verify idempotent subscription lifecycle event handling, upcoming renewal visibility, or grace/recovery flow. |
| **9** | `p3_step_09_expansion_or_referral_reviewed` | Expansion or Referral Opportunity Reviewed via HITL | Evaluate catalog-grounded upsell/referral opportunity and verify Owner HITL approval before sharing. |
| **10** | `p3_step_10_unit_economics_verified` | Customer Unit Economics & Cost Budget Verified | Verify `ACTUAL`/`ALLOCATED`/`ESTIMATED` delivery costs against verified revenue, margin, and monthly cost limit. |
| **11** | `p3_step_11_privacy_export_tested` | Privacy Export & Offboarding Compliance Tested | Run org-scoped redacted data portability export and verify legal-hold / HITL deletion safeguards. |
| **12** | `p3_step_12_backup_restore_verified` | Multi-Tenant Ops Readiness & Backup Drill Verified | Verify DB probe, DLQ recovery flow, concurrency guardrails, and documented backup/restore verification drill. |
