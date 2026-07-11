"""Source mappers fill memory_events idempotently — docs/MEMORY.md §2,
docs/phases/PHASE-7-memory.md item 1. All data here is SYNTHETIC."""
from __future__ import annotations

import json

from sqlalchemy import select

from app.db import SessionLocal
from app.memory import mappers
from app.models import CalendarEvent, MemoryEvent, Nudge, SiblingSnapshot, User, Workout

from .conftest import make_user


def _mishka_snapshot(fetched_at: str, recent: list[dict]) -> SiblingSnapshot:
    return SiblingSnapshot(
        app="mishka",
        fetched_at=fetched_at,
        ok=1,
        latency_ms=10,
        payload_json=json.dumps({"recent": recent, "watchlist_count": 0}),
        error=None,
    )


def _michi_snapshot(fetched_at: str, studied_today: int, streak: int, words: int) -> SiblingSnapshot:
    return SiblingSnapshot(
        app="michi",
        fetched_at=fetched_at,
        ok=1,
        latency_ms=10,
        payload_json=json.dumps(
            {"studied_today": studied_today, "streak_days": streak, "words_known": words}
        ),
        error=None,
    )


def test_workout_mapper_writes_and_is_idempotent():
    uid = make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        db.add(
            Workout(
                user_id=uid,
                wtype="strength",
                ts_start="2026-07-08 18:00:00",
                ts_end="2026-07-08 18:52:00",
                duration_s=3120,
                source="Traditional Strength Training",
                provider_uid="derived:strength:2026-07-08 18:00:00",
            )
        )
        db.commit()

        assert mappers.map_workouts(db) == 1
        db.commit()
        # re-run creates nothing new
        assert mappers.map_workouts(db) == 0
        db.commit()

        rows = db.scalars(select(MemoryEvent).where(MemoryEvent.kind == "workout")).all()
        assert len(rows) == 1
        assert rows[0].source == "workouts"
        assert "52 min" in (rows[0].title or "")


def test_study_mapper_one_per_day_and_skips_idle_days():
    make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        db.add(_michi_snapshot("2026-07-08 21:00:00", studied_today=1, streak=4, words=310))
        db.add(_michi_snapshot("2026-07-08 22:00:00", studied_today=1, streak=4, words=312))  # same day
        db.add(_michi_snapshot("2026-07-09 21:00:00", studied_today=0, streak=0, words=312))  # idle
        db.commit()

        created = mappers.map_study(db)
        db.commit()
        assert created == 1  # one study day only
        assert mappers.map_study(db) == 0  # idempotent

        rows = db.scalars(select(MemoryEvent).where(MemoryEvent.kind == "study")).all()
        assert len(rows) == 1
        assert rows[0].provider_uid == "michi:2026-07-08"
        assert "streak" in (rows[0].title or "")


def test_film_mapper_maps_recent_watches_idempotently():
    make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        recent = [
            {
                "title": "A Synthetic Film",
                "watched_at": "2026-07-07 20:30:00",
                "rating": 4,
                "poster_url": "x",
                "user_email": "mack@example.com",
            },
            {
                "title": "Another Fake One",
                "watched_at": "2026-07-08 21:00:00",
                "rating": 5,
                "poster_url": "y",
                "user_email": "mack@example.com",
            },
        ]
        db.add(_mishka_snapshot("2026-07-08 23:00:00", recent))
        # a later snapshot repeats the same watches (overlapping windows)
        db.add(_mishka_snapshot("2026-07-09 23:00:00", recent))
        db.commit()

        created = mappers.map_films(db)
        db.commit()
        assert created == 2
        assert mappers.map_films(db) == 0

        rows = db.scalars(select(MemoryEvent).where(MemoryEvent.kind == "film")).all()
        assert len(rows) == 2
        assert all(r.source == "mishka" for r in rows)


