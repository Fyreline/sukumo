# Honmaru — API surface & ingestion contracts

Two halves: **§1–2** what Honmaru serves and accepts; **§3–6** every external contract it
depends on. All Honmaru endpoints under `/api`, JSON, JWT bearer unless marked
*(ingest-token)* or *(open)*. Errors: `{"detail": {"code": "...", "message": "..."}}`,
the sibling convention.

## 1. Honmaru's own REST surface

```
POST /api/auth/login|refresh|logout   GET /api/auth/me       -- port of Michi (AUTH.md)
GET  /api/health                                              (open) liveness for tunnel/status checks

GET  /api/dashboard        -- THE aggregate: one response paints every bridge tile:
                           --   {briefing?, vitals{...}, habits[...], goal{...},
                           --    occasions[...], memory_strip[...], siblings[...],
                           --    nudges_pending[...], japan{days_to_go}}
                           -- server-composed from tables + latest snapshots; the SPA
                           --   does NO cross-source assembly (ARCHITECTURE §5.4)

POST /api/ingest/health    (ingest-token) Health Auto Export webhook — §2
POST /api/ingest/event     (ingest-token) generic event — §3 (Shortcuts etc.)
POST /api/notify           (ingest-token, scope notify) the household bus — §5

GET/POST/PATCH /api/habits, /api/habits/{id}/events   -- config + the 1-tap log
GET/POST/PATCH /api/people, /api/occasions, /api/gifts
GET  /api/nudges?status=…             POST /api/nudges/{id}/snooze|dismiss|action
GET  /api/nudges/act/{token}          (open) one-click action link used INSIDE ntfy
                                      -- signed single-use token, marks actioned;
                                      --   GET because notification taps are GETs;
                                      --   idempotent, expires with the nudge
GET  /api/briefings/today|{date}
GET  /api/journal/{date}, /api/journal?from=&to=      PATCH /api/journal/{date} (mood)
GET  /api/digests?kind=weekly
GET  /api/status            -- sibling/source health: latest sync_runs + snapshot ages
```

## 2. Health Auto Export → `POST /api/ingest/health`

The iOS app **Health Auto Export — JSON+CSV** (paid tier) runs automations that POST
Apple Health data to a REST endpoint on a schedule. Configuration on the phone (documented
here because it *is* part of the contract): API Export → URL
`https://honmaru-api.mishka-hub.com/api/ingest/health`, header
`Authorization: Bearer <ingest token>`, format JSON, aggregation **daily** for metrics,
plus workouts; schedule hourly (cheap; upserts make it idempotent).

**2a. Assumed payload shape** (its documented export format):

```json
{ "data": {
    "metrics": [
      { "name": "step_count", "units": "count",
        "data": [ { "date": "2026-07-10 00:00:00 +0100", "qty": 8123 } ] },
      { "name": "sleep_analysis", "units": "hr",
        "data": [ { "date": "…", "asleep": 7.1, "inBed": 7.9, … } ] }
    ],
    "workouts": [
      { "name": "Traditional Strength Training", "start": "…", "end": "…",
        "duration": 3120, "activeEnergyBurned": { "qty": 310, "units": "kcal" },
        "distance": { "qty": 0, "units": "km" } } ] } }
```

> ⚠️ **Fixtures first, verify field spellings against a real export from Mack's phone in
> Phase 2, and correct this section in the same commit** — exactly the Kakeibo Starling
> discipline. The app's schema has drifted between versions; the ingester must log-and-
> store unknown metric names rather than reject (DATA_MODEL §2).

**2b. Mapping:** `ingest/health.py` holds ONE dict from HAE names → canonical metrics
(`step_count→step_count`, `sleep_analysis→sleep_asleep/sleep_inbed` (two rows),
`active_energy→active_energy`, …); workouts map by name → `wtype` slug with the raw name
kept in `source`. Response: `{"accepted": n, "upserted": n, "unknown_metrics": [...]}`.
Every call writes a `sync_runs` row — the freshness rule (COACH.md §3.8) watches it.

