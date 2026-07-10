# Phase 7 — Memory engine (owner: Opus build, Fable journal UI)

Days assembling themselves + the journal worth scrolling. **Deadline-bearing: live
before 2026-09-10** (Japan). Needs HANDOFF Q4 (photos) — assembly ships without photos
if No/unanswered.

## Build
1. Source mappers per MEMORY §2 filling `memory_events` (film/study/place/finance
   mappers ride existing snapshots/bus; photo mapper via osxphotos if Q4 yes —
   metadata only, run inside the nightly agent on the Mac).
2. `memory/assemble.py` per MEMORY §3: deterministic summary_md slots, stats_json,
   re-runnable, `--date` backfill; yesterday-1 re-run built in. `journal_days` +
   anniversary lookback query.
3. `memory/digest.py`: weekly digest (Sunday, into briefing + digests row); trip-range
   digest with the settings-flagged window (Japan dates from PRIVATE.md §4).
4. `scripts/assemble_day.py` + plist (deploy Phase 8).
5. JournalPage per MEMORY §5: day cards on the liquid thread, month nav, trip chapter
   headers (crimson torii for Japan), day detail w/ sparkline stats + Photos deep
   link + mood one-tap; bridge memory strip goes live.
6. Backfill: run assembly over everything already in `memory_events` since Phase 2
   went live — launch day should open onto weeks of history, not an empty page.

## Acceptance
- [ ] Nightly run assembles yesterday with real data: a workout, a Michi session and
      a watched film all appear on the right days (verify against reality, not logs).
- [ ] Re-running assembly for any date is byte-identical (determinism test); late
      health data → yesterday-1 re-run updates it.
- [ ] Thin day renders honestly short; a trip-flagged range renders the chapter
      treatment (fixture a fake 3-day trip).
- [ ] Weekly digest lands in Sunday's briefing with correct week-vs-week numbers,
      neutral phrasing (copy review).
- [ ] Anniversary line appears when a lookback hit is fixtured.
- [ ] pytest + typecheck + build green (paste output).
