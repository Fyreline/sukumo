"""Away mode — calendar-detected holidays, docs/COACH.md §6.

The coach must not nag about the gym, the office commute, movement or the
reading chair while Mack is on holiday — the calendar already knows. Detection
is deliberately dumb (COACH §3's "ship dumb, observe, sharpen"): today
(Europe/London) falling inside any ingested all-day ``calendar_events`` row
whose span is at least ``min_days`` (default 3 — i.e. a two-night trip) reads
as away. Single-day and two-day all-day events (bank holidays, birthdays,
"car MOT") never trigger it.

ICS semantics matter here (DATA_MODEL §6): an all-day event's DTEND is
**exclusive**, so a 2026-07-06 → 2026-07-14 holiday covers the 6th through
the 13th and the coach is back on the 14th. ``ends_at`` may be missing
(single-day events often omit DTEND) — that reads as a one-day span.

Two settings knobs (config.py accessor pattern, DATA_MODEL §7):

- ``away_detection``  {"min_days": 3, "exclude_titles": ["…substring…"]} —
  case-insensitive title-substring exclusion for all-day spans that aren't
  trips (e.g. a week-long "Sprint review" placeholder).
- ``away_override``   {"away_until": "YYYY-MM-DD", "title": "…"} — a manual
  switch that forces away through the given date (inclusive) regardless of
  the calendar, for the trip that never made it onto a feed.

When several qualifying events cover today, the longest span wins for the
title/until surfaced to the briefing and dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CalendarEvent
from . import config as coach_config
from .proposals import today_local


@dataclass
class AwayStatus:
    away: bool
    title: str | None = None
    until: date | None = None  # last day away (inclusive) — home the day after

    @classmethod
    def home(cls) -> "AwayStatus":
        return cls(away=False)


def _event_date(ts: str | None) -> date | None:
    """The calendar-date part of a stored ``calendar_events`` timestamp.
    All-day rows are written as ``YYYY-MM-DD 00:00:00`` straight from the ICS
    bare date (clients/calendar._normalize_dt) — the first ten characters ARE
    the local calendar date, no tz conversion to second-guess."""
    if not ts:
        return None
    try:
        return date.fromisoformat(ts[:10])
    except ValueError:
        return None


def _excluded(title: str | None, exclude_titles: list[str]) -> bool:
    if not title:
        return False
    lowered = title.lower()
    return any(sub.lower() in lowered for sub in exclude_titles if isinstance(sub, str) and sub)


def _override_status(session: Session, today: date) -> AwayStatus | None:
    raw = coach_config.get_setting(session, coach_config.KEY_AWAY_OVERRIDE, None)
    if not isinstance(raw, dict):
        return None
    try:
        until = date.fromisoformat(str(raw.get("away_until")))
    except (ValueError, TypeError):
        return None
    if today > until:
        return None  # override expired — fall through to the calendar
    title = raw.get("title")
    return AwayStatus(away=True, title=str(title) if title else None, until=until)


def away_status(session: Session, now: datetime) -> AwayStatus:
    """Is today (Europe/London) an away day? Pure read — tables only, no
    network (COACH §1: rules and their helpers are testable with a frozen
    db + clock)."""
    today = today_local(now)

    override = _override_status(session, today)
    if override is not None:
        return override

    detection = coach_config.get_setting(session, coach_config.KEY_AWAY_DETECTION, None)
    detection = detection if isinstance(detection, dict) else {}
    try:
        min_days = max(1, int(detection.get("min_days", coach_config.DEFAULT_AWAY_MIN_DAYS)))
    except (ValueError, TypeError):
        min_days = coach_config.DEFAULT_AWAY_MIN_DAYS
    exclude_titles = detection.get("exclude_titles")
    exclude_titles = exclude_titles if isinstance(exclude_titles, list) else []

    best: tuple[int, date, str | None] | None = None  # (span_days, end_exclusive, title)
    rows = session.scalars(select(CalendarEvent).where(CalendarEvent.all_day == 1)).all()
    for event in rows:
        start = _event_date(event.starts_at)
        if start is None:
            continue
        # ICS all-day DTEND is exclusive; a missing DTEND means a one-day event.
        end_exclusive = _event_date(event.ends_at) or (start + timedelta(days=1))
        span_days = (end_exclusive - start).days
        if span_days < min_days:
            continue
        if not (start <= today < end_exclusive):
            continue
        if _excluded(event.title, exclude_titles):
            continue
        if best is None or span_days > best[0]:
            best = (span_days, end_exclusive, event.title)

    if best is None:
        return AwayStatus.home()
    span_days, end_exclusive, title = best
    title = title.strip() if title else None
    return AwayStatus(away=True, title=title or None, until=end_exclusive - timedelta(days=1))
