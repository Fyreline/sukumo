"""Coach engine — the gate + delivery mechanics against a frozen clock
(docs/COACH.md §1-2, §4, docs/phases/PHASE-6-coach.md acceptance).

Covers: dedupe drop, dismissed→cooldown, daily cap keeps highest priority,
23:00→07:30 quiet-hours hold + morning redelivery, Mac-asleep expiry (the
21:15 reading scenario), stale-sibling silence, the movement-rules end-to-end
scenario, and tick idempotency.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.coach import engine
from app.coach.proposals import NudgeProposal, Rule, RuleResult
from app.config import get_settings
from app.db import SessionLocal
from app.models import Nudge
from tests.conftest import make_user
from tests.coach_helpers import (
    add_habit,
    add_health_sample,
    add_memory_event,
    add_setting,
    add_snapshot,
    add_workout,
    london,
    utc_str,
)


def _primary() -> int:
    return make_user(email="mack@example.com", role="primary")


async def _tick(now, *, poll=False):
    with SessionLocal() as db:
        return await engine.tick(db, get_settings(), now, poll=poll)


def _nudges(**filters):
    with SessionLocal() as db:
        q = select(Nudge)
        rows = db.scalars(q).all()
        out = []
        for n in rows:
            if all(getattr(n, k) == v for k, v in filters.items()):
                out.append((n.rule_key, n.dedupe_key, n.status, n.channel))
        return out


# ---- synthetic-rule harness for the pure gate mechanics --------------------
def _patch_rules(monkeypatch, rules):
    monkeypatch.setattr(engine, "load_rules", lambda: rules)


def _static_rule(key, proposals, cooldown_hours=24):
    return Rule(key=key, evaluate=lambda now, db: RuleResult(proposals=proposals), cooldown_hours=cooldown_hours)


# ============================================================================
# dedupe + cooldown
# ============================================================================
@pytest.mark.anyio
async def test_dedupe_key_drops_a_second_proposal(monkeypatch):
    _primary()
    now = london(2026, 7, 15, 12, 0)
    p = NudgeProposal("t", "t:once", "Hi", "there", now)
    _patch_rules(monkeypatch, [_static_rule("t", [p])])

    await _tick(now)
    await _tick(now)  # re-run: dedupe_key already present
    assert len([n for n in _nudges() if n[1] == "t:once"]) == 1


@pytest.mark.anyio
async def test_dismissed_nudge_respects_cooldown(monkeypatch):
    uid = _primary()
    # a dismissed nudge from 2h ago for rule 't'
    now = london(2026, 7, 15, 12, 0)
    with SessionLocal() as db:
        db.add(
            Nudge(
                rule_key="t",
                user_id=uid,
                dedupe_key="t:yesterday",
                scheduled_for=utc_str(london(2026, 7, 15, 10, 0)),
                channel="ntfy",
                title="x",
                body="y",
                status="dismissed",
                created_at=utc_str(london(2026, 7, 15, 10, 0)),
            )
        )
        db.commit()
    p = NudgeProposal("t", "t:today", "Hi", "there", now)
    _patch_rules(monkeypatch, [_static_rule("t", [p], cooldown_hours=24)])

    result = await _tick(now)
    assert result["counts"]["cooldown"] == 1
    assert not [n for n in _nudges() if n[1] == "t:today"]


# ============================================================================
# daily cap keeps highest priority
# ============================================================================
@pytest.mark.anyio
async def test_daily_cap_keeps_highest_priority(monkeypatch):
    _primary()
    add_setting("coach_daily_cap", 2)
    now = london(2026, 7, 15, 12, 0)
    proposals = [
        NudgeProposal("a", "a:1", "A", "low", now, priority="low"),
        NudgeProposal("b", "b:1", "B", "default", now, priority="default"),
        NudgeProposal("c", "c:1", "C", "high", now, priority="high"),
    ]
    rules = [_static_rule(p.rule_key, [p]) for p in proposals]
    _patch_rules(monkeypatch, rules)

    result = await _tick(now)
    assert result["counts"]["delivered"] == 2
    assert result["counts"]["capped_inbox"] == 1
    pushed = {rk for rk, dk, st, ch in _nudges() if ch == "ntfy"}
    capped = {rk for rk, dk, st, ch in _nudges() if ch == "inbox"}
    assert pushed == {"c", "b"}  # high + default kept
    assert capped == {"a"}  # low demoted to inbox


# ============================================================================
# quiet hours: a 23:00 proposal delivers 07:30+
# ============================================================================
@pytest.mark.anyio
async def test_2300_proposal_holds_then_delivers_next_morning(monkeypatch):
    _primary()
    add_setting("coach_quiet_hours", "22:30-07:30")
    late = london(2026, 7, 15, 23, 0)
    # a no-expiry proposal: held through quiet hours, not expired
    p = NudgeProposal("t", "t:hold", "Held", "for morning", late, expiry=None)
    _patch_rules(monkeypatch, [_static_rule("t", [p])])

    result = await _tick(late)
    assert result["counts"]["held"] == 1
    with SessionLocal() as db:
        n = db.scalar(select(Nudge).where(Nudge.dedupe_key == "t:hold"))
        assert n.status == "pending"
        # scheduled_for pushed to 07:30 London (06:30 UTC in BST)
        assert n.scheduled_for.endswith("06:30:00")

    # next tick after the window: redelivered
    morning = london(2026, 7, 16, 7, 35)
    _patch_rules(monkeypatch, [])  # no new proposals, just redelivery
    result2 = await _tick(morning)
    assert result2["counts"]["redelivered"] == 1
    with SessionLocal() as db:
        n = db.scalar(select(Nudge).where(Nudge.dedupe_key == "t:hold"))
        assert n.status == "sent"


# ============================================================================
# Mac-asleep expiry — the 21:15 reading scenario (COACH §4)
# ============================================================================
@pytest.mark.anyio
async def test_slept_through_reading_moment_expires_not_pushes():
    uid = _primary()
    add_habit(uid, "reading", kind="tap", evidence="events:reading")  # no habit_events -> stale
    # machine wakes at 09:00, having slept through last night's 21:15
    now = london(2026, 7, 16, 9, 0)
    await _tick(now)

    with SessionLocal() as db:
        n = db.scalar(select(Nudge).where(Nudge.rule_key == "reading"))
        assert n is not None
        assert n.status == "expired"  # never a stale morning push
        assert n.channel == "inbox"
        assert n.sent_at is not None
        # dedupe keyed to the missed cycle (yesterday)
        assert n.dedupe_key == "reading:2026-07-15"


@pytest.mark.anyio
async def test_reading_delivers_at_its_moment():
    uid = _primary()
    add_habit(uid, "reading", kind="tap", evidence="events:reading")
    now = london(2026, 7, 15, 21, 20)  # just past 21:15
    await _tick(now)
    with SessionLocal() as db:
        n = db.scalar(select(Nudge).where(Nudge.rule_key == "reading"))
        assert n.status == "sent"
        assert n.dedupe_key == "reading:2026-07-15"


@pytest.mark.anyio
async def test_reading_silent_when_read_recently():
    uid = _primary()
    hid = add_habit(uid, "reading", kind="tap", evidence="events:reading")
    from tests.coach_helpers import add_habit_event

    add_habit_event(hid, "2026-07-15", source="tap")  # read today
    now = london(2026, 7, 15, 21, 20)
    await _tick(now)
    assert not [n for n in _nudges() if n[0] == "reading"]


# ============================================================================
# stale-in-silent-out: michi
# ============================================================================
@pytest.mark.anyio
async def test_michi_silent_on_stale_snapshot():
    _primary()
    now = london(2026, 7, 15, 20, 30)
    # snapshot streak alive + not studied, but fetched 5h ago -> stale
    add_snapshot("michi", True, {"streak_days": 9, "studied_today": False}, london(2026, 7, 15, 15, 0))
    result = await _tick(now)
    assert not [n for n in _nudges() if n[0] == "michi-streak-guard"]
    assert result["counts"]["stale"] >= 1


@pytest.mark.anyio
async def test_michi_fires_on_fresh_snapshot():
    _primary()
    now = london(2026, 7, 15, 20, 30)
    add_snapshot("michi", True, {"streak_days": 9, "studied_today": False}, london(2026, 7, 15, 20, 20))
    await _tick(now)
    assert [n for n in _nudges() if n[0] == "michi-streak-guard" and n[2] == "sent"]


# ============================================================================
# movement rules end-to-end (COACH §3.2/§3.12, PHASE-6 acceptance)
# ============================================================================
def _gym_habit(uid):
    add_habit(uid, "gym", config={"wtypes": ["strength"], "gap_floor_days": 4}, evidence="workouts:wtype in cfg")


@pytest.mark.anyio
async def test_office_day_no_workout_fires_gym_at_1645():
    uid = _primary()
    _gym_habit(uid)
    add_memory_event("place", "office:arrived:2026-07-15 08:30:00", london(2026, 7, 15, 8, 30), "Office arrived")

    # before 16:45 — silent
    await _tick(london(2026, 7, 15, 16, 30))
    assert not [n for n in _nudges() if n[0] == "gym-day"]

    # at 16:45 — office-linked gym nudge
    await _tick(london(2026, 7, 15, 16, 45))
    gym = [n for n in _nudges() if n[0] == "gym-day"]
    assert gym and gym[0][1] == "gym:2026-07-15" and gym[0][2] == "sent"


@pytest.mark.anyio
async def test_four_day_gap_no_office_fires_fallback_at_1745():
    uid = _primary()
    _gym_habit(uid)
    add_workout(uid, "strength", london(2026, 7, 11, 18, 0))  # 4 days before the 15th

    # at 16:45 with no office arrival — nothing (office-linked needs office day)
    await _tick(london(2026, 7, 15, 16, 45))
    assert not [n for n in _nudges() if n[0] == "gym-day"]

    # at 17:45 — the fallback floor fires
    await _tick(london(2026, 7, 15, 17, 45))
    gym = [n for n in _nudges() if n[0] == "gym-day"]
    assert gym and gym[0][2] == "sent"


@pytest.mark.anyio
async def test_gym_day_satisfied_by_geofence_habit_event():
    """A gym-geofence arrival (habit_events row, source tap) counts as done —
    neither the 16:45 office-linked nudge nor the 17:45 fallback fires
    (COACH §3.2: machine sessions never reach the watch)."""
    uid = _primary()
    _gym_habit(uid)
    add_memory_event("place", "office:arrived:2026-07-15 08:30:00", london(2026, 7, 15, 8, 30), "Office arrived")
    from app.models import Habit

    with SessionLocal() as db:
        habit_id = db.scalar(select(Habit.id).where(Habit.key == "gym"))
    from tests.coach_helpers import add_habit_event

    add_habit_event(habit_id, "2026-07-15", source="tap")

    await _tick(london(2026, 7, 15, 16, 45))
    await _tick(london(2026, 7, 15, 17, 45))
    assert not [n for n in _nudges() if n[0] == "gym-day"]


@pytest.mark.anyio
async def test_low_movement_suppressed_by_gym_habit_event():
    """Low steps + no workout, but a gym habit_events row today (the geofence
    arrival) — being at the gym is movement, no poke (COACH §3.12)."""
    uid = _primary()
    _gym_habit(uid)
    add_setting("low_movement", {"step_threshold": 5000})
    add_health_sample(uid, "step_count", 1200, london(2026, 7, 15, 12, 0))
    from app.models import Habit

    with SessionLocal() as db:
        habit_id = db.scalar(select(Habit.id).where(Habit.key == "gym"))
    from tests.coach_helpers import add_habit_event

    add_habit_event(habit_id, "2026-07-15", source="tap")

    await _tick(london(2026, 7, 15, 18, 30))
    assert not [n for n in _nudges() if n[0] == "low-movement"]


@pytest.mark.anyio
async def test_low_movement_fires_at_1830_when_steps_low_no_workout():
    uid = _primary()
    add_setting("low_movement", {"step_threshold": 5000})
    add_health_sample(uid, "step_count", 1200, london(2026, 7, 15, 12, 0))
    await _tick(london(2026, 7, 15, 18, 30))
    move = [n for n in _nudges() if n[0] == "low-movement"]
    assert move and move[0][1] == "move:2026-07-15" and move[0][2] == "sent"


@pytest.mark.anyio
async def test_low_movement_suppressed_when_gym_already_fired():
    uid = _primary()
    _gym_habit(uid)
    add_setting("low_movement", {"step_threshold": 5000})
    add_health_sample(uid, "step_count", 1200, london(2026, 7, 15, 12, 0))
    add_memory_event("place", "office:arrived:2026-07-15 08:30:00", london(2026, 7, 15, 8, 30), "Office arrived")

    # single tick at 18:30: gym-day already fired earlier today would suppress —
    # simulate by firing gym at 16:45 first, then low-movement at 18:30.
    await _tick(london(2026, 7, 15, 16, 45))
    assert [n for n in _nudges() if n[0] == "gym-day"]
    await _tick(london(2026, 7, 15, 18, 30))
    assert not [n for n in _nudges() if n[0] == "low-movement"]  # never two movement pokes


# ============================================================================
# idempotency in anger (COACH §1)
# ============================================================================
@pytest.mark.anyio
async def test_tick_is_idempotent_across_three_runs():
    uid = _primary()
    add_habit(uid, "reading", kind="tap", evidence="events:reading")
    _gym_habit(uid)
    add_setting("low_movement", {"step_threshold": 5000})
    add_health_sample(uid, "step_count", 1200, london(2026, 7, 15, 12, 0))
    add_snapshot("michi", True, {"streak_days": 9, "studied_today": False}, london(2026, 7, 15, 21, 10))

    now = london(2026, 7, 15, 21, 20)

    def count():
        with SessionLocal() as db:
            return len(db.scalars(select(Nudge)).all())

    await _tick(now)
    after_first = count()
    await _tick(now)
    await _tick(now)
    after_third = count()
    assert after_first == after_third
    assert after_first > 0
