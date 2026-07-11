# Sukumo — Data model

SQLite via SQLAlchemy, WAL mode, `data/sukumo.db`. Conventions as siblings: integer PKs,
`created_at`/`updated_at` UTC ISO strings, all *local* semantics (dates, quiet hours)
computed in **Europe/London** at use time, never baked into storage. Idempotency is the
theme: every passive source has a natural key so re-delivery upserts instead of
duplicating.

## 1. Identity & tokens

```
users            id, email UNIQUE, display_name, role ('primary'|'partner'),
                 created_at            -- rows appear on first successful proxied login
refresh_tokens   port of Michi's table verbatim (rotating, reuse tripwire)
ingest_tokens    id, name ('health-mack-iphone', 'shortcut-office', 'michi-bus'),
                 token_hash UNIQUE (sha256 of the raw token — raw shown once at mint),
                 scope ('ingest'|'notify'|'ingest+notify'), user_id NULLABLE,
                 last_seen_at, revoked_at NULLABLE
```

Ingest tokens are the auth story for everything that can't do a login flow (Health Auto
Export, Shortcuts, sibling scripts POSTing to the bus). Minted by
`scripts/mint_ingest_token.py`, sent as `Authorization: Bearer <raw>`. AUTH.md §3.

## 2. Health & habits

```
health_samples   id, user_id, metric, ts_start, ts_end, value REAL, unit, source,
                 UNIQUE(user_id, metric, ts_start, source)
                 -- metric: canonical snake_case ('step_count','sleep_asleep',
                 --   'active_energy','resting_heart_rate','stand_hours', …) mapped
                 --   from phone payload names in ingest/health.py (API.md §2c);
                 --   unknown metrics stored verbatim, never dropped
workouts         id, user_id, wtype, ts_start, ts_end, duration_s, kcal, distance_m,
                 source, provider_uid, UNIQUE(user_id, provider_uid, source)
location_points  id, user_id, ts (UTC ISO), lat REAL, lon REAL, accuracy_m REAL NULL,
                 speed_ms REAL NULL, source ('overland'), UNIQUE(user_id, ts, source)
                 -- raw GPS from the Overland logger (API.md §3b); points with
                 --   horizontal_accuracy > 100m never land. TRANSIENT: pruned
                 --   after 90 days by the nightly assembly once the day's
                 --   movement aggregate exists (§8) — the aggregate in
                 --   journal_days.stats_json is what lives forever. Location
                 --   never leaves this table + the primary-only journal.
habits           id, user_id, key UNIQUE ('gym','reading','japanese','walk'), title,
                 kind ('auto'|'tap'|'hybrid'), target_json ({"per_week":3} |
                 {"per_day":1}), evidence ('workouts:wtype in cfg'|'events:reading'|
                 'michi:session'), active BOOL, config_json (thresholds — PRIVATE values
                 live here, in the DB, not in code)
habit_events     id, habit_id, local_date, value REAL DEFAULT 1, source
                 ('auto'|'tap'|'coach_confirm'), note NULLABLE,
                 UNIQUE(habit_id, local_date, source)
                 -- 'auto' rows are re-derived (delete+rebuild per day) from evidence;
                 --   'tap'/'coach_confirm' rows are human signals and never rebuilt over
books            id, title, author NULLABLE, status ('reading'|'finished'|'abandoned'),
                 started_on, finished_on NULLABLE, notes NULLABLE
                 -- the reading habit's companion (HANDOFF Q1): the current read shows
                 --   on the streak card; finishing one writes a memory_events
                 --   milestone. Recommendations are v2 — the history accrues now.
```

Streak/gap maths is computed in queries off `habit_events`, not stored — no counter to
corrupt. A habit whose `kind='auto'` never shows a checkbox anywhere in the UI (the
material-difference law, PLAN.md §1).

## 3. People, occasions, gifts (the deliberate-manual corner)

```
people           id, name, relation, birthday DATE NULLABLE, notes, archived BOOL
occasions        id, person_id NULLABLE, title, month_day ('09-22') or date DATE
                 (one of the two: recurrence 'yearly'|'once'), lead_days INT DEFAULT 21,
                 kind ('birthday'|'anniversary'|'event'|'deadline'),
                 private_to_user INT NULLABLE FK users.id  -- surprise guard, see below
                 -- birthdays auto-materialise one occasion per person with a birthday;
                 --   handled in people router, not by trigger magic
gift_ideas       id, person_id, idea, url NULLABLE, price_pence NULLABLE,
                 status ('idea'|'bought'|'given'), occasion_id NULLABLE, created_at
```

