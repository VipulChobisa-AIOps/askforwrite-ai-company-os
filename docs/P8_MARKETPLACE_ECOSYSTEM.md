# Phase P8 — Third-Party Marketplace Ecosystem

**Branch:** `feat/p8-marketplace-ecosystem`  
**Migration:** `n4c9d0e1f2a3` (`down_revision="m3b8c9d0e1f2"`)  
**Primary Service:** `app/services/p8_marketplace.py`  
**API Routers:** `/v1/p8/marketplace/*` and `/v1/ops/roadmap-scorecard` (`app/api/v1/p8_marketplace.py`)

---

## Objectives Delivered

1. **Developer Onboarding & KYB Gate (`p8_developer_profiles`)**
   - Third-party developers register in `PENDING` KYB state with masked payout details (`payout_account_masked`).
   - Only Owner-reviewed `VERIFIED` developers can submit packages to the marketplace (`403` if `PENDING`, `REJECTED`, or `SUSPENDED`).

2. **Permission-Scoped, Cryptographically Signed Listings (`p8_marketplace_listings`)**
   - Package types restricted to `AGENT_PLUGIN`, `CONNECTOR_ADAPTER`, and `WORKFLOW_PACK`.
   - Requested permissions validated strictly against `ALLOWED_PLUGIN_PERMISSIONS` (`read_icps`, `read_metrics`, `stage_content`, `run_sandbox_diagnostics`, `emit_webhook`), rejecting wildcard or administrative scopes (`422`).
   - External endpoints pass SSRF checks (`validate_external_url`), and listing copy passes `check_gtm_copy_safety`.
   - Canonical manifests are hashed with SHA-256 and signed with the node ECDSA NIST P-256 key (`app.security.ecdsa_pki.sign_block`).
   - Security review and publishing (`review_marketplace_listing`) require Owner role + `security_review_status="APPROVED"` + valid cryptographic verification, sealing a `TrustChain` block.

3. **Tenant-Isolated Installation & Non-Plaintext Secret Isolation (`p8_tenant_installs`)**
   - Installations verify `PUBLISHED` + `APPROVED` status and re-verify both SHA-256 manifest digest and ECDSA P-256 signature on install (`403` on tampered or unverified manifests).
   - Tenant-granted permissions cannot exceed the security-reviewed manifest.
   - Customer secrets are converted into masked previews (`••••1234`) plus org-scoped SHA-256 digests (`secret_digests_json`); raw plaintext secrets are never stored or returned.

4. **Verified-Installer Reviews, Moderation & Revenue-Share Ledger (`p8_marketplace_reviews`, `p8_revenue_share_ledger`)**
   - Only tenants with a recorded installation of a listing may submit ratings/reviews (`403` otherwise).
   - Owner abuse moderation (`PUBLISHED`, `FLAGGED_UNDER_REVIEW`, `REMOVED`) hides removed reviews from default listings.
   - Marketplace commission splits (`commission_bps` 500–3000) strictly segregate `SANDBOX` from `ACTUAL` revenue entries.

5. **Agent, Scorecard & Unified Control Center UI**
   - Registered `marketplace_curator_agent` in `app/services/registry.py`.
   - Added `/v1/ops/roadmap-scorecard` aggregating P0–P8 state while preserving P3.1 production cutover blockers.
   - Wired `#nav-p8-marketplace` and `#page-p8-marketplace` (`p8LoadControlCentre`, `p8BindEvents`) in `app/dashboard/index.html` and `app/dashboard/dashboard.js`.

## Verification Scope Notes
- Tested locally using FastAPI `TestClient` against isolated SQLite databases and Playwright headless Chromium tests; no live third-party payouts or production marketplace transactions have been executed.
- Authoritative P3.1 release readiness remains `BLOCKED` (`production_cutover_approved: false`).
