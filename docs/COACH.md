# Sukumo — The Coach

The reason this app exists (PLAN.md §1): a scheduled process that notices, encourages,
and remembers — so Mack doesn't have to run his own life admin in his head. This doc is
the spec Opus builds Phase 6 from; the tone rules in §5 are as binding as the schema.

## 0. Standing disclaimer

The coach reflects data the phone already recorded and dates Mack already entered. It
never interprets health data medically, never predicts, never comments on trends in
body metrics beyond neutral display. A rule that would need medical judgement to write
is a rule we don't ship.

## 1. Engine shape

`coach_tick.py` every 15 min (ARCHITECTURE §2), strictly this order:

1. **Poll** ambient sources due for refresh (siblings, weather hourly, calendar hourly)
   → snapshots. Failures degrade to `stale`, never crash the tick.
2. **Evaluate** every registered rule (pure function: `(now, db) → [NudgeProposal]`).
   Rules read tables/snapshots only — no network in rules, testable with a frozen db.
3. **Gate** proposals: dedupe_key already exists → drop; rule cooldown active → drop;
   daily cap reached → keep only highest priority; quiet hours → schedule for the next
   morning window instead of dropping.
4. **Deliver** nudges whose `scheduled_for ≤ now`: render template → redaction gate →
   channel (ntfy v1) → mark `sent`. Snoozed nudges re-enter here at `snoozed_until`.
5. Write the `sync_runs` row (`coach:tick`, counts per stage).

Idempotent by construction: the dedupe_key means a crashed tick re-run cannot double-
send. All schedule maths in Europe/London.

## 2. Caps, quiet hours, cooldowns (the don't-be-annoying contract)

- Quiet hours default **22:30–07:30** (settings-overridable). Nothing pushes inside
  them; `high` priority ops alerts are the only exception (health-sync broken can wait
  till morning — a down sibling API can too; the exception exists for future genuine
  urgency, and v1 ships with **zero** rules marked high).
- **Daily cap: 5 pushes** (briefing counts as 1). Beyond it, nudges land inbox-only.
- Per-rule cooldowns in §3 — a dismissed nudge silences that rule's re-fire for the
  cooldown; an **actioned** one resets the rule's underlying condition anyway.
- Snooze options surfaced in UI/ntfy actions: 3h, tomorrow, next week.

## 3. Rule catalogue v1

Each rule: *condition → timing → dedupe_key → cooldown → template sketch*. Thresholds
marked ⚙ live in `habits.config_json` / settings (values discussed in PRIVATE.md, not
here).

1. **morning-briefing** — daily 07:35. dedupe `briefing:<date>`. The anchor push:
   weather (home + office day verdict if today), calendar top lines, streak states,
   gym-gap status, occasions inside lead window, goal delta since last week (label
   only, no figures in push), memory note ("1 year since …" when journal_days has a
   hit). Composed by `briefing.py` from the same proposals the rules emit — the
   briefing *is* the digest of rules, not a second brain. `composed_by='rules'` v1;
   LLM polish is HANDOFF Q10.
