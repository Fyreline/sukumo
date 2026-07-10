"""Habit auto-evidence derivation -- docs/DATA_MODEL.md #2,
docs/phases/PHASE-2-ingestion.md build item 6.

Habits whose ``evidence`` is the literal string ``'workouts:wtype in cfg'``
get their ``'auto'`` habit_events rows delete+rebuilt from the workouts
table on every poll tick (called from scripts/poll_sources.py, matching the
docstring's "nightly rebuild" framing -- in practice it runs on the same 15
minute coach/poll cadence, ARCHITECTURE.md #2). The set of workout wtypes
that count as evidence for a given habit (e.g. the gym habit's
``["strength", "hiit"]``) lives in that habit's ``config_json``, never in
code -- DATA_MODEL #2's "thresholds ... live here, in the DB, not in code".

``'tap'`` and ``'coach_confirm'`` habit_events rows are human signals and are
never touched here -- only rows with ``source='auto'`` are deleted and
re-inserted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Habit, HabitEvent, Workout

LONDON = ZoneInfo("Europe/London")

EVIDENCE_WORKOUTS = "workouts:wtype in cfg"


def _local_date_from_utc_str(ts_utc: str) -> str:
    dt = datetime.strptime(ts_utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.astimezone(LONDON).date().isoformat()


def derive_auto_habit_events(session: Session) -> dict:
    """Delete+rebuild 'auto' habit_events for every active habit whose
    evidence is 'workouts:wtype in cfg' -- one row per local_date that has
    >=1 matching workout. Returns {"habits_processed": n, "events_written": n}.
    """
    habits = session.scalars(
        select(Habit).where(Habit.active == 1, Habit.evidence == EVIDENCE_WORKOUTS)
    ).all()

    habits_processed = 0
    events_written = 0
    for habit in habits:
        cfg = json.loads(habit.config_json or "{}")
        wtypes = cfg.get("wtypes") or []
        if not wtypes:
            continue
        habits_processed += 1

        # delete+rebuild ONLY this habit's 'auto' rows -- 'tap'/'coach_confirm'
        # rows are untouched (DATA_MODEL #2).
        session.execute(delete(HabitEvent).where(HabitEvent.habit_id == habit.id, HabitEvent.source == "auto"))

        workouts = session.scalars(
            select(Workout).where(Workout.user_id == habit.user_id, Workout.wtype.in_(wtypes))
        ).all()
        local_dates = sorted({_local_date_from_utc_str(w.ts_start) for w in workouts})
        for local_date in local_dates:
            session.add(HabitEvent(habit_id=habit.id, local_date=local_date, value=1, source="auto"))
            events_written += 1

    session.commit()
    return {"habits_processed": habits_processed, "events_written": events_written}
