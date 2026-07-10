# Sukumo — Architecture

Deliberately the household shape: **Vite/React SPA + FastAPI + SQLite**, web static on
GitHub Pages (or served locally), API on the household Mac behind the shared Cloudflare
Tunnel. Anyone who has worked on Mishka Hub, Michi or Kakeibo can navigate this repo
blind. Two things are new here versus the siblings: a **PWA shell** (installable,
offline-tolerant dashboard, later web-push) and a **second scheduled process** (the
coach) beside the API.

## 1. Repo layout

```
sukumo/
├── README.md
├── docs/                        # this suite; phases/ has per-phase build orders
├── apps/
│   ├── web/                     # Vite + React 19 + TypeScript + Tailwind v4 + motion
│   │   ├── index.html
│   │   ├── public/
│   │   │   ├── manifest.webmanifest   # PWA: name, icons, standalone display
│   │   │   └── icons/                 # maskable icons, the aigame vat glyph (DESIGN §2)
│   │   ├── vite.config.ts       # dev port 5179 (5173 Mishka, 5174 Michi, 5178 Kakeibo)
│   │   └── src/
│   │       ├── main.tsx
│   │       ├── App.tsx          # route switch + shell + auth gate
│   │       ├── sw.ts            # service worker: app-shell cache, never caches /api
│   │       ├── theme.css        # MIRROR of Aizome canonical (DESIGN.md §1) — never hand-edit
│   │       ├── auth.ts          # port of Michi's (key: sukumo_auth)
│   │       ├── api.ts           # fetch wrapper w/ bearer + 401 refresh retry (port)
│   │       ├── pages/
│   │       │   ├── BridgePage.tsx     # THE dashboard (DESIGN.md §3) — Fable-built
│   │       │   ├── JournalPage.tsx    # memory engine reader (MEMORY.md §5) — Fable-built
│   │       │   ├── NudgeInbox.tsx     # nudge history, snooze/dismiss/action
│   │       │   ├── PeoplePage.tsx     # people / occasions / gift vault
│   │       │   ├── HabitsPage.tsx     # habit config + evidence review
│   │       │   └── SettingsPage.tsx   # quiet hours, caps, channels, tokens
│   │       └── components/
│   │           ├── tiles/             # one component per bridge tile (DESIGN.md §4)
│   │           ├── Sparkline.tsx      # shared tiny-chart primitives (SVG, viz tokens)
│   │           └── ThemeToggle.tsx    # straight port from Mishka
│   └── server/                  # FastAPI
│       ├── requirements.txt     # fastapi, uvicorn, sqlalchemy, pydantic-settings,
│       │                        #   pyjwt, httpx, ics, apprise? NO — see §5 (httpx only)
│       ├── app/
│       │   ├── main.py          # app factory, CORS, routers
│       │   ├── config.py        # env prefix SUKUMO_ (see §4)
│       │   ├── db.py            # engine/session helpers (port)
│       │   ├── models.py        # DATA_MODEL.md
│       │   ├── security.py      # JWT access + rotating refresh (port of Michi's)
│       │   ├── auth.py          # current_user dep + ingest_token dep (AUTH.md §3)
│       │   ├── identity.py      # Mishka Hub identity client (port of Michi's)
│       │   ├── notify.py        # the notification bus core (API.md §5): channel
│       │   │                    #   drivers ntfy (v1) + webpush (later), redaction rule
│       │   ├── ingest/
│       │   │   ├── health.py    # phone health payloads (Shortcuts/HAE, API.md §2) → samples/workouts
│       │   │   └── events.py    # generic Shortcuts/scripts events → memory_events etc.
│       │   ├── clients/         # thin read-only sibling clients (API.md §4)
│       │   │   ├── michi.py     # study stats + streak
│       │   │   ├── kakeibo.py   # house-goal snapshot
│       │   │   ├── mishka.py    # recent watches
│       │   │   ├── weather.py   # Open-Meteo (keyless)
│       │   │   └── calendar.py  # ICS subscription poller
│       │   ├── coach/
│       │   │   ├── engine.py    # tick loop: evaluate → dedupe → schedule → deliver
│       │   │   ├── rules/       # one module per rule (COACH.md §3), registry pattern
│       │   │   └── briefing.py  # morning briefing composer (rules-only v1)
│       │   ├── memory/
│       │   │   ├── assemble.py  # day assembly from memory_events (MEMORY.md §3)
│       │   │   └── digest.py    # weekly digest composer
│       │   └── routers/
│       │       ├── auth.py      # login (proxied) / refresh / logout / me
│       │       ├── ingest.py    # POST /api/ingest/* (token-auth, not JWT)
│       │       ├── dashboard.py # GET /api/dashboard — one aggregate tile payload
│       │       ├── habits.py    ├── people.py    ├── nudges.py
│       │       ├── journal.py   ├── notify.py    # POST /api/notify (bus entry, token)
│       │       ├── status.py    # sibling health checks
│       │       └── health.py    # GET /api/health (unauthenticated liveness)
│       └── scripts/
│           ├── coach_tick.py    # LaunchAgent entrypoint (also: python -m app.coach)
│           ├── poll_sources.py  # calendar/weather/sibling cache refresh entrypoint
│           ├── assemble_day.py  # nightly journal assembly entrypoint
│           ├── backup_db.py     # port of Michi's (sqlite3 .backup(), WAL-safe)
│           └── mint_ingest_token.py  # prints a new ingest token, stores hash
├── data/                        # gitignored: sukumo.db, sukumo.dev.db, backups/
└── .claude/launch.json          # sukumo-web 5179, sukumo-api 8301 (dev)
```

