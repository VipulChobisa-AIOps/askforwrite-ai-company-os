# P3.1 Browser End-to-End (Playwright) Verification Report

**Suite Location:** `tests/e2e/test_dashboard_e2e.py`  
**Dependency:** `playwright` (`pytest` plugin `playwright-0.10.0`, Chromium browser)  
**Verification State:** **`LOCAL_VERIFIED`** (synthetic isolated Uvicorn + SQLite test environment)  
**Production Live Smoke State:** **`NOT_TESTED`**

---

## 1. Isolated Test Harness Design

`live_e2e_server` launches an isolated Uvicorn subprocess bound to an ephemeral localhost port using a temporary SQLite database in `tempfile.TemporaryDirectory`, with:
- `dotenv.load_dotenv` disabled so host `.env` live keys or Neon DB are never loaded.
- `APP_ENV=development`, `ALLOW_LIVE_SIDE_EFFECTS=false`, `ENABLE_EXTERNAL_SIDE_EFFECTS=false`.
- Synthetic seeded agency account (`Acme Digital Agency`), an empty customer org (for empty-state verification), a seeded `TenantSubscriptionRecord` (`growth`), seeded onboarding steps, service deliverable (`DELIVERED` awaiting customer acceptance), and an approval request (`PENDING` & `REJECTED` filter checks).

Telemetry listeners capture `pageerror`, HTTP 5xx responses, failed requests (outside intentional offline tests), and console errors throughout every user flow.

---

## 2. Verified Scenarios & Viewports

### A. Desktop (`1440x900`) — Customer Portal, Empty, Error, & Offline States
Test: `test_desktop_auth_empty_error_offline_and_customer_portal_e2e`
1. Invalid password login keeps `#auth-gate-overlay` open and displays `#auth-gate-message`.
2. Empty customer login verifies:
   - Unauthorized admin navigation links (`#nav-dashboard`, `#nav-organizations`, `#nav-revenue`, `#nav-commercial-os`, `#nav-customer-success`) remain hidden.
   - Empty deliverable and support ticket states render honestly (`No service deliverables`, `No support tickets`).
   - Subscription/billing contracts load in `#nav-cw-billing` (`launch`, `growth`).
   - Logout restores `#auth-gate-overlay`.
3. Agency customer login verifies:
   - Completing an onboarding checklist task updates `#portal-p3-onboarding-summary`.
   - Accepting a `DELIVERED` item updates status to `ACCEPTED`.
   - Intercepting `POST /v1/me/support/tickets` with HTTP `500` shows `#portal-p3-error` without displaying any fake success banner; unrouting allows real persistence into `#portal-p3-tickets-list`.
   - Offline mode (`context.set_offline(True)` + `offline` event) renders explicit offline state with zero simulated success.

### B. Desktop (`1440x900`) — Owner Lifecycle, Delivery, Health, Tickets, Renewals, & Approvals
Test: `test_desktop_owner_lifecycle_delivery_health_tickets_renewals_and_approvals_e2e`
1. Invalid `OWNER_API_KEY` rejects unlock; valid key reveals `#nav-customer-success`.
2. Approvals page verifies empty `REJECTED` filter, then opens approval modal (`#modal-overlay`), submits approval (`#btn-approve`), waits for modal dismissal, and verifies item moves to `#filter-approved`.
3. Customer Success Control Centre renders KPIs, Customer 360 table rows, creates a deliverable (`Playwright Verified Keyword Map`), computes Customer Health score (`HEALTHY`/`NEEDS_ATTENTION`/`AT_RISK`/`INSUFFICIENT_DATA`), resolves the customer-submitted support ticket to `RESOLVED`, displays active subscription in `#p3-renewals-tbody` and Net Verified Revenue in `#p3-ue-viewer`, and loads Ops Readiness & 12-Step Checklist.
4. Logout cleanly returns to `#auth-gate-overlay`.

### C. Mobile (`390x844`) — Responsive Drawer & Customer Portal
Test: `test_mobile_viewport_navigation_and_cs_workflows_e2e`
1. Owner unlock, opening `#sidebar` drawer via `#menu-toggle`, navigating to `#nav-customer-success` (auto-closing drawer), switching P3 subtabs (`health-support`, `subs-growth-ue`), logging out via drawer, and logging into the mobile customer portal.

---

## 3. Defects Found & Fixed During Playwright Verification

- **Sidebar CSS visibility race (`#nav-approvals`):** After login, `.sidebar` transitions `visibility: hidden -> visible` while `.nav-item` inherits CSS transitions (`250ms`), briefly leaving `#nav-approvals` reporting `hidden` right after `#auth-gate-overlay` closed; test now awaits `page.locator("#nav-approvals").wait_for(state="visible")` before asserting visibility rules.
- **Renewals table test fixture vs table schema:** `#p3-renewals-tbody` displays `Org | SKU | Billing | Renewal | Status` (`TenantSubscriptionRecord`) rather than payment gateway provider names; synthetic seeding now creates a `growth` `TenantSubscriptionRecord` and asserts `org_id` + `ACTIVE`.

---

## 4. Remaining Gap

- Live Render/staging URL has not been smoke-tested in Playwright because `https://os.askforwrite.com/health` and `https://askforwrite-ai-company-os.onrender.com/health` timed out at `35s+` during verification (`BLOCKED`).
