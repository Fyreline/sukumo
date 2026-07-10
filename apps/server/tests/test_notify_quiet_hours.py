"""Quiet-hours hold — docs/COACH.md §2, docs/phases/PHASE-5-notify.md
acceptance: "send at 23:00 -> held till 07:30 window; unit-test with frozen
clock." ``quiet_hours_hold`` is a pure function of ``now``, so these tests
pass an explicit frozen instant rather than needing a clock-mocking
library."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app import notify

LONDON = ZoneInfo("Europe/London")
DEFAULT = "22:30-07:30"


def _london(y, m, d, h, mi) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=LONDON)


def test_23_00_is_held_until_07_30_the_next_morning():
    now = _london(2026, 7, 10, 23, 0)
    held = notify.quiet_hours_hold(now, DEFAULT)
    assert held is not None
    held_london = held.astimezone(LONDON)
    assert held_london.date().isoformat() == "2026-07-11"
    assert (held_london.hour, held_london.minute) == (7, 30)


def test_12_00_is_immediate():
    now = _london(2026, 7, 10, 12, 0)
    assert notify.quiet_hours_hold(now, DEFAULT) is None


def test_07_00_is_held_until_07_30_the_same_morning():
    now = _london(2026, 7, 10, 7, 0)
    held = notify.quiet_hours_hold(now, DEFAULT)
    assert held is not None
    held_london = held.astimezone(LONDON)
    assert held_london.date().isoformat() == "2026-07-10"
    assert (held_london.hour, held_london.minute) == (7, 30)


def test_exactly_22_30_is_held():
    now = _london(2026, 7, 10, 22, 30)
    assert notify.quiet_hours_hold(now, DEFAULT) is not None


def test_exactly_07_30_is_not_held():
    # the window is [start, end) -- 07:30 itself is back in daytime.
    now = _london(2026, 7, 10, 7, 30)
    assert notify.quiet_hours_hold(now, DEFAULT) is None


def test_a_utc_instant_is_converted_to_london_before_the_check():
    # 23:00 BST (UTC+1 in July) == 22:00 UTC -- passing the UTC instant must
    # still land inside the LONDON-local quiet window.
    from datetime import timezone

    now_utc = datetime(2026, 7, 10, 22, 0, tzinfo=timezone.utc)
    held = notify.quiet_hours_hold(now_utc, DEFAULT)
    assert held is not None
    assert held.astimezone(LONDON).time().isoformat(timespec="minutes") == "07:30"


def test_custom_non_wrapping_window():
    # a sanity check for the non-midnight-wrapping branch, e.g. a lunch hold.
    now = _london(2026, 7, 10, 12, 30)
    held = notify.quiet_hours_hold(now, "12:00-13:00")
    assert held is not None
    assert held.astimezone(LONDON).time().isoformat(timespec="minutes") == "13:00"

    now_outside = _london(2026, 7, 10, 14, 0)
    assert notify.quiet_hours_hold(now_outside, "12:00-13:00") is None
