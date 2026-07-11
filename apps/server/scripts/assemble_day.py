#!/usr/bin/env python3
"""Nightly journal assembly entrypoint — docs/ARCHITECTURE.md §2,
docs/MEMORY.md §3, docs/phases/PHASE-7-memory.md items 2-3, 5.

Env-driven like scripts/coach_tick.py / poll_sources.py; runnable as
``python scripts/assemble_day.py``. Deployed by Phase 8 via
deploy/com.sukumo.journal.plist (daily 02:30) — this script is NOT loaded here.

Modes::

    assemble_day.py                 # nightly: yesterday + re-run yesterday-1,
                                    #   + Sunday weekly digest, + trip-range check
    assemble_day.py --date D        # (re)assemble one local day D
    assemble_day.py --from A --to B # backfill an inclusive [A, B] span
    assemble_day.py --backfill      # backfill the full data span (launch-day
                                    #   history: everything already in the well)

Every run writes a ``sync_runs`` row (source ``journal:assemble``) so silence
is diagnosable from the Ops tile alone (ARCHITECTURE §5.6). Photos are opt-in:
set ``SUKUMO_PHOTOS_LIBRARY`` (or the ``photos_library_path`` setting) to a
Photos.app library to include per-day photo metadata; unset → skipped
(HANDOFF Q4 graceful-degrade).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal, engine  # noqa: E402
from app.memory import assemble as assemble_mod  # noqa: E402
from app.memory import digest as digest_mod  # noqa: E402
from app.memory import mappers as mappers_mod  # noqa: E402
from app.memory import photos as photos_mod  # noqa: E402
from app.models import Base, SyncRun  # noqa: E402

LONDON = assemble_mod.LONDON


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _photos_library(session) -> str | None:
    """Opt-in library path: env wins, then the settings row, else None —
    the shared resolution now lives in app.memory.photos (the journal's
    thumb endpoints use the same one)."""
    return photos_mod.resolve_library_path(session)


def run(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Sukumo journal assembly")
    parser.add_argument("--date", help="assemble a single local day YYYY-MM-DD")
    parser.add_argument("--from", dest="from_", help="backfill span start YYYY-MM-DD")
    parser.add_argument("--to", dest="to", help="backfill span end YYYY-MM-DD")
    parser.add_argument("--backfill", action="store_true", help="assemble the full data span")
    args = parser.parse_args(argv)

    started_at = _utcnow_str()
    now = datetime.now(timezone.utc)
    session = SessionLocal()
    result: dict = {}
    status = "ok"
    error: str | None = None
    items = 0
    try:
        # Photos (opt-in) first, so their events are in the well before assembly.
        lib = _photos_library(session)
        photo_result = photos_mod.map_photos(session, library_path=lib)
        result["photos"] = photo_result

        if args.date:
            assemble_mod.assemble_day(session, args.date, now=now)
            result["mode"] = "date"
            result["assembled"] = [args.date]
            items = 1
        elif args.from_ and args.to:
            r = assemble_mod.assemble_range(session, args.from_, args.to, now=now)
            result["mode"] = "range"
            result.update(r)
            items = r["days"]
        elif args.backfill:
            # Populate the well from every ride-along source BEFORE measuring
            # its span — the mappers are what turn ingested calendar/sibling
            # history into memory_events, so the backfill bounds must be read
            # after them, not before.
            mappers_mod.run_mappers(session, now)
            bounds = assemble_mod.data_date_bounds(session)
            if bounds is None:
                result["mode"] = "backfill"
                result["days"] = 0
                result["note"] = "empty well — nothing to assemble"
            else:
                start, end = bounds
                r = assemble_mod.assemble_range(session, start, end, now=now)
                result["mode"] = "backfill"
                result["span"] = [start, end]
                result.update(r)
                items = r["days"]
        else:
            r = assemble_mod.assemble_yesterday(session, now=now)
            result["mode"] = "nightly"
            result.update(r)
            items = len(r["assembled"])
            # Sunday: persist the week-in-review digest (also injected into the
            # morning briefing). "Yesterday" (Saturday's date) ends the window.
            today_local = now.astimezone(LONDON).date()
            if today_local.weekday() == 6:  # Sunday
                d = digest_mod.weekly_digest(session, today_local - timedelta(days=1), now=now)
                result["weekly_digest"] = {"period_start": d.period_start, "period_end": d.period_end}
            # Trip range: promote to a trip digest once the flagged range ends.
            result["trip_digest"] = digest_mod.maybe_trip_digest(session, now=now)
    except Exception as exc:  # noqa: BLE001 — record then re-raise for the exit code
        status = "error"
        error = str(exc)
        result["error"] = error
    finally:
        session.add(
            SyncRun(
                source="journal:assemble",
                started_at=started_at,
                finished_at=_utcnow_str(),
                status=status,
                items=items,
                error=error,
            )
        )
        session.commit()
        session.close()
    return result


def main() -> None:
    Base.metadata.create_all(engine)  # no Alembic (ARCHITECTURE §4); mirrors app.main's lifespan
    result = run()
    print(json.dumps(result, indent=2))
    if result.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
