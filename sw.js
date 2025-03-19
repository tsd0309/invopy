const CACHE_NAME = 'inventory-system-v1';
const STATIC_CACHE = 'static-v1';
const DYNAMIC_CACHE = 'dynamic-v1';
const OFFLINE_URL = '/offline.html';

// Assets that should be cached immediately during installation
const CORE_ASSETS = [
    '/',
    '/offline.html',
    '/static/manifest.json',
    '/static/sw.js',
    '/static/icons/icon-512x512.png'
];

// Assets that should be cached during installation if there's time/bandwidth
const SECONDARY_ASSETS = [
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css',
    'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js',
    '/static/icons/icon-72x72.png',
    '/static/icons/icon-96x96.png',
    '/static/icons/icon-128x128.png',
    '/static/icons/icon-144x144.png',
    '/static/icons/icon-152x152.png',
    '/static/icons/icon-192x192.png',
    '/static/icons/icon-384x384.png',
    '/static/icons/splash-640x1136.png',
    '/static/icons/splash-750x1334.png',
    '/static/icons/splash-828x1792.png',
    '/static/icons/splash-1125x2436.png',
    '/static/icons/splash-1170x2532.png',
    '/static/icons/splash-1179x2556.png',
    '/static/icons/splash-1284x2778.png',
    '/static/icons/splash-1290x2796.png'
];

// Routes that should be cached with network-first strategy
const NETWORK_FIRST_ROUTES = [
    '/products',
    '/invoices',
    '/customers',
    '/reports'
];

// Install event - cache core assets immediately
self.addEventListener('install', (event) => {
    event.waitUntil(
        Promise.all([
            // Cache core assets immediately
            caches.open(STATIC_CACHE).then((cache) => {
                console.log('Caching core assets');
                return cache.addAll(CORE_ASSETS);
            }),
            // Cache secondary assets in the background
            caches.open(DYNAMIC_CACHE).then((cache) => {
                console.log('Caching secondary assets');
                return cache.addAll(SECONDARY_ASSETS);
            })
        ])
    );
    self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (![STATIC_CACHE, DYNAMIC_CACHE].includes(cacheName)) {
                        console.log('Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        }).then(() => {
            // Claim clients immediately
            return self.clients.claim();
        })
    );
});

// Helper function to determine caching strategy
function shouldNetworkFirst(url) {
    return NETWORK_FIRST_ROUTES.some(route => url.includes(route)) || 
           url.includes('/api/') || 
           url.includes('?');
}

// Fetch event with different strategies based on request type
self.addEventListener('fetch', (event) => {
    // Skip cross-origin requests
    if (!event.request.url.startsWith(self.location.origin)) {
        return;
    }

    // Network-first strategy for dynamic routes and API calls
    if (shouldNetworkFirst(event.request.url)) {
        event.respondWith(
            fetch(event.request)
                .then(response => {
                    // Clone the response before caching
                    const responseToCache = response.clone();
                    caches.open(DYNAMIC_CACHE)
                        .then(cache => {
                            cache.put(event.request, responseToCache);
                        });
                    return response;
                })
                .catch(() => {
                    return caches.match(event.request)
                        .then(response => {
                            if (response) {
                                return response;
                            }
                            if (event.request.mode === 'navigate') {
                                return caches.match(OFFLINE_URL);
                            }
                            return new Response('', {
                                status: 408,
                                statusText: 'Request timed out.'
                            });
                        });
                })
        );
        return;
    }

    // Cache-first strategy for static assets
    event.respondWith(
        caches.match(event.request)
            .then(response => {
                if (response) {
                    // Return cached response and update cache in background
                    fetch(event.request)
                        .then(networkResponse => {
                            caches.open(DYNAMIC_CACHE)
                                .then(cache => {
                                    cache.put(event.request, networkResponse);
                                });
                        })
                        .catch(() => {/* Ignore errors */});
                    return response;
                }

                // If not in cache, fetch from network
                return fetch(event.request)
                    .then(networkResponse => {
                        const responseToCache = networkResponse.clone();
                        caches.open(DYNAMIC_CACHE)
                            .then(cache => {
                                cache.put(event.request, responseToCache);
                            });
                        return networkResponse;
                    });
            })
    );
});

// Background sync for offline actions
self.addEventListener('sync', (event) => {
    if (event.tag === 'sync-invoices') {
        event.waitUntil(syncInvoices());
    }
});

// Push notification support
self.addEventListener('push', (event) => {
    const options = {
        body: event.data.text(),
        icon: '/static/icons/icon-192x192.png',
        badge: '/static/icons/icon-72x72.png',
        vibrate: [100, 50, 100]
    };

    event.waitUntil(
        self.registration.showNotification('Inventory System', options)
    );
}); 