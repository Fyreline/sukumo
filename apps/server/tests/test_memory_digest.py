"""Digests — weekly week-vs-week (neutral phrasing) + trip range.
docs/MEMORY.md §3, COACH §0/§5, docs/phases/PHASE-7-memory.md item 3. SYNTHETIC."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from app.coach import config as coach_config
from app.db import SessionLocal
from app.memory import digest as D
from app.models import Digest, JournalDay, MemoryEvent

from .conftest import make_user


def _journal_day(db, local_date, *, steps=0, workouts=0, study=False, films=0, photos=0, events=0):
    db.add(
        JournalDay(
            local_date=local_date,
            assembled_at=f"{local_date} 02:30:00",
            summary_md=f"## {local_date}\n\nA synthetic day.\n",
            stats_json=json.dumps(
                {"steps": steps, "workouts": workouts, "study": study, "films": films, "photos": photos}
            ),
            event_count=events,
            mood=None,
        )
    )


# Words that would signal a trend/medical judgement — banned by COACH §0.
_BANNED = ["up from", "down from", "improved", "declined", "better", "worse", "on track", "behind", "should", "keep it up", "well done"]


def test_weekly_digest_neutral_phrasing_and_week_vs_week():
    make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        # this week (Mon 6 Jul – Sun 12 Jul 2026), end_date = Sat 11th
        _journal_day(db, "2026-07-06", steps=8000, workouts=1, study=True, films=1, events=3)
        _journal_day(db, "2026-07-08", steps=5000, study=True, events=1)
        _journal_day(db, "2026-07-11", steps=6000, events=1)
        # previous week
        _journal_day(db, "2026-07-01", steps=4000, workouts=1, events=1)
        _journal_day(db, "2026-06-30", steps=3000, events=1)
        db.commit()

        start, end, md, totals = D.compose_weekly(db, date(2026, 7, 11))
        assert start == "2026-07-05"
        assert end == "2026-07-11"
        assert totals["steps"] == 19000
        # both weeks' numbers appear, side by side
        assert "19,000" in md
        assert "previous week" in md
        low = md.lower()
        for bad in _BANNED:
            assert bad not in low, f"banned trend phrase leaked: {bad!r}"


def test_weekly_digest_persists_and_is_idempotent():
    make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        _journal_day(db, "2026-07-11", steps=6000, events=1)
        db.commit()
        d1 = D.weekly_digest(db, date(2026, 7, 11))
        first_id = d1.id
        d2 = D.weekly_digest(db, date(2026, 7, 11))
        assert d2.id == first_id  # upsert, not duplicate
        rows = db.query(Digest).filter(Digest.kind == "weekly").all()
        assert len(rows) == 1


def test_weekly_moment_of_week_prefers_best_film():
    make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        _journal_day(db, "2026-07-08", films=1, photos=3, events=2)
        db.add(
            MemoryEvent(
                user_id=None,
                ts="2026-07-08 20:00:00",
                kind="film",
                title="A Fixtured Favourite",
                detail_json=json.dumps({"rating": 5}),
                source="mishka",
                provider_uid="mf1",
            )
        )
        db.add(
            MemoryEvent(
                user_id=None,
                ts="2026-07-08 12:00:00",
                kind="photo",
                title="3 photos",
                detail_json=json.dumps({"count": 3, "places": []}),
                source="photos",
                provider_uid="photo:2026-07-08",
            )
        )
        db.commit()
        _s, _e, md, _t = D.compose_weekly(db, date(2026, 7, 11))
        assert "Moment of the week" in md
        assert "A Fixtured Favourite" in md


def test_trip_digest_on_fixtured_three_day_trip():
    make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        for i, dstr in enumerate(("2026-09-10", "2026-09-11", "2026-09-12")):
            db.add(
                JournalDay(
                    local_date=dstr,
                    assembled_at=f"{dstr} 02:30:00",
                    summary_md=f"## Day {i + 1}\n\nA synthetic trip day.\n",
                    stats_json=json.dumps({"steps": 12000, "photos": 40, "films": 0}),
                    event_count=5,
                    mood=None,
                )
            )
        db.commit()
        row = D.trip_digest(db, date(2026, 9, 10), date(2026, 9, 12), title="Fuji")
        assert row.kind == "trip"
        assert "# Fuji" in row.content_md  # cover header
        assert row.content_md.count("A synthetic trip day.") == 3  # each day stitched in
        assert "photos" in row.content_md.lower()


def test_maybe_trip_digest_unset_is_noop():
    make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        # japan_range unset today (MEMORY §3) → no-op
        out = D.maybe_trip_digest(db, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
        assert out["status"] == "not_configured"
        assert db.query(Digest).count() == 0


def test_maybe_trip_digest_fires_after_range_ends():
    make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        coach_config.set_setting(
            db, coach_config.KEY_JAPAN_RANGE, {"start": "2026-09-10", "end": "2026-09-12", "title": "Fuji"}
        )
        _journal_day(db, "2026-09-11", steps=12000, photos=40, events=5)
        db.commit()
        # before the range ends → pending, nothing written
        assert D.maybe_trip_digest(db, now=datetime(2026, 9, 11, tzinfo=timezone.utc))["status"] == "pending"
        assert db.query(Digest).count() == 0
        # after it ends → the trip digest lands
        out = D.maybe_trip_digest(db, now=datetime(2026, 9, 14, tzinfo=timezone.utc))
        assert out["status"] == "ok"
        assert db.query(Digest).filter(Digest.kind == "trip").count() == 1
