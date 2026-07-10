# Phase 2 — Ingestion core (owner: Sonnet)

Passive data flowing: ingest tokens, the health webhook, generic events, calendar +
weather pollers, sync_runs everywhere. Fixtures first (the Kakeibo discipline).

## Build
1. Models: `ingest_tokens`, `health_samples`, `workouts`, `habits`, `habit_events`,
   `memory_events`, `calendar_events`, `sibling_snapshots`, `sync_runs`, `settings`
   (DATA_MODEL). `scripts/mint_ingest_token.py`.
2. `auth.py` ingest_token dependency (scope check, last_seen_at stamp, revocation).
3. `ingest/health.py` per API §2: accepts BOTH payload shapes (canonical Shortcuts
   Path A + HAE's `data`-enveloped Path B, sniffed by shape); fixtures for both
   written NOW. **Build the real Shortcuts health-sync automation on Mack's phone and
   verify against dev before acceptance** (API §2a caveats — per-type queryability,
   aggregation), documenting the shortcut's steps in PRIVATE.md and correcting API §2
   in the same commit. Mapping dict, unknown-metric passthrough, workout upsert,
   `sync_runs` row, response counts.
4. `ingest/events.py` per API §3: reading→habit_events(tap), office→memory_events +
   office history, manual/milestone→memory_events.
5. `clients/weather.py` (Open-Meteo, home+office) and `clients/calendar.py` (ics,
   full-window replace) + `scripts/poll_sources.py` wiring → snapshots/calendar_events
   + sync_runs.
6. Habit auto-evidence derivation: nightly rebuild of `auto` habit_events from
   workouts (gym) — the delete+rebuild rule (DATA_MODEL §2).
7. Routers: habits (config + events + the 1-tap POST), status (`/api/status` off
   sync_runs + snapshot ages).

## Acceptance
- [ ] Real Shortcuts sync from the phone lands: `health_samples` rows for ≥4 metrics
      + sleep + ≥1 real workout; re-POST of same payload → zero new rows (idempotency
      test). HAE fixture also ingests correctly (Path B stays warm).
- [ ] Token with `notify` scope 403s on `/api/ingest/*`; revoked token 401s;
      last_seen_at visible in `/api/status`.
- [ ] Reading one-tap POST → habit_event(tap); repeat same day → 200, still one row.
- [ ] Calendar fixture poll twice → stable row count; weather snapshot ages correctly.
- [ ] `grep -rn "\.post\|\.put\|\.delete" app/clients/` → empty (read-only law).
- [ ] pytest + typecheck green (paste output).
