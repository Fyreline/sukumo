"""low-movement — the one gentle evening movement poke (COACH §3.12, HANDOFF Q11).

By 18:30, if steps are under the configured threshold AND no workout of any type
was logged today, one soft push — and a walk is exactly what it asks for (walks
never satisfy the gym rule, but they satisfy this one). Suppressed if gym-day
already fired today: never two movement pokes in one day (COACH §3.12). No push
text ever carries the step figure — "barely moved" is a category, not a value
(ARCHITECTURE §5.2).

Unconfigured (no ``low_movement.step_threshold`` setting) → ``not_configured``.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from ...models import HealthSample, Nudge, Workout
from .. import config as coach_config
from ..proposals import LONDON, NudgeProposal, Rule, RuleResult, parse_utc, today_local, today_trigger_if_past

MOVE_HH, MOVE_MM = 18, 30


def _local_date(ts_utc: str) -> str:
    return parse_utc(ts_utc).astimezone(LONDON).date().isoformat()


def evaluate(now: datetime, session) -> RuleResult:
    cfg = coach_config.get_setting(session, coach_config.KEY_LOW_MOVEMENT, None)
    if not isinstance(cfg, dict) or cfg.get("step_threshold") is None:
        return RuleResult.not_configured("no low_movement.step_threshold")
    threshold = float(cfg["step_threshold"])

    trigger = today_trigger_if_past(now, MOVE_HH, MOVE_MM)
    if trigger is None:
        return RuleResult()

    today = today_local(now).isoformat()

    # never two movement pokes in a day: suppress if gym-day already fired today
    gym_today = session.scalar(
        select(Nudge).where(Nudge.dedupe_key == f"gym:{today}", Nudge.status != "expired")
    )
    if gym_today is not None:
        return RuleResult()

    # no workout of any type today
    workout_today = any(
        _local_date(w.ts_start) == today for w in session.scalars(select(Workout)).all()
    )
    if workout_today:
        return RuleResult()

    steps = sum(
        s.value
        for s in session.scalars(select(HealthSample).where(HealthSample.metric == "step_count")).all()
        if _local_date(s.ts_start) == today
    )
    if steps >= threshold:
        return RuleResult()

    return RuleResult(
        proposals=[
            NudgeProposal(
                rule_key="low-movement",
                dedupe_key=f"move:{today}",
                title="A quiet day for steps",
                body="Barely moved today — even a short evening walk would round it off. \U0001f319",
                scheduled_for=trigger,
                tags=["coach", "movement"],
                expiry=timedelta(hours=4),
            )
        ]
    )


RULE = Rule(key="low-movement", evaluate=evaluate, cooldown_hours=24)
