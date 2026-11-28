/* FieldGuard Offline-First Mobile PWA Client (IndexedDB Queue + Camera Capture + Geo-OTP) */
(function () {
  const DB_NAME = 'afw_fieldguard_offline_queue';
  const STORE_NAME = 'pending_events';
  let authToken = localStorage.getItem('afw_fg_token') || '';
  let currentUserId = localStorage.getItem('afw_fg_uid') || '';

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/mobile/sw.js').catch(() => {});
  }

  function openQueueDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE_NAME)) {
          req.result.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function enqueueOffline(endpoint, payload) {
    const db = await openQueueDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      tx.objectStore(STORE_NAME).add({ endpoint, payload, queuedAt: new Date().toISOString() });
      tx.oncomplete = () => { refreshQueueBadge(); resolve(true); };
      tx.onerror = () => reject(tx.error);
    });
  }

  async function listQueue() {
    const db = await openQueueDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const req = tx.objectStore(STORE_NAME).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }

  async function removeQueued(id) {
    const db = await openQueueDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      tx.objectStore(STORE_NAME).delete(id);
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => reject(tx.error);
    });
  }

  async function refreshQueueBadge() {
    try {
      const items = await listQueue();
      const badge = document.getElementById('queue-badge');
      const syncLog = document.getElementById('sync-log');
      if (badge) {
        badge.style.display = items.length ? 'inline-block' : 'none';
        badge.textContent = `${items.length} queued`;
      }
      if (syncLog) {
        syncLog.textContent = items.length
          ? items.map((x) => `[${x.queuedAt}] ${x.endpoint}`).join('\n')
          : 'Queue empty. All events synced.';
      }
    } catch (_) {}
  }

  async function apiPost(endpoint, payload, queueIfOffline = true) {
    if (!navigator.onLine && queueIfOffline) {
      await enqueueOffline(endpoint, payload);
      return { queued_offline: true, endpoint };
    }
    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify(payload),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail?.message || data.detail || `HTTP ${resp.status}`);
      return data;
    } catch (err) {
      if (!navigator.onLine && queueIfOffline) {
        await enqueueOffline(endpoint, payload);
        return { queued_offline: true, endpoint };
      }
      throw err;
    }
  }

  async function flushOfflineQueue() {
    const items = await listQueue();
    let synced = 0;
    for (const item of items) {
      try {
        await apiPost(item.endpoint, item.payload, false);
        await removeQueued(item.id);
        synced += 1;
      } catch (_) {
        break;
      }
    }
    await refreshQueueBadge();
    return synced;
  }

  function readFileDataUri(inputEl) {
    return new Promise((resolve) => {
      const file = inputEl && inputEl.files && inputEl.files[0];
      if (!file) return resolve(null);
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(file);
    });
  }

  function getLiveCoords() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error('Geolocation unavailable'));
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy_meters: pos.coords.accuracy || 10.0,
        }),
        (err) => reject(new Error(err.message || 'GPS permission denied')),
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
      );
    });
  }

  function updateNetPill() {
    const pill = document.getElementById('net-pill');
    if (!pill) return;
    if (navigator.onLine) {
      pill.textContent = 'ONLINE';
      pill.className = 'pill online';
      flushOfflineQueue();
    } else {
      pill.textContent = 'OFFLINE';
      pill.className = 'pill offline';
    }
  }

  window.addEventListener('online', updateNetPill);
  window.addEventListener('offline', updateNetPill);

  document.querySelectorAll('nav.bottom-bar button').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('nav.bottom-bar button').forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
      btn.classList.add('active');
      const target = document.getElementById(btn.dataset.tab);
      if (target) target.classList.add('active');
    });
  });

  document.getElementById('btn-fg-login')?.addEventListener('click', async () => {
    const email = document.getElementById('fg-email').value.trim();
    const password = document.getElementById('fg-pass').value;
    const box = document.getElementById('auth-status');
    box.style.display = 'block';
    try {
      const data = await apiPost('/v1/auth/login', { email, password }, false);
      authToken = data.access_token || '';
      currentUserId = data.user?.id || '';
      localStorage.setItem('afw_fg_token', authToken);
      localStorage.setItem('afw_fg_uid', currentUserId);
      box.textContent = `Signed in as ${email}. Offline sync ready.`;
    } catch (e) {
      box.textContent = `Login failed: ${e.message}`;
    }
  });

  async function recordAttendance(checkType) {
    const log = document.getElementById('att-log');
    log.textContent = 'Acquiring high-accuracy GPS fix...';
    try {
      const gps = await getLiveCoords();
      const res = await apiPost('/v1/mobile/attendance/check-in', {
        ...gps,
        check_type: checkType,
        client_timestamp: new Date().toISOString(),
        mock_provider_detected: false,
      });
      log.textContent = JSON.stringify(res, null, 2);
    } catch (e) {
      log.textContent = `Error: ${e.message}`;
    }
  }

  document.getElementById('btn-checkin')?.addEventListener('click', () => recordAttendance('check_in'));
  document.getElementById('btn-checkout')?.addEventListener('click', () => recordAttendance('check_out'));

  document.getElementById('btn-request-otp')?.addEventListener('click', async () => {
    const log = document.getElementById('visit-log');
    try {
      const res = await apiPost('/v1/field-force/visits/otp/issue', {
        task_id: document.getElementById('visit-task-id').value.trim(),
        client_contact: document.getElementById('visit-client-contact').value.trim() || null,
        delivery_channel: 'EMAIL',
      }, false);
      log.textContent = JSON.stringify(res, null, 2);
    } catch (e) {
      log.textContent = `OTP error: ${e.message}`;
    }
  });

  document.getElementById('btn-submit-visit')?.addEventListener('click', async () => {
    const log = document.getElementById('visit-log');
    try {
      const gps = await getLiveCoords();
      const photoUri = await readFileDataUri(document.getElementById('visit-photo'));
      const res = await apiPost('/v1/field-force/visits/verify', {
        task_id: document.getElementById('visit-task-id').value.trim(),
        user_id: currentUserId,
        ...gps,
        geo_otp_code: document.getElementById('visit-otp').value.trim() || null,
        photo_evidence_base64_or_url: photoUri,
        verify_scene: Boolean(photoUri),
      });
      log.textContent = JSON.stringify(res, null, 2);
    } catch (e) {
      log.textContent = `Visit error: ${e.message}`;
    }
  });

  document.getElementById('btn-submit-claim')?.addEventListener('click', async () => {
    const log = document.getElementById('claim-log');
    try {
      const gps = await getLiveCoords();
      const photoUri = await readFileDataUri(document.getElementById('claim-receipt-photo'));
      const today = new Date().toISOString().slice(0, 10);
      const nowIso = new Date().toISOString();
      const amount = parseFloat(document.getElementById('claim-amount').value || '0');
      const receipts = amount > 0 && photoUri ? [{
        category: document.getElementById('claim-category').value,
        amount,
        merchant_name: document.getElementById('claim-merchant').value.trim() || null,
        receipt_date: today,
        receipt_base64_or_hash: photoUri,
      }] : [];
      const res = await apiPost('/v1/field-force/conveyance/submit', {
        user_id: currentUserId,
        claim_date: today,
        transport_mode: document.getElementById('claim-mode').value,
        tour_plan_id: document.getElementById('claim-tour-id').value.trim() || null,
        gps_breadcrumbs: [
          { latitude: gps.latitude, longitude: gps.longitude, timestamp: nowIso },
          { latitude: gps.latitude, longitude: gps.longitude, timestamp: nowIso },
        ],
        receipts,
      });
      log.textContent = JSON.stringify(res, null, 2);
    } catch (e) {
      log.textContent = `Claim error: ${e.message}`;
    }
  });

  document.getElementById('btn-flush-queue')?.addEventListener('click', async () => {
    const n = await flushOfflineQueue();
    const log = document.getElementById('sync-log');
    log.textContent = `Synced ${n} queued event(s).`;
  });

  updateNetPill();
  refreshQueueBadge();
})();
