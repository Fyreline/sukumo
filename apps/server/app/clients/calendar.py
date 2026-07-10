"""ICS calendar subscription poller -- docs/API.md #6,
docs/phases/PHASE-2-ingestion.md build item 5.

docs/ARCHITECTURE.md #5.1 (hard rule): read-only -- this module must never
issue a write HTTP verb (POST/PUT/DELETE). It only fetches + parses; the DB
"full-window replace" write lives in scripts/poll_sources.py so this module
stays a thin, framework-free parser (easy to fixture-test without a DB).

Dependency choice (documented per docs/phases/PHASE-2-ingestion.md): the
``ics`` package's recurrence support is thin (no RRULE/EXDATE expansion), so
this uses ``icalendar`` (RFC 5545 parsing, handles Apple's published-feed
quirks) + ``recurring-ical-events`` (expands RRULE/EXDATE within a rolling
window) instead -- the combination the recurring-ical-events project itself
exists for.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import icalendar
import recurring_ical_events

# Rolling window: past 30 days -> future 400 days, so yearly recurring
# events (birthdays) always land at least once (DATA_MODEL #6).
WINDOW_PAST_DAYS = 30
WINDOW_FUTURE_DAYS = 400


async def fetch_ics(url: str, timeout: float = 15.0) -> bytes:
    """Read-only GET of a published ICS feed."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


def _normalize_dt(value: datetime | date | None) -> tuple[str | None, bool]:
    """Returns (naive UTC 'YYYY-MM-DD HH:MM:SS' string, all_day)."""
    if value is None:
        return None, False
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.strftime("%Y-%m-%d %H:%M:%S"), False
    # a bare `date` (all-day event, no time component)
    return f"{value.isoformat()} 00:00:00", True


def parse_events(
    ics_bytes: bytes,
    now: datetime | None = None,
    window_past_days: int = WINDOW_PAST_DAYS,
    window_future_days: int = WINDOW_FUTURE_DAYS,
) -> list[dict]:
    """Parses an ICS feed and expands recurring events within the rolling
    window. Returns plain dicts shaped for calendar_events (DATA_MODEL #6),
    never SQLAlchemy objects -- callers own the DB write."""
    cal = icalendar.Calendar.from_ical(ics_bytes)
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=window_past_days)
    window_end = now + timedelta(days=window_future_days)

    occurrences = recurring_ical_events.of(cal).between(window_start, window_end)

    calendar_name = None
    calname = cal.get("X-WR-CALNAME")
    if calname:
        calendar_name = str(calname)

    events: list[dict] = []
    for component in occurrences:
        uid = str(component.get("UID", "")).strip()
        if not uid:
            continue
        dtstart = component.get("DTSTART")
        dtend = component.get("DTEND")
        starts_at, all_day = _normalize_dt(dtstart.dt if dtstart else None)
        if starts_at is None:
            continue
        ends_at, _ = _normalize_dt(dtend.dt if dtend else None)

        summary = component.get("SUMMARY")
        location = component.get("LOCATION")
        events.append(
            {
                "ics_uid": uid,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "all_day": 1 if all_day else 0,
                "title": str(summary) if summary else None,
                "location": str(location) if location else None,
                "calendar_name": calendar_name,
            }
        )
    return events
