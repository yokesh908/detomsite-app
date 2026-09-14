const CACHE_NAME = 'vendor-app-v4';

self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('fetch', event => {
  // Never intercept API calls — only cache static assets so the app shell
  // works offline. This avoids stale order data.
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/api/')) return;

  event.respondWith(
    caches.match(event.request).then(cached => {
      const fetchPromise = fetch(event.request).then(response => {
        if (response && response.status === 200 && url.origin === self.location.origin) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => cached);
      return cached || fetchPromise;
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    Promise.all([
      // Take control of open tabs immediately so push works right away.
      self.clients.claim(),
      caches.keys().then(names => Promise.all(names.filter(n => n !== CACHE_NAME).map(n => caches.delete(n)))),
    ])
  );
});

// ─── Push notifications: a new order from a student ───
self.addEventListener('push', event => {
  let payload = {
    title: 'Vendor App',
    body: 'New update',
    tag: 'vendor-alert',
    url: '/mobile',
    icon: '/mobile/icon-192.png',
  };
  try {
    const data = event.data ? event.data.json() : null;
    if (data) payload = { ...payload, ...data };
  } catch (e) {
    // Plain-text payload (older format) — show it as-is.
    if (event.data) payload.body = event.data.text();
  }

  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      tag: payload.tag,
      icon: payload.icon,
      badge: '/mobile/icon-192.png',
      vibrate: [200, 100, 200],
      data: { url: payload.url || '/mobile' },
    })
  );
});

// Tap the notification → open the vendor app (or focus it if already open).
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/mobile';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      for (const client of windowClients) {
        if ('focus' in client) return client.focus();
      }
      return clients.openWindow(targetUrl);
    })
  );
});
