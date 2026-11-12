/**
 * AskforWrite AI Company OS — Service Worker
 * Version: 3.5.0 (P0 Truthfulness & Fail-Closed Release)
 * Provides network-first asset freshness, cache-busting on release, and offline fallback.
 */

const CACHE_NAME = 'afw-os-shell-v3.5-truthfulness';
const BUILD_VERSION = 'v3.5-p0-truthfulness';

const STATIC_ASSETS = [
  '/dashboard/',
  '/dashboard/index.html',
  '/dashboard/dashboard.css',
  '/dashboard/dashboard.js',
  '/dashboard/manifest.json',
  '/dashboard/icon-192.svg',
  '/dashboard/icon-512.svg'
];

// ── Installation: Pre-cache App Shell ──────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        return cache.addAll(STATIC_ASSETS);
      })
      .then(() => self.skipWaiting())
  );
});

// ── Activation: Clean Old Caches & Claim Clients ───────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// ── Fetch: Strategic Caching & Offline Fallback ─────────────────
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Only handle HTTP/HTTPS GET requests
  if (request.method !== 'GET') {
    return;
  }

  // Bypass dynamic API & health requests (always network-only for live data; never serve cached auth/health)
  if (url.pathname.startsWith('/v1/') || url.pathname.startsWith('/api/') || url.pathname === '/health' || url.pathname.startsWith('/docs') || url.pathname.startsWith('/openapi.json')) {
    event.respondWith(
      fetch(request).catch(() => {
        return new Response(
          JSON.stringify({
            error: 'Offline Mode',
            status: 'BLOCKED',
            capability_status: 'BLOCKED',
            message: 'Network connection is currently unavailable. Live API action blocked (no false success).',
            offline: true
          }),
          {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
          }
        );
      })
    );
    return;
  }

  // Navigation & Dashboard static assets: Network-first so updated Login Gate & JS are never served stale from cache
  if (request.mode === 'navigate' || url.pathname.startsWith('/dashboard/')) {
    event.respondWith(
      fetch(request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, responseClone));
          }
          return networkResponse;
        })
        .catch(async () => {
          const cachedResponse = await caches.match(request) || await caches.match('/dashboard/index.html') || await caches.match('/dashboard/');
          if (cachedResponse) {
            return cachedResponse;
          }
          return new Response(
            '<!DOCTYPE html><html><body style="background:#07090e;color:#fff;font-family:sans-serif;text-align:center;padding:50px;"><h1>AFW OS — Offline (BLOCKED)</h1><p>You are currently offline. Live workspace requires an active connection.</p></body></html>',
            { headers: { 'Content-Type': 'text/html' } }
          );
        })
    );
    return;
  }

  // Other GET requests: Cache-first with network fallback
  event.respondWith(
    caches.match(request).then((response) => {
      return response || fetch(request).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, responseToCache));
        }
        return networkResponse;
      });
    })
  );
});
