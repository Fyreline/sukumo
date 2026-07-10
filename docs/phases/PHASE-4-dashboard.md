# Phase 4 — The Bridge (owner: Fable)

The dashboard earns its "tab worth opening" title: DESIGN §3's eight tiles live off
real ingested data via one `/api/dashboard` call, PWA installable. Also PeoplePage so
the Q8 seed session can happen.

## Build
1. `routers/dashboard.py`: server-composed aggregate (API §1 shape) — vitals from
   daily aggregates + 14-day series, habit states with gap maths, latest sibling
   snapshots with ages, occasions window, memory strip counts (empty until Phase 7 —
   render the thread anyway), pending nudge count (0 until Phase 6).
2. People/occasions/gifts models + routers + PeoplePage (add/edit, lead-days,
   gift vault with status flow).
3. BridgePage + tiles per DESIGN §3–4: sparklines (shared SVG primitives, viz
   tokens), goal ring, streak cards with the hanko one-tap stamp animation, ops row,
   skeletons, per-tile stale degradation.
4. Service worker: network-first `/api/dashboard` with last-good fallback + `stale`
   chip; manifest + real keep icon (both scheme theme colours).
5. HabitsPage (config UI over Phase 2's endpoints) + SettingsPage shell.

## Acceptance
- [ ] Cold load on iPhone-width: one dashboard request, skeleton → painted < 1s local;
      airplane-mode reload → last-good bridge + stale chip (test it for real).
- [ ] Stop Michi → its tile greys with age, everything else lives.
- [ ] Real data visible: yesterday's steps/sleep from the phone, a real workout in
      streaks, goal ring showing Kakeibo's live pct.
- [ ] A2HS install on a real iPhone → standalone launch, keep icon correct in light
      and dark.
- [ ] Reduced-motion honoured; VoiceOver reads sensible tile summaries; AA contrast
      spot-check on both schemes.
- [ ] pytest + typecheck + build green (paste output).
