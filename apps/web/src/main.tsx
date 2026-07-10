import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import './index.css'

// Register the app-shell service worker (docs/DESIGN.md §5) only in
// production builds — in dev, Vite's own HMR client + unbundled module
// graph make a caching SW actively counterproductive (stale-module bugs),
// and there is nothing to precache yet since `vite dev` never emits
// `dist/sw.js`. `sw.ts` never touches `/api` (Phase 1 scope), so this is
// safe to enable unconditionally once built.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { type: 'module' }).catch(() => {
      /* best-effort — a failed SW registration must never block the app */
    })
  })
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
