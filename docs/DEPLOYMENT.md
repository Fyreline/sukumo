# Sukumo — Deployment

The Michi/Kakeibo pattern, fourth verse: **web static on GitHub Pages, uvicorn behind
the shared Cloudflare Tunnel + LaunchAgents on the household Mac.** Values here are the
single source of truth for ports/labels (ARCHITECTURE §2 mirrors them).

## 1. Matrix

| Thing | Value |
|---|---|
| API prod | LaunchAgent `com.sukumo.api`, uvicorn `127.0.0.1:8300`, `data/sukumo.db`, no `--reload` |
| API dev | launch.json `sukumo-api`, port `8301`, dev db |
| Web dev | launch.json `sukumo-web`, port `5179` |
| Web prod | GitHub Pages from `apps/web` build (Michi's workflow, `VITE_API_BASE=https://sukumo-api.mishka-hub.com`) |
| Tunnel | `sukumo-api.mishka-hub.com` → `http://127.0.0.1:8300` |
| Coach | `com.sukumo.coach`, StartInterval 900 |
| Journal | `com.sukumo.journal`, daily 02:30 |
| Backup | `com.sukumo.backup`, daily 03:30 |

## 2. Tunnel ingress (shared household tunnel — edit with care)

Root LaunchDaemon shared by all apps; config `~/.cloudflared/config.yml`. Add the
hostname **above** the catch-all 404:

```yaml
  - hostname: sukumo-api.mishka-hub.com
    service: http://127.0.0.1:8300
```

Then `cloudflared tunnel route dns <tunnel-name> sukumo-api.mishka-hub.com`, restart
the daemon, and verify **the siblings still answer** (`michi-api…/api/health`,
`kakeibo-api…/api/health`, Mishka's hostname) before calling it done — the standing
household rule for touching shared ingress.

## 3. LaunchAgents

Copy `com.michi.api`'s plist per agent, swap label/paths/port; logs to
`~/Library/Logs/sukumo/`. **Standing household lessons (learned on Kakeibo):**

1. Any LaunchAgent touching `~/Documents` must invoke `.venv/bin/python` directly
   (not via shell wrappers) or macOS TCC prompts eat it silently.
2. Verify with `launchctl bootstrap gui/$(id -u) …` then check the log actually grew.
3. Scheduled agents run `scripts/*.py` entrypoints that exit — never long-lived loops
   (uvicorn is the one KeepAlive agent).

## 4. Backups

`scripts/backup_db.py` — port of Michi's: sqlite3 `.backup()` API (WAL-safe, never `cp`
a live db) → `data/backups/sukumo-<ts>.db`, prune to 30. The DB *is* the private data
store (birthdays, gift ideas, health rows) — backups stay on the household Mac, which
is itself Time-Machine'd; nothing leaves the house.

## 5. Phone-side setup (the PRIVATE.md checklist expands this)

The health-sync Shortcut + its two automations (API.md §2a), ntfy app subscribed to
the private topic, further Shortcuts automations (office geofence ×2, reading
one-tap), PWA installed from the Pages URL. Each item has a verify step in Phase 8 — a deploy isn't done until a
real nudge has arrived on the real phone through the real tunnel.

## 6. Repo visibility

Same policy as Kakeibo: repo may go public. `.gitignore` covers `data/`, `.env`,
`docs/PRIVATE.md`, `*.db`. The standing check before any commit adding docs: no
birthdays, coordinates, figures, employer/venue names. (The 22 Sep constraint in
PRIVATE.md is doubly sensitive — it's a surprise.)
