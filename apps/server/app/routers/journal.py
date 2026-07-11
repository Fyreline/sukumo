"""Journal day / digest read API — docs/MEMORY.md §3-5, docs/API.md §1,
docs/phases/PHASE-7-memory.md item 6.

    GET   /api/journal/{date}   one assembled day (+ its events + anniversary)
    GET   /api/journal?from=&to=   a span of assembled days (list)
    GET   /api/journal/{date}/photos   that day's per-photo metadata (MEMORY §5)
    GET   /api/photos/{uuid}/thumb     small derivative JPEG — NEVER an original
    PATCH /api/journal/{date}   set mood — the ONE optional human field
    GET   /api/digests?kind=    weekly / trip digests

Every route is **primary-only** (403 for role='partner'), the same door as
routers/people.py: the journal is primary-only at v1 (the partner portal never
renders it — DESIGN §3). JWT required; assembly is a server-side job, so there
is no create/delete here — only reads and the single ``mood`` tap.

The two photo routes are plain ``def`` (threadpool) on purpose: osxphotos work
is sync and the first call after a restart parses the Photos library — that
must not block the event loop under the rest of the API.
"""
from __future__ import annotations

import json
import re
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import DATA_DIR
from ..db import get_session
from ..errors import SukumoHTTPException
from ..memory import photos as photos_mod
from ..memory.assemble import _events_for, anniversary
from ..models import Digest, JournalDay, User

router = APIRouter(tags=["journal"])

THUMBS_DIR = DATA_DIR / "thumbs"  # data/ is gitignored — thumbs never reach the repo

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MOODS = {"great", "good", "ok", "low", "rough"}
_DIGEST_KINDS = ("weekly", "trip")


def primary_only(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> int:
    """The journal door: role='primary' only (v1), mirroring people.py."""
    user = session.get(User, user_id)
    if user is None or user.role != "primary":
        raise SukumoHTTPException(
            status_code=403, detail="The journal is primary-only at v1", code="forbidden"
        )
    return user_id


def _valid_date(value: str, field: str) -> str:
    if not _DATE_RE.match(value):
        raise SukumoHTTPException(
            status_code=422, detail=f"{field} must be 'YYYY-MM-DD'", code="validation_error"
        )
    try:
        date.fromisoformat(value)
    except ValueError:
        raise SukumoHTTPException(
            status_code=422, detail=f"{field} is not a real date", code="validation_error"
        )
    return value


def _day_dict(jd: JournalDay, *, events: list | None = None) -> dict:
    out = {
        "local_date": jd.local_date,
        "assembled_at": jd.assembled_at,
        "summary_md": jd.summary_md,
        "stats": json.loads(jd.stats_json or "{}"),
        "event_count": jd.event_count,
        "mood": jd.mood,
    }
    if events is not None:
        out["events"] = [
            {
                "kind": e.kind,
                "ts": e.ts,
                "title": e.title,
                "detail": _safe_json(e.detail_json),
                "source": e.source,
            }
            for e in events
        ]
    return out


def _safe_json(raw: str) -> dict:
    try:
        d = json.loads(raw or "{}")
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


@router.get("/journal/{day}")
async def get_journal_day(
    day: str, user_id: int = Depends(primary_only), session: Session = Depends(get_session)
) -> dict:
    _valid_date(day, "date")
    jd = session.get(JournalDay, day)
    if jd is None:
        raise SukumoHTTPException(
            status_code=404, detail="No journal for that day yet", code="not_found"
        )
    events = _events_for(session, day)
    out = _day_dict(jd, events=events)
    out["anniversary"] = anniversary(session, day)
    return out


@router.get("/journal")
async def list_journal_days(
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    user_id: int = Depends(primary_only),
    session: Session = Depends(get_session),
) -> dict:
    _valid_date(from_, "from")
    _valid_date(to, "to")
    if from_ > to:
        raise SukumoHTTPException(
            status_code=422, detail="'from' must be on or before 'to'", code="validation_error"
        )
    rows = session.scalars(
        select(JournalDay)
        .where(JournalDay.local_date >= from_, JournalDay.local_date <= to)
        .order_by(JournalDay.local_date.desc())
    ).all()
    return {"days": [_day_dict(jd) for jd in rows]}


@router.get("/journal/{day}/photos")
def get_journal_day_photos(
    day: str, user_id: int = Depends(primary_only), session: Session = Depends(get_session)
) -> dict:
    """The day's per-photo metadata — {uuid, taken_at, place} each — for the
    journal's thumbnail strip (MEMORY §5). ``configured`` is false (with an
    empty list) when no Photos library is wired up, so the UI can say so
    honestly instead of spinning."""
    _valid_date(day, "date")
    library = photos_mod.resolve_library_path(session)
    if not library or not photos_mod.library_exists(library):
        return {"date": day, "photos": [], "configured": False}
    return {"date": day, "photos": photos_mod.photos_for_date(library, day), "configured": True}


@router.get("/photos/{uuid}/thumb")
def get_photo_thumb(
    uuid: str, user_id: int = Depends(primary_only), session: Session = Depends(get_session)
) -> FileResponse:
    """A small derivative JPEG for one photo — the ONLY pixel-shaped thing the
    API ever serves, and never an original (memory/photos.py export_thumb).
    Primary-only like the rest of the journal; 404 for unknown/invalid uuids.
    Deliberately NOT service-worker cached (sw.ts allow-lists /api/dashboard
    alone) — an authed, private response stays out of shared caches too."""
    library = photos_mod.resolve_library_path(session)
    if not library or not photos_mod.library_exists(library):
        raise SukumoHTTPException(status_code=404, detail="No photo library configured", code="not_found")
    path = photos_mod.export_thumb(library, uuid, THUMBS_DIR)
    if path is None:
        raise SukumoHTTPException(status_code=404, detail="No thumbnail for that photo", code="not_found")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


class MoodPatch(BaseModel):
    mood: str | None = None


@router.patch("/journal/{day}")
async def patch_journal_mood(
    day: str,
    body: MoodPatch,
    user_id: int = Depends(primary_only),
    session: Session = Depends(get_session),
) -> dict:
    _valid_date(day, "date")
    if body.mood is not None and body.mood not in _MOODS:
        raise SukumoHTTPException(
            status_code=422, detail=f"mood must be one of {sorted(_MOODS)} or null", code="validation_error"
        )
    jd = session.get(JournalDay, day)
    if jd is None:
        raise SukumoHTTPException(
            status_code=404, detail="No journal for that day yet", code="not_found"
        )
    jd.mood = body.mood  # the one human field — set or cleared, never required
    session.commit()
    session.refresh(jd)
    return _day_dict(jd)


@router.get("/digests")
async def list_digests(
    kind: str | None = Query(None),
    user_id: int = Depends(primary_only),
    session: Session = Depends(get_session),
) -> dict:
    if kind is not None and kind not in _DIGEST_KINDS:
        raise SukumoHTTPException(
            status_code=422, detail=f"kind must be one of {_DIGEST_KINDS}", code="validation_error"
        )
    stmt = select(Digest)
    if kind is not None:
        stmt = stmt.where(Digest.kind == kind)
    rows = session.scalars(stmt.order_by(Digest.period_start.desc())).all()
    return {
        "digests": [
            {
                "id": d.id,
                "kind": d.kind,
                "period_start": d.period_start,
                "period_end": d.period_end,
                "content_md": d.content_md,
                "sent_at": d.sent_at,
            }
            for d in rows
        ]
    }
