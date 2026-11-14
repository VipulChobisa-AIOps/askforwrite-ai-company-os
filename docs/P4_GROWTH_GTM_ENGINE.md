# P4 Repeatable Growth & GTM Engine — AskforWrite AI Company OS

**Branch:** `feat/p4-growth-gtm-engine`  
**Alembic Head Revision:** `j0e5f6a7b8c9` (down revision `i9d4e5f6a7b8`)  
**Primary Service:** `app/services/p4_growth_gtm.py`  
**API Router:** `/v1/p4/growth/*` (`app/api/v1/p4_growth.py`)

---

## 1. Marketing Claim Integrity & Remediation

Previously hardcoded unverified uplift, guarantee, and multiplier strings in `app/services/growth_engine.py` and `app/services/previews.py` (`+340% Revenue Growth`, `80% CAC reduction`, `99.4% within 3s`, `10x ROI`, `8x ROI`, `guaranteed inclusion`, `100% refund`, `0 proxy attendance`) were audited and replaced with architecture-grounded descriptions and explicitly labeled illustrative sandbox baselines.

`check_gtm_copy_safety` combines `validate_outreach_integrity` (shared P2 core integrity filter) with extended claim-safety checks to block exaggerated percentages, refund promises, or unverified guarantees across ICP value propositions and GTM campaigns.

---

## 2. Data Model (`j0e5f6a7b8c9`)

1. `p4_icp_profiles` — Tenant-scoped Ideal Customer Profiles with buyer personas, pain points, disqualifiers, and deterministic fit scoring (`/v1/p4/growth/icps/{id}/score`).
2. `p4_market_intel_records` — Market, competitor, keyword-gap, and win/loss records requiring `source_url` (SSRF-validated) and `evidence_ref` provenance before `VERIFIED_SOURCE` classification.
3. `p4_growth_campaigns` — Multi-channel campaigns linked directly to shared `approval_requests` (`action="p4_gtm_campaign_launch"`). Execution in `SIMULATION` or `LIVE` is blocked until Owner/authorized HITL `APPROVED` decision exists.
4. `p4_pipeline_deals` — Stage-tracked deals (`DISCOVERED -> QUALIFIED -> DISCOVERY_CALL -> PROPOSAL_SENT -> NEGOTIATION -> WON/LOST`) with mandatory structured `lost_reason` on `LOST` and strict `evidence_status` (`ACTUAL` vs `SANDBOX`) separation.

---

## 3. Honest Analytics & Unified Dashboard Integration

- `compute_gtm_funnel_analytics` (`GET /v1/p4/growth/analytics`) strictly separates `actual_verified` from `sandbox_and_simulation` deals and returns `win_rate_pct: null` when closed deals equal `0`.
- Registered P4 agents `gtm_strategist_agent` and `competitive_intel_agent` in `app/services/registry.py`.
- Added `#nav-p4-growth` and `#page-p4-growth` to the unified Control Center UI (`app/dashboard/index.html`, `app/dashboard/dashboard.js`).
