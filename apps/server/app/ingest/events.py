"""Generic Shortcuts/scripts events (office/gym geofences, one-tap reading
log, share-sheet notes, ...) -> memory_events and habit_events --
docs/DATA_MODEL.md, docs/API.md #3, docs/phases/PHASE-2-ingestion.md.

Payload (API.md #3)::

    {"kind": "office" | "gym" | "reading" | "place" | "manual" | "milestone",
     "state": "arrived" | "left" | null,
     "value": 1, "title": "...optional...", "ts": "...optional, default now..."}

Routing: ``reading`` -> ``habit_events`` (source ``'tap'``, idempotent per
Europe/London local day); ``office`` arrived/left -> ``memory_events(kind=
'place')``; ``gym`` arrived/left -> the same place row (synthetic "Gym ..."
title -- the payload's title is IGNORED so a phone automation can never echo
a location string into the well), and ``arrived`` ALSO logs the day against
the active ``gym`` habit (source ``'tap'``, note ``'geofence'``, idempotent
per day) so machine-only sessions the watch never records still count
(docs/COACH.md #3.2); ``place``/``manual``/``milestone`` -> ``memory_events``
directly. All local-date maths happens at use time (DATA_MODEL preamble),
never baked into storage.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dateutil import parser as dateutil_parser
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Habit, HabitEvent, MemoryEvent, User

LONDON = ZoneInfo("Europe/London")
ALLOWED_KINDS = {"office", "gym", "reading", "place", "manual", "milestone"}


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_ts(raw: str | None) -> str:
    if not raw:
        return _utcnow_str()
    dt = dateutil_parser.parse(raw)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _local_date(ts_utc: str) -> str:
    dt = datetime.strptime(ts_utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.astimezone(LONDON).date().isoformat()


def _resolve_user_id(session: Session, token_user_id: int | None) -> int:
    """The reading habit needs a concrete owner. If the presenting ingest
    token isn't bound to a user (DATA_MODEL #1: user_id is NULLABLE, e.g. a
    household bus token), fall back to the household's 'primary' user."""
    if token_user_id is not None:
        return token_user_id
    primary = session.scalar(select(User).where(User.role == "primary"))
    if primary is None:
        raise ValueError("no owning user for this event: ingest token has no user_id and no primary user exists")
    return primary.id


def _get_or_create_reading_habit(session: Session, user_id: int) -> Habit:
    habit = session.scalar(select(Habit).where(Habit.key == "reading"))
    if habit is not None:
        return habit
    habit = Habit(
        user_id=user_id,
        key="reading",
        title="Reading",
        kind="tap",
        target_json=json.dumps({"per_day": 1}),
        evidence="events:reading",
        active=1,
        config_json="{}",
    )
    session.add(habit)
    session.flush()
    return habit


def ingest_event(session: Session, token_user_id: int | None, payload: dict) -> dict:
    kind = payload.get("kind")
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"unknown event kind: {kind!r}")

    state = payload.get("state")
    value = float(payload.get("value") or 1)
    title = payload.get("title")
    ts = _normalize_ts(payload.get("ts"))

    if kind == "reading":
        user_id = _resolve_user_id(session, token_user_id)
        habit = _get_or_create_reading_habit(session, user_id)
        local_date = _local_date(ts)
        existing = session.scalar(
            select(HabitEvent).where(
                HabitEvent.habit_id == habit.id,
                HabitEvent.local_date == local_date,
                HabitEvent.source == "tap",
            )
        )
        created = False
        if existing is None:
            session.add(
                HabitEvent(habit_id=habit.id, local_date=local_date, value=value, source="tap", note=title)
            )
            created = True
        session.commit()
        return {"kind": "reading", "habit_id": habit.id, "local_date": local_date, "created": created}

    # office / gym / place / manual / milestone -> memory_events. user_id
    # stays whatever the token carries (possibly None -- "household events
    # allowed", DATA_MODEL #5).
    habit_event: dict | None = None
    if kind == "gym":
        mem_kind = "place"
        # Synthetic title ONLY -- a gym geofence automation must never echo
        # its location string into the memory well (docs/API.md #3).
        title = None
        default_title = f"Gym {state}" if state else "Gym"
        if state == "arrived":
            habit_event = _log_gym_habit_day(session, ts)
    elif kind == "office":
        mem_kind = "place"
        default_title = f"Office {state}" if state else "Office"
    elif kind == "place":
        mem_kind = "place"
        default_title = title or "Place"
    else:
        mem_kind = kind  # 'manual' | 'milestone'
        default_title = title or kind

    # The payload carries no id of its own, so provider_uid is derived from
    # the event's own fields -- identical re-POSTs (same kind/state/ts)
    # collapse to the same row (DATA_MODEL's idempotency law).
    provider_uid = f"{kind}:{state or 'na'}:{ts}"
    existing = session.scalar(
        select(MemoryEvent).where(MemoryEvent.source == "ingest:event", MemoryEvent.provider_uid == provider_uid)
    )
    created = False
    if existing is None:
        session.add(
            MemoryEvent(
                user_id=token_user_id,
                ts=ts,
                kind=mem_kind,
                title=title or default_title,
                detail_json=json.dumps({"state": state, "value": value}),
                source="ingest:event",
                provider_uid=provider_uid,
            )
        )
        created = True
    session.commit()
    out = {"kind": kind, "mem_kind": mem_kind, "provider_uid": provider_uid, "created": created}
    if kind == "gym":
        out["habit_event"] = habit_event
    return out


def _log_gym_habit_day(session: Session, ts_utc: str) -> dict | None:
    """A gym-geofence arrival counts the day against the active ``gym`` habit
    (COACH.md #3.2: machine-only sessions never reach the watch). source
    ``'tap'`` (a human-signal row, never rebuilt over -- DATA_MODEL #2), note
    ``'geofence'``, idempotent per (habit, local day, source). Returns None --
    memory event only -- when no active gym habit exists: the habit's config
    (which wtypes count, etc.) is deliberate setup, never auto-invented."""
    habit = session.scalar(select(Habit).where(Habit.key == "gym", Habit.active == 1))
    if habit is None:
        return None
    local_date = _local_date(ts_utc)
    existing = session.scalar(
        select(HabitEvent).where(
            HabitEvent.habit_id == habit.id,
            HabitEvent.local_date == local_date,
            HabitEvent.source == "tap",
        )
    )
    created = False
    if existing is None:
        session.add(
            HabitEvent(habit_id=habit.id, local_date=local_date, value=1, source="tap", note="geofence")
        )
        created = True
    return {"habit_id": habit.id, "local_date": local_date, "created": created}
