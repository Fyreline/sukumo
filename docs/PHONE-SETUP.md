# Sukumo — Phone setup (generic, no secrets)

The user-facing steps for wiring a phone into Sukumo's ingest endpoints. This doc is
committed, so it carries **no real tokens, coordinates, or private URLs** — only the
public API hostname. Actual token values live wherever they were handed over at mint
time (and can always be re-minted: `scripts/mint_ingest_token.py`; rotation = mint
new, update the one client, revoke old — AUTH.md §3). The health-sync Shortcut and
geofence automations have their own checklist in PRIVATE.md (DEPLOYMENT §5); this doc
covers the app-based sources.

## 1. Overland — passive location (API.md §3b)

[Overland](https://overland.p3k.app) is a free, open-source background GPS logger.
It POSTs batches straight to Sukumo — no third-party service ever sees a point.

1. **Install** "Overland GPS Tracker" from the App Store (by Aaron Parecki / p3k).
2. **Mint a token** on the household Mac (scope `ingest`, bound to the primary user):

   ```
   cd ~/Documents/Dev/sukumo/apps/server
   .venv/bin/python scripts/mint_ingest_token.py --name overland-<person>-iphone --scope ingest --user-id 1
   ```

   Copy the raw token — it is shown exactly once.
3. **Point the app at Sukumo.** In Overland's settings:
   - *Receiver Endpoint URL*: `https://sukumo-api.mishka-hub.com/api/ingest/location`
   - *Access token*: paste the raw token. Overland sends it as
     `Authorization: Bearer …` — the standard ingest door. **Never** put the token
     in the URL itself; query strings end up in server access logs (the endpoint
     rejects that path anyway — API.md §3b).
   - *Device ID*: anything memorable (it isn't stored server-side).
4. **Battery / logging mode:** choose **Significant Location Changes** (or the
   adaptive/"trip only" mode on newer builds) rather than continuous best-accuracy
   logging — it's the difference between negligible and noticeable battery drain,
   and the daily aggregate only needs the shape of the day, not a point per second.
   Points with accuracy worse than 100 m are discarded server-side regardless.
5. **Grant "Always" location permission** when iOS asks (Settings → Overland →
   Location → Always + Precise), or background logging silently stops.
6. **Verify:** walk around the block, open Overland and tap *Send Now*, then check
   the Ops/status tile (or `GET /api/status`) for a fresh `ingest:location` row.
   Tomorrow's journal day gains a Route card if the day has ≥2 usable points.

What the phone sends and what happens to it: raw points live 90 days
(`location_points`), the daily trace/distance/away-minutes aggregate lives forever
in the journal (`stats_json`), and location appears **only** in the primary-only
journal — never the dashboard, the partner portal, or any push (MEMORY.md §2).

## 2. Health sync + Shortcuts geofences

Covered by API.md §2 (health payload paths A/B) and §3 (generic events). The concrete
shortcut steps, geofence list and rebuild notes are deliberately in PRIVATE.md — they
name real places.

## 3. Notifications

Subscribe the ntfy iOS app to the household topic (the topic string is in
PRIVATE.md; it is unguessable and never committed) — API.md §5.
