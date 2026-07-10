# Honmaru — Design

The brief: **ukiyo-e meets mission control.** The Cyberpunk-companion fantasy delivered
through the household's woodblock language — data-dense like a command bridge, but
washi-and-indigo calm, never neon. Phone-first (it's a PWA on Mack's home screen);
desktop gets the same bridge with more columns.

## 1. Theme

`apps/web/src/theme.css` is a **mirror** of the canonical Aizome palette
(`learningLanguageMachine/apps/web/src/theme.css`). Phase 1 adds
`DST_HONMARU="/Users/mack/Documents/Dev/honmaru/apps/web/src/theme.css"` to
`learningLanguageMachine/scripts/sync-theme.sh` and updates the canonical header's
MIRRORS list. Semantic token names are frozen household-wide; Honmaru introduces **no
new tokens** — if a need appears, it's an edit to the canonical file synced everywhere.

Usage grammar (consistent with siblings): paper ground; `ink` text; `clay` (hanko
crimson) is *the* accent — coach moments, the keep glyph, primary actions; `sky` info +
partner accent; `olive` success/streaks-alive; `kraft` warnings/stale; `fig` occasions &
affection (birthdays, memory hearts); `liquid` the connector — here it is the **thread**:
the timeline line in the journal and the tile-connecting hairlines on the bridge.
Data-viz ramp (`viz-1..4`) for sparklines/rings only. Dark mode = night print, free via
tokens; verify every tile in both.

## 2. App identity

Name on screen: **Honmaru** with the keep glyph — a minimal woodblock castle-keep mark
in clay, doubling as PWA icon (maskable, paper ground). The cat appears here too:
Mishka sits *on the keep roof* in the empty/loading states (household continuity, one
cat, many jobs). Type: the household stack (match Michi's DESIGN choices verbatim).

## 3. The Bridge (`BridgePage`) — the morning tab

One scroll, tiles in priority order, painted from ONE `/api/dashboard` call (skeleton
shimmer until it lands, cached-last-response shown instantly via service worker with a
`stale` chip if offline):

1. **Today** — date, weather glyph strip (home/office), briefing_md rendered, Japan
   countdown chip while active. The coach's face; clay left-border.
2. **Vitals** — 4 stat chips (steps, sleep, active kcal, workouts-this-week) each with
   a 14-day sparkline. Neutral display, no targets colouring except streak-linked ones.
3. **Streaks** — habit cards: name, flame/state, gap phrasing ("last: yesterday"),
   auto habits show their evidence source icon; tap habits (reading) show the big
   one-tap log button.
4. **House goal** — Kakeibo pct ring + pace label + "as of" age. Numbers visible here
   (it's the authed app, not a push).
5. **People** — next occasions inside 45 days, lead-status pill (gift: none/ideas/
   bought ✓ in olive), tap → PeoplePage.
6. **Memory strip** — last 7 day-dots on the liquid thread, sized by event_count,
   tap → journal day. Anniversary line when present ("one year since …", fig).
7. **Castle status (Ops)** — one row per sibling + per source: green/kraft/clay dot,
   age, latency. The infra-monitor payoff; tap → `/api/status` detail with sync_runs.
8. **Nudge inbox chip** — pending/snoozed count, tap → NudgeInbox.

Tiles degrade independently — a dead sibling greys its tile with the stale age; the
bridge never blanks because one source is down (mirrors ARCHITECTURE §5.6 honesty).

## 4. Motion & feel

`motion` (the household's library): tiles rise-in with stagger on first paint only
(<300ms total, respects `prefers-reduced-motion`); sparklines draw once; the one-tap
log gives a hanko-stamp press animation (scale + clay ink-spread) — the app's single
signature flourish, reused for nudge "actioned". No parallax, no persistent ambient
motion — mission-control calm.

## 5. PWA shell

`manifest.webmanifest`: standalone, portrait, paper/ink theme colours (both schemes),
maskable keep icon set. Service worker: precache app shell, network-first for `/api`
with last-good-response fallback (bridge must paint on the train), **never** cache
auth or act endpoints. Install prompt: a quiet Settings row, not a nag banner. iOS
A2HS tested through the tunnel domain in Phase 8 acceptance (16.4+ requirement met
household-wide).

## 6. Accessibility

Contrast per household bar (AA on paper and night print — the palette already passes;
don't undermine it with opacity tricks); every sparkline/ring carries a text
equivalent; touch targets ≥44px; the whole bridge navigable with VoiceOver reading
sensible tile summaries (aria-label composed from the same data as the visuals).
