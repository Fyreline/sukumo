import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const root = fileURLToPath(new URL('.', import.meta.url))

// For GitHub Pages *project* sites the app is served from /<repo>/, so a
// deploy workflow sets VITE_BASE=/sukumo/ at build time (docs/DEPLOYMENT.md).
// Defaults to '/' for local dev. Sukumo's dev server owns port 5179 — Mishka
// Hub 5173, Michi 5174, Japan 2026 5175/5177, Kakeibo 5178 — so all can run
// side-by-side on the household machine (docs/ARCHITECTURE.md §2).
const BASE = process.env.VITE_BASE ?? '/'

export default defineConfig({
  base: BASE,
  plugins: [react(), tailwindcss()],
  server: { port: 5179 },
  build: {
    rollupOptions: {
      input: {
        main: `${root}index.html`,
        // The hand-rolled service worker (docs/ARCHITECTURE.md §1,
        // docs/DESIGN.md §5) is built as its own entry so it ships as an
        // ordinary ES module at the dist root, registered from main.tsx
        // with `{ type: 'module' }` — no extra PWA build plugin needed for
        // the Phase 1 shell-only precache.
        sw: `${root}src/sw.ts`,
      },
      output: {
        entryFileNames: (chunk) => (chunk.name === 'sw' ? 'sw.js' : 'assets/[name]-[hash].js'),
      },
    },
  },
})
