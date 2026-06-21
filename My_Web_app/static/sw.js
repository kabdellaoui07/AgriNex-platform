const CACHE_NAME = 'agrinex-v3';
const ASSETS = [
  '/static/css/main.css',
  '/static/images/Design%20sans%20titre.svg',
  '/static/favicon.ico',
  '/static/manifest.json'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS).catch(err => console.log('Asset cache error: ', err));
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  // Only handle GET requests, pass through everything else natively
  if (e.request.method !== 'GET') {
    return;
  }

  // Bypass service worker for non-http/https requests (e.g. chrome-extension://)
  if (!e.request.url.startsWith('http')) {
    return;
  }

  e.respondWith(
    caches.match(e.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(e.request).catch(() => {
        // If network fetch fails (e.g. local server is stopped), 
        // return a friendly message rather than letting Chrome fail with ERR_FAILED.
        return new Response("AgriNex Local Server is offline. Please run 'python app.py' in your terminal.", {
          status: 503,
          headers: { 'Content-Type': 'text/plain; charset=utf-8' }
        });
      });
    })
  );
});
