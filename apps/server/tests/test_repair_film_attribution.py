"""scripts/repair_film_attribution.py -- data-repair for the film
attribution bug (memory_events kind='film' previously included the
partner's Mishka watches, not just the primary user's). Idempotent: running
twice must produce the same counts. All data here is SYNTHETIC."""
from __future__ import annotations

import json

from sqlalchemy import select

from app.db import SessionLocal
from app.memory import mappers
from app.models import JournalDay, MemoryEvent, SiblingSnapshot

from .conftest import make_user
from scripts import repair_film_attribution as repair


def _mishka_snapshot(fetched_at: str, recent: list[dict]) -> SiblingSnapshot:
    return SiblingSnapshot(
        app="mishka",
        fetched_at=fetched_at,
        ok=1,
        latency_ms=10,
        payload_json=json.dumps({"recent": recent, "watchlist_count": 0}),
        error=None,
    )


def _seed_mixed_household_watches() -> None:
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
        ]
        db.add(_mishka_snapshot("2026-07-09 23:00:00", recent))
        db.commit()


def _seed_pre_fix_mixed_film_events() -> None:
    """Simulate the BUGGY state: both housemates' watches already mapped
    into memory_events(kind='film') (as the old, unfiltered mapper would
    have done), with the snapshot still around to re-derive from."""
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
        ]
        db.add(_mishka_snapshot("2026-07-09 23:00:00", recent))
        db.commit()

        # Hand-insert both as memory_events, bypassing the (now filtered)
        # mapper -- exactly what the old, unfiltered map_films() produced.
        db.add(
            MemoryEvent(
                ts="2026-07-07 20:30:00",
                kind="film",
                title="Mack's Film",
                detail_json=json.dumps({"rating": 4, "poster_url": "x"}),
                source="mishka",
                provider_uid="mishka:2026-07-07 20:30:00:aaaaaaaa",
            )
        )
        db.add(
            MemoryEvent(
                ts="2026-07-08 21:00:00",
                kind="film",
                title="Amy's Film",
                detail_json=json.dumps({"rating": 5, "poster_url": "y"}),
                source="mishka",
                provider_uid="mishka:2026-07-08 21:00:00:bbbbbbbb",
            )
        )
        db.commit()


def test_repair_deletes_and_remaps_only_primary_users_watches():
    _seed_pre_fix_mixed_film_events()
    with SessionLocal() as db:
        pre = db.scalars(select(MemoryEvent).where(MemoryEvent.kind == "film")).all()
        assert len(pre) == 2  # the buggy pre-fix state: both housemates' watches

        result = repair.repair_film_attribution(db)
        db.commit()

        assert result["film_events_deleted"] == 2
        assert result["film_events_recreated"] == 1  # only Mack's watch comes back
        assert result["film_events_remaining"] == 1

        rows = db.scalars(select(MemoryEvent).where(MemoryEvent.kind == "film")).all()
        assert len(rows) == 1
        assert rows[0].title == "Mack's Film"


def test_repair_reassembles_journal_days_that_had_film_events():
    _seed_pre_fix_mixed_film_events()
    with SessionLocal() as db:
        from app.memory.assemble import assemble_day

        # Pre-repair: both days get assembled with their (buggy) film event.
        assemble_day(db, "2026-07-07", run_maps=False)
        assemble_day(db, "2026-07-08", run_maps=False)
        db.commit()

        jd_before = db.get(JournalDay, "2026-07-08")
        assert jd_before is not None
        assert jd_before.event_count == 1  # Amy's film, wrongly in Mack's journal

        result = repair.repair_film_attribution(db)
        db.commit()

        assert result["journal_days_reassembled"] == 2  # both 07-07 and 07-08 touched

        jd_after = db.get(JournalDay, "2026-07-08")
        assert jd_after.event_count == 0  # Amy's watch is gone from Mack's journal

        jd_07 = db.get(JournalDay, "2026-07-07")
        assert jd_07.event_count == 1  # Mack's own watch is untouched


def test_repair_is_idempotent():
    """The FIRST run fixes the buggy pre-existing state (deletes 2, keeps 1)
    -- that run's counts naturally differ from later ones. Idempotency means
    that once the well is in the corrected steady state, repeated runs keep
    reporting the SAME counts as each other (nothing left to fix, forever)."""
    _seed_pre_fix_mixed_film_events()
    with SessionLocal() as db:
        first = repair.repair_film_attribution(db)
        db.commit()
        second = repair.repair_film_attribution(db)
        db.commit()
        third = repair.repair_film_attribution(db)
        db.commit()

        assert first["film_events_remaining"] == 1
        assert second == third
        assert second["film_events_deleted"] == 1
        assert second["film_events_recreated"] == 1
        assert second["film_events_remaining"] == 1


def test_repair_with_no_film_events_is_a_noop():
    make_user(email="mack@example.com", display_name="Mack", role="primary")
    with SessionLocal() as db:
        result = repair.repair_film_attribution(db)
        db.commit()
        assert result == {
            "film_events_deleted": 0,
            "film_events_recreated": 0,
            "film_events_remaining": 0,
            "journal_days_reassembled": 0,
        }


def test_repair_never_touches_other_kinds():
    """Sanity: repair only deletes kind='film' rows -- other memory_events
    kinds (e.g. workouts already mapped) must survive untouched."""
    _seed_pre_fix_mixed_film_events()
    with SessionLocal() as db:
        from app.models import User, Workout

        mack_id = db.scalar(select(User.id).where(User.email == "mack@example.com"))
        db.add(
            Workout(
                user_id=mack_id,
                wtype="strength",
                ts_start="2026-07-07 18:00:00",
                ts_end="2026-07-07 18:52:00",
                duration_s=3120,
                source="Traditional Strength Training",
                provider_uid="derived:strength:2026-07-07 18:00:00",
            )
        )
        db.commit()
        mappers.map_workouts(db)
        db.commit()

        workout_count_before = len(
            db.scalars(select(MemoryEvent).where(MemoryEvent.kind == "workout")).all()
        )
        assert workout_count_before == 1

        repair.repair_film_attribution(db)
        db.commit()

        workout_count_after = len(
            db.scalars(select(MemoryEvent).where(MemoryEvent.kind == "workout")).all()
        )
        assert workout_count_after == 1
