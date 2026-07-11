/// <reference lib="webworker" />
export {}

declare const self: ServiceWorkerGlobalScope

// Sukumo's service worker — docs/ARCHITECTURE.md §1, docs/DESIGN.md §5.
//
// Two jobs, nothing else:
//  1. Precache the app shell (fixed, small, build-time-known list).
//  2. Network-first for GET /api/dashboard with a last-good-response
//     fallback (the bridge must paint on the train). A cache-served
//     fallback is stamped `X-Sukumo-Stale: 1` so the UI can show the kraft
//     `stale` chip (api.ts getWithStale).
//
// Auth (`/api/auth/*`) and one-click nudge action links (`/api/nudges/act/*`)
// are NEVER cached — the dashboard path is the ONLY /api path this worker
// touches, allow-listed by exact pathname, and only 200s are stored.
const SHELL_CACHE = 'sukumo-shell-v4'
const API_CACHE = 'sukumo-api-v1'
const KNOWN_CACHES = [SHELL_CACHE, API_CACHE]
// The worker may be served from a subpath (GitHub Pages: /sukumo/sw.js), so
// the shell is precached relative to wherever the worker actually lives.
const BASE = new URL('.', self.location.href).pathname
const SHELL_URLS = [
  BASE,
  `${BASE}index.html`,
  `${BASE}manifest.webmanifest`,
  `${BASE}icons/icon.svg`,
  `${BASE}icons/icon-192.png`,
  `${BASE}icons/icon-512.png`,
  `${BASE}icons/apple-touch-icon.png`,
]
const DASHBOARD_PATH = '/api/dashboard'

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => !KNOWN_CACHES.includes(key)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

async function dashboardNetworkFirst(request: Request): Promise<Response> {
  const cache = await caches.open(API_CACHE)
  try {
    const response = await fetch(request)
    if (response.ok) {
      // Last-good only: never store an error body over a good bridge.
      await cache.put(request.url, response.clone())
    }
    return response
  } catch {
    // Offline (or the API is down): serve the last good copy, marked stale.
    const cached = await cache.match(request.url, { ignoreVary: true })
    if (cached) {
      const headers = new Headers(cached.headers)
      headers.set('X-Sukumo-Stale', '1')
      const body = await cached.blob()
      return new Response(body, { status: 200, statusText: 'OK (stale)', headers })
    }
    return Response.error()
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)

  // The one /api path with offline behaviour. The API may live on another
  // origin (dev 8301 / the tunnel domain), so match by pathname, not origin.
  if (url.pathname === DASHBOARD_PATH) {
    event.respondWith(dashboardNetworkFirst(request))
    return
  }

  // Everything else /api-shaped (auth, act links, habits, people, …) is
  // deliberately untouched — straight to the network.
  if (url.pathname.startsWith('/api/')) return

  if (url.origin !== self.location.origin) return
  if (!SHELL_URLS.includes(url.pathname)) return

  // Cache-first for the precached shell only.
  event.respondWith(caches.match(request).then((cached) => cached ?? fetch(request)))
})
