# Honmaru — Build Plan

**Codename: Honmaru** (本丸 — the innermost keep of a Japanese castle: the command post
everything else defends and reports to). This is the app discussed as "Aizome HQ" — but
*Aizome* is the household **palette's** name, shared by every app, so naming one app after
it would be like naming a ship "Navy". Honmaru says what this app is: the keep at the
centre of the household castle, where Mishka Hub, Michi, Kakeibo and the Japan dashboard
all report in. Alternatives considered: *Tenshu* (天守, the keep's tower — close second,
slightly harder to say), *Genkan* (玄関, entrance hall — too passive), *Butai* (舞台,
stage — wrong metaphor). **If Mack prefers "Aizome HQ" it's a one-grep rename; asked in
[HANDOFF.md](HANDOFF.md) Q13.**

Docs-first (this suite), then phased implementation with explicit owners, same as Michi
and Kakeibo. Model policy per household preference: **Sonnet for well-specified ports/
scaffolds and API integrations, Opus for the judgement-heavy coach-rule engine, Fable for
the dashboard visuals and final verification.** Every phase ends at its doc's acceptance
criteria, independently verified by the orchestrator (run the code, not the report —
subagent claims are not evidence).

> ⚠️ **Standing disclaimer, repeated wherever health appears:** Honmaru *displays and
> summarises* data Mack's devices already record (Apple Health, workouts, sleep). It is
> not a medical device, makes no diagnoses or predictions, and its nudges are lifestyle
> reminders ("you haven't gymmed in 4 days"), never health advice. See COACH.md §0.

## 1. Who this is for (the real brief)

A single primary user (see [PRIVATE.md](PRIVATE.md), gitignored — real birthdays, office
arrangements, locations and figures live there, never here), UK/Scotland-based, with a
partner who may get a read-only or lightweight account later (HANDOFF Q9). The brief, in
Mack's own framing:

- **"Unless it makes a material difference I just won't bother using it."** This is the
  design law of the whole app. Every feature must survive the filter: *does it work with
  zero or near-zero manual entry?* Data arrives passively (Apple Health export, sibling
  apps' APIs, calendar feeds, Shortcuts automations) or, where a human signal is truly
  unavoidable (reading, gift ideas), it costs **one tap**.
- **A companion, not a form.** The app should *reach out* — phone nudges to read more,
  a poke when the gym gap grows, "tomorrow looks like an office day", "X's birthday is
  in 3 weeks, your gift vault is empty" — like the calm-competent AI companion out of a
  video game, minus the dystopia. Encouraging in tone, never nagging (caps, cooldowns
  and quiet hours are hard requirements, COACH.md §4).
- **The keep unifies the castle.** Tiles for Michi's study streak, Kakeibo's house-goal
  number, Mishka Hub activity, Japan countdown — plus operational status of each
  sibling's API, so Honmaru doubles as the household infra monitor.
- **A memory engine** that assembles each day from data already generated (photos,
  films logged, words learned, places, calendar) into a scrollable journal — with the
  **Japan trip (Sept 2026) as its inaugural, densest chapter**. This sets the only hard
  deadline in the plan: journal assembly working before ~10 Sept 2026.
- All UK: British English, GBP where money shows, Europe/London time everywhere a
  schedule fires.

> **Why this section reads generically:** this repo may be public, same policy as
> Kakeibo. Real personal specifics (birthdays, office details, home/office coordinates,
> gym thresholds) live only in [PRIVATE.md](PRIVATE.md) (gitignored) and in runtime DB/
> config — never in committed docs, seed data, or source.

## 2. What Honmaru is (and is not)

**Is:** a self-hosted life dashboard (PWA) + a scheduled "coach" process that ingests
passive data, evaluates a rule catalogue, and delivers nudges to Mack's phone; a
household status board; an automatic journal.

**Is not:** a medical tool; a to-do app (no task lists — the siblings and calendar own
their domains); a chat bot (the coach speaks in scheduled, structured moments, not
conversation); a second copy of any sibling's data (it reads their APIs live and caches
thinly, DATA_MODEL.md §6).

**Deferred by explicit decision (2026-07-10):** native iOS companion app (HealthKit
background sync, lock-screen widgets, Live Activities) — web/PWA first; the $99 Apple
Developer licence is the price of that later phase, TestFlight covers both household
phones when it comes. Home-control (Home Assistant frontend) — shelved, not enough
controllable hardware yet.

