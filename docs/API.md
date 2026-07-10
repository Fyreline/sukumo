# Sukumo — API surface & ingestion contracts

Two halves: **§1–2** what Sukumo serves and accepts; **§3–6** every external contract it
depends on. All Sukumo endpoints under `/api`, JSON, JWT bearer unless marked
*(ingest-token)* or *(open)*. Errors: `{"detail": {"code": "...", "message": "..."}}`,
the sibling convention.

## 1. Sukumo's own REST surface

```
POST /api/auth/login|refresh|logout   GET /api/auth/me       -- port of Michi (AUTH.md)
GET  /api/health                                              (open) liveness for tunnel/status checks

GET  /api/dashboard        -- THE aggregate: one response paints every bridge tile:
                           --   {briefing?, vitals{...}, habits[...], goal{...},
                           --    occasions[...], memory_strip[...], siblings[...],
                           --    nudges_pending[...], japan{days_to_go}}
                           -- server-composed from tables + latest snapshots; the SPA
                           --   does NO cross-source assembly (ARCHITECTURE §5.4)

POST /api/ingest/health    (ingest-token) phone health sync webhook — §2
POST /api/ingest/event     (ingest-token) generic event — §3 (Shortcuts etc.)
POST /api/notify           (ingest-token, scope notify) the household bus — §5

GET/POST/PATCH /api/habits, /api/habits/{id}/events   -- config + the 1-tap log
GET/POST/PATCH /api/books                              -- current read + history (Q1)
GET/POST/PATCH /api/people, /api/occasions, /api/gifts -- incl. calendar-import
                                                       --   candidates (DATA_MODEL §3)
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

## 2. Phone health data → `POST /api/ingest/health`

**Decision (2026-07-10): free-first.** For the record, because it was asked: iCloud —
including iCloud+ — offers **no** route to Health data. Health syncs end-to-end
encrypted between the user's own devices only; it never appears on iCloud.com and has
no web API at any subscription tier. The manual Health-app "Export All Health Data"
zip exists but is a hand-cranked XML dump, useless for automation. The two real
options are below; the endpoint accepts **both** payloads (sniffed by shape) so the
choice stays reversible.

**2a. Path A (default, free): a Shortcuts health-sync automation.** iOS Shortcuts can
query Apple Health on-device (*Find Health Samples* etc.) and POST the results with
*Get Contents of URL* — no third-party app, no cost. Two personal automations (≈08:00
and ≈21:00, "Run Immediately") run a shortcut that gathers yesterday's + today's
daily aggregates (steps, active energy, resting HR, stand hours), sleep for last
night, and recent workouts, then POSTs Sukumo's canonical shape:

```json
{ "metrics": [ { "metric": "step_count", "date": "2026-07-10", "qty": 8123,
                 "unit": "count" } ],
  "workouts": [ { "name": "Traditional Strength Training", "start": "…", "end": "…",
                  "duration_s": 3120, "kcal": 310, "distance_m": 0 } ] }
```

Headers: `Authorization: Bearer <ingest token>`, URL
`https://sukumo-api.mishka-hub.com/api/ingest/health`.

> ⚠️ **Build the real shortcut on Mack's phone during Phase 2 and verify each sample
> type is actually queryable with the aggregation needed** (steps/energy aggregate
> cleanly; sleep and workouts may need a per-sample loop — acceptable, it's a dozen
> rows/day). Document the final shortcut's steps in PRIVATE.md so it can be rebuilt on
> a new phone. Known trade-off: Shortcuts automations need the phone to have been
> unlocked around the scheduled time — twice-daily scheduling plus the 36h freshness
> rule (COACH.md §3.8) absorbs this. If it proves flaky in the first weeks, fall to
> Path B without server changes.

**2b. Path B (fallback, paid): Health Auto Export — JSON+CSV** (~£10 premium tier),
whose REST automation POSTs its own documented format — metrics/workouts wrapped in a
`"data"` envelope with `{name, units, data:[{date, qty}]}` entries. The ingester
detects the envelope and maps accordingly. Same ⚠️ as above if adopted: fixtures
first, verify real field spellings, correct this section in the same commit (the
Kakeibo Starling discipline).

**2c. Mapping:** `ingest/health.py` holds ONE dict from payload names (canonical and
HAE aliases) → canonical metrics (`sleep_analysis→sleep_asleep/sleep_inbed` (two
rows), `active_energy→active_energy`, …); workouts map by name → `wtype` slug with
the raw name kept in `source`. Unknown metrics stored verbatim, never rejected
(DATA_MODEL §2). Response: `{"accepted": n, "upserted": n, "unknown_metrics": [...]}`.
Every call writes a `sync_runs` row — the freshness rule watches it.

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
Sukumo never holds Mack's password (Michi's own AUTH reasoning, applied one level up).
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
- **Calendar — ICS subscription URL(s)** (`SUKUMO_ICS_URLS`): polled hourly with `ics`
  parser, full-window replace per feed (DATA_MODEL §6). This household's feeds
  (HANDOFF Q3): Mack's personal Apple calendar + the shared couple calendar (private
  ICS URLs → PRIVATE §3; the shared one is young and incomplete — rules must not
  assume completeness) + a free public bank-holiday ICS matching the employer's
  observed holidays (which feed: PRIVATE §3). The work calendar itself is not
  exportable — rule 6 leans on patterns and geofence history instead.
- **Photos (memory engine):** if the household Mac has iCloud Photo Library synced,
  `osxphotos` reads metadata (timestamps, locations, counts — no image uploads anywhere)
  during nightly assembly; MEMORY.md §2. HANDOFF Q4 gates this.