2. **gym-day** — reshaped per HANDOFF Q11: the expectation is **office-day-linked**.
   On a confirmed office day (geofence arrival) that isn't the configured exempt
   day ⚙ (PRIVATE §4 — it can swap weeks, so it's config) with no gym session
   logged by 16:45 → propose at 16:45 ("in the office with no
   session yet — gym on the way home?"). Fallback floor regardless of location: no
   gym session in ⚙4 days → 17:45 nudge. A day counts as done when EITHER a
   qualifying workout (`wtype ∈ gym set ⚙`) OR a gym `habit_events` row exists —
   the gym-geofence arrival (API §3 `kind: gym`) writes the latter, so
   machine-only sessions the watch never records still count, for both the
   done-today check and the gap floor. Walks never satisfy this rule. dedupe
   `gym:<date>`, cooldown 24h. Tone: invitation, not guilt.
3. **reading** — habit `reading` has no `habit_events` in ⚙2 days → 21:15 push with
   the one-tap action ("20 minutes tonight? ✓ = logged"). The ntfy action button hits
   `act/{token}` which both marks actioned AND writes the habit_event — the loop
   closes without opening any app. dedupe `reading:<date>`, cooldown 24h.
4. **michi-streak-guard** — Michi snapshot: `streak_days > 0 && !studied_today` and
   local time ≥ 20:00 → push linking straight to michi's PWA. dedupe
   `michi:<date>`, no cooldown (it's inherently once/day). Skips silently if snapshot
   stale — never nag off dead data (applies to every rule: **stale in, silent out**).
5. **birthday-gift** — occasion within `lead_days` and no `gift_ideas` row with
   status `bought` linked to it → weekly prompt (Sunday briefing slot + one midweek
   push), escalating copy at ≤7 days. dedupe `gift:<occasion_id>:<year>:<week>`.
   Uses the vault: if ideas exist but unbought, the push lists idea *titles* (names of
   people are fine in pushes — prices/URLs stay in-app).
6. **office-day** — evening-before (18:30) verdict for tomorrow from: calendar events
   whose location/title match office patterns ⚙, weather (rain shifts the
   recommendation, commute is walk/train — PRIVATE), this week's office count vs
   target ⚙, and any all-day OOO events. Template: "Tomorrow reads like an office
   day: <reasons>." dedupe `office:<date>`. It *suggests*; it doesn't track compliance
   beyond the geofence events feeding history. Config (from HANDOFF Q2, values in
   PRIVATE §3): a weekly **target pattern** distinguishing habitual office days from
   *aspirational* ones — the rule leans encouraging on the aspirational days he
   historically skips, stays quiet about the habitual ones, and skips bank holidays
   (the employer-matching feed, API §6). Weather shifts the *framing* of the
   walk-commute, not the verdict. Honestly heuristic v1 — ship dumb, observe, sharpen.
7. **occasion-reminder** — non-birthday occasions at lead_days and again at 2 days.
   dedupe `occ:<id>:<offset>`.
8. **ops: health-sync-stale** — no `ingest:health` sync_run success in 36h → inbox +
   morning mention (not an evening push). dedupe `ops-health:<date>`.
9. **ops: sibling-down** — sibling snapshot failing 3 consecutive polls → inbox +
   morning mention, auto-resolving note when it recovers. dedupe `ops-<app>:<date>`.
10. **goal-milestone** — Kakeibo pct crosses a 5% boundary → celebratory push (label
    only: "House pot just crossed another 5% 🎉"). dedupe `goal:<pct5>`.
11. **japan-countdown** — 60/30/14/7/1 days → briefing line + push at 30/7. dedupe
    `japan:<days>`. (Sunsets after the trip; the memory engine takes over.)
12. **low-movement** — from HANDOFF Q11: by 18:30, steps < ⚙ threshold AND no workout
    of any type today → one gentle push ("barely moved today — even a short evening
    walk counts"). A gym `habit_events` row today (the geofence arrival, or any hand
    log) counts as a workout here — being at the gym is movement even when the watch
    recorded nothing. Walks don't satisfy rule 2, but they're exactly what this rule
    asks for. dedupe `move:<date>`, inherently daily; **suppressed if rule 2 already
    fired today** — never two movement pokes in one day.

Adding a rule = one module in `coach/rules/`, registered, with tests for condition,
dedupe and template redaction — the catalogue is designed to grow (ideas parked for
v2: sleep-debt gentle flag, book recommendations riding the reading history
(Mishka-style, HANDOFF Q1), "no memory_events this weekend — go do something" — each
needs the §0 sniff test before building).

## 4. Timing tolerance

Every rule's timing is quarter-hour-safe by design (nothing needs sub-15-min
precision); `scheduled_for` carries the intended minute so delivery order is stable
even when a tick is late. If the Mac slept through ticks, the next tick delivers
what's still relevant and **expires** proposals whose moment passed (`expired` status)
— a 9am machine wake must not fire last night's 21:15 reading nudge.

## 5. Voice

Second person, warm, brief, zero exclamation-mark abuse, Aizome-household personality
(the same register as Michi's encouragement strings). Every template answers three
things in ≤2 sentences: what was noticed, why it might matter today, the one-tap next
step. Never "you failed to", never streak-shaming, never more than one emoji. The
coach celebrates at least as often as it prompts (rules 10–11 and briefing wins exist
for this reason). Templates live beside their rules and are reviewed as copy, not
code, in Phase 6 acceptance.

## 6. Away mode

The coach must not poke at the gym/office/reading routine while Mack is on holiday —
the calendar already knows (`coach/away.py`, born of a real holiday's misplaced
low-movement nudge on day one in production).

- **Detection:** today (Europe/London) falls inside any ingested all-day
  `calendar_events` row spanning ≥ `min_days` (default **3** — a two-night trip).
  ICS all-day DTEND is **exclusive**: a 06→14 July holiday covers the 6th–13th; the
  coach is back on the 14th. Settings key `away_detection`
  (`{"min_days": 3, "exclude_titles": ["…substring…"]}`) tunes the floor and excludes
  non-trip spans by case-insensitive title substring. When several qualifying events
  cover today, the longest wins for the surfaced title/until.
- **Override:** settings key `away_override`
  (`{"away_until": "YYYY-MM-DD", "title": "…"}`) forces away through that date
  (inclusive) regardless of the calendar — for the trip that never hit a feed.
- **Suppression:** while away, the rules in settings key `away_suppressed_rules`
  (default **gym-day, office-day, low-movement, reading**) are skipped at evaluate
  time — no nudge rows, no expired rows, counted as `away` in the tick counts
  (same accounting shape as `not_configured`). Everything else — briefing,
  michi-streak-guard, birthday-gift, occasion-reminder, ops rules, goal-milestone,
  japan-countdown — runs as normal: streaks and people don't pause for holidays.
- **Briefing:** opens with "You're away — {title}. The coach is off your back until
  you're home. ☀️" (title omitted gracefully when the event has none), and the
  weather line is suppressed — it frames a Glasgow commute, meaningless abroad.
  Calendar, occasion and Japan lines stay. The title follows the §3.5 person-name
  precedent (calendar titles are fine in pushes) and still rides the runtime
  redaction gate like every line.
- **Dashboard:** the aggregate carries `away: {"title", "until"} | null` for both
  roles — household-level and harmless.
