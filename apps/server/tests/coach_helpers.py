"""Shared seeding helpers for the coach test suite (Phase 6)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.coach.proposals import LONDON
from app.db import SessionLocal
from app.models import (
    CalendarEvent,
    Habit,
    HabitEvent,
    HealthSample,
    MemoryEvent,
    Occasion,
    Setting,
    SiblingSnapshot,
    Workout,
)


def london(year: int, month: int, day: int, hh: int, mm: int) -> datetime:
    """A Europe/London wall-clock instant as an aware UTC datetime."""
    return datetime(year, month, day, hh, mm, tzinfo=LONDON).astimezone(timezone.utc)


def utc_str(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def add_habit(user_id: int, key: str, *, config: dict | None = None, kind: str = "auto", evidence: str | None = None,
              target: dict | None = None) -> int:
    with SessionLocal() as db:
        h = Habit(
            user_id=user_id,
            key=key,
            title=key.title(),
            kind=kind,
            evidence=evidence,
            active=1,
            target_json=json.dumps(target or {}),
            config_json=json.dumps(config or {}),
        )
        db.add(h)
        db.commit()
        return h.id


def add_workout(user_id: int, wtype: str, ts_start: datetime, uid: str | None = None) -> None:
    with SessionLocal() as db:
        db.add(
            Workout(
                user_id=user_id,
                wtype=wtype,
                ts_start=utc_str(ts_start),
                ts_end=None,
                source="test",
                provider_uid=uid or f"w:{wtype}:{utc_str(ts_start)}",
            )
        )
        db.commit()


def add_health_sample(user_id: int, metric: str, value: float, ts_start: datetime) -> None:
    with SessionLocal() as db:
        db.add(
            HealthSample(
                user_id=user_id, metric=metric, ts_start=utc_str(ts_start), value=value, unit="count", source="test"
            )
        )
        db.commit()


def add_memory_event(kind: str, provider_uid: str, ts: datetime, title: str | None = None) -> None:
    with SessionLocal() as db:
        db.add(
            MemoryEvent(
                user_id=None,
                ts=utc_str(ts),
                kind=kind,
                title=title,
                detail_json="{}",
                source="ingest:event",
                provider_uid=provider_uid,
            )
        )
        db.commit()


def add_snapshot(app: str, ok: bool, payload: dict | None, fetched_at: datetime) -> None:
    with SessionLocal() as db:
        db.add(
            SiblingSnapshot(
                app=app,
                fetched_at=utc_str(fetched_at),
                ok=1 if ok else 0,
                latency_ms=10,
                payload_json=json.dumps(payload) if payload is not None else None,
                error=None if ok else "down",
            )
        )
        db.commit()


def add_habit_event(habit_id: int, local_date: str, source: str = "auto") -> None:
    with SessionLocal() as db:
        db.add(HabitEvent(habit_id=habit_id, local_date=local_date, value=1, source=source))
        db.commit()


def add_setting(key: str, value) -> None:
    with SessionLocal() as db:
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value_json=json.dumps(value)))
        else:
            row.value_json = json.dumps(value)
        db.commit()


def add_all_day_event(*, title: str | None, start: str, end_exclusive: str | None, uid: str | None = None) -> None:
    """An all-day calendar_events row exactly as clients/calendar.py writes it:
    bare ICS dates stored as 'YYYY-MM-DD 00:00:00', DTEND exclusive (may be
    absent for single-day events)."""
    with SessionLocal() as db:
        db.add(
            CalendarEvent(
                ics_uid=uid or f"test:{title}:{start}",
                starts_at=f"{start} 00:00:00",
                ends_at=f"{end_exclusive} 00:00:00" if end_exclusive else None,
                all_day=1,
                title=title,
                location=None,
                calendar_name="test",
            )
        )
        db.commit()


def add_occasion(*, title: str, kind: str, month_day: str | None = None, date_str: str | None = None,
                 lead_days: int = 21, person_id: int | None = None, recurrence: str = "yearly") -> int:
    with SessionLocal() as db:
        occ = Occasion(
            person_id=person_id,
            title=title,
            month_day=month_day,
            date=date_str,
            recurrence=recurrence,
            lead_days=lead_days,
            kind=kind,
        )
        db.add(occ)
        db.commit()
        return occ.id
