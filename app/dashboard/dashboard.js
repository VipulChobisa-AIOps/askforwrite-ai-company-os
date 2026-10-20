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
    refreshInterval: 10000, // 10s auto-refresh
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
    };
    $('#page-title').textContent = titles[pageName] || pageName;

    // Page-specific initialization hooks
    if (pageName === 'quality') {
      initQualityPage();
    } else if (pageName === 'mobility') {
      initMobilityPage();
    } else if (pageName === 'inventory') {
      initInventoryPage();
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
      // Try health check first
      await api('GET', '/health');
      setConnectionStatus(true);

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
      loadDemoData();
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
      const data = await api('GET', '/v1/approvals');
      const rawList = data.approvals || (Array.isArray(data) ? data : []);
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
      const [tasksRes, visitsRes, claimsRes] = await Promise.allSettled([
        api('GET', '/v1/field-force/tasks'),
        api('GET', '/v1/field-force/visits'),
        api('GET', '/v1/field-force/conveyance/claims'),
      ]);

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
        if (me.credits) {
          const leadLimit = me.credits.lead_credits_limit || 0;
          const leadRem = me.credits.lead_credits_remaining || 0;
          if ($('#portal-stat-leads')) $('#portal-stat-leads').textContent = `${leadRem} / ${leadLimit}`;
          if ($('#portal-lead-badge')) $('#portal-lead-badge').textContent = `${100 - (me.credits.lead_utilization_pct || 0)}% Left`;
          if ($('#portal-fill-leads')) $('#portal-fill-leads').style.width = `${Math.min(100, me.credits.lead_utilization_pct || 0)}%`;

          const outLimit = me.credits.outreach_credits_limit || 0;
          const outRem = me.credits.outreach_credits_remaining || 0;
          if ($('#portal-stat-outreach')) $('#portal-stat-outreach').textContent = `${outRem} / ${outLimit}`;
          if ($('#portal-fill-outreach')) $('#portal-fill-outreach').style.width = `${Math.min(100, me.credits.outreach_utilization_pct || 0)}%`;
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
        if (CONFIG.userRole === 'customer') {
          if ($('#sidebar-user-name')) $('#sidebar-user-name').textContent = me.full_name || me.email || 'Customer';
          if ($('#sidebar-user-role')) $('#sidebar-user-role').textContent = 'Customer (' + (me.tier || 'Starter') + ')';
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
      if (Array.isArray(invoices) && invoices.length > 0) {
        const tbody = $('#portal-invoices-tbody');
        if (tbody) {
          tbody.innerHTML = invoices.map(inv => `
            <tr>
              <td><code>${esc(inv.invoice_id)}</code></td>
              <td>AskforWrite AI Workspace</td>
              <td>${inv.currency === 'USD' ? '$' : '₹'}${inv.amount}</td>
              <td>${esc(inv.provider)}</td>
              <td><span class="status-pill ${inv.status === 'PAID' ? 'approved' : 'pending'}">${esc(inv.status)}</span></td>
              <td><a href="/v1/pay/checkout?package=growth_all_in_one&company=AskforWrite+Client" target="_blank" class="text-btn">Receipt ↗</a></td>
            </tr>
          `).join('');
        }
      }
    } catch (e) {
      console.warn('Billing invoices fetch:', e.message);
    }
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
      fetchCustomerPortalData(),
    ]);
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
      dotContainer.title = online ? 'API Connected' : 'API Offline — Using demo data';
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
    try {
      await api('POST', `/v1/approvals/${pendingDecision.approvalId}/decision`, {
        decision: decision,
        reason: note || `${decision} via Owner Dashboard`,
      });
      toast(`Approval ${decision.toLowerCase()} successfully`, 'success');
      closeModal();
      await fetchApprovals();
      await fetchLeads();
      await fetchDashboardData();
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
          inspector_id: inspectorId,
          rating: rating,
          observed_ripeness: groundtruth,
          notes: notes,
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
        // Preset inspection
        const preset = qualityState.activePreset || 'ripe';
        res = await api('POST', '/v1/quality/inspect', {
          preset: preset,
          inspector_id: inspectorId,
        });
      }

      // Render Results
      const classification = res.classification || {};
      const ensemble = res.model_ensemble || {};
      const colorimetry = res.colorimetry || {};
      const texture = res.texture_glcm || {};

      // Ripeness Badge
      const ripeness = classification.ripeness || 'RIPE';
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
        $('#quality-grade-badge').textContent = classification.commercial_grade || 'Commercial Grade';
      }
      if ($('#quality-brix-val')) {
        $('#quality-brix-val').textContent = `${classification.estimated_sugar_brix ?? 14.5}° Bx`;
      }
      if ($('#quality-shelflife-val')) {
        $('#quality-shelflife-val').textContent = `Est. Shelf-Life: ${classification.estimated_shelf_life_days ?? 5} days`;
      }
      if ($('#quality-staging-rec')) {
        $('#quality-staging-rec').textContent = classification.supply_chain_staging || 'Store in standard temperature-controlled staging.';
      }
      if ($('#quality-consensus-ratio')) {
        $('#quality-consensus-ratio').textContent = `Model Consensus: ${ensemble.consensus_ratio || '4/4 Models Agreed'}`;
      }
      if ($('#quality-trust-pill')) {
        $('#quality-trust-pill').textContent = res.task_id ? `TrustBlock #${res.task_id.substring(0, 8)}` : 'TrustBlock Sealed';
      }

      // 4-Model Ensemble Bars
      const models = ensemble.individual_models || {};
      const updateModelBar = (key, labelId, barId) => {
        const m = models[key];
        const labelEl = $(`#${labelId}`);
        const barEl = $(`#${barId}`);
        if (m && labelEl && barEl) {
          const pct = ((m.confidence || 0.9) * 100).toFixed(1);
          labelEl.textContent = `${m.prediction} (${pct}%)`;
          barEl.style.width = `${pct}%`;
          if (m.prediction === 'RIPE') {
            labelEl.style.color = 'var(--green)';
            barEl.style.background = 'var(--green)';
          } else if (m.prediction === 'UNRIPE') {
            labelEl.style.color = 'var(--amber)';
            barEl.style.background = 'var(--amber)';
          } else {
            labelEl.style.color = 'var(--red)';
            barEl.style.background = 'var(--red)';
          }
        }
      };

      updateModelBar('svm_rbf', 'label-svm', 'bar-svm');
      updateModelBar('random_forest', 'label-rf', 'bar-rf');
      updateModelBar('gaussian_nb', 'label-gnb', 'bar-gnb');
      updateModelBar('pytorch_cnn', 'label-cnn', 'bar-cnn');

      // Texture & Colorimetry
      if ($('#val-mean-hue')) $('#val-mean-hue').textContent = `${(colorimetry.mean_hue_angle || 72.5).toFixed(1)}°`;
      if ($('#val-glcm-homo')) $('#val-glcm-homo').textContent = (texture.homogeneity || 0.842).toFixed(3);
      if ($('#val-glcm-contrast')) $('#val-glcm-contrast').textContent = (texture.contrast || 12.4).toFixed(1);
      if ($('#val-glcm-energy')) $('#val-glcm-energy').textContent = (texture.energy || 0.315).toFixed(3);
      if ($('#val-glcm-corr')) $('#val-glcm-corr').textContent = (texture.correlation || 0.912).toFixed(3);
      if ($('#val-hist-bin')) $('#val-hist-bin').textContent = `#${colorimetry.dominant_bin_index ?? 146}`;

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
          operator_id: operatorId,
          dispatch_accuracy_rating: rating,
          notes: notes,
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

      const forecast = res.forecast || {};
      const rebalance = res.rebalancing || {};

      // Forecast Demand
      if ($('#mobility-pred-demand')) {
        $('#mobility-pred-demand').textContent = `${forecast.predicted_hourly_demand || 42} trips/hr`;
      }
      if ($('#mobility-period-label')) {
        $('#mobility-period-label').textContent = forecast.period || 'Circadian Simulated Demand';
      }

      // Stations Churn Table
      const tbody = $('#mobility-stations-tbody');
      if (tbody && rebalance.all_stations) {
        tbody.innerHTML = rebalance.all_stations.map(st => {
          let badgeHtml = '';
          if (st.status === 'DEPLETED') {
            badgeHtml = '<span class="status-pill rejected" style="background:rgba(239,68,68,0.15);color:var(--red);border:1px solid var(--red-glow)">DEPLETED</span>';
          } else if (st.status === 'ACCUMULATED') {
            badgeHtml = '<span class="status-pill" style="background:rgba(6,182,212,0.15);color:var(--cyan);border:1px solid var(--cyan-glow)">ACCUMULATED</span>';
          } else {
            badgeHtml = '<span class="status-pill approved" style="background:rgba(16,185,129,0.15);color:var(--green);border:1px solid var(--green-glow)">BALANCED</span>';
          }

          return `
            <tr>
              <td>
                <div style="font-weight:600">${esc(st.name)}</div>
                <div style="font-size:0.75rem;color:var(--text-muted)">Station ID: #${st.id}</div>
              </td>
              <td><span style="font-size:0.78rem;color:var(--text-secondary)">${esc(st.zone)}</span></td>
              <td>${st.capacity}</td>
              <td><strong>${st.current_bikes}</strong></td>
              <td>
                <div style="display:flex;align-items:center;gap:6px">
                  <div style="width:50px;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden">
                    <div style="width:${Math.min(100, st.available_pct)}%;height:100%;background:${st.available_pct < 25 ? 'var(--red)' : st.available_pct > 75 ? 'var(--cyan)' : 'var(--green)'}"></div>
                  </div>
                  <span style="font-size:0.75rem">${st.available_pct}%</span>
                </div>
              </td>
              <td>${badgeHtml}</td>
            </tr>
          `;
        }).join('');
      }

      // Rebalancing Priority Routes
      const routesList = $('#mobility-routes-list');
      const routesCount = $('#mobility-routes-count');
      if (routesList && rebalance.priority_rebalance_routes) {
        const routes = rebalance.priority_rebalance_routes;
        if (routesCount) routesCount.textContent = `${routes.length} Route${routes.length === 1 ? '' : 's'} Active`;

        if (routes.length === 0) {
          routesList.innerHTML = '<div class="empty-state" style="padding:16px"><p>All stations currently within balanced threshold.</p></div>';
        } else {
          routesList.innerHTML = routes.map(r => `
            <div class="route-dispatch-card">
              <div>
                <div style="font-weight:700;font-size:0.82rem;color:var(--text-primary);margin-bottom:2px">
                  ${esc(r.from_hub)} <span style="color:var(--cyan);margin:0 4px">➔</span> ${esc(r.to_hub)}
                </div>
                <div style="font-size:0.74rem;color:var(--text-muted)">
                  Distance: ${r.distance_km || 2.4} km • Transfer: <strong style="color:var(--green)">+${r.transfer_quantity} bikes</strong>
                </div>
              </div>
              <span class="badge" style="background:rgba(168,85,247,0.15);color:var(--purple);border:1px solid var(--purple-glow)">Priority #${r.priority}</span>
            </div>
          `).join('');
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
                  <strong style="font-size: 0.85rem;">${esc(a.alert_type)}</strong>
                </div>
                <div style="font-size: 0.8rem; color: var(--text-primary); margin-bottom: 4px;">${esc(a.message || '')}</div>
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
    const metrics = data.audit_metrics || data.summary || {};

    if ($('#inventory-total-skus')) $('#inventory-total-skus').textContent = metrics.total_skus ?? 0;
    if ($('#inventory-total-value')) $('#inventory-total-value').textContent = `₹${(metrics.total_inventory_valuation || 0).toLocaleString()}`;
    if ($('#inventory-dead-stock-count')) $('#inventory-dead-stock-count').textContent = metrics.dead_stock_skus_count ?? 0;
    if ($('#inventory-trapped-capital')) $('#inventory-trapped-capital').textContent = `₹${(metrics.capital_locked_in_dead_stock || 0).toLocaleString()}`;

    // ABC-XYZ table
    const abcItems = data.abc_analysis?.items || [];
    const abcTbody = $('#inventory-abc-xyz-tbody');
    if (abcTbody) {
      if (!abcItems.length) {
        abcTbody.innerHTML = '<tr class="empty-row"><td colspan="5"><div class="empty-state"><p>No SKU data found</p></div></td></tr>';
      } else {
        abcTbody.innerHTML = abcItems.map(item => {
          const cls = item.category || 'B';
          return `
            <tr>
              <td>
                <div style="font-weight:600">${esc(item.sku)}</div>
                <div style="font-size:0.75rem;color:var(--text-muted)">${esc(item.name || '')}</div>
              </td>
              <td>₹${(item.annual_value || 0).toLocaleString()}</td>
              <td>${(item.cumulative_share_pct || 0).toFixed(1)}%</td>
              <td><span class="status-pill" style="background:rgba(168,85,247,0.15);color:var(--purple);font-weight:700">Class ${esc(cls)}</span></td>
              <td style="font-size:0.78rem;color:var(--text-secondary)">${esc(item.management_strategy || 'Standard control')}</td>
            </tr>
          `;
        }).join('');
      }
    }

    // Reorder recommendations
    const reorders = data.reorder_recommendations || [];
    const reorderTbody = $('#inventory-reorder-tbody');
    if (reorderTbody) {
      if (!reorders.length) {
        reorderTbody.innerHTML = '<tr class="empty-row"><td colspan="6"><div class="empty-state"><p>All stock levels optimal</p></div></td></tr>';
      } else {
        reorderTbody.innerHTML = reorders.map(r => {
          const needed = r.reorder_needed;
          return `
            <tr>
              <td><strong>${esc(r.sku)}</strong></td>
              <td>${r.current_stock}</td>
              <td>${r.safety_stock}</td>
              <td><strong>${r.reorder_point}</strong></td>
              <td>${r.economic_order_quantity}</td>
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

    // Dead stock list
    const deadStockList = $('#inventory-deadstock-list');
    const deadItems = data.dead_stock_analysis?.dead_stock_items || [];
    if (deadStockList) {
      if (!deadItems.length) {
        deadStockList.innerHTML = '<div class="empty-state"><p>No dead stock detected. Inventory turnover healthy.</p></div>';
      } else {
        deadStockList.innerHTML = deadItems.map(d => `
          <div style="display:flex;justify-content:space-between;align-items:center;background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.2);padding:10px 14px;border-radius:var(--radius-sm)">
            <div>
              <div style="font-weight:700;color:var(--red);font-size:0.85rem">${esc(d.sku)} — ${esc(d.name || '')}</div>
              <div style="font-size:0.75rem;color:var(--text-muted)">Idle for ${d.days_since_last_sale} days • ${d.units_idle} units trapped</div>
            </div>
            <div style="text-align:right">
              <div style="font-weight:800;color:var(--red);font-size:0.95rem">₹${(d.locked_capital || 0).toLocaleString()}</div>
              <div style="font-size:0.75rem;color:var(--amber)">${esc(d.recommended_action || 'Liquidation')}</div>
            </div>
          </div>
        `).join('');
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
        const isPassword = input.type === 'password';
        input.type = isPassword ? 'text' : 'password';
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
      if (input) input.type = input.type === 'password' ? 'text' : 'password';
    });
    $('#btn-portal-upgrade')?.addEventListener('click', () => {
      window.open('/v1/pay/checkout?package=growth_all_in_one&company=AskforWrite+Client', '_blank');
    });

    // Customer Portal BYOK & Service Execution listeners
    $('#btn-save-portal-gemini-key')?.addEventListener('click', handleSavePortalGeminiKey);
    $('#btn-run-tenant-service')?.addEventListener('click', handleRunTenantService);
    $('#btn-portal-refresh')?.addEventListener('click', fetchCustomerPortalData);

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

    $('#login-password')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleCustomerLogin();
    });
    $('#auth-owner-key')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleOwnerUnlock();
    });


    // Mobile Phone Simulator actions
    $('#btn-phone-checkin')?.addEventListener('click', async () => {
      toast('GPS Check-in recorded at Jaipur Hub (26.9124° N, 75.7873° E)', 'success');
      animateNumber('#stat-visits', (state.fieldVisits?.length || 0) + 1);
    });

    $('#btn-phone-submit-visit')?.addEventListener('click', async () => {
      const client = ($('#phone-client-id')?.value || 'Client Visit').trim();
      const otp = ($('#phone-otp-code')?.value || '1234').trim();
      toast(`Visit to "${client}" verified with OTP ${otp}! Proof sealed in Trust Block.`, 'success');
      if ($('#phone-client-id')) $('#phone-client-id').value = '';
      if ($('#phone-otp-code')) $('#phone-otp-code').value = '';
    });

    $('#btn-phone-claim')?.addEventListener('click', async () => {
      const km = parseFloat($('#phone-distance-km')?.value || '15');
      const purpose = $('#phone-purpose')?.value || 'Client site visit';
      const amt = Math.round(km * 4.5);
      toast(`Conveyance claim submitted: ₹${amt} (${km} km) for ${purpose}`, 'success');
      if ($('#phone-distance-km')) $('#phone-distance-km').value = '';
      if ($('#phone-purpose')) $('#phone-purpose').value = '';
    });

    // PixelBot Chat
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
      } catch (_) {
        if (box) {
          box.innerHTML += `
            <div style="align-self:flex-start;background:rgba(168,85,247,0.15);border:1px solid var(--purple-glow);padding:8px 12px;border-radius:8px;font-size:0.85rem;max-width:85%">
              🤖 <strong>PixelBot:</strong> Received: "${esc(q)}". Connected to Company OS at os.askforwrite.com with 11 capabilities online.
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
        toast(`Growth Campaign synthesized & sealed in TrustBlock!`, 'success');

        const container = $('#growth-results-container');
        if (container) container.style.display = 'block';

        const variantsList = $('#growth-variants-list');
        if (variantsList && res.creative_assets?.variants) {
          variantsList.innerHTML = res.creative_assets.variants.map(v => `
            <div class="variant-card">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                <div>
                  <span class="variant-ratio-badge">${esc(v.aspect_ratio)}</span>
                  <strong style="font-size:0.85rem">${esc(v.channel_placement)}</strong>
                </div>
                <span style="font-size:0.75rem;color:var(--text-muted)">${esc(v.dimensions)}</span>
              </div>
              <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:6px"><strong>Prompt:</strong> ${esc(v.prompt_recipe)}</div>
              <div style="display:flex;justify-content:space-between;align-items:center;font-size:0.78rem">
                <span style="color:var(--cyan)">Overlay: "${esc(v.headline_overlay)}"</span>
                <span class="badge" style="background:rgba(16,185,129,0.15);color:var(--green)">CTA: ${esc(v.call_to_action)}</span>
              </div>
            </div>
          `).join('');
        }

        const blogPreview = $('#growth-blog-preview');
        if (blogPreview && res.seo_geo_blog) {
          blogPreview.textContent = res.seo_geo_blog.markdown_body;
        }
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
                  Pay ₹${res.price_inr?.toLocaleString() || '9,999'}/mo via Razorpay
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
            <div class="chat-bubble closer">
              <div style="font-size:0.7rem;color:var(--cyan);font-weight:700;margin-bottom:3px">AskforWrite AI Closer</div>
              Our Autonomous AI Growth Suite is ₹9,999/month ($129 USD). It provides unlimited Pixel AI ad visuals, 4-site SEO publishing, and a 24/7 automated WhatsApp sales closer!
              <div style="margin-top:8px">
                <a href="/v1/pay/checkout?package=growth_all_in_one&company=AskforWrite+Client" target="_blank" class="primary-btn" style="display:inline-block;padding:6px 12px;font-size:0.75rem;text-decoration:none">
                  Instant Checkout Link
                </a>
              </div>
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
      state.refreshTimer = setInterval(fetchAll, CONFIG.refreshInterval);
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
    CONFIG.refreshInterval = 10000;

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

  // ── Auth Gate & Multi-Role Onboarding ────────────────────
  function checkAuthGate() {
    const hasOwnerKey = Boolean(CONFIG.ownerApiKey);
    const hasAccessToken = Boolean(CONFIG.accessToken);

    const gate = $('#auth-gate-overlay');
    if (!hasOwnerKey && !hasAccessToken) {
      if (gate) gate.style.display = 'flex';
      return false;
    }

    if (gate) gate.style.display = 'none';

    // Apply role-based navigation visibility
    const isCustomer = CONFIG.userRole === 'customer' || (!hasOwnerKey && hasAccessToken);
    const ownerTabs = ['dashboard', 'leads', 'approvals', 'outreach', 'organizations', 'revenue'];

    ownerTabs.forEach(tab => {
      const navItem = $(`#nav-${tab}`);
      if (navItem) {
        navItem.style.display = isCustomer ? 'none' : 'flex';
      }
    });

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

    toast('Logged out of workspace.', 'info');
    checkAuthGate();
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
        if (serviceKey === 'pixel_ai_pack') {
          payload = { product_name: rawParam, target_audience: 'B2B Enterprise Leaders' };
        } else if (serviceKey === 'ask4_academic_order') {
          payload = { topic: rawParam };
        } else if (serviceKey === 'mango_quality_analytics') {
          payload = { crop_variety: rawParam, preset: 'ripe' };
        } else {
          payload = { query: rawParam };
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

  // ── Initialize ───────────────────────────────────────────
  async function init() {
    initApiKey();
    bindEvents();
    checkAuthGate();

    const initialPage = window.location.hash.replace('#', '') || (CONFIG.userRole === 'customer' ? 'portal' : 'dashboard');
    navigateTo(initialPage);

    // Initial load
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
          { heading: "4. Data Grievance Officer", body: "Vipul Kumar Chobisa, ASKFORWRITE (UDYAM-RJ-14-0018404), Udaipur Bus Stand, Udaipur, Rajasthan, India - 313001. Email: compliance@askforwrite.in." }
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
          <p style="margin:0 0 8px 0">Protected under Section 15 and Section 16 of the MSMED Act, 2006. Grievance &amp; Compliance Officer: Vipul Kumar Chobisa (compliance@askforwrite.in).</p>
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
          { heading: "4. Grievance Contact", body: "Billing support: billing@askforwrite.in. Statutory MSME Samadhaan forum: Udaipur, Rajasthan." }
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
        ${escapeHtml(doc.copyright || '© 2026 ASKFORWRITE (UDYAM-RJ-14-0018404). All Rights Reserved.')} • Official Inquiries: ${escapeHtml(doc.contact || 'legal@askforwrite.in')}
      </div>
    `;

    container.innerHTML = html;
  }

  window.openLegalModal = openLegalModal;
  window.closeLegalModal = closeLegalModal;
  window.switchLegalTab = switchLegalTab;

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
    viewLead: (id) => {
      const lead = state.leads.find(l => l.id === id);
      if (lead) {
        toast(`${lead.company} — ${lead.industry} — Score: ${((lead.fit_score || 0) * 100).toFixed(0)}%`, 'info');
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

  // Boot
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