## 2. Processes & ports

| Thing | Value |
|---|---|
| API prod | LaunchAgent `com.sukumo.api`, uvicorn `127.0.0.1:8300`, no `--reload` |
| API dev | launch.json `sukumo-api`, port `8301`, `SUKUMO_DATABASE_URL` → `data/sukumo.dev.db` |
| Web dev | launch.json `sukumo-web`, port `5179` |
| Coach | LaunchAgent `com.sukumo.coach`, `StartInterval 900` (15 min), runs `scripts/coach_tick.py` |
| Source poller | same tick (coach_tick calls poll first) — **one** agent, not two, fewer moving parts |
| Journal assembly | LaunchAgent `com.sukumo.journal`, daily 02:30, `scripts/assemble_day.py` (yesterday) |
| Backup | LaunchAgent `com.sukumo.backup`, daily 03:30, prune to 30 |
| Tunnel hostname | `sukumo-api.mishka-hub.com` → `http://127.0.0.1:8300` |
| Web prod | GitHub Pages (Michi pattern) — HTTPS required for PWA install + later web-push ✓ |

Port ladder for the record: Mishka 8000/5173 · Michi 8100/5174 · Kakeibo 8200/8201/5178 ·
**Sukumo 8300/8301/5179**.

**Why the coach is a script, not an in-process scheduler:** a LaunchAgent tick is
observable (`launchctl`, log files), survives API restarts independently, can't wedge the
API event loop, and matches the household's existing operational muscle. The tick is
idempotent and cheap; 15 min is well under every rule's timing tolerance (COACH.md §4).

## 3. Data flow (one picture)

```
iPhone Shortcuts health sync (API §2) ──POST /api/ingest/health──►┐
iOS Shortcuts (office geofence, 1-tap read log) ──POST /api/ingest/event──►│
Michi / Kakeibo / Mishka read APIs ◄──httpx (service token)── poll ──►│  SQLite
ICS calendar feed(s) ◄── poll ──►│ sukumo.db
Open-Meteo forecast ◄── poll ──►┘
                                                        │
        coach_tick (15 min): rules ──► nudges table ──► notify.py ──► ntfy → phones
        assemble_day (02:30): memory_events ──► journal_days ──► weekly digest
        GET /api/dashboard ◄── BridgePage (PWA) — one request paints every tile
```

## 4. Config (env prefix `SUKUMO_`, pydantic-settings, `.env` gitignored)

`DATABASE_URL`, `JWT_SECRET`, `MISHKA_BASE_URL` (identity), `MICHI_BASE_URL` +
`MICHI_SERVICE_TOKEN`, `KAKEIBO_BASE_URL` + `KAKEIBO_SERVICE_TOKEN`,
`MISHKA_SERVICE_TOKEN`, `NTFY_URL` + `NTFY_TOPIC` (unguessable, PRIVATE.md),
`ICS_URLS` (comma-sep), `HOME_LAT/LON` + `OFFICE_LAT/LON` (PRIVATE.md → .env only),
`QUIET_HOURS` (default `22:30-07:30`), `TZ=Europe/London` assumed throughout.

## 5. Hard rules (grep-able acceptance items)

1. **Read-only siblings:** `clients/*.py` contain no `.post/.put/.delete` except
   `weather.py`/none — Sukumo never writes to a sibling.
   (`grep -rn "\.post\|\.put\|\.delete" app/clients/` → empty.)
2. **No sensitive numbers in push payloads:** ntfy.sh is a third party until/unless
   self-hosted; notification text carries *categories, not values* ("morning briefing
   ready", "gym gap: 4 days") — never sleep hours, weights, balances. The one enforcement
   point is `notify.py`'s redaction gate; rule text templates live beside it and are
   reviewed against this in Phase 5 acceptance.
3. **Coach may only create nudges via the engine** (dedupe/caps/quiet-hours live there);
   no route or script calls `notify.send()` directly except the bus endpoint itself.
4. **The SPA never talks to siblings** — only Sukumo's API does (CORS stays simple,
   tokens stay server-side).
5. **PRIVATE data** (coordinates, birthdays seeded, thresholds) enters via `.env` or the
   DB — a committed file containing a birthday or a coordinate is a build failure.
6. Every scheduled entrypoint writes a `sync_runs` row (source, status, counts, error) —
   silence must be diagnosable from the Ops tile alone (DATA_MODEL.md §7).
