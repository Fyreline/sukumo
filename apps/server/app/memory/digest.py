"""Digest composers — docs/MEMORY.md §3, docs/phases/PHASE-7-memory.md item 3.

Two digests, both persisted to ``digests`` (DATA_MODEL §5) and read back by
``GET /api/digests`` and the Sunday briefing:

* **Weekly** — the week's ``journal_days`` stitched into a short paragraph plus
  numbers *versus the week before*, and one "moment of the week" (the best-rated
  film or the largest photo cluster). Injected into Sunday's morning briefing.
* **Trip** — a settings-flagged date range (``japan_range``; unset today) whose
  per-day assemblies are promoted into a ``trip`` digest with a cover header
  when the range ends.

Voice (COACH §0/§5): neutral, factual, warm. Counts are displayed, never
judged — no "up/down", no trend or medical-ish commentary on body metrics. The
comparison line states this week's number and last week's, side by side, and
leaves the reading to the reader.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..coach import config as coach_config
from ..models import Digest, JournalDay, MemoryEvent
from .assemble import _detail, _local_date_of, _pretty_date, _stars, _utc_window


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _days_in(session: Session, start: date, end: date) -> list[JournalDay]:
    rows = session.scalars(
        select(JournalDay)
        .where(JournalDay.local_date >= start.isoformat(), JournalDay.local_date <= end.isoformat())
        .order_by(JournalDay.local_date.asc())
    ).all()
    return list(rows)


def _totals(days: list[JournalDay]) -> dict:
    agg = {"steps": 0, "workouts": 0, "study_days": 0, "films": 0, "photos": 0, "logged_days": 0}
    for jd in days:
        try:
            s = json.loads(jd.stats_json or "{}")
        except (ValueError, TypeError):
            s = {}
        agg["steps"] += int(s.get("steps") or 0)
        agg["workouts"] += int(s.get("workouts") or 0)
        agg["study_days"] += 1 if s.get("study") else 0
        agg["films"] += int(s.get("films") or 0)
        agg["photos"] += int(s.get("photos") or 0)
        if jd.event_count or s.get("steps"):
            agg["logged_days"] += 1
    return agg


def _moment_of_week(session: Session, start: date, end: date) -> str | None:
    """Best-rated film in the window, else the largest photo cluster. Neutral,
    celebratory — a single highlight, never a ranking of the person."""
    lo, _ = _utc_window(start.isoformat())
    _, hi = _utc_window(end.isoformat())
    events = session.scalars(
        select(MemoryEvent).where(
            MemoryEvent.kind.in_(("film", "photo")),
            MemoryEvent.ts >= lo,
            MemoryEvent.ts <= hi,
        )
    ).all()
    best_film = None
    best_rating = -1.0
    best_photo = None
    best_photo_n = 0
    for e in events:
        ld = _local_date_of(e.ts)
        if ld < start.isoformat() or ld > end.isoformat():
            continue
        det = _detail(e)
        if e.kind == "film":
            try:
                r = float(det.get("rating"))
            except (ValueError, TypeError):
                r = 0.0
            if r > best_rating:
                best_rating, best_film = r, e
        elif e.kind == "photo":
            n = int(det.get("count") or 0)
            if n > best_photo_n:
                best_photo_n, best_photo = n, e
    if best_film is not None and best_rating >= 4:
        stars = _stars(_detail(best_film).get("rating"))
        return f"Moment of the week: *{best_film.title}* {stars}".strip()
    if best_photo is not None and best_photo_n > 0:
        det = _detail(best_photo)
        where = f" around {det['places'][0]}" if det.get("places") else ""
        return f"Moment of the week: {best_photo_n} photos in one day{where}."
    if best_film is not None:
        stars = _stars(_detail(best_film).get("rating"))
        return f"Moment of the week: *{best_film.title}* {stars}".strip()
    return None


def compose_weekly(session: Session, end_date: date) -> tuple[str, str, str, dict]:
    """Compose the week ending ``end_date`` (inclusive, a 7-day window).

    Returns ``(period_start_iso, period_end_iso, content_md, totals)``. Pure
    read of ``journal_days`` — safe to call from the briefing without writing."""
    start = end_date - timedelta(days=6)
    prev_start = start - timedelta(days=7)
    prev_end = start - timedelta(days=1)

    days = _days_in(session, start, end_date)
    prev_days = _days_in(session, prev_start, prev_end)
    this = _totals(days)
    last = _totals(prev_days)

    if start.month == end_date.month and start.year == end_date.year:
        span = f"{start.day}–{end_date.day} {end_date.strftime('%B %Y')}"
    else:
        span = f"{start.strftime('%-d %b')} – {end_date.strftime('%-d %b %Y')}"
    header = f"# Week in review — {span}"

    # Neutral, side-by-side counts (COACH §0: displayed, never judged).
    def _line(label: str, cur, prev, fmt=str) -> str:
        return f"- {label}: {fmt(cur)} (previous week {fmt(prev)})"

    body_lines = [
        _line("Steps", this["steps"], last["steps"], lambda n: f"{n:,}"),
        _line("Workouts", this["workouts"], last["workouts"]),
        _line("Study days", this["study_days"], last["study_days"]),
        _line("Films", this["films"], last["films"]),
        _line("Photos", this["photos"], last["photos"]),
    ]

    if this["logged_days"] == 0:
        para = "A quiet week — little made it into the journal."
    else:
        para = (
            f"{this['logged_days']} day{'s' if this['logged_days'] != 1 else ''} "
            "left a trace this week."
        )

    parts = [header, "", para, "", "\n".join(body_lines)]
    moment = _moment_of_week(session, start, end_date)
    if moment:
        parts += ["", moment]
    content_md = "\n".join(parts).strip() + "\n"
    return start.isoformat(), end_date.isoformat(), content_md, this


def weekly_digest(session: Session, end_date: date, *, now: datetime | None = None) -> Digest:
    """Compose + upsert the weekly ``digests`` row (kind='weekly', keyed on
    period_start). Idempotent: re-running the same week updates content in
    place rather than duplicating."""
    now = now or datetime.now(timezone.utc)
    period_start, period_end, content_md, _ = compose_weekly(session, end_date)
    row = session.scalar(
        select(Digest).where(Digest.kind == "weekly", Digest.period_start == period_start)
    )
    if row is None:
        row = Digest(
            period_start=period_start,
            period_end=period_end,
            kind="weekly",
            content_md=content_md,
            sent_at=None,
        )
        session.add(row)
    else:
        row.period_end = period_end
        row.content_md = content_md
    session.commit()
    return row


# -------------------------------------------------------------------- trip --
def compose_trip(session: Session, start: date, end: date, *, title: str = "Japan") -> str:
    """Stitch the per-day assemblies of a trip range into one document with a
    cover header (MEMORY §3). Each day's own ``summary_md`` is reused verbatim."""
    days = _days_in(session, start, end)
    totals = _totals(days)
    cover = [
        f"# {title}",
        f"### {_pretty_date(start)} – {_pretty_date(end)}",
        "",
        (
            f"{totals['logged_days']} days · {totals['photos']} photos · "
            f"{totals['films']} films · {totals['steps']:,} steps"
        ),
        "",
        "---",
        "",
    ]
    body = []
    for jd in days:
        body.append(jd.summary_md.strip())
        body.append("")
    return "\n".join(cover + body).strip() + "\n"


