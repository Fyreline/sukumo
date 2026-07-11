#!/usr/bin/env python3
"""One-off (idempotent) repair for the journal-photo filter: before
app/memory/photos.py grew ``is_journal_photo``, the photo mapper counted
EVERY asset in the Photos library — so days read "34 photos" when 30 of them
were Shortcuts-app screenshots, and the thumb strip showed them too.

Same shape as scripts/repair_film_attribution.py (the household's repair
template): don't guess which existing rows are inflated, just

    1. Delete every memory_events row with kind='photo' (provider_uid
       ``photo:<date>`` re-derives deterministically from the library, so
       nothing is lost).
    2. Re-run the (now filtering) photo mapper over the full library
       (``since=None``) — only journal-worthy photos come back, and days
       whose photos were ALL screenshots come back as no row at all.
    3. Re-assemble every journal_day whose local date had a photo event
       before step 1 or after step 2 (assemble_day is deterministic and
       re-runnable per docs/MEMORY.md §3), so the "N photos around X"
       summary line and stats_json counts reflect the filter.
    4. Clear the data/thumbs/ cache wholesale — simpler than proving which
       uuids the filter now excludes, and it rebuilds lazily on the next
       strip open (export_thumb re-checks the filter per uuid anyway).

Idempotent: a second run deletes and recreates the same rows and re-assembles
the same day set (thumbs purged: 0 the second time). Run twice to verify.

Prints counts only — never place names, moment titles or uuids (personal
data, ARCHITECTURE §5.2) — to stdout as JSON, and to a sync_runs row
(source 'repair:photo_filter') like every other maintenance script here.

Usage::

    SUKUMO_DATABASE_URL=sqlite:////path/to/sukumo.db \\
        .venv/bin/python scripts/repair_photo_filter.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import DATA_DIR  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.memory import assemble as assemble_mod  # noqa: E402
from app.memory import photos as photos_mod  # noqa: E402
from app.models import Base, MemoryEvent, SyncRun  # noqa: E402

THUMBS_DIR = DATA_DIR / "thumbs"  # the journal router's cache (routers/journal.py)


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _photo_count(rows: list[MemoryEvent]) -> int:
    """Sum of per-day photo counts across kind='photo' rows (counts only)."""
    total = 0
    for row in rows:
        try:
            total += int(json.loads(row.detail_json or "{}").get("count", 0))
        except (ValueError, TypeError):
            pass
    return total


def _purge_thumbs(thumbs_dir: Path) -> int:
    """Delete every cached thumb JPEG (partials too); returns files removed.
    The cache is purely derivative — it rebuilds lazily, filter-checked."""
    if not thumbs_dir.is_dir():
        return 0
    removed = 0
    for f in thumbs_dir.glob("*.jpg"):
        f.unlink(missing_ok=True)
        removed += 1
    return removed


def repair_photo_filter(
    session: Session, *, library_path: str | None = None, thumbs_dir: Path = THUMBS_DIR
) -> dict:
    """Delete + re-map kind='photo' memory_events with the journal filter,
    re-assemble every affected journal_day, purge the thumb cache. Returns
    counts only (no places/titles/uuids)."""
    before_rows = session.scalars(
        select(MemoryEvent).where(MemoryEvent.kind == "photo")
    ).all()
    before_dates = {assemble_mod._local_date_of(r.ts) for r in before_rows}
    photos_before = _photo_count(before_rows)
    deleted = len(before_rows)
    for row in before_rows:
        session.delete(row)
    session.commit()

    map_result = photos_mod.map_photos(session, library_path=library_path)
    session.commit()

    after_rows = session.scalars(
        select(MemoryEvent).where(MemoryEvent.kind == "photo")
    ).all()
    after_dates = {assemble_mod._local_date_of(r.ts) for r in after_rows}

    affected_dates = sorted(before_dates | after_dates)
    for local_date in affected_dates:
        assemble_mod.assemble_day(session, local_date, run_maps=False)

    return {
        "mapper_status": map_result.get("status"),
        "photo_day_rows_deleted": deleted,
        "photo_day_rows_recreated": len(after_rows),
        "photos_counted_before": photos_before,
        "photos_counted_after": _photo_count(after_rows),
        "journal_days_reassembled": len(affected_dates),
        "thumbs_purged": _purge_thumbs(thumbs_dir),
    }


def run() -> dict:
    Base.metadata.create_all(engine)  # no Alembic (ARCHITECTURE §4)
    started_at = _utcnow_str()
    session = SessionLocal()
    status = "ok"
    error: str | None = None
    result: dict = {}
    try:
        library = photos_mod.resolve_library_path(session)
        result = repair_photo_filter(session, library_path=library)
    except Exception as exc:  # noqa: BLE001 -- record then re-raise for the exit code
        status = "error"
        error = str(exc)
        result["error"] = error
    finally:
        session.add(
            SyncRun(
                source="repair:photo_filter",
                started_at=started_at,
                finished_at=_utcnow_str(),
                status=status,
                items=result.get("photo_day_rows_recreated", 0),
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
