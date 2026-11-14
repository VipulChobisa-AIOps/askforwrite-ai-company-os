# P2 Real-World Acceptance Checklist (12 Steps)

Tracked live in database table `p2_acceptance_checklist_steps` and exposed in `/app` under **P2 Commercial Revenue OS -> Tab 5: 12-Step Acceptance Checklist** (`GET /v1/commercial/acceptance-checklist`, `POST /v1/commercial/acceptance-checklist/{step_number}`).

Statuses strictly distinguish:
- `NOT_TESTED` (initial default on every environment until explicitly verified)
- `SANDBOX_VERIFIED` (verified end-to-end in staging/test harness with deterministic guards)
- `LIVE_VERIFIED` (verified against a genuine external prospect/buyer in production with immutable proof)

---

## Manual Verification Procedure (Steps 1–12)

| # | Key | Verification Requirement | How to Verify & Record Proof |
|---|---|---|---|
| **1** | `env_connectors_creds` | Configure environment, DB (`h8c3d4e5f6a7`), connectors, and credentials | Run `alembic current`, check `/v1/commercial/control-centre` connector states (`LIVE_VERIFIED` SMTP/payment webhooks). |
| **2** | `verify_catalog_sku` | Confirm `managed_seo_content_pilot` price (INR 4,999 / USD 59), billing type (`managed_pilot_14d`), and scope | Inspect `GET /v1/commercial/offer/managed_seo_content_pilot`; attach response JSON snapshot. |
| **3** | `discover_ingest_agencies` | Discover or ingest 5–10 real Indian digital marketing / SEO agencies | Submit agencies via `POST /v1/commercial/prospects/ingest` with real source URLs & verified public contacts. |
| **4** | `review_briefs_and_qualify` | Inspect 6-criterion qualification breakdown & Account Intelligence Briefs | Generate briefs via `POST /v1/commercial/prospects/{lead_id}/brief`; verify facts vs assumptions are accurately separated. |
| **5** | `approve_first_outreach` | Draft honest outreach & approve via Owner HITL gate | Prepare via `POST /v1/commercial/outreach/prepare` and approve in `/v1/approvals/{id}/decision`. |
| **6** | `send_live_outreach` | Send live outreach via `hostinger_smtp` in production mode | Dispatch via `POST /v1/commercial/outreach/{id}/dispatch`; record SMTP `message_id` receipt proving `SENT` (`external_sent: true`). |
| **7** | `log_real_reply_discovery` | Capture genuine buyer reply & discovery notes | Submit via `POST /v1/commercial/pipeline/{lead_id}/responses` with actual reply summary & discovery pain points. |
| **8** | `approve_share_proposal` | Build 8-clause catalog-backed proposal, approve HITL, and share | Create -> Approve HITL -> Share (`POST /v1/commercial/proposals/{id}/share`); verify pricing & clauses match discovery. |
| **9** | `verify_real_payment` | Initiate verified checkout & settle real payment (INR 4,999 / USD 59) | Confirm settlement via signed Razorpay/PayPal webhook or AFW DirectPay UTR confirmation (`ACTIVATION_COMPLETED`). |
| **10** | `confirm_onboarding_activation` | Confirm tenant provisioning, entitlements, and required client onboarding inputs | Inspect engagement in `GET /v1/commercial/engagements` and submit onboarding inputs (`POST /v1/commercial/engagements/{id}/onboarding`). |
| **11** | `complete_pilot_delivery` | Execute pilot delivery workflow, human-review artifacts, and confirm buyer handover | Run `/deliver`, review generated audit/cluster/2 articles/schema, and confirm delivery via `/complete-delivery`. |
| **12** | `record_feedback_and_renewal` | Capture genuine post-pilot buyer feedback & renewal evaluation | Record buyer rating & comments via `/feedback-renewal`; confirm `auto_charge_disabled=true` and record commercial outcome. |
