"""reading — the 21:15 one-tap nudge whose action button closes the loop
(COACH §3.3).

Condition: the ``reading`` habit has no ``habit_events`` within its stale
window (doc-given 2 days). Fires at 21:15 with a one-tap action — the ntfy
button hits ``act/{token}`` which both marks the nudge actioned AND runs the
callback registered here, writing a ``coach_confirm`` habit_event. No app to
open; the loop closes from the notification.

This rule uses ``most_recent_trigger`` (not the today-only helper) so a moment
slept through becomes an ``expired`` nudge at the next wake rather than a stale
"20 minutes tonight?" push at 9am — the COACH §4 scenario. The 75-minute expiry
horizon means a tick that only reaches it after ~22:30 expires it instead of
holding it to a nonsensical morning delivery.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from ...models import Habit, HabitEvent
from ... import notify
from .. import config as coach_config
from ..proposals import (
    LONDON,
    NudgeProposal,
    Rule,
    RuleResult,
    most_recent_trigger,
)

READING_HH, READING_MM = 21, 15
DEFAULT_STALE_DAYS = 2  # COACH §3.3 gives this literally


def _write_reading_event(session, nudge) -> None:
    """Action callback (COACH §3.3): the one-tap ✓ writes the reading
    habit_event. Idempotent per Europe/London day."""
    habit = session.scalar(select(Habit).where(Habit.key == "reading"))
    if habit is None:
        return
    today = datetime.now(LONDON).date().isoformat()
    existing = session.scalar(
        select(HabitEvent).where(
            HabitEvent.habit_id == habit.id,
            HabitEvent.local_date == today,
            HabitEvent.source == "coach_confirm",
        )
    )
    if existing is None:
        session.add(
            HabitEvent(habit_id=habit.id, local_date=today, value=1, source="coach_confirm", note="coach one-tap")
        )
        session.commit()


# Register the callback at import — app.main's load_rules() imports this module
# at startup so /api/nudges/act/{token} (API process) finds it.
notify.register_action_callback("reading", _write_reading_event)


def evaluate(now: datetime, session) -> RuleResult:
    habit = coach_config.get_habit(session, "reading")
    if habit is None:
        return RuleResult.not_configured("no active reading habit")

    cfg = coach_config.habit_config(habit)
    stale_days = int(cfg.get("stale_days", DEFAULT_STALE_DAYS))

    trigger = most_recent_trigger(now, READING_HH, READING_MM)
    cycle_date = trigger.astimezone(LONDON).date()

    recent = session.scalars(
        select(HabitEvent.local_date).where(HabitEvent.habit_id == habit.id)
    ).all()
    recent_set = set(recent)
    window = {(cycle_date - timedelta(days=i)).isoformat() for i in range(stale_days)}
    if window & recent_set:
        return RuleResult()  # read recently — nothing to nudge

    return RuleResult(
        proposals=[
            NudgeProposal(
                rule_key="reading",
                dedupe_key=f"reading:{cycle_date.isoformat()}",
                title="A few pages tonight?",
                body="It's been a couple of days — 20 minutes counts. Tap ✓ to log it.",
                scheduled_for=trigger,
                tags=["coach", "reading"],
                expiry=timedelta(minutes=75),  # dead by ~22:30, never held to morning
            )
        ]
    )


RULE = Rule(key="reading", evaluate=evaluate, cooldown_hours=24)
