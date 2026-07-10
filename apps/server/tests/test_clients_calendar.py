"""app.clients.calendar -- ICS parsing + recurrence expansion within the
rolling window (DATA_MODEL.md #6, docs/phases/PHASE-2-ingestion.md build
item 5). Uses ONLY the synthetic fixture at tests/fixtures/sample_calendar.ics
-- invented UIDs/dates, no relation to any real feed."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.clients import calendar as calendar_client

FIXTURE = Path(__file__).parent / "fixtures" / "sample_calendar.ics"
NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


def _load() -> bytes:
    return FIXTURE.read_bytes()


def test_parse_events_reads_calendar_name():
    events = calendar_client.parse_events(_load(), now=NOW)
    assert all(e["calendar_name"] == "Sample Household Calendar" for e in events)


def test_parse_events_includes_events_within_window():
    events = calendar_client.parse_events(_load(), now=NOW)
    titles = {e["title"] for e in events}
    assert "Team Sync" in titles


def test_parse_events_excludes_events_outside_window():
    events = calendar_client.parse_events(_load(), now=NOW)
    titles = {e["title"] for e in events}
    assert "Old One-off Event" not in titles
    assert "Far Future Event" not in titles


def test_yearly_recurring_birthday_lands_within_future_window():
    """The rolling window is past 30d -> future 400d specifically so a
    yearly RRULE always produces at least one upcoming occurrence."""
    events = calendar_client.parse_events(_load(), now=NOW)
    birthdays = [e for e in events if e["title"] == "Sample Birthday"]
    assert len(birthdays) >= 1
    assert all(e["starts_at"].startswith("2026-09-22") or e["starts_at"].startswith("2027-") for e in birthdays)


def test_all_day_event_flagged_and_normalized_to_midnight():
    events = calendar_client.parse_events(_load(), now=NOW)
    birthday = next(e for e in events if e["title"] == "Sample Birthday")
    assert birthday["all_day"] == 1
    assert birthday["starts_at"].endswith("00:00:00")


def test_timed_event_not_flagged_all_day_and_converted_to_utc():
    events = calendar_client.parse_events(_load(), now=NOW)
    sync = next(e for e in events if e["title"] == "Team Sync")
    assert sync["all_day"] == 0
    assert sync["starts_at"] == "2026-06-15 09:00:00"
    assert sync["ends_at"] == "2026-06-15 10:00:00"
    assert sync["location"] == "Meeting Room 3"


def test_parsing_twice_is_stable_row_count():
    """DATA_MODEL #6: ICS has no deltas, so a feed poll is a pure function
    of (bytes, now) -- parsing the same bytes twice must yield the same
    event set (the acceptance list's "calendar fixture poll twice -> stable
    row count", exercised at the parser level; scripts/poll_sources.py's
    delete+replace is covered in test_poll_sources.py)."""
    first = calendar_client.parse_events(_load(), now=NOW)
    second = calendar_client.parse_events(_load(), now=NOW)
    assert len(first) == len(second)
    assert {(e["ics_uid"], e["starts_at"]) for e in first} == {(e["ics_uid"], e["starts_at"]) for e in second}
