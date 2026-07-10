# Honmaru — Handoff: open questions

Read before building. **Blocking** = a phase can't reach acceptance without it; others
have documented defaults that ship unless Mack overrides. Answer inline, tick the box.

- [ ] **Q1 · Reading source (Phase 2/6).** How do you actually read — Kindle, physical,
  both? Kindle has no clean API; default plan is the honest one-tap (Shortcut/ntfy
  action, COACH §3.3). Is one tap per session acceptable, or should reading be a
  briefing-only gentle theme with no tracking at all? *Default: one-tap.*
- [ ] **Q2 · Office-day inputs (Phase 6, blocking for rule 6).** What actually decides
  a good office day? Team/anchor days? Specific meetings in calendar? A per-week
  target? How do you commute, and does weather genuinely matter? (Answers → PRIVATE.md
  §3 + rule config.)
- [ ] **Q3 · Calendar (Phase 2, blocking for calendar ingest).** Google or Apple
  calendar household? Can you produce private ICS URLs for the calendars that matter
  (personal + work if allowed — work calendars often forbid export; if so, say so and
  rule 6 leans on patterns instead)?
- [ ] **Q4 · Photos on the Mac (Phase 7).** Is iCloud Photo Library synced to the
  household Mac (Photos.app with full library)? Yes → osxphotos metadata ingest;
  No → photo lines drop from the journal v1 (counts could come later via Shortcuts).
- [ ] **Q5 · Health Auto Export purchase (Phase 2, blocking).** The REST-API automation
  sits behind its paid tier (~£10 one-off/premium). OK to buy on the household Apple
  ID? (It's the entire vitals pipeline until the native companion exists.)
- [ ] **Q6 · Notification channel comfort.** v1 = ntfy.sh public service, unguessable
  topic, redacted payloads (API §5). Comfortable? Alternatives: self-hosted ntfy
  (another daemon to run) or waiting for web-push. *Default: ntfy.sh as specced.*
- [ ] **Q7 · Sibling patches approval (Phase 3).** Green-light three small read-only
  PRs: Michi `/api/stats/service`, Kakeibo `/api/goal/service`, Mishka
  `/api/activity/service` (API §4 shapes)? They're additive and token-gated.
- [ ] **Q8 · Seed data session.** 30 minutes with the PeoplePage when Phase 4 lands:
  birthdays, occasions, lead-days, first gift ideas. (List to gather: PRIVATE.md §2.)
- [ ] **Q9 · Amy at v1.** She *can* log in (shared identity) — should the bridge show
  a partner view (her Michi streak?), and does she want any nudges? *Default v1:
  coach nudges primary only; bridge is Mack-centric; revisit post-ship.*
- [ ] **Q10 · LLM briefing polish.** Rules-composed briefing v1 (deterministic, free).
  Later: an LLM pass for warmth via API key or a Claude scheduled task (the Kakeibo
  §98 pattern). Worth it, and which mechanism? *Default: rules-only v1.*
- [ ] **Q11 · Gym definition (Phase 6).** Which workout types count for gym-gap, and
  the gap threshold (specced default 3 days)? Also: does "a long walk counts" apply?
- [ ] **Q12 · Geofence comfort.** Two iOS Shortcuts automations (arrive/leave office →
  POST). Fine? (Runs on-device; Honmaru only ever sees the arrive/leave pings.)
  *Default: yes, set up in Phase 8.*
- [ ] **Q13 · The name.** Honmaru (PLAN.md header) vs "Aizome HQ" vs other. Rename is
  cheap **before** Phase 1 mints ports/labels/hostname (`com.honmaru.*`,
  `honmaru-api.mishka-hub.com`); expensive after.

## Standing verification rule

Same as Michi/Kakeibo: the orchestrator independently verifies every phase's
acceptance list by running the code — subagent completion reports are not evidence.
Phase 8's list is the ship gate; nothing is "done" until a real phone, on a non-home
network, receives a real nudge and paints the bridge through the tunnel.
