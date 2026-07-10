# Sukumo — Handoff: open questions

All thirteen questions answered 2026-07-10 (Mack's answers paraphrased here; personal
specifics moved to [PRIVATE.md](PRIVATE.md) per the redaction pattern). Two carry
follow-up **actions** rather than blockers. The doc suite has been updated to match —
this file is now the decision record.

- [x] **Q1 · Reading source.** Physical books. One-tap logging confirmed acceptable;
  the real priority is *keeping the habit alive*, tracking is secondary. Added: a
  lightweight `books` table (current read shows on the streak card; finishing one
  becomes a journal milestone — DATA_MODEL §2). Mishka-style book recommendations are
  parked for v2, once reading history has accumulated.
- [x] **Q2 · Office-day inputs.** Answered; the weekly pattern (habitual days,
  aspirational days he tends to skip, and which day is the known laziness risk) lives
  in PRIVATE.md §3. Rule 6 config gains a *target pattern* with habitual vs
  aspirational days — the coach leans encouraging on the aspirational ones. Pattern
  moves week to week; it's a default aim, not a contract.
- [x] **Q3 · Calendar.** Apple household. Work calendar is NOT exportable — rule 6
  leans on patterns + the geofence history; the employer observes a standard public
  bank-holiday calendar (which one + its free ICS feed: PRIVATE.md §3), which Sukumo
  subscribes to so rule 6 skips holidays. There's also a **shared couple calendar**
  (young — only started recently, incomplete; rules must not assume completeness).
  **→ ACTION (Mack, before Phase 2 acceptance): generate private ICS URLs for the
  personal + shared Apple calendars → PRIVATE.md §3.**
- [x] **Q4 · Photos on the Mac.** Unknown — iCloud Photos is on for the phone
  (optimised storage), household-Mac state unverified. **→ ACTION (Phase 7, first
  build item): check Photos.app on the household Mac**; osxphotos reads metadata fine
  even with optimised storage, originals not required. The film-scan photo folder on
  the Windows desktop is parked as a possible v2 watched-folder source (PRIVATE §4).
- [x] **Q5 · Health pipeline cost.** No free iCloud route exists (Health is
  E2E-encrypted device sync only — iCloud+ doesn't change that), so v1 uses the
  **free Shortcuts health-sync automation** (API §2 Path A). Mack confirmed:
  set everything up around the free path, decide on Health Auto Export (~£10) only
  if it proves unreliable. He also rarely browses health data (glances at the watch)
  — so ingest stays **minimal-first**: workouts + steps are the core (they're *coach
  evidence*, not a health browser), sleep next, everything else optional.
- [x] **Q6 · Notification channel.** Mack deferred to the default → **ntfy.sh as
  specced** (unguessable topic, redacted payloads, free iOS app — installing it is
  part of the Phase 8 phone setup). Web-push upgrade reconsidered once the PWA is
  proven on the home screen.
- [x] **Q7 · Sibling patches.** Approved. Phase 3 green-lit as specced.
- [x] **Q8 · Seed data.** Birthdays mostly already exist as events in his calendar →
  PeoplePage gains a **"suggest from calendar" import** (calendar events with
  birthday-shaped titles become candidate people, confirmed manually — DATA_MODEL §3);
  manual top-up after. The 30-minute seed session shrinks to a review.
- [x] **Q9 · Amy at v1.** She can sign in, but realistically won't use it much: the
  `partner` role gets a **slim portal** instead of the full bridge — her Michi streak,
  Mishka recents, Japan countdown, links out to the household apps. No coach, no
  nudges, no finance tile (DESIGN §3). Full partner experience revisited post-ship.
- [x] **Q10 · LLM briefing polish.** Rules-composed v1 confirmed. Later polish rides
  the existing **Claude Code Max subscription via a scheduled task** (the Kakeibo
  pattern) — no API key spend. Revisit post-ship, only if the rules-composed voice
  feels flat in practice.
- [x] **Q11 · Gym definition.** Reshaped the rule (COACH §3.2): the expectation is
  **office-day-linked** — gym on office days, with one configured exempt day
  (specifics: PRIVATE §4), rather than a flat N-day gap; a gap floor stays as
  fallback. **Walks do not count as gym** — but he wants to walk to work most days,
  so a new **low-movement rule** (COACH §3.12) pings gently when a day has neither a
  workout nor meaningful steps.
- [x] **Q12 · Geofence.** Approved — and explicitly fine with *richer* location
  detail, so journal `place` events may carry location names where sources provide
  them (photos, calendar); no extra tracking is added beyond what's already specced.
- [x] **Q13 · The name.** **Sukumo** (蒅) — Mack's pick, keeping the aizome/
  indigo-dyeing theme. Reasoning + considered alternatives (Kon'ya, Aigame) in
  PLAN.md's header; the aigame vat survives as the app glyph (DESIGN §2). Labels/
  hostname minted accordingly (`com.sukumo.*`, `sukumo-api.mishka-hub.com`).

## Outstanding actions (not blockers to starting Phase 1)

1. Mack: private ICS URLs (personal + shared) → PRIVATE.md §3 (needed by Phase 2
   acceptance).
2. Phase 7 first item: verify household-Mac Photos.app library state.
3. Phase 8 seed review: confirm calendar-imported birthday candidates + lead days.

## Standing verification rule

Same as Michi/Kakeibo: the orchestrator independently verifies every phase's
acceptance list by running the code — subagent completion reports are not evidence.
Phase 8's list is the ship gate; nothing is "done" until a real phone, on a non-home
network, receives a real nudge and paints the bridge through the tunnel.
