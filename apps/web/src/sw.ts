/// <reference lib="webworker" />
export {}

declare const self: ServiceWorkerGlobalScope

// Sukumo's app-shell cache — docs/ARCHITECTURE.md §1, docs/DESIGN.md §5.
// Phase 1 scope ONLY: precache the shell (this fixed, small, build-time-known
// list of same-origin GET URLs). Network-first `/api` caching with a
// last-good-response fallback is Phase 4 work — until then this worker's
// fetch handler only ever answers requests for what it explicitly
// precached, so `/api/*` (and everything else) always goes straight to the
// network, untouched, by construction.
const CACHE_NAME = 'sukumo-shell-v1'
const SHELL_URLS = ['/', '/index.html', '/manifest.webmanifest', '/icons/icon.svg']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (!SHELL_URLS.includes(url.pathname)) return

  // Cache-first for the precached shell only — everything else (never
  // matched above, including every `/api/*` request) is left completely
  // unhandled and falls through to the browser's normal network fetch.
  event.respondWith(caches.match(request).then((cached) => cached ?? fetch(request)))
})
