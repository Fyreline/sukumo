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
| Photos (osxphotos, if Q4 yes) | `photo` | photo uuid | count + times + place names per day; **metadata only in the well, no originals ever copied or uploaded**. **Journal-photo predicate** (`memory/photos.py is_journal_photo`, shared by the mapper, the day listing AND the thumb exporter): a photo counts unless osxphotos flags it `screenshot`, `screen_recording`, `hidden` or `intrash` — those four exactly, nothing more (saved WhatsApp images etc. stay; the filter exists because Shortcuts screenshots were flooding the strip, not to curate the camera roll). The journal's thumb strip is served separately: small *derivative* JPEGs on demand (`/api/photos/{uuid}/thumb`, primary-only), cached in gitignored `data/thumbs/` — never originals, never in the repo |
| `/api/ingest/event` manual | `manual`/`milestone` | event id | share-sheet "remember this" |
| Books (status→finished) | `milestone` | `book:<id>` | "finished *Title*" |
| Overland location ingest | *(none — bypasses the well)* | — | raw GPS points land in `location_points` (API.md §3b), never as `memory_events`; assembly reduces each day to one movement block in `stats_json` (trace/distance/away minutes) and the raw points die at 90 days. **All metadata stays local** — no geocoding, no tiles, no third-party call, ever — **and the partner never sees location**: it surfaces only through the primary-only journal, never the dashboard, portal, or a push (grep-pinned by `test_architecture_rules.py`) |

Ingesters are idempotent on `(source, provider_uid)` — assembly can re-run any day
forever. Parked v2 source (HANDOFF Q4): the film-scan photo folder on the Windows
desktop — a future watched-folder ingest, not in v1.

## 3. Nightly assembly (`assemble_day.py`, 02:30, for yesterday)

1. Gather yesterday's `memory_events` + daily `health_samples` aggregates + the day's
   `location_points` reduced to a movement block (`memory/movement.py`): haversine
   distance (jumps >200 m inside 30 s are GPS noise, skipped), minutes outside 150 m
   of home when `SUKUMO_HOME_LAT/LON` is set (else null), and a Douglas-Peucker-
   simplified trace of ≤200 absolute `[lat, lon]` points (absolute rather than
   normalised — stats_json is already primary-only, and absolute coords redraw
   without a second lookup).
2. Compose `summary_md` — rules-based v1: a template with slots (movement line —
   including "Out and about — 6.2 km on foot." on traced days, study
   line, events line, films line, photos line), skipping empty slots so thin days read
   naturally short. Deterministic, testable, no LLM required. Figures are fine here
   (it's the authed journal); the redaction gate applies to pushes, which never read
   summary_md/stats_json.
3. Store `journal_days` row (`stats_json` carries the numbers the UI charts, plus
   `trace`/`distance_m`/`away_min` on days with location data). The nightly run also
   prunes raw `location_points` older than 90 days (DATA_MODEL §8).
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
(sparklines), events by kind, a **Route card** on days with a movement trace — the
simplified polyline drawn as bare SVG auto-fitted to its bounding box (cos-lat
corrected so distances aren't squashed), sky ink at the liquid-thread weight, olive
start dot, clay end dot, captioned "6.2 km on foot · 3h 7m out". Deliberately **no
base map and no external tile/geocoding request** — the coordinates never leave the
household; that absence *is* the design. Degrades to nothing when a day has no trace;
draw-in animation skipped under reduced motion. Then the day's photos as a collapsible
strip ("N photos ›", filtered counts) of **moment groups**: the server buckets the
day's journal-worthy photos by Photos' own moment title, falling back to time-gap
clusters (>90 min apart) labelled with the dominant place name (or just the time
range when nothing is geocoded); each group renders a small ink-soft label row above
its lazy-loaded row of authed derivative thumbs (blob→object-URL, revoked on
collapse), 24-thumb cap across groups ("+N more"). Then the mood one-tap. There is
deliberately **no "Open Photos" link**: macOS/iOS expose no public URL scheme to a
specific photo, moment or date (`photos-redirect://` could only open the app), so
the in-journal thumbs ARE the way to see the day. Search v1 is a client-side title
filter; anything fancier waits for real need.