def test_film_mapper_only_maps_primary_users_watches():
    """Mishka's ``recent`` feed is household-wide (both housemates' watches).
    Only the primary user's own watches should land as memory_events — the
    partner's watches must be skipped entirely, not merely hidden later."""
    make_user(email="mack@example.com", display_name="Mack", role="primary")
    make_user(email="amy@example.com", display_name="Amy", role="partner")
    with SessionLocal() as db:
        recent = [
            {
                "title": "Mack's Film",
                "watched_at": "2026-07-07 20:30:00",
                "rating": 4,
                "poster_url": "x",
                "user_email": "mack@example.com",
            },
            {
                "title": "Amy's Film",
                "watched_at": "2026-07-08 21:00:00",
                "rating": 5,
                "poster_url": "y",
                "user_email": "amy@example.com",
            },
            {
                # case-insensitive match on the primary's email
                "title": "Mack's Other Film",
                "watched_at": "2026-07-09 21:00:00",
                "rating": 3,
                "poster_url": "z",
                "user_email": "Mack@Example.com",
            },
        ]
        db.add(_mishka_snapshot("2026-07-09 23:00:00", recent))
        db.commit()

        created = mappers.map_films(db)
        db.commit()
        assert created == 2
        assert mappers.map_films(db) == 0  # idempotent

        rows = db.scalars(select(MemoryEvent).where(MemoryEvent.kind == "film")).all()
        titles = {r.title for r in rows}
        assert titles == {"Mack's Film", "Mack's Other Film"}
        assert "Amy's Film" not in titles


def test_film_mapper_maps_nothing_without_a_primary_user():
    """No primary user configured yet (e.g. before first login) — nothing is
    attributable, so nothing is mapped rather than guessing."""
    make_user(email="amy@example.com", display_name="Amy", role="partner")
    with SessionLocal() as db:
        recent = [
            {
                "title": "Some Film",
                "watched_at": "2026-07-07 20:30:00",
                "rating": 4,
                "poster_url": "x",
                "user_email": "amy@example.com",
            },
        ]
        db.add(_mishka_snapshot("2026-07-08 23:00:00", recent))
        db.commit()

        assert mappers.map_films(db) == 0
        rows = db.scalars(select(MemoryEvent).where(MemoryEvent.kind == "film")).all()
        assert rows == []


def test_calendar_mapper_only_past_events():
    with SessionLocal() as db:
        db.add(CalendarEvent(ics_uid="past-1", starts_at="2026-07-01 09:00:00", all_day=0, title="Past thing", location="Somewhere", calendar_name="personal"))
        db.add(CalendarEvent(ics_uid="future-1", starts_at="2099-01-01 09:00:00", all_day=0, title="Future thing", location=None, calendar_name="personal"))
        db.commit()

        created = mappers.map_calendar(db)
        db.commit()
        assert created == 1
        assert mappers.map_calendar(db) == 0

        rows = db.scalars(select(MemoryEvent).where(MemoryEvent.kind == "calendar")).all()
        assert len(rows) == 1
        assert rows[0].provider_uid == "past-1:2026-07-01 09:00:00"


def test_finance_mapper_labels_only_no_figures():
    uid = make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        db.add(
            Nudge(
                rule_key="goal-milestone",
                user_id=uid,
                dedupe_key="goal:45",
                scheduled_for="2026-07-05 08:00:00",
                channel="ntfy",
                title="A milestone on the house pot",
                body="crossed another 5%",
                status="sent",
            )
        )
        db.commit()

        created = mappers.map_finance(db)
        db.commit()
        assert created == 1
        assert mappers.map_finance(db) == 0

        row = db.scalar(select(MemoryEvent).where(MemoryEvent.kind == "finance"))
        assert row.provider_uid == "goal:45"
        assert "45%" in (row.title or "")
        # a percentage label is allowed; no currency figure leaks in
        assert "£" not in (row.title or "")


def test_run_mappers_returns_counts():
    make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        db.add(CalendarEvent(ics_uid="p", starts_at="2026-07-01 09:00:00", all_day=1, title="X", location=None, calendar_name="c"))
        db.commit()
        counts = mappers.run_mappers(db)
        assert set(counts) == {"workouts", "study", "films", "calendar", "finance"}
        assert counts["calendar"] == 1
