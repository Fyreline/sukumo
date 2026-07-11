# Sukumo — Memory engine

The zero-effort journal: days assemble themselves from data the household already
generates; Mack's only optional input is a one-tap mood. Hard deadline: **assembly and
the journal UI live before 2026-09-10** so the Japan trip records itself (PLAN.md §5).

## 1. Principle

Nothing here asks to be written. If a day is thin, the journal says so honestly ("a
quiet Tuesday — 4,102 steps, one episode logged") rather than prompting anyone to
journal harder. The engine's job is *assembly and retrieval*, not creation.

## 2. Sources → `memory_events` (the per-source mapping)

| Source | kind | provider_uid | What lands |
|---|---|---|---|
| Health ingest | `workout` | HAE workout uid | type, duration — "gym, 52 min" |
| Michi snapshot | `study` | `michi:<date>` | words/lessons that day, streak marks |
| Mishka snapshot | `film` | `mishka:<watch id>` | title, rating, poster_url — **primary user's watches only**, filtered on `recent[].user_email` (API.md §4); the partner's watches are skipped, not stored |
| Calendar | `calendar` | ics_uid | title + location of *attended* (past) events |
| Shortcuts office/geofence | `place` | event id | office days, notable arrivals |
| Kakeibo milestone (via bus) | `finance` | nudge dedupe_key | "crossed 45%" — labels only |
| Photos (osxphotos, if Q4 yes) | `photo` | photo uuid | count + times + place names per day; **metadata only in the well, no originals ever copied or uploaded**. The journal's thumb strip is served separately: small *derivative* JPEGs on demand (`/api/photos/{uuid}/thumb`, primary-only), cached in gitignored `data/thumbs/` — never originals, never in the repo |
| `/api/ingest/event` manual | `manual`/`milestone` | event id | share-sheet "remember this" |
| Books (status→finished) | `milestone` | `book:<id>` | "finished *Title*" |

Ingesters are idempotent on `(source, provider_uid)` — assembly can re-run any day
forever. Parked v2 source (HANDOFF Q4): the film-scan photo folder on the Windows
desktop — a future watched-folder ingest, not in v1.

## 3. Nightly assembly (`assemble_day.py`, 02:30, for yesterday)

1. Gather yesterday's `memory_events` + daily `health_samples` aggregates.
2. Compose `summary_md` — rules-based v1: a template with slots (movement line, study
   line, events line, films line, photos line), skipping empty slots so thin days read
   naturally short. Deterministic, testable, no LLM required.
3. Store `journal_days` row (`stats_json` carries the numbers the UI charts).
4. Re-assembly on demand (`assemble_day.py --date`) for backfill or when late data
   arrives (HAE syncs can lag) — the daily agent also re-runs yesterday-1 for this.

**Weekly digest** (Sunday within the morning briefing + `digests` row): the week's
days stitched into a paragraph + numbers vs the week before (neutral phrasing, COACH
§0), one "moment of the week" (largest photo cluster or best-rated film). **Trip
digests**: a date-range flagged in settings (the Japan range lives in PRIVATE.md §4
and runtime settings only — exact travel dates never sit in committed docs) gets
per-day assembly promoted into a `trip` digest with a cover page when the range ends.

## 4. The anniversary well

Assembly also answers "what happened on this date in past years" (`journal_days`
lookback) — feeding the briefing's memory line. This gets better every year the
system runs; it's the compounding payoff of starting now.

## 5. Journal UI (Fable, Phase 7)

`JournalPage`: a vertical scroll of day cards (washi paper, date in ink, event pearls
on a `--color-liquid` thread — the Michi trail motif repurposed as a timeline), month
jump-nav, thin-day cards visually quieter. Trip ranges render with a chapter header
(Japan gets the crimson torii treatment). Day card tap → detail: stats row
(sparklines), events by kind, the day's photos as a collapsible thumbnail strip
("N photos ›" → a lazy-loaded row of authed derivative thumbs, blob→object-URL,
revoked on collapse), the mood one-tap. An "Open Photos" link remains but is
labelled honestly: **macOS/iOS expose no public URL scheme to a specific photo,
moment or date** — `photos-redirect://` can only open the app, so the in-journal
thumbs are the way to actually *see* the day. Search v1 is a client-side title
filter; anything fancier waits for real need.
