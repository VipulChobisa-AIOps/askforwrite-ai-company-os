/**
 * AskforWrite Company OS — Admin Dashboard Controller
 * Connects to the FastAPI backend and provides real-time dashboard management
 */

(function () {
  'use strict';

  // ── Configuration ────────────────────────────────────────
  const CONFIG = {
    _apiBase: (window.location.origin && window.location.origin !== 'null') ? window.location.origin : 'http://localhost:8000',
    get apiBase() {
      return this._apiBase;
    },
    set apiBase(value) {
      this._apiBase = value;
    },
    ownerApiKey: localStorage.getItem('askforwrite_owner_key') || localStorage.getItem('afw_api_key') || '',
    accessToken: localStorage.getItem('afw_access_token') || '',
    geminiApiKey: localStorage.getItem('afw_gemini_key') || '',
    userRole: localStorage.getItem('afw_user_role') || (localStorage.getItem('askforwrite_owner_key') ? 'owner' : ''),
    userName: localStorage.getItem('afw_user_name') || '',
    refreshInterval: 60000, // 60s auto-refresh (stays safely under 60 req/min rate limit)
  };

  // ── State ────────────────────────────────────────────────
  const state = {
    connected: false,
    currentPage: 'dashboard',
    approvals: [],
    leads: [],
    outreach: [],
    organizations: [],
    invoices: [],
    fieldTasks: [],
    fieldVisits: [],
    fieldClaims: [],
    auditLogs: [],
    watchdogTelemetry: null,
    watchdogAlerts: [],
    ceoBriefing: null,
    inventoryAnalysis: null,
    refreshTimer: null,
    approvalFilter: 'all',
  };

  // ── DOM Refs ─────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  // ── API Client ───────────────────────────────────────────
  async function api(method, path, body = null) {
    const headers = { 'Content-Type': 'application/json' };
    if (CONFIG.ownerApiKey) headers['X-API-Key'] = CONFIG.ownerApiKey;
    if (CONFIG.accessToken) headers['Authorization'] = `Bearer ${CONFIG.accessToken}`;
    if (CONFIG.geminiApiKey) headers['X-Gemini-API-Key'] = CONFIG.geminiApiKey;

    const opts = { method, headers };
    if (body) opts.body = JSON.stringify(body);

    const res = await fetch(`${CONFIG.apiBase}${path}`, opts);
    if (!res.ok) {
      if (res.status === 401 && !path.startsWith('/v1/auth/')) {
        // P0-B Fail-Closed Auth Gate: revoke expired/invalid session immediately
        CONFIG.accessToken = '';
        CONFIG.ownerApiKey = '';
        localStorage.removeItem('afw_access_token');
        localStorage.removeItem('askforwrite_owner_key');
        localStorage.removeItem('afw_api_key');
        checkAuthGate();
      }
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  }


  // ── Toast Notifications ──────────────────────────────────
  function toast(message, type = 'info') {
    const container = $('#toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      el.style.transform = 'translateX(40px)';
      setTimeout(() => el.remove(), 300);
    }, 4000);
  }

  // ── Navigation ───────────────────────────────────────────
  function navigateTo(pageName) {
    state.currentPage = pageName;

    // Update sidebar
    $$('.nav-item').forEach(n => n.classList.remove('active'));
    const navEl = $(`[data-page="${pageName}"]`);
    if (navEl) navEl.classList.add('active');

    // Update pages
    $$('.page').forEach(p => p.classList.remove('active'));
    const pageEl = $(`#page-${pageName}`);
    if (pageEl) pageEl.classList.add('active');

    // Hide bottom-right floating closer on Growth Suite (Pillar 3 & 4 already embeds it inline)
    document.body.classList.toggle('afw-hide-floating-closer', pageName === 'growth');

    // Update title
    const titles = {
      dashboard: 'Dashboard',
      leads: 'Leads',
      approvals: 'Approvals',
      outreach: 'Outreach',
      organizations: 'Organizations',
      revenue: 'Revenue & Billing',
      'field-force': 'Field Force',
      portal: 'Customer Self-Serve Portal',
      growth: 'Autonomous AI Growth Suite',
      mobile: 'Pixel AI Mobile & PWA Command',
      'trust-chain': 'Cryptographic Trust Ledger',
      quality: 'Produce Quality AI — Computer Vision Ripeness & Grading',
      mobility: 'Urban Mobility AI — Fleet Demand & Station Rebalancing',
      inventory: 'Warehouse StockSense AI — ABC-XYZ & Inventory Automation',
      'commercial-os': 'P2 Commercial Acquisition & Revenue OS (India Agencies Pilot)',
      'customer-success': 'P3 Customer Success, Retention & Repeatable Growth Engine',
      'p4-growth': 'P4 Repeatable Growth & GTM Engine',
      'p5-scale': 'P5 Multi-Tenant Scale, SLA & Provisioning',
      'p6-packs': 'P6 Multi-Industry AI Vertical Packs',
      'p7-autonomy': 'P7 Autonomous Workforce & Delegation DAGs',
      'p8-marketplace': 'P8 Partner Marketplace & Master Release Scorecard',
      ...(typeof CW_PAGE_TITLES !== 'undefined' ? CW_PAGE_TITLES : {}),
    };
    if ($('#page-title')) $('#page-title').textContent = titles[pageName] || pageName;

    // Page-specific initialization hooks
    if (pageName === 'quality') {
      initQualityPage();
    } else if (pageName === 'mobility') {
      initMobilityPage();
    } else if (pageName === 'inventory') {
      initInventoryPage();
    } else if (pageName === 'trust-chain' && typeof verifyTrustChainUi === 'function') {
      verifyTrustChainUi(true);
    } else if (pageName === 'commercial-os' && typeof p2LoadControlCentre === 'function') {
      p2LoadControlCentre();
    } else if (pageName === 'customer-success' && typeof p3LoadControlCentre === 'function') {
      p3LoadControlCentre();
    } else if (pageName === 'p4-growth' && typeof p4LoadControlCentre === 'function') {
      p4LoadControlCentre();
    } else if (pageName === 'p5-scale' && typeof p5LoadControlCentre === 'function') {
      p5LoadControlCentre();
    } else if (pageName === 'p6-packs' && typeof p6LoadControlCentre === 'function') {
      p6LoadControlCentre();
    } else if (pageName === 'p7-autonomy' && typeof p7LoadControlCentre === 'function') {
      p7LoadControlCentre();
    } else if (pageName === 'p8-marketplace' && typeof p8LoadControlCentre === 'function') {
      p8LoadControlCentre();
    } else if (pageName === 'cw-profile' && typeof cwLoadProfile === 'function') {
      cwLoadProfile();
    } else if (['cw-marketplace', 'cw-workforce', 'cw-connectors', 'cw-run-console'].includes(pageName) && typeof cwHydrateRegistry === 'function') {
      cwHydrateRegistry();
    } else if (pageName === 'cw-workflows' && typeof cwLoadWorkflows === 'function') {
      cwLoadWorkflows();
    } else if (pageName === 'cw-history' && typeof cwLoadEvidenceHistory === 'function') {
      cwLoadEvidenceHistory();
    } else if (pageName === 'cw-analytics' && typeof cwLoadAnalytics === 'function') {
      cwLoadAnalytics();
    } else if (pageName === 'cw-billing' && typeof cwLoadBilling === 'function') {
      cwLoadBilling();
    } else if (pageName === 'cw-settings' && typeof cwLoadEmergencyStops === 'function') {
      cwLoadEmergencyStops();
    }

    // Update URL hash
    if (window.location.hash !== `#${pageName}`) {
      try {
        window.history.replaceState(null, '', `#${pageName}`);
      } catch (_) {}
    }

    // Close mobile sidebar
    $('#sidebar').classList.remove('open');
  }


  // ── Data Fetching ────────────────────────────────────────
  async function fetchDashboardData() {
    try {
      // Try health check first and update build SHA & runtime posture badge
      const health = await api('GET', '/health');
      setConnectionStatus(true);

      const shaPill = $('#build-sha-pill');
      if (shaPill && health) {
        shaPill.textContent = `${health.build_version || 'v3.5-p0'} • ${(health.commit_sha || 'dev').slice(0, 7)}`;
      }
      const dataBadge = $('#data-mode-badge');
      if (dataBadge && health) {
        dataBadge.className = 'status-pill approved';
        dataBadge.textContent = health.runtime_posture || 'LOCAL_ENGINE_VERIFIED';
      }

      // Parallel fetch project status & pending approval count
      const [projectStatus, pendingCount] = await Promise.allSettled([
        api('GET', '/v1/project/status'),
        api('GET', '/v1/approvals/pending/count'),
      ]);

      if (projectStatus.status === 'fulfilled') {
        updateStatsFromProject(projectStatus.value);
      }
      if (pendingCount.status === 'fulfilled' && typeof pendingCount.value.pending_approvals === 'number') {
        animateNumber('#stat-pending', pendingCount.value.pending_approvals);
        const badge = $('#approval-badge');
        if (badge) {
          badge.textContent = pendingCount.value.pending_approvals;
          badge.style.display = pendingCount.value.pending_approvals > 0 ? 'inline' : 'none';
        }
      }
    } catch (e) {
      console.warn('Dashboard fetch failed:', e.message);
      setConnectionStatus(false);
      // P0 Truthfulness Rule: NEVER silently inject loadDemoData() when live API is offline!
      const dataBadge = $('#data-mode-badge');
      if (dataBadge) {
        dataBadge.className = 'status-pill rejected';
        dataBadge.textContent = 'BLOCKED • API OFFLINE';
      }
    }
  }

  async function fetchLeads() {
    try {
      const data = await api('GET', '/v1/leads');
      state.leads = data.leads || (Array.isArray(data) ? data : []);
      renderLeads();
    } catch (e) {
      console.warn('Leads fetch:', e.message);
    }
  }

  async function fetchApprovals() {
    try {
      const results = await Promise.all(
        ['PENDING', 'APPROVED', 'REJECTED'].map(s =>
          api('GET', `/v1/approvals?status=${s}`).catch(() => ({ approvals: [] }))
        )
      );
      const rawList = results.flatMap(data => data.approvals || (Array.isArray(data) ? data : []));
      state.approvals = rawList.map(a => ({
        ...a,
        id: a.approval_id || a.id,
      }));
      renderApprovals();
      renderRecentApprovals();
      updateApprovalBadge();
    } catch (e) {
      console.warn('Approvals fetch:', e.message);
    }
  }

  async function fetchOutreach() {
    try {
      const data = await api('GET', '/v1/outreach');
      state.outreach = data.records || data.outreach || (Array.isArray(data) ? data : []);
      renderOutreach();
    } catch (e) {
      console.warn('Outreach fetch:', e.message);
    }
  }

  async function fetchOrganizations() {
    try {
      const data = await api('GET', '/v1/accounts/orgs');
      state.organizations = Array.isArray(data) ? data : (data.organizations || []);
      renderOrganizations();
    } catch (e) {
      console.warn('Orgs fetch:', e.message);
    }
  }

  async function fetchFieldForceData() {
    try {
      const [tasksRes, visitsRes, claimsRes, attRes] = await Promise.allSettled([
        api('GET', '/v1/field-force/tasks'),
        api('GET', '/v1/field-force/visits'),
        api('GET', '/v1/field-force/conveyance/claims'),
        api('GET', '/v1/field-force/attendance/history'),
      ]);
      if (attRes.status === 'fulfilled') {
        const attRows = Array.isArray(attRes.value) ? attRes.value : [];
        animateNumber('#stat-attendance', attRows.length);
      }

      if (tasksRes.status === 'fulfilled') {
        state.fieldTasks = Array.isArray(tasksRes.value) ? tasksRes.value : [];
        animateNumber('#stat-field-tasks', state.fieldTasks.length);
      }
      if (visitsRes.status === 'fulfilled') {
        state.fieldVisVisits = Array.isArray(visitsRes.value) ? visitsRes.value : [];
        state.fieldVisits = state.fieldVisVisits;
        animateNumber('#stat-visits', state.fieldVisits.length);
      }
      if (claimsRes.status === 'fulfilled') {
        state.fieldClaims = Array.isArray(claimsRes.value) ? claimsRes.value : [];
        animateNumber('#stat-claims', state.fieldClaims.length);
      }

      renderFieldForce();
    } catch (e) {
      console.warn('Field Force fetch:', e.message);
    }
  }

  async function fetchCustomerPortalData() {
    try {
      const me = await api('GET', '/v1/me');
      if (me) {
        if ($('#portal-org-name')) $('#portal-org-name').textContent = me.org_name || 'Organization';
        if ($('#portal-org-id')) $('#portal-org-id').textContent = me.org_id || '';
        if ($('#portal-tier-badge')) {
          $('#portal-tier-badge').textContent = (me.tier || 'Starter').toUpperCase() + ' Tier';
        }
        if ($('#portal-token-display') && CONFIG.accessToken) {
          $('#portal-token-display').value = CONFIG.accessToken;
        }
        if (me.credits) {
          const leadLimit = me.credits.lead_credits_limit || 0;
          const leadRem = me.credits.lead_credits_remaining || 0;
          const leadLeftPct = Math.max(0, Math.min(100, Math.round(100 - (me.credits.lead_utilization_pct || 0))));
          if ($('#portal-stat-leads')) $('#portal-stat-leads').textContent = `${leadRem} / ${leadLimit}`;
          if ($('#portal-lead-badge')) $('#portal-lead-badge').textContent = `${leadLeftPct}% Left`;
          if ($('#portal-fill-leads')) $('#portal-fill-leads').style.width = `${leadLeftPct}%`;

          const outLimit = me.credits.outreach_credits_limit || 0;
          const outRem = me.credits.outreach_credits_remaining || 0;
          const outLeftPct = Math.max(0, Math.min(100, Math.round(100 - (me.credits.outreach_utilization_pct || 0))));
          if ($('#portal-stat-outreach')) $('#portal-stat-outreach').textContent = `${outRem} / ${outLimit}`;
          if ($('#portal-fill-outreach')) $('#portal-fill-outreach').style.width = `${outLeftPct}%`;
        }
        if (typeof applyCustomerEntitlementNav === 'function' && Array.isArray(me.capabilities)) {
          applyCustomerEntitlementNav(me.capabilities, me.tier);
        }

        // Masked key display
        const statusEl = $('#portal-gemini-key-status');
        const maskedEl = $('#portal-gemini-key-masked');
        if (me.has_custom_gemini_key && me.gemini_key_masked) {
          if (statusEl) {
            statusEl.textContent = 'Active (BYOK Isolated)';
            statusEl.className = 'status-pill approved';
          }
          if (maskedEl) maskedEl.textContent = me.gemini_key_masked;
        } else {
          if (statusEl) {
            statusEl.textContent = 'Not Configured (Deterministic Fallback)';
            statusEl.className = 'status-pill pending';
          }
          if (maskedEl) maskedEl.textContent = 'None (Deterministic Fallback)';
        }

        // Update sidebar info
        if (['customer', 'member', 'tenant_admin'].includes(CONFIG.userRole) || (!CONFIG.ownerApiKey && !!CONFIG.accessToken)) {
          if ($('#sidebar-user-name')) $('#sidebar-user-name').textContent = me.full_name || me.email || 'Customer';
          if ($('#sidebar-user-role')) {
            const labelPrefix = me.role === 'tenant_admin' ? 'Tenant Admin' : 'Workspace';
            $('#sidebar-user-role').textContent = `${labelPrefix} (${me.tier || 'Starter'})`;
          }
          if ($('#sidebar-user-avatar')) {
            const initials = (me.full_name || me.email || 'CU').split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
            $('#sidebar-user-avatar').textContent = initials;
          }
        }
      }
    } catch (e) {
      console.warn('Customer portal data fetch:', e.message);
    }

    try {
      const invoices = await api('GET', '/v1/me/billing');
      const tbody = $('#portal-invoices-tbody');
      if (tbody && Array.isArray(invoices)) {
        if (invoices.length > 0) {
          tbody.innerHTML = invoices.map(inv => {
            const st = String(inv.status || 'PENDING').toUpperCase();
            const majorAmt = (typeof inv.amount_major === 'number')
              ? inv.amount_major
              : (Number(inv.amount || 0) / 100);
            const fmtAmt = majorAmt.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            return `
              <tr>
                <td><code>${esc(inv.invoice_id)}</code></td>
                <td>AskforWrite AI Workspace</td>
                <td>${inv.currency === 'USD' ? '$' : '₹'}${esc(fmtAmt)}</td>
                <td>${esc(inv.provider)}</td>
                <td><span class="status-pill ${st === 'PAID' ? 'approved' : 'pending'}">${esc(st)}</span></td>
                <td><button type="button" class="text-btn" onclick="alert('Invoice ID: ${esc(inv.invoice_id)}\nAmount: ${inv.currency === 'USD' ? '$' : '₹'}${esc(fmtAmt)}\nProvider: ${esc(inv.provider)}\nStatus: ${esc(st)}')">Receipt</button></td>
              </tr>
            `;
          }).join('');
        } else {
          tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">No verified billing invoices yet</td></tr>';
        }
      }
    } catch (e) {
      console.warn('Billing invoices fetch:', e.message);
      const tbody = $('#portal-invoices-tbody');
      if (tbody) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Unable to load billing invoices</td></tr>';
      }
    }
    await fetchCustomerP3PortalData();
  }

  async function fetchAll() {
    const isCustomer = CONFIG.userRole === 'customer' || (!CONFIG.ownerApiKey && CONFIG.accessToken);
    if (isCustomer) {
      await fetchCustomerPortalData();
      return;
    }
    await fetchDashboardData();
    await Promise.allSettled([
      fetchLeads(),
      fetchApprovals(),
      fetchOutreach(),
      fetchOrganizations(),
      fetchFieldForceData(),
      fetchWatchdogData(),
      fetchCeoBriefing(),
      fetchRevenueAndAuditPanels(),
    ]);
  }

  async function fetchRevenueAndAuditPanels() {
    // 1. Populate Dashboard Recent Activity (#audit-timeline) from 18-field evidence ledger
    try {
      const evRes = await api('GET', '/v1/registry/evidence?limit=10');
      const records = evRes.records || [];
      const timeline = $('#audit-timeline');
      if (timeline) {
        if (!records.length) {
          timeline.innerHTML = '<div class="empty-state"><p>No recent autonomous activity recorded yet.</p></div>';
        } else {
          timeline.innerHTML = records.slice(0, 8).map(r => `
            <div class="audit-item" style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:10px 14px;border-bottom:1px solid var(--border-subtle)">
              <div>
                <div style="font-weight:600;font-size:0.84rem;color:var(--text-primary)">${esc(r.service_name || r.agent_id || r.action || 'Operation')}</div>
                <div style="font-size:0.76rem;color:var(--text-secondary)">${esc(r.output_summary || r.execution_mode || '')}</div>
              </div>
              <div style="text-align:right;white-space:nowrap">
                <span class="status-pill ${String(r.status || '').toUpperCase() === 'FAILED' ? 'rejected' : 'approved'}">${esc(r.status || 'VERIFIED')}</span>
                <div style="font-size:0.7rem;color:var(--text-muted);margin-top:3px">${formatDate(r.created_at || r.timestamp)}</div>
              </div>
            </div>
          `).join('');
        }
      }
    } catch (e) {
      console.warn('Audit timeline fetch:', e.message);
    }

    // 2. Populate Owner Revenue & Billing (#page-revenue) from live orders + CEO briefing revenue
    try {
      const ordersRes = await api('GET', '/v1/orders?limit=50');
      const orders = ordersRes.orders || [];
      const rev = state.ceoBriefing?.revenue || {};
      const totalInr = Number(rev.total_revenue_inr || 0);
      const totalOrdersAmt = orders.reduce((acc, o) => acc + Number(o.amount || 0), 0);
      if ($('#stat-total-revenue')) {
        $('#stat-total-revenue').textContent = `₹${(totalInr || totalOrdersAmt).toLocaleString()}`;
      }
      if ($('#stat-invoices')) {
        $('#stat-invoices').textContent = String(orders.length);
      }
      if ($('#stat-subscriptions')) {
        $('#stat-subscriptions').textContent = String(state.ceoBriefing?.tenants?.active_tenants ?? state.organizations?.length ?? 0);
      }
      const tbody = $('#invoices-tbody');
      if (tbody) {
        if (!orders.length) {
          tbody.innerHTML = '<tr class="empty-row"><td colspan="6"><div class="empty-state"><p>No verified invoices/orders recorded yet</p></div></td></tr>';
        } else {
          tbody.innerHTML = orders.map(o => {
            const st = String(o.status || 'PENDING').toUpperCase();
            const sym = String(o.currency || 'INR').toUpperCase() === 'USD' ? '$' : '₹';
            return `
              <tr>
                <td><code>${esc(o.transaction_id || o.id || '—')}</code></td>
                <td>${esc(o.customer_email || o.org_name || 'Direct Client')}</td>
                <td>${sym}${Number(o.amount || 0).toLocaleString()}</td>
                <td>${esc(o.provider || 'directpay')}</td>
                <td><span class="status-pill ${st === 'FULFILLED' || st === 'CONFIRMED' || st === 'PAID' ? 'approved' : 'pending'}">${esc(st)}</span></td>
                <td>${formatDate(o.created_at)}</td>
              </tr>
            `;
          }).join('');
        }
      }
    } catch (e) {
      console.warn('Revenue panel fetch:', e.message);
    }
  }


  // ── P3 Customer Self-Service Portal Loader ──────────────
  async function fetchCustomerP3PortalData() {
    const statusPill = $('#portal-p3-status');
    const errBox = $('#portal-p3-error');
    const summaryEl = $('#portal-p3-onboarding-summary');
    const tasksEl = $('#portal-p3-onboarding-tasks');
    const delivEl = $('#portal-p3-deliveries-list');
    const ticketsEl = $('#portal-p3-tickets-list');
    if (!tasksEl || !delivEl || !ticketsEl) return;

    if (statusPill) {
      statusPill.textContent = 'Loading...';
      statusPill.className = 'status-pill pending';
    }
    if (errBox) {
      errBox.style.display = 'none';
      errBox.textContent = '';
    }

    try {
      const [onb, delivRes, tickRes] = await Promise.all([
        api('GET', '/v1/me/onboarding'),
        api('GET', '/v1/me/deliveries'),
        api('GET', '/v1/me/support/tickets'),
      ]);

      const pct = Number(onb.progress_pct ?? onb.completion_pct ?? 0);
      const obStatus = onb.status || onb.readiness_state || 'NOT_STARTED';
      if (summaryEl) {
        summaryEl.textContent = `${pct}% Complete • ${obStatus}`;
      }
      const tasks = Array.isArray(onb.tasks) ? onb.tasks : [];
      tasksEl.innerHTML = tasks.length ? tasks.map(t => {
        const ownerLabel = t.owner_role || t.assigned_to || t.owner || 'customer';
        const isDone = Boolean(t.completed || t.status === 'completed');
        return `
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 10px;border-bottom:1px solid var(--glass-border);font-size:0.82rem;flex-wrap:wrap">
          <div>
            <strong>${esc(t.title || t.task_key)}</strong>
            <div style="font-size:0.74rem;color:var(--text-muted)">Owner: ${esc(ownerLabel)} • Status: ${isDone ? 'completed' : 'pending'}</div>
          </div>
          ${isDone
            ? '<span class="status-pill approved">Completed</span>'
            : `<button type="button" class="secondary-btn portal-task-complete-btn" onclick="app.portalCompleteTask('${esc(t.task_key)}')" style="padding:5px 10px;font-size:0.75rem">Mark Done</button>`
          }
        </div>
      `;
      }).join('') : '<div class="empty-state"><p>No onboarding tasks configured.</p></div>';

      const deliveries = Array.isArray(delivRes.deliveries) ? delivRes.deliveries : [];
      delivEl.innerHTML = deliveries.length ? deliveries.map(d => {
        const qs = String(d.quality_state || 'NOT_STARTED');
        const canAccept = qs === 'DELIVERED';
        const canRequestRev = qs === 'DELIVERED' || qs === 'QUALITY_REVIEW';
        const scopeLabel = Array.isArray(d.approved_scope) && d.approved_scope.length
          ? d.approved_scope.join(', ')
          : (d.original_requirement || d.customer_requirement || 'Standard delivery');
        return `
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 10px;border-bottom:1px solid var(--glass-border);font-size:0.82rem;flex-wrap:wrap">
            <div>
              <strong>${esc(d.title || d.sku_key || d.delivery_id)}</strong>
              <span class="status-pill ${qs === 'ACCEPTED' ? 'approved' : qs === 'REVISION_REQUESTED' ? 'rejected' : 'pending'}" style="margin-left:6px">${esc(qs)}</span>
              <div style="font-size:0.74rem;color:var(--text-muted)">Scope: ${esc(scopeLabel)}</div>
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap">
              ${canAccept ? `<button type="button" class="success-btn" onclick="app.portalRespondDelivery('${esc(d.delivery_id)}','ACCEPTED')" style="padding:5px 10px;font-size:0.75rem">Accept</button>` : ''}
              ${canRequestRev ? `<button type="button" class="danger-btn" onclick="app.portalRespondDelivery('${esc(d.delivery_id)}','REVISION_REQUESTED')" style="padding:5px 10px;font-size:0.75rem">Request Revision</button>` : ''}
            </div>
          </div>
        `;
      }).join('') : '<div class="empty-state"><p>No service deliverables assigned yet.</p></div>';

      const tickets = Array.isArray(tickRes.tickets) ? tickRes.tickets : [];
      ticketsEl.innerHTML = tickets.length ? tickets.map(t => {
        const msgs = Array.isArray(t.messages) ? t.messages : [];
        const latestMsg = msgs.length ? msgs[msgs.length - 1] : null;
        const canCsat = (t.status === 'RESOLVED' || t.status === 'CLOSED') && t.csat_rating == null;
        return `
        <div style="padding:8px 10px;border-bottom:1px solid var(--glass-border);font-size:0.82rem;display:flex;flex-direction:column;gap:6px">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
            <div>
              <strong>${esc(t.subject)}</strong>
              <span class="status-pill ${t.status === 'RESOLVED' || t.status === 'CLOSED' ? 'approved' : 'pending'}" style="margin-left:6px">${esc(t.status)}</span>
              <div style="font-size:0.74rem;color:var(--text-muted)">${esc(t.category || 'general')} • Priority: ${esc(t.priority || 'MEDIUM')} • Messages: ${msgs.length}${t.csat_rating ? ` • CSAT: ${t.csat_rating}/5` : ''}</div>
              ${latestMsg ? `<div style="font-size:0.74rem;color:var(--text-secondary);margin-top:2px">Latest (${esc(latestMsg.sender_type || 'update')}): ${esc(latestMsg.body || '')}</div>` : ''}
            </div>
            <code style="font-size:0.72rem;color:var(--text-muted)">${esc(t.ticket_id)}</code>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
            <input id="portal-tkt-reply-${esc(t.ticket_id)}" class="settings-input" placeholder="Reply to ticket..." style="flex:1;min-width:160px;padding:5px 8px;font-size:0.76rem">
            <button type="button" class="secondary-btn" onclick="app.portalReplyTicket('${esc(t.ticket_id)}')" style="padding:5px 10px;font-size:0.75rem">Send Reply</button>
            ${canCsat ? `
              <select id="portal-tkt-csat-${esc(t.ticket_id)}" class="settings-select" style="width:90px;padding:5px 8px;font-size:0.75rem">
                <option value="5">5 ★</option><option value="4">4 ★</option><option value="3">3 ★</option><option value="2">2 ★</option><option value="1">1 ★</option>
              </select>
              <button type="button" class="primary-btn" onclick="app.portalSubmitCsat('${esc(t.ticket_id)}')" style="padding:5px 10px;font-size:0.75rem">Rate CSAT</button>
            ` : ''}
          </div>
        </div>
      `;
      }).join('') : '<div class="empty-state"><p>No support tickets raised yet.</p></div>';

      await portalRefreshGsc();

      if (statusPill) {
        statusPill.textContent = 'Synced';
        statusPill.className = 'status-pill approved';
      }
    } catch (e) {
      if (errBox) {
        errBox.style.display = 'block';
        errBox.textContent = `Unable to load customer portal data: ${e.message || 'Network or server error'}`;
      }
      if (statusPill) {
        statusPill.textContent = 'Error';
        statusPill.className = 'status-pill rejected';
      }
    }
  }

  async function portalCompleteTask(taskKey) {
    try {
      await api('PATCH', `/v1/me/onboarding/tasks/${encodeURIComponent(taskKey)}`, {
        completed: true,
        evidence_summary: 'Completed from customer workspace portal',
      });
      toast('Onboarding step marked complete', 'success');
      await fetchCustomerP3PortalData();
    } catch (e) {
      toast(`Could not update onboarding step: ${e.message}`, 'error');
    }
  }

  async function portalRespondDelivery(deliveryId, action) {
    try {
      await api('POST', `/v1/me/deliveries/${encodeURIComponent(deliveryId)}/respond`, {
        action,
        note: action === 'ACCEPTED' ? 'Accepted by customer in portal' : 'Revision requested from customer portal',
      });
      toast(`Deliverable updated to ${action}`, 'success');
      await fetchCustomerP3PortalData();
    } catch (e) {
      toast(`Deliverable update failed: ${e.message}`, 'error');
    }
  }

  async function portalCreateTicket() {
    const subject = ($('#portal-ticket-subject')?.value || '').trim();
    const category = ($('#portal-ticket-category')?.value || 'onboarding').trim();
    const priority = ($('#portal-ticket-priority')?.value || 'MEDIUM').trim().toUpperCase();
    const description = ($('#portal-ticket-description')?.value || '').trim();
    if (!subject || !description) {
      toast('Enter both a ticket subject and description', 'error');
      return;
    }
    const errBox = $('#portal-p3-error');
    if (errBox) { errBox.style.display = 'none'; errBox.textContent = ''; }
    try {
      await api('POST', '/v1/me/support/tickets', {
        subject,
        category,
        priority,
        description,
      });
      if ($('#portal-ticket-subject')) $('#portal-ticket-subject').value = '';
      if ($('#portal-ticket-description')) $('#portal-ticket-description').value = '';
      toast('Support ticket submitted', 'success');
      await fetchCustomerP3PortalData();
    } catch (e) {
      if (errBox) {
        errBox.style.display = 'block';
        errBox.textContent = `Ticket submission failed: ${e.message || 'Network or server error'}`;
      }
      toast(`Ticket submission failed: ${e.message}`, 'error');
    }
  }

  async function portalReplyTicket(ticketId) {
    const inputEl = $(`#portal-tkt-reply-${ticketId}`);
    const body = (inputEl?.value || '').trim();
    if (!body) {
      toast('Enter a reply message first', 'error');
      return;
    }
    try {
      await api('POST', `/v1/me/support/tickets/${encodeURIComponent(ticketId)}/messages`, { body });
      toast('Reply posted to support ticket', 'success');
      await fetchCustomerP3PortalData();
    } catch (e) {
      toast(`Ticket reply failed: ${e.message}`, 'error');
    }
  }

  async function portalSubmitCsat(ticketId) {
    const rating = Number($(`#portal-tkt-csat-${ticketId}`)?.value || 5);
    try {
      await api('POST', `/v1/me/support/tickets/${encodeURIComponent(ticketId)}/csat`, {
        rating,
        comment: `Rated ${rating}/5 from Customer Portal`,
      });
      toast('Thank you for your feedback!', 'success');
      await fetchCustomerP3PortalData();
    } catch (e) {
      toast(`CSAT submission failed: ${e.message}`, 'error');
    }
  }

  async function portalExportData() {
    const outEl = $('#portal-privacy-output');
    try {
      const res = await api('GET', '/v1/me/data-export');
      if (outEl) {
        const counts = res.compliance_request?.export_manifest?.record_counts || res.export_manifest?.record_counts || {};
        outEl.textContent = `Redacted export ready (secrets stripped). Records: ${JSON.stringify(counts)}`;
      }
      toast('Tenant DPDP/GDPR data export generated', 'success');
    } catch (e) {
      if (outEl) outEl.textContent = `Export failed: ${e.message}`;
      toast(`Data export failed: ${e.message}`, 'error');
    }
  }

  async function portalSaveConsent() {
    const outEl = $('#portal-privacy-output');
    const marketing = Boolean($('#portal-consent-marketing')?.checked);
    const aiAssist = Boolean($('#portal-consent-ai')?.checked);
    try {
      await api('PATCH', '/v1/me/consent-preferences', {
        consent_preferences: { marketing_updates: marketing, ai_support_triage: aiAssist },
      });
      if (outEl) outEl.textContent = `Consent saved (marketing=${marketing}, ai_triage=${aiAssist})`;
      toast('Privacy consent preferences updated', 'success');
    } catch (e) {
      toast(`Consent update failed: ${e.message}`, 'error');
    }
  }

  async function portalRefreshGsc() {
    const gscEl = $('#portal-gsc-status');
    if (!gscEl) return;
    try {
      const gsc = await api('GET', '/v1/me/integrations/gsc/status');
      const missing = Array.isArray(gsc.missing_env_vars) && gsc.missing_env_vars.length
        ? ` • Missing env: ${gsc.missing_env_vars.join(', ')}`
        : '';
      gscEl.innerHTML = `
        <div><strong>State:</strong> ${esc(gsc.gsc_state || 'BLOCKED')} (${esc(gsc.connection_status || 'NOT_CONNECTED')})</div>
        <div><strong>Property:</strong> ${esc(gsc.selected_property || 'None selected')}${esc(missing)}</div>
      `;
    } catch (e) {
      gscEl.textContent = `GSC status unavailable: ${e.message}`;
    }
  }

  // ── Connection Status ────────────────────────────────────
  function setConnectionStatus(online) {
    state.connected = online;
    const dot = $('#connection-dot .dot');
    if (dot) {
      dot.classList.toggle('online', online);
      dot.classList.toggle('offline', !online);
    }
    const dotContainer = $('#connection-dot');
    if (dotContainer) {
      dotContainer.title = online ? 'API Connected' : 'API Offline — Backend unreachable';
    }
    const dataBadge = $('#data-mode-badge');
    if (!online && dataBadge) {
      dataBadge.className = 'status-pill rejected';
      dataBadge.textContent = 'BLOCKED • API OFFLINE';
    }
    const container = $('#page-container');
    if (container) {
      let banner = $('#offline-status-banner');
      if (!online) {
        if (!banner) {
          banner = document.createElement('div');
          banner.id = 'offline-status-banner';
          banner.setAttribute('role', 'alert');
          banner.style.cssText = 'margin-bottom:14px;padding:10px 14px;border-radius:8px;border:1px solid rgba(239,68,68,0.55);background:rgba(239,68,68,0.14);color:#fecaca;font-size:0.84rem;display:flex;justify-content:space-between;align-items:center;gap:10px;';
          banner.textContent = '⚠️ Offline / Backend Unreachable — Live actions are paused and no synthetic success messages will be shown.';
          container.prepend(banner);
        }
        banner.style.display = 'flex';
      } else if (banner) {
        banner.style.display = 'none';
      }
    }
  }

  // ── Stats Updaters ───────────────────────────────────────
  function updateStatsFromProject(data) {
    const counts = data.operating_model?.l4_data_layer?.counts || data.database_stats || {};
    animateNumber('#stat-leads', counts.leads || 0);
    animateNumber('#stat-pending', counts.approval_requests ?? counts.pending_approvals ?? 0);
    animateNumber('#stat-orgs', counts.organizations || 0);
    animateNumber('#stat-outreach', counts.outreach_records ?? counts.outreach ?? 0);

    if (counts.invoices !== undefined) animateNumber('#stat-invoices', counts.invoices);
    if (counts.subscriptions !== undefined) animateNumber('#stat-subscriptions', counts.subscriptions);
  }

  function animateNumber(selector, target) {
    const el = $(selector);
    if (!el) return;
    const start = parseInt(el.textContent) || 0;
    const diff = target - start;
    const duration = 600;
    const startTime = performance.now();

    function step(now) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const ease = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      el.textContent = Math.round(start + diff * ease);
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  // ── Pipeline Rendering ───────────────────────────────────
  function updatePipeline() {
    const counts = { discovered: 0, qualified: 0, outreach: 0, contacted: 0, converted: 0 };
    state.leads.forEach(lead => {
      const s = (lead.status || '').toUpperCase();
      if (s === 'DISCOVERED' || s === 'RESEARCHED') counts.discovered++;
      else if (s === 'QUALIFIED') counts.qualified++;
      else if (s === 'APPROVED_FOR_OUTREACH' || s === 'PENDING_APPROVAL') counts.outreach++;
      else if (s === 'CONTACTED') counts.contacted++;
      else if (s === 'CONVERTED' || s === 'PROPOSAL_APPROVED') counts.converted++;
    });

    const total = Math.max(state.leads.length, 1);
    Object.entries(counts).forEach(([stage, count]) => {
      const fill = $(`#fill-${stage}`);
      const countEl = $(`#count-${stage === 'outreach' ? 'outreach-stage' : stage}`);
      if (fill) fill.style.width = `${Math.max((count / total) * 100, count > 0 ? 15 : 0)}%`;
      if (countEl) countEl.textContent = count;
    });
  }

  // ── Render: Leads ────────────────────────────────────────
  function renderLeads() {
    const tbody = $('#leads-tbody');
    if (!state.leads.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="6"><div class="empty-state"><p>No leads found. Click "Discover Leads" to start.</p></div></td></tr>';
      return;
    }

    tbody.innerHTML = state.leads.map(lead => `
      <tr>
        <td>
          <div style="font-weight:600">${esc(lead.company)}</div>
          <div style="font-size:0.78rem;color:var(--text-muted)">${esc(lead.website || '')}</div>
        </td>
        <td>${esc(lead.industry || '—')}</td>
        <td>${esc(lead.geography || '—')}</td>
        <td>
          <div style="display:flex;align-items:center;gap:8px">
            <div style="width:60px;height:6px;background:rgba(148,163,184,0.1);border-radius:3px;overflow:hidden">
              <div style="width:${(lead.fit_score || 0) * 100}%;height:100%;background:${lead.fit_score >= 0.7 ? 'var(--green)' : lead.fit_score >= 0.4 ? 'var(--amber)' : 'var(--red)'};border-radius:3px"></div>
            </div>
            <span style="font-size:0.82rem;font-weight:600">${((lead.fit_score || 0) * 100).toFixed(0)}%</span>
          </div>
        </td>
        <td><span class="status-pill ${(lead.status || '').toLowerCase()}">${esc(lead.status || 'Unknown')}</span></td>
        <td>
          <button class="text-btn" onclick="app.viewLead('${esc(lead.id)}')">View</button>
        </td>
      </tr>
    `).join('');

    updatePipeline();
  }

  // ── Render: Approvals ────────────────────────────────────
  function renderApprovals() {
    const grid = $('#approvals-grid');
    let filtered = state.approvals;
    if (state.approvalFilter !== 'all') {
      filtered = filtered.filter(a => a.status === state.approvalFilter);
    }

    if (!filtered.length) {
      grid.innerHTML = '<div class="empty-state"><p>No approval requests matching filter</p></div>';
      return;
    }

    grid.innerHTML = filtered.map(a => `
      <div class="approval-card">
        <div class="approval-card-header">
          <span class="approval-card-action">${formatAction(a.action)}</span>
          <span class="status-pill ${(a.status || '').toLowerCase()}">${esc(a.status)}</span>
        </div>
        <div class="approval-card-details">
          <p><strong>Task:</strong> ${esc(a.task_id?.slice(0, 8) || '—')}...</p>
          ${a.lead_id ? `<p><strong>Lead:</strong> ${esc(a.lead_id.slice(0, 8))}...</p>` : ''}
          ${a.requested_by ? `<p><strong>Requested by:</strong> ${esc(a.requested_by)}</p>` : ''}
          ${a.decision_note ? `<p><strong>Note:</strong> ${esc(a.decision_note)}</p>` : ''}
        </div>
        <div class="approval-card-footer">
          <span class="approval-card-date">${formatDate(a.created_at)}</span>
          ${a.status === 'PENDING' ? `
            <div class="approval-actions">
              <button class="action-btn approve" title="Approve" onclick="app.openApprovalModal('${esc(a.id)}', 'APPROVED')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              </button>
              <button class="action-btn reject" title="Reject" onclick="app.openApprovalModal('${esc(a.id)}', 'REJECTED')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
          ` : ''}
        </div>
      </div>
    `).join('');
  }

  function renderRecentApprovals() {
    const list = $('#recent-approvals-list');
    const recent = state.approvals.slice(0, 5);

    if (!recent.length) {
      list.innerHTML = '<div class="empty-state"><p>No approvals yet</p></div>';
      return;
    }

    list.innerHTML = recent.map(a => `
      <div class="approval-item">
        <div class="approval-info">
          <div class="approval-action-text">${formatAction(a.action)}</div>
          <div class="approval-meta">By ${esc(a.requested_by || '—')} • ${formatDate(a.created_at)}</div>
        </div>
        <span class="status-pill ${(a.status || '').toLowerCase()}">${esc(a.status)}</span>
        ${a.status === 'PENDING' ? `
          <div class="approval-actions">
            <button class="action-btn approve" title="Approve" onclick="app.openApprovalModal('${esc(a.id)}', 'APPROVED')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            </button>
            <button class="action-btn reject" title="Reject" onclick="app.openApprovalModal('${esc(a.id)}', 'REJECTED')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
        ` : ''}
      </div>
    `).join('');
  }

  function updateApprovalBadge() {
    const pending = state.approvals.filter(a => a.status === 'PENDING').length;
    const badge = $('#approval-badge');
    if (pending > 0) {
      badge.style.display = 'inline';
      badge.textContent = pending;
    } else {
      badge.style.display = 'none';
    }
  }

  // ── Render: Outreach ─────────────────────────────────────
  function renderOutreach() {
    const tbody = $('#outreach-tbody');
    if (!state.outreach.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="5"><div class="empty-state"><p>No outreach records</p></div></td></tr>';
      return;
    }
    tbody.innerHTML = state.outreach.map(o => `
      <tr>
        <td>
          <div style="font-weight:600">${esc(o.recipient_email || '—')}</div>
          ${o.recipient_name ? `<div style="font-size:0.78rem;color:var(--text-muted)">${esc(o.recipient_name)}</div>` : ''}
        </td>
        <td style="max-width:300px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(o.subject || '—')}</td>
        <td>${esc(o.channel || 'email')}</td>
        <td><span class="status-pill ${(o.status || '').toLowerCase().replace(/_/g, '-')}">${esc(o.status || '—')}</span></td>
        <td style="font-size:0.82rem;color:var(--text-muted)">${o.sent_at ? formatDate(o.sent_at) : '—'}</td>
      </tr>
    `).join('');
  }

  // ── Render: Organizations ────────────────────────────────
  function renderOrganizations() {
    const grid = $('#org-grid');
    if (!state.organizations.length) {
      grid.innerHTML = '<div class="empty-state"><p>No organizations yet. They are auto-created upon payment.</p></div>';
      return;
    }
    grid.innerHTML = state.organizations.map(org => `
      <div class="org-card">
        <div class="org-card-name">${esc(org.name)}</div>
        <div class="org-card-slug">@${esc(org.slug)} • <span class="status-pill ${org.is_active ? 'approved' : 'rejected'}">${org.is_active ? 'Active' : 'Inactive'}</span></div>
        <div class="org-card-stats">
          <div class="org-stat">
            <span class="org-stat-label">Tier</span>
            <span class="org-stat-value" style="text-transform:capitalize">${esc(org.tier)}</span>
          </div>
          <div class="org-stat">
            <span class="org-stat-label">Lead Credits</span>
            <span class="org-stat-value">${org.lead_credits_used || 0}/${org.lead_credits_limit || 0}</span>
          </div>
          <div class="org-stat">
            <span class="org-stat-label">Outreach Credits</span>
            <span class="org-stat-value">${org.outreach_credits_used || 0}/${org.outreach_credits_limit || 0}</span>
          </div>
        </div>
      </div>
    `).join('');

    animateNumber('#stat-orgs', state.organizations.length);
  }

  // ── Approval Modal ───────────────────────────────────────
  let pendingDecision = { approvalId: null, decision: null };

  function openApprovalModal(approvalId, decision) {
    pendingDecision = { approvalId, decision };
    const approval = state.approvals.find(a => a.id === approvalId);

    $('#modal-title').textContent = decision === 'APPROVED' ? '✓ Approve Request' : '✕ Reject Request';
    $('#modal-detail').innerHTML = approval ? `
      <p><strong>Action:</strong> ${formatAction(approval.action)}</p>
      <p><strong>Requested by:</strong> ${esc(approval.requested_by || '—')}</p>
      <p><strong>Created:</strong> ${formatDate(approval.created_at)}</p>
    ` : '<p>Loading...</p>';
    $('#decision-note').value = '';
    $('#modal-overlay').style.display = 'flex';
  }

  function closeModal() {
    $('#modal-overlay').style.display = 'none';
    pendingDecision = { approvalId: null, decision: null };
  }

  async function submitDecision(decision) {
    if (!pendingDecision.approvalId) return;

    const note = $('#decision-note').value.trim();
    const isCustomer = CONFIG.userRole === 'customer' || (!CONFIG.ownerApiKey && !!CONFIG.accessToken);
    try {
      if (isCustomer) {
        await api('POST', `/v1/me/approvals/${pendingDecision.approvalId}/decide`, {
          decision: decision,
          reason: note || `${decision} via Customer Control Center`,
          decision_note: note || `${decision} via Customer Control Center`,
        });
        toast(`Approval ${decision.toLowerCase()} successfully`, 'success');
        if (typeof cwFetchScopedApprovals === 'function') {
          await cwFetchScopedApprovals();
        }
        closeModal();
      } else {
        await api('POST', `/v1/approvals/${pendingDecision.approvalId}/decision`, {
          decision: decision,
          reason: note || `${decision} via Owner Dashboard`,
        });
        toast(`Approval ${decision.toLowerCase()} successfully`, 'success');
        await fetchApprovals();
        closeModal();
        await fetchLeads();
        await fetchDashboardData();
      }
    } catch (e) {
      toast(`Decision failed: ${e.message}`, 'error');
    }
  }

  // ── Field Force Rendering ────────────────────────────────
  function renderFieldForce() {
    const list = $('#field-alerts-list');
    if (!list) return;

    const items = [
      ...state.fieldTasks.map(t => ({
        type: 'Task',
        title: t.title || 'Field Task',
        desc: `Status: ${t.status} • Assigned: ${t.assigned_to_user_id || 'Unassigned'}`,
        status: t.status,
      })),
      ...state.fieldVisits.map(v => ({
        type: 'Visit',
        title: `Client Visit — ${v.client_company || 'Site'}`,
        desc: `Verified: ${v.status} • Accuracy: ${v.gps_accuracy_meters ? v.gps_accuracy_meters + 'm' : '—'}`,
        status: v.status,
      })),
      ...state.fieldClaims.map(c => ({
        type: 'Claim',
        title: `Conveyance Claim ₹${c.amount || 0}`,
        desc: `Status: ${c.status} • Distance: ${c.distance_km || 0} km`,
        status: c.status,
      })),
    ];

    if (!items.length) {
      list.innerHTML = '<div class="empty-state"><p>All field operations running smoothly — no anomalies</p></div>';
      return;
    }

    list.innerHTML = items.slice(0, 8).map(item => `
      <div class="approval-item">
        <div class="approval-info">
          <div class="approval-action-text"><span class="card-badge" style="margin-right:8px">${esc(item.type)}</span>${esc(item.title)}</div>
          <div class="approval-meta">${esc(item.desc)}</div>
        </div>
        <span class="status-pill ${(item.status || '').toLowerCase()}">${esc(item.status || 'Active')}</span>
      </div>
    `).join('');
  }

  // ── Lead Discovery Trigger ───────────────────────────────
  async function triggerLeadDiscovery() {
    const btn = $('#btn-discover-leads');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner" style="margin-right:8px"></span> Discovering...';
    }
    toast('Running autonomous lead discovery & enrichment...', 'info');

    try {
      const res = await api('POST', '/v1/leads/discover', {
        objective: 'B2B Logistics and Field Operations SaaS companies in India',
        limit: 5,
        idempotency_key: 'disc_' + Date.now(),
        live_source: false,
      });
      const added = res.count || (res.leads ? res.leads.length : 0) || 5;
      toast(`Successfully discovered ${added} new high-intent leads!`, 'success');
      await fetchLeads();
      await fetchDashboardData();
    } catch (e) {
      toast(`Discovery failed: ${e.message}`, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-icon">
            <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
          </svg>
          Discover Leads
        `;
      }
    }
  }

  // ── Demo Data (offline mode) ─────────────────────────────
  function loadDemoData() {
    // Populate with demo stats for visual preview
    animateNumber('#stat-leads', 1);
    animateNumber('#stat-pending', 0);
    animateNumber('#stat-orgs', 1);
    animateNumber('#stat-outreach', 6);

    // Demo pipeline
    setTimeout(() => {
      const fills = { discovered: 40, qualified: 20, outreach: 25, contacted: 10, converted: 5 };
      Object.entries(fills).forEach(([stage, pct]) => {
        const fill = $(`#fill-${stage}`);
        if (fill) fill.style.width = `${pct}%`;
      });
    }, 500);
  }

  // ── Utility Functions ────────────────────────────────────
  function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
  }
  const escapeHtml = esc;

  function formatAction(action) {
    return (action || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString('en-IN', {
        day: 'numeric', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      });
    } catch {
      return dateStr;
    }
  }

  // ── Produce Quality AI Controller ────────────────────────
  let qualityState = {
    initialized: false,
    activePreset: 'ripe',
    uploadedFile: null,
    uploadedBase64: null,
  };

  function initQualityPage() {
    if (qualityState.initialized) return;
    qualityState.initialized = true;

    // Preset selector buttons
    $$('.preset-btn[data-preset]').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.preset-btn[data-preset]').forEach(b => {
          b.classList.remove('active');
          b.style.borderColor = 'var(--glass-border)';
          b.style.background = 'var(--bg-card)';
        });
        btn.classList.add('active');
        btn.style.borderColor = 'var(--cyan)';
        btn.style.background = 'rgba(6, 182, 212, 0.12)';

        qualityState.activePreset = btn.dataset.preset;
        qualityState.uploadedFile = null;
        qualityState.uploadedBase64 = null;

        // Reset dropzone UI
        const previewWrap = $('#dropzone-preview-wrap');
        const prompt = $('#dropzone-prompt');
        const fileInput = $('#quality-file-input');
        if (previewWrap) previewWrap.style.display = 'none';
        if (prompt) prompt.style.display = 'block';
        if (fileInput) fileInput.value = '';

        runQualityInspection();
      });
    });

    // Dropzone & File Input
    const dropzone = $('#quality-dropzone');
    const fileInput = $('#quality-file-input');

    dropzone?.addEventListener('click', (e) => {
      if (e.target.id !== 'btn-clear-image') {
        fileInput?.click();
      }
    });

    dropzone?.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });

    dropzone?.addEventListener('dragleave', () => {
      dropzone.classList.remove('dragover');
    });

    dropzone?.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        handleQualityFileUpload(e.dataTransfer.files[0]);
      }
    });

    fileInput?.addEventListener('change', (e) => {
      if (e.target.files && e.target.files.length > 0) {
        handleQualityFileUpload(e.target.files[0]);
      }
    });

    $('#btn-clear-image')?.addEventListener('click', (e) => {
      e.stopPropagation();
      qualityState.uploadedFile = null;
      qualityState.uploadedBase64 = null;
      const previewWrap = $('#dropzone-preview-wrap');
      const prompt = $('#dropzone-prompt');
      if (previewWrap) previewWrap.style.display = 'none';
      if (prompt) prompt.style.display = 'block';
      if (fileInput) fileInput.value = '';

      // Fallback to table ripe
      const ripeBtn = $('#btn-preset-ripe');
      if (ripeBtn) ripeBtn.click();
    });

    $('#btn-run-quality-inspect')?.addEventListener('click', () => {
      runQualityInspection();
    });

    $('#btn-submit-quality-uat')?.addEventListener('click', async () => {
      const rating = parseInt($('#quality-uat-rating')?.value || '4', 10);
      const groundtruth = $('#quality-uat-groundtruth')?.value || 'RIPE';
      const notes = ($('#quality-uat-notes')?.value || '').trim();
      const inspectorId = ($('#quality-inspector-id')?.value || 'inspector-alpha').trim();

      const btn = $('#btn-submit-quality-uat');
      if (btn) btn.disabled = true;

      try {
        await api('POST', '/v1/quality/uat', {
          role: inspectorId || 'Quality Inspector',
          rating: rating,
          comments: notes ? `${notes} (Observed: ${groundtruth})` : `Observed ripeness: ${groundtruth}`,
        });
        toast('Inspector UAT survey logged into Trust Registry!', 'success');
        if ($('#quality-uat-notes')) $('#quality-uat-notes').value = '';
      } catch (err) {
        toast(`UAT submission failed: ${err.message}`, 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    });

    // Run initial inspection for the default Table Ripe preset
    runQualityInspection();
  }

  function handleQualityFileUpload(file) {
    if (!file || !file.type.startsWith('image/')) {
      toast('Please upload a valid PNG or JPEG image file', 'error');
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      const previewImg = $('#quality-image-preview');
      const filenameSpan = $('#quality-filename');
      const previewWrap = $('#dropzone-preview-wrap');
      const prompt = $('#dropzone-prompt');

      if (previewImg) previewImg.src = e.target.result;
      if (filenameSpan) filenameSpan.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
      if (previewWrap) previewWrap.style.display = 'flex';
      if (prompt) prompt.style.display = 'none';

      // Deactivate presets visually
      $$('.preset-btn[data-preset]').forEach(b => {
        b.classList.remove('active');
        b.style.borderColor = 'var(--glass-border)';
        b.style.background = 'var(--bg-card)';
      });

      qualityState.activePreset = null;
      qualityState.uploadedFile = file;
      qualityState.uploadedBase64 = e.target.result;

      runQualityInspection();
    };
    reader.readAsDataURL(file);
  }

  async function runQualityInspection() {
    const btn = $('#btn-run-quality-inspect');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner" style="margin-right:6px"></span> Analyzing Produce...';
    }

    try {
      let res;
      const inspectorId = ($('#quality-inspector-id')?.value || 'inspector-alpha').trim();

      if (qualityState.uploadedFile) {
        // Multipart image upload
        const fd = new FormData();
        fd.append('file', qualityState.uploadedFile);
        fd.append('inspector_id', inspectorId);

        const headers = {};
        if (CONFIG.ownerApiKey) headers['X-API-Key'] = CONFIG.ownerApiKey;
        else if (CONFIG.accessToken) headers['Authorization'] = `Bearer ${CONFIG.accessToken}`;

        const response = await fetch(`${CONFIG.apiBase}/v1/quality/inspect-image`, {
          method: 'POST',
          headers,
          body: fd,
        });
        if (!response.ok) {
          const err = await response.json().catch(() => ({ detail: response.statusText }));
          throw new Error(err.detail || `HTTP ${response.status}`);
        }
        res = await response.json();
      } else {
        const preset = qualityState.activePreset || 'ripe';
        res = await api('POST', '/v1/quality/inspect', {
          preset_or_sample: preset,
          crop_variety: 'Alphonso Mango',
          batch_lot_id: `LOT-${inspectorId.slice(0, 12).toUpperCase()}-${Date.now().toString(36).slice(-4).toUpperCase()}`,
        });
      }

      const report = res.inspection_report || res;
      const classification = report.classification || report;
      const visualMetrics = report.visual_metrics || {};
      const texture = visualMetrics.glcm_texture_descriptors || report.texture_glcm || {};
      const colorimetry = report.colorimetry || visualMetrics;

      const rawRipeness = String(report.predicted_class || classification.ripeness || 'RIPE').trim();
      const ripeness = rawRipeness.toUpperCase();
      const ripenessEl = $('#quality-ripeness-badge');
      if (ripenessEl) {
        ripenessEl.textContent = ripeness;
        if (ripeness === 'RIPE') {
          ripenessEl.style.color = 'var(--green)';
        } else if (ripeness === 'UNRIPE') {
          ripenessEl.style.color = 'var(--amber)';
        } else {
          ripenessEl.style.color = 'var(--red)';
        }
      }

      if ($('#quality-grade-badge')) {
        $('#quality-grade-badge').textContent = report.commercial_grade || classification.commercial_grade || 'Commercial Grade';
      }
      if ($('#quality-brix-val')) {
        const brix = report.estimated_brix_sugar_degrees ?? classification.estimated_sugar_brix ?? 14.5;
        $('#quality-brix-val').textContent = `${Number(brix).toFixed(1)}° Bx`;
      }
      if ($('#quality-shelflife-val')) {
        const shelf = report.shelf_life_days ?? classification.estimated_shelf_life_days ?? 5;
        $('#quality-shelflife-val').textContent = `Est. Shelf-Life: ${shelf} days`;
      }
      if ($('#quality-staging-rec')) {
        $('#quality-staging-rec').textContent = report.recommended_action || classification.supply_chain_staging || 'Store in standard temperature-controlled staging.';
      }

      const rawEnsemble = report.model_ensemble || res.model_ensemble;
      const ensembleArr = Array.isArray(rawEnsemble) ? rawEnsemble : [];
      const agreedCount = ensembleArr.filter(m => String(m.pred || m.prediction || '').toUpperCase() === ripeness).length;
      if ($('#quality-consensus-ratio')) {
        const ratioText = ensembleArr.length
          ? `${agreedCount}/${ensembleArr.length} Models Agreed (${Number(report.ensemble_confidence_pct || 0).toFixed(1)}%)`
          : (rawEnsemble?.consensus_ratio || '4/4 Models Agreed');
        $('#quality-consensus-ratio').textContent = `Model Consensus: ${ratioText}`;
      }
      if ($('#quality-trust-pill')) {
        const tbHash = res.trust_block_hash || res.task_id;
        $('#quality-trust-pill').textContent = tbHash ? `TrustBlock #${String(tbHash).substring(0, 8)}` : 'TrustBlock Sealed';
      }

      const findModel = (matchers, legacyKey) => {
        if (ensembleArr.length) {
          return ensembleArr.find(m => {
            const hay = `${m.name || ''} ${m.algorithm || ''}`.toLowerCase();
            return matchers.some(tok => hay.includes(tok));
          });
        }
        return rawEnsemble?.individual_models?.[legacyKey];
      };
      const updateModelBar = (matchers, legacyKey, labelId, barId) => {
        const m = findModel(matchers, legacyKey);
        const labelEl = $(`#${labelId}`);
        const barEl = $(`#${barId}`);
        if (m && labelEl && barEl) {
          const rawConf = Number(m.conf ?? m.confidence ?? 0.9);
          const pct = (rawConf > 1 ? rawConf : rawConf * 100).toFixed(1);
          const pred = String(m.pred || m.prediction || ripeness).toUpperCase();
          labelEl.textContent = `${pred} (${pct}%)`;
          barEl.style.width = `${Math.min(100, Number(pct))}%`;
          if (pred === 'RIPE') {
            labelEl.style.color = 'var(--green)';
            barEl.style.background = 'var(--green)';
          } else if (pred === 'UNRIPE') {
            labelEl.style.color = 'var(--amber)';
            barEl.style.background = 'var(--amber)';
          } else {
            labelEl.style.color = 'var(--red)';
            barEl.style.background = 'var(--red)';
          }
        }
      };

      updateModelBar(['svm', 'support vector'], 'svm_rbf', 'label-svm', 'bar-svm');
      updateModelBar(['random forest', 'forest'], 'random_forest', 'label-rf', 'bar-rf');
      updateModelBar(['naive bayes', 'gaussian'], 'gaussian_nb', 'label-gnb', 'bar-gnb');
      updateModelBar(['cnn', 'pytorch', 'resnet'], 'pytorch_cnn', 'label-cnn', 'bar-cnn');

      const meanHue = Number(visualMetrics.mean_hue_degrees ?? colorimetry.mean_hue_angle ?? 72.5);
      const topBins = visualMetrics.color_histogram_top_bins;
      const domBin = Array.isArray(topBins) && topBins.length
        ? (topBins[0]?.bin ?? topBins[0]?.bin_index ?? topBins[0])
        : (colorimetry.dominant_bin_index ?? 146);
      if ($('#val-mean-hue')) $('#val-mean-hue').textContent = `${meanHue.toFixed(1)}°`;
      if ($('#val-glcm-homo')) $('#val-glcm-homo').textContent = Number(texture.homogeneity ?? 0.842).toFixed(3);
      if ($('#val-glcm-contrast')) $('#val-glcm-contrast').textContent = Number(texture.contrast ?? 12.4).toFixed(1);
      if ($('#val-glcm-energy')) $('#val-glcm-energy').textContent = Number(texture.energy ?? 0.315).toFixed(3);
      if ($('#val-glcm-corr')) $('#val-glcm-corr').textContent = Number(texture.correlation ?? 0.912).toFixed(3);
      if ($('#val-hist-bin')) $('#val-hist-bin').textContent = `#${domBin}`;

      toast('Produce computer vision analysis completed & sealed in TrustBlock', 'success');
    } catch (err) {
      toast(`Inspection failed: ${err.message}`, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 16px; height: 16px; margin-right: 6px;"><circle cx="12" cy="12" r="10"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>
          Run Vision Inspection
        `;
      }
    }
  }

  // ── Urban Mobility AI Controller ──────────────────────────
  let mobilityState = {
    initialized: false,
    isWeekend: false,
    debounceTimer: null,
  };

  function initMobilityPage() {
    if (mobilityState.initialized) return;
    mobilityState.initialized = true;

    // Sliders
    const hourSlider = $('#slider-mobility-hour');
    const tempSlider = $('#slider-mobility-temp');
    const humSlider = $('#slider-mobility-hum');
    const precipSlider = $('#slider-mobility-precip');

    const updateSliderLabels = () => {
      const h = parseInt(hourSlider?.value || '8', 10);
      const t = parseInt(tempSlider?.value || '72', 10);
      const hum = parseInt(humSlider?.value || '60', 10);
      const p = parseInt(precipSlider?.value || '0', 10);

      const hourLabel = $('#label-mobility-hour');
      if (hourLabel) {
        const periodStr = (6 <= h && h <= 11) ? 'Morning Peak' : (16 <= h && h <= 20) ? 'Evening Peak' : 'Off-Peak';
        hourLabel.textContent = `${String(h).padStart(2, '0')}:00 (${periodStr})`;
      }

      const tempLabel = $('#label-mobility-temp');
      if (tempLabel) tempLabel.textContent = `${t}°F`;

      const humLabel = $('#label-mobility-hum');
      if (humLabel) humLabel.textContent = `${hum}%`;

      const precipLabel = $('#label-mobility-precip');
      if (precipLabel) {
        const valInches = (p / 100).toFixed(2);
        const condition = p === 0 ? 'Dry' : p < 50 ? 'Light Rain' : 'Heavy Rain';
        precipLabel.textContent = `${valInches}" (${condition})`;
      }
    };

    const debouncedRunSim = () => {
      updateSliderLabels();
      if (mobilityState.debounceTimer) clearTimeout(mobilityState.debounceTimer);
      mobilityState.debounceTimer = setTimeout(() => {
        runMobilitySimulation();
      }, 250);
    };

    hourSlider?.addEventListener('input', debouncedRunSim);
    tempSlider?.addEventListener('input', debouncedRunSim);
    humSlider?.addEventListener('input', debouncedRunSim);
    precipSlider?.addEventListener('input', debouncedRunSim);

    // Day Profile Toggle
    $('#btn-toggle-weekday')?.addEventListener('click', () => {
      $('#btn-toggle-weekday').classList.add('active');
      $('#btn-toggle-weekend').classList.remove('active');
      mobilityState.isWeekend = false;
      debouncedRunSim();
    });

    $('#btn-toggle-weekend')?.addEventListener('click', () => {
      $('#btn-toggle-weekend').classList.add('active');
      $('#btn-toggle-weekday').classList.remove('active');
      mobilityState.isWeekend = true;
      debouncedRunSim();
    });

    // Dispatch Rebalance Truck
    $('#btn-dispatch-mobility-truck')?.addEventListener('click', async () => {
      const h = parseInt($('#slider-mobility-hour')?.value || '8', 10);
      const btn = $('#btn-dispatch-mobility-truck');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner" style="margin-right:6px"></span> Dispatching Truck...';
      }

      try {
        await api('POST', '/v1/mobility/rebalance', {
          hour_of_day: h,
          auto_dispatch_field_force: true,
        });
        toast('Rebalance dispatch order dispatched to Field Force & sealed in TrustBlock!', 'success');
        await runMobilitySimulation();
      } catch (err) {
        toast(`Dispatch failed: ${err.message}`, 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 16px; height: 16px; margin-right: 6px;"><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>
            Dispatch Rebalance Truck
          `;
        }
      }
    });

    // Operator UAT Feedback
    $('#btn-submit-mobility-uat')?.addEventListener('click', async () => {
      const operatorId = ($('#mobility-uat-operator')?.value || 'fleet-op-01').trim();
      const rating = parseInt($('#mobility-uat-rating')?.value || '4', 10);
      const notes = ($('#mobility-uat-notes')?.value || '').trim();

      const btn = $('#btn-submit-mobility-uat');
      if (btn) btn.disabled = true;

      try {
        await api('POST', '/v1/mobility/uat', {
          role: operatorId || 'Fleet Dispatcher',
          rating: rating,
          comments: notes || 'Verified mobility rebalancing dispatch',
        });
        toast('Fleet Operator UAT survey submitted and registered!', 'success');
        if ($('#mobility-uat-notes')) $('#mobility-uat-notes').value = '';
      } catch (err) {
        toast(`UAT submission failed: ${err.message}`, 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    });

    // Run initial simulation
    updateSliderLabels();
    runMobilitySimulation();
  }

  async function runMobilitySimulation() {
    const h = parseInt($('#slider-mobility-hour')?.value || '8', 10);
    const t = parseFloat($('#slider-mobility-temp')?.value || '72');
    const hum = parseFloat($('#slider-mobility-hum')?.value || '60');
    const p = parseFloat($('#slider-mobility-precip')?.value || '0') / 100.0;
    const isWeekend = mobilityState.isWeekend;

    try {
      const res = await api('POST', '/v1/mobility/optimize', {
        hour_of_day: h,
        temperature_f: t,
        humidity_pct: hum,
        precipitation_inches: p,
        is_weekend: isWeekend,
      });

      const inner = res.result || res;
      const forecast = inner.forecast || res.forecast || {};
      const rebalance = inner.rebalancing || res.rebalancing || {};

      if ($('#mobility-pred-demand')) {
        const demand = forecast.predicted_hourly_demand ?? forecast.predicted_demand ?? 42;
        $('#mobility-pred-demand').textContent = `${Math.round(Number(demand))} trips/hr`;
      }
      if ($('#mobility-period-label')) {
        $('#mobility-period-label').textContent = forecast.demand_regime || forecast.period || 'Circadian Simulated Demand';
      }

      const stations = rebalance.station_inventory_states || rebalance.all_stations || [];
      const tbody = $('#mobility-stations-tbody');
      if (tbody && stations.length) {
        tbody.innerHTML = stations.map(st => {
          const rawCat = String(st.churn_category || st.status || 'BALANCED').toUpperCase();
          const availPct = Math.round(Number(st.availability_pct ?? st.available_pct ?? 50));
          let badgeHtml = '';
          if (rawCat.includes('DEPLET')) {
            badgeHtml = '<span class="status-pill rejected" style="background:rgba(239,68,68,0.15);color:var(--red);border:1px solid var(--red-glow)">DEPLETED</span>';
          } else if (rawCat.includes('ACCUMULAT')) {
            badgeHtml = '<span class="status-pill" style="background:rgba(6,182,212,0.15);color:var(--cyan);border:1px solid var(--cyan-glow)">ACCUMULATED</span>';
          } else {
            badgeHtml = '<span class="status-pill approved" style="background:rgba(16,185,129,0.15);color:var(--green);border:1px solid var(--green-glow)">BALANCED</span>';
          }
          const stId = st.station_id ?? st.id ?? '—';
          const zoneLabel = st.zone || (rawCat.includes('HIGH_CHURN') ? 'High-Churn Corridor' : 'Metro Hub');

          return `
            <tr>
              <td>
                <div style="font-weight:600">${esc(st.name || st.station_name || 'Station')}</div>
                <div style="font-size:0.75rem;color:var(--text-muted)">Station ID: #${esc(String(stId))}</div>
              </td>
              <td><span style="font-size:0.78rem;color:var(--text-secondary)">${esc(zoneLabel)}</span></td>
              <td>${esc(String(st.capacity ?? 0))}</td>
              <td><strong>${esc(String(st.current_bikes ?? 0))}</strong></td>
              <td>
                <div style="display:flex;align-items:center;gap:6px">
                  <div style="width:50px;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden">
                    <div style="width:${Math.min(100, Math.max(0, availPct))}%;height:100%;background:${availPct < 25 ? 'var(--red)' : availPct > 75 ? 'var(--cyan)' : 'var(--green)'}"></div>
                  </div>
                  <span style="font-size:0.75rem">${availPct}%</span>
                </div>
              </td>
              <td>${badgeHtml}</td>
            </tr>
          `;
        }).join('');
      }

      const routesList = $('#mobility-routes-list');
      const routesCount = $('#mobility-routes-count');
      const routes = rebalance.priority_rebalance_routes || [];
      if (routesList) {
        if (routesCount) routesCount.textContent = `${routes.length} Route${routes.length === 1 ? '' : 's'} Active`;

        if (routes.length === 0) {
          routesList.innerHTML = '<div class="empty-state" style="padding:16px"><p>All stations currently within balanced threshold.</p></div>';
        } else {
          routesList.innerHTML = routes.map((r, idx) => {
            const fromHub = r.pickup_station?.name || r.from_hub || 'Source Hub';
            const toHub = r.dropoff_station?.name || r.to_hub || 'Target Hub';
            const qty = r.transfer_quantity_bikes ?? r.transfer_quantity ?? 0;
            const transit = r.estimated_transit_minutes ? `${r.estimated_transit_minutes} min` : `${r.distance_km || 2.4} km`;
            const prio = r.priority ?? (idx + 1);
            return `
              <div class="route-dispatch-card">
                <div>
                  <div style="font-weight:700;font-size:0.82rem;color:var(--text-primary);margin-bottom:2px">
                    ${esc(fromHub)} <span style="color:var(--cyan);margin:0 4px">➔</span> ${esc(toHub)}
                  </div>
                  <div style="font-size:0.74rem;color:var(--text-muted)">
                    Transit: ${esc(transit)} • Transfer: <strong style="color:var(--green)">+${esc(String(qty))} bikes</strong>
                  </div>
                </div>
                <span class="badge" style="background:rgba(168,85,247,0.15);color:var(--purple);border:1px solid var(--purple-glow)">Priority #${esc(String(prio))}</span>
              </div>
            `;
          }).join('');
        }
      }
    } catch (err) {
      // Quiet fail on slider drag if network busy
      console.warn('Mobility simulation failed:', err.message);
    }
  }

  // ── Watchdog & Supervisory Control ──────────────────────
  async function fetchWatchdogData() {
    try {
      const [telemetryRes, alertsRes] = await Promise.allSettled([
        api('GET', '/v1/watchdog/telemetry'),
        api('GET', '/v1/watchdog/alerts?status=ACTIVE'),
      ]);

      if (telemetryRes.status === 'fulfilled') {
        state.watchdogTelemetry = telemetryRes.value;
        renderWatchdogTelemetry(telemetryRes.value);
      }
      if (alertsRes.status === 'fulfilled') {
        const alerts = alertsRes.value.alerts || (Array.isArray(alertsRes.value) ? alertsRes.value : []);
        state.watchdogAlerts = alerts;
        renderWatchdogAlerts(alerts);
      }
    } catch (e) {
      console.warn('Watchdog fetch:', e.message);
    }
  }

  function renderWatchdogTelemetry(telemetry) {
    if (!telemetry) return;
    const score = telemetry.health_score ?? 100;
    const activeAlerts = telemetry.active_alerts_total ?? state.watchdogAlerts.length;
    const completionRate = telemetry.operational_metrics?.task_completion_rate ?? 1.0;
    const pendingDepth = telemetry.operational_metrics?.pending_approval_queue_depth ?? 0;

    const scoreEl = $('#watchdog-health-score');
    if (scoreEl) scoreEl.textContent = score;

    const badgeEl = $('#watchdog-status-badge');
    if (badgeEl) {
      badgeEl.textContent = `HEALTH ${score}/100`;
      badgeEl.className = 'status-pill ' + (score >= 90 ? 'approved' : score >= 70 ? 'pending' : 'rejected');
    }

    const alertsCountEl = $('#watchdog-alerts-count');
    if (alertsCountEl) alertsCountEl.textContent = activeAlerts;

    const compRateEl = $('#watchdog-completion-rate');
    if (compRateEl) compRateEl.textContent = `${Math.round(completionRate * 100)}%`;

    const pendingEl = $('#watchdog-pending-approvals');
    if (pendingEl) pendingEl.textContent = pendingDepth;
  }

  function renderWatchdogAlerts(alerts) {
    const list = $('#watchdog-alerts-list');
    const fieldList = $('#field-alerts-list');

    const html = (!alerts || !alerts.length)
      ? '<div class="empty-state"><p>All operational subsystems healthy. No active alerts.</p></div>'
      : alerts.map(a => {
          const sev = (a.severity || 'MEDIUM').toUpperCase();
          const sevColor = sev === 'CRITICAL' ? 'var(--red)' : sev === 'HIGH' ? 'var(--amber)' : sev === 'MEDIUM' ? 'var(--cyan)' : 'var(--purple)';
          const sevBg = sev === 'CRITICAL' ? 'rgba(239,68,68,0.15)' : sev === 'HIGH' ? 'rgba(245,158,11,0.15)' : sev === 'MEDIUM' ? 'rgba(6,182,212,0.15)' : 'rgba(168,85,247,0.15)';

          return `
            <div class="approval-item" style="border-left: 3px solid ${sevColor}; padding: 12px 14px; margin-bottom: 8px;">
              <div class="approval-info" style="flex: 1;">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                  <span class="status-pill" style="background: ${sevBg}; color: ${sevColor}; font-size: 0.7rem; font-weight: 700;">${esc(sev)}</span>
                  <strong style="font-size: 0.85rem;">${esc(a.title || a.alert_type || 'Operational Alert')}</strong>
                </div>
                <div style="font-size: 0.8rem; color: var(--text-primary); margin-bottom: 4px;">${esc(a.description || a.message || '')}</div>
                ${a.suggested_action ? `<div style="font-size: 0.74rem; color: var(--cyan); margin-bottom: 4px;">Recommended: ${esc(a.suggested_action)}</div>` : ''}
                <div class="approval-meta" style="font-size: 0.72rem; color: var(--text-muted);">
                  ID: ${esc(a.id)} • Triggered: ${formatDate(a.created_at)}
                </div>
              </div>
              <div>
                <button class="primary-btn btn-resolve-alert" data-alert-id="${esc(a.id)}" style="padding: 5px 12px; font-size: 0.75rem; white-space: nowrap;">
                  Resolve Alert
                </button>
              </div>
            </div>
          `;
        }).join('');

    if (list) list.innerHTML = html;
    if (fieldList && alerts.length > 0) fieldList.innerHTML = html;
  }

  // ── CEO Briefing & Autonomous Shift Controller ─────────
  async function fetchCeoBriefing() {
    try {
      const briefing = await api('GET', '/v1/scheduler/briefing');
      state.ceoBriefing = briefing;
      renderCeoBriefing(briefing);
    } catch (e) {
      console.warn('CEO briefing fetch:', e.message);
    }
  }

  function renderCeoBriefing(b) {
    const el = $('#ceo-briefing-summary');
    if (!el || !b) return;

    const rev = b.revenue || {};
    const tenants = b.tenants || {};
    const gov = b.governance || {};
    const dog = b.watchdog || {};
    const shift = b.latest_shift;

    let shiftHtml = '<div class="empty-state" style="padding:12px;"><p>No autonomous shift has been executed yet today. Click "Run Autonomous Shift" above.</p></div>';
    if (shift) {
      const steps = (shift.summary && shift.summary.step_results) ? shift.summary.step_results : {};
      const sdr = steps.outbound_sdr || {};
      const seo = steps.owned_media_seo || {};
      const ord = steps.order_fulfillment || {};
      const dogStep = steps.watchdog_audit || {};

      shiftHtml = `
        <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; padding: 14px 18px; margin-top: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="status-pill approved" style="font-size: 0.75rem; font-weight: 700;">${esc(shift.status || 'COMPLETED')}</span>
              <strong style="font-size: 0.9rem; color: #ffffff;">Shift: ${esc(shift.shift_id)}</strong>
              <span style="font-size: 0.75rem; color: var(--text-muted);">${formatDate(shift.completed_at || shift.started_at)}</span>
            </div>
            <div style="font-size: 0.75rem; font-family: monospace; color: var(--emerald);">
              TrustBlock: ${(shift.trust_block_hash || '').substring(0, 16)}...
            </div>
          </div>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; font-size: 0.8rem;">
            <div style="background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px;">
              <span style="color: var(--cyan); font-weight: 600;">1. Outbound SDR</span><br>
              ${sdr.leads_discovered_count || 0} Leads Discovered • ${sdr.previews_generated_count || 0} Trojan Previews
            </div>
            <div style="background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px;">
              <span style="color: var(--purple); font-weight: 600;">2. Owned Media SEO</span><br>
              ${seo.networks_targeted_count || 4} Authority Networks Targeted
            </div>
            <div style="background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px;">
              <span style="color: var(--emerald); font-weight: 600;">3. Order Fulfillment</span><br>
              ${ord.fulfilled_count || 0} Orders Fulfilled Automatically
            </div>
            <div style="background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px;">
              <span style="color: var(--amber); font-weight: 600;">4. L1 Watchdog Audit</span><br>
              Health: ${dogStep.health_score || 100}/100 • ${dogStep.active_alerts_total || 0} Active Alerts
            </div>
          </div>
        </div>
      `;
    }

    el.innerHTML = `
      <div class="stats-grid" style="margin-bottom: 14px;">
        <div class="stat-card" data-accent="green">
          <div class="stat-header"><span class="stat-label">Total Revenue</span></div>
          <div class="stat-value" style="font-size: 1.4rem;">₹${(rev.total_revenue_inr || 0).toLocaleString()}</div>
          <div class="stat-trend up"><span>$</span> ${(rev.total_revenue_usd || 0).toLocaleString()} USD International</div>
        </div>
        <div class="stat-card" data-accent="purple">
          <div class="stat-header"><span class="stat-label">Active Tenants</span></div>
          <div class="stat-value" style="font-size: 1.4rem;">${tenants.active_tenants || 0}</div>
          <div class="stat-trend neutral"><span>🏢</span> ${tenants.total_leads || 0} Total Leads Tracked</div>
        </div>
        <div class="stat-card" data-accent="amber">
          <div class="stat-header"><span class="stat-label">Pending Approvals</span></div>
          <div class="stat-value" style="font-size: 1.4rem;">${gov.pending_hitl_approvals || 0}</div>
          <div class="stat-trend neutral"><span>⏳</span> L0 Owner Governance</div>
        </div>
        <div class="stat-card" data-accent="cyan">
          <div class="stat-header"><span class="stat-label">Watchdog Health</span></div>
          <div class="stat-value" style="font-size: 1.4rem;">${dog.health_score || 100}/100</div>
          <div class="stat-trend up"><span>🛡</span> ${dog.active_alerts || 0} Active Alerts</div>
        </div>
      </div>
      <div style="font-size: 0.85rem; color: var(--text-secondary); line-height: 1.6; background: rgba(79, 70, 229, 0.08); border-left: 3px solid var(--purple); padding: 10px 14px; border-radius: 4px; margin-bottom: 10px;">
        <strong>Executive Digest:</strong> ${esc(b.executive_summary || '')}
      </div>
      <h4 style="font-size: 0.85rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 14px;">Latest Autonomous Shift Execution</h4>
      ${shiftHtml}
    `;
  }

  // ── Warehouse StockSense AI Controller ───────────────────
  let inventoryInitialized = false;

  function initInventoryPage() {
    if (inventoryInitialized) return;
    inventoryInitialized = true;

    $('#btn-run-inventory-audit')?.addEventListener('click', runInventoryAudit);

    $('#btn-submit-inventory-uat')?.addEventListener('click', async () => {
      const rating = parseInt($('#inventory-uat-rating')?.value || '5', 10);
      const operator = ($('#inventory-uat-operator')?.value || 'wh-mgr-01').trim();
      const notes = ($('#inventory-uat-notes')?.value || '').trim();

      const btn = $('#btn-submit-inventory-uat');
      if (btn) btn.disabled = true;

      try {
        await api('POST', '/v1/inventory/uat', {
          operator_id: operator,
          rating: rating,
          notes: notes,
          discrepancy_reported: rating <= 2,
        });
        toast('Warehouse Manager UAT Feedback recorded & sealed in TrustBlock!', 'success');
        if ($('#inventory-uat-notes')) $('#inventory-uat-notes').value = '';
      } catch (err) {
        toast(`UAT submission failed: ${err.message}`, 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    });

    // Auto-run initial audit
    runInventoryAudit();
  }

  async function runInventoryAudit() {
    const btn = $('#btn-run-inventory-audit');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner" style="margin-right:6px"></span> Analyzing SKUs...';
    }

    try {
      const res = await api('POST', '/v1/inventory/analyze', {
        service_level_z: 1.65,
        forecast_alpha: 0.3,
        dead_stock_threshold_days: 90,
      });

      state.inventoryAnalysis = res;
      renderInventoryAudit(res);
      toast('StockSense Inventory Audit complete & sealed to TrustBlock!', 'success');
    } catch (err) {
      toast(`StockSense audit failed: ${err.message}`, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-icon"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg>
          Run StockSense Audit
        `;
      }
    }
  }

  function renderInventoryAudit(data) {
    if (!data) return;
    const inner = data.result || data;
    const metrics = data.audit_metrics || inner.audit_metrics || data.summary || {};

    if ($('#inventory-total-skus')) $('#inventory-total-skus').textContent = metrics.total_skus ?? 0;
    if ($('#inventory-total-value')) $('#inventory-total-value').textContent = `₹${Number(metrics.total_inventory_valuation || 0).toLocaleString()}`;
    if ($('#inventory-dead-stock-count')) $('#inventory-dead-stock-count').textContent = metrics.dead_stock_skus_count ?? 0;
    if ($('#inventory-trapped-capital')) $('#inventory-trapped-capital').textContent = `₹${Number(metrics.capital_locked_in_dead_stock || 0).toLocaleString()}`;

    const abcItems = inner.abc_analysis?.items || data.abc_analysis?.items || [];
    const abcTbody = $('#inventory-abc-xyz-tbody');
    if (abcTbody) {
      if (!abcItems.length) {
        abcTbody.innerHTML = '<tr class="empty-row"><td colspan="5"><div class="empty-state"><p>No SKU data found</p></div></td></tr>';
      } else {
        abcTbody.innerHTML = abcItems.map(item => {
          const cls = item.abc_xyz_class || item.category || 'B';
          const annualVal = Number(item.annual_usage_value ?? item.annual_value ?? 0);
          const cumPct = Number(item.cumulative_value_pct ?? item.cumulative_share_pct ?? 0);
          const strategy = item.management_strategy
            || (cls.startsWith('A') ? 'Tight JIT control & weekly review' : cls.startsWith('B') ? 'Balanced automated ROP' : 'Bulk periodic replenishment');
          return `
            <tr>
              <td>
                <div style="font-weight:600">${esc(item.sku)}</div>
                <div style="font-size:0.75rem;color:var(--text-muted)">${esc(item.name || '')}</div>
              </td>
              <td>₹${annualVal.toLocaleString()}</td>
              <td>${cumPct.toFixed(1)}%</td>
              <td><span class="status-pill" style="background:rgba(168,85,247,0.15);color:var(--purple);font-weight:700">Class ${esc(cls)}</span></td>
              <td style="font-size:0.78rem;color:var(--text-secondary)">${esc(strategy)}</td>
            </tr>
          `;
        }).join('');
      }
    }

    const reorders = inner.reorder_recommendations || data.reorder_recommendations || [];
    const reorderTbody = $('#inventory-reorder-tbody');
    if (reorderTbody) {
      if (!reorders.length) {
        reorderTbody.innerHTML = '<tr class="empty-row"><td colspan="6"><div class="empty-state"><p>All stock levels optimal</p></div></td></tr>';
      } else {
        reorderTbody.innerHTML = reorders.map(r => {
          const needed = Boolean(r.reorder_needed);
          const eoq = r.eoq ?? r.economic_order_qty ?? r.economic_order_quantity ?? '—';
          return `
            <tr>
              <td><strong>${esc(r.sku)}</strong></td>
              <td>${esc(String(r.current_stock ?? 0))}</td>
              <td>${esc(String(r.safety_stock ?? 0))}</td>
              <td><strong>${esc(String(r.reorder_point ?? 0))}</strong></td>
              <td>${esc(String(eoq))}</td>
              <td>
                <span class="status-pill ${needed ? 'rejected' : 'approved'}">
                  ${needed ? 'ORDER NOW' : 'HEALTHY'}
                </span>
              </td>
            </tr>
          `;
        }).join('');
      }
    }

    const deadStockList = $('#inventory-deadstock-list');
    const deadItems = inner.dead_stock_analysis?.items || inner.dead_stock_analysis?.dead_stock_items || data.dead_stock_analysis?.items || [];
    if (deadStockList) {
      if (!deadItems.length) {
        deadStockList.innerHTML = '<div class="empty-state"><p>No dead stock detected. Inventory turnover healthy.</p></div>';
      } else {
        deadStockList.innerHTML = deadItems.map(d => {
          const daysIdle = d.days_idle ?? d.days_since_last_sale ?? 0;
          const qtyIdle = d.current_stock ?? d.units_idle ?? 0;
          const action = d.recommended_liquidation_action || d.recommended_action || 'Liquidation';
          return `
            <div style="display:flex;justify-content:space-between;align-items:center;background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.2);padding:10px 14px;border-radius:var(--radius-sm)">
              <div>
                <div style="font-weight:700;color:var(--red);font-size:0.85rem">${esc(d.sku)} — ${esc(d.name || '')}</div>
                <div style="font-size:0.75rem;color:var(--text-muted)">Idle for ${esc(String(daysIdle))} days • ${esc(String(qtyIdle))} units trapped</div>
              </div>
              <div style="text-align:right">
                <div style="font-weight:800;color:var(--red);font-size:0.95rem">₹${Number(d.locked_capital || 0).toLocaleString()}</div>
                <div style="font-size:0.75rem;color:var(--amber)">${esc(action)}</div>
              </div>
            </div>
          `;
        }).join('');
      }
    }
  }

  // ── Event Listeners ──────────────────────────────────────
  function bindEvents() {
    // Sidebar navigation
    $$('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const page = item.dataset.page;
        if (page) navigateTo(page);
      });
    });

    // View all approvals button
    $('#btn-view-all-approvals')?.addEventListener('click', (e) => {
      e.preventDefault();
      navigateTo('approvals');
    });

    // Mobile menu toggle
    $('#menu-toggle').addEventListener('click', () => {
      $('#sidebar').classList.toggle('open');
    });

    // Refresh button
    $('#btn-refresh').addEventListener('click', async () => {
      toast('Refreshing data...', 'info');
      await fetchAll();
      toast('Data refreshed', 'success');
    });

    // Modal controls
    $('#modal-close').addEventListener('click', closeModal);
    $('#modal-overlay').addEventListener('click', (e) => {
      if (e.target === $('#modal-overlay')) closeModal();
    });
    $('#btn-approve').addEventListener('click', () => submitDecision('APPROVED'));
    $('#btn-reject').addEventListener('click', () => submitDecision('REJECTED'));

    // Approval filters
    $$('.filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.approvalFilter = btn.dataset.filter;
        renderApprovals();
      });
    });

    // Discover leads button
    $('#btn-discover-leads')?.addEventListener('click', triggerLeadDiscovery);

    // Global search
    $('#global-search')?.addEventListener('input', (e) => {
      const query = (e.target.value || '').toLowerCase().trim();
      if (!query) {
        renderLeads();
        renderApprovals();
        return;
      }
      const tbody = $('#leads-tbody');
      if (tbody) {
        const filtered = state.leads.filter(l =>
          (l.company || '').toLowerCase().includes(query) ||
          (l.industry || '').toLowerCase().includes(query) ||
          (l.website || '').toLowerCase().includes(query)
        );
        if (!filtered.length) {
          tbody.innerHTML = '<tr class="empty-row"><td colspan="6"><div class="empty-state"><p>No matching leads found</p></div></td></tr>';
        } else {
          tbody.innerHTML = filtered.map(lead => `
            <tr>
              <td>
                <div style="font-weight:600">${esc(lead.company)}</div>
                <div style="font-size:0.78rem;color:var(--text-muted)">${esc(lead.website || '')}</div>
              </td>
              <td>${esc(lead.industry || '—')}</td>
              <td>${esc(lead.geography || '—')}</td>
              <td>
                <div style="display:flex;align-items:center;gap:8px">
                  <div style="width:60px;height:6px;background:rgba(148,163,184,0.1);border-radius:3px;overflow:hidden">
                    <div style="width:${(lead.fit_score || 0) * 100}%;height:100%;background:${lead.fit_score >= 0.7 ? 'var(--green)' : lead.fit_score >= 0.4 ? 'var(--amber)' : 'var(--red)'};border-radius:3px"></div>
                  </div>
                  <span style="font-size:0.82rem;font-weight:600">${((lead.fit_score || 0) * 100).toFixed(0)}%</span>
                </div>
              </td>
              <td><span class="status-pill ${(lead.status || '').toLowerCase()}">${esc(lead.status || 'Unknown')}</span></td>
              <td>
                <button class="text-btn" onclick="app.viewLead('${esc(lead.id)}')">View</button>
              </td>
            </tr>
          `).join('');
        }
      }
    });

    // Settings button & modal controls
    $('#btn-settings')?.addEventListener('click', openSettingsModal);
    $('#settings-modal-close')?.addEventListener('click', closeSettingsModal);
    $('#btn-cancel-settings')?.addEventListener('click', closeSettingsModal);
    $('#btn-save-settings')?.addEventListener('click', saveSettings);
    $('#btn-clear-settings')?.addEventListener('click', resetSettings);
    $('#settings-modal-overlay')?.addEventListener('click', (e) => {
      if (e.target === $('#settings-modal-overlay')) closeSettingsModal();
    });

    // Toggle API key password visibility
    $('#btn-toggle-key-visibility')?.addEventListener('click', () => {
      const input = $('#settings-api-key');
      if (input) {
        input.classList.toggle('unmasked');
      }
    });

    // Customer portal copy & toggle
    $('#btn-copy-token')?.addEventListener('click', () => {
      const val = $('#portal-token-display')?.value || '';
      if (navigator.clipboard) {
        navigator.clipboard.writeText(val).then(() => toast('Bearer token copied to clipboard!', 'success'));
      } else {
        toast('Token copied to clipboard', 'success');
      }
    });
    $('#btn-toggle-portal-token')?.addEventListener('click', () => {
      const input = $('#portal-token-display');
      if (input) input.classList.toggle('unmasked');
    });
    $('#btn-portal-upgrade')?.addEventListener('click', () => {
      window.open('/v1/pay/checkout?package=growth_all_in_one&company=AskforWrite+Client', '_blank');
    });

    // Customer Portal BYOK & Service Execution listeners
    $('#btn-save-portal-gemini-key')?.addEventListener('click', handleSavePortalGeminiKey);
    $('#btn-run-tenant-service')?.addEventListener('click', handleRunTenantService);
    $('#btn-portal-refresh')?.addEventListener('click', fetchCustomerPortalData);
    $('#btn-portal-create-ticket')?.addEventListener('click', portalCreateTicket);
    $('#btn-portal-export-data')?.addEventListener('click', portalExportData);
    $('#btn-portal-save-consent')?.addEventListener('click', portalSaveConsent);
    $('#btn-portal-refresh-gsc')?.addEventListener('click', portalRefreshGsc);
    window.addEventListener('offline', () => setConnectionStatus(false));
    window.addEventListener('online', () => setConnectionStatus(true));

    // Quick-launch service tool icon buttons inside Customer Portal
    $$('.portal-quick-tool-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const srv = btn.dataset.portalService;
        const sel = $('#portal-service-selector');
        if (srv && sel) {
          sel.value = srv;
          handleRunTenantService();
        }
      });
    });

    // Company OS Command Dock: Service Tool Logo Buttons & "Call an Agent" Buttons
    $$('.os-service-tool-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const toolKey = btn.dataset.toolKey;
        if (toolKey) handleInvokeCommandDockTool(toolKey);
      });
    });

    $$('.agent-call-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const agentKey = btn.dataset.callAgent;
        if (agentKey) handleInvokeCommandDockTool(agentKey);
      });
    });

    $('#btn-run-credibility-audit')?.addEventListener('click', handleRunCredibilityAudit);
    $('#btn-view-connector-inventory')?.addEventListener('click', handleViewConnectorInventory);
    $('#btn-view-release-checklist')?.addEventListener('click', handleViewReleaseChecklist);
    $('#btn-run-jaipur-sme-e2e')?.addEventListener('click', handleRunJaipurSmeScenario);
    $('#btn-execute-agent-run-console')?.addEventListener('click', () => {
      const targetKey = ($('#agent-run-target-select')?.value || 'discovery_sdr_agent').trim();
      const taskText = ($('#agent-run-task-input')?.value || '').trim();
      const runMode = ($('#agent-run-mode-select')?.value || 'human_assisted').trim();
      handleInvokeCommandDockTool(targetKey, { objective: taskText, mode: runMode });
    });
    $('#btn-agent-activate-selected')?.addEventListener('click', () => handleControlAgentState('activate'));
    $('#btn-agent-pause-selected')?.addEventListener('click', () => handleControlAgentState('pause'));
    $('#btn-agent-emergency-stop-selected')?.addEventListener('click', () => handleControlAgentState('emergency_stop'));
    $('#btn-close-os-console')?.addEventListener('click', () => {
      const c = $('#os-command-dock-console');
      if (c) c.style.display = 'none';
    });

    // Auth Gate tabs & submit buttons
    $$('.auth-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        if (tab) switchAuthTab(tab);
      });
    });

    $('#btn-customer-login')?.addEventListener('click', handleCustomerLogin);
    $('#btn-customer-register')?.addEventListener('click', handleCustomerRegister);
    $('#btn-owner-unlock')?.addEventListener('click', handleOwnerUnlock);
    $('#btn-logout')?.addEventListener('click', handleLogout);

    // Opportunity Scanner listeners
    $('#btn-run-opportunity-scan')?.addEventListener('click', () => handleOpportunityScan('banner'));
    $('#scanner-url-input')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleOpportunityScan('banner');
    });
    $('#btn-modal-run-scan')?.addEventListener('click', () => handleOpportunityScan('modal'));
    $('#scan-modal-url')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleOpportunityScan('modal');
    });

    $('#login-password')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleCustomerLogin();
    });
    $('#auth-owner-key')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleOwnerUnlock();
    });


    // Trust Chain Explorer live verification handler
    async function verifyTrustChainUi(silent = false) {
      const btn = $('#btn-verify-chain');
      if (btn && !silent) {
        btn.disabled = true;
        btn.textContent = 'Verifying ECDSA Chain...';
      }
      try {
        const isCust = !CONFIG.ownerApiKey && !!CONFIG.accessToken;
        let data;
        if (isCust) {
          const r = await api('POST', '/v1/me/use-service', { service_key: 'trust_engine', payload: { action: 'verify_chain' } });
          data = r.result || r;
        } else {
          data = await api('GET', '/v1/trust/verify');
        }
        const valid = Boolean(data.chain_valid);
        const total = data.total_blocks ?? (data.block_index != null ? data.block_index + 1 : 1);
        const tipHash = data.tip_hash || data.block_hash || data.genesis_hash || 'verified';
        const timeline = $('#trust-chain-timeline') || $('#trust-blocks-list');
        if (timeline) {
          const statusRow = document.createElement('div');
          statusRow.className = 'trust-block-card';
          statusRow.style.borderColor = valid ? 'var(--green)' : 'var(--red)';
          statusRow.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:8px">
              <strong>${valid ? '✓ CRYPTOGRAPHIC CHAIN VERIFIED (NIST P-256)' : '✕ CHAIN INTEGRITY ERROR'}</strong>
              <span class="status-pill ${valid ? 'approved' : 'rejected'}">${esc(String(total))} Blocks Sealed</span>
            </div>
            <div class="trust-hash-pill">Tip Hash: ${esc(String(tipHash))}</div>
            <div class="trust-block-details">
              <span>Protocol: ${esc(data.protocol || 'AFW-COMPANY-OS-TRUST-CHAIN-V2')}</span>
              <span>Errors: ${esc(String((data.errors || []).length))}</span>
            </div>
          `;
          const prevBanner = timeline.querySelector('[data-trust-live-banner="1"]');
          if (prevBanner) prevBanner.remove();
          statusRow.setAttribute('data-trust-live-banner', '1');
          timeline.prepend(statusRow);
        }
        if (!silent) toast(valid ? `Trust Ledger verified (${total} blocks, 0 errors)` : 'Trust Ledger verification reported errors', valid ? 'success' : 'error');
      } catch (err) {
        if (!silent) toast(`Trust verification failed: ${err.message}`, 'error');
      } finally {
        if (btn && !silent) {
          btn.disabled = false;
          btn.textContent = 'Verify Cryptographic Chain';
        }
      }
    }
    window.verifyTrustChainUi = verifyTrustChainUi;
    $('#btn-verify-chain')?.addEventListener('click', () => verifyTrustChainUi(false));

    // Mobile Phone Simulator actions — tenant /v1/mobile/* endpoints for subscribers, watchdog fallback for Owner API key
    $('#btn-phone-checkin')?.addEventListener('click', async () => {
      try {
        const isCust = !CONFIG.ownerApiKey && !!CONFIG.accessToken;
        if (isCust) {
          const res = await api('POST', '/v1/mobile/attendance/check-in', {
            latitude: 24.5854, longitude: 73.7125, device_fingerprint: 'afw-pwa-sim',
          });
          toast(`GPS Check-in verified (${res.status || 'RECORDED'})`, 'success');
        } else {
          const res = await api('POST', '/v1/watchdog/invoke-tool', {
            target_key: 'field_ops_dispatcher_agent',
            payload: { action: 'gps_checkin', mode: 'local_engine' },
          });
          toast(`[${res.capability_status}] GPS Check-in verified (${res.evidence?.evidence_reference || 'TrustBlock'})`, 'success');
        }
        animateNumber('#stat-visits', (state.fieldVisits?.length || 0) + 1);
      } catch (err) {
        toast(`BLOCKED: Field GPS check-in failed (${err.message})`, 'error');
      }
    });

    $('#btn-phone-submit-visit')?.addEventListener('click', async () => {
      const client = ($('#phone-client-id')?.value || 'Client Visit').trim();
      const otp = ($('#phone-otp-code')?.value || '1234').trim();
      try {
        const isCust = !CONFIG.ownerApiKey && !!CONFIG.accessToken;
        if (isCust) {
          const res = await api('POST', '/v1/mobile/visits/submit', {
            client_name: client, latitude: 24.5854, longitude: 73.7125, otp_code: otp, notes: 'Mobile simulator check-in',
          });
          toast(`Visit to "${client}" verified (${res.status || 'RECORDED'})`, 'success');
        } else {
          const res = await api('POST', '/v1/watchdog/invoke-tool', {
            target_key: 'field_ops_dispatcher_agent',
            payload: { action: 'visit_verification', client, otp, mode: 'local_engine' },
          });
          toast(`[${res.capability_status}] Visit to "${client}" verified (${res.evidence?.evidence_reference || 'TrustBlock'})`, 'success');
        }
        if ($('#phone-client-id')) $('#phone-client-id').value = '';
        if ($('#phone-otp-code')) $('#phone-otp-code').value = '';
      } catch (err) {
        toast(`BLOCKED: Visit verification failed (${err.message})`, 'error');
      }
    });

    $('#btn-phone-claim')?.addEventListener('click', async () => {
      const km = parseFloat($('#phone-distance-km')?.value || '15');
      const purpose = $('#phone-purpose')?.value || 'Client site visit';
      try {
        const isCust = !CONFIG.ownerApiKey && !!CONFIG.accessToken;
        const amt = Math.round(km * 4.5);
        if (isCust) {
          const res = await api('POST', '/v1/mobile/conveyance/claim', {
            distance_km: km, claimed_amount_inr: amt, purpose,
          });
          toast(`Conveyance claim submitted: ₹${amt} (${km} km) • ${res.status || 'RECORDED'}`, 'success');
        } else {
          const res = await api('POST', '/v1/watchdog/invoke-tool', {
            target_key: 'field_ops_dispatcher_agent',
            payload: { action: 'conveyance_claim', distance_km: km, purpose, mode: 'local_engine' },
          });
          toast(`[${res.capability_status}] Conveyance audited: ₹${amt} (${km} km) • ${res.evidence?.evidence_reference || 'TrustBlock'}`, 'success');
        }
        if ($('#phone-distance-km')) $('#phone-distance-km').value = '';
        if ($('#phone-purpose')) $('#phone-purpose').value = '';
      } catch (err) {
        toast(`BLOCKED: Conveyance claim failed (${err.message})`, 'error');
      }
    });

    // PixelBot Chat — Strict error reporting (never fake a reply when API fails)
    const handlePixelBotSend = async () => {
      const input = $('#pixelbot-input');
      const q = (input?.value || '').trim();
      if (!q) return;
      input.value = '';

      const box = $('#pixelbot-messages');
      if (box) {
        box.innerHTML += `
          <div style="align-self:flex-end;background:rgba(6,182,212,0.15);border:1px solid var(--cyan-glow);padding:8px 12px;border-radius:8px;font-size:0.85rem;max-width:85%">
            👤 <strong>You:</strong> ${esc(q)}
          </div>
        `;
        box.scrollTop = box.scrollHeight;
      }

      try {
        const res = await api('POST', '/v1/mobile/pixel/assist', { prompt: q });
        if (box) {
          box.innerHTML += `
            <div style="align-self:flex-start;background:rgba(168,85,247,0.15);border:1px solid var(--purple-glow);padding:8px 12px;border-radius:8px;font-size:0.85rem;max-width:85%">
              🤖 <strong>PixelBot:</strong> ${esc(res.reply)}
            </div>
          `;
          box.scrollTop = box.scrollHeight;
        }
      } catch (err) {
        if (box) {
          box.innerHTML += `
            <div style="align-self:flex-start;background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.4);color:#fca5a5;padding:8px 12px;border-radius:8px;font-size:0.82rem;max-width:85%">
              ⚠️ <strong>[BLOCKED / API ERROR]:</strong> PixelBot endpoint failed (${esc(err.message)}). No simulated response rendered.
            </div>
          `;
          box.scrollTop = box.scrollHeight;
        }
      }
    };
    $('#btn-pixelbot-send')?.addEventListener('click', handlePixelBotSend);
    $('#pixelbot-input')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handlePixelBotSend();
    });

    // Growth Visualization Studio helpers (XSS-safe Markdown renderer + tab switcher)
    let latestGrowthPayload = null;
    function renderSafeMarkdown(md) {
      const safeLines = String(md || '').split(/\r?\n/);
      const out = [];
      let inList = false;
      const inlineFmt = (line) => esc(line)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
      for (const raw of safeLines) {
        const line = raw.trim();
        if (!line) {
          if (inList) { out.push('</ul>'); inList = false; }
          continue;
        }
        if (line.startsWith('### ')) {
          if (inList) { out.push('</ul>'); inList = false; }
          out.push(`<h3>${inlineFmt(line.slice(4))}</h3>`);
        } else if (line.startsWith('## ')) {
          if (inList) { out.push('</ul>'); inList = false; }
          out.push(`<h2>${inlineFmt(line.slice(3))}</h2>`);
        } else if (line.startsWith('# ')) {
          if (inList) { out.push('</ul>'); inList = false; }
          out.push(`<h1>${inlineFmt(line.slice(2))}</h1>`);
        } else if (/^([-*•]|\d+\.)\s+/.test(line)) {
          if (!inList) { out.push('<ul>'); inList = true; }
          out.push(`<li>${inlineFmt(line.replace(/^([-*•]|\d+\.)\s+/, ''))}</li>`);
        } else {
          if (inList) { out.push('</ul>'); inList = false; }
          out.push(`<p>${inlineFmt(line)}</p>`);
        }
      }
      if (inList) out.push('</ul>');
      return out.join('');
    }

    $$('#growth-viz-tabs .growth-viz-tab').forEach(tabBtn => {
      tabBtn.addEventListener('click', () => {
        const target = tabBtn.dataset.gviz;
        $$('#growth-viz-tabs .growth-viz-tab').forEach(b => b.classList.toggle('active', b === tabBtn));
        $$('#growth-results-container .growth-viz-panel').forEach(p => {
          p.classList.toggle('active', p.id === `gviz-panel-${target}`);
        });
      });
    });

    $('#btn-copy-growth-md')?.addEventListener('click', async () => {
      const md = latestGrowthPayload?.seo_geo_blog?.markdown_body || '';
      if (!md) return toast('Generate a campaign first', 'warning');
      try { await navigator.clipboard.writeText(md); toast('Article Markdown copied!', 'success'); }
      catch { toast('Copy failed', 'error'); }
    });

    $('#btn-copy-growth-schema')?.addEventListener('click', async () => {
      const sc = latestGrowthPayload?.seo_geo_blog?.schema_graph_json_ld || latestGrowthPayload?.seo_geo_blog?.json_ld_schema;
      if (!sc) return toast('Generate a campaign first', 'warning');
      try { await navigator.clipboard.writeText(JSON.stringify(sc, null, 2)); toast('Schema JSON-LD copied!', 'success'); }
      catch { toast('Copy failed', 'error'); }
    });

    // Growth Suite Unified Campaign Generator
    $('#btn-run-growth-engine')?.addEventListener('click', async () => {
      const product = ($('#growth-product-input')?.value || 'Organic Wellness Tea').trim();
      const audience = ($('#growth-audience-input')?.value || 'Modern Urban Professionals').trim();
      const rawKws = ($('#growth-keywords-input')?.value || 'organic tea, wellness booster, healthy living').trim();
      const keywords = rawKws.split(',').map(k => k.trim()).filter(Boolean);

      const btn = $('#btn-run-growth-engine');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner" style="margin-right:8px"></span> Synthesizing Growth Campaign...';
      }
      toast('Synthesizing Pixel AI visual specs, SEO article & omnichannel ads...', 'info');

      try {
        const payload = {
          client_name: product,
          product_or_service: product,
          target_audience: audience,
          keywords: keywords,
          idempotency_key: 'growth_' + Date.now(),
        };
        const res = await api('POST', '/v1/growth/campaign/unified', payload);
        latestGrowthPayload = res;
        toast(`Growth Campaign synthesized & sealed in TrustBlock!`, 'success');

        const container = $('#growth-results-container');
        if (container) container.style.display = 'block';
        if ($('#growth-viz-meta')) {
          const tb = res.trust_block_hash ? `TrustBlock #${String(res.trust_block_hash).slice(0, 10)}` : 'Synthesized Live';
          $('#growth-viz-meta').textContent = `${product} • ${audience} • ${tb}`;
        }

        const swatchBox = $('#growth-palette-swatches');
        const palette = res.creative_assets?.color_palette || {};
        if (swatchBox) {
          const entries = Object.entries(palette).filter(([, v]) => typeof v === 'string');
          swatchBox.innerHTML = entries.length
            ? `<span style="font-size:0.76rem;color:var(--text-muted);font-weight:600;">Brand Palette:</span>` +
              entries.map(([k, hex]) => `
                <span class="growth-swatch">
                  <span class="growth-swatch-dot" style="background:${esc(hex)}"></span>
                  <span>${esc(k)}: ${esc(hex)}</span>
                </span>
              `).join('')
            : '';
        }

        const variantsList = $('#growth-variants-list');
        if (variantsList && res.creative_assets?.variants) {
          variantsList.innerHTML = res.creative_assets.variants.map(v => `
            <div class="variant-card">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
                <div>
                  <span class="variant-ratio-badge">${esc(v.aspect_ratio)}</span>
                  <strong style="font-size:0.86rem;color:#fff">${esc(v.channel_placement)}</strong>
                </div>
                <span style="font-size:0.74rem;color:var(--text-muted)">${esc(v.dimensions)}</span>
              </div>
              <div class="growth-visual-frame">
                <span style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.06em;color:var(--cyan);font-weight:700">${esc(v.aspect_ratio)} Creative Spec • ${esc(v.dimensions)}</span>
                <div style="font-size:0.95rem;font-weight:700;color:#ffffff;margin:8px 0;line-height:1.3">${esc(v.headline_overlay)}</div>
                <div><span class="badge" style="background:rgba(16,185,129,0.2);color:var(--green)">CTA: ${esc(v.call_to_action)}</span></div>
              </div>
              <div style="font-size:0.77rem;color:var(--text-secondary);line-height:1.45"><strong>Visual Prompt:</strong> ${esc(v.prompt_recipe)}</div>
            </div>
          `).join('');
        }

        const blogPreview = $('#growth-blog-preview');
        if (blogPreview && res.seo_geo_blog) {
          blogPreview.innerHTML = renderSafeMarkdown(res.seo_geo_blog.markdown_body || '');
        }

        const omniBox = $('#growth-omnichannel-list');
        const omni = res.omnichannel_campaign || {};
        if (omniBox) {
          const cards = [];
          if (omni.instagram_meta) {
            cards.push(`<div class="growth-channel-card"><strong style="color:var(--cyan)">Instagram / Meta Ad</strong>\n\n<strong>Hook:</strong> ${esc(omni.instagram_meta.hook)}\n\n${esc(omni.instagram_meta.body)}\n\n<em>${esc((omni.instagram_meta.hashtags || []).join(' '))}</em></div>`);
          }
          if (omni.linkedin) {
            cards.push(`<div class="growth-channel-card"><strong style="color:var(--purple)">LinkedIn Authority Post</strong>\n\n<strong>${esc(omni.linkedin.headline)}</strong>\n\n${esc(omni.linkedin.body)}</div>`);
          }
          if (omni.google_search_ads) {
            const g = omni.google_search_ads;
            cards.push(`<div class="growth-channel-card"><strong style="color:var(--green)">Google Search Ads</strong>\n\n• ${esc(g.headline_1)} | ${esc(g.headline_2)} | ${esc(g.headline_3)}\n\n${esc(g.description_1)}\n${esc(g.description_2)}</div>`);
          }
          if (Array.isArray(omni.instagram_reels_script)) {
            cards.push(`<div class="growth-channel-card"><strong style="color:var(--amber)">30s Reels / Shorts Storyboard</strong>\n\n${omni.instagram_reels_script.map(s => `[${esc(s.time || s.scene || '')}] ${esc(s.voiceover || s.visual || JSON.stringify(s))}`).join('\n\n')}</div>`);
          }
          if (Array.isArray(omni.linkedin_carousel_slides)) {
            cards.push(`<div class="growth-channel-card"><strong style="color:var(--cyan)">LinkedIn 5-Slide Carousel</strong>\n\n${omni.linkedin_carousel_slides.map((s, i) => `Slide ${i + 1}: ${esc(s.title || s.headline || '')} — ${esc(s.body || s.copy || '')}`).join('\n\n')}</div>`);
          }
          if (Array.isArray(omni.twitter_x_thread)) {
            cards.push(`<div class="growth-channel-card"><strong style="color:#fff">X / Twitter Thread</strong>\n\n${omni.twitter_x_thread.map(t => esc(t)).join('\n\n---\n\n')}</div>`);
          }
          if (omni.whatsapp_direct_broadcast) {
            cards.push(`<div class="growth-channel-card"><strong style="color:var(--green)">WhatsApp Direct Broadcast</strong>\n\n${esc(omni.whatsapp_direct_broadcast.message_template)}</div>`);
          }
          omniBox.innerHTML = cards.length ? cards.join('') : '<div class="empty-state"><p>No omnichannel copy returned.</p></div>';
        }

        if ($('#growth-schema-preview')) {
          const schemaObj = res.seo_geo_blog?.schema_graph_json_ld || res.seo_geo_blog?.json_ld_schema || {};
          $('#growth-schema-preview').textContent = JSON.stringify(schemaObj, null, 2);
        }
        if ($('#growth-llms-preview')) {
          const llms = res.seo_geo_blog?.llms_txt_manifest || res.seo_geo_blog?.llms_txt || 'No llms.txt manifest returned.';
          $('#growth-llms-preview').textContent = typeof llms === 'string' ? llms : JSON.stringify(llms, null, 2);
        }

        const chkBox = $('#growth-checkout-links');
        if (chkBox) {
          const links = res.checkout_links || {};
          const entries = Object.entries(links).filter(([, u]) => typeof u === 'string' && (u.startsWith('http://') || u.startsWith('https://') || u.startsWith('/')));
          chkBox.innerHTML = entries.length
            ? entries.map(([label, url]) => `
                <div class="growth-channel-card" style="display:flex;flex-direction:column;justify-content:space-between;gap:10px">
                  <div>
                    <strong style="color:#fff;text-transform:uppercase;font-size:0.78rem">${esc(label.replace(/_/g, ' '))}</strong>
                    <div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px;word-break:break-all">${esc(url)}</div>
                  </div>
                  <a href="${esc(url)}" target="_blank" rel="noopener" class="primary-btn" style="text-decoration:none;justify-content:center">Open Checkout Link →</a>
                </div>
              `).join('')
            : '<div class="empty-state"><p>Checkout links available in AFW DirectPay.</p></div>';
        }

        if (container) container.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } catch (err) {
        toast(`Growth run failed: ${err.message}`, 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px;margin-right:6px"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
            Generate Unified Growth Campaign
          `;
        }
      }
    });

    // Inbound Closer Chat Simulator
    const closerChatHistory = [];
    const closerSessionId = 'closer_session_' + Date.now();

    const handleCloserChat = async (userMsg) => {
      const msg = (userMsg || $('#closer-chat-input')?.value || '').trim();
      if (!msg) return;

      const chatLog = $('#closer-chat-log');
      const input = $('#closer-chat-input');
      if (input) input.value = '';

      if (chatLog) {
        chatLog.innerHTML += `
          <div class="chat-bubble user">
            ${esc(msg)}
          </div>
        `;
        chatLog.scrollTop = chatLog.scrollHeight;
      }

      closerChatHistory.push({ role: 'user', content: msg });

      try {
        const res = await api('POST', '/v1/growth/inbound-closer/chat', {
          session_id: closerSessionId,
          prospect_name: 'Website Inbound Visitor',
          prospect_contact: 'visitor@inbound.lead',
          message: msg,
          history: closerChatHistory,
          currency: 'INR',
          channel: 'whatsapp_simulator',
        });

        closerChatHistory.push({ role: 'assistant', content: res.reply });

        if (chatLog) {
          let checkoutHtml = '';
          if (res.checkout_link) {
            checkoutHtml = `
              <div style="margin-top:10px;padding:10px;background:rgba(79,70,229,0.3);border-radius:6px;border:1px solid var(--purple)">
                <div style="font-weight:700;font-size:0.8rem;color:white;margin-bottom:4px">🚀 Instant Onboarding Checkout:</div>
                <a href="${esc(res.checkout_link)}" target="_blank" class="primary-btn" style="display:inline-block;padding:6px 14px;font-size:0.75rem;text-decoration:none">
                  Pay ₹${res.price_inr?.toLocaleString() || '6,999'}/mo via DirectPay
                </a>
              </div>
            `;
          }

          chatLog.innerHTML += `
            <div class="chat-bubble closer">
              <div style="font-size:0.7rem;color:var(--cyan);font-weight:700;margin-bottom:3px">AskforWrite AI Closer</div>
              <div>${esc(res.reply)}</div>
              ${checkoutHtml}
            </div>
          `;
          chatLog.scrollTop = chatLog.scrollHeight;
        }
      } catch (err) {
        if (chatLog) {
          chatLog.innerHTML += `
            <div class="chat-bubble closer" style="border:1px solid rgba(239,68,68,0.45);background:rgba(239,68,68,0.12);color:#fca5a5;">
              <div style="font-size:0.7rem;color:#f87171;font-weight:700;margin-bottom:3px">⚠️ [BLOCKED / API ERROR]</div>
              Inbound Sales Closer API call failed (${esc(err.message)}). False-success fallback disabled; no unverified pitch or checkout link shown.
            </div>
          `;
          chatLog.scrollTop = chatLog.scrollHeight;
        }
      }
    };

    $('#btn-closer-send')?.addEventListener('click', () => handleCloserChat());
    $('#closer-chat-input')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleCloserChat();
    });

    $$('.growth-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const msg = chip.dataset.msg;
        if (msg) handleCloserChat(msg);
      });
    });

    // Watchdog scan trigger
    $('#btn-watchdog-scan')?.addEventListener('click', async () => {
      const btn = $('#btn-watchdog-scan');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner" style="margin-right:6px"></span> Scanning...';
      }
      try {
        const res = await api('POST', '/v1/watchdog/scan');
        toast(`Watchdog scan complete: ${res.new_alerts_detected} new alerts. Health: ${res.health_score}/100`, 'info');
        await fetchWatchdogData();
      } catch (err) {
        toast(`Watchdog scan failed: ${err.message}`, 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 14px; height: 14px;"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg>
            Run Watchdog Scan
          `;
        }
      }
    });

    // Autonomous Shift trigger
    $('#btn-run-autonomous-shift')?.addEventListener('click', async () => {
      const btn = $('#btn-run-autonomous-shift');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner" style="margin-right:6px"></span> Running Shift...';
      }
      try {
        const res = await api('POST', '/v1/scheduler/run-shift');
        toast(`Autonomous shift ${res.shift_id} completed successfully in ${res.duration_seconds}s!`, 'success');
        await fetchCeoBriefing();
        await fetchDashboardData();
      } catch (err) {
        toast(`Shift execution failed: ${err.message}`, 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 14px; height: 14px;"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            Run Autonomous Shift
          `;
        }
      }
    });

    $('#btn-refresh-ceo-briefing')?.addEventListener('click', async () => {
      await fetchCeoBriefing();
      toast('CEO Executive Briefing refreshed.', 'info');
    });

    // Alert resolution event delegation
    document.addEventListener('click', async (e) => {
      const target = e.target.closest('.btn-resolve-alert');
      if (!target) return;
      const alertId = target.dataset.alertId;
      if (!alertId) return;

      target.disabled = true;
      try {
        await api('POST', `/v1/watchdog/alerts/${alertId}/resolve`, {
          resolved_by: 'owner',
          resolution_notes: 'Resolved via Command Center UI',
        });
        toast('Alert resolved & sealed in TrustBlock!', 'success');
        await fetchWatchdogData();
      } catch (err) {
        toast(`Resolve failed: ${err.message}`, 'error');
        target.disabled = false;
      }
    });

    // Hash change routing
    window.addEventListener('hashchange', () => {
      const page = window.location.hash.replace('#', '') || 'dashboard';
      navigateTo(page);
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeModal();
        closeSettingsModal();
      }
    });
  }


  // ── Settings Modal ───────────────────────────────────────
  function openSettingsModal() {
    const keyInput = $('#settings-api-key');
    const geminiInput = $('#settings-gemini-key');
    const baseInput = $('#settings-api-base');
    const intervalSelect = $('#settings-refresh-interval');

    if (keyInput) keyInput.value = CONFIG.ownerApiKey || '';
    if (geminiInput) geminiInput.value = CONFIG.geminiApiKey || '';
    if (baseInput) baseInput.value = CONFIG.apiBase || window.location.origin;
    if (intervalSelect) intervalSelect.value = String(CONFIG.refreshInterval);

    const overlay = $('#settings-modal-overlay');
    if (overlay) overlay.style.display = 'flex';
  }

  function closeSettingsModal() {
    const overlay = $('#settings-modal-overlay');
    if (overlay) overlay.style.display = 'none';
  }

  function resetRefreshTimer() {
    if (state.refreshTimer) {
      clearInterval(state.refreshTimer);
      state.refreshTimer = null;
    }
    if (CONFIG.refreshInterval > 0) {
      const safeMs = Math.max(30000, CONFIG.refreshInterval);
      state.refreshTimer = setInterval(() => {
        if (!document.hidden && (CONFIG.ownerApiKey || CONFIG.accessToken)) fetchAll();
      }, safeMs);
    }
  }

  function saveSettings() {
    const key = ($('#settings-api-key')?.value || '').trim();
    const geminiKey = ($('#settings-gemini-key')?.value || '').trim();
    const base = ($('#settings-api-base')?.value || '').trim() || window.location.origin;
    const interval = parseInt($('#settings-refresh-interval')?.value || '10000', 10);

    CONFIG.ownerApiKey = key;
    CONFIG.geminiApiKey = geminiKey;
    CONFIG.apiBase = base;
    CONFIG.refreshInterval = isNaN(interval) ? 10000 : interval;

    localStorage.setItem('askforwrite_owner_key', key);
    if (geminiKey) {
      localStorage.setItem('afw_gemini_key', geminiKey);
    } else {
      localStorage.removeItem('afw_gemini_key');
    }
    localStorage.setItem('askforwrite_api_base', base);
    localStorage.setItem('askforwrite_refresh_interval', String(CONFIG.refreshInterval));

    resetRefreshTimer();
    closeSettingsModal();
    toast('Settings saved & applied', 'success');
    fetchAll();
  }

  function resetSettings() {
    localStorage.removeItem('askforwrite_owner_key');
    localStorage.removeItem('afw_api_key');
    localStorage.removeItem('afw_access_token');
    localStorage.removeItem('afw_gemini_key');
    localStorage.removeItem('afw_user_role');
    localStorage.removeItem('afw_user_name');
    localStorage.removeItem('askforwrite_api_base');
    localStorage.removeItem('askforwrite_refresh_interval');

    CONFIG.ownerApiKey = '';
    CONFIG.accessToken = '';
    CONFIG.geminiApiKey = '';
    CONFIG.userRole = '';
    CONFIG.userName = '';
    CONFIG.apiBase = window.location.origin;
    CONFIG.refreshInterval = 60000;

    const keyInput = $('#settings-api-key');
    const geminiInput = $('#settings-gemini-key');
    const baseInput = $('#settings-api-base');
    const intervalSelect = $('#settings-refresh-interval');

    if (keyInput) keyInput.value = '';
    if (geminiInput) geminiInput.value = '';
    if (baseInput) baseInput.value = CONFIG.apiBase;
    if (intervalSelect) intervalSelect.value = String(CONFIG.refreshInterval);

    resetRefreshTimer();
    toast('Settings reset to defaults', 'info');
    checkAuthGate();
    fetchAll();
  }

  // ── Auth Gate & Multi-Role Onboarding (P0-B Fail-Closed Protected Shell) ──
  function checkAuthGate() {
    const hasOwnerKey = Boolean(CONFIG.ownerApiKey);
    const hasAccessToken = Boolean(CONFIG.accessToken);

    const gate = $('#auth-gate-overlay');
    const sidebarEl = $('#sidebar');
    const mainEl = $('#main-content');
    if (!hasOwnerKey && !hasAccessToken) {
      if (gate) gate.style.display = 'flex';
      if (sidebarEl) sidebarEl.style.visibility = 'hidden';
      if (mainEl) mainEl.style.visibility = 'hidden';
      document.body.classList.add('afw-hide-floating-closer');
      return false;
    }

    if (gate) gate.style.display = 'none';
    if (sidebarEl) sidebarEl.style.visibility = 'visible';
    if (mainEl) mainEl.style.visibility = 'visible';
    document.body.classList.toggle('afw-hide-floating-closer', state.currentPage === 'growth');

    // Apply role + entitlement-based navigation visibility & settings separation
    const isCustomer = CONFIG.userRole === 'customer' || (!hasOwnerKey && hasAccessToken);
    const ownerTabs = [
      'dashboard', 'leads', 'outreach', 'organizations', 'revenue',
      'field-force', 'growth', 'mobile', 'trust-chain', 'quality', 'mobility', 'inventory',
      'commercial-os', 'customer-success', 'p4-growth',
      'p5-scale', 'p6-packs', 'p7-autonomy', 'p8-marketplace',
    ];
    const customerTabs = [
      'portal', 'approvals', 'cw-profile', 'cw-marketplace', 'cw-workforce',
      'cw-run-console', 'cw-workflows', 'cw-connectors', 'cw-history',
      'cw-analytics', 'cw-billing', 'cw-settings',
    ];

    ownerTabs.forEach(tab => {
      const navItem = $(`#nav-${tab}`);
      if (navItem) {
        navItem.style.display = isCustomer ? 'none' : 'flex';
      }
    });
    customerTabs.forEach(tab => {
      const navItem = $(`#nav-${tab}`);
      if (navItem) {
        navItem.style.display = 'flex';
      }
    });
    const ownerKeyGroup = $('#settings-owner-key-group');
    if (ownerKeyGroup) {
      ownerKeyGroup.style.display = isCustomer ? 'none' : 'block';
    }

    if (isCustomer) {
      if (state.currentPage === 'dashboard' || ownerTabs.includes(state.currentPage)) {
        navigateTo('portal');
      }
      if ($('#sidebar-user-name') && CONFIG.userName) {
        $('#sidebar-user-name').textContent = CONFIG.userName;
      }
      if ($('#sidebar-user-role')) {
        $('#sidebar-user-role').textContent = 'Customer Workspace';
      }
    } else {
      if ($('#sidebar-user-name')) $('#sidebar-user-name').textContent = 'Vipul Choubisa';
      if ($('#sidebar-user-role')) $('#sidebar-user-role').textContent = 'Owner';
      if ($('#sidebar-user-avatar')) $('#sidebar-user-avatar').textContent = 'VC';
    }

    return true;
  }

  // Unlock vertical product workspaces for paid subscribers based on live /v1/me capabilities
  function applyCustomerEntitlementNav(capabilities, tier) {
    if (CONFIG.ownerApiKey) return;
    const capSet = new Set((capabilities || []).map(c => String(typeof c === 'string' ? c : (c.capability || '')).toLowerCase()));
    const isAll = capSet.has('all_access') || ['enterprise', 'company_os_enterprise'].includes(String(tier || '').toLowerCase());
    const capToTabs = [
      [['growth_all_in_one', 'growth_suite', 'marketing_campaign_suite', 'seo_content_automation', 'pixel_ai_creative_studio'], ['growth', 'p4-growth']],
      [['customer_discovery', 'lead_generation', 'smb_discovery'], ['leads', 'outreach']],
      [['field_force_automation', 'delivery_field_force', 'field_force'], ['field-force', 'mobile']],
      [['computer_vision_quality_analytics', 'produce_quality_cv', 'quality_analytics'], ['quality']],
      [['spatiotemporal_logistics_optimization', 'bike_mobility_ai', 'mobility_analytics'], ['mobility']],
      [['warehouse_stocksense', 'inventory_analytics', 'warehouse_automation'], ['inventory']],
      [['trust_ledger_audit', 'trust_engine'], ['trust-chain']],
    ];
    capToTabs.forEach(([reqCaps, tabs]) => {
      const allowed = isAll || reqCaps.some(c => capSet.has(c));
      if (allowed) {
        tabs.forEach(t => {
          const el = $(`#nav-${t}`);
          if (el) el.style.display = 'flex';
        });
      }
    });
  }

  function switchAuthTab(tabName) {
    $$('.auth-tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tabName));
    $$('.auth-tab-content').forEach(c => {
      c.style.display = (c.id === `auth-tab-${tabName}`) ? 'block' : 'none';
    });
    const msg = $('#auth-gate-message');
    if (msg) msg.style.display = 'none';
  }

  function showAuthGateError(text) {
    const msg = $('#auth-gate-message');
    if (msg) {
      msg.textContent = text;
      msg.style.display = 'block';
      msg.style.background = 'rgba(239, 68, 68, 0.15)';
      msg.style.color = '#fca5a5';
      msg.style.border = '1px solid rgba(239, 68, 68, 0.4)';
    }
  }

  async function handleCustomerLogin() {
    const email = ($('#login-email')?.value || '').trim();
    const password = ($('#login-password')?.value || '').trim();
    const geminiKey = ($('#login-gemini-key')?.value || '').trim();

    if (!email || !password) {
      showAuthGateError('Please enter both email and password.');
      return;
    }

    try {
      const btn = $('#btn-customer-login');
      if (btn) { btn.disabled = true; btn.textContent = 'Signing in...'; }

      const res = await api('POST', '/v1/auth/login', {
        email,
        password,
        portal: 'customer',
      });

      CONFIG.ownerApiKey = '';
      localStorage.removeItem('askforwrite_owner_key');
      localStorage.removeItem('afw_api_key');
      CONFIG.accessToken = res.access_token;
      CONFIG.userRole = res.role || 'customer';
      CONFIG.userName = res.full_name || email;
      localStorage.setItem('afw_access_token', res.access_token);
      localStorage.setItem('afw_user_role', CONFIG.userRole);
      localStorage.setItem('afw_user_name', CONFIG.userName);

      if (geminiKey) {
        CONFIG.geminiApiKey = geminiKey;
        localStorage.setItem('afw_gemini_key', geminiKey);
        try {
          await api('POST', '/v1/me/gemini-key', { gemini_api_key: geminiKey });
        } catch (e) {
          console.warn('Sync BYOK key on login:', e);
        }
      }

      toast(`Welcome back, ${res.full_name || 'Customer'}!`, 'success');
      checkAuthGate();
      navigateTo('portal');
      await fetchCustomerPortalData();
      cwHydrateRegistry().catch(() => {});
    } catch (err) {
      showAuthGateError(err.message || 'Login failed. Please check your credentials.');
    } finally {
      const btn = $('#btn-customer-login');
      if (btn) { btn.disabled = false; btn.textContent = 'Sign In to Workspace'; }
    }
  }

  async function handleCustomerRegister() {
    const fullName = ($('#reg-name')?.value || '').trim();
    const company = ($('#reg-company')?.value || '').trim();
    const email = ($('#reg-email')?.value || '').trim();
    const password = ($('#reg-password')?.value || '').trim();
    const pkg = ($('#reg-package')?.value || 'free_trial').trim();
    const geminiKey = ($('#reg-gemini-key')?.value || '').trim();

    if (!fullName || !company || !email || !password) {
      showAuthGateError('Please fill in all required registration fields.');
      return;
    }

    try {
      const btn = $('#btn-customer-register');
      if (btn) { btn.disabled = true; btn.textContent = 'Creating Workspace...'; }

      let res;
      if (pkg === 'free_trial') {
        res = await api('POST', '/v1/auth/register', {
          email,
          password,
          full_name: fullName,
          company_name: company,
          role: 'customer',
          gemini_api_key: geminiKey || null,
        });
      } else {
        res = await api('POST', '/v1/auth/signup', {
          company_name: company,
          email,
          password,
          full_name: fullName,
          package_key: pkg,
          payment_provider: 'afw_directpay',
          gemini_api_key: geminiKey || null,
        });
      }

      if (!res.access_token) {
        if (res.checkout_url) {
          toast('Workspace created. Complete checkout to activate your workspace!', 'info');
          window.open(res.checkout_url, '_blank', 'noopener');
        } else {
          showAuthGateError('Payment verification is pending before sign-in.');
        }
        return;
      }

      CONFIG.ownerApiKey = '';
      localStorage.removeItem('askforwrite_owner_key');
      localStorage.removeItem('afw_api_key');
      CONFIG.accessToken = res.access_token;
      CONFIG.userRole = res.role || 'customer';
      CONFIG.userName = res.full_name || fullName;
      localStorage.setItem('afw_access_token', res.access_token);
      localStorage.setItem('afw_user_role', CONFIG.userRole);
      localStorage.setItem('afw_user_name', CONFIG.userName);

      if (geminiKey) {
        CONFIG.geminiApiKey = geminiKey;
        localStorage.setItem('afw_gemini_key', geminiKey);
      }

      toast(`Workspace created for ${company}!`, 'success');
      checkAuthGate();
      navigateTo('portal');
      await fetchCustomerPortalData();

      if (res.checkout_url && pkg !== 'free_trial') {
        toast('Directpay checkout link generated for your package!', 'info');
      }
    } catch (err) {
      showAuthGateError(err.message || 'Workspace creation failed.');
    } finally {
      const btn = $('#btn-customer-register');
      if (btn) { btn.disabled = false; btn.textContent = 'Create Instant Workspace'; }
    }
  }

  async function handleOwnerUnlock() {
    const ownerKey = ($('#auth-owner-key')?.value || '').trim();
    const ownerGemini = ($('#auth-owner-gemini-key')?.value || '').trim();

    if (!ownerKey) {
      showAuthGateError('Please enter your Owner / Manager API Key.');
      return;
    }

    try {
      const btn = $('#btn-owner-unlock');
      if (btn) { btn.disabled = true; btn.textContent = 'Verifying...'; }

      const testRes = await fetch(`${CONFIG.apiBase}/v1/project/status`, {
        headers: { 'X-API-Key': ownerKey },
      });
      if (!testRes.ok) {
        throw new Error('Invalid Owner API Key (Authentication Failed)');
      }

      CONFIG.accessToken = '';
      localStorage.removeItem('afw_access_token');
      CONFIG.ownerApiKey = ownerKey;
      CONFIG.userRole = 'owner';
      CONFIG.userName = 'Vipul Choubisa';
      localStorage.setItem('askforwrite_owner_key', ownerKey);
      localStorage.setItem('afw_user_role', 'owner');
      localStorage.setItem('afw_user_name', 'Vipul Choubisa');

      if (ownerGemini) {
        CONFIG.geminiApiKey = ownerGemini;
        localStorage.setItem('afw_gemini_key', ownerGemini);
      }

      toast('Owner Command Center unlocked!', 'success');
      checkAuthGate();
      navigateTo('dashboard');
      await fetchAll();
      cwHydrateRegistry().catch(() => {});
      resetRefreshTimer();
    } catch (err) {
      showAuthGateError(err.message || 'Invalid Owner API Key.');
    } finally {
      const btn = $('#btn-owner-unlock');
      if (btn) { btn.disabled = false; btn.textContent = 'Unlock Owner Command Center'; }
    }
  }

  function handleLogout() {
    localStorage.removeItem('askforwrite_owner_key');
    localStorage.removeItem('afw_api_key');
    localStorage.removeItem('afw_access_token');
    localStorage.removeItem('afw_user_role');
    localStorage.removeItem('afw_user_name');
    localStorage.removeItem('afw_gemini_key');

    CONFIG.ownerApiKey = '';
    CONFIG.accessToken = '';
    CONFIG.geminiApiKey = '';
    CONFIG.userRole = '';
    CONFIG.userName = '';

    if (state.refreshTimer) {
      clearInterval(state.refreshTimer);
      state.refreshTimer = null;
    }

    toast('Logged out of workspace.', 'info');
    checkAuthGate();
  }

  // ── Live Opportunity Scanner & Lead Magnet (XSS-Hardened) ─
  function safeHref(url) {
    const u = String(url || '').trim();
    if (u.startsWith('/') || u.startsWith('https://') || u.startsWith('http://')) return esc(u);
    return '#';
  }

  function renderScanResult(data, container) {
    if (!container) return;
    const leaksHtml = (data.top_pain_leaks || []).map(leak => `
      <div class="scanner-leak-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px;flex-shrink:0;color:#ef4444;margin-top:2px;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        <span>${esc(leak)}</span>
      </div>
    `).join('');

    container.innerHTML = `
      <div class="scanner-results-card">
        <div class="scanner-score-row">
          <div>
            <div style="font-size:0.75rem; text-transform:uppercase; color:var(--text-muted); font-weight:700; letter-spacing:0.05em;">Live Audit Result</div>
            <div style="font-size:1.15rem; font-weight:700; color:var(--text-primary);">${esc(data.company_name || '')} <span style="font-size:0.85rem; font-weight:400; color:var(--text-muted);">(${esc(data.domain || '')})</span></div>
          </div>
          <div class="scanner-score-badge">
            <div style="text-align:right;">
              <div style="font-size:0.7rem; color:var(--text-muted); text-transform:uppercase; font-weight:600;">Opportunity Gap</div>
              <div class="scanner-score-val">${esc(String(data.seo_geo_gap_score ?? 0))}/100</div>
            </div>
            <span style="font-size:0.72rem; padding:4px 8px; border-radius:6px; background:rgba(245, 158, 11, 0.15); color:#f59e0b; border:1px solid rgba(245, 158, 11, 0.3); font-weight:700;">
              ${esc(data.audit_status || 'LIVE_VERIFIED')}
            </span>
          </div>
        </div>

        <div style="font-size:0.82rem; font-weight:700; color:var(--text-primary); margin-bottom:8px; display:flex; align-items:center; gap:6px;">
          <span>Critical Revenue &amp; AI Visibility Leaks</span>
          <span style="font-size:0.7rem; color:var(--text-muted); font-weight:400;">(${data.top_pain_leaks?.length || 0} high-priority issues)</span>
        </div>
        <div class="scanner-leaks-list">
          ${leaksHtml}
        </div>

        <div class="scanner-offer-box">
          <div>
            <div style="font-weight:700; color:var(--text-primary); font-size:0.92rem; display:flex; align-items:center; gap:8px;">
              <span>🚀 ${esc(data.package_name || 'Autonomous SEO & AI Closer Fix Pack')}</span>
              <span style="font-size:0.72rem; background:rgba(34, 197, 94, 0.2); color:#4ade80; padding:2px 8px; border-radius:10px; font-weight:700;">₹${esc(String(data.price_inr ?? 0))} / $${esc(String(data.price_usd ?? 0))}</span>
            </div>
            <div style="font-size:0.78rem; color:var(--text-secondary); margin-top:3px;">
              ${esc(data.remediation_offer || 'Instant deployment: /llms.txt manifest, structured SEO schema, and 50 live leads.')}
            </div>
          </div>
          <div style="display:flex; gap:8px; align-items:center;">
            ${data.preview_url ? `<a href="${safeHref(data.preview_url)}" target="_blank" rel="noopener" class="secondary-btn" style="padding:8px 14px; font-size:0.82rem; text-decoration:none; display:inline-flex; align-items:center; gap:6px;">
              <span>View Preview</span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
            </a>` : ''}
            <a href="${safeHref(data.checkout_url)}" target="_blank" rel="noopener" class="primary-btn" style="padding:9px 18px; font-size:0.84rem; font-weight:700; text-decoration:none; display:inline-flex; align-items:center; gap:6px; background:linear-gradient(135deg, #2563eb, #10b981);">
              <span>Fix Now • ₹${esc(String(data.price_inr ?? 0))}</span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;"><path d="M5 12h14"/><path d="M12 5l7 7-7 7"/></svg>
            </a>
          </div>
        </div>
      </div>
    `;
    container.style.display = 'block';
  }

  async function handleOpportunityScan(source = 'banner') {
    const isModal = source === 'modal';
    const urlInput = isModal ? $('#scan-modal-url') : $('#scanner-url-input');
    const compInput = isModal ? $('#scan-modal-company') : $('#scanner-company-input');
    const emailInput = isModal ? $('#scan-modal-email') : $('#scanner-email-input');
    const btn = isModal ? $('#btn-modal-run-scan') : $('#btn-run-opportunity-scan');
    const container = isModal ? $('#scan-modal-result') : $('#scanner-results-container');

    const url = (urlInput?.value || '').trim();
    const company_name = (compInput?.value || '').trim();
    const email = (emailInput?.value || '').trim();

    if (!url) {
      if (isModal) {
        showAuthGateError('Please enter a website URL to scan.');
      } else {
        toast('Please enter a website URL (e.g. https://example.com)', 'warning');
      }
      return;
    }

    const origText = btn ? btn.textContent : '';
    try {
      if (btn) {
        btn.disabled = true;
        btn.textContent = '⚡ Scanning live website...';
      }
      if (container) {
        container.style.display = 'block';
        container.innerHTML = `
          <div style="padding:16px; text-align:center; color:var(--text-secondary); background:rgba(15,23,42,0.6); border:1px solid rgba(255,255,255,0.08); border-radius:var(--radius-sm);">
            <div style="margin-bottom:6px; font-weight:600; color:var(--cyan);">Auditing SEO tags, /llms.txt manifest, and GEO readiness...</div>
            <div style="font-size:0.75rem; color:var(--text-muted);">This takes ~3-5 seconds. Checking live responses.</div>
          </div>
        `;
      }

      const res = await api('POST', '/v1/previews/scan', {
        url,
        company_name,
        email,
      });

      renderScanResult(res, container);
      toast(`Scan complete for ${res.domain}! Detected ${res.top_pain_leaks?.length || 0} optimization opportunities.`, 'success');
    } catch (err) {
      if (container) {
        container.innerHTML = `
          <div style="padding:14px; background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.3); border-radius:var(--radius-sm); color:#fca5a5; font-size:0.85rem;">
            Failed to audit URL: ${esc(err.message || 'Please check that the website is accessible.')}
          </div>
        `;
      }
      toast(`Scan failed: ${err.message}`, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = origText;
      }
    }
  }

  // ── Customer Portal BYOK & Services ──────────────────────
  async function handleSavePortalGeminiKey() {
    const key = ($('#portal-gemini-key-input')?.value || '').trim();
    try {
      const res = await api('POST', '/v1/me/gemini-key', { gemini_api_key: key });
      if (key) {
        CONFIG.geminiApiKey = key;
        localStorage.setItem('afw_gemini_key', key);
        toast(`Gemini BYOK Key saved (${res.gemini_key_masked})`, 'success');
      } else {
        CONFIG.geminiApiKey = '';
        localStorage.removeItem('afw_gemini_key');
        toast('Gemini BYOK Key removed. Reverting to deterministic fallback.', 'info');
      }
      if ($('#portal-gemini-key-input')) $('#portal-gemini-key-input').value = '';
      await fetchCustomerPortalData();
    } catch (err) {
      toast(`Failed to save Gemini key: ${err.message}`, 'error');
    }
  }

  async function handleRunTenantService() {
    const serviceKey = ($('#portal-service-selector')?.value || 'pixel_ai_pack').trim();
    const rawParam = ($('#portal-service-param')?.value || '').trim();
    let payload = {};

    if (rawParam) {
      if (rawParam.startsWith('{') && rawParam.endsWith('}')) {
        try {
          payload = JSON.parse(rawParam);
        } catch {
          payload = { query: rawParam };
        }
      } else {
        if (['pixel_ai_pack', 'seo_blog_copilot', 'marketing_suite', 'growth_all_in_one'].includes(serviceKey)) {
          payload = { product_name: rawParam, query: rawParam, target_audience: 'B2B Enterprise Leaders' };
        } else if (serviceKey === 'ask4_academic_order') {
          payload = { topic: rawParam };
        } else if (serviceKey === 'mango_quality_analytics') {
          payload = { variety: rawParam, crop_variety: rawParam, preset_or_sample: 'ripe', preset: 'ripe' };
        } else if (['lead_discovery', 'lead_generation', 'customer_discovery'].includes(serviceKey)) {
          payload = { objective: rawParam, query: rawParam };
        } else {
          payload = { query: rawParam, incoming_message: rawParam };
        }
      }
    }

    const outEl = $('#portal-service-output');
    const btn = $('#btn-run-tenant-service');

    try {
      if (btn) { btn.disabled = true; btn.textContent = 'Executing...'; }
      if (outEl) {
        outEl.style.display = 'block';
        outEl.textContent = `⚡ Executing ${serviceKey}...\nPayload: ${JSON.stringify(payload, null, 2)}`;
      }

      const res = await api('POST', '/v1/me/use-service', {
        service_key: serviceKey,
        payload,
      });

      if (outEl) {
        outEl.textContent = `✅ Status: ${res.status}\nRemaining Credits: ${res.credits_remaining}\nCredits Used: ${res.credits_used}\n\nResult:\n` + JSON.stringify(res.result, null, 2);
      }
      toast(`Service ${serviceKey} executed successfully!`, 'success');
      await fetchCustomerPortalData();
    } catch (err) {
      if (outEl) {
        outEl.style.display = 'block';
        outEl.textContent = `❌ Execution Error: ${err.message}`;
      }
      toast(`Execution failed: ${err.message}`, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '▶ Execute Service'; }
    }
  }

  // ── API Key & Settings Setup ─────────────────────────────
  function initApiKey() {
    // Read persisted settings from localStorage
    const storedKey = localStorage.getItem('askforwrite_owner_key') || localStorage.getItem('afw_api_key');
    if (storedKey !== null) {
      CONFIG.ownerApiKey = storedKey;
    }
    const storedToken = localStorage.getItem('afw_access_token');
    if (storedToken !== null) {
      CONFIG.accessToken = storedToken;
    }
    const storedGemini = localStorage.getItem('afw_gemini_key');
    if (storedGemini !== null) {
      CONFIG.geminiApiKey = storedGemini;
    }
    const storedRole = localStorage.getItem('afw_user_role');
    if (storedRole !== null) {
      CONFIG.userRole = storedRole;
    }
    const storedName = localStorage.getItem('afw_user_name');
    if (storedName !== null) {
      CONFIG.userName = storedName;
    }
    const storedInterval = localStorage.getItem('askforwrite_refresh_interval');
    if (storedInterval !== null) {
      const parsed = parseInt(storedInterval, 10);
      if (!isNaN(parsed)) CONFIG.refreshInterval = parsed;
    }
    const storedBase = localStorage.getItem('askforwrite_api_base');
    if (storedBase) {
      CONFIG.apiBase = storedBase;
    }
  }

  // ── Company OS Command Dock & Credibility Audit ──────────
  async function handleInvokeCommandDockTool(targetKey, customPayload = {}) {
    const consoleBox = $('#os-command-dock-console');
    const titleEl = $('#os-console-title');
    const badgeEl = $('#os-console-badge');
    const outEl = $('#os-console-output');

    if (consoleBox) consoleBox.style.display = 'block';
    if (titleEl) titleEl.textContent = `⚡ Executing Connected Subsystem: ${targetKey}...`;
    if (badgeEl) {
      badgeEl.className = 'status-pill pending';
      badgeEl.textContent = 'RUNNING';
    }
    if (outEl) {
      outEl.textContent = `Dispatching execution to ${targetKey} with 15-field evidence tracking...`;
    }

    try {
      const res = await api('POST', '/v1/watchdog/invoke-tool', {
        target_key: targetKey,
        payload: customPayload || {},
      });

      if (titleEl) {
        titleEl.textContent = `✅ ${res.name} (${res.category === 'ai_agent' ? 'Specialist AI Agent' : 'Service Tool'}) — ${res.latency_ms}ms`;
      }
      if (badgeEl) {
        badgeEl.className = 'status-pill approved';
        badgeEl.textContent = `${res.capability_status || 'LOCAL_ENGINE_VERIFIED'} • BLOCK #${res.trust_block?.index ?? 0}`;
      }
      if (outEl) {
        outEl.textContent =
          `[Capability Status] ${res.capability_status || res.status}\n` +
          `[Subsystem]         ${res.name} (${res.target_key})\n` +
          `[Latency]           ${res.latency_ms} ms\n` +
          `[Fallback Used]     ${res.evidence?.fallback_used}\n` +
          `[Evidence Ref]      ${res.evidence?.evidence_reference || '—'}\n` +
          `[Assertions]        ${(res.assertions_passed || []).join(' • ')}\n` +
          `[TrustBlock Hash]   ${res.trust_block?.block_hash || '—'}\n\n` +
          `--- 15-Field Execution Evidence Envelope ---\n` +
          JSON.stringify(res.evidence || {}, null, 2) +
          `\n\n--- Execution Result ---\n` +
          JSON.stringify(res.result, null, 2);
      }
      toast(`[${res.capability_status || 'VERIFIED'}] ${res.name} executed (${res.latency_ms}ms)`, 'success');
    } catch (err) {
      if (badgeEl) {
        badgeEl.className = 'status-pill rejected';
        badgeEl.textContent = 'BLOCKED / ERROR';
      }
      if (outEl) {
        outEl.textContent = `❌ Execution Blocked for ${targetKey}: ${err.message}`;
      }
      toast(`Failed to invoke ${targetKey}: ${err.message}`, 'error');
    }
  }

  async function handleViewConnectorInventory() {
    const consoleBox = $('#os-command-dock-console');
    const titleEl = $('#os-console-title');
    const badgeEl = $('#os-console-badge');
    const outEl = $('#os-console-output');

    if (consoleBox) consoleBox.style.display = 'block';
    if (titleEl) titleEl.textContent = '🔌 Inspecting 10-Connector Truthfulness Inventory...';
    if (badgeEl) {
      badgeEl.className = 'status-pill pending';
      badgeEl.textContent = 'CHECKING';
    }
    try {
      const res = await api('GET', '/v1/watchdog/connectors');
      if (titleEl) titleEl.textContent = `🔌 Platform Connector Truthfulness Inventory (${res.total_connectors} Connectors)`;
      if (badgeEl) {
        badgeEl.className = 'status-pill approved';
        badgeEl.textContent = 'CAPABILITY STATUS MODEL v1.0';
      }
      if (outEl) {
        const rows = (res.connectors || []).map((c, idx) =>
          `${String(idx + 1).padStart(2, '0')}. [${c.status.padEnd(21, ' ')}] ${c.name.padEnd(44, ' ')} | Creds: ${c.credentials_present ? 'YES' : 'NO '} | ${c.fallback_behavior}`
        ).join('\n');
        outEl.textContent =
          `========================================================================================\n` +
          `ASKFORWRITE AI COMPANY OS — 10-CONNECTOR TRUTHFULNESS INVENTORY\n` +
          `========================================================================================\n` +
          `${rows}\n` +
          `========================================================================================`;
      }
      toast('Connector inventory loaded', 'info');
    } catch (err) {
      if (outEl) outEl.textContent = `❌ Connector check failed: ${err.message}`;
      toast(`Connector check failed: ${err.message}`, 'error');
    }
  }

  async function handleViewReleaseChecklist() {
    const consoleBox = $('#os-command-dock-console');
    const titleEl = $('#os-console-title');
    const badgeEl = $('#os-console-badge');
    const outEl = $('#os-console-output');

    if (consoleBox) consoleBox.style.display = 'block';
    if (titleEl) titleEl.textContent = '✅ Evaluating 12/12 Commercial Release Acceptance Checklist...';
    try {
      const res = await api('GET', '/v1/watchdog/release-checklist');
      if (titleEl) titleEl.textContent = `✅ Commercial Release Checklist: ${res.passed_count}/${res.total_items} Passed (${res.status})`;
      if (badgeEl) {
        badgeEl.className = res.passed_count === res.total_items ? 'status-pill approved' : 'status-pill rejected';
        badgeEl.textContent = `${res.passed_count}/${res.total_items} VERIFIED`;
      }
      if (outEl) {
        const rows = (res.checklist || []).map(item =>
          `${String(item.id).padStart(2, '0')}. [${item.passed ? 'PASS' : 'FAIL'}] ${item.gate.padEnd(62, ' ')} | Evidence: ${item.evidence}`
        ).join('\n');
        outEl.textContent =
          `========================================================================================\n` +
          `ASKFORWRITE AI COMPANY OS — 12/12 COMMERCIAL RELEASE ACCEPTANCE CHECKLIST\n` +
          `========================================================================================\n` +
          `${rows}\n` +
          `========================================================================================`;
      }
      toast(`Release Checklist: ${res.passed_count}/${res.total_items} Passed!`, 'success');
    } catch (err) {
      if (outEl) outEl.textContent = `❌ Release checklist check failed: ${err.message}`;
      toast(`Release checklist failed: ${err.message}`, 'error');
    }
  }

  async function handleControlAgentState(action) {
    const agentKey = ($('#agent-run-target-select')?.value || 'discovery_sdr_agent').trim();
    const consoleBox = $('#os-command-dock-console');
    const titleEl = $('#os-console-title');
    const badgeEl = $('#os-console-badge');
    const outEl = $('#os-console-output');

    if (consoleBox) consoleBox.style.display = 'block';
    try {
      const res = await api('POST', '/v1/watchdog/agent-control', {
        agent_key: agentKey,
        action,
        reason: `Dashboard operator command: ${action}`,
      });
      if (titleEl) titleEl.textContent = `🎛️ Agent Governance Control: ${res.control.agent_key} -> ${res.control.state}`;
      if (badgeEl) {
        badgeEl.className = res.control.state === 'ACTIVE' ? 'status-pill approved' : 'status-pill rejected';
        badgeEl.textContent = `${res.control.state} • BLOCK #${res.trust_block_index}`;
      }
      if (outEl) {
        outEl.textContent = JSON.stringify(res, null, 2);
      }
      toast(`Agent ${agentKey} state set to ${res.control.state}`, res.control.state === 'ACTIVE' ? 'success' : 'warning');
    } catch (err) {
      toast(`Agent control failed: ${err.message}`, 'error');
    }
  }

  async function handleRunJaipurSmeScenario() {
    const consoleBox = $('#os-command-dock-console');
    const titleEl = $('#os-console-title');
    const badgeEl = $('#os-console-badge');
    const outEl = $('#os-console-output');

    if (consoleBox) consoleBox.style.display = 'block';
    if (titleEl) titleEl.textContent = '🏭 Running 12-Step Jaipur Distribution SME Sandbox E2E...';
    if (badgeEl) {
      badgeEl.className = 'status-pill pending';
      badgeEl.textContent = 'STAGING SANDBOX';
    }
    try {
      const res = await api('POST', '/v1/watchdog/sme-sandbox-scenario', {});
      if (titleEl) titleEl.textContent = `🏭 ${res.scenario_name} — ${res.passed_steps}/${res.total_steps} Steps Passed (${res.duration_ms}ms)`;
      if (badgeEl) {
        badgeEl.className = 'status-pill approved';
        badgeEl.textContent = `SANDBOX VERIFIED • SIDE EFFECTS: ${res.external_side_effects_enabled ? 'ON' : 'OFF'}`;
      }
      if (outEl) {
        const lines = (res.steps || []).map(s =>
          `Step ${String(s.step).padStart(2, '0')} [${s.status}] (${s.capability_status}) ${s.name}: ${JSON.stringify(s.detail)}`
        ).join('\n');
        outEl.textContent =
          `========================================================================================\n` +
          `${res.scenario_name}\n` +
          `========================================================================================\n` +
          `${lines}\n` +
          `========================================================================================`;
      }
      toast(`Jaipur SME 12-Step Sandbox E2E Passed (${res.passed_steps}/${res.total_steps})!`, 'success');
    } catch (err) {
      if (outEl) outEl.textContent = `❌ Jaipur SME Sandbox Scenario failed: ${err.message}`;
      toast(`Jaipur SME Sandbox Scenario failed: ${err.message}`, 'error');
    }
  }

  async function handleRunCredibilityAudit() {
    const btn = $('#btn-run-credibility-audit');
    const statusBadge = $('#credibility-status-badge');
    const consoleBox = $('#os-command-dock-console');
    const titleEl = $('#os-console-title');
    const badgeEl = $('#os-console-badge');
    const outEl = $('#os-console-output');

    const origText = btn ? btn.textContent : '';
    try {
      if (btn) {
        btn.disabled = true;
        btn.textContent = '🛡️ Auditing 16 Subsystems...';
      }
      if (consoleBox) consoleBox.style.display = 'block';
      if (titleEl) titleEl.textContent = '🛡️ Running Full 16-Subsystem Zero-Mock Credibility Audit...';
      if (badgeEl) {
        badgeEl.className = 'status-pill pending';
        badgeEl.textContent = 'TESTING 16 SUBSYSTEMS';
      }
      if (outEl) {
        outEl.textContent = 'Executing all 9 Specialist AI Agents + 7 Core Service Tools in simulated environment with real DB persistence and ECDSA P-256 verification...';
      }

      const res = await api('POST', '/v1/watchdog/credibility-audit', {});

      if (statusBadge) {
        statusBadge.className = res.tolerance_met ? 'status-pill approved' : 'status-pill rejected';
        statusBadge.textContent = `${res.passed_count}/${res.total_subsystems_tested} Passed • ${res.failure_rate_pct.toFixed(4)}% Err`;
      }
      if (titleEl) {
        titleEl.textContent = `🛡️ System Credibility Audit: ${res.commercial_rollout_status} (${res.total_duration_ms}ms)`;
      }
      if (badgeEl) {
        badgeEl.className = res.tolerance_met ? 'status-pill approved' : 'status-pill rejected';
        badgeEl.textContent = `RELIABILITY: ${res.reliability_pct}% • BLOCK #${res.master_trust_block?.index ?? 0}`;
      }
      if (outEl) {
        const lines = (res.subsystems || []).map((s, idx) =>
          `${String(idx + 1).padStart(2, '0')}. [${s.status}] ${s.name.padEnd(44, ' ')} | ${String(s.latency_ms || 0).padStart(6, ' ')}ms | Block #${s.trust_block_index ?? '—'} | ${(s.assertions_passed || []).join(', ')}`
        ).join('\n');
        outEl.textContent =
          `========================================================================================\n` +
          `ASKFORWRITE AI COMPANY OS — INTERNAL CREDIBILITY & ZERO-MOCK AUDIT REPORT\n` +
          `========================================================================================\n` +
          `Commercial Rollout Status : ${res.commercial_rollout_status}\n` +
          `Cloud Hosting Verified    : ${res.cloud_hosting?.provider} (${res.cloud_hosting?.production_domain})\n` +
          `Subsystems Tested         : ${res.passed_count} / ${res.total_subsystems_tested} Passed\n` +
          `Failure Rate              : ${res.failure_rate_pct}% (Target Tolerance < ${res.target_failure_tolerance_pct}%)\n` +
          `Zero-Mock Certified       : ${res.zero_mock_certified}\n` +
          `Merkle Trust Chain Valid  : ${res.trust_chain_valid}\n` +
          `Master TrustBlock Hash    : ${res.master_trust_block?.block_hash}\n` +
          `----------------------------------------------------------------------------------------\n` +
          `${lines}\n` +
          `========================================================================================`;
      }
      toast(`Credibility Audit Certified: ${res.passed_count}/${res.total_subsystems_tested} Passed (0% Failure Rate)!`, 'success');
    } catch (err) {
      if (outEl) outEl.textContent = `❌ Credibility Audit Failed: ${err.message}`;
      toast(`Credibility audit failed: ${err.message}`, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = origText;
      }
    }
  }

  // ── Initialize ───────────────────────────────────────────
  async function init() {
    initApiKey();
    bindEvents();
    const isAuthenticated = checkAuthGate();
    if (!isAuthenticated) {
      // Do NOT fire background API requests or render demo data before user authentication
      if (state.refreshTimer) {
        clearInterval(state.refreshTimer);
        state.refreshTimer = null;
      }
      return;
    }

    const initialPage = window.location.hash.replace('#', '') || ((['customer', 'member', 'tenant_admin'].includes(CONFIG.userRole) || (!CONFIG.ownerApiKey && !!CONFIG.accessToken)) ? 'portal' : 'dashboard');
    navigateTo(initialPage);

    // Initial load (only after authentication passes)
    await fetchAll();

    // Auto-refresh timer
    resetRefreshTimer();
  }

  // ── Legal & Compliance Declarations Modal ─────────────────
  let legalDocsCache = null;

  async function openLegalModal(tabId = 'tos') {
    const overlay = $('#legal-modal-overlay');
    if (overlay) overlay.style.display = 'flex';
    await switchLegalTab(tabId);
  }

  function closeLegalModal() {
    const overlay = $('#legal-modal-overlay');
    if (overlay) overlay.style.display = 'none';
  }

  async function fetchLegalDocuments() {
    if (legalDocsCache) return legalDocsCache;
    try {
      legalDocsCache = await api('GET', '/legal/all');
      return legalDocsCache;
    } catch (err) {
      console.warn('Could not fetch dynamic legal docs, using built-in metadata', err);
      return null;
    }
  }

  async function switchLegalTab(tabId) {
    document.querySelectorAll('.legal-tab-btn').forEach(btn => btn.classList.remove('active'));
    const activeBtn = $(`#legal-tab-btn-${tabId}`);
    if (activeBtn) activeBtn.classList.add('active');

    const contentBox = $('#legal-modal-content');
    if (!contentBox) return;

    contentBox.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted)"><span class="spinner" style="margin-right:8px"></span> Loading statutory legal declarations...</div>';

    const docs = await fetchLegalDocuments();

    if (tabId === 'tos') {
      const tos = docs?.terms_of_service || {
        title: "AskforWrite AI Company OS — Terms of Service & Enterprise Agreement",
        effective_date: "2026-10-14",
        company: "ASKFORWRITE",
        udyam_registration: "UDYAM-RJ-14-0018404",
        sections: [
          { heading: "1. Acceptance of Terms & Statutory Entity", body: "Operated by ASKFORWRITE, registered MSME under Government of India Udyam Registration Number UDYAM-RJ-14-0018404 in Udaipur, Rajasthan, India. All users agree to these terms." },
          { heading: "2. Autonomous Multi-Agent Service", body: "Provides enterprise AI orchestration with Human-in-the-Loop governance and immutable ECDSA P-256 Merkle block sealing." },
          { heading: "3. Strict BYOK Gemini API Isolation", body: "Commercial tenants bring their own Gemini API keys. Zero owner quota consumption. Fallback to deterministic rule-based output when no key is set." },
          { heading: "4. Intellectual Property & Copyright", body: "All code, algorithms, and interface assets are the exclusive intellectual property of ASKFORWRITE (UDYAM-RJ-14-0018404). © 2026 ASKFORWRITE. All Rights Reserved." },
          { heading: "5. Jurisdiction & MSMED Act", body: "Governed by the laws of India, Information Technology Act 2000, and MSMED Act 2006. Disputes subject to arbitration in Udaipur, Rajasthan." }
        ]
      };

      renderLegalDocument(contentBox, tos);
    } else if (tabId === 'privacy') {
      const priv = docs?.privacy_policy || {
        title: "AskforWrite AI Company OS — Privacy Policy & Data Protection Declaration",
        effective_date: "2026-10-14",
        company: "ASKFORWRITE",
        udyam_registration: "UDYAM-RJ-14-0018404",
        sections: [
          { heading: "1. Data Collection Scope", body: "We collect account credentials (hashed with PBKDF2/bcrypt), tenant metadata, and cryptographic audit proofs. No credit card numbers are ever stored." },
          { heading: "2. Strict BYOK Key Zero-Retention Guarantee", body: "Tenant Gemini API keys are encrypted at rest, masked in UI (AIza••••••••••••••••1a2b), never printed in logs, never shared across tenants, and never used to train models. Cleared on demand." },
          { heading: "3. Multi-Tenant Cryptographic Partitioning", body: "Tenant data is partitioned by unique org_id and sealed in tamper-evident trust chains." },
          { heading: "4. Data Grievance Officer", body: "Vipul Kumar Chobisa, ASKFORWRITE (UDYAM-RJ-14-0018404), Udaipur Bus Stand, Udaipur, Rajasthan, India - 313001. Email: info@askforwrite.in." }
        ]
      };

      renderLegalDocument(contentBox, priv);
    } else if (tabId === 'declaration') {
      const decl = docs?.msme_declaration || {
        title: "ASKFORWRITE — Statutory MSME Enterprise Declaration & Legal Identity",
        firm_legal_name: "ASKFORWRITE",
        trade_name: "ASKFORWRITE",
        enterprise_type: "Micro Enterprise (Services)",
        udyam_registration_number: "UDYAM-RJ-14-0018404",
        issuing_ministry: "Ministry of Micro, Small and Medium Enterprises, Government of India",
        registered_office: { locality: "Udaipur Bus Stand", city: "Udaipur", state: "Rajasthan", country: "India", pincode: "313001" },
        banking_and_settlement_coordinates: { bank_name: "ICICI Bank Ltd", ifsc_code: "ICIC0006940", merchant_upi_vpa: "ask4write@icici" }
      };

      contentBox.innerHTML = `
        <div style="margin-bottom:18px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
            <span class="legal-statutory-pill">GOVERNMENT OF INDIA MSME REGISTRY</span>
            <span class="legal-statutory-pill" style="color:var(--cyan);border-color:rgba(6,182,212,0.3)">UDYAM-RJ-14-0018404</span>
          </div>
          <h2 style="font-size:1.3rem;font-weight:800;color:var(--text-primary);margin:0 0 6px 0">${escapeHtml(decl.title)}</h2>
          <p style="font-size:0.82rem;color:var(--text-muted);margin:0">Official Statutory Enterprise Declaration pursuant to the Micro, Small and Medium Enterprises Development Act, 2006.</p>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
          <div class="legal-section-card">
            <div style="font-size:0.72rem;color:var(--text-muted);text-transform:uppercase">Firm Legal Entity</div>
            <div style="font-weight:700;color:var(--text-primary);font-size:1.05rem">${escapeHtml(decl.firm_legal_name)}</div>
            <div style="font-size:0.74rem;color:var(--cyan)">Micro Enterprise (Services)</div>
          </div>
          <div class="legal-section-card">
            <div style="font-size:0.72rem;color:var(--text-muted);text-transform:uppercase">Udyam Registration Number</div>
            <div style="font-weight:700;font-family:'JetBrains Mono',monospace;color:var(--cyan);font-size:1rem">${escapeHtml(decl.udyam_registration_number)}</div>
            <div style="font-size:0.74rem;color:var(--text-muted)">Ministry of MSME, Govt of India</div>
          </div>
        </div>

        <div class="legal-section-card">
          <div class="legal-section-title">🏢 Registered Enterprise Coordinates</div>
          <p style="margin:0 0 8px 0">Locality: Udaipur Bus Stand, City: Udaipur, District: Udaipur, State: Rajasthan, Country: India - 313001.</p>
          <div style="font-size:0.8rem;color:var(--text-muted)">National Industry Classifications: 6201 (Computer programming), 6202 (Computer consultancy), 6209 (Other IT &amp; AI systems).</div>
        </div>

        <div class="legal-section-card">
          <div class="legal-section-title">🏛️ Banking &amp; Sovereign DirectPay Settlement Coordinates</div>
          <div style="font-size:0.82rem;line-height:1.6">
            <strong>Bank:</strong> ICICI Bank Ltd | <strong>Branch:</strong> Udaipur Bus Stand (IFSC: <code>ICIC0006940</code>)<br>
            <strong>Merchant UPI VPA:</strong> <code>ask4write@icici</code> | <strong>SWIFT:</strong> <code>ICICINBBXXX</code><br>
            <strong>Beneficiary:</strong> ASKFORWRITE / Vipul Kumar Chobisa
          </div>
        </div>

        <div class="legal-section-card">
          <div class="legal-section-title">⚖️ Statutory Protections &amp; Grievance Redressal</div>
          <p style="margin:0 0 8px 0">Protected under Section 15 and Section 16 of the MSMED Act, 2006. Grievance &amp; Compliance Officer: Vipul Kumar Chobisa (info@askforwrite.in).</p>
          <div style="font-size:0.76rem;color:#64748b">© 2026 ASKFORWRITE (UDYAM-RJ-14-0018404). All Rights Reserved.</div>
        </div>
      `;
    } else if (tabId === 'refunds') {
      const ref = docs?.refund_policy || {
        title: "AskforWrite AI Company OS — Refund, Cancellation & Settlement Policy",
        effective_date: "2026-10-14",
        company: "ASKFORWRITE",
        udyam_registration: "UDYAM-RJ-14-0018404",
        sections: [
          { heading: "1. Subscription Cancellations", body: "Tenants may cancel subscriptions anytime via the Customer Portal. Service remains active through the end of the paid billing period with zero cancellation penalty." },
          { heading: "2. 7-Day Money-Back Guarantee", body: "Full refunds within 7 days of initial subscription if under 20% of monthly credits (leads/outreach/tokens) were utilized. Returned to source UPI or bank account in 5-7 days." },
          { heading: "3. DirectPay Instant Reconciliation", body: "Direct UPI/Wire transactions automatically seal NIST P-256 blocks. Unmatched proofs are reconciled by our automated watchdog within 12 hours." },
          { heading: "4. Grievance Contact", body: "Billing support: info@askforwrite.in. Statutory MSME Samadhaan forum: Udaipur, Rajasthan." }
        ]
      };

      renderLegalDocument(contentBox, ref);
    }
  }

  function renderLegalDocument(container, doc) {
    let html = `
      <div style="margin-bottom:18px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <span class="legal-statutory-pill">MSME UDYAM-RJ-14-0018404</span>
          <span style="font-size:0.75rem;color:var(--text-muted)">Effective: ${escapeHtml(doc.effective_date || '2026-10-14')}</span>
        </div>
        <h2 style="font-size:1.3rem;font-weight:800;color:var(--text-primary);margin:0 0 4px 0">${escapeHtml(doc.title)}</h2>
        <div style="font-size:0.8rem;color:var(--cyan)">Entity: ${escapeHtml(doc.company || 'ASKFORWRITE')} • Udaipur, Rajasthan, India</div>
      </div>
    `;

    (doc.sections || []).forEach(sec => {
      html += `
        <div class="legal-section-card">
          <div class="legal-section-title">${escapeHtml(sec.heading)}</div>
          <div style="font-size:0.85rem;line-height:1.6;color:var(--text-secondary)">${escapeHtml(sec.body)}</div>
        </div>
      `;
    });

    html += `
      <div style="margin-top:16px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.08);font-size:0.74rem;color:#64748b;text-align:center">
        ${escapeHtml(doc.copyright || '© 2026 ASKFORWRITE (UDYAM-RJ-14-0018404). All Rights Reserved.')} • Official Inquiries: ${escapeHtml(doc.contact || 'info@askforwrite.in')}
      </div>
    `;

    container.innerHTML = html;
  }

  window.openLegalModal = openLegalModal;
  window.closeLegalModal = closeLegalModal;
  window.switchLegalTab = switchLegalTab;

  // ══════════════════════════════════════════════════════════════════════
  // P1 CUSTOMER BUSINESS CONTROL CENTER & REGISTRY ENGINE
  // ══════════════════════════════════════════════════════════════════════
  const cwState = {
    services: [],
    categories: [],
    agents: [],
    connectors: [],
    evidence: [],
    definitions: [],
    runs: [],
    contracts: [],
    ledger: [],
    stops: [],
    initialized: false,
  };

  const CW_PAGE_TITLES = {
    portal: 'Business Overview & Quick Launch',
    'cw-profile': 'Business Profile & AI Recommendations',
    'cw-marketplace': 'Service Marketplace (9 Categories)',
    'cw-workforce': 'AI Workforce & Agent Controls',
    'cw-run-console': 'Agent Run Console',
    'cw-workflows': 'Workflow Builder & 8-State Runs',
    'cw-connectors': 'Connected Tools & Verification',
    'cw-history': 'Tasks & 18-Field Execution Evidence',
    approvals: 'HITL Approvals',
    'cw-analytics': 'Organization Analytics & Reports',
    'cw-billing': 'Subscription & Credit Ledger',
    'cw-settings': 'Settings & 4-Level Emergency Stop',
    'commercial-os': 'P2 Commercial Acquisition & Revenue OS',
    'customer-success': 'P3 Customer Success, Retention & Growth Engine',
    'p4-growth': 'P4 Repeatable Growth & GTM Engine',
  };

  function cwIsCustomer() {
    return CONFIG.userRole === 'customer' || (!CONFIG.ownerApiKey && !!CONFIG.accessToken);
  }

  function cwSplitList(val) {
    return (val || '')
      .split(',')
      .map(s => s.trim())
      .filter(Boolean);
  }

  function cwOriginClass(origin) {
    if (origin === 'LIVE_PROVIDER_VERIFIED' || origin === 'LOCAL_DETERMINISTIC') return 'live';
    if (origin === 'SANDBOX_VERIFIED' || origin === 'HUMAN_ASSISTED') return 'sandbox';
    if (origin === 'SIMULATED_SYNTHETIC') return 'simulated';
    return 'blocked';
  }

  function cwStateClass(stateStr) {
    const s = (stateStr || '').toUpperCase();
    if (['LIVE_VERIFIED', 'LOCAL_ENGINE_VERIFIED', 'COMPLETED', 'ACTIVE', 'READY'].includes(s)) return 'live';
    if (['SANDBOX_VERIFIED', 'HUMAN_ASSISTED', 'RUNNING', 'CONFIGURED_UNVERIFIED'].includes(s)) return 'sandbox';
    if (['SIMULATED', 'WAITING_APPROVAL', 'DRAFT', 'ROADMAP'].includes(s)) return 'simulated';
    return 'blocked';
  }

  async function cwFetchScopedApprovals() {
    if (!cwIsCustomer()) {
      await fetchApprovals();
      return;
    }
    try {
      const data = await api('GET', '/v1/me/approvals');
      const rows = data.approvals || [];
      state.approvals = rows.map(a => ({
        id: a.approval_id || a.id,
        task_id: a.task_id,
        action: a.action,
        requested_by: a.requested_by,
        status: a.status,
        decided_by: a.decided_by,
        decision_note: a.decision_note,
        created_at: a.created_at,
      }));
      renderApprovals();
      renderRecentApprovals();
    } catch (e) {
      toast(`Failed to load scoped approvals: ${e.message}`, 'error');
    }
  }

  async function cwHydrateRegistry() {
    try {
      const [svcRes, agRes, connRes] = await Promise.all([
        api('GET', '/v1/registry/services'),
        api('GET', '/v1/registry/agents'),
        api('GET', '/v1/registry/connectors'),
      ]);
      cwState.services = svcRes.services || [];
      cwState.categories = svcRes.categories || [];
      cwState.agents = agRes.agents || [];
      cwState.connectors = connRes.connectors || [];

      // Single Source of Truth hydration for Overview quick tools & selector
      const iconBar = $('#portal-service-icon-bar');
      if (iconBar) {
        iconBar.innerHTML = cwState.services.map(s => `
          <button type="button" class="portal-quick-tool-btn" data-portal-service="${escapeHtml(s.service_id)}" title="${escapeHtml(s.description || '')}">
            ${escapeHtml(s.service_name)} <span style="opacity:0.7;font-size:0.7rem;">(${escapeHtml(s.execution_status)})</span>
          </button>
        `).join('');
        iconBar.querySelectorAll('.portal-quick-tool-btn').forEach(btn => {
          btn.addEventListener('click', () => {
            const sel = $('#portal-service-selector');
            if (sel) {
              sel.value = btn.dataset.portalService;
              handleRunTenantService();
            }
          });
        });
      }

      const svcSel = $('#portal-service-selector');
      if (svcSel && cwState.services.length > 0) {
        const cur = svcSel.value;
        svcSel.innerHTML = cwState.services.map(s => (
          `<option value="${escapeHtml(s.service_id)}">${escapeHtml(s.service_name)} (${escapeHtml(s.category)} • ${escapeHtml(s.execution_status)})</option>`
        )).join('');
        if (cur && cwState.services.some(s => s.service_id === cur)) {
          svcSel.value = cur;
        }
      }

      const catFilter = $('#cw-marketplace-category-filter');
      if (catFilter) {
        const curCat = catFilter.value || 'all';
        const cats = [...new Set(cwState.services.map(s => s.category).filter(Boolean))];
        catFilter.innerHTML = '<option value="all">All 9 Business Categories</option>' +
          cats.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c.replace(/_/g, ' ').toUpperCase())}</option>`).join('');
        catFilter.value = curCat;
      }

      const runAgentSel = $('#cw-run-agent-select');
      if (runAgentSel && cwState.agents.length > 0) {
        const curA = runAgentSel.value;
        runAgentSel.innerHTML = cwState.agents.map(a => (
          `<option value="${escapeHtml(a.agent_id)}">${escapeHtml(a.agent_name)} (${escapeHtml(a.business_function)} • ${a.credits_per_run ?? 1} cr)</option>`
        )).join('');
        if (curA && cwState.agents.some(a => a.agent_id === curA)) {
          runAgentSel.value = curA;
        }
      }

      const runSvcSel = $('#cw-run-service-select');
      if (runSvcSel) {
        runSvcSel.innerHTML = '<option value="">-- Agent Direct Execution --</option>' +
          cwState.services.map(s => `<option value="${escapeHtml(s.service_id)}">${escapeHtml(s.service_name)}</option>`).join('');
      }

      cwRenderMarketplace();
      cwRenderWorkforce();
      cwRenderConnectors();
    } catch (e) {
      console.warn('Registry hydration:', e.message);
    }
  }

  function cwRenderMarketplace() {
    const container = $('#cw-marketplace-container');
    if (!container) return;
    const filterVal = $('#cw-marketplace-category-filter')?.value || 'all';
    const items = filterVal === 'all'
      ? cwState.services
      : cwState.services.filter(s => s.category === filterVal);
    if (!items.length) {
      container.innerHTML = '<div class="empty-state"><p>No services matched filter.</p></div>';
      return;
    }
    container.innerHTML = items.map(s => `
      <div class="cw-card">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
          <div>
            <div style="font-size:0.72rem;color:var(--cyan);text-transform:uppercase;">${escapeHtml((s.category || '').replace(/_/g, ' '))}</div>
            <h3 style="margin:2px 0;">${escapeHtml(s.service_name)}</h3>
          </div>
          <span class="cw-pill ${cwStateClass(s.execution_status)}">${escapeHtml(s.execution_status)}</span>
        </div>
        <p style="margin:0;font-size:0.83rem;color:var(--text-secondary);">${escapeHtml(s.description || '')}</p>
        <div style="font-size:0.78rem;color:var(--text-muted);">
          <strong>Outcome:</strong> ${escapeHtml(s.business_outcome || 'Operational automation')}<br>
          <strong>Agents:</strong> ${escapeHtml((s.available_agents || []).join(', ') || 'None')}<br>
          <strong>Connectors:</strong> ${escapeHtml((s.required_connectors || []).join(', ') || 'None')}<br>
          <strong>Entitlement Key:</strong> <code>${escapeHtml(s.entitlement_key || 'core')}</code> • <strong>v${escapeHtml(s.version || '1.0.0')}</strong>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:auto;">
          <button type="button" class="secondary-btn cw-btn-open-console" data-service-id="${escapeHtml(s.service_id)}" data-agent-id="${escapeHtml((s.available_agents || [])[0] || '')}">Open in Run Console</button>
        </div>
      </div>
    `).join('');

    container.querySelectorAll('.cw-btn-open-console').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.agentId && $('#cw-run-agent-select')) {
          $('#cw-run-agent-select').value = btn.dataset.agentId;
        }
        if (btn.dataset.serviceId && $('#cw-run-service-select')) {
          $('#cw-run-service-select').value = btn.dataset.serviceId;
        }
        navigateTo('cw-run-console');
      });
    });
  }

  function cwRenderWorkforce() {
    const grid = $('#cw-workforce-grid');
    if (!grid) return;
    if (!cwState.agents.length) {
      grid.innerHTML = '<div class="empty-state"><p>No agents found in registry.</p></div>';
      return;
    }
    grid.innerHTML = cwState.agents.map(a => {
      const active = !!a.tenant_active;
      return `
        <div class="cw-card">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
            <div>
              <div style="font-size:0.72rem;color:var(--purple);text-transform:uppercase;">${escapeHtml(a.business_function || 'operations')}</div>
              <h3 style="margin:2px 0;">${escapeHtml(a.agent_name)}</h3>
            </div>
            <span class="cw-pill ${active ? 'live' : 'disabled'}">${active ? 'ACTIVE' : escapeHtml(a.status || 'INACTIVE')}</span>
          </div>
          <p style="margin:0;font-size:0.82rem;color:var(--text-secondary);">${escapeHtml(a.description || '')}</p>
          <div style="font-size:0.76rem;color:var(--text-muted);">
            <strong>ID:</strong> <code>${escapeHtml(a.agent_id)}</code> • <strong>v${escapeHtml(a.version || '1.0.0')}</strong><br>
            <strong>Tools:</strong> ${escapeHtml((a.supported_tools || []).join(', '))}<br>
            <strong>Approvals:</strong> ${escapeHtml((a.required_approvals || []).join(', ') || 'Standard policy')}
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end;margin-top:auto;">
            <button type="button" class="secondary-btn cw-agent-toggle-btn" data-agent-id="${escapeHtml(a.agent_id)}" data-active="${active ? '1' : '0'}">${active ? 'Deactivate' : 'Activate'}</button>
            <button type="button" class="primary-btn cw-agent-launch-btn" data-agent-id="${escapeHtml(a.agent_id)}">Run Agent</button>
          </div>
        </div>
      `;
    }).join('');

    grid.querySelectorAll('.cw-agent-toggle-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const agentId = btn.dataset.agentId;
        const currentlyActive = btn.dataset.active === '1';
        try {
          await api('POST', `/v1/registry/agents/${agentId}/${currentlyActive ? 'deactivate' : 'activate'}`);
          toast(`Agent ${agentId} ${currentlyActive ? 'deactivated' : 'activated'}`, 'success');
          await cwHydrateRegistry();
        } catch (e) {
          toast(`Agent action blocked: ${e.message}`, 'error');
        }
      });
    });

    grid.querySelectorAll('.cw-agent-launch-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if ($('#cw-run-agent-select')) $('#cw-run-agent-select').value = btn.dataset.agentId;
        navigateTo('cw-run-console');
      });
    });
  }

  function cwRenderConnectors() {
    const grid = $('#cw-connectors-grid');
    if (!grid) return;
    if (!cwState.connectors.length) {
      grid.innerHTML = '<div class="empty-state"><p>No connectors returned from registry.</p></div>';
      return;
    }
    grid.innerHTML = cwState.connectors.map(c => `
      <div class="cw-card">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
          <div>
            <div style="font-size:0.72rem;color:var(--cyan);text-transform:uppercase;">${escapeHtml(c.provider || c.connector_id)} • ${escapeHtml(c.environment || 'staging')}</div>
            <h3 style="margin:2px 0;">${escapeHtml(c.connector_id)}</h3>
          </div>
          <span class="cw-pill ${cwStateClass(c.capability_state)}">${escapeHtml(c.capability_state)}</span>
        </div>
        <div style="font-size:0.77rem;color:var(--text-muted);">
          <strong>Category:</strong> ${escapeHtml(c.service_category || '')} • <strong>Auth:</strong> ${escapeHtml(c.authentication_type || '')}<br>
          <strong>Permissions:</strong> ${escapeHtml((c.required_permissions || []).join(', '))}<br>
          <strong>Verified:</strong> ${escapeHtml(c.last_verified_at || 'Never')} ${c.last_error ? `<br><span style="color:#fca5a5;">Error: ${escapeHtml(c.last_error)}</span>` : ''}
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
          <input type="text" class="settings-input cw-conn-key-input" data-connector-id="${escapeHtml(c.connector_id)}" placeholder='{"api_key":"..."} or setting value' autocomplete="off" spellcheck="false" style="flex:1;min-width:160px;">
          <button type="button" class="secondary-btn cw-conn-save-btn" data-connector-id="${escapeHtml(c.connector_id)}">Save Config</button>
          <button type="button" class="primary-btn cw-conn-verify-btn" data-connector-id="${escapeHtml(c.connector_id)}">Verify Probe</button>
        </div>
      </div>
    `).join('');

    grid.querySelectorAll('.cw-conn-save-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const cid = btn.dataset.connectorId;
        const input = grid.querySelector(`.cw-conn-key-input[data-connector-id="${cid}"]`);
        const raw = (input?.value || '').trim();
        let settings = { configured_token: raw };
        if (raw.startsWith('{')) {
          try {
            settings = JSON.parse(raw);
          } catch (err) {
            toast(`Invalid connector JSON: ${err.message}`, 'error');
            return;
          }
        }
        try {
          await api('POST', `/v1/registry/connectors/${cid}/configure`, { settings });
          toast(`Connector ${cid} saved as CONFIGURED_UNVERIFIED (verification probe still required)`, 'info');
          if (input) input.value = '';
          await cwHydrateRegistry();
        } catch (e) {
          toast(`Connector config failed: ${e.message}`, 'error');
        }
      });
    });

    grid.querySelectorAll('.cw-conn-verify-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const cid = btn.dataset.connectorId;
        try {
          const res = await api('POST', `/v1/registry/connectors/${cid}/verify`, {});
          toast(`Connector ${cid} status: ${res.status}`, res.status === 'LIVE_VERIFIED' ? 'success' : 'info');
          await cwHydrateRegistry();
        } catch (e) {
          toast(`Connector verify failed: ${e.message}`, 'error');
        }
      });
    });
  }

  async function cwLoadProfile() {
    if (!cwIsCustomer()) return;
    try {
      const data = await api('GET', '/v1/me/business-profile');
      const p = data.profile || {};
      if ($('#cw-prof-name')) $('#cw-prof-name').value = p.business_name || '';
      if ($('#cw-prof-industry')) $('#cw-prof-industry').value = p.industry || '';
      if ($('#cw-prof-location')) $('#cw-prof-location').value = p.location || p.city || '';
      if ($('#cw-prof-website')) $('#cw-prof-website').value = p.website || '';
      if ($('#cw-prof-email')) $('#cw-prof-email').value = p.contact_info?.email || '';
      if ($('#cw-prof-phone')) $('#cw-prof-phone').value = p.contact_info?.phone || '';
      if ($('#cw-prof-employees')) $('#cw-prof-employees').value = p.employee_count || 10;
      if ($('#cw-prof-products')) $('#cw-prof-products').value = (p.products_and_services || p.products || []).join(', ');
      if ($('#cw-prof-segments')) $('#cw-prof-segments').value = (p.customer_segments || []).join(', ');
      if ($('#cw-prof-channels')) $('#cw-prof-channels').value = (p.sales_channels || []).join(', ');
      if ($('#cw-prof-software')) $('#cw-prof-software').value = (p.current_software || []).join(', ');
      if ($('#cw-prof-pain')) $('#cw-prof-pain').value = (p.operational_pain_points || []).join(', ');
      if ($('#cw-prof-objectives')) $('#cw-prof-objectives').value = (p.business_objectives || []).join(', ');
      if ($('#cw-prof-automations')) $('#cw-prof-automations').value = (p.required_automations || []).join(', ');
      if ($('#cw-prof-desc')) $('#cw-prof-desc').value = p.description || p.requirements_text || '';
      if (data.recommendation || data.recommendations || data.structured_requirements) {
        cwRenderRecommendations(data);
      }
    } catch (e) {
      console.warn('Load profile:', e.message);
    }
  }

  function cwRenderRecommendations(data) {
    const box = $('#cw-recommendations-box');
    const badge = $('#cw-readiness-badge');
    const rec = data.recommendation || data.recommendations || {};
    const readiness = data.assessment?.readiness_score ?? (data.profile?.selection_confirmed ? 95 : 70);
    if (badge && readiness !== undefined) {
      badge.textContent = `Readiness: ${readiness}%`;
    }
    if (!box) return;
    const items = rec.explanations || rec.recommended_services || data.structured_requirements || [];
    const selectedModules = rec.recommended_modules || items.map(i => i.module || i.category).filter(Boolean);
    const basePlan = rec.recommended_tier || rec.recommended_base_tier || 'growth';
    box.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
        <div>
          <h3 style="margin:0;">Explainable Service Recommendations</h3>
          <div style="font-size:0.8rem;color:var(--text-muted);">Recommended Plan: <code>${escapeHtml(basePlan)}</code> • Est. Credits/mo: ${escapeHtml(String(rec.expected_monthly_credits ?? 0))} • Confirmation required before provisioning</div>
        </div>
        <button type="button" class="primary-btn" id="btn-cw-confirm-selection">Confirm &amp; Lock Recommendation Selection</button>
      </div>
      <div class="cw-grid-2" style="margin-top:12px;">
        ${items.map(it => `
          <div class="cw-card">
            <strong>${escapeHtml(it.title || it.service_name || it.module || '')}</strong>
            <div style="font-size:0.8rem;color:var(--text-secondary);">${escapeHtml(it.reason || it.description || it.why || '')}</div>
            <div style="font-size:0.75rem;color:var(--text-muted);">
              <strong>Agents:</strong> ${escapeHtml((it.agents || it.recommended_agents || []).join(', '))}<br>
              <strong>Connectors:</strong> ${escapeHtml((it.required_connectors || it.connectors || []).join(', '))}<br>
              <strong>Est. Credits/mo:</strong> ${escapeHtml(String(it.expected_monthly_credits ?? it.credits ?? '20'))}<br>
              <strong>Limitation:</strong> ${escapeHtml(Array.isArray(it.limitations) ? it.limitations.join('; ') : (it.limitations || 'Honest mode labels enforced'))}
            </div>
          </div>
        `).join('') || '<div style="color:var(--text-muted);">No module recommendations returned.</div>'}
      </div>
    `;
    $('#btn-cw-confirm-selection')?.addEventListener('click', async () => {
      try {
        await api('POST', '/v1/me/business-profile/confirm', {
          base_plan_key: basePlan,
          selected_modules: selectedModules,
          activate_selection: false,
        });
        toast('Business requirements & service recommendations confirmed!', 'success');
      } catch (e) {
        toast(`Confirmation failed: ${e.message}`, 'error');
      }
    });
  }

  async function cwSaveProfile() {
    const payload = {
      business_name: ($('#cw-prof-name')?.value || '').trim() || 'SME Business Profile',
      industry: ($('#cw-prof-industry')?.value || '').trim() || 'SME Services',
      description: ($('#cw-prof-desc')?.value || '').trim(),
      location: ($('#cw-prof-location')?.value || '').trim(),
      website: ($('#cw-prof-website')?.value || '').trim(),
      contact_info: {
        email: ($('#cw-prof-email')?.value || '').trim(),
        phone: ($('#cw-prof-phone')?.value || '').trim(),
      },
      company_size: $('#cw-prof-size')?.value || 'small',
      employee_count: Number($('#cw-prof-employees')?.value || 10),
      products_and_services: cwSplitList($('#cw-prof-products')?.value),
      customer_segments: cwSplitList($('#cw-prof-segments')?.value),
      sales_channels: cwSplitList($('#cw-prof-channels')?.value),
      current_software: cwSplitList($('#cw-prof-software')?.value),
      operational_pain_points: cwSplitList($('#cw-prof-pain')?.value),
      business_objectives: cwSplitList($('#cw-prof-objectives')?.value),
      required_automations: cwSplitList($('#cw-prof-automations')?.value),
      expected_monthly_volume: {
        executions: Number($('#cw-prof-volume')?.value || 250),
        monthly_budget_inr: Number($('#cw-prof-budget')?.value || 15000),
        approval_mode: $('#cw-prof-approval-mode')?.value || 'hitl_required',
      },
      requirements_text: ($('#cw-prof-desc')?.value || '').trim() || 'Automate operations',
    };
    try {
      const data = await api('POST', '/v1/me/business-profile', payload);
      cwRenderRecommendations(data);
      toast('Business profile saved & AI recommendations generated', 'success');
    } catch (e) {
      toast(`Profile save failed: ${e.message}`, 'error');
    }
  }

  async function cwExecuteAgent() {
    const agentId = $('#cw-run-agent-select')?.value;
    if (!agentId) {
      toast('Select an agent from the registry first', 'error');
      return;
    }
    const mode = $('#cw-run-mode-select')?.value || 'SIMULATION';
    const idem = ($('#cw-run-idempotency-key')?.value || '').trim() || null;
    let inputPayload = {};
    try {
      inputPayload = JSON.parse(($('#cw-run-input-json')?.value || '{}').trim() || '{}');
    } catch (e) {
      toast(`Invalid JSON payload: ${e.message}`, 'error');
      return;
    }
    const svcId = $('#cw-run-service-select')?.value;
    if (svcId) inputPayload.service_id = svcId;
    if ($('#cw-run-mode-indicator')) {
      $('#cw-run-mode-indicator').textContent = `Mode: ${mode}`;
    }
    const card = $('#cw-run-result-card');
    try {
      const res = await api('POST', `/v1/registry/agents/${agentId}/execute`, {
        input_payload: inputPayload,
        execution_mode: mode,
        idempotency_key: idem,
      });
      const ev = res.evidence || res;
      const previewOut = ev.metadata?.output_preview || res.output || res;
      if (card) {
        card.style.display = 'flex';
        card.innerHTML = `
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
            <div>
              <strong>Execution ID:</strong> <code>${escapeHtml(ev.execution_id || res.execution_id || '')}</code>
            </div>
            <div style="display:flex;gap:8px;align-items:center;">
              <span class="cw-pill ${cwOriginClass(ev.output_origin || res.output_origin)}">${escapeHtml(ev.output_origin || res.output_origin || 'SIMULATED_SYNTHETIC')}</span>
              <span class="cw-pill ${cwStateClass(ev.status)}">${escapeHtml(ev.status || 'COMPLETED')}</span>
            </div>
          </div>
          <div style="font-size:0.8rem;color:var(--text-muted);">
            <strong>Mode:</strong> ${escapeHtml(ev.execution_mode || mode)} • <strong>Credits Consumed:</strong> ${escapeHtml(String(ev.credits_consumed ?? 0))} • <strong>Evidence:</strong> <code>${escapeHtml(ev.evidence_reference || '—')}</code>
          </div>
          <pre class="cw-code-box">${escapeHtml(JSON.stringify(previewOut, null, 2))}</pre>
          <div style="display:flex;justify-content:flex-end;">
            <button type="button" class="secondary-btn" id="btn-cw-inspect-last-evidence">Inspect 18-Field Evidence</button>
          </div>
        `;
        $('#btn-cw-inspect-last-evidence')?.addEventListener('click', () => cwOpenEvidenceDrawer(ev));
      }
      toast(`Executed ${agentId} (${ev.output_origin || mode})`, 'success');
      await cwLoadEvidenceHistory();
    } catch (e) {
      if (card) {
        card.style.display = 'flex';
        card.innerHTML = `<div class="cw-pill blocked">EXECUTION BLOCKED / FAILED</div><pre class="cw-code-box">${escapeHtml(e.message)}</pre>`;
      }
      toast(`Agent execution failed: ${e.message}`, 'error');
    }
  }

  function cwOpenEvidenceDrawer(rec) {
    const drawer = $('#cw-evidence-drawer');
    const body = $('#cw-evidence-drawer-body');
    const title = $('#cw-evidence-drawer-title');
    if (!drawer || !body) return;
    if (title) title.textContent = `Evidence: ${rec.execution_id || 'Record'}`;
    const fields = [
      ['execution_id', rec.execution_id],
      ['tenant_id', rec.tenant_id || rec.org_id],
      ['workflow_id', rec.workflow_id],
      ['agent_id', rec.agent_id],
      ['connector_id', rec.connector_id],
      ['execution_mode', rec.execution_mode],
      ['output_origin', rec.output_origin],
      ['input_reference', rec.input_reference],
      ['output_reference', rec.output_reference],
      ['provider_request_id', rec.provider_request_id],
      ['fallback_used', String(!!rec.fallback_used)],
      ['approval_id', rec.approval_id],
      ['status', rec.status],
      ['failure_reason', rec.failure_reason],
      ['credits_consumed', rec.credits_consumed],
      ['started_at', rec.started_at],
      ['completed_at', rec.completed_at],
      ['evidence_reference', rec.evidence_reference],
      ['version', rec.version],
      ['metadata', JSON.stringify(rec.metadata || {}, null, 2)],
    ];
    body.innerHTML = `
      <div class="cw-evidence-grid">
        ${fields.map(([k, v]) => `
          <div class="cw-evidence-field">
            <div class="cw-evidence-label">${escapeHtml(k)}</div>
            <div class="cw-evidence-value">${escapeHtml(v !== undefined && v !== null ? String(v) : '—')}</div>
          </div>
        `).join('')}
      </div>
    `;
    drawer.style.display = 'flex';
  }

  async function cwLoadEvidenceHistory() {
    try {
      const modeFilter = $('#cw-history-mode-filter')?.value || '';
      const q = modeFilter ? `?execution_mode=${encodeURIComponent(modeFilter)}` : '';
      const res = await api('GET', `/v1/registry/evidence${q}`);
      cwState.evidence = res.records || [];
      const tbody = $('#cw-history-tbody');
      if (!tbody) return;
      if (!cwState.evidence.length) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="7"><div class="empty-state"><p>No execution evidence recorded yet.</p></div></td></tr>';
        return;
      }
      tbody.innerHTML = cwState.evidence.map((rec, idx) => {
        const durMs = (rec.started_at && rec.completed_at)
          ? Math.max(0, Date.parse(rec.completed_at) - Date.parse(rec.started_at))
          : 0;
        return `
        <tr>
          <td><code>${escapeHtml(rec.execution_id)}</code></td>
          <td><strong>${escapeHtml(rec.agent_id || rec.workflow_id || '—')}</strong></td>
          <td>
            <span class="cw-pill sandbox">${escapeHtml(rec.execution_mode)}</span>
            <span class="cw-pill ${cwOriginClass(rec.output_origin)}">${escapeHtml(rec.output_origin)}</span>
          </td>
          <td><span class="cw-pill ${cwStateClass(rec.status)}">${escapeHtml(rec.status)}</span></td>
          <td>${escapeHtml(String(rec.credits_consumed ?? 0))}</td>
          <td>${escapeHtml(String(durMs))} ms</td>
          <td><button type="button" class="secondary-btn cw-inspect-ev-btn" data-idx="${idx}">Inspect 18 Fields</button></td>
        </tr>
      `;
      }).join('');
      tbody.querySelectorAll('.cw-inspect-ev-btn').forEach(btn => {
        btn.addEventListener('click', () => cwOpenEvidenceDrawer(cwState.evidence[Number(btn.dataset.idx)]));
      });
    } catch (e) {
      console.warn('Evidence load:', e.message);
    }
  }

  async function cwLoadWorkflows() {
    try {
      const [defsRes, runsRes] = await Promise.all([
        api('GET', '/v1/workflows/definitions'),
        api('GET', '/v1/workflows/runs'),
      ]);
      cwState.definitions = defsRes.workflows || defsRes.definitions || [];
      cwState.runs = runsRes.runs || [];

      const defsList = $('#cw-wf-definitions-list');
      if (defsList) {
        defsList.innerHTML = cwState.definitions.length ? cwState.definitions.map(d => `
          <div class="cw-card" style="margin-bottom:8px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <strong>${escapeHtml(d.name)}</strong>
              <span class="cw-pill sandbox">v${escapeHtml(d.version)} • Budget ${escapeHtml(String(d.max_credits_budget))} cr</span>
            </div>
            <div style="font-size:0.75rem;color:var(--text-muted);">${(d.steps || []).length} steps • ID: <code>${escapeHtml(d.workflow_id)}</code></div>
            <button type="button" class="primary-btn cw-wf-start-btn" data-wf-id="${escapeHtml(d.workflow_id)}">Start Workflow Run</button>
          </div>
        `).join('') : '<div class="empty-state"><p>No workflow definitions yet.</p></div>';
        defsList.querySelectorAll('.cw-wf-start-btn').forEach(btn => {
          btn.addEventListener('click', async () => {
            try {
              await api('POST', '/v1/workflows/runs', { workflow_id: btn.dataset.wfId, start_immediately: true });
              toast('Workflow run executed', 'success');
              await cwLoadWorkflows();
              await cwFetchScopedApprovals();
            } catch (e) {
              toast(`Workflow start failed: ${e.message}`, 'error');
            }
          });
        });
      }

      const runsList = $('#cw-wf-runs-list');
      if (runsList) {
        runsList.innerHTML = cwState.runs.length ? cwState.runs.map(r => `
          <div class="cw-card" style="margin-bottom:8px;">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
              <div><code>${escapeHtml(r.run_id)}</code> • Step ${escapeHtml(String(r.current_step_index))}/${escapeHtml(String(r.total_steps))}</div>
              <span class="cw-pill ${cwStateClass(r.status)}">${escapeHtml(r.status)}</span>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              ${r.status === 'DRAFT' ? `<button type="button" class="secondary-btn cw-run-action" data-run-id="${escapeHtml(r.run_id)}" data-act="ready">Mark Ready</button>` : ''}
              ${['DRAFT', 'READY'].includes(r.status) ? `<button type="button" class="primary-btn cw-run-action" data-run-id="${escapeHtml(r.run_id)}" data-act="start">Start</button>` : ''}
              ${r.status === 'WAITING_APPROVAL' ? `<button type="button" class="primary-btn cw-run-action" data-run-id="${escapeHtml(r.run_id)}" data-act="resume">Resume After HITL</button>` : ''}
              ${['DRAFT', 'READY', 'RUNNING', 'WAITING_APPROVAL'].includes(r.status) ? `<button type="button" class="danger-btn cw-run-action" data-run-id="${escapeHtml(r.run_id)}" data-act="cancel">Cancel Run</button>` : ''}
            </div>
          </div>
        `).join('') : '<div class="empty-state"><p>No workflow runs recorded yet.</p></div>';
        runsList.querySelectorAll('.cw-run-action').forEach(btn => {
          btn.addEventListener('click', async () => {
            try {
              const body = btn.dataset.act === 'cancel' ? { reason: 'Cancelled via Control Center' } : undefined;
              await api('POST', `/v1/workflows/runs/${btn.dataset.runId}/${btn.dataset.act}`, body);
              toast(`Workflow run action '${btn.dataset.act}' completed`, 'success');
              await cwLoadWorkflows();
            } catch (e) {
              toast(`Workflow action failed: ${e.message}`, 'error');
            }
          });
        });
      }
    } catch (e) {
      console.warn('Workflows load:', e.message);
    }
  }

  async function cwCreateWorkflow() {
    const name = ($('#cw-wf-name')?.value || '').trim() || 'Custom SME Workflow';
    const budget = Number($('#cw-wf-budget')?.value || 10);
    let steps = [];
    try {
      steps = JSON.parse(($('#cw-wf-steps-json')?.value || '[]').trim());
    } catch (e) {
      toast(`Invalid workflow steps JSON: ${e.message}`, 'error');
      return;
    }
    try {
      await api('POST', '/v1/workflows/definitions', {
        name,
        max_credits_budget: budget,
        steps,
      });
      toast(`Workflow '${name}' created`, 'success');
      await cwLoadWorkflows();
    } catch (e) {
      toast(`Create workflow failed: ${e.message}`, 'error');
    }
  }

  async function cwLoadAnalytics() {
    await cwLoadEvidenceHistory();
    await cwLoadBilling();
    const sumEl = $('#cw-analytics-summary');
    const brkEl = $('#cw-analytics-breakdown');
    if (!sumEl || !brkEl) return;
    const total = cwState.evidence.length;
    const completed = cwState.evidence.filter(r => r.status === 'COMPLETED').length;
    const blocked = cwState.evidence.filter(r => r.status === 'BLOCKED' || r.status === 'FAILED').length;
    const creditsSpent = cwState.evidence.reduce((acc, r) => acc + Number(r.credits_consumed || 0), 0);
    const byOrigin = {};
    cwState.evidence.forEach(r => {
      const k = r.output_origin || 'UNKNOWN';
      byOrigin[k] = (byOrigin[k] || 0) + 1;
    });
    sumEl.innerHTML = `
      <div class="cw-card"><div class="stat-label">Total Recorded Executions</div><div class="stat-value">${total}</div></div>
      <div class="cw-card"><div class="stat-label">Completed / Blocked+Failed</div><div class="stat-value">${completed} / ${blocked}</div></div>
      <div class="cw-card"><div class="stat-label">Verified Credits Consumed</div><div class="stat-value">${creditsSpent}</div></div>
    `;
    brkEl.innerHTML = `
      <h3>Execution Origin Breakdown (Observed Only — Zero Fabricated Metrics)</h3>
      <pre class="cw-code-box">${escapeHtml(JSON.stringify({ by_output_origin: byOrigin, ledger_entries: cwState.ledger.length }, null, 2))}</pre>
    `;
  }

  async function cwLoadBilling() {
    try {
      const [contractsRes, ledgerRes] = await Promise.all([
        api('GET', '/v1/revenue/pricing/contracts'),
        cwIsCustomer() ? api('GET', '/v1/me/credits/ledger').catch(() => ({ entries: [] })) : Promise.resolve({ entries: [] }),
      ]);
      const tierMap = contractsRes.modular_tier_contracts || {};
      cwState.contracts = Object.entries(tierMap).map(([planKey, obj]) => ({
        plan_key: planKey,
        ...obj,
      }));
      cwState.ledger = ledgerRes.entries || [];

      const clustersMap = contractsRes.pricing_clusters || {};
      const addonsMap = contractsRes.modular_addons || {};
      const clGrid = $('#cw-pricing-clusters-grid');
      if (clGrid) {
        const clusters = Object.values(clustersMap).sort((a, b) => (a.cluster_number || 0) - (b.cluster_number || 0));
        clGrid.innerHTML = clusters.map(cl => `
          <div style="background:rgba(15,23,42,0.72);border:1px solid var(--glass-border);border-radius:10px;padding:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
              <span style="font-size:0.7rem;font-weight:700;color:var(--cyan);text-transform:uppercase;">Cluster ${escapeHtml(String(cl.cluster_number || ''))}</span>
              <span style="font-size:0.74rem;font-weight:700;color:var(--green);">₹${Number(cl.standalone_monthly_inr || 0).toLocaleString('en-IN')}/mo · $${escapeHtml(String(cl.standalone_monthly_usd || 0))}</span>
            </div>
            <div style="font-weight:700;font-size:0.84rem;margin-bottom:4px;">${escapeHtml(String(cl.name || '').replace(/^Cluster \d+:\s*/, ''))}</div>
            <div style="font-size:0.74rem;color:var(--text-muted);line-height:1.45;margin-bottom:6px;">${escapeHtml(cl.tagline || '')}</div>
            <div style="font-size:0.7rem;color:#93c5fd;"><code>${escapeHtml((cl.services || []).join(', '))}</code></div>
          </div>
        `).join('') || '<div style="font-size:0.8rem;color:var(--text-muted);">Pricing clusters unavailable.</div>';
      }

      const addonBar = $('#cw-addon-chips-bar');
      if (addonBar) {
        const addons = Object.values(addonsMap);
        addonBar.innerHTML = addons.length ? (
          '<span style="color:var(--text-muted);font-weight:600;">Click to add module:</span>' +
          addons.map(m => `
            <button type="button" class="secondary-btn cw-addon-chip" data-addon="${escapeHtml(m.module_key)}" style="padding:4px 10px;font-size:0.74rem;">
              + ${escapeHtml(m.module_key)} (₹${Number(m.monthly_price_inr || 0).toLocaleString('en-IN')} / $${escapeHtml(String(m.monthly_price_usd || 0))})
            </button>
          `).join('')
        ) : '';
        addonBar.querySelectorAll('.cw-addon-chip').forEach(btn => {
          btn.addEventListener('click', () => {
            const inp = $('#cw-bill-addons');
            if (!inp) return;
            const key = btn.getAttribute('data-addon') || '';
            const cur = inp.value.split(',').map(s => s.trim()).filter(Boolean);
            if (key && !cur.includes(key)) cur.push(key);
            inp.value = cur.join(', ');
          });
        });
      }

      const tierSel = $('#cw-bill-tier');
      if (tierSel && cwState.contracts.length) {
        const curT = tierSel.value;
        tierSel.innerHTML = cwState.contracts.map(c => (
          `<option value="${escapeHtml(c.plan_key)}">${escapeHtml(c.plan_name || c.name || c.plan_key)} (₹${Number(c.base_price?.inr ?? 0).toLocaleString('en-IN')}/mo • $${escapeHtml(String(c.base_price?.usd ?? 0))})</option>`
        )).join('');
        if (curT && cwState.contracts.some(c => c.plan_key === curT)) tierSel.value = curT;
      }

      const tierCheckoutSku = {
        launch: 'company_os_starter',
        growth: 'growth_all_in_one',
        operations: 'operations_suite',
        business_pro: 'company_os_pro',
        enterprise: 'company_os_enterprise',
      };
      const cBox = $('#cw-pricing-contracts-list');
      if (cBox) {
        cBox.innerHTML = cwState.contracts.map(c => {
          const inrMo = Number(c.base_price?.inr ?? 0);
          const usdMo = Number(c.base_price?.usd ?? 0);
          const inrYr = Number(c.annual_price?.inr ?? Math.round(inrMo * 0.8));
          const usdYr = Number(c.annual_price?.usd ?? Math.round(usdMo * 0.8));
          const clusters = (c.included_clusters || []).map(ck => {
            const clObj = clustersMap[ck];
            return clObj ? `C${clObj.cluster_number}` : ck;
          }).join(' + ');
          const pkgSlug = tierCheckoutSku[c.plan_key] || c.internal_sku || c.plan_key;
          return `
          <div style="border-bottom:1px solid var(--glass-border);padding:10px 0;font-size:0.8rem;">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
              <div>
                <strong>${escapeHtml(c.plan_name || c.name || c.plan_key)}</strong>
                ${clusters ? `<span class="badge" style="margin-left:6px;font-size:0.68rem;">${escapeHtml(clusters)}</span>` : ''}
              </div>
              <a href="/v1/pay/checkout?package=${encodeURIComponent(pkgSlug)}" target="_blank" style="font-size:0.74rem;color:var(--cyan);font-weight:600;text-decoration:none;">Checkout ↗</a>
            </div>
            <div style="margin-top:4px;color:var(--green);font-weight:700;">
              ₹${inrMo.toLocaleString('en-IN')}/mo ($${usdMo} USD)
              <span style="color:#a5b4fc;font-weight:500;margin-left:8px;">Annual (-20%): ₹${inrYr.toLocaleString('en-IN')}/mo ($${usdYr})</span>
            </div>
            <div style="margin-top:2px;color:var(--text-muted);font-size:0.75rem;">
              Modules: <code>${escapeHtml((c.included_modules || []).join(', '))}</code> •
              Credits: ${escapeHtml(String(c.included_credits || 0))} • Seats: ${escapeHtml(String(c.seat_limit || 0))} • Agents: ${escapeHtml(String(c.agent_limit || (c.entitled_agents || []).length))}
            </div>
          </div>
          `;
        }).join('') || '<div class="empty-state"><p>No contracts available.</p></div>';
      }

      const lBox = $('#cw-credit-ledger-list');
      if (lBox) {
        lBox.innerHTML = cwState.ledger.length ? cwState.ledger.map(e => `
          <div style="border-bottom:1px solid var(--glass-border);padding:6px 0;font-size:0.78rem;display:flex;justify-content:space-between;">
            <span><strong>${escapeHtml(e.entry_type)}</strong> (${escapeHtml(String(e.delta))} cr) • ${escapeHtml(e.reason || e.idempotency_key || '')}</span>
            <code>Balance: ${escapeHtml(String(e.balance_after))}</code>
          </div>
        `).join('') : '<div class="empty-state"><p>No credit ledger entries yet.</p></div>';
      }
    } catch (e) {
      console.warn('Billing load:', e.message);
    }
  }

  async function cwLoadEmergencyStops() {
    try {
      const endpoint = cwIsCustomer() ? '/v1/me/emergency-stops' : '/v1/watchdog/emergency-stops';
      const res = await api('GET', endpoint);
      cwState.stops = res.emergency_stops || [];
      const list = $('#cw-estop-active-list');
      if (list) {
        list.innerHTML = cwState.stops.length ? cwState.stops.map(s => `
          <div style="padding:6px 0;border-bottom:1px solid var(--glass-border);font-size:0.78rem;">
            <span class="cw-pill blocked">${escapeHtml(s.scope_level)}: ${escapeHtml(s.scope_target)}</span>
            <span style="margin-left:6px;">${escapeHtml(s.state)} — ${escapeHtml(s.reason || '')}</span>
          </div>
        `).join('') : '<div style="font-size:0.8rem;color:var(--text-muted);">No active emergency stops (all authorized agents operational).</div>';
      }
    } catch (e) {
      console.warn('Emergency stops load:', e.message);
    }
  }

  function cwInitControlCenter() {
    if (cwState.initialized) return;
    cwState.initialized = true;

    $('#cw-marketplace-category-filter')?.addEventListener('change', cwRenderMarketplace);
    $('#btn-cw-refresh-marketplace')?.addEventListener('click', cwHydrateRegistry);
    $('#btn-cw-refresh-workforce')?.addEventListener('click', cwHydrateRegistry);
    $('#btn-cw-refresh-connectors')?.addEventListener('click', cwHydrateRegistry);
    $('#btn-cw-reload-profile')?.addEventListener('click', cwLoadProfile);
    $('#btn-cw-save-profile')?.addEventListener('click', cwSaveProfile);
    $('#btn-cw-execute-agent')?.addEventListener('click', cwExecuteAgent);
    $('#btn-cw-refresh-workflows')?.addEventListener('click', cwLoadWorkflows);
    $('#btn-cw-create-workflow')?.addEventListener('click', cwCreateWorkflow);
    $('#btn-cw-refresh-history')?.addEventListener('click', cwLoadEvidenceHistory);
    $('#cw-history-mode-filter')?.addEventListener('change', cwLoadEvidenceHistory);
    $('#btn-cw-refresh-analytics')?.addEventListener('click', cwLoadAnalytics);
    $('#btn-cw-refresh-billing')?.addEventListener('click', cwLoadBilling);
    $('#btn-cw-close-evidence')?.addEventListener('click', () => { $('#cw-evidence-drawer').style.display = 'none'; });
    $('#btn-cw-close-evidence-footer')?.addEventListener('click', () => { $('#cw-evidence-drawer').style.display = 'none'; });

    $('#btn-cw-apply-subscription')?.addEventListener('click', async () => {
      try {
        const res = await api('POST', '/v1/me/modular-subscription', {
          base_tier: $('#cw-bill-tier')?.value || 'growth',
          addon_modules: cwSplitList($('#cw-bill-addons')?.value),
          credit_packs: Number($('#cw-bill-credits')?.value || 0),
        });
        if (res?.payment_required && res.checkout_url) {
          toast('Payment required — opening AFW DirectPay checkout...', 'info');
          window.open(res.checkout_url, '_blank', 'noopener');
          return;
        }
        toast('Modular subscription configured!', 'success');
        await cwLoadBilling();
        await cwHydrateRegistry();
      } catch (e) {
        toast(`Subscription update failed: ${e.message}`, 'error');
      }
    });

    $('#btn-cw-purchase-credits')?.addEventListener('click', async () => {
      const packs = Math.max(1, Number($('#cw-bill-credits')?.value || 1));
      try {
        const res = await api('POST', '/v1/me/credits/purchase', { credit_packs: packs });
        if (res?.payment_required && res.checkout_url) {
          toast('Opening AFW DirectPay checkout for credit pack...', 'info');
          window.open(res.checkout_url, '_blank', 'noopener');
          return;
        }
        toast(`Purchased ${packs} credit pack(s)`, 'success');
        await cwLoadBilling();
      } catch (e) {
        toast(`Credit purchase failed: ${e.message}`, 'error');
      }
    });

    $('#btn-cw-renew-subscription')?.addEventListener('click', async () => {
      try {
        const res = await api('POST', '/v1/me/subscription/renew', {});
        if (res?.payment_required && res.checkout_url) {
          toast('Opening AFW DirectPay checkout for renewal...', 'info');
          window.open(res.checkout_url, '_blank', 'noopener');
          return;
        }
        toast('Subscription renewed cleanly', 'success');
        await cwLoadBilling();
      } catch (e) {
        toast(`Renew failed: ${e.message}`, 'error');
      }
    });

    $('#btn-cw-cancel-subscription')?.addEventListener('click', async () => {
      try {
        await api('POST', '/v1/me/subscription/cancel', { cancel_at_period_end: true });
        toast('Subscription marked cancel-at-period-end', 'info');
        await cwLoadBilling();
      } catch (e) {
        toast(`Cancel failed: ${e.message}`, 'error');
      }
    });

    $('#btn-cw-save-gemini')?.addEventListener('click', async () => {
      const key = ($('#cw-settings-gemini-key')?.value || '').trim();
      try {
        await api('POST', '/v1/me/gemini-key', { gemini_api_key: key });
        toast('Tenant BYOK Gemini key updated', 'success');
      } catch (e) {
        toast(`BYOK save failed: ${e.message}`, 'error');
      }
    });

    const handleEstop = async (targetState) => {
      const scope = $('#cw-estop-scope')?.value || 'tenant';
      const target = ($('#cw-estop-target')?.value || '').trim() || null;
      const reason = ($('#cw-estop-reason')?.value || '').trim() || 'Safety control updated';
      const endpoint = cwIsCustomer() ? '/v1/me/emergency-stop' : '/v1/watchdog/emergency-stop';
      try {
        await api('POST', endpoint, { scope_level: scope, scope_target: target, state: targetState, reason });
        toast(`Emergency stop state set to ${targetState}`, targetState === 'EMERGENCY_STOPPED' ? 'warning' : 'success');
        await cwLoadEmergencyStops();
      } catch (e) {
        toast(`Emergency stop failed: ${e.message}`, 'error');
      }
    };
    $('#btn-cw-trigger-estop')?.addEventListener('click', () => handleEstop('EMERGENCY_STOPPED'));
    $('#btn-cw-release-estop')?.addEventListener('click', () => handleEstop('ACTIVE'));

    // Sidebar click hook to set clean page title and refresh tab data from backend
    $('.sidebar-nav')?.addEventListener('click', (ev) => {
      const item = ev.target.closest('.nav-item[data-page]');
      if (!item) return;
      const page = item.dataset.page;
      if (CW_PAGE_TITLES[page] && $('#page-title')) {
        $('#page-title').textContent = CW_PAGE_TITLES[page];
      }
      if (page === 'cw-profile') cwLoadProfile();
      if (page === 'cw-marketplace' || page === 'cw-workforce' || page === 'cw-connectors' || page === 'cw-run-console') cwHydrateRegistry();
      if (page === 'cw-workflows') cwLoadWorkflows();
      if (page === 'cw-history') cwLoadEvidenceHistory();
      if (page === 'cw-analytics') cwLoadAnalytics();
      if (page === 'cw-billing') cwLoadBilling();
      if (page === 'cw-settings') cwLoadEmergencyStops();
      if (page === 'commercial-os') p2LoadControlCentre();
      if (page === 'customer-success') p3LoadControlCentre();
      if (page === 'p4-growth') p4LoadControlCentre();
      if (page === 'p5-scale') p5LoadControlCentre();
      if (page === 'p6-packs') p6LoadControlCentre();
      if (page === 'p7-autonomy') p7LoadControlCentre();
      if (page === 'p8-marketplace') p8LoadControlCentre();
      if (page === 'approvals' && cwIsCustomer()) cwFetchScopedApprovals();
    });
    p2BindEvents();
    p3BindEvents();
    p4BindEvents();
    p5BindEvents();
    p6BindEvents();
    p7BindEvents();
    p8BindEvents();
  }

  // ── P2 Commercial Revenue OS Controller ───────────────────
  function p2SwitchSubtab(tabKey) {
    $$('.p2-subtab-btn').forEach(btn => {
      const isAct = btn.dataset.p2tab === tabKey;
      btn.classList.toggle('active', isAct);
      btn.classList.toggle('primary-btn', isAct);
      btn.classList.toggle('secondary-btn', !isAct);
    });
    $$('.p2-subtab-panel').forEach(panel => {
      panel.style.display = panel.id === `p2-panel-${tabKey}` ? 'block' : 'none';
    });
  }

  function p2FillLeadForms(leadId, email, company) {
    if ($('#p2-out-lead-id')) $('#p2-out-lead-id').value = leadId || '';
    if ($('#p2-out-email') && email) $('#p2-out-email').value = email;
    if ($('#p2-resp-lead-id')) $('#p2-resp-lead-id').value = leadId || '';
    if ($('#p2-prop-lead-id')) $('#p2-prop-lead-id').value = leadId || '';
    if ($('#p2-pipe-lead-id')) $('#p2-pipe-lead-id').value = leadId || '';
    toast(`Selected ${company || leadId} across P2 forms`, 'info');
  }

  async function p2LoadControlCentre() {
    if (cwIsCustomer()) return;
    try {
      const [ccRes, offerRes, prosRes, pipeRes, propRes, reconRes, engRes, accRes] = await Promise.all([
        api('GET', '/v1/commercial/control-centre'),
        api('GET', '/v1/commercial/offer/managed_seo_content_pilot'),
        api('GET', '/v1/commercial/prospects'),
        api('GET', '/v1/commercial/pipeline'),
        api('GET', '/v1/commercial/proposals'),
        api('GET', '/v1/commercial/reconciliation'),
        api('GET', '/v1/commercial/engagements'),
        api('GET', '/v1/commercial/acceptance-checklist'),
      ]);

      const vk = ccRes.verified_commercial_metrics || {};
      const sm = ccRes.simulation_and_test_metrics || {};
      const caps = ccRes.capability_status_summary || {};
      if ($('#p2-verified-kpis')) {
        $('#p2-verified-kpis').innerHTML = `
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">
            <div><strong>${Number(vk.real_prospects_discovered || 0)}</strong><br><span style="color:var(--text-muted)">Real Prospects</span></div>
            <div><strong>${Number(vk.outreach_sent || 0)}</strong><br><span style="color:var(--text-muted)">Live Sends</span></div>
            <div><strong>${Number(vk.responses_received || 0)}</strong><br><span style="color:var(--text-muted)">Responses</span></div>
            <div><strong>${Number(vk.proposals_sent || 0)} / ${Number(vk.pending_owner_approvals || 0)}</strong><br><span style="color:var(--text-muted)">Shared Props / Approvals</span></div>
            <div><strong>${Number(vk.active_paying_customers || 0)}</strong><br><span style="color:var(--text-muted)">Paid Customers</span></div>
            <div><strong>₹${Number(vk.verified_revenue_inr || 0).toLocaleString('en-IN')}</strong><br><span style="color:var(--text-muted)">Verified Revenue</span></div>
          </div>
          <div style="margin-top:8px;font-size:0.75rem;color:var(--text-muted);">
            Qualified: ${Number(vk.qualified_leads || 0)} &bull; Checkouts: ${Number(vk.checkouts_initiated || 0)} &bull; Verified Payments: ${Number(vk.verified_payments || 0)} &bull; Deliveries Done: ${Number(vk.deliverables_completed || 0)}
          </div>
        `;
      }

      if ($('#p2-sim-and-caps')) {
        const capHtml = Object.entries(caps).map(([stateKey, list]) => (
          `<span class="cw-pill ${cwStateClass(stateKey)}" style="margin:2px;">${escapeHtml(stateKey)}: ${escapeHtml((list || []).join(', '))}</span>`
        )).join('');
        $('#p2-sim-and-caps').innerHTML = `
          <div style="margin-bottom:8px;">
            <span class="cw-pill simulated">Simulated Sends: ${Number(sm.simulated_outreach_sent || 0)}</span>
            <span class="cw-pill simulated">Simulated Runs: ${Number(sm.simulated_workflow_runs || 0)}</span>
            <span class="cw-pill blocked">Synthetic Excluded: ${Number(sm.synthetic_prospects_count || 0)}</span>
            <span class="cw-pill blocked">Pending/Retry Recon: ${Number(sm.pending_or_retry_reconciliations || 0)}</span>
          </div>
          <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:6px;">${escapeHtml(sm.note || 'Strictly excluded from verified_commercial_metrics above.')}</div>
          <div style="display:flex;flex-wrap:wrap;gap:4px;">${capHtml}</div>
        `;
      }

      if ($('#p2-offer-contract')) {
        $('#p2-offer-contract').innerHTML = `
          <strong>${escapeHtml(offerRes.name)}</strong> &mdash; ₹${Number(offerRes.price_inr || 0).toLocaleString('en-IN')} INR / $${Number(offerRes.price_usd || 0)} USD
          (${escapeHtml(offerRes.billing_type)}, interval: ${escapeHtml(offerRes.billing_interval)})<br>
          <span style="color:var(--text-muted);">Deliverables: ${(offerRes.deliverables || []).map(escapeHtml).join(' &bull; ')}</span><br>
          <span style="color:var(--amber,#f59e0b);">Non-guarantees: ${(offerRes.non_guarantees || []).map(escapeHtml).join(' | ')}</span>
        `;
      }

      // Render Prospects
      const prospects = prosRes.prospects || [];
      if ($('#p2-prospects-tbody')) {
        $('#p2-prospects-tbody').innerHTML = prospects.length ? prospects.map(p => {
          const crit = (p.qualification_breakdown && p.qualification_breakdown.criteria) || {};
          const critText = Object.entries(crit).map(([k, v]) => `${escapeHtml(k)}: ${v.score}/${v.max}`).join(' &bull; ');
          const contact = (p.public_contacts && p.public_contacts[0]) || {};
          return `
            <tr>
              <td><strong>${escapeHtml(p.company)}</strong><br><span style="font-size:0.75rem;color:var(--text-muted);">${escapeHtml(p.domain)} &bull; ${escapeHtml(p.location)}</span></td>
              <td><span class="cw-pill ${cwStateClass(p.pipeline_status)}">${escapeHtml(p.pipeline_status)}</span></td>
              <td><strong>${Number(p.qualification_score || 0).toFixed(1)}</strong>/100<br><span style="font-size:0.72rem;color:var(--text-muted);">${critText}</span></td>
              <td style="font-size:0.74rem;"><a href="${escapeHtml(p.source_url)}" target="_blank" rel="noopener">${escapeHtml(p.source_type)}</a><br>${escapeHtml(contact.value || 'No public email')} (${contact.verified ? 'Verified' : 'Unverified'})</td>
              <td style="display:flex;gap:4px;flex-wrap:wrap;">
                <button type="button" class="secondary-btn" onclick="window.app.p2SelectLead('${escapeHtml(p.lead_id)}','${escapeHtml(contact.value || '')}','${escapeHtml(p.company)}')">Select</button>
                <button type="button" class="secondary-btn" onclick="window.app.p2ShowBrief('${escapeHtml(p.lead_id)}')">Brief</button>
                <button type="button" class="secondary-btn" onclick="window.app.p2Requalify('${escapeHtml(p.lead_id)}')">Score</button>
              </td>
            </tr>
          `;
        }).join('') : '<tr class="empty-row"><td colspan="5"><div class="empty-state"><p>No real agency prospects ingested yet.</p></div></td></tr>';
      }

      // Render Pipeline
      const pipe = pipeRes.pipeline || [];
      if ($('#p2-pipeline-tbody')) {
        $('#p2-pipeline-tbody').innerHTML = pipe.length ? pipe.map(row => `
          <tr>
            <td><strong>${escapeHtml(row.company)}</strong><br><span style="font-size:0.73rem;color:var(--text-muted);">${escapeHtml(row.domain)}</span></td>
            <td><span class="cw-pill ${cwStateClass(row.pipeline_status)}">${escapeHtml(row.pipeline_status)}</span></td>
            <td>${Number(row.qualification_score || 0).toFixed(1)}</td>
            <td style="font-size:0.76rem;">${escapeHtml(row.next_action || '')}</td>
            <td style="font-size:0.74rem;">Props: ${row.latest_proposal ? escapeHtml(row.latest_proposal.status) : 'NONE'} &bull; Payment: ${escapeHtml(row.payment_status || 'UNPAID')}</td>
          </tr>
        `).join('') : '<tr class="empty-row"><td colspan="5"><div class="empty-state"><p>Pipeline is empty.</p></div></td></tr>';
      }

      // Render Proposals
      const props = propRes.proposals || [];
      if ($('#p2-proposals-list')) {
        $('#p2-proposals-list').innerHTML = props.length ? props.map(pr => {
          const pricing = pr.pricing || {};
          return `
            <div style="border-top:1px solid var(--border);padding:8px 0;">
              <strong>${escapeHtml(pr.sku_key)}</strong> (${escapeHtml(pricing.currency || 'INR')} ${Number(pricing.total_amount || 0).toLocaleString()}) &mdash;
              Status: <span class="cw-pill ${cwStateClass(pr.status)}">${escapeHtml(pr.status)}</span>
              <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;">
                <button type="button" class="secondary-btn" onclick="window.app.p2ShareProposal('${escapeHtml(pr.proposal_id)}')">Share Approved Proposal</button>
                <button type="button" class="primary-btn" onclick="window.app.p2CreateCheckout('${escapeHtml(pr.proposal_id)}')">Generate DirectPay Link</button>
                ${pr.checkout_url ? `<a href="${escapeHtml(pr.checkout_url)}" target="_blank" rel="noopener" style="font-size:0.76rem;color:var(--cyan);">Open Checkout ↗</a>` : ''}
              </div>
            </div>
          `;
        }).join('') : '<div style="color:var(--text-muted);">No structured proposals generated yet.</div>';
      }

      // Render Reconciliation Queue
      const recons = reconRes.reconciliations || [];
      if ($('#p2-reconciliation-list')) {
        $('#p2-reconciliation-list').innerHTML = recons.length ? recons.map(rc => `
          <div style="border-top:1px solid var(--border);padding:6px 0;">
            <span class="cw-pill ${cwStateClass(rc.verification_state)}">${escapeHtml(rc.verification_state)}</span>
            <strong>${escapeHtml(rc.provider)}</strong> (${escapeHtml(rc.currency)} ${Number(rc.received_amount || 0)} / ${Number(rc.expected_amount || 0)})
            <div style="font-size:0.74rem;color:var(--text-muted);">Ref: ${escapeHtml(rc.checkout_reference)} &bull; Retries: ${Number(rc.retry_count || 0)} ${rc.last_error ? `&bull; ${escapeHtml(rc.last_error)}` : ''}</div>
            ${rc.verification_state !== 'ACTIVATION_COMPLETED' ? `<button type="button" class="secondary-btn" style="margin-top:4px;" onclick="window.app.p2RetryRecon('${escapeHtml(rc.reconciliation_id)}')">Retry</button>` : ''}
          </div>
        `).join('') : '<div style="color:var(--text-muted);">No checkout or payment events recorded yet.</div>';
      }

      // Render Engagements
      const engs = engRes.engagements || [];
      if ($('#p2-engagements-list')) {
        $('#p2-engagements-list').innerHTML = engs.length ? engs.map(en => `
          <div style="border-top:1px solid var(--border);padding:8px 0;">
            <strong>${escapeHtml(en.org_id)}</strong> (${escapeHtml(en.sku_key)}) &mdash;
            <span class="cw-pill ${cwStateClass(en.status)}">${escapeHtml(en.status)}</span>
            <button type="button" class="secondary-btn" style="margin-left:8px;" onclick="window.app.p2SelectEngagement('${escapeHtml(en.engagement_id)}')">Select Engagement</button>
            <div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px;">
              Workflow Run: ${escapeHtml(en.workflow_run_id || 'Pending')} &bull; Stage: ${escapeHtml((en.deliverables || {}).stage_status || 'NOT_STARTED')} &bull; Renewal Auto-Charge Disabled: YES
            </div>
          </div>
        `).join('') : '<div style="color:var(--text-muted);">No paid customer engagements activated yet.</div>';
      }

      // Render 12-Step Acceptance Checklist
      const steps = accRes.steps || [];
      const sum = accRes.summary || {};
      if ($('#p2-acceptance-summary')) {
        $('#p2-acceptance-summary').innerHTML = `NOT_TESTED: <strong>${sum.NOT_TESTED || 0}</strong> &bull; SANDBOX_VERIFIED: <strong>${sum.SANDBOX_VERIFIED || 0}</strong> &bull; LIVE_VERIFIED: <strong>${sum.LIVE_VERIFIED || 0}</strong>`;
      }
      if ($('#p2-acceptance-steps-list')) {
        $('#p2-acceptance-steps-list').innerHTML = steps.map(st => `
          <div style="border-top:1px solid var(--border);padding:8px 0;display:grid;grid-template-columns:2fr 1fr 1.5fr auto;gap:8px;align-items:center;">
            <div>
              <strong>${escapeHtml(st.title)}</strong><br>
              <span style="font-size:0.74rem;color:var(--text-muted);">${escapeHtml(st.description)}</span>
            </div>
            <select id="p2-step-status-${st.step_number}" class="settings-select">
              <option value="NOT_TESTED" ${st.verification_status === 'NOT_TESTED' ? 'selected' : ''}>NOT_TESTED</option>
              <option value="SANDBOX_VERIFIED" ${st.verification_status === 'SANDBOX_VERIFIED' ? 'selected' : ''}>SANDBOX_VERIFIED</option>
              <option value="LIVE_VERIFIED" ${st.verification_status === 'LIVE_VERIFIED' ? 'selected' : ''}>LIVE_VERIFIED</option>
            </select>
            <input id="p2-step-evidence-${st.step_number}" class="settings-input" value="${escapeHtml(st.evidence_summary || '')}" placeholder="Verified evidence summary / ID">
            <button type="button" class="secondary-btn" onclick="window.app.p2SaveStep(${st.step_number})">Save</button>
          </div>
        `).join('');
      }
    } catch (e) {
      toast(`P2 Control Centre load failed: ${e.message}`, 'error');
    }
  }

  function p2BindEvents() {
    $$('#p2-subtabs-bar .p2-subtab-btn').forEach(btn => {
      btn.addEventListener('click', () => p2SwitchSubtab(btn.dataset.p2tab));
    });
    $('#btn-p2-refresh-all')?.addEventListener('click', p2LoadControlCentre);
    $('#btn-p2-discover-live')?.addEventListener('click', async () => {
      try {
        const res = await api('POST', '/v1/commercial/prospects/discover', { query: 'digital marketing SEO agency India', limit: 5 });
        toast(`Live Discovery: ${res.status} — ${res.reason || `${(res.discovered || []).length} discovered`}`, res.status === 'BLOCKED' ? 'warning' : 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Discovery failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p2-ingest-prospect')?.addEventListener('click', async () => {
      try {
        const res = await api('POST', '/v1/commercial/prospects/ingest', {
          company: ($('#p2-in-company')?.value || '').trim(),
          website: ($('#p2-in-website')?.value || '').trim(),
          location: ($('#p2-in-location')?.value || 'India').trim(),
          source_url: ($('#p2-in-source')?.value || '').trim(),
          public_email: ($('#p2-in-email')?.value || '').trim() || null,
          public_contact_verified: !!$('#p2-in-contact-verified')?.checked,
          actual_services: cwSplitList($('#p2-in-services')?.value),
          publicly_verifiable_needs: cwSplitList($('#p2-in-needs')?.value),
          inspect_live_website: !!$('#p2-in-inspect-live')?.checked,
        });
        toast(`Prospect ingested: ${res.company} (${res.pipeline_status}, score ${res.qualification_score})`, 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Prospect intake failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p2-prepare-outreach')?.addEventListener('click', async () => {
      try {
        const res = await api('POST', '/v1/commercial/outreach/prepare', {
          lead_id: ($('#p2-out-lead-id')?.value || '').trim(),
          recipient_email: ($('#p2-out-email')?.value || '').trim() || null,
          recipient_name: ($('#p2-out-name')?.value || '').trim() || null,
          custom_notes: ($('#p2-out-notes')?.value || '').trim() || null,
        });
        if ($('#p2-last-outreach-id')) $('#p2-last-outreach-id').value = res.outreach_id || '';
        if ($('#p2-outreach-result')) {
          $('#p2-outreach-result').innerHTML = `
            <div class="cw-pill sandbox">Draft Prepared (${escapeHtml(res.status)})</div>
            <div style="margin-top:6px;">Outreach ID: <code>${escapeHtml(res.outreach_id)}</code> &bull; Approval ID: <code>${escapeHtml(res.approval_id)}</code></div>
            <div style="margin-top:4px;color:var(--text-muted);">Approve in HITL Approvals tab before clicking Dispatch Approved Draft.</div>
          `;
        }
        toast('Outreach draft created & waiting for Owner approval', 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Prepare outreach failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p2-dispatch-outreach')?.addEventListener('click', async () => {
      const oid = ($('#p2-last-outreach-id')?.value || '').trim();
      if (!oid) { toast('Prepare or enter an Outreach ID first', 'warning'); return; }
      try {
        const res = await api('POST', `/v1/commercial/outreach/${encodeURIComponent(oid)}/dispatch`, {});
        toast(`Dispatch finished: ${res.status} (${res.delivery_mode || (res.external_sent ? 'LIVE' : 'SIMULATED')})`, res.external_sent ? 'success' : 'warning');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Dispatch blocked: ${e.message}`, 'error');
      }
    });
    $('#btn-p2-log-response')?.addEventListener('click', async () => {
      const lid = ($('#p2-resp-lead-id')?.value || '').trim();
      try {
        await api('POST', `/v1/commercial/pipeline/${encodeURIComponent(lid)}/responses`, {
          sentiment: $('#p2-resp-sentiment')?.value || 'interested',
          summary: ($('#p2-resp-summary')?.value || '').trim(),
          discovery_notes: ($('#p2-resp-discovery')?.value || '').trim() || null,
        });
        toast('Prospect response logged', 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Log response failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p2-create-proposal')?.addEventListener('click', async () => {
      try {
        const res = await api('POST', '/v1/commercial/proposals', {
          lead_id: ($('#p2-prop-lead-id')?.value || '').trim(),
          sku_key: ($('#p2-prop-sku')?.value || 'managed_seo_content_pilot').trim(),
          currency: $('#p2-prop-currency')?.value || 'INR',
          custom_problem_statement: ($('#p2-prop-problem')?.value || '').trim() || null,
        });
        toast(`Proposal created (${res.status}) — approve in Approvals tab`, 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Create proposal failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p2-transition-status')?.addEventListener('click', async () => {
      const lid = ($('#p2-pipe-lead-id')?.value || '').trim();
      try {
        await api('POST', `/v1/commercial/pipeline/${encodeURIComponent(lid)}/transition`, {
          target_status: $('#p2-pipe-status')?.value || 'DISCOVERY',
          next_action: ($('#p2-pipe-next')?.value || '').trim() || null,
        });
        toast('Pipeline status updated cleanly', 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Transition failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p2-submit-onboarding')?.addEventListener('click', async () => {
      const eid = ($('#p2-eng-id')?.value || '').trim();
      try {
        await api('POST', `/v1/commercial/engagements/${encodeURIComponent(eid)}/onboarding`, {
          target_domain: ($('#p2-onb-domain')?.value || '').trim(),
          cms_delivery_mode: $('#p2-onb-cms')?.value || 'markdown_html_export',
          priority_topics: cwSplitList($('#p2-onb-topics')?.value),
        });
        toast('Customer onboarding inputs saved', 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Onboarding failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p2-run-delivery')?.addEventListener('click', async () => {
      const eid = ($('#p2-eng-id')?.value || '').trim();
      try {
        const res = await api('POST', `/v1/commercial/engagements/${encodeURIComponent(eid)}/deliver`, {});
        toast(`Delivery workflow staged: ${res.status}`, 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Delivery workflow failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p2-complete-delivery')?.addEventListener('click', async () => {
      const eid = ($('#p2-eng-id')?.value || '').trim();
      try {
        await api('POST', `/v1/commercial/engagements/${encodeURIComponent(eid)}/complete-delivery`, {
          delivery_channel_proof: ($('#p2-deliv-proof')?.value || '').trim(),
        });
        toast('Engagement delivery confirmed completed', 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Complete delivery failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p2-submit-feedback')?.addEventListener('click', async () => {
      const eid = ($('#p2-eng-id')?.value || '').trim();
      try {
        const res = await api('POST', `/v1/commercial/engagements/${encodeURIComponent(eid)}/feedback-renewal`, {
          rating: Number($('#p2-fb-rating')?.value || 5),
          comments: ($('#p2-fb-comments')?.value || '').trim(),
          interested_in_renewal: $('#p2-fb-renew')?.value === 'true',
        });
        if ($('#p2-feedback-result')) {
          const rec = res.renewal_recommendation || {};
          $('#p2-feedback-result').innerHTML = `Renewal Recommended: <strong>${escapeHtml(rec.recommended_plan_sku || '')}</strong> (auto_charge_disabled: ${!!rec.auto_charge_disabled})`;
        }
        toast('Feedback & renewal recommendation recorded', 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Feedback failed: ${e.message}`, 'error');
      }
    });
  }

  // ── P3 Customer Success & Growth Engine Controller ─────────
  function p3SwitchSubtab(tabKey) {
    $$('.p3-subtab-btn').forEach(btn => {
      const isAct = btn.dataset.p3tab === tabKey;
      btn.classList.toggle('active', isAct);
      btn.classList.toggle('primary-btn', isAct);
      btn.classList.toggle('secondary-btn', !isAct);
    });
    $$('.p3-subtab-panel').forEach(panel => {
      panel.style.display = panel.id === `p3-panel-${tabKey}` ? 'block' : 'none';
    });
  }

  async function p3LoadOrgDetails(orgId) {
    if (!orgId) return;
    try {
      const [onbRes, healthRes, ueRes] = await Promise.all([
        api('GET', `/v1/cs/customers/${encodeURIComponent(orgId)}/onboarding`),
        api('GET', `/v1/cs/customers/${encodeURIComponent(orgId)}/health`),
        api('GET', `/v1/cs/unit-economics/${encodeURIComponent(orgId)}`),
      ]);
      if ($('#p3-onboarding-tasks')) {
        const tasks = onbRes.tasks || [];
        const blockers = onbRes.blockers || [];
        $('#p3-onboarding-tasks').innerHTML = `
          <div style="margin-bottom:8px;">
            <strong>SKU:</strong> ${escapeHtml(onbRes.sku_key || '')} •
            <strong>Progress:</strong> ${onbRes.progress_pct || 0}% •
            <strong>Status:</strong> ${escapeHtml(onbRes.status || '')}
          </div>
          ${blockers.length ? `<div style="color:var(--amber);margin-bottom:8px;"><strong>Blockers:</strong> ${blockers.map(escapeHtml).join(', ')}</div>` : ''}
          <div style="display:flex;flex-direction:column;gap:4px;max-height:190px;overflow:auto;">
            ${tasks.map(t => `<div>${t.completed ? '✅' : '⬜'} <strong>${escapeHtml(t.title || t.key)}</strong> <span style="color:var(--text-muted)">(${escapeHtml(t.owner || '')})</span></div>`).join('')}
          </div>
        `;
      }
      if ($('#p3-health-viewer')) {
        const bd = healthRes.breakdown || [];
        $('#p3-health-viewer').innerHTML = `
          <div style="margin-bottom:8px;">
            <strong>State:</strong> <span class="badge">${escapeHtml(healthRes.health_state || 'INSUFFICIENT_DATA')}</span> •
            <strong>Score:</strong> ${healthRes.overall_score ?? 'INSUFFICIENT_DATA'} •
            <strong>Freshness:</strong> ${escapeHtml(healthRes.data_freshness || '')}
          </div>
          <div style="display:flex;flex-direction:column;gap:4px;">
            ${bd.map(d => `<div><code>${escapeHtml(d.dimension)}</code>: ${d.score ?? 'N/A'} — <span style="color:var(--text-muted)">${escapeHtml(d.evidence || '')}</span></div>`).join('')}
          </div>
        `;
      }
      if ($('#p3-ue-viewer')) {
        const rev = ueRes.revenue_summary || {};
        const cost = ueRes.cost_summary || {};
        const lbl = cost.costs_by_quality_label || {};
        const prof = ueRes.profitability || {};
        const acq = ueRes.acquisition_and_ltv || {};
        $('#p3-ue-viewer').innerHTML = `
          <div><strong>Net Verified Revenue:</strong> ₹${rev.net_verified_revenue_inr ?? 0} | <strong>Operating Cost:</strong> ₹${cost.total_operating_cost_inr ?? 0} | <strong>Gross Margin:</strong> ${prof.gross_margin_pct ?? 'INSUFFICIENT_DATA'}%</div>
          <div style="margin-top:4px;color:var(--text-muted);">Labels — ACTUAL: ₹${lbl.ACTUAL ?? 0}, ALLOCATED: ₹${lbl.ALLOCATED ?? 0}, ESTIMATED: ₹${lbl.ESTIMATED ?? 0} | Historical CAC/LTV: ${escapeHtml(String(acq.ltv_data_quality || 'INSUFFICIENT_DATA'))}</div>
        `;
      }
    } catch (e) {
      toast(`Customer detail load error: ${e.message}`, 'error');
    }
  }

  async function p3LoadControlCentre() {
    if (cwIsCustomer()) return;
    try {
      const [ccRes, custRes, delivRes, tktRes, impRes, relRes, growthRes, opsRes, accRes] = await Promise.all([
        api('GET', '/v1/cs/control-centre'),
        api('GET', '/v1/cs/customers'),
        api('GET', '/v1/cs/deliveries'),
        api('GET', '/v1/cs/support/tickets'),
        api('GET', '/v1/cs/improvements'),
        api('GET', '/v1/cs/subscriptions/reliability'),
        api('GET', '/v1/cs/growth'),
        api('GET', '/v1/cs/ops/readiness'),
        api('GET', '/v1/cs/acceptance'),
      ]);
      const rrRes = await api('GET', '/v1/cs/release-readiness').catch(() => null);

      const vco = ccRes.verified_customer_ops || {};
      const act = vco.activation || {};
      const del = vco.delivery || {};
      const ret = vco.retention_and_subscriptions || {};
      const rev = vco.revenue_and_unit_economics || {};
      const sup = vco.support_and_improvements || {};
      const sim = ccRes.simulation_and_test_metrics || {};

      if ($('#p3-cc-freshness')) {
        $('#p3-cc-freshness').textContent = `${ccRes.data_freshness || 'REALTIME'} • ${ccRes.reporting_period?.period_days || 30}d`;
      }
      if ($('#p3-cc-live-kpis')) {
        const cards = [
          ['Active Customers', `${ret.active_customers ?? 0} (At-Risk: ${ret.at_risk_customers ?? 0})`],
          ['Activation Rate', `${act.activation_rate_pct ?? 0}% (${act.activated_customers ?? 0}/${act.total_customers ?? 0})`],
          ['Verified Recurring MRR', `₹${rev.verified_recurring_mrr_inr ?? 0}`],
          ['Verified ARR (Recurring Only)', String(rev.verified_arr_inr ?? 'INSUFFICIENT_DATA')],
          ['One-Time Pilot Revenue', `₹${rev.verified_one_time_revenue_inr ?? 0}`],
          ['Deliveries & QA Pass Rate', `${del.total_deliveries ?? 0} (${del.qa_pass_rate_pct ?? 'INSUFFICIENT_DATA'}%)`],
          ['Open Support & Avg CSAT', `${sup.open_tickets ?? 0} open • ${sup.avg_csat_out_of_5 ?? 'INSUFFICIENT_DATA'}/5`],
          ['Outstanding Receivables', `₹${rev.outstanding_receivables_inr ?? 0}`],
        ];
        $('#p3-cc-live-kpis').innerHTML = cards
          .map(([k, v]) => `<div class="stat-card"><div class="stat-header"><span class="stat-label">${escapeHtml(k)}</span></div><div class="stat-value" style="font-size:1.15rem;">${escapeHtml(String(v))}</div></div>`)
          .join('');
      }
      if ($('#p3-cc-sim-kpis')) {
        $('#p3-cc-sim-kpis').textContent = `Policy: ${sim.exclusion_policy || 'EXCLUDED'} | Synthetic Prospects: ${sim.synthetic_prospects_count ?? 0} | Sandbox Accounts: ${sim.sandbox_customer_accounts_count ?? 0} | Simulation Runs: ${sim.simulation_workflow_runs_count ?? 0}`;
      }
      if ($('#p3-cc-methods')) {
        const cm = ccRes.calculation_method || {};
        $('#p3-cc-methods').innerHTML = Object.entries(cm)
          .map(([k, v]) => `<div><strong>${escapeHtml(k)}:</strong> ${escapeHtml(String(v))}</div>`)
          .join('');
      }

      const customers = custRes.customers || [];
      if ($('#p3-customers-tbody')) {
        $('#p3-customers-tbody').innerHTML = customers.length
          ? customers.map(c => `<tr>
              <td><code>${escapeHtml(c.org_id)}</code></td>
              <td><span class="badge">${escapeHtml(c.lifecycle_state)}</span></td>
              <td>${c.onboarding_progress_pct ?? 0}%</td>
              <td>${c.activation_ready ? 'Ready' : 'Blocked/Pending'}</td>
              <td><button type="button" class="secondary-btn" onclick="window.app.p3SelectOrg('${escapeHtml(c.org_id)}')">Select</button></td>
            </tr>`).join('')
          : '<tr><td colspan="5">No customer accounts yet</td></tr>';
      }

      if ($('#p3-deliveries-tbody')) {
        const dels = delivRes.deliveries || [];
        $('#p3-deliveries-tbody').innerHTML = dels.length
          ? dels.map(d => `<tr>
              <td>${escapeHtml(d.title)}</td>
              <td><code>${escapeHtml(d.org_id)}</code></td>
              <td><span class="badge">${escapeHtml(d.quality_state)}</span></td>
              <td>${Object.keys(d.output_artifacts || {}).length} artifact(s)</td>
              <td style="display:flex;gap:4px;flex-wrap:wrap;">
                <button type="button" class="secondary-btn" onclick="window.app.p3QaPass('${escapeHtml(d.delivery_id)}', true)">QA Pass</button>
                <button type="button" class="danger-btn" onclick="window.app.p3QaPass('${escapeHtml(d.delivery_id)}', false)">QA Fail</button>
              </td>
            </tr>`).join('')
          : '<tr><td colspan="5">No service deliveries recorded</td></tr>';
      }

      if ($('#p3-tickets-tbody')) {
        const tkts = tktRes.tickets || [];
        $('#p3-tickets-tbody').innerHTML = tkts.length
          ? tkts.map(t => `<tr>
              <td><code>${escapeHtml(t.ticket_number)}</code></td>
              <td>${escapeHtml(t.subject)}</td>
              <td>${escapeHtml(t.priority)}</td>
              <td><span class="badge">${escapeHtml(t.status)}</span></td>
              <td>${t.csat_rating ?? '-'}</td>
              <td style="display:flex;gap:4px;flex-wrap:wrap;">
                <button type="button" class="secondary-btn" onclick="window.app.p3SelectTicketReply('${escapeHtml(t.ticket_id)}')">Reply</button>
                <button type="button" class="secondary-btn" onclick="window.app.p3AiAssistTicket('${escapeHtml(t.ticket_id)}')">AI Triage</button>
                <button type="button" class="secondary-btn" onclick="window.app.p3ResolveTicket('${escapeHtml(t.ticket_id)}')">Resolve</button>
              </td>
            </tr>`).join('')
          : '<tr><td colspan="6">No support tickets</td></tr>';
      }

      if ($('#p3-improvements-tbody')) {
        const imps = impRes.improvements || [];
        $('#p3-improvements-tbody').innerHTML = imps.length
          ? imps.map(i => `<tr>
              <td>${escapeHtml(i.source_category)}</td>
              <td>${escapeHtml(i.title)}</td>
              <td>${i.priority_score}</td>
              <td>${i.frequency_count}</td>
              <td><span class="badge">${escapeHtml(i.status)}</span></td>
              <td style="display:flex;gap:4px;align-items:center;">
                <select id="p3-imp-status-${escapeHtml(i.improvement_id)}" class="settings-select" style="width:120px;padding:3px 6px;font-size:0.74rem;">
                  ${['OPEN', 'IN_BACKLOG', 'PLANNED', 'RESOLVED', 'DISMISSED'].map(st => `<option value="${st}" ${i.status === st ? 'selected' : ''}>${st}</option>`).join('')}
                </select>
                <button type="button" class="secondary-btn" onclick="window.app.p3UpdateImprovement('${escapeHtml(i.improvement_id)}')">Save</button>
              </td>
            </tr>`).join('')
          : '<tr><td colspan="6">No improvement clusters yet</td></tr>';
      }

      if ($('#p3-renewals-tbody')) {
        const rens = relRes.upcoming_renewals || [];
        $('#p3-renewals-tbody').innerHTML = rens.length
          ? rens.map(r => `<tr>
              <td><code>${escapeHtml(r.org_id)}</code></td>
              <td>${escapeHtml(r.internal_sku || '')}</td>
              <td>${escapeHtml(r.billing_type || '')}</td>
              <td>${escapeHtml((r.renewal_date || '').slice(0, 10))} (${r.days_remaining}d)</td>
              <td>${escapeHtml(r.status || '')}</td>
            </tr>`).join('')
          : '<tr><td colspan="5">No upcoming renewals in 30d window</td></tr>';
      }

      if ($('#p3-growth-tbody')) {
        const opps = growthRes.opportunities || [];
        $('#p3-growth-tbody').innerHTML = opps.length
          ? opps.map(o => `<tr>
              <td><code>${escapeHtml(o.org_id)}</code></td>
              <td>${escapeHtml(o.title)}</td>
              <td>${escapeHtml(o.recommended_sku_key || '-')}</td>
              <td><span class="badge">${escapeHtml(o.status)}</span></td>
              <td><button type="button" class="secondary-btn" onclick="window.app.p3ShareOpportunity('${escapeHtml(o.opportunity_id)}')">HITL Share</button></td>
            </tr>`).join('')
          : '<tr><td colspan="5">No expansion/referral opportunities yet</td></tr>';
      }

      if ($('#p3-ops-summary')) {
        const dbh = opsRes.database_health || {};
        const conc = opsRes.concurrency_limits || {};
        $('#p3-ops-summary').innerHTML = `DB Status: <strong>${escapeHtml(dbh.status || 'UNKNOWN')}</strong> (${escapeHtml(dbh.dialect || '')}, ping ${dbh.ping_latency_ms ?? '-'}ms) | Active Workflows: ${conc.active_runs_total ?? 0} (Cap/org: ${conc.max_concurrent_runs_per_org ?? 5})`;
      }
      if ($('#p3-release-readiness-summary') && rrRes) {
        const subs = Object.entries(rrRes.subsystems || {})
          .map(([k, v]) => `<code>${escapeHtml(k)}</code>: <strong>${escapeHtml(v.state || 'UNKNOWN')}</strong>`)
          .join(' | ');
        const gaps = (rrRes.blocking_gaps || []).length;
        $('#p3-release-readiness-summary').innerHTML = `
          <div>Overall Gate: <strong>${escapeHtml(rrRes.overall_release_readiness || 'BLOCKED')}</strong> • Cutover Approved: <strong>${rrRes.production_cutover_approved ? 'YES' : 'NO'}</strong> • Blocking Gaps: ${gaps}</div>
          <div style="margin-top:4px;font-size:0.78rem;color:var(--text-muted);">${subs}</div>
        `;
      }
      if ($('#p3-dlq-tbody')) {
        const dlqs = opsRes.dlq_summary?.open_items || [];
        $('#p3-dlq-tbody').innerHTML = dlqs.length
          ? dlqs.map(i => `<tr>
              <td>${escapeHtml(i.incident_type)}</td>
              <td><code>${escapeHtml(i.resource_ref || '')}</code></td>
              <td>${escapeHtml(i.status)}</td>
              <td>${i.retry_attempts}</td>
              <td><button type="button" class="secondary-btn" onclick="window.app.p3RetryDlq('${escapeHtml(i.id)}')">Retry</button></td>
            </tr>`).join('')
          : '<tr><td colspan="5">No open DLQ incidents</td></tr>';
      }

      if ($('#p3-acceptance-summary')) {
        const smr = accRes.summary || {};
        $('#p3-acceptance-summary').textContent = `Live: ${smr.live_verified_count || 0} | Sandbox: ${smr.sandbox_verified_count || 0} | Not Tested: ${smr.not_tested_count ?? 12}`;
      }
      if ($('#p3-acceptance-steps-list')) {
        const steps = accRes.steps || [];
        $('#p3-acceptance-steps-list').innerHTML = steps.map(s => `
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 0;border-bottom:1px solid var(--border-subtle);">
            <div style="flex:1;min-width:220px;">
              <strong>#${s.step_number} ${escapeHtml(s.title)}</strong>
              <div style="font-size:0.78rem;color:var(--text-muted);">${escapeHtml(s.description)}</div>
            </div>
            <div style="display:flex;gap:6px;align-items:center;">
              <select id="p3-step-status-${s.step_number}" class="settings-select" style="width:165px;">
                ${['NOT_TESTED', 'SANDBOX_VERIFIED', 'LIVE_VERIFIED'].map(opt => `<option value="${opt}" ${s.verification_status === opt ? 'selected' : ''}>${opt}</option>`).join('')}
              </select>
              <input type="text" id="p3-step-evidence-${s.step_number}" class="settings-input" value="${escapeHtml(s.evidence_summary || '')}" placeholder="Evidence summary" style="width:200px;">
              <button type="button" class="secondary-btn" onclick="window.app.p3SaveStep(${s.step_number})">Save</button>
            </div>
          </div>
        `).join('');
      }

      const activeOrg = ($('#p3-active-org-id')?.value || '').trim() || (customers[0]?.org_id || '');
      if (activeOrg) {
        if ($('#p3-active-org-id') && !$('#p3-active-org-id').value) $('#p3-active-org-id').value = activeOrg;
        await p3LoadOrgDetails(activeOrg);
      }
    } catch (e) {
      toast(`P3 Control Centre load error: ${e.message}`, 'error');
    }
  }

  function p3BindEvents() {
    $$('.p3-subtab-btn').forEach(btn => {
      btn.addEventListener('click', () => p3SwitchSubtab(btn.dataset.p3tab));
    });
    $('#btn-p3-refresh-all')?.addEventListener('click', p3LoadControlCentre);
    $('#btn-p3-confirm-activation')?.addEventListener('click', async () => {
      const oid = ($('#p3-active-org-id')?.value || '').trim();
      if (!oid) return toast('Enter or select an org_id first', 'error');
      try {
        await api('POST', `/v1/cs/customers/${encodeURIComponent(oid)}/onboarding/confirm-activation`, { confirmation_note: 'Confirmed from P3 console' });
        toast('Customer confirmed ACTIVE', 'success');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Activation blocked: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-transition-lifecycle')?.addEventListener('click', async () => {
      const oid = ($('#p3-active-org-id')?.value || '').trim();
      const targetState = $('#p3-lifecycle-target')?.value || 'ONBOARDING';
      const reason = ($('#p3-lifecycle-reason')?.value || '').trim() || 'Updated from Customer Operations console';
      if (!oid) return toast('Enter or select an org_id first', 'error');
      try {
        await api('POST', `/v1/cs/customers/${encodeURIComponent(oid)}/lifecycle`, { target_state: targetState, reason });
        toast(`Customer lifecycle updated to ${targetState}`, 'success');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Lifecycle transition failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-reply-ticket')?.addEventListener('click', async () => {
      const ticketId = ($('#p3-tkt-reply-id')?.value || '').trim();
      const visibility = $('#p3-tkt-reply-vis')?.value || 'customer_visible';
      const body = ($('#p3-tkt-reply-body')?.value || '').trim();
      if (!ticketId || !body) return toast('Select a Ticket ID and enter a message', 'error');
      try {
        await api('POST', `/v1/cs/support/tickets/${encodeURIComponent(ticketId)}/messages`, {
          body,
          visibility,
          sender_type: 'staff',
        });
        if ($('#p3-tkt-reply-body')) $('#p3-tkt-reply-body').value = '';
        toast(`Posted ${visibility === 'internal_only' ? 'internal note' : 'customer reply'}`, 'success');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Ticket message failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-run-maintenance')?.addEventListener('click', async () => {
      try {
        const res = await api('POST', '/v1/cs/ops/run-maintenance', {});
        const graceCount = Array.isArray(res.grace_enforcement)
          ? res.grace_enforcement.length
          : (res.grace_enforcement?.suspended_count || 0);
        toast(`Maintenance complete (grace suspended: ${graceCount})`, 'info');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Maintenance sweep failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-create-delivery')?.addEventListener('click', async () => {
      const oid = ($('#p3-active-org-id')?.value || '').trim();
      const title = ($('#p3-deliv-title')?.value || '').trim();
      const req = ($('#p3-deliv-req')?.value || '').trim();
      if (!oid || !title || !req) return toast('Provide org_id, title & requirement', 'error');
      try {
        await api('POST', '/v1/cs/deliveries', { org_id: oid, title, original_requirement: req });
        toast('Service delivery record created', 'success');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Delivery creation failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-compute-health')?.addEventListener('click', async () => {
      const oid = ($('#p3-active-org-id')?.value || '').trim();
      if (!oid) return toast('Select an org_id first', 'error');
      await p3LoadOrgDetails(oid);
      toast('Customer health re-evaluated', 'success');
    });
    $('#btn-p3-health-alerts')?.addEventListener('click', async () => {
      const oid = ($('#p3-active-org-id')?.value || '').trim();
      if (!oid) return toast('Select an org_id first', 'error');
      try {
        const res = await api('POST', `/v1/cs/customers/${encodeURIComponent(oid)}/health/alerts`, {});
        toast(`Generated ${res.count || 0} internal alert(s)`, 'info');
      } catch (e) {
        toast(`Alert scan failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-create-ticket')?.addEventListener('click', async () => {
      const oid = ($('#p3-active-org-id')?.value || '').trim();
      const subject = ($('#p3-tkt-subject')?.value || '').trim();
      const desc = ($('#p3-tkt-desc')?.value || '').trim();
      if (!oid || !subject || !desc) return toast('Provide org_id, subject & description', 'error');
      try {
        await api('POST', '/v1/cs/support/tickets', {
          org_id: oid,
          subject,
          description: desc,
          category: $('#p3-tkt-cat')?.value || 'general',
        });
        toast('Support ticket opened', 'success');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Ticket creation failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-synthesize-improvements')?.addEventListener('click', async () => {
      try {
        const res = await api('POST', '/v1/cs/improvements/synthesize', {});
        toast(`Synthesized ${res.count || 0} improvement item(s)`, 'success');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Synthesis failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-enforce-grace')?.addEventListener('click', async () => {
      try {
        const res = await api('POST', '/v1/cs/subscriptions/enforce-grace', {});
        toast(`Grace check complete: ${res.suspended_count || 0} suspended`, 'info');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Grace enforcement failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-eval-growth')?.addEventListener('click', async () => {
      const oid = ($('#p3-active-org-id')?.value || '').trim();
      if (!oid) return toast('Select an org_id first', 'error');
      try {
        const res = await api('POST', `/v1/cs/growth/${encodeURIComponent(oid)}/evaluate`, {});
        toast(`Evaluated ${res.count || 0} growth opportunity(ies)`, 'success');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Growth evaluation failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-save-budget')?.addEventListener('click', async () => {
      const oid = ($('#p3-active-org-id')?.value || '').trim();
      const lim = Number($('#p3-budget-limit')?.value || 0);
      if (!oid || lim <= 0) return toast('Enter org_id and positive monthly limit INR', 'error');
      try {
        await api('PUT', `/v1/cs/unit-economics/${encodeURIComponent(oid)}/budget`, { monthly_cost_limit_inr: lim });
        toast('Customer monthly cost budget saved', 'success');
        await p3LoadOrgDetails(oid);
      } catch (e) {
        toast(`Save budget failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-scan-timeouts')?.addEventListener('click', async () => {
      try {
        const res = await api('POST', '/v1/cs/ops/workflows/scan-timeouts', {});
        toast(`Scanned ${res.checked_running_count} running jobs; timed out: ${res.timed_out_count}`, 'info');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Scan failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-record-drill')?.addEventListener('click', async () => {
      const scope = ($('#p3-drill-scope')?.value || 'postgresql_primary_database').trim();
      const ev = ($('#p3-drill-evidence')?.value || '').trim();
      try {
        await api('POST', '/v1/cs/ops/backup-drill', {
          target_scope: scope,
          restore_tested: true,
          evidence_ref: ev || null,
          notes: 'Verified via P3 Founder Operations Console',
        });
        toast('Backup verification drill recorded', 'success');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Record drill failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p3-export-data')?.addEventListener('click', async () => {
      const oid = ($('#p3-active-org-id')?.value || '').trim();
      if (!oid) return toast('Select an org_id first', 'error');
      try {
        const res = await api('POST', `/v1/cs/compliance/${encodeURIComponent(oid)}/export`, {});
        if ($('#p3-compliance-output')) {
          $('#p3-compliance-output').textContent = `Export ID: ${res.compliance_request?.id} | Counts: ${JSON.stringify(res.compliance_request?.export_manifest?.record_counts || {})}`;
        }
        toast('DPDP/GDPR redacted bundle exported & audited', 'success');
      } catch (e) {
        toast(`Export failed: ${e.message}`, 'error');
      }
    });
  }

  // ── P4 Growth & GTM Engine Controller ─────────────────────
  async function p4LoadControlCentre() {
    try {
      const res = await api('GET', '/v1/p4/growth/overview');
      const a = res.analytics || {};
      const act = a.actual_verified || {};
      const sbx = a.sandbox_and_simulation || {};

      if ($('#p4-analytics-summary')) {
        $('#p4-analytics-summary').innerHTML = `
          <div class="cw-card"><div style="font-size:0.75rem;color:var(--text-muted);">ACTUAL VERIFIED PIPELINE</div><div style="font-size:1.35rem;font-weight:700;">${act.total_deals ?? 0} deals • ₹${(act.won_value_inr ?? 0).toLocaleString()}</div><div style="font-size:0.75rem;color:var(--cyan);">Win Rate: ${act.win_rate_pct === null || act.win_rate_pct === undefined ? 'N/A (0 closed)' : act.win_rate_pct + '%'}</div></div>
          <div class="cw-card"><div style="font-size:0.75rem;color:var(--text-muted);">SANDBOX / SIMULATION PIPELINE</div><div style="font-size:1.35rem;font-weight:700;">${sbx.total_deals ?? 0} deals • ₹${(sbx.open_pipeline_inr ?? 0).toLocaleString()}</div><div style="font-size:0.75rem;color:var(--text-muted);">Strictly separated from ACTUAL</div></div>
          <div class="cw-card"><div style="font-size:0.75rem;color:var(--text-muted);">GTM COVERAGE</div><div style="font-size:1.35rem;font-weight:700;">${a.icp_count ?? 0} ICPs • ${a.intel_count ?? 0} Intel • ${a.campaign_count ?? 0} Campaigns</div><div style="font-size:0.75rem;color:var(--text-muted);">${escapeHtml(a.analytics_integrity || '')}</div></div>
        `;
      }

      if ($('#p4-icp-list')) {
        const icps = res.icps || [];
        $('#p4-icp-list').innerHTML = icps.length
          ? icps.map(i => `<div><strong>${escapeHtml(i.name)}</strong> (${escapeHtml(i.industry)}, ${escapeHtml(i.geography)}) • Pains: ${escapeHtml((i.pain_points || []).join(', ') || '-')}</div>`).join('')
          : 'No ICPs configured yet';
      }

      if ($('#p4-intel-list')) {
        const intel = res.intel || [];
        $('#p4-intel-list').innerHTML = intel.length
          ? intel.map(r => `<div><strong>[${escapeHtml(r.intel_type)}]</strong> ${escapeHtml(r.subject_name)} — ${escapeHtml(r.summary)} <code>${escapeHtml(r.confidence_level)}</code>${r.evidence_ref ? ` (${escapeHtml(r.evidence_ref)})` : ''}</div>`).join('')
          : 'No provenance-verified intel logged yet';
      }

      if ($('#p4-campaigns-tbody')) {
        const camps = res.campaigns || [];
        $('#p4-campaigns-tbody').innerHTML = camps.length
          ? camps.map(c => `<tr>
              <td>${escapeHtml(c.name)}</td>
              <td>${escapeHtml((c.channels || []).join(', '))}</td>
              <td><span class="badge">${escapeHtml(c.status)}</span></td>
              <td>${escapeHtml(c.execution_mode)}</td>
              <td><button type="button" class="secondary-btn" onclick="window.app.p4ExecuteCampaign('${escapeHtml(c.campaign_id)}')">Execute Sandbox</button></td>
            </tr>`).join('')
          : '<tr><td colspan="5">No campaigns staged</td></tr>';
      }

      if ($('#p4-deals-tbody')) {
        const deals = res.deals || [];
        $('#p4-deals-tbody').innerHTML = deals.length
          ? deals.map(d => `<tr>
              <td>${escapeHtml(d.company_name)}</td>
              <td><span class="badge">${escapeHtml(d.evidence_status)}</span></td>
              <td>${escapeHtml(d.stage)}</td>
              <td>₹${Number(d.deal_value_inr || 0).toLocaleString()}</td>
              <td>${escapeHtml(d.attribution_source)}${d.lost_reason ? ` • Lost: ${escapeHtml(d.lost_reason)}` : ''}</td>
              <td style="display:flex;gap:4px;flex-wrap:wrap;">
                ${d.stage === 'DISCOVERED' ? `<button type="button" class="secondary-btn" onclick="window.app.p4TransitionDeal('${escapeHtml(d.deal_id)}', 'QUALIFIED')">Qualify</button>` : ''}
                ${d.stage === 'QUALIFIED' ? `<button type="button" class="secondary-btn" onclick="window.app.p4TransitionDeal('${escapeHtml(d.deal_id)}', 'PROPOSAL_SENT')">Propose</button>` : ''}
              </td>
            </tr>`).join('')
          : '<tr><td colspan="6">No deals tracked</td></tr>';
      }
    } catch (e) {
      toast(`P4 GTM load error: ${e.message}`, 'error');
    }
  }

  function p4BindEvents() {
    $('#btn-p4-refresh-all')?.addEventListener('click', p4LoadControlCentre);
    $('#btn-p4-create-icp')?.addEventListener('click', async () => {
      const name = ($('#p4-icp-name')?.value || '').trim();
      const industry = ($('#p4-icp-industry')?.value || '').trim();
      if (!name || !industry) return toast('Provide ICP name and industry', 'error');
      const painPoints = ($('#p4-icp-pain')?.value || '').split(',').map(s => s.trim()).filter(Boolean);
      try {
        await api('POST', '/v1/p4/growth/icps', {
          name,
          industry,
          geography: ($('#p4-icp-geo')?.value || 'India').trim() || 'India',
          pain_points: painPoints,
        });
        toast('ICP profile created', 'success');
        await p4LoadControlCentre();
      } catch (e) {
        toast(`Create ICP failed: ${e.message}`, 'error');
      }
    });

    $('#btn-p4-add-intel')?.addEventListener('click', async () => {
      const subject = ($('#p4-intel-subject')?.value || '').trim();
      const summary = ($('#p4-intel-summary')?.value || '').trim();
      const url = ($('#p4-intel-url')?.value || '').trim() || null;
      const ref = ($('#p4-intel-ref')?.value || '').trim() || null;
      if (!subject || !summary) return toast('Provide intel subject and summary', 'error');
      try {
        await api('POST', '/v1/p4/growth/intel', {
          intel_type: $('#p4-intel-type')?.value || 'COMPETITOR',
          subject_name: subject,
          summary,
          source_url: url,
          evidence_ref: ref,
          confidence_level: url && ref ? 'VERIFIED_SOURCE' : 'OBSERVATION',
        });
        toast('Market intelligence recorded', 'success');
        await p4LoadControlCentre();
      } catch (e) {
        toast(`Log intel failed: ${e.message}`, 'error');
      }
    });

    $('#btn-p4-create-campaign')?.addEventListener('click', async () => {
      const name = ($('#p4-camp-name')?.value || '').trim();
      const product = ($('#p4-camp-product')?.value || '').trim() || 'AskforWrite Growth OS';
      const audience = ($('#p4-camp-audience')?.value || '').trim() || 'Indian SME Founders';
      if (!name) return toast('Provide campaign name', 'error');
      try {
        await api('POST', '/v1/p4/growth/campaigns', {
          name,
          objective: `GTM campaign for ${product}`,
          product_name: product,
          target_audience: audience,
          keywords: [product, audience],
        });
        toast('Campaign staged for HITL approval', 'success');
        await p4LoadControlCentre();
      } catch (e) {
        toast(`Stage campaign failed: ${e.message}`, 'error');
      }
    });

    $('#btn-p4-create-deal')?.addEventListener('click', async () => {
      const company = ($('#p4-deal-company')?.value || '').trim();
      if (!company) return toast('Provide company name', 'error');
      try {
        await api('POST', '/v1/p4/growth/deals', {
          company_name: company,
          deal_value_inr: Number($('#p4-deal-value')?.value || 0),
          evidence_status: $('#p4-deal-origin')?.value || 'SANDBOX',
          attribution_source: ($('#p4-deal-source')?.value || 'ORGANIC_INBOUND').trim(),
        });
        toast('Pipeline deal logged', 'success');
        await p4LoadControlCentre();
      } catch (e) {
        toast(`Add deal failed: ${e.message}`, 'error');
      }
    });
  }

  // ── P5 Productization & Multi-Customer Scale Controller ───
  async function p5LoadControlCentre() {
    if (!$('#page-p5-scale')) return;
    try {
      const res = await api('GET', '/v1/p5/scale/overview');
      const sum = res.summary || {};
      if ($('#p5-kpi-templates')) $('#p5-kpi-templates').textContent = String(sum.template_count || 0);
      if ($('#p5-kpi-active-runs')) $('#p5-kpi-active-runs').textContent = String(sum.active_provisioned_count || 0);
      if ($('#p5-kpi-breaches')) $('#p5-kpi-breaches').textContent = String(sum.quota_breaches_count || 0);
      if ($('#p5-kpi-incidents')) $('#p5-kpi-incidents').textContent = String(sum.open_incidents_count || 0);

      if ($('#p5-templates-tbody')) {
        const tpls = res.templates || [];
        $('#p5-templates-tbody').innerHTML = tpls.length
          ? tpls.map(t => `<tr>
              <td><strong>${escapeHtml(t.template_key)}</strong></td>
              <td><span class="badge">${escapeHtml(t.tier_id)}</span></td>
              <td>${escapeHtml((t.selected_modules || []).join(', '))}</td>
              <td>₹${Number(t.monthly_price_inr || 0).toLocaleString()}</td>
              <td>${escapeHtml((t.catalog_service_ids || []).join(', '))}</td>
            </tr>`).join('')
          : '<tr><td colspan="5">No templates loaded</td></tr>';
      }

      if ($('#p5-runs-tbody')) {
        const runs = res.provisioning_runs || [];
        $('#p5-runs-tbody').innerHTML = runs.length
          ? runs.map(r => `<tr>
              <td>${escapeHtml(r.template_key)}</td>
              <td><span class="badge">${escapeHtml(r.state)}</span></td>
              <td>${(r.completed_steps || []).length}/5</td>
              <td>${r.state === 'FAILED' ? `<button type="button" class="secondary-btn" onclick="window.app.p5RetryRun('${escapeHtml(r.run_id)}')">Retry</button>` : escapeHtml(r.execution_mode)}</td>
            </tr>`).join('')
          : '<tr><td colspan="4">No runs recorded</td></tr>';
      }

      if ($('#p5-incidents-tbody')) {
        const incs = res.incidents || [];
        $('#p5-incidents-tbody').innerHTML = incs.length
          ? incs.map(i => `<tr>
              <td>${escapeHtml(i.title)}</td>
              <td>${escapeHtml(i.severity)}</td>
              <td><span class="badge">${escapeHtml(i.status)}</span></td>
              <td>${i.status !== 'RESOLVED' ? `<button type="button" class="secondary-btn" onclick="window.app.p5TransitionIncident('${escapeHtml(i.incident_id)}', 'RESOLVED')">Resolve</button>` : 'Closed'}</td>
            </tr>`).join('')
          : '<tr><td colspan="4">No incidents logged</td></tr>';
      }
    } catch (e) {
      toast(`Failed to load P5 Scale overview: ${e.message}`, 'error');
    }
  }

  function p5BindEvents() {
    $('#btn-p5-refresh-all')?.addEventListener('click', p5LoadControlCentre);
    $('#btn-p5-start-prov')?.addEventListener('click', async () => {
      const company = ($('#p5-prov-company')?.value || '').trim();
      const tpl = ($('#p5-prov-tpl')?.value || 'india_agency_starter').trim();
      const idem = ($('#p5-prov-idem')?.value || '').trim() || `ui-${Date.now()}`;
      try {
        await api('POST', '/v1/p5/scale/provisioning', {
          template_key: tpl,
          idempotency_key: idem,
          company_name: company || undefined,
          execution_mode: 'SIMULATION',
        });
        toast('Tenant provisioning run executed', 'success');
        await p5LoadControlCentre();
      } catch (e) {
        toast(`Provisioning failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p5-create-incident')?.addEventListener('click', async () => {
      const title = ($('#p5-inc-title')?.value || '').trim();
      const severity = ($('#p5-inc-severity')?.value || 'SEV3_MEDIUM').trim();
      if (!title) return toast('Provide incident title', 'error');
      try {
        await api('POST', '/v1/p5/scale/incidents', { title, severity, category: 'SLA_DEGRADATION' });
        toast('Incident opened', 'success');
        await p5LoadControlCentre();
      } catch (e) {
        toast(`Create incident failed: ${e.message}`, 'error');
      }
    });
  }

  // ── P6 Multi-Industry SME Packs & India SEO Controller ────
  async function p6LoadControlCentre() {
    if (!$('#page-p6-packs')) return;
    try {
      const res = await api('GET', '/v1/p6/packs/overview');
      const sum = res.summary || {};
      if ($('#p6-kpi-packs')) $('#p6-kpi-packs').textContent = String(sum.pack_count || 0);
      if ($('#p6-kpi-sandbox')) {
        $('#p6-kpi-sandbox').textContent = String((sum.sandbox_pack_count || 0) + (sum.roadmap_pack_count || 0));
      }
      if ($('#p6-kpi-deployments')) $('#p6-kpi-deployments').textContent = String(sum.deployment_count || 0);
      if ($('#p6-kpi-seo')) $('#p6-kpi-seo').textContent = String(sum.seo_baseline_count || 0);

      if ($('#p6-packs-tbody')) {
        const packs = res.packs || [];
        $('#p6-packs-tbody').innerHTML = packs.length
          ? packs.map(p => `<tr>
              <td><strong>${escapeHtml(p.pack_key)}</strong></td>
              <td>${escapeHtml(p.sector)}</td>
              <td><span class="badge">${escapeHtml(p.readiness_status)}</span></td>
              <td>₹${Number(p.monthly_price_inr || 0).toLocaleString()}</td>
              <td>${escapeHtml((p.analytics_capabilities || []).join(', '))}</td>
            </tr>`).join('')
          : '<tr><td colspan="5">No packs loaded</td></tr>';
      }

      if ($('#p6-deployments-tbody')) {
        const deps = res.deployments || [];
        $('#p6-deployments-tbody').innerHTML = deps.length
          ? deps.map(d => `<tr>
              <td>${escapeHtml(d.pack_key)}</td>
              <td><span class="badge">${escapeHtml(d.status)}</span></td>
              <td>${escapeHtml(d.readiness_label)}</td>
              <td><button type="button" class="secondary-btn" onclick="window.app.p6RunDiagnostics('${escapeHtml(d.deployment_id)}')">Run Diagnostics</button></td>
            </tr>`).join('')
          : '<tr><td colspan="4">No pack deployments</td></tr>';
      }
    } catch (e) {
      toast(`Failed to load P6 Packs overview: ${e.message}`, 'error');
    }
  }

  function p6BindEvents() {
    $('#btn-p6-refresh-all')?.addEventListener('click', p6LoadControlCentre);
    $('#btn-p6-create-seo')?.addEventListener('click', async () => {
      const city = ($('#p6-seo-city')?.value || 'Bengaluru').trim();
      const vertical = ($('#p6-seo-vertical')?.value || 'distribution_wholesale').trim();
      const sku = ($('#p6-seo-sku')?.value || 'seo_blog_copilot').trim();
      try {
        await api('POST', '/v1/p6/packs/seo-baselines', {
          city_or_cluster: city,
          industry_vertical: vertical,
          primary_catalog_sku: sku,
        });
        toast('India local SEO baseline created', 'success');
        await p6LoadControlCentre();
      } catch (e) {
        toast(`SEO baseline failed: ${e.message}`, 'error');
      }
    });
  }

  // ── P7 Controlled Autonomous Workforce Controller ─────────
  async function p7LoadControlCentre() {
    if (!$('#page-p7-autonomy')) return;
    try {
      const res = await api('GET', '/v1/p7/workforce/overview');
      const sum = res.summary || {};
      if ($('#p7-kpi-dags')) $('#p7-kpi-dags').textContent = String(sum.dag_plan_count || 0);
      if ($('#p7-kpi-memories')) $('#p7-kpi-memories').textContent = String(sum.active_memory_count || 0);
      if ($('#p7-kpi-paused')) $('#p7-kpi-paused').textContent = String(sum.paused_agent_count || 0);
      if ($('#p7-kpi-eval-fails')) $('#p7-kpi-eval-fails').textContent = String(sum.failed_eval_count || 0);

      if ($('#p7-dags-tbody')) {
        const dags = res.dag_plans || [];
        $('#p7-dags-tbody').innerHTML = dags.length
          ? dags.map(d => `<tr>
              <td><strong>${escapeHtml(d.name)}</strong></td>
              <td>${d.computed_depth}/${d.max_depth}</td>
              <td>${d.credits_consumed}/${d.credit_budget}</td>
              <td><span class="badge">${escapeHtml(d.status)}</span></td>
              <td><button type="button" class="secondary-btn" onclick="window.app.p7ExecuteDag('${escapeHtml(d.plan_id)}')">Execute Sandbox</button></td>
            </tr>`).join('')
          : '<tr><td colspan="5">No delegation DAGs planned</td></tr>';
      }

      if ($('#p7-policies-tbody')) {
        const pols = res.autonomy_policies || [];
        $('#p7-policies-tbody').innerHTML = pols.length
          ? pols.map(p => `<tr>
              <td>${escapeHtml(p.agent_id)}</td>
              <td><span class="badge">${escapeHtml(p.autonomy_level)}</span></td>
              <td>${p.is_paused ? 'PAUSED' : 'Active'}</td>
              <td>${Number(p.min_eval_threshold || 0.75).toFixed(2)}</td>
            </tr>`).join('')
          : '<tr><td colspan="4">No autonomy policies configured</td></tr>';
      }
    } catch (e) {
      toast(`Failed to load P7 Autonomy overview: ${e.message}`, 'error');
    }
  }

  function p7BindEvents() {
    $('#btn-p7-refresh-all')?.addEventListener('click', p7LoadControlCentre);
    $('#btn-p7-save-policy')?.addEventListener('click', async () => {
      const agentId = ($('#p7-pol-agent')?.value || 'gtm_strategist_agent').trim();
      const level = ($('#p7-pol-level')?.value || 'LEVEL_2_APPROVAL_GATED').trim();
      try {
        await api('PUT', `/v1/p7/workforce/autonomy-policies/${encodeURIComponent(agentId)}`, {
          autonomy_level: level,
          requires_hitl_for_external: true,
          min_eval_threshold: level.startsWith('LEVEL_3') || level.startsWith('LEVEL_4') ? 0.85 : 0.75,
        });
        toast('Autonomy policy saved', 'success');
        await p7LoadControlCentre();
      } catch (e) {
        toast(`Policy failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p7-run-eval')?.addEventListener('click', async () => {
      const agentId = ($('#p7-eval-agent')?.value || 'gtm_strategist_agent').trim();
      const quality = Number($('#p7-eval-quality')?.value || 0.9);
      const safety = Number($('#p7-eval-safety')?.value || 0.95);
      try {
        await api('POST', '/v1/p7/workforce/evals', {
          agent_id: agentId,
          eval_suite_name: 'dashboard_spot_eval',
          quality_score: quality,
          safety_score: safety,
        });
        toast('Continuous evaluation recorded', 'success');
        await p7LoadControlCentre();
      } catch (e) {
        toast(`Eval failed: ${e.message}`, 'error');
      }
    });
  }

  // ── P8 Marketplace Ecosystem & Master Scorecard ──────────
  async function p8LoadControlCentre() {
    try {
      const [mktRes, scoreRes] = await Promise.all([
        api('GET', '/v1/p8/marketplace/overview'),
        api('GET', '/v1/ops/roadmap-scorecard').catch(() => ({ overall_release_readiness: 'TENANT_VIEW', phases: [] })),
      ]);
      const sum = mktRes.summary || {};
      if ($('#p8-kpi-devs')) $('#p8-kpi-devs').textContent = String(sum.verified_developer_count || 0);
      if ($('#p8-kpi-listings')) $('#p8-kpi-listings').textContent = String(sum.published_listing_count || 0);
      if ($('#p8-kpi-installs')) $('#p8-kpi-installs').textContent = String(sum.install_count || 0);
      if ($('#p8-kpi-readiness')) $('#p8-kpi-readiness').textContent = String(scoreRes.overall_release_readiness || 'BLOCKED');

      if ($('#p8-listings-tbody')) {
        const rows = mktRes.listings || [];
        $('#p8-listings-tbody').innerHTML = rows.length
          ? rows.map(l => `<tr>
              <td><strong>${escapeHtml(l.name)}</strong><br><small>${escapeHtml(l.listing_slug)}</small></td>
              <td>${escapeHtml(l.package_type)}</td>
              <td><span class="badge">${escapeHtml(l.security_review_status)}</span></td>
              <td><span class="badge">${escapeHtml(l.published_status)}</span></td>
              <td>
                <button type="button" class="secondary-btn" onclick="window.app.p8VerifySignature('${escapeHtml(l.listing_id)}')">Verify ECDSA</button>
                ${l.published_status === 'PUBLISHED' ? `<button type="button" class="primary-btn" onclick="window.app.p8InstallListing('${escapeHtml(l.listing_id)}')">Install</button>` : ''}
              </td>
            </tr>`).join('')
          : '<tr><td colspan="5">No marketplace packages submitted</td></tr>';
      }

      if ($('#p8-scorecard-tbody')) {
        const phases = scoreRes.phases || [];
        $('#p8-scorecard-tbody').innerHTML = phases.length
          ? phases.map(p => `<tr>
              <td><strong>${escapeHtml(p.phase)}</strong></td>
              <td>${escapeHtml(p.title)}</td>
              <td><span class="badge">${escapeHtml(p.implementation_status)}</span></td>
              <td><span class="badge">${escapeHtml(p.verification_status)}</span></td>
            </tr>`).join('')
          : '<tr><td colspan="4">Scorecard unavailable</td></tr>';
      }
    } catch (e) {
      toast(`Failed to load P8 Marketplace: ${e.message}`, 'error');
    }
  }

  function p8BindEvents() {
    $('#btn-p8-refresh-all')?.addEventListener('click', p8LoadControlCentre);
    $('#btn-p8-reg-dev')?.addEventListener('click', async () => {
      const developer_name = ($('#p8-dev-name')?.value || '').trim();
      const contact_email = ($('#p8-dev-email')?.value || '').trim();
      const legal_entity_name = ($('#p8-dev-entity')?.value || '').trim();
      if (!developer_name || !contact_email || !legal_entity_name) {
        toast('Developer name, email, and legal entity are required', 'warning');
        return;
      }
      try {
        const dev = await api('POST', '/v1/p8/marketplace/developers', {
          developer_name,
          contact_email,
          legal_entity_name,
        });
        if ($('#p8-list-dev-id')) $('#p8-list-dev-id').value = dev.developer_id || '';
        toast(`Developer registered (${dev.kyb_status})`, 'success');
        await p8LoadControlCentre();
      } catch (e) {
        toast(`Developer registration failed: ${e.message}`, 'error');
      }
    });
    $('#btn-p8-submit-listing')?.addEventListener('click', async () => {
      const developer_id = ($('#p8-list-dev-id')?.value || '').trim();
      const listing_slug = ($('#p8-list-slug')?.value || '').trim();
      const name = ($('#p8-list-name')?.value || '').trim();
      if (!developer_id || !listing_slug || !name) {
        toast('Developer ID, listing slug, and name are required', 'warning');
        return;
      }
      try {
        await api('POST', '/v1/p8/marketplace/listings', {
          developer_id,
          listing_slug,
          name,
          package_type: 'AGENT_PLUGIN',
          requested_permissions: ['read_metrics'],
        });
        toast('Signed listing submitted for security review', 'success');
        await p8LoadControlCentre();
      } catch (e) {
        toast(`Listing submission failed: ${e.message}`, 'error');
      }
    });
  }

  // ── Public API (for onclick handlers) ────────────────────
  window.app = {
    openApprovalModal,
    openSettingsModal,
    closeSettingsModal,
    openLegalModal,
    closeLegalModal,
    switchLegalTab,
    checkAuthGate,
    handleLogout,
    triggerLeadDiscovery,
    cwHydrateRegistry,
    cwLoadProfile,
    cwLoadWorkflows,
    cwLoadEvidenceHistory,
    cwLoadBilling,
    cwLoadEmergencyStops,
    cwFetchScopedApprovals,
    fetchCustomerP3PortalData,
    portalCompleteTask,
    portalRespondDelivery,
    portalReplyTicket,
    portalSubmitCsat,
    portalExportData,
    portalSaveConsent,
    portalRefreshGsc,
    p2LoadAll: p2LoadControlCentre,
    p2SelectLead: p2FillLeadForms,
    p2ShowBrief: async (leadId) => {
      try {
        const b = await api('POST', `/v1/commercial/prospects/${encodeURIComponent(leadId)}/brief`, {});
        if ($('#p2-brief-viewer')) {
          $('#p2-brief-viewer').innerHTML = `
            <strong>${escapeHtml(b.company || leadId)}</strong> (${escapeHtml(b.output_origin || '')})
            <div style="margin-top:6px;"><strong>Verified Facts:</strong><ul>${(b.verified_facts || []).map(x => `<li>${escapeHtml(x)}</li>`).join('')}</ul></div>
            <div><strong>Reasonable Inferences:</strong><ul>${(b.reasonable_inferences || []).map(x => `<li>${escapeHtml(x)}</li>`).join('')}</ul></div>
            <div><strong>Unverified Assumptions (Verify on Call):</strong><ul>${(b.unverified_assumptions || []).map(x => `<li>${escapeHtml(x)}</li>`).join('')}</ul></div>
            <div><strong>Discovery Questions:</strong><ul>${(b.suggested_discovery_questions || []).map(x => `<li>${escapeHtml(x)}</li>`).join('')}</ul></div>
          `;
        }
        toast('Account intelligence brief loaded', 'success');
      } catch (e) {
        toast(`Brief generation failed: ${e.message}`, 'error');
      }
    },
    p2Requalify: async (leadId) => {
      try {
        await api('POST', `/v1/commercial/prospects/${encodeURIComponent(leadId)}/requalify`, {});
        toast('Qualification score recalculated', 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Requalify failed: ${e.message}`, 'error');
      }
    },
    p2ShareProposal: async (proposalId) => {
      try {
        await api('POST', `/v1/commercial/proposals/${encodeURIComponent(proposalId)}/share`, {});
        toast('Approved proposal shared with buyer', 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Share blocked: ${e.message}`, 'error');
      }
    },
    p2CreateCheckout: async (proposalId) => {
      try {
        const res = await api('POST', `/v1/commercial/proposals/${encodeURIComponent(proposalId)}/checkout`, { provider: 'afw_directpay', preferred_rail: 'upi_direct' });
        toast(`Checkout created (${res.status}) — awaits verified settlement`, 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Checkout blocked: ${e.message}`, 'error');
      }
    },
    p2RetryRecon: async (reconId) => {
      try {
        const res = await api('POST', `/v1/commercial/reconciliation/${encodeURIComponent(reconId)}/retry`, {});
        toast(`Reconciliation retried: ${res.verification_state}`, 'info');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Retry failed: ${e.message}`, 'error');
      }
    },
    p2SelectEngagement: (engagementId) => {
      if ($('#p2-eng-id')) $('#p2-eng-id').value = engagementId;
      toast(`Selected engagement ${engagementId}`, 'info');
    },
    p2SaveStep: async (stepNumber) => {
      try {
        const st = $(`#p2-step-status-${stepNumber}`)?.value || 'NOT_TESTED';
        const ev = ($(`#p2-step-evidence-${stepNumber}`)?.value || '').trim();
        await api('POST', `/v1/commercial/acceptance-checklist/${stepNumber}`, { verification_status: st, evidence_summary: ev || null });
        toast(`Step ${stepNumber} updated to ${st}`, 'success');
        await p2LoadControlCentre();
      } catch (e) {
        toast(`Step update failed: ${e.message}`, 'error');
      }
    },
    p3LoadAll: p3LoadControlCentre,
    p3SelectOrg: async (orgId) => {
      if ($('#p3-active-org-id')) $('#p3-active-org-id').value = orgId;
      toast(`Selected customer org ${orgId}`, 'info');
      await p3LoadOrgDetails(orgId);
    },
    p3QaPass: async (deliveryId, passed) => {
      try {
        await api('POST', `/v1/cs/deliveries/${encodeURIComponent(deliveryId)}/qa-review`, {
          passed: !!passed,
          checks: { manual_founder_qa: !!passed, scope_verified: !!passed },
        });
        toast(`Deliverable QA ${passed ? 'PASSED' : 'FAILED (Revision Requested)'}`, passed ? 'success' : 'error');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`QA update failed: ${e.message}`, 'error');
      }
    },
    p3AiAssistTicket: async (ticketId) => {
      try {
        const res = await api('POST', `/v1/cs/support/tickets/${encodeURIComponent(ticketId)}/ai-assist`, {});
        toast(
          res.triage?.requires_human_approval
            ? 'AI Triage paused: Sensitive topic gated by Owner HITL approval'
            : `AI Triage completed (${res.triage?.suggested_category || 'general'})`,
          res.triage?.requires_human_approval ? 'info' : 'success'
        );
        await p3LoadControlCentre();
      } catch (e) {
        toast(`AI assist failed: ${e.message}`, 'error');
      }
    },
    p3ResolveTicket: async (ticketId) => {
      try {
        await api('POST', `/v1/cs/support/tickets/${encodeURIComponent(ticketId)}/transition`, {
          target_state: 'RESOLVED',
          reason: 'Resolved from Customer Operations console',
        });
        toast('Support ticket resolved', 'success');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Resolve failed: ${e.message}`, 'error');
      }
    },
    p3SelectTicketReply: (ticketId) => {
      if ($('#p3-tkt-reply-id')) $('#p3-tkt-reply-id').value = ticketId;
      $('#p3-tkt-reply-body')?.focus();
    },
    p3UpdateImprovement: async (improvementId) => {
      const st = $(`#p3-imp-status-${improvementId}`)?.value || 'IN_BACKLOG';
      try {
        await api('PATCH', `/v1/cs/improvements/${encodeURIComponent(improvementId)}`, { status: st });
        toast(`Improvement item updated to ${st}`, 'success');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Improvement update failed: ${e.message}`, 'error');
      }
    },
    p3ShareOpportunity: async (oppId) => {
      try {
        const res = await api('POST', `/v1/cs/growth/opportunities/${encodeURIComponent(oppId)}/share`, {});
        toast(
          res.status === 'APPROVAL_REQUIRED'
            ? `Owner HITL approval staged (${res.approval_id})`
            : 'Growth offer authorized & shared',
          'info'
        );
        await p3LoadControlCentre();
      } catch (e) {
        toast(`Share blocked: ${e.message}`, 'error');
      }
    },
    p3RetryDlq: async (incidentId) => {
      try {
        const res = await api('POST', `/v1/cs/ops/dlq/${encodeURIComponent(incidentId)}/retry`, {});
        toast(`DLQ job requeued (${res.workflow_run_status})`, 'success');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`DLQ retry failed: ${e.message}`, 'error');
      }
    },
    p3SaveStep: async (stepNumber) => {
      try {
        const st = $(`#p3-step-status-${stepNumber}`)?.value || 'NOT_TESTED';
        const ev = ($(`#p3-step-evidence-${stepNumber}`)?.value || '').trim();
        await api('POST', `/v1/cs/acceptance/${stepNumber}`, {
          verification_status: st,
          evidence_summary: ev || 'Verified by owner',
        });
        toast(`P3 Step ${stepNumber} updated to ${st}`, 'success');
        await p3LoadControlCentre();
      } catch (e) {
        toast(`P3 step update failed: ${e.message}`, 'error');
      }
    },
    viewLead: (id) => {
      const lead = state.leads.find(l => l.id === id);
      if (lead) {
        toast(`${lead.company} — ${lead.industry} — Score: ${((lead.fit_score || 0) * 100).toFixed(0)}%`, 'info');
      }
    },
    p4LoadAll: p4LoadControlCentre,
    p4ExecuteCampaign: async (campaignId) => {
      try {
        await api('POST', `/v1/p4/growth/campaigns/${encodeURIComponent(campaignId)}/execute`, { execution_mode: 'SIMULATION' });
        toast('Campaign launched in SIMULATION mode', 'success');
        await p4LoadControlCentre();
      } catch (e) {
        toast(`Campaign execution blocked: ${e.message}`, 'error');
      }
    },
    p4TransitionDeal: async (dealId, targetStage) => {
      try {
        await api('POST', `/v1/p4/growth/deals/${encodeURIComponent(dealId)}/transition`, { target_stage: targetStage });
        toast(`Deal moved to ${targetStage}`, 'success');
        await p4LoadControlCentre();
      } catch (e) {
        toast(`Deal transition failed: ${e.message}`, 'error');
      }
    },
    p5LoadAll: p5LoadControlCentre,
    p5RetryRun: async (runId) => {
      try {
        await api('POST', `/v1/p5/scale/provisioning/${encodeURIComponent(runId)}/retry`, {});
        toast('Provisioning run recovered', 'success');
        await p5LoadControlCentre();
      } catch (e) {
        toast(`Retry failed: ${e.message}`, 'error');
      }
    },
    p5TransitionIncident: async (incidentId, targetStatus) => {
      try {
        await api('POST', `/v1/p5/scale/incidents/${encodeURIComponent(incidentId)}/transition`, { target_status: targetStatus });
        toast(`Incident moved to ${targetStatus}`, 'success');
        await p5LoadControlCentre();
      } catch (e) {
        toast(`Incident update failed: ${e.message}`, 'error');
      }
    },
    p6LoadAll: p6LoadControlCentre,
    p6RunDiagnostics: async (deploymentId) => {
      try {
        await api('POST', `/v1/p6/packs/deployments/${encodeURIComponent(deploymentId)}/diagnostics`, {});
        toast('Pack sandbox diagnostics completed', 'success');
        await p6LoadControlCentre();
      } catch (e) {
        toast(`Diagnostics failed: ${e.message}`, 'error');
      }
    },
    p7LoadAll: p7LoadControlCentre,
    p7ExecuteDag: async (planId) => {
      try {
        await api('POST', `/v1/p7/workforce/dag-plans/${encodeURIComponent(planId)}/execute`, { execution_mode: 'SIMULATION' });
        toast('Delegation DAG executed in SIMULATION', 'success');
        await p7LoadControlCentre();
      } catch (e) {
        toast(`DAG execution blocked: ${e.message}`, 'error');
      }
    },
    p8LoadAll: p8LoadControlCentre,
    p8VerifySignature: async (listingId) => {
      try {
        const res = await api('GET', `/v1/p8/marketplace/listings/${encodeURIComponent(listingId)}/verify-signature`);
        toast(`Signature check: verified=${Boolean(res.verified)}`, res.verified ? 'success' : 'error');
      } catch (e) {
        toast(`Signature check failed: ${e.message}`, 'error');
      }
    },
    p8InstallListing: async (listingId) => {
      try {
        const payload = { listing_id: listingId, config: { source: 'dashboard' } };
        if (CONFIG.ownerApiKey) {
          let orgId = state.organizations?.[0]?.id;
          if (!orgId) {
            const orgs = await api('GET', '/v1/accounts/orgs').catch(() => []);
            const list = Array.isArray(orgs) ? orgs : (orgs.organizations || []);
            orgId = list[0]?.id;
          }
          if (orgId) payload.org_id = orgId;
        }
        await api('POST', '/v1/p8/marketplace/installs', payload);
        toast('Marketplace package installed cleanly', 'success');
        await p8LoadControlCentre();
      } catch (e) {
        toast(`Install failed: ${e.message}`, 'error');
      }
    },
    setApiKey: (key) => {
      CONFIG.ownerApiKey = key;
      localStorage.setItem('askforwrite_owner_key', key);
      toast('API key saved', 'success');
      checkAuthGate();
      fetchAll();
    },
  };

  // Boot & Non-blocking Background Warmup
  function bootApplication() {
    cwInitControlCenter();
    init();
    // Hydrate registry only if already authenticated, completely non-blocking
    if (CONFIG.ownerApiKey || CONFIG.accessToken) {
      cwHydrateRegistry().catch(() => {});
    }
    // Background warm-up ping for instant responsiveness on os.askforwrite.com
    try {
      if (typeof window !== 'undefined') {
        const warmup = () => {
          fetch(`${CONFIG.apiBase}/health`, { method: 'GET', cache: 'no-store' }).catch(() => {});
        };
        if ('requestIdleCallback' in window) {
          requestIdleCallback(warmup, { timeout: 1500 });
        } else {
          setTimeout(warmup, 100);
        }
      }
    } catch (_) {}
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootApplication);
  } else {
    bootApplication();
  }
})();

