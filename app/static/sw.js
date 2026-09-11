const CACHE = 'dpn-ai-v10.0.1-ui-shell';
const SHELL = ['/', '/styles.css?v=10.0.1', '/app.js?v=10.0.1', '/manifest.webmanifest'];
const CACHEABLE_PATHS = new Set([
  '/',
  '/styles.css',
  '/app.js',
  '/manifest.webmanifest',
  '/v8-desktop.css',
  '/v9-desktop.css',
  '/v8-desktop.js',
  '/v9-desktop.js',
]);

self.addEventListener('install', event =>
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()))
);

self.addEventListener('activate', event =>
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  )
);

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  if (!CACHEABLE_PATHS.has(url.pathname)) return;
  if (url.pathname === '/' && url.search) return;
  if (url.search && url.search !== '?v=10.0.1') return;

  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (!response.ok || response.type !== 'basic') return response;
        const copy = response.clone();
        caches.open(CACHE).then(cache => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
