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
    ownerApiKey: 'eOIoBi4YXOUfl1I0UMLm10SiiapNv9BWyTKAfTCafrD22g_VIFl9p_je4fMI5Wb6',
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
    };
    $('#page-title').textContent = titles[pageName] || pageName;

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

  async function fetchAll() {
    await fetchDashboardData();
    await Promise.allSettled([
      fetchLeads(),
      fetchApprovals(),
      fetchOutreach(),
      fetchOrganizations(),
      fetchFieldForceData(),
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
      window.open('https://razorpay.me/@askforwrite', '_blank');
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
                <a href="https://razorpay.me/@askforwrite?amount=999900&notes_package=growth_all_in_one" target="_blank" class="primary-btn" style="display:inline-block;padding:6px 12px;font-size:0.75rem;text-decoration:none">
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
    const baseInput = $('#settings-api-base');
    const intervalSelect = $('#settings-refresh-interval');

    if (keyInput) keyInput.value = CONFIG.ownerApiKey || '';
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
    const base = ($('#settings-api-base')?.value || '').trim() || window.location.origin;
    const interval = parseInt($('#settings-refresh-interval')?.value || '10000', 10);

    CONFIG.ownerApiKey = key;
    CONFIG.apiBase = base;
    CONFIG.refreshInterval = isNaN(interval) ? 10000 : interval;

    localStorage.setItem('askforwrite_owner_key', key);
    localStorage.setItem('askforwrite_api_base', base);
    localStorage.setItem('askforwrite_refresh_interval', String(CONFIG.refreshInterval));

    resetRefreshTimer();
    closeSettingsModal();
    toast('Settings saved & applied', 'success');
    fetchAll();
  }

  function resetSettings() {
    localStorage.removeItem('askforwrite_owner_key');
    localStorage.removeItem('askforwrite_api_base');
    localStorage.removeItem('askforwrite_refresh_interval');

    CONFIG.ownerApiKey = 'eOIoBi4YXOUfl1I0UMLm10SiiapNv9BWyTKAfTCafrD22g_VIFl9p_je4fMI5Wb6';
    CONFIG.apiBase = window.location.origin;
    CONFIG.refreshInterval = 10000;

    const keyInput = $('#settings-api-key');
    const baseInput = $('#settings-api-base');
    const intervalSelect = $('#settings-refresh-interval');

    if (keyInput) keyInput.value = CONFIG.ownerApiKey;
    if (baseInput) baseInput.value = CONFIG.apiBase;
    if (intervalSelect) intervalSelect.value = String(CONFIG.refreshInterval);

    resetRefreshTimer();
    toast('Settings reset to defaults', 'info');
    fetchAll();
  }

  // ── API Key & Settings Setup ─────────────────────────────
  function initApiKey() {
    // Read persisted settings from localStorage
    const storedKey = localStorage.getItem('askforwrite_owner_key');
    if (storedKey !== null) {
      CONFIG.ownerApiKey = storedKey;
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
    const initialPage = window.location.hash.replace('#', '') || 'dashboard';
    navigateTo(initialPage);

    // Initial load
    await fetchAll();

    // Auto-refresh timer
    resetRefreshTimer();
  }

  // ── Public API (for onclick handlers) ────────────────────
  window.app = {
    openApprovalModal,
    openSettingsModal,
    closeSettingsModal,
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
