# Phase 5 — Notification bus (owner: Sonnet)

`notify()` core + ntfy delivery + the nudge lifecycle API/UI. After this phase a
household script can make a phone buzz through one POST — before any coach exists.

## Build
1. `nudges` model + `notify.py`: channel driver interface (`ntfy` v1; `inbox` always),
   ntfy publish via httpx (title/body/priority/tags/actions), **redaction gate** —
   template placeholder allowlist; any digit-bearing value not on it (dates, counts of
   days, small integers ok) is rejected at test time and stripped at runtime with an
   error log. Unit-test the gate with money/sleep-figure examples.
2. `POST /api/notify` (ingest-token scope `notify`): bus entry per API §5 → inbox
   nudge + forward.
3. Nudge lifecycle: `GET /api/nudges`, snooze/dismiss/action routes, signed
   single-use `act/{token}` (AUTH §4) with ntfy action buttons wired.
4. NudgeInbox page: pending/snoozed/history, actions, source tags.
5. First customer: patch Michi's LaunchAgent failure path (or a wrapper script) to
   POST to the bus — proves the "every app gains a voice" goal.

## Acceptance
- [ ] `curl` the bus with the notify token → phone buzzes (real device, ntfy app),
      inbox row exists; `ingest`-scoped token → 403.
- [ ] Notification action button tap → nudge `actioned`, second tap → idempotent
      no-op; expired token → 410.
- [ ] Redaction: a test template containing "£1,234" or "6.2 hr" fails CI; runtime
      strip logged.
- [ ] Quiet-hours check works at the delivery layer (send at 23:00 → held till
      07:30 window; unit-test with frozen clock).
- [ ] pytest + typecheck green (paste output).
