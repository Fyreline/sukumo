"""Every coach template passes the redaction gate (docs/ARCHITECTURE.md §5.2,
docs/phases/PHASE-6-coach.md build item 6: "extend the Phase-5 pytest pattern
to cover every coach template"). The push text carries categories, never
money/health figures.
"""
from __future__ import annotations

from datetime import date, timedelta

from app import notify
from app.coach import briefing as briefing_module
from app.coach.rules import (
    birthday_gift,
    gym_day,
    goal_milestone,
    japan_countdown,
    low_movement,
    michi_streak_guard,
    occasion_reminder,
    office_day,
    ops_health_sync,
    ops_sibling_down,
    reading,
)
from app.config import get_settings
from app.db import SessionLocal
from app.models import Person
from tests.conftest import make_user
from tests.coach_helpers import (
    add_habit,
    add_health_sample,
    add_memory_event,
    add_occasion,
    add_setting,
    add_snapshot,
    add_workout,
    london,
)


def _collect_templates() -> list[tuple[str, str, str]]:
    """Seed firing conditions for every rule, evaluate, and return
    (rule_key, title, body) for each emitted proposal."""
    uid = make_user(email="mack@example.com", role="primary")

    # habits + config
    add_habit(uid, "gym", config={"wtypes": ["strength"], "gap_floor_days": 4}, evidence="workouts:wtype in cfg")
    add_habit(uid, "reading", kind="tap", evidence="events:reading")
    add_setting("low_movement", {"step_threshold": 5000})
    add_setting("office_pattern", {"aspirational": ["Thu"]})
    add_setting("japan_range", {"start": (date(2026, 7, 15) + timedelta(days=30)).isoformat()})

    # data that trips each rule
    add_memory_event("place", "office:arrived:2026-07-15 08:30:00", london(2026, 7, 15, 8, 30), "Office arrived")
    add_health_sample(uid, "step_count", 1200, london(2026, 7, 15, 12, 0))
    add_snapshot("michi", True, {"streak_days": 9, "studied_today": False}, london(2026, 7, 15, 20, 20))
    add_snapshot("kakeibo", True, {"pct": 27.0}, london(2026, 7, 15, 6, 0))
    add_snapshot("weather", True, {"office": {"daily": {"precipitation_probability_max": [80, 70]}}}, london(2026, 7, 15, 6, 0))

    pid = None
    with SessionLocal() as db:
        p = Person(name="Ken")
        db.add(p)
        db.commit()
        pid = p.id
    add_occasion(title="Ken's birthday", kind="birthday", month_day="07-25", person_id=pid, lead_days=21)
    add_occasion(title="Dentist", kind="deadline", date_str=(date(2026, 7, 15) + timedelta(days=2)).isoformat(),
                 recurrence="once")
    # a sibling down 3x for the ops:sibling-down template
    for h in (10, 11, 12):
        add_snapshot("mishka", False, None, london(2026, 7, 14, h, 0))
    from tests.test_coach_rules import _add_sync_run

    _add_sync_run("ingest:health", "ok", london(2026, 7, 13, 12, 0))  # stale -> health-sync template

    out: list[tuple[str, str, str]] = []
    firings = [
        (gym_day, london(2026, 7, 15, 16, 45)),
        (reading, london(2026, 7, 15, 21, 20)),
        (michi_streak_guard, london(2026, 7, 15, 20, 30)),
        (low_movement, london(2026, 7, 15, 18, 30)),
        (goal_milestone, london(2026, 7, 15, 12, 0)),
        (japan_countdown, london(2026, 7, 15, 8, 0)),
        (office_day, london(2026, 7, 15, 18, 30)),
        (occasion_reminder, london(2026, 7, 15, 10, 5)),
        (birthday_gift, london(2026, 7, 19, 10, 30)),  # Sunday
        (ops_health_sync, london(2026, 7, 15, 7, 40)),
        (ops_sibling_down, london(2026, 7, 15, 7, 40)),
    ]
    for module, now in firings:
        with SessionLocal() as db:
            res = module.evaluate(now, db)
        for p in res.proposals:
            out.append((p.rule_key, p.title, p.body))
    return out


def test_every_rule_template_passes_the_redaction_gate():
    templates = _collect_templates()
    # sanity: we actually exercised the catalogue, not an empty list
    keys = {rk for rk, _, _ in templates}
    assert len(keys) >= 10
    for rule_key, title, body in templates:
        notify.check_redaction(title)  # raises RedactionError on a money/health shape
        notify.check_redaction(body)


def test_briefing_text_passes_the_redaction_gate():
    make_user(email="mack@example.com", role="primary")
    add_snapshot(
        "weather", True, {"office": {"daily": {"precipitation_probability_max": [80]}}}, london(2026, 7, 15, 6, 0)
    )
    with SessionLocal() as db:
        content_md, push_body = briefing_module.compose(db, london(2026, 7, 15, 7, 40), get_settings(), [])
    notify.check_redaction(push_body)
    for line in content_md.splitlines():
        notify.check_redaction(line)
