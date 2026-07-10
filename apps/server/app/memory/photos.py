"""Photo metadata mapper — docs/MEMORY.md §2, HANDOFF Q4.

**Metadata only.** This module reads *counts, time ranges and place names* out
of a macOS Photos library via ``osxphotos`` and writes one ``memory_events``
row per local day (kind ``photo``). It NEVER copies, exports, uploads or reads
image pixels; originals are not required (Q4: osxphotos reads metadata fine on
an optimised-storage library). The journal links into Photos with a time-range
deep link — no file ever leaves the Mac.

**Opt-in.** The mapper is inert unless a library path is supplied (the nightly
agent passes ``settings['photos_library_path']``; the test suite never sets it,
so assembly is hermetic). With no path — or with osxphotos absent, or the path
missing — it returns ``{"status": "not_configured"}`` and writes nothing. This
is the graceful-degrade path when HANDOFF Q4 is "no library".
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MemoryEvent

LONDON = ZoneInfo("Europe/London")

DEFAULT_LIBRARY = str(Path.home() / "Pictures" / "Photos Library.photoslibrary")


def library_exists(path: str | None = None) -> bool:
    path = path or DEFAULT_LIBRARY
    return Path(path).exists()


def _day_aggregates(library_path: str, since: str | None = None) -> dict[str, dict]:
    """Return ``{local_date: {count, first, last, places:[...]}}`` for the
    library. Pure metadata — reads ``photo.date`` (a local datetime) and the
    reverse-geocoded place name only. ``since`` (``YYYY-MM-DD``) bounds the
    scan for incremental nightly runs.

    Import of osxphotos is deferred to call time so the package stays an
    optional dependency: a machine without it simply reports not_configured.
    """
    import osxphotos  # noqa: PLC0415 — optional, deferred so absence degrades gracefully

    db = osxphotos.PhotosDB(dbfile=str(Path(library_path) / "database" / "Photos.sqlite"))
    days: dict[str, dict] = {}
    for photo in db.photos():
        when = photo.date  # tz-aware local datetime
        if when is None:
            continue
        local_date = when.date().isoformat()
        if since is not None and local_date < since:
            continue
        bucket = days.setdefault(
            local_date, {"count": 0, "first": None, "last": None, "_places": set()}
        )
        bucket["count"] += 1
        hhmm = when.strftime("%H:%M")
        if bucket["first"] is None or hhmm < bucket["first"]:
            bucket["first"] = hhmm
        if bucket["last"] is None or hhmm > bucket["last"]:
            bucket["last"] = hhmm
        place = getattr(photo, "place", None)
        name = getattr(place, "name", None) if place else None
        if name:
            bucket["_places"].add(name)
    # freeze the place sets into sorted lists (deterministic)
    for bucket in days.values():
        bucket["places"] = sorted(bucket.pop("_places"))
    return days


def map_photos(
    session: Session, *, library_path: str | None = None, since: str | None = None
) -> dict:
    """Write one memory_events(kind='photo') row per local day with photos.

    provider_uid ``photo:<local_date>`` → idempotent per day; re-runs refresh
    the day's count/time-range/places in place. Returns a status dict with
    aggregate counts only (never per-photo detail). ``not_configured`` when no
    library is available — the whole photo path is optional (HANDOFF Q4).
    """
    if not library_path:
        return {"status": "not_configured", "reason": "no library path configured"}
    if not Path(library_path).exists():
        return {"status": "not_configured", "reason": "library path does not exist"}
    try:
        days = _day_aggregates(library_path, since=since)
    except ImportError:
        return {"status": "not_configured", "reason": "osxphotos not installed"}

    created = 0
    for local_date, agg in days.items():
        if agg["count"] <= 0:
            continue
        provider_uid = f"photo:{local_date}"
        # midday-local as the row ts so the day bucket is unambiguous; the
        # real per-photo times live in detail_json's first/last.
        ts = _noon_utc(local_date)
        detail = {
            "count": agg["count"],
            "first": agg["first"],
            "last": agg["last"],
            "places": agg["places"],
        }
        existing = session.scalar(
            select(MemoryEvent).where(
                MemoryEvent.source == "photos", MemoryEvent.provider_uid == provider_uid
            )
        )
        title = f"{agg['count']} photo{'s' if agg['count'] != 1 else ''}"
        if agg["places"]:
            title += f" · {agg['places'][0]}"
        if existing is None:
            session.add(
                MemoryEvent(
                    user_id=None,
                    ts=ts,
                    kind="photo",
                    title=title,
                    detail_json=json.dumps(detail, sort_keys=True),
                    source="photos",
                    provider_uid=provider_uid,
                )
            )
            created += 1
        else:
            existing.ts = ts
            existing.title = title
            existing.detail_json = json.dumps(detail, sort_keys=True)
    session.commit()
    return {"status": "ok", "days": len(days), "created": created}


def _noon_utc(local_date: str) -> str:
    dt = datetime.fromisoformat(f"{local_date}T12:00:00").replace(tzinfo=LONDON)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