## 3. Goals, ranked

1. **Vitals without effort** — steps, sleep, workouts, stand/energy flowing in from
   Health Auto Export with zero taps; freshness monitored, breakage nudged (ops rule).
2. **The coach** — the rule catalogue of COACH.md §3 live: gym-gap, reading, Michi
   streak guard, birthday gift lead-time, office-day suggestion, morning briefing.
3. **One dashboard** — the tab that's worth opening every morning: today's briefing,
   vitals, streaks, house goal, upcoming occasions, memory strip, sibling status.
4. **Memory engine** — days assembled automatically; weekly digest; Japan chapter
   ready for September.
5. **Life admin vault** — people, occasions, gift ideas: the only intentionally manual
   corner, entered rarely, surfaced by the coach at the right moment.
6. **Notification bus** — one `notify()` pipe every household app/script can POST to
   (API.md §5), so Michi's LaunchAgent failing or Kakeibo spotting something odd gains
   a voice through Honmaru rather than each app growing its own.

## 4. The doc suite (reading order for implementers)

| Doc | Owns |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | repo layout, stack, ports, processes, PWA shell |
| [DATA_MODEL.md](DATA_MODEL.md) | every table, uniqueness keys, retention |
| [API.md](API.md) | Honmaru's REST surface + every ingestion contract (Health Auto Export payload, sibling read endpoints, ICS, weather, Shortcuts) |
| [AUTH.md](AUTH.md) | Mishka-identity proxy login (Michi's pattern), ingest tokens |
| [COACH.md](COACH.md) | the rule engine: catalogue, scheduling, tone, caps, delivery |
| [MEMORY.md](MEMORY.md) | journal assembly, sources, weekly digest, Japan mode |
| [DESIGN.md](DESIGN.md) | the bridge layout, tiles, Aizome usage, PWA install |
| [DEPLOYMENT.md](DEPLOYMENT.md) | LaunchAgents, tunnel ingress, Pages, backups |
| [HANDOFF.md](HANDOFF.md) | open questions blocking real data — **read before building** |
| [PRIVATE.md](PRIVATE.md) | gitignored; the real specifics + fill-in checklist |

## 5. Phases (details in docs/phases/)

| Phase | Owner | Delivers |
|---|---|---|
| [1 — Scaffold](phases/PHASE-1-scaffold.md) | Sonnet | repo, web+server skeletons, auth port, theme mirror, dev servers |
| [2 — Ingestion core](phases/PHASE-2-ingestion.md) | Sonnet | health webhook + storage, generic event ingest, sync_runs, freshness |
| [3 — Siblings](phases/PHASE-3-siblings.md) | Sonnet | service-token read endpoints on Michi/Kakeibo/Mishka + Honmaru clients + status board |
| [4 — Dashboard v1](phases/PHASE-4-dashboard.md) | Fable | the bridge: tiles live off real ingested data, PWA installable |
| [5 — Notify bus](phases/PHASE-5-notify.md) | Sonnet | `notify()` core, ntfy delivery, nudge inbox API + UI, action endpoints |
| [6 — Coach](phases/PHASE-6-coach.md) | Opus | rule engine + catalogue + briefing composer + coach LaunchAgent |
| [7 — Memory engine](phases/PHASE-7-memory.md) | Opus build / Fable journal UI | day assembly, digest, journal + Japan chapter UI |
| [8 — Verify & ship](phases/PHASE-8-verify-ship.md) | Fable | LaunchAgents, tunnel, backups, E2E through the tunnel from a phone |

Sequencing note: phases 2–3 unblock 4; 5 unblocks 6; 7 rides on 2's event store and
must land **before 2026-09-10** (Japan). Everything else is pressure-free.

## 6. Success criteria (the material-difference test, six weeks post-ship)

- Mack opens the dashboard ≥5 mornings/week without forcing himself.
- ≥3 coach nudges/week get *actioned* (not dismissed) — the encourage-don't-nag proof.
- Zero manual entry needed for vitals/streak/goal tiles in normal operation.
- A birthday passes with the gift bought ≥1 week early because Honmaru raised it.
- The Japan journal exists day-by-day without either of them doing anything during
  the trip beyond living it and taking photos.
