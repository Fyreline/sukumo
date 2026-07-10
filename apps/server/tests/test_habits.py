"""Habits router (config CRUD + the 1-tap log) and app.habits'
derive_auto_habit_events (delete+rebuild 'auto' rows, never touch
'tap'/'coach_confirm') -- docs/DATA_MODEL.md #2, docs/phases/PHASE-2-ingestion.md
acceptance list."""
from __future__ import annotations

import json

from tests.conftest import make_user


def test_create_list_and_patch_habit(authed):
    client, user_id, headers = authed
    res = client.post(
        "/api/habits",
        json={"key": "gym", "title": "Gym", "kind": "auto", "evidence": "workouts:wtype in cfg"},
        headers=headers,
    )
    assert res.status_code == 200
    habit_id = res.json()["id"]
    assert res.json()["active"] is True

    listed = client.get("/api/habits", headers=headers)
    assert listed.status_code == 200
    assert any(h["key"] == "gym" for h in listed.json())

    patched = client.patch(f"/api/habits/{habit_id}", json={"active": False}, headers=headers)
    assert patched.status_code == 200
    assert patched.json()["active"] is False


def test_create_duplicate_key_conflicts(authed):
    client, user_id, headers = authed
    client.post("/api/habits", json={"key": "gym", "title": "Gym", "kind": "auto"}, headers=headers)
    res = client.post("/api/habits", json={"key": "gym", "title": "Gym 2", "kind": "auto"}, headers=headers)
    assert res.status_code == 409


def test_habits_require_jwt_auth(client):
    res = client.get("/api/habits")
    assert res.status_code == 401


def test_one_tap_log_is_idempotent_same_day(authed):
    client, user_id, headers = authed
    create = client.post("/api/habits", json={"key": "reading", "title": "Reading", "kind": "tap"}, headers=headers)
    habit_id = create.json()["id"]

    first = client.post(f"/api/habits/{habit_id}/events", json={"local_date": "2026-06-01"}, headers=headers)
    second = client.post(f"/api/habits/{habit_id}/events", json={"local_date": "2026-06-01"}, headers=headers)
    assert first.json()["created"] is True
    assert second.json()["created"] is False

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import HabitEvent

    with SessionLocal() as db:
        assert len(db.scalars(select(HabitEvent).where(HabitEvent.habit_id == habit_id)).all()) == 1


def test_one_tap_log_missing_habit_404s(authed):
    client, user_id, headers = authed
    res = client.post("/api/habits/999/events", json={}, headers=headers)
    assert res.status_code == 404


# ---------------------------------------------------------- auto-evidence --
def _make_habit(user_id: int, key: str, wtypes: list[str], evidence: str = "workouts:wtype in cfg") -> int:
    from app.db import SessionLocal
    from app.models import Habit

    with SessionLocal() as db:
        habit = Habit(
            user_id=user_id,
            key=key,
            title=key,
            kind="auto",
            target_json="{}",
            evidence=evidence,
            active=1,
            config_json=json.dumps({"wtypes": wtypes}),
        )
        db.add(habit)
        db.commit()
        return habit.id


def _make_workout(user_id: int, wtype: str, ts_start: str) -> None:
    from app.db import SessionLocal
    from app.models import Workout

    with SessionLocal() as db:
        db.add(
            Workout(
                user_id=user_id,
                wtype=wtype,
                ts_start=ts_start,
                ts_end=None,
                duration_s=1800,
                kcal=200,
                distance_m=None,
                source="Test Workout",
                provider_uid=f"test:{wtype}:{ts_start}",
            )
        )
        db.commit()


def test_derive_auto_habit_events_builds_rows_from_matching_workouts(client):
    from app.db import SessionLocal
    from app.habits import derive_auto_habit_events

    user_id = make_user()
    habit_id = _make_habit(user_id, "gym", ["strength", "hiit"])
    _make_workout(user_id, "strength", "2026-06-01 07:00:00")
    _make_workout(user_id, "hiit", "2026-06-03 07:00:00")
    _make_workout(user_id, "run", "2026-06-02 07:00:00")  # not in cfg -> ignored

    with SessionLocal() as db:
        result = derive_auto_habit_events(db)
    assert result["habits_processed"] == 1
    assert result["events_written"] == 2

    from sqlalchemy import select

    from app.models import HabitEvent

    with SessionLocal() as db:
        rows = db.scalars(select(HabitEvent).where(HabitEvent.habit_id == habit_id)).all()
        assert {r.local_date for r in rows} == {"2026-06-01", "2026-06-03"}
        assert all(r.source == "auto" for r in rows)


def test_derive_auto_habit_events_delete_rebuilds_on_second_run(client):
    from app.db import SessionLocal
    from app.habits import derive_auto_habit_events

    user_id = make_user()
    habit_id = _make_habit(user_id, "gym", ["strength"])
    _make_workout(user_id, "strength", "2026-06-01 07:00:00")

    with SessionLocal() as db:
        derive_auto_habit_events(db)

    # a workout is deleted (simulating a correction) -- the rebuild must
    # remove the now-stale 'auto' row, not just append.
    from sqlalchemy import delete

    from app.models import Workout

    with SessionLocal() as db:
        db.execute(delete(Workout))
        db.commit()
        derive_auto_habit_events(db)

    from sqlalchemy import select

    from app.models import HabitEvent

    with SessionLocal() as db:
        rows = db.scalars(select(HabitEvent).where(HabitEvent.habit_id == habit_id)).all()
        assert rows == []


def test_derive_auto_habit_events_never_touches_tap_or_coach_confirm_rows(client):
    from app.db import SessionLocal
    from app.habits import derive_auto_habit_events
    from app.models import HabitEvent

    user_id = make_user()
    habit_id = _make_habit(user_id, "gym", ["strength"])

    with SessionLocal() as db:
        db.add(HabitEvent(habit_id=habit_id, local_date="2026-05-01", value=1, source="tap", note="human logged"))
        db.add(HabitEvent(habit_id=habit_id, local_date="2026-05-02", value=1, source="coach_confirm"))
        db.commit()

    _make_workout(user_id, "strength", "2026-06-01 07:00:00")

    with SessionLocal() as db:
        derive_auto_habit_events(db)
        derive_auto_habit_events(db)  # run twice to prove no duplication/removal of human rows either

    from sqlalchemy import select

    with SessionLocal() as db:
        rows = db.scalars(select(HabitEvent).where(HabitEvent.habit_id == habit_id)).all()
        by_source = {r.source: r for r in rows}
        assert "tap" in by_source and by_source["tap"].local_date == "2026-05-01"
        assert "coach_confirm" in by_source
        assert by_source["auto"].local_date == "2026-06-01"
        assert len(rows) == 3


def test_derive_auto_habit_events_ignores_habits_without_matching_evidence_string(client):
    from app.db import SessionLocal
    from app.habits import derive_auto_habit_events

    user_id = make_user()
    _make_habit(user_id, "reading", [], evidence="events:reading")

    with SessionLocal() as db:
        result = derive_auto_habit_events(db)
    assert result["habits_processed"] == 0
