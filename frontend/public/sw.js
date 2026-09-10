"""
Service worker for offline support and caching
"""
const CACHE_NAME = 'detomsite-v2';
const urlsToCache = [
  '/',
  '/index.html',
  '/assets/main.css',
  '/assets/main.js',
];

self.addEventListener('install', event => {
  // Activate immediately so a newly deployed bundle replaces the old one
  // instead of lingering until every tab is closed.
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(urlsToCache);
    })
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(response => {
      if (response) {
        return response;
      }

      return fetch(event.request).then(response => {
        // Cache successful responses
        if (!response || response.status !== 200 || response.type === 'error') {
          return response;
        }

        const responseToCache = response.clone();
        caches.open(CACHE_NAME).then(cache => {
          cache.put(event.request, responseToCache);
        });

        return response;
      }).catch(() => {
        // Return offline page if available
        return caches.match('/offline.html');
      });
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    Promise.all([
      // Take control of already-open tabs right away.
      self.clients.claim(),
      // Drop every old cache (e.g. detomsite-v1) so users get the new bundle.
      caches.keys().then(cacheNames => {
        return Promise.all(
          cacheNames.map(cacheName => {
            if (cacheName !== CACHE_NAME) {
              return caches.delete(cacheName);
            }
          })
        );
      }),
    ])
  );
});

// Handle push notifications
self.addEventListener('push', event => {
  const options = {
    body: event.data.text(),
    icon: '/icon-192.png',
    badge: '/badge.png',
  };

  event.waitUntil(
    self.registration.showNotification('DETOMSITE', options)
  );
});
