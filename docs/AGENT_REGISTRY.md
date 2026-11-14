# Agent Registry Documentation

**Source of Truth:** `app/services/registry.py` (`AGENT_REGISTRY`)  
**API Surface:** `app/api/v1/registry.py`

All `20` registered specialist AI agents share a validated dataclass contract containing `agent_id`, `agent_name`, `description`, `business_function`, `capabilities`, `supported_tools`, `input_schema`, `output_schema`, `model_configuration`, `system_instructions`, `permission_policy`, `execution_limits`, `required_approvals`, `version`, and `status`.

---

## Registered AI Workforce (20 Agents: 13 P0/P1 + 7 P2 Commercial)

| `agent_id` | Business Function | Phase | Allowed Tool Names (`supported_tools`) | HITL Approval Gates (`required_approvals`) |
|---|---|---|---|---|
| `ceo_manager_agent` | `governance_trust` | P0/P1 | `discovery_pipeline`, `research_synthesis`, `sales_draft`, `trust_seal` | `external_sales_outreach` |
| `discovery_sdr_agent` | `lead_discovery` | P0/P1 | `lead_search`, `lead_scoring`, `lead_dedupe` | `—` |
| `research_analyst_agent` | `research_intelligence` | P0/P1 | `source_synthesis`, `citation_builder`, `trust_seal` | `—` |
| `academic_research_agent` | `research_intelligence` | P0/P1 | `academic_synthesis`, `bibtex_formatter`, `trust_seal` | `—` |
| `sales_proposal_agent` | `sales_proposals` | P0/P1/P2 | `pain_diagnose`, `proposal_draft`, `approval_request`, `email_dispatch` | `external_sales_outreach` |
| `seo_content_agent` | `seo_content` | P0/P1 | `blog_generate`, `seo_stage_draft`, `wordpress_stage` | `—` |
| `marketing_creative_agent` | `marketing_campaigns` | P0/P1 | `social_campaign_generate`, `creative_pack_generate` | `—` |
| `support_followup_agent` | `customer_support` | P0/P1 | `ticket_triage`, `followup_draft`, `approval_request` | `customer_followup_dispatch` |
| `field_ops_agent` | `field_operations` | P0/P1 | `route_optimize`, `telemetry_summary` | `—` |
| `warehouse_stocksense_agent` | `inventory_quality` | P0/P1 | `inventory_abc_eoq`, `dead_stock_audit` | `—` |
| `quality_vision_agent` | `inventory_quality` | P0/P1 | `quality_grade`, `defect_scoring` | `—` |
| `mobility_rebalance_agent` | `inventory_quality` | P0/P1 | `mobility_forecast`, `rebalance_route` | `—` |
| `trust_governance_agent` | `governance_trust` | P0/P1 | `trust_seal`, `trust_verify`, `watchdog_scan` | `—` |
| `market_research_agent` | `research_intelligence` | P2 | `catalog_verify`, `source_lookup`, `claim_classifier` | `—` |
| `prospect_discovery_agent` | `lead_discovery` | P2 | `serper_search`, `google_places`, `website_enrich`, `domain_company_dedupe` | `—` |
| `lead_qualification_agent` | `lead_discovery` | P2 | `rubric_scorer`, `contact_validity_check`, `freshness_check` | `—` |
| `account_intelligence_agent` | `research_intelligence` | P2 | `dossier_reader`, `brief_generator`, `epistemic_classifier` | `—` |
| `outreach_preparation_agent` | `sales_proposals` | P2 | `suppression_check`, `rate_limit_check`, `honesty_validator`, `approval_request` | `external_sales_outreach` |
| `customer_onboarding_agent` | `customer_support` | P2 | `onboarding_checklist`, `entitlement_assign`, `input_collector` | `—` |
| `customer_success_agent` | `customer_support` | P2 | `workflow_delivery`, `feedback_capture`, `renewal_recommender` | `—` |

---

## Tenant Agent Lifecycle & Policy Enforcement

Tenant configuration is stored per `(org_id, agent_id)` in `tenant_agent_configs` (`TenantAgentConfigRecord`).

1. **Entitlement Check:** Activation via `POST /v1/registry/agents/{agent_id}/activate` verifies tenant subscription entitlements derived from the active package/modular selection (`entitled_agents` / `entitled_capabilities`).
2. **Lifecycle States:** `AVAILABLE` (catalog baseline), `ACTIVE`, `PAUSED`, `DEACTIVATED`, `EMERGENCY_STOPPED`.
3. **Least-Privilege Tool Allowlist:** Configuring or executing an agent (`PATCH /v1/registry/agents/{agent_id}/configure`, `POST /v1/registry/agents/{agent_id}/execute`) intersects tenant tool selections against `AGENT_REGISTRY[agent_id].supported_tools`. Out-of-scope tools are rejected (`HTTP 403` / `HTTP 400`).
4. **Atomic Credit Reservation:** Every execution reserves credits atomically (`reserve_execution_credits`), commits on completion (`commit_credit_reservation`), or refunds automatically (`refund_credit_reservation`) on failure or block (`SIMULATION` or `PRODUCTION`).
5. **Execution Evidence & History:** `GET /v1/registry/agents/{agent_id}/history` returns organization-scoped `ExecutionEvidenceRecord` rows with `execution_mode`, `output_origin`, `credits_consumed`, and redacted I/O references.
