"""gym-day — office-day-linked with a 4-day fallback floor (COACH §3.2,
HANDOFF Q11).

Two ways to fire, sharing one dedupe key (``gym:<date>``) so at most one gym
nudge lands per day:

1. **office-linked (16:45):** a confirmed office day (geofence arrival logged
   today) that isn't the configured exempt weekday, with no gym workout yet →
   "gym on the way home?".
2. **fallback floor (17:45):** regardless of location, no gym workout in the
   configured gap-floor window (default 4 days, the one doc-blessed default) →
   a gentler nudge.

A day is "done" when EITHER a qualifying workout (``wtype`` in the configured
gym set) OR a gym ``habit_events`` row exists — the gym-geofence arrival
(app/ingest/events.py) logs the latter, so machine-only sessions the watch
never records still count. Walks never satisfy this rule. Tone is invitation,
never guilt (COACH §2/§5). Unconfigured (no gym habit, or no ``wtypes`` in its
config_json) → ``not_configured``, never a guessed nudge.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from ...models import HabitEvent, MemoryEvent, Workout
from .. import config as coach_config
from ..proposals import (
    LONDON,
    NudgeProposal,
    Rule,
    RuleResult,
    parse_utc,
    today_local,
    today_trigger_if_past,
)

DEADLINE_HH, DEADLINE_MM = 16, 45  # office-linked
FALLBACK_HH, FALLBACK_MM = 17, 45  # gap-floor


def _local_date(ts_utc: str) -> str:
    return parse_utc(ts_utc).astimezone(LONDON).date().isoformat()


def _gym_dates(session, user_id: int, habit_id: int, wtypes: list[str]) -> set[str]:
    """Days with a qualifying workout OR a gym habit_events row (the geofence
    arrival, or any hand log) — one set feeds both the done-today check and
    the gap floor, so a machine-only session silences both nudges."""
    rows = session.scalars(
        select(Workout).where(Workout.user_id == user_id, Workout.wtype.in_(wtypes))
    ).all()
    dates = {_local_date(w.ts_start) for w in rows}
    dates.update(
        session.scalars(select(HabitEvent.local_date).where(HabitEvent.habit_id == habit_id)).all()
    )
    return dates


def _office_arrived_today(session, today: str) -> bool:
    rows = session.scalars(
        select(MemoryEvent).where(
            MemoryEvent.kind == "place", MemoryEvent.provider_uid.like("office:arrived:%")
        )
    ).all()
    return any(_local_date(m.ts) == today for m in rows)


def evaluate(now: datetime, session) -> RuleResult:
    habit = coach_config.get_habit(session, "gym")
    cfg = coach_config.habit_config(habit)
    wtypes = cfg.get("wtypes") or []
    if habit is None or not wtypes:
        return RuleResult.not_configured("no active gym habit with wtypes")

    user_id = habit.user_id
    today = today_local(now)
    today_str = today.isoformat()
    gym_dates = _gym_dates(session, user_id, habit.id, wtypes)
    done_today = today_str in gym_dates
    gap_floor = int(cfg.get("gap_floor_days", coach_config.DEFAULT_GYM_GAP_FLOOR_DAYS))
    exempt_weekday = cfg.get("exempt_weekday")  # e.g. "Fri" — can swap weeks (config)

    dedupe = f"gym:{today_str}"

    # (1) office-linked at 16:45
    if not done_today and exempt_weekday != today.strftime("%a"):
        trigger = today_trigger_if_past(now, DEADLINE_HH, DEADLINE_MM)
        if trigger is not None and _office_arrived_today(session, today_str):
            return RuleResult(
                proposals=[
                    NudgeProposal(
                        rule_key="gym-day",
                        dedupe_key=dedupe,
                        title="In the office, no session yet",
                        body="Gym's on the way home if you fancy it — a short one still counts.",
                        scheduled_for=trigger,
                        tags=["coach", "gym"],
                        expiry=timedelta(hours=3),
                        context={"reason": "office-linked"},
                    )
                ]
            )

    # (2) fallback floor at 17:45 — no gym workout within the floor window
    recent = sum(1 for i in range(gap_floor) if (today - timedelta(days=i)).isoformat() in gym_dates)
    if recent == 0:
        trigger = today_trigger_if_past(now, FALLBACK_HH, FALLBACK_MM)
        if trigger is not None:
            return RuleResult(
                proposals=[
                    NudgeProposal(
                        rule_key="gym-day",
                        dedupe_key=dedupe,
                        title="Gym's been quiet",
                        body=f"No session in {gap_floor} days — no pressure, but tonight's open if you want it.",
                        scheduled_for=trigger,
                        tags=["coach", "gym"],
                        expiry=timedelta(hours=3),
                        context={"reason": "fallback-floor"},
                    )
                ]
            )

    return RuleResult()


RULE = Rule(key="gym-day", evaluate=evaluate, cooldown_hours=24)
