# Phase 1 — Scaffold (owner: Sonnet)

Repo skeleton to first pixel: web + server boot, auth round-trips against real Mishka
Hub, theme mirrored, dev launch entries working. Pure porting — Michi is the template;
when in doubt, do what Michi did.

## Build
1. Layout per ARCHITECTURE §1 (empty modules with docstrings where later phases own
   the content). `.gitignore`: `data/`, `.env`, `docs/PRIVATE.md`, `*.db`,
   `node_modules/`, `dist/`.
2. Server: app factory, config (`SUKUMO_` prefix), db.py, `security.py`/`identity.py`/
   `routers/auth.py` ported from Michi (delta: `role` assignment, AUTH §1),
   `routers/health.py`. Dev db `data/sukumo.dev.db`.
3. Web: Vite + React 19 + TS + Tailwind v4 + motion; port `auth.ts` (key
   `sukumo_auth`), `api.ts`, LoginScreen, ThemeToggle, empty BridgePage behind the
   auth gate. Dev port **5179**.
4. Theme: add `DST_SUKUMO` to `learningLanguageMachine/scripts/sync-theme.sh`, update
   the canonical header's MIRRORS list, run it, commit the mirrored `theme.css` here.
5. PWA shell: manifest + placeholder vat icon + service worker registering and
   precaching the shell (network-first `/api` comes in Phase 4 with real data).
6. `.claude/launch.json`: `sukumo-api` (8301), `sukumo-web` (5179).

## Acceptance
- [ ] Login with real Mishka creds through dev server → me() renders display_name;
      wrong password → same-shape 401; Mishka stopped → 503 `identity_unavailable`.
- [ ] Refresh rotation + reuse tripwire tests ported and green.
- [ ] `diff` theme.css against canonical → identical; sync script run shows all
      mirrors "in step ✓".
- [ ] Both launch.json entries boot; 5173/5174/5178 siblings unaffected.
- [ ] pytest + typecheck + `npm run build` green (paste output).
