// Minimal service worker -- exists ONLY to satisfy Chrome's PWA
// installability requirement (a registered, activated service worker
// with a fetch handler) so "Add to Home Screen" treats this as a real
// installable app and actually uses the manifest's icons, instead of
// silently falling back to a low-res bookmark-style shortcut icon.
//
// Deliberately does NO caching and NO offline support -- every request
// just passes straight through to the network, unmodified. Given how
// many real caching headaches this app has already hit (Render builds,
// GitHub Pages, browser caches), the last thing this needs is a service
// worker adding its own caching layer on top. If offline support is
// ever wanted later, that's a deliberate future addition, not this.

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