def trip_digest(
    session: Session, start: date, end: date, *, title: str = "Japan", now: datetime | None = None
) -> Digest:
    """Compose + upsert a ``trip`` digest for ``[start, end]`` (keyed on
    period_start)."""
    now = now or datetime.now(timezone.utc)
    content_md = compose_trip(session, start, end, title=title)
    row = session.scalar(
        select(Digest).where(Digest.kind == "trip", Digest.period_start == start.isoformat())
    )
    if row is None:
        row = Digest(
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            kind="trip",
            content_md=content_md,
            sent_at=None,
        )
        session.add(row)
    else:
        row.period_end = end.isoformat()
        row.content_md = content_md
    session.commit()
    return row


def maybe_trip_digest(session: Session, *, now: datetime | None = None) -> dict:
    """If a ``japan_range`` (settings) exists and has ended by ``now``, produce
    its trip digest. Range unset today → no-op (fixture-tested). The range
    lives only in runtime settings / PRIVATE.md — never in committed docs."""
    now = now or datetime.now(timezone.utc)
    value = coach_config.get_setting(session, coach_config.KEY_JAPAN_RANGE, None)
    if not isinstance(value, dict) or "start" not in value or "end" not in value:
        return {"status": "not_configured"}
    try:
        start = date.fromisoformat(value["start"])
        end = date.fromisoformat(value["end"])
    except (ValueError, TypeError):
        return {"status": "not_configured"}
    today = now.astimezone(timezone.utc).date()
    if today <= end:
        return {"status": "pending", "ends": end.isoformat()}
    title = value.get("title", "Japan")
    row = trip_digest(session, start, end, title=title, now=now)
    return {"status": "ok", "period_start": row.period_start, "period_end": row.period_end}
