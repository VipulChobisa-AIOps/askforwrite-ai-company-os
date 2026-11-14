# P2 Commercial Data Model & API Reference

**Alembic Revision Head:** `h8c3d4e5f6a7` (depends on `g7b2c3d4e5f6`)  
**Router Prefix:** `/v1/commercial/*` (`app/api/v1/commercial.py`)

---

## 1. Database Schema (`migrations/versions/h8c3d4e5f6a7_add_p2_commercial_revenue_engine_tables.py`)

| Table Name | SQLAlchemy Model (`app/db/models.py`) | Purpose |
|---|---|---|
| `p2_prospect_dossiers` | `P2ProspectDossierRecord` | Agency profile, deduplicated `normalized_domain` & `normalized_company_key`, source provenance, 6-criterion qualification breakdown, epistemic research claims & briefs, 12-status commercial stage, and response history. |
| `p2_commercial_proposals` | `P2CommercialProposalRecord` | 8-clause catalog-backed commercial proposals linked to Owner `ApprovalRequest`, share timestamps, and verified checkout URLs/sessions. |
| `p2_suppression_entries` | `P2SuppressionEntryRecord` | Persistent email & domain opt-out / `DO_NOT_CONTACT` registry enforced before outreach preparation and dispatch. |
| `p2_payment_reconciliation_queue` | `P2PaymentReconciliationRecord` | Tracks checkout initiation -> webhook/DirectPay verification -> tenant provisioning -> engagement activation, replay deduplication, retry counters, and `REFUNDED`/`DISPUTED`/`FAILED` transitions. |
| `p2_customer_engagements` | `P2CustomerEngagementRecord` | Post-payment tenant onboarding checklist, required client inputs, P1 `WorkflowRunRecord` linkage, deliverable artifacts, completion proof, buyer feedback, and renewal recommendation. |
| `p2_acceptance_checklist_steps` | `P2AcceptanceStepRecord` | Persistent 12-step real-world pilot acceptance tracker (`NOT_TESTED`, `SANDBOX_VERIFIED`, `LIVE_VERIFIED`). |

---

## 2. API Endpoints Summary

### Offer, Discovery & Qualification
| Method & Path | Role | Purpose |
|---|---|---|
| `GET /v1/commercial/offer/{sku_key}` | Manager+ | Returns catalog-verified SKU pricing, billing type, deliverables, and explicit non-guarantees. |
| `POST /v1/commercial/prospects/ingest` | Manager+ | Validates, deduplicates (domain + company), rejects synthetic fixtures, and scores a genuine India agency prospect. |
| `POST /v1/commercial/prospects/discover` | Owner | Runs configured live search discovery in `PRODUCTION` with `LIVE_VERIFIED` connector; returns honest `BLOCKED` status otherwise. |
| `GET /v1/commercial/prospects` | Manager+ | Lists non-synthetic prospect dossiers ordered by qualification score. |
| `POST /v1/commercial/prospects/{lead_id}/requalify` | Manager+ | Recomputes 6-criterion qualification score using configurable criteria weights. |
| `POST /v1/commercial/prospects/{lead_id}/brief` | Manager+ | Generates Account Intelligence Brief separating `verified_facts`, `reasonable_inferences`, and `unverified_assumptions`. |

### Outreach, Responses & 12-Stage Pipeline
| Method & Path | Role | Purpose |
|---|---|---|
| `POST /v1/commercial/outreach/prepare` | Manager+ | Runs honesty claim validator, DB suppression check, duplicate check, rate limits, and queues `PENDING_APPROVAL` + `ApprovalRequest`. |
| `POST /v1/commercial/outreach/{outreach_id}/dispatch` | Owner | Sends Owner-approved outreach cleanly (`SENT` when live provider executes; `SIMULATED_SENT` in simulation mode). |
| `GET /v1/commercial/pipeline` | Manager+ | Returns unified 12-stage commercial pipeline view (dossiers, latest outreach, latest proposal, customer engagement). |
| `POST /v1/commercial/pipeline/{lead_id}/transition` | Owner | Audit-logged transition across any of the 12 P2 pipeline statuses (`DO_NOT_CONTACT` updates DB suppression). |
| `POST /v1/commercial/pipeline/{lead_id}/responses` | Manager+ | Records real prospect reply with source provenance and optional discovery notes; auto-suppresses opt-outs. |

### Structured Proposals, Checkout & Payment Reconciliation
| Method & Path | Role | Purpose |
|---|---|---|
| `POST /v1/commercial/proposals` | Manager+ | Builds 8-clause proposal verified against catalog SKU pricing and creates `proposal_delivery` HITL approval. |
| `GET /v1/commercial/proposals` | Manager+ | Lists structured P2 proposals and HITL approval states. |
| `POST /v1/commercial/proposals/{proposal_id}/share` | Owner | Shares an Owner-approved proposal with buyer (`SHARED`) and attaches verified payment link. |
| `POST /v1/commercial/proposals/{proposal_id}/checkout` | Owner | Creates checkout session (`afw_directpay`, `razorpay`, or `paypal`) + `CHECKOUT_CREATED` reconciliation row without activating tenant. |
| `GET /v1/commercial/reconciliation` | Manager+ | Inspects payment reconciliation queue, verification state, retry counts, and activation IDs. |
| `POST /v1/commercial/reconciliation/{reconciliation_id}/retry` | Owner | Retries activation only if verified received amount satisfies catalog SKU price. |

### Customer Activation, Delivery, Control Centre & Acceptance Tracker
| Method & Path | Role | Purpose |
|---|---|---|
| `GET /v1/commercial/engagements` | Manager+ | Lists paid customer engagements and checklists. |
| `POST /v1/commercial/engagements/{engagement_id}/onboarding` | Manager+ | Captures required client domain, CMS mode, and priority SEO topics (`ONBOARDING_READY`). |
| `POST /v1/commercial/engagements/{engagement_id}/deliver` | Manager+ | Launches P1 pilot delivery workflow; stages audit, cluster, 2 articles, and JSON-LD without premature completion. |
| `POST /v1/commercial/engagements/{engagement_id}/complete-delivery` | Owner | Marks engagement `DELIVERY_COMPLETED` with handover proof and ECDSA TrustBlock seal. |
| `POST /v1/commercial/engagements/{engagement_id}/feedback-renewal` | Manager+ | Stores buyer rating/comments and issues non-auto-charging renewal recommendation (`auto_charge_disabled=True`). |
| `GET /v1/commercial/control-centre` | Manager+ | Returns strictly separated `verified_commercial_metrics`, `simulation_and_test_metrics`, and `capability_status_summary`. |
| `GET /v1/commercial/acceptance-checklist` | Manager+ | Returns the 12-step real-world verification checklist and summary counts. |
| `POST /v1/commercial/acceptance-checklist/{step_number}` | Owner | Saves verified evidence and status (`NOT_TESTED` / `SANDBOX_VERIFIED` / `LIVE_VERIFIED`). |
