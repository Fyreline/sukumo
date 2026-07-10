"""Per-rule conditions — each rule fires on its condition and ONLY then, and
skips 'not_configured' when its config is absent (docs/COACH.md §3,
docs/phases/PHASE-6-coach.md acceptance)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.coach.rules import (
    birthday_gift,
    goal_milestone,
    japan_countdown,
    morning_briefing,
    occasion_reminder,
    office_day,
    ops_health_sync,
    ops_sibling_down,
)
from app.db import SessionLocal
from app.models import Person, SyncRun
from tests.conftest import make_user
from tests.coach_helpers import (
    add_occasion,
    add_setting,
    add_snapshot,
    london,
    utc_str,
)


def _primary():
    return make_user(email="mack@example.com", role="primary")


def _eval(rule_module, now):
    with SessionLocal() as db:
        return rule_module.evaluate(now, db)


def _add_person(name: str) -> int:
    with SessionLocal() as db:
        p = Person(name=name)
        db.add(p)
        db.commit()
        return p.id


def _add_sync_run(source: str, status: str, started_at) -> None:
    with SessionLocal() as db:
        db.add(SyncRun(source=source, started_at=utc_str(started_at), finished_at=utc_str(started_at), status=status, items=1))
        db.commit()


# ---------------------------------------------------------------- briefing --
def test_briefing_silent_before_0735():
    _primary()
    assert _eval(morning_briefing, london(2026, 7, 15, 7, 0)).proposals == []


def test_briefing_fires_after_0735_and_is_cap_exempt():
    _primary()
    res = _eval(morning_briefing, london(2026, 7, 15, 7, 40))
    assert len(res.proposals) == 1
    assert res.proposals[0].cap_exempt is True
    assert res.proposals[0].dedupe_key == "briefing:2026-07-15"


# ---------------------------------------------------------------- goal ------
def test_goal_milestone_not_configured_without_snapshot():
    _primary()
    assert _eval(goal_milestone, london(2026, 7, 15, 12, 0)).status == "not_configured"


def test_goal_milestone_fires_on_5pct_boundary():
    _primary()
    add_snapshot("kakeibo", True, {"pct": 27.0}, london(2026, 7, 15, 6, 0))
    res = _eval(goal_milestone, london(2026, 7, 15, 12, 0))
    assert len(res.proposals) == 1
    assert res.proposals[0].dedupe_key == "goal:25"


def test_goal_milestone_silent_below_first_boundary():
    _primary()
    add_snapshot("kakeibo", True, {"pct": 3.0}, london(2026, 7, 15, 6, 0))
    assert _eval(goal_milestone, london(2026, 7, 15, 12, 0)).proposals == []


# ---------------------------------------------------------------- japan -----
def test_japan_not_configured_without_range():
    _primary()
    assert _eval(japan_countdown, london(2026, 7, 15, 8, 0)).status == "not_configured"


def test_japan_pushes_at_30_days():
    _primary()
    start = date(2026, 7, 15) + timedelta(days=30)
    add_setting("japan_range", {"start": start.isoformat()})
    res = _eval(japan_countdown, london(2026, 7, 15, 8, 0))
    assert len(res.proposals) == 1
    assert res.proposals[0].push is True
    assert res.proposals[0].dedupe_key == "japan:30"


def test_japan_briefing_only_at_60_days():
    _primary()
    start = date(2026, 7, 15) + timedelta(days=60)
    add_setting("japan_range", {"start": start.isoformat()})
    res = _eval(japan_countdown, london(2026, 7, 15, 8, 0))
    assert len(res.proposals) == 1
    assert res.proposals[0].push is False  # 60 is a briefing line, not a push


def test_japan_silent_off_a_milestone():
    _primary()
    start = date(2026, 7, 15) + timedelta(days=45)
    add_setting("japan_range", {"start": start.isoformat()})
    assert _eval(japan_countdown, london(2026, 7, 15, 8, 0)).proposals == []


# ---------------------------------------------------------------- office ----
def test_office_not_configured_without_pattern():
    _primary()
    assert _eval(office_day, london(2026, 7, 15, 18, 30)).status == "not_configured"


def test_office_fires_for_aspirational_tomorrow():
    _primary()
    # 2026-07-15 is a Wednesday; tomorrow is Thursday
    add_setting("office_pattern", {"aspirational": ["Thu"], "habitual": ["Tue"]})
    res = _eval(office_day, london(2026, 7, 15, 18, 30))
    assert len(res.proposals) == 1
    assert res.proposals[0].dedupe_key == "office:2026-07-16"


def test_office_quiet_for_habitual_tomorrow():
    _primary()
    add_setting("office_pattern", {"aspirational": ["Mon"], "habitual": ["Thu"]})
    assert _eval(office_day, london(2026, 7, 15, 18, 30)).proposals == []


# ---------------------------------------------------------------- occasion --
def test_occasion_reminder_fires_at_two_days():
    _primary()
    target = date(2026, 7, 15) + timedelta(days=2)
    add_occasion(title="Dentist", kind="deadline", date_str=target.isoformat(), recurrence="once", lead_days=21)
    res = _eval(occasion_reminder, london(2026, 7, 15, 10, 5))
    assert len(res.proposals) == 1
    assert res.proposals[0].dedupe_key.endswith(":2")


def test_occasion_reminder_ignores_birthdays():
    _primary()
    target = date(2026, 7, 15) + timedelta(days=2)
    add_occasion(title="Ken", kind="birthday", date_str=target.isoformat(), recurrence="once")
    assert _eval(occasion_reminder, london(2026, 7, 15, 10, 5)).proposals == []


# ---------------------------------------------------------------- birthday --
def test_birthday_gift_fires_on_sunday_within_window():
    _primary()
    pid = _add_person("Ken")
    # 2026-07-19 is a Sunday; birthday six days later
    add_occasion(title="Ken's birthday", kind="birthday", month_day="07-25", person_id=pid, lead_days=21)
    res = _eval(birthday_gift, london(2026, 7, 19, 10, 30))
    assert len(res.proposals) == 1
    assert res.proposals[0].dedupe_key.endswith(":sun")
    assert "Ken" in res.proposals[0].body  # names are fine in pushes


def test_birthday_gift_silent_when_bought():
    _primary()
    pid = _add_person("Ken")
    oid = add_occasion(title="Ken's birthday", kind="birthday", month_day="07-25", person_id=pid, lead_days=21)
    from app.models import GiftIdea

    with SessionLocal() as db:
        db.add(GiftIdea(person_id=pid, idea="a book", status="bought", occasion_id=oid))
        db.commit()
    assert _eval(birthday_gift, london(2026, 7, 19, 10, 30)).proposals == []


def test_birthday_gift_silent_midweek_off_slot():
    _primary()
    pid = _add_person("Ken")
    add_occasion(title="Ken's birthday", kind="birthday", month_day="07-25", person_id=pid, lead_days=21)
    # 2026-07-14 is a Tuesday — neither Sunday nor Wednesday
    assert _eval(birthday_gift, london(2026, 7, 14, 10, 30)).proposals == []


# ---------------------------------------------------------------- ops -------
def test_health_sync_silent_when_never_synced():
    _primary()
    assert _eval(ops_health_sync, london(2026, 7, 15, 7, 40)).proposals == []


def test_health_sync_fires_when_stale():
    _primary()
    _add_sync_run("ingest:health", "ok", london(2026, 7, 13, 12, 0))  # ~43h before 15th 07:40
    res = _eval(ops_health_sync, london(2026, 7, 15, 7, 40))
    assert len(res.proposals) == 1
    assert res.proposals[0].push is False  # morning mention only


def test_health_sync_silent_when_fresh():
    _primary()
    _add_sync_run("ingest:health", "ok", london(2026, 7, 15, 6, 0))
    assert _eval(ops_health_sync, london(2026, 7, 15, 7, 40)).proposals == []


def test_sibling_down_fires_after_three_failures():
    _primary()
    for h in (18, 18, 19):
        add_snapshot("michi", False, None, london(2026, 7, 14, h, 0))
    res = _eval(ops_sibling_down, london(2026, 7, 15, 7, 40))
    downs = [p for p in res.proposals if p.dedupe_key.startswith("ops-michi:")]
    assert len(downs) == 1
    assert downs[0].push is False


def test_sibling_down_silent_when_healthy():
    _primary()
    add_snapshot("michi", True, {"streak_days": 1, "studied_today": True}, london(2026, 7, 15, 6, 0))
    assert not [p for p in _eval(ops_sibling_down, london(2026, 7, 15, 7, 40)).proposals if p.dedupe_key.startswith("ops-michi")]
