# P2 Founder Operating Guide — Acquiring the First Paying Customer

This runbook explains how the founder operates **P2 Commercial Revenue OS** cleanly in production (`/app` -> *P2 Commercial Revenue OS* sidebar tab).

---

## 1. Pre-Flight Verification

1. Verify environment configuration (`APP_ENV=production`, strong `OWNER_API_KEY`, PostgreSQL migrated to `h8c3d4e5f6a7`).
2. Confirm connector capability states in the Control Centre strip:
   - `hostinger_smtp` (or verified SMTP relay) must be `LIVE_VERIFIED` before dispatching live emails.
   - `razorpay`, `paypal`, and/or `afw_directpay` settlement rails must have valid credentials / bank details configured.
3. Verify the commercial catalog offer via `GET /v1/commercial/offer/managed_seo_content_pilot`:
   - Price: `₹4,999 INR` / `$59 USD`
   - Billing Type: `managed_pilot_14d` (14-day pilot, manual renewal decision only)
   - Never promise #1 Google rankings, guaranteed ROI multiples, or unconfigured discounts.

---

## 2. Step-by-Step Daily Commercial Workflow

### Step A — Prospect Intake & Research (5–10 Real Indian Agencies)
- Use curated public sources (agency websites, Google Search/Maps, public directories) via **Tab 1: Prospects & Briefs**.
- Provide `source_url`, verified public contact email, city in India, actual agency services, and observable SEO/content needs.
- Review the 6-criterion qualification score breakdown (`icp_fit`, `need_evidence`, `activity_website_quality`, `service_fit`, `contact_validity`, `evidence_freshness`).
- Open the **Account Intelligence Brief** for shortlisted agencies:
  - Rely ONLY on items listed under **Verified Facts** when drafting personalized opening lines.
  - Use **Unverified Assumptions** strictly as agenda items to confirm during discovery.

### Step B — Honest Outreach Under Owner Approval (HITL)
- Click **Select** -> fill optional factual context -> click **Draft & Request Owner Approval** (`POST /v1/commercial/outreach/prepare`).
- Reject/avoid invented call backreferences, #1 guarantees, or discount timers (enforced automatically by the integrity validator).
- Open **HITL Approvals**, inspect the exact recipient and body text, approve (`POST /v1/approvals/{id}/decision`), and then click **Dispatch Approved Draft**.
- Check receipt status: only **`SENT`** (`external_sent: true`) counts toward live outreach KPIs.

### Step C — Response Triage, Discovery & Opt-Out Discipline
- When a prospect replies:
  - Record replies honestly in **Tab 2: Log Prospect Response & Discovery Notes**.
  - If they decline or ask to opt out, choose `not_interested` or `unsubscribe` immediately so `p2_suppression_entries` and `DO_NOT_CONTACT` block all further contact permanently.
  - For interested replies, record verified pain points and CMS details into **Discovery Notes**.

### Step D — Proposal -> Owner Approval -> Verified Settlement
- Generate a structured proposal in **Tab 3** (`POST /v1/commercial/proposals`), citing confirmed discovery pain points and matching `managed_seo_content_pilot` catalog terms.
- Approve the proposal in **HITL Approvals**, click **Share Approved Proposal**, and generate a **DirectPay** (`afw_directpay`) or **Razorpay** (`razorpay`) checkout link.
- Wait for real buyer settlement (webhook capture or UTR confirmation). **Never** manually toggle a deal to `WON` without verified settlement in the Payment Reconciliation Queue.

### Step E — Onboarding, Delivery, Feedback & Renewal
- Once settlement provisions the client engagement (`ONBOARDING_PENDING_INPUTS`), capture client domain, CMS delivery mode, and priority SEO topics in **Tab 4**.
- Trigger **Run Pilot Delivery Workflow** to generate the technical audit, keyword cluster, 2 human-review drafts, and JSON-LD bundle.
- Review every output manually, deliver to the buyer, record delivery handover proof via **Mark Client Delivery Completed**, and gather genuine post-pilot feedback + non-auto-charged renewal evaluation.
