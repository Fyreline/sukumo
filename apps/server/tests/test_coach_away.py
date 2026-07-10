"""Away mode — docs/COACH.md §6, against a frozen clock and a fixtured db.

Covers: detection off a multi-day all-day event (inside / after the exclusive
DTEND / under the min_days floor / title-substring exclusion / manual
override / longest-event-wins), the engine's evaluate-time suppression (no
nudge rows AT ALL, counted as ``away``, non-suppressed rules unaffected), the
briefing's away line + weather suppression, and redaction survival for a
title carrying digits. All fixture data is synthetic (ARCHITECTURE §5.5).
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app import notify
from app.coach import briefing as briefing_module
from app.coach import engine
from app.coach.away import away_status
from app.config import get_settings
from app.db import SessionLocal
from app.models import Nudge
from tests.coach_helpers import (
    add_all_day_event,
    add_habit,
    add_health_sample,
    add_setting,
    add_snapshot,
    london,
)
from tests.conftest import make_user

# The synthetic 8-day holiday: 06 July -> DTEND 14 July (exclusive), so the
# away days are the 6th through the 13th.
HOLIDAY_TITLE = "Somewhere with friends"


def _holiday():
    add_all_day_event(title=HOLIDAY_TITLE, start="2026-07-06", end_exclusive="2026-07-14")


def _status(now):
    with SessionLocal() as db:
        return away_status(db, now)


def _primary() -> int:
    return make_user(email="mack@example.com", role="primary")


async def _tick(now):
    with SessionLocal() as db:
        return await engine.tick(db, get_settings(), now, poll=False)


def _nudges(rule_key: str):
    with SessionLocal() as db:
        return [n for n in db.scalars(select(Nudge)).all() if n.rule_key == rule_key]


# ============================================================================
# detection (away.away_status)
# ============================================================================
def test_away_inside_a_multi_day_all_day_event():
    _holiday()
    status = _status(london(2026, 7, 11, 9, 0))
    assert status.away is True
    assert status.title == HOLIDAY_TITLE
    assert status.until == date(2026, 7, 13)  # last away day — DTEND exclusive


def test_not_away_on_the_exclusive_dtend_date():
    _holiday()
    assert _status(london(2026, 7, 14, 9, 0)).away is False  # home on the 14th
    assert _status(london(2026, 7, 5, 9, 0)).away is False  # not yet started


def test_two_day_event_is_under_the_min_days_floor():
    add_all_day_event(title="City hop", start="2026-07-06", end_exclusive="2026-07-08")
    assert _status(london(2026, 7, 7, 9, 0)).away is False


def test_min_days_is_settings_tunable():
    add_all_day_event(title="City hop", start="2026-07-06", end_exclusive="2026-07-08")
    add_setting("away_detection", {"min_days": 2})
    assert _status(london(2026, 7, 7, 9, 0)).away is True


def test_single_day_event_without_dtend_never_triggers():
    add_all_day_event(title="Car MOT", start="2026-07-11", end_exclusive=None)
    assert _status(london(2026, 7, 11, 9, 0)).away is False


def test_non_all_day_events_are_ignored():
    # a week-long timed event (all_day=0) must not read as a holiday
    from app.models import CalendarEvent

    with SessionLocal() as db:
        db.add(
            CalendarEvent(
                ics_uid="test:timed", starts_at="2026-07-06 09:00:00", ends_at="2026-07-14 17:00:00",
                all_day=0, title="Long conference", calendar_name="test",
            )
        )
        db.commit()
    assert _status(london(2026, 7, 11, 9, 0)).away is False


def test_exclusion_by_case_insensitive_title_substring():
    _holiday()
    add_setting("away_detection", {"exclude_titles": ["somewhere WITH"]})
    assert _status(london(2026, 7, 11, 9, 0)).away is False


def test_manual_override_forces_away_without_any_event():
    add_setting("away_override", {"away_until": "2026-07-20", "title": "Off grid"})
    status = _status(london(2026, 7, 11, 9, 0))
    assert status.away is True
    assert status.title == "Off grid"
    assert status.until == date(2026, 7, 20)  # inclusive


def test_expired_override_falls_through_to_the_calendar():
    add_setting("away_override", {"away_until": "2026-07-01", "title": "Off grid"})
    _holiday()
    status = _status(london(2026, 7, 11, 9, 0))
    assert status.away is True and status.title == HOLIDAY_TITLE


def test_longest_overlapping_event_wins_title_and_until():
    _holiday()  # 8 days
    add_all_day_event(title="Wedding weekend", start="2026-07-10", end_exclusive="2026-07-13")  # 3 days
    status = _status(london(2026, 7, 11, 9, 0))
    assert status.title == HOLIDAY_TITLE and status.until == date(2026, 7, 13)


# ============================================================================
# engine suppression (COACH §6: skipped ENTIRELY, counted as 'away')
# ============================================================================
def _gym_habit(uid):
    add_habit(uid, "gym", config={"wtypes": ["strength"], "gap_floor_days": 4}, evidence="workouts:wtype in cfg")


@pytest.mark.anyio
async def test_gym_day_fires_normally_when_home():
    uid = _primary()
    _gym_habit(uid)
    await _tick(london(2026, 7, 15, 17, 45))  # fallback floor, no gym in 4 days
    assert _nudges("gym-day")


@pytest.mark.anyio
async def test_gym_day_writes_no_rows_at_all_while_away():
    uid = _primary()
    _gym_habit(uid)
    add_all_day_event(title=HOLIDAY_TITLE, start="2026-07-13", end_exclusive="2026-07-18")
    result = await _tick(london(2026, 7, 15, 17, 45))  # same scenario + away event
    assert _nudges("gym-day") == []  # no nudge rows, no expired rows
    assert result["counts"]["away"] >= 1


@pytest.mark.anyio
async def test_low_movement_suppressed_while_away():
    uid = _primary()
    add_setting("low_movement", {"step_threshold": 5000})
    add_health_sample(uid, "step_count", 1200, london(2026, 7, 15, 12, 0))
    add_all_day_event(title=HOLIDAY_TITLE, start="2026-07-13", end_exclusive="2026-07-18")
    await _tick(london(2026, 7, 15, 18, 30))
    assert _nudges("low-movement") == []


@pytest.mark.anyio
async def test_michi_streak_guard_still_fires_while_away():
    _primary()
    add_all_day_event(title=HOLIDAY_TITLE, start="2026-07-13", end_exclusive="2026-07-18")
    add_snapshot("michi", True, {"streak_days": 9, "studied_today": False}, london(2026, 7, 15, 19, 55))
    await _tick(london(2026, 7, 15, 20, 5))
    michi = _nudges("michi-streak-guard")
    assert michi and michi[0].status == "sent"  # streaks don't pause for holidays


@pytest.mark.anyio
async def test_suppressed_set_is_settings_overridable():
    _primary()
    add_all_day_event(title=HOLIDAY_TITLE, start="2026-07-13", end_exclusive="2026-07-18")
    add_setting("away_suppressed_rules", ["michi-streak-guard"])
    add_snapshot("michi", True, {"streak_days": 9, "studied_today": False}, london(2026, 7, 15, 19, 55))
    result = await _tick(london(2026, 7, 15, 20, 5))
    assert _nudges("michi-streak-guard") == []
    assert result["counts"]["away"] == 1


# ============================================================================
# briefing (COACH §6: away line leads, weather suppressed)
# ============================================================================
def _rainy_weather_snapshot(now):
    add_snapshot(
        "weather",
        True,
        {"office": {"daily": {"precipitation_probability_max": [90]}}},
        now,
    )


def test_briefing_opens_with_away_line_and_no_weather():
    _primary()
    _holiday()
    now = london(2026, 7, 11, 7, 40)
    _rainy_weather_snapshot(now)
    with SessionLocal() as db:
        content_md, push_body = briefing_module.compose(db, now, get_settings(), [])
    assert f"You're away — {HOLIDAY_TITLE}. The coach is off your back until you're home. ☀️" in content_md
    assert "Rain" not in content_md and "brolly" not in content_md  # weather suppressed
    assert push_body.startswith("You're away")


def test_briefing_away_line_graceful_without_title():
    _primary()
    add_all_day_event(title=None, start="2026-07-06", end_exclusive="2026-07-14")
    with SessionLocal() as db:
        content_md, _ = briefing_module.compose(db, london(2026, 7, 11, 7, 40), get_settings(), [])
    assert "You're away — the coach is off your back until you're home. ☀️" in content_md


def test_briefing_weather_present_when_home():
    _primary()
    now = london(2026, 7, 20, 7, 40)
    _rainy_weather_snapshot(now)
    with SessionLocal() as db:
        content_md, _ = briefing_module.compose(db, now, get_settings(), [])
    assert "Rain looks likely" in content_md and "You're away" not in content_md


def test_away_line_with_figures_in_title_survives_the_runtime_gate():
    # A calendar title carrying money/health-shaped figures must be stripped
    # by notify.redact, never crash the pipeline (COACH §6 / ARCHITECTURE §5.2).
    _primary()
    add_all_day_event(title="Trip costing £1,234 and 6.2 hours away", start="2026-07-06", end_exclusive="2026-07-14")
    with SessionLocal() as db:
        content_md, push_body = briefing_module.compose(db, london(2026, 7, 11, 7, 40), get_settings(), [])
    safe_body, violations = notify.redact(push_body)
    assert violations  # the gate caught the figures…
    assert "£1,234" not in safe_body and "6.2 hours" not in safe_body  # …and stripped them
    assert "You're away" in safe_body  # without losing the line itself
