# Phase 8 — Verify & ship (owner: Fable)

Production: LaunchAgents, tunnel ingress, Pages deploy, backups, phone-side setup —
then the end-to-end proof. Nothing here is new code; it's the household deployment
muscle plus honest verification (HANDOFF's standing rule).

## Build
1. LaunchAgents per DEPLOYMENT §1/3: `com.sukumo.api|coach|journal|backup` —
   `.venv/bin/python` direct (the TCC lesson), logs under `~/Library/Logs/sukumo/`.
2. Tunnel ingress per DEPLOYMENT §2 + DNS route; **sibling health checks after**.
3. Pages workflow (Michi's, retargeted), `VITE_API_BASE` → tunnel hostname; CORS
   allows the Pages origin.
4. `scripts/backup_db.py` + agent; restore drill (open a backup copy, count rows).
5. Phone setup per DEPLOYMENT §5: retarget the health-sync Shortcut → prod URL, ntfy
   subscription, office geofence + reading Shortcuts, PWA install from Pages.
6. Seed session with Mack (HANDOFF Q8): people, occasions, gift ideas, habit configs,
   PRIVATE.md filled; Japan trip range set.

## Acceptance (the ship gate — every line on real devices/networks)
- [ ] Phone on 4G (not home wifi): login → bridge paints through the tunnel < 2s warm.
- [ ] The health-sync Shortcut automation hits prod twice daily (sync_runs shows it);
      disable it → 36h later the ops rule surfaces in the briefing (or time-travel
      test the rule against a prod db copy).
- [ ] Overnight in prod: 02:30 journal row, 03:30 backup file, 07:35 briefing push —
      all three timestamps from logs, same morning.
- [ ] Office geofence arrival → memory_event within a minute; reading one-tap from
      the home screen → habit_event.
- [ ] `launchctl` list shows all agents healthy after a Mac reboot (actually reboot).
- [ ] All sibling APIs still answer post-ingress-change; bus POST from a Michi-side
      script buzzes the phone.
- [ ] `git check-ignore docs/PRIVATE.md data/ .env` all ignored; repo grep for
      birthdays/coords/figures clean before any visibility change.
- [ ] PLAN §6 success-criteria review scheduled: calendar occasion "Sukumo six-week
      review" auto-created — the app tracks its own material-difference test.
