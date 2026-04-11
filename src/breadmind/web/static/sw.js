/**
 * BreadMind Service Worker
 * Provides offline support, caching strategies, and push notifications.
 *
 * Cache manifest targets the SDUI (Preact + HTM) frontend shipped under
 * /static/sdui/ and /static/vendor/. Legacy chat/settings assets live in
 * static_legacy/ and are no longer served at /static/ paths.
 */

const CACHE_VERSION = 'v2-sdui';
const SHELL_CACHE = `breadmind-shell-${CACHE_VERSION}`;
const STATIC_CACHE = `breadmind-static-${CACHE_VERSION}`;
const API_CACHE = `breadmind-api-${CACHE_VERSION}`;

const SHELL_ASSETS = [
  '/',
  '/index.html',
  '/static/offline.html',
  '/static/manifest.json',
  // Stylesheet
  '/static/css/sdui.css',
  // SDUI runtime
  '/static/sdui/main.js',
  '/static/sdui/renderer.js',
  '/static/sdui/ws.js',
  '/static/sdui/patch.js',
  '/static/sdui/components/index.js',
  '/static/sdui/components/layout.js',
  '/static/sdui/components/display.js',
  '/static/sdui/components/data.js',
  '/static/sdui/components/interactive.js',
  '/static/sdui/components/flow.js',
  // Vendor ES modules
  '/static/vendor/preact.module.js',
  '/static/vendor/preact-hooks.module.js',
  '/static/vendor/htm.module.js',
  // Icons referenced by manifest.json
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-maskable-192.png',
  '/static/icons/icon-maskable-512.png',
  '/static/icons/apple-touch-icon.png',
];

const ALL_CACHES = [SHELL_CACHE, STATIC_CACHE, API_CACHE];

// ── INSTALL ──
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => Promise.all(
        SHELL_ASSETS.map((asset) =>
          cache.add(asset).catch((err) => {
            // Don't fail the whole install if one optional asset is missing.
            console.warn('[SW] Failed to cache', asset, err);
          })
        )
      ))
      .then(() => self.skipWaiting())
  );
});

// ── ACTIVATE ──
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => !ALL_CACHES.includes(key))
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
      .then(() => {
        // Notify all clients about update
        return self.clients.matchAll({ type: 'window' });
      })
      .then((clients) => {
        clients.forEach((client) => {
          client.postMessage({ type: 'SW_UPDATED' });
        });
      })
  );
});

// ── FETCH ──
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip WebSocket requests
  if (url.protocol === 'ws:' || url.protocol === 'wss:') {
    return;
  }

  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }

  // Navigation requests: network-first -> cache -> offline.html
  if (request.mode === 'navigate') {
    event.respondWith(networkFirstNavigation(request));
    return;
  }

  // API requests: network-first with timeout -> cache
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirstWithTimeout(request, API_CACHE, 5000));
    return;
  }

  // Static assets: cache-first -> network (with background update)
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirstWithUpdate(request, STATIC_CACHE));
    return;
  }

  // Default: network-first
  event.respondWith(networkFirstWithTimeout(request, SHELL_CACHE, 5000));
});

// ── PUSH ──
self.addEventListener('push', (event) => {
  let data = { title: 'BreadMind', body: 'New notification', url: '/' };
  if (event.data) {
    try {
      data = Object.assign(data, event.data.json());
    } catch (e) {
      data.body = event.data.text();
    }
  }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/icons/icon-192.png',
      badge: '/static/icons/icon-192.png',
      data: { url: data.url || '/' },
      vibrate: [200, 100, 200],
      tag: data.tag || 'breadmind-notification',
      renotify: true,
    })
  );
});

// ── NOTIFICATION CLICK ──
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then((clients) => {
        // Focus existing window if available
        for (const client of clients) {
          if (client.url.includes(self.location.origin) && 'focus' in client) {
            client.navigate(targetUrl);
            return client.focus();
          }
        }
        // Otherwise open new window
        return self.clients.openWindow(targetUrl);
      })
  );
});

// ── Caching Strategies ──

async function networkFirstNavigation(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    const cached = await caches.match(request);
    if (cached) return cached;
    return caches.match('/static/offline.html');
  }
}

async function networkFirstWithTimeout(request, cacheName, timeout) {
  try {
    const response = await fetchWithTimeout(request, timeout);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: 'offline' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

async function cacheFirstWithUpdate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);

  // Background update
  const fetchPromise = fetch(request)
    .then((response) => {
      if (response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  return cached || fetchPromise;
}

function fetchWithTimeout(request, timeout) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), timeout);
    fetch(request)
      .then((response) => {
        clearTimeout(timer);
        resolve(response);
      })
      .catch((err) => {
        clearTimeout(timer);
        reject(err);
      });
  });
}
