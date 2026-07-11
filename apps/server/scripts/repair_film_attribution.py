#!/usr/bin/env python3
"""One-off (idempotent) repair for the film-attribution bug: before
app/memory/mappers.py::map_films started filtering on ``recent[].user_email``
(Mishka Hub PR: GET /api/activity/service now carries who actually watched
each film), Sukumo's journal mapped the ENTIRE household ``recent`` feed —
so the partner's watches were showing up in the primary user's journal.

This script does not try to guess which existing memory_events(kind='film')
rows are wrong; it's simpler and provably correct to:

    1. Delete every memory_events row with kind='film' (their provider_uid
       can be re-derived deterministically from the stored mishka
       sibling_snapshots, so nothing is lost).
    2. Re-run the (now attribution-aware) film mapper from those same
       snapshots — only the primary user's watches come back.
    3. Re-assemble every journal_day whose local date had a film event
       either before step 1 or after step 2 (assemble_day is deterministic
       and re-runnable per docs/MEMORY.md §3 — a day with no other changes
       comes back byte-identical).

Idempotent: a second run finds the same (now-correct) film rows, deletes and
recreates the same count, and re-assembles the same day set. Run twice to
verify: counts should match.

Prints counts only -- never film titles (personal data, ARCHITECTURE §5.2)
-- to stdout as JSON, and to a sync_runs row (source
'repair:film_attribution') like every other maintenance script in this repo.

Usage::

    SUKUMO_DATABASE_URL=sqlite:////path/to/sukumo.db \\
        .venv/bin/python scripts/repair_film_attribution.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.memory import assemble as assemble_mod  # noqa: E402
from app.memory import mappers as mappers_mod  # noqa: E402
from app.models import Base, MemoryEvent, SyncRun  # noqa: E402


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def repair_film_attribution(session: Session) -> dict:
    """Delete + re-map kind='film' memory_events, then re-assemble every
    affected journal_day. Returns counts only (no titles)."""
    before_rows = session.scalars(
        select(MemoryEvent).where(MemoryEvent.kind == "film")
    ).all()
    before_dates = {assemble_mod._local_date_of(r.ts) for r in before_rows}
    deleted = len(before_rows)
    for row in before_rows:
        session.delete(row)
    session.commit()

    recreated = mappers_mod.map_films(session)
    session.commit()

    after_rows = session.scalars(
        select(MemoryEvent).where(MemoryEvent.kind == "film")
    ).all()
    after_dates = {assemble_mod._local_date_of(r.ts) for r in after_rows}

    affected_dates = sorted(before_dates | after_dates)
    for local_date in affected_dates:
        assemble_mod.assemble_day(session, local_date, run_maps=False)

    return {
        "film_events_deleted": deleted,
        "film_events_recreated": recreated,
        "film_events_remaining": len(after_rows),
        "journal_days_reassembled": len(affected_dates),
    }


def run() -> dict:
    Base.metadata.create_all(engine)  # no Alembic (ARCHITECTURE §4)
    started_at = _utcnow_str()
    session = SessionLocal()
    status = "ok"
    error: str | None = None
    result: dict = {}
    try:
        result = repair_film_attribution(session)
    except Exception as exc:  # noqa: BLE001 -- record then re-raise for the exit code
        status = "error"
        error = str(exc)
        result["error"] = error
    finally:
        session.add(
            SyncRun(
                source="repair:film_attribution",
                started_at=started_at,
                finished_at=_utcnow_str(),
                status=status,
                items=result.get("film_events_recreated", 0),
                error=error,
            )
        )
        session.commit()
        session.close()
    return result


def main() -> None:
    result = run()
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
