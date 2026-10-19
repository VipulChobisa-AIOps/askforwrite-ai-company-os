/**
 * AskforWrite AI Company OS — Service Worker
 * Version: 1.0.0
 * Provides fast asset caching, offline shell fallback, and background sync.
 */

const CACHE_NAME = 'afw-os-shell-v1';

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

  // Bypass dynamic API requests (always network-first for live data)
  if (url.pathname.startsWith('/v1/') || url.pathname.startsWith('/api/') || url.pathname.startsWith('/docs') || url.pathname.startsWith('/openapi.json')) {
    event.respondWith(
      fetch(request).catch(() => {
        return new Response(
          JSON.stringify({
            error: 'Offline Mode',
            message: 'Network connection is currently unavailable. Cached OS telemetry is displayed.',
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

  // Navigation requests: Network-first, fallback to cached App Shell
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response && response.status === 200) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, responseClone));
          }
          return response;
        })
        .catch(async () => {
          const cachedResponse = await caches.match('/dashboard/index.html') || await caches.match('/dashboard/');
          if (cachedResponse) {
            return cachedResponse;
          }
          return new Response(
            '<!DOCTYPE html><html><body style="background:#07090e;color:#fff;font-family:sans-serif;text-align:center;padding:50px;"><h1>AFW OS — Offline</h1><p>You are currently offline. Please reconnect to the internet.</p></body></html>',
            { headers: { 'Content-Type': 'text/html' } }
          );
        })
    );
    return;
  }

  // Dashboard static assets: Stale-While-Revalidate
  if (url.pathname.startsWith('/dashboard/')) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        const fetchPromise = fetch(request)
          .then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200) {
              const responseToCache = networkResponse.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, responseToCache));
            }
            return networkResponse;
          })
          .catch(() => cachedResponse);

        return cachedResponse || fetchPromise;
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
