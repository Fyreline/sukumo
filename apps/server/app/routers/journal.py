"""Journal day / digest read API — docs/MEMORY.md §3-5, docs/API.md §1,
docs/phases/PHASE-7-memory.md item 6.

    GET   /api/journal/{date}   one assembled day (+ its events + anniversary)
    GET   /api/journal?from=&to=   a span of assembled days (list)
    PATCH /api/journal/{date}   set mood — the ONE optional human field
    GET   /api/digests?kind=    weekly / trip digests

Every route is **primary-only** (403 for role='partner'), the same door as
routers/people.py: the journal is primary-only at v1 (the partner portal never
renders it — DESIGN §3). JWT required; assembly is a server-side job, so there
is no create/delete here — only reads and the single ``mood`` tap.
"""
from __future__ import annotations

import json
import re
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..errors import SukumoHTTPException
from ..memory.assemble import _events_for, anniversary
from ..models import Digest, JournalDay, User

router = APIRouter(tags=["journal"])

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
