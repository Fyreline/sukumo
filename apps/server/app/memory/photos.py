"""Photo metadata mapper + journal thumbnails — docs/MEMORY.md §2/§5, HANDOFF Q4.

**Metadata first.** This module reads *counts, time ranges and place names* out
of a macOS Photos library via ``osxphotos`` and writes one ``memory_events``
row per local day (kind ``photo``). The mapper NEVER copies, exports, uploads
or reads image pixels; originals are not required (Q4: osxphotos reads metadata
fine on an optimised-storage library).

**Journal-worthy only.** Every path here — mapper, day listing, thumb export —
shares ONE predicate, ``is_journal_photo``: screenshots, screen recordings,
hidden and trashed assets never count, never list, never thumb (MEMORY §2).

**Thumbnails (MEMORY §5).** The journal's photo strip is served small
*derivative* JPEGs on demand: ``photos_for_date`` lists a day's per-photo
metadata grouped by moment (Photos' own event clusters, time-gap fallback)
and ``export_thumb`` converts the SMALLEST existing Photos derivative
(never an original) into a ≤512px JPEG cached under ``data/thumbs/`` —
gitignored, served only to the authed primary (routers/journal.py). No image
ever leaves the household: the tunnel-fronted API is the same authed door as
every other journal read.

**Opt-in.** Everything here is inert unless a library path is supplied (env
``SUKUMO_PHOTOS_LIBRARY`` or the ``photos_library_path`` setting — see
``resolve_library_path``; the test suite never sets either, so assembly is
hermetic). With no path — or with osxphotos absent, or the path missing — the
mapper returns ``{"status": "not_configured"}`` and writes nothing. This is
the graceful-degrade path when HANDOFF Q4 is "no library".
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from collections import Counter
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


def is_journal_photo(photo) -> bool:
    """THE shared journal-photo predicate (docs/MEMORY.md §2) — one function so
    the nightly mapper, the day listing and the thumb exporter can never
    disagree about what counts as a memory.

    Excludes exactly four osxphotos.PhotoInfo flags (all verified properties
    on osxphotos 0.76.x): ``screenshot``, ``screen_recording``, ``hidden``,
    ``intrash``. Nothing else — saved WhatsApp images etc. stay; the user's
    complaint was Shortcuts-app screenshots flooding the strip, not "curate
    my camera roll". Defaults are falsy so a photo object missing a flag
    (older library schema, test double) passes rather than vanishing."""
    return not (
        bool(getattr(photo, "screenshot", False))
        or bool(getattr(photo, "screen_recording", False))
        or bool(getattr(photo, "hidden", False))
        or bool(getattr(photo, "intrash", False))
    )


def _day_aggregates(library_path: str, since: str | None = None) -> dict[str, dict]:
    """Return ``{local_date: {count, first, last, places:[...]}}`` for the
    library, counting only photos that pass ``is_journal_photo`` (screenshots,
    screen recordings, hidden and trashed assets never reach the well). Pure
    metadata — reads ``photo.date`` (a local datetime) and the reverse-geocoded
    place name only. ``since`` (``YYYY-MM-DD``) bounds the scan for
    incremental nightly runs.

    Import of osxphotos is deferred to call time so the package stays an
    optional dependency: a machine without it simply reports not_configured.
    """
    import osxphotos  # noqa: PLC0415 — optional, deferred so absence degrades gracefully

    db = osxphotos.PhotosDB(dbfile=str(Path(library_path) / "database" / "Photos.sqlite"))
    days: dict[str, dict] = {}
    for photo in db.photos():
        if not is_journal_photo(photo):  # screenshots etc. never reach the well
            continue
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
        # Guard against undated/epoch-stamped imports (real library has a
        # 1970-01-01 outlier) — clock-garbage must not stretch the journal.
        if local_date < "2000-01-01":
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


# ====================== journal thumbnails (MEMORY §5) ======================

# osxphotos photo uuids — strict shape so the thumb cache filename can never
# be steered anywhere (the uuid IS the filename under data/thumbs/).
UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")

THUMB_MAX_PX = 512  # longest edge — a strip thumbnail, nowhere near an original
THUMB_JPEG_QUALITY = "70"  # sips formatOptions; keeps a 512px thumb ≲100KB

# PhotosDB parses the whole library database on open (tens of seconds on a
# real library), so the API process keeps one instance and refreshes it on a
# TTL — new photos appear in the journal only after the nightly mapper runs
# anyway, so a stale handle here costs nothing visible.
_DB_TTL_S = 6 * 3600
_db_lock = threading.Lock()
_db_cache: dict = {"path": None, "db": None, "loaded_at": 0.0}


def resolve_library_path(session: Session) -> str | None:
    """Opt-in library path: env wins, then the settings row, else None —
    the same resolution the nightly agent uses (scripts/assemble_day.py)."""
    env = os.environ.get("SUKUMO_PHOTOS_LIBRARY")
    if env:
        return env
    from ..coach import config as coach_config  # noqa: PLC0415 — avoid import cycle at module load

    setting = coach_config.get_setting(session, "photos_library_path", None)
    return setting if isinstance(setting, str) and setting else None


def _photosdb(library_path: str):
    """A cached osxphotos.PhotosDB for the library (see _DB_TTL_S). Raises
    ImportError when osxphotos is absent — callers degrade to 'no photos'."""
    import osxphotos  # noqa: PLC0415 — optional, deferred so absence degrades gracefully

    with _db_lock:
        fresh = (
            _db_cache["db"] is not None
            and _db_cache["path"] == library_path
            and time.monotonic() - _db_cache["loaded_at"] < _DB_TTL_S
        )
        if not fresh:
            _db_cache["db"] = osxphotos.PhotosDB(
                dbfile=str(Path(library_path) / "database" / "Photos.sqlite")
            )
            _db_cache["path"] = library_path
            _db_cache["loaded_at"] = time.monotonic()
        return _db_cache["db"]


# A new time-gap cluster starts when consecutive (moment-less) photos sit more
# than this far apart — roughly "a different thing happened".
GROUP_GAP_MIN = 90


def photos_for_date(library_path: str, local_date: str) -> list[dict]:
    """One local day's photos, filtered (``is_journal_photo``) and grouped by
    *moment*: ``[{label, start, end, photos: [{uuid, taken_at, place}]}]``,
    groups ordered by start time, photos time-sorted within each.

    Grouping prefers Photos' own event clustering — photos sharing a non-empty
    ``PhotoInfo.moment_info.title`` form one group labelled with it. Photos
    without a usable moment fall back to time-gap clustering (>GROUP_GAP_MIN
    minutes starts a new group) labelled with the cluster's dominant ``place``
    name, or ``None`` (the UI shows the time range instead). Same date
    semantics as the mapper (photo.date is the library's local datetime).
    Metadata only — no pixels touched here."""
    try:
        db = _photosdb(library_path)
    except ImportError:
        return []
    entries: list[dict] = []
    for photo in db.photos():
        if not is_journal_photo(photo):
            continue
        when = photo.date
        if when is None or when.date().isoformat() != local_date:
            continue
        place = getattr(photo, "place", None)
        name = getattr(place, "name", None) if place else None
        moment = getattr(photo, "moment_info", None)
        title = getattr(moment, "title", None) if moment is not None else None
        if not (isinstance(title, str) and title.strip()):
            title = None
        entries.append({"when": when, "uuid": photo.uuid, "place": name, "moment": title})
    entries.sort(key=lambda e: (e["when"].strftime("%H:%M:%S"), e["uuid"]))
    return _group_day_entries(entries)


def _group_day_entries(entries: list[dict]) -> list[dict]:
    """Time-sorted entries → moment groups (see photos_for_date). Pure and
    deterministic: same entries, same groups, always."""
    by_moment: dict[str, list[dict]] = {}
    loose: list[dict] = []
    for e in entries:
        if e["moment"]:
            by_moment.setdefault(e["moment"], []).append(e)
        else:
            loose.append(e)

    groups = [_freeze_group(title, members) for title, members in by_moment.items()]

    cluster: list[dict] = []
    for e in loose:
        if cluster and (e["when"] - cluster[-1]["when"]).total_seconds() > GROUP_GAP_MIN * 60:
            groups.append(_freeze_group(_dominant_place(cluster), cluster))
            cluster = []
        cluster.append(e)
    if cluster:
        groups.append(_freeze_group(_dominant_place(cluster), cluster))

    groups.sort(key=lambda g: (g["start"], g["end"], g["label"] or ""))
    return groups


def _dominant_place(members: list[dict]) -> str | None:
    """The cluster's most common place name (alphabetical on ties, so re-runs
    can't flap between labels); None when nothing is geocoded."""
    counts = Counter(m["place"] for m in members if m["place"])
    if not counts:
        return None
    top = max(counts.values())
    return min(place for place, n in counts.items() if n == top)


def _freeze_group(label: str | None, members: list[dict]) -> dict:
    return {
        "label": label,
        "start": members[0]["when"].strftime("%H:%M"),
        "end": members[-1]["when"].strftime("%H:%M"),
        "photos": [
            {"uuid": m["uuid"], "taken_at": m["when"].strftime("%H:%M"), "place": m["place"]}
            for m in members
        ],
    }


def export_thumb(library_path: str, uuid: str, cache_dir: Path) -> Path | None:
    """A small JPEG thumbnail for one photo, cached at ``cache_dir/{uuid}.jpg``
    so each photo is exported exactly once. Sources the SMALLEST existing
    Photos *derivative* (never the original) and squeezes it through sips to
    ≤512px JPEG. Returns None (→ 404) for unknown uuids, photos the journal
    filter excludes (``is_journal_photo`` — same gate as the listing, so a
    guessed screenshot uuid serves nothing), photos with no local derivative,
    or a failed conversion — never an exception to the router."""
    if not UUID_RE.match(uuid):
        return None
    dest = cache_dir / f"{uuid}.jpg"
    if dest.exists():
        return dest
    try:
        db = _photosdb(library_path)
        photo = db.get_photo(uuid)
    except ImportError:
        return None
    if photo is None or not is_journal_photo(photo):
        return None
    derivatives = [Path(p) for p in (photo.path_derivatives or []) if p and Path(p).exists()]
    if not derivatives:
        return None
    src = min(derivatives, key=lambda p: p.stat().st_size)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_dir / f"{uuid}.partial.jpg"
    try:
        subprocess.run(
            [
                "sips",
                "-s", "format", "jpeg",
                "-s", "formatOptions", THUMB_JPEG_QUALITY,
                "-Z", str(THUMB_MAX_PX),
                str(src),
                "--out", str(tmp),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        tmp.replace(dest)
        return dest
    except (subprocess.SubprocessError, OSError):
        tmp.unlink(missing_ok=True)
        return None
