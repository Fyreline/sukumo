# Phase 6 — The Coach (owner: Opus)

The rule engine and catalogue of COACH.md, ending with the coach LaunchAgent live and
the morning briefing arriving daily. HANDOFF Q1/Q2/Q11 are answered (2026-07-10) —
rule configs come from PRIVATE.md §3–4 at seed; any still-unconfigured rule sits
`not_configured`.

## Build
1. `coach/engine.py` per COACH §1: poll → evaluate → gate → deliver, sync_runs row,
   idempotent re-run, expiry of missed moments (§4). Rules are pure `(now, db) →
   [NudgeProposal]`; registry auto-discovers `coach/rules/*.py`.
2. Gate layer: dedupe_key uniqueness, per-rule cooldowns, daily cap w/ priority keep,
   quiet-hours rescheduling — all unit-tested with a frozen clock + seeded db.
3. Catalogue v1: the twelve rules of COACH §3, each with condition tests, dedupe
   tests, and template copy reviewed against COACH §5 (the copy review is an
   acceptance item, not vibes — read every template aloud).
4. `briefing.py`: composes from the same proposal stream + weather/calendar/streak
   summaries; `briefings` row; 07:35 delivery as the day's first push.
5. `scripts/coach_tick.py` + LaunchAgent plist (deploy in Phase 8; runnable manually
   now).
6. SettingsPage: quiet hours, daily cap, per-rule enable/disable.

## Acceptance
- [ ] Frozen-clock test suite: every rule fires on its condition and ONLY then; a
      dismissed nudge respects cooldown; cap keeps highest priority; 23:00 proposal
      delivers 07:30+; Mac-asleep gap expires the 21:15 reading nudge (§4 scenario).
- [ ] Stale sibling snapshot → rule 4 silent (stale-in-silent-out test).
- [ ] Run `coach_tick.py` against the real dev db three times in a row → identical
      nudge table after run 1 (idempotency in anger).
- [ ] A real morning: briefing push on the phone at 07:35 with true weather/calendar/
      streak content (leave it armed overnight; verify next day).
- [ ] Movement rules end-to-end: (a) doctor the db to an office day with no workout
      → 16:45 gym-day nudge; (b) a 4-day gap with no office day → 17:45 fallback;
      (c) a low-step no-workout day → 18:30 low-movement nudge, AND suppressed when
      a gym nudge already fired that day (the one-movement-poke rule); real phone
      push → action button closes the loop.
- [ ] pytest + typecheck green (paste output).