## 3. Generic events → `POST /api/ingest/event`

For iOS **Shortcuts automations** and anything else with a single fact to report:

```json
{ "kind": "office" | "reading" | "place" | "manual" | "milestone",
  "state": "arrived" | "left" | null,
  "value": 1, "title": "…optional…", "ts": "…optional, default now…" }
```

Routing: `reading` → `habit_events` (source `tap`); `office` arrived/left →
`memory_events(kind=place)` + feeds the office-day rule's history; `manual`/`milestone`
→ `memory_events`. Planned Shortcuts (set up in Phase 8, listed in PRIVATE.md checklist):
office geofence arrive/leave; a home-screen "📖 logged" one-tap; optionally a share-sheet
"remember this" → `manual`.

## 4. Sibling read contracts (the Phase-3 patches)

Each sibling gains **one additive, read-only endpoint** behind a static service token
(env on both sides, e.g. `MICHI_SERVICE_TOKEN`) — deliberately NOT the user-JWT flow, so
Honmaru never holds Mack's password (Michi's own AUTH reasoning, applied one level up).
Small PRs to each repo; shapes owned here so the clients and patches agree:

```
Michi   GET /api/stats/service   → { streak_days, studied_today, due_reviews,
                                     words_known, last_session_at }
Kakeibo GET /api/goal/service    → { goal_pence, saved_pence, pct, pace_status,
                                     as_of }             -- numbers stay server-side;
                                                          -- bridge shows them, pushes NEVER do
Mishka  GET /api/activity/service→ { recent: [{title, watched_at, poster_url,
                                     rating}], watchlist_count }
```

All three: `Authorization: Bearer <service token>`, 401 without; **no other fields
consumed** even if present (snapshot contract, DATA_MODEL §6). Fallback if a sibling
patch stalls: Letterboxd's public RSS can stand in for Mishka's recents; Michi/Kakeibo
have no fallback — their tiles show `stale` honestly.

## 5. The notification bus — `POST /api/notify`

Any household app/script, one pipe: `{ "title", "body", "priority": "low|default|high",
"tags": ["michi","ops"], "source": "com.michi.api" }` *(ingest-token, scope notify)*.
Delivery = `notify.py`: writes an `inbox` nudge row (so it's on the bridge) and forwards
to the phone channel. **Redaction gate lives here** (ARCHITECTURE §5.2): outbound push
text is template-checked; anything numeric that looks like money/health gets
category-ised or dropped. Siblings adopt it opportunistically (Michi's LaunchAgent
failure hook is the first customer) — never a blocking dependency for them.

**Channel v1: ntfy.sh** with a long random topic (PRIVATE.md) — zero infra, free iOS
app, action buttons (the §1 `act/{token}` links). Sensitive detail stays out by the
redaction rule, so the third-party exposure is "someone with the topic string sees
that a nudge fired". Web-push (self-contained, no third party) is the planned Phase-9+
upgrade once the PWA is proven; `notify.py`'s driver interface keeps that a swap, not a
rewrite. HANDOFF Q6 confirms Mack's comfort with this sequencing.

## 6. Ambient sources

- **Weather — Open-Meteo** (keyless, free): daily forecast for home + office coords
  (.env), polled with the coach tick, snapshot-cached. Used by office-day rule + briefing.
- **Calendar — ICS subscription URL(s)** (`HONMARU_ICS_URLS`): polled hourly with `ics`
  parser, full-window replace per feed (DATA_MODEL §6). Google/Apple both export private
  ICS URLs; which calendars exist is HANDOFF Q3.
- **Photos (memory engine):** if the household Mac has iCloud Photo Library synced,
  `osxphotos` reads metadata (timestamps, locations, counts — no image uploads anywhere)
  during nightly assembly; MEMORY.md §2. HANDOFF Q4 gates this.