Real names/birthdays are **data**, entered through the UI into the DB (backed up
locally) — they never appear in the repo. Seed checklist in PRIVATE.md. Import
assist (HANDOFF Q8): PeoplePage suggests candidates from `calendar_events` whose
titles look like birthdays; every candidate is confirmed by hand — nothing
auto-creates a person. Occasions carry a `private_to_user` flag (nullable FK) —
required before the partner portal may ever render occasion data (PRIVATE §2 ⚠️).

## 4. Coach

```
nudges           id, rule_key, user_id, dedupe_key, scheduled_for, sent_at NULLABLE,
                 channel ('ntfy'|'webpush'|'inbox'), title, body,
                 status ('pending'|'sent'|'snoozed'|'dismissed'|'actioned'|'expired'),
                 snoozed_until NULLABLE, context_json, created_at,
                 UNIQUE(dedupe_key)
                 -- dedupe_key formats defined per-rule in COACH.md §3, e.g.
                 --   'gym-gap:2026-07-10' or 'birthday-gift:person=4:occ=2026'
briefings        id, local_date UNIQUE, content_md, composed_by ('rules'|'llm'),
                 sent_at NULLABLE
```

`status` transitions are the coach's memory — "was this already said, did he act on it"
— and feed the success metric (PLAN.md §6: actioned/dismissed ratio) and the per-rule
cooldowns. Nudges older than 90 days with terminal status may be pruned by backup script.

## 5. Memory engine

```
memory_events    id, user_id NULLABLE (household events allowed), ts, kind
                 ('photo'|'film'|'study'|'place'|'calendar'|'finance'|'workout'|
                  'manual'|'milestone'), title, detail_json, source, provider_uid,
                 UNIQUE(source, provider_uid)
                 -- the single well every journal day draws from; ingesters map
                 --   their domain into it (MEMORY.md §2 has the per-source mapping)
journal_days     local_date PK, assembled_at, summary_md, stats_json, event_count,
                 mood NULLABLE  -- the ONE optional human field, one tap, never required
digests          id, period_start, period_end, kind ('weekly'|'trip'), content_md,
                 sent_at, UNIQUE(kind, period_start)
```

## 6. Sibling snapshots (thin cache, not a copy)

```
sibling_snapshots  id, app ('michi'|'kakeibo'|'mishka'|'weather'|'calendar'),
                   fetched_at, ok BOOL, latency_ms, payload_json, error NULLABLE
                   -- keep last N=50 per app, prune on insert; dashboard reads the
                   --   latest ok row and shows its age — NEVER re-derives sibling
                   --   domain logic from payload internals beyond the agreed
                   --   read-contract fields (API.md §4)
calendar_events    id, ics_uid, starts_at, ends_at, all_day BOOL, title, location,
                   calendar_name, UNIQUE(ics_uid, starts_at)
                   -- refreshed by full-window replace per feed poll (ICS has no deltas)
```

## 7. Operations

```
sync_runs        id, source ('ingest:health'|'poll:michi'|'coach:tick'|
                 'journal:assemble'|…), started_at, finished_at, status
                 ('ok'|'error'|'not_configured'), items INT, error NULLABLE
push_subscriptions  (Phase-later, web-push) id, user_id, endpoint UNIQUE, keys_json
settings         key PK, value_json  -- quiet hours override, caps, channel choice;
                                     --   read-through defaults from config.py
```

## 8. Retention

SQLite with daily `.backup()` (WAL-safe) pruned to 30 — the Kakeibo/Michi pattern.
`health_samples` at minute granularity is the only unbounded-ish table; the phone
sync sends **daily aggregates + workouts** (API.md §2, either path), which keeps
row counts trivial (≈10 metrics × 365 days). If minute-level ever lands, aggregate to
daily on ingest and discard raw — revisit only with a real need.

`location_points` is the aggregate-then-discard case in practice: the nightly
assembly (`assemble_yesterday` → `movement.prune_location_points`) deletes raw points
older than **90 days**, but only for days whose `journal_days` row already exists —
a day the assembly somehow missed keeps its raw points until it is assembled. The
daily movement aggregate (`stats_json`: trace ≤200 points, distance, away minutes)
lives forever in `journal_days`. Chosen over the backup script as the pruning home
because retention is an assembly concern (the prune precondition *is* "the aggregate
exists"), and the journal agent already runs nightly.
