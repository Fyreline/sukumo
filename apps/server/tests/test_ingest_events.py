"""POST /api/ingest/event -- reading -> habit_events(tap) idempotent per
day, office arrived/left -> memory_events(kind='place'), manual/milestone ->
memory_events -- docs/API.md #3, docs/phases/PHASE-2-ingestion.md acceptance
list."""
from __future__ import annotations

from tests.conftest import ingest_headers, make_ingest_token, make_user


def _mint(user_id: int | None) -> dict:
    raw, _id = make_ingest_token(scope="ingest", user_id=user_id)
    return ingest_headers(raw)


def test_reading_event_creates_habit_and_tap_event(client):
    user_id = make_user()
    headers = _mint(user_id)

    res = client.post(
        "/api/ingest/event",
        json={"kind": "reading", "ts": "2026-06-01T20:00:00+01:00"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "reading"
    assert body["created"] is True
    assert body["local_date"] == "2026-06-01"  # BST -> same local day

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Habit, HabitEvent

    with SessionLocal() as db:
        habit = db.scalar(select(Habit).where(Habit.key == "reading"))
        assert habit is not None
        assert habit.kind == "tap"
        events = db.scalars(select(HabitEvent).where(HabitEvent.habit_id == habit.id)).all()
        assert len(events) == 1
        assert events[0].source == "tap"


def test_reading_event_same_day_is_idempotent(client):
    headers = _mint(make_user())
    first = client.post(
        "/api/ingest/event", json={"kind": "reading", "ts": "2026-06-01T09:00:00+01:00"}, headers=headers
    )
    second = client.post(
        "/api/ingest/event", json={"kind": "reading", "ts": "2026-06-01T21:00:00+01:00"}, headers=headers
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False  # same Europe/London local day -> no dup

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import HabitEvent

    with SessionLocal() as db:
        assert db.scalar(select(HabitEvent)).local_date == "2026-06-01"
        assert len(db.scalars(select(HabitEvent)).all()) == 1


def test_reading_event_different_day_creates_second_row(client):
    headers = _mint(make_user())
    client.post("/api/ingest/event", json={"kind": "reading", "ts": "2026-06-01T21:00:00+01:00"}, headers=headers)
    client.post("/api/ingest/event", json={"kind": "reading", "ts": "2026-06-02T21:00:00+01:00"}, headers=headers)

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import HabitEvent

    with SessionLocal() as db:
        assert len(db.scalars(select(HabitEvent)).all()) == 2


def test_office_arrived_creates_memory_event(client):
    headers = _mint(make_user())
    res = client.post(
        "/api/ingest/event",
        json={"kind": "office", "state": "arrived", "ts": "2026-06-01T09:05:00+01:00"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["mem_kind"] == "place"
    assert body["created"] is True

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import MemoryEvent

    with SessionLocal() as db:
        row = db.scalar(select(MemoryEvent))
        assert row.kind == "place"
        assert row.title == "Office arrived"
        assert row.source == "ingest:event"


def test_repeated_identical_office_event_is_idempotent(client):
    headers = _mint(make_user())
    payload = {"kind": "office", "state": "arrived", "ts": "2026-06-01T09:05:00+01:00"}
    client.post("/api/ingest/event", json=payload, headers=headers)
    res = client.post("/api/ingest/event", json=payload, headers=headers)
    assert res.json()["created"] is False

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import MemoryEvent

    with SessionLocal() as db:
        assert len(db.scalars(select(MemoryEvent)).all()) == 1


def test_office_left_is_distinct_from_arrived(client):
    headers = _mint(make_user())
    ts = "2026-06-01T17:30:00+01:00"
    client.post("/api/ingest/event", json={"kind": "office", "state": "arrived", "ts": ts}, headers=headers)
    client.post("/api/ingest/event", json={"kind": "office", "state": "left", "ts": ts}, headers=headers)

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import MemoryEvent

    with SessionLocal() as db:
        assert len(db.scalars(select(MemoryEvent)).all()) == 2


def test_manual_event_creates_memory_event_with_given_title(client):
    headers = _mint(make_user())
    res = client.post(
        "/api/ingest/event",
        json={"kind": "manual", "title": "Remembered something nice"},
        headers=headers,
    )
    assert res.status_code == 200

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import MemoryEvent

    with SessionLocal() as db:
        row = db.scalar(select(MemoryEvent))
        assert row.kind == "manual"
        assert row.title == "Remembered something nice"


def test_milestone_event_creates_memory_event(client):
    headers = _mint(make_user())
    res = client.post("/api/ingest/event", json={"kind": "milestone", "title": "Finished a book"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["mem_kind"] == "milestone"


def test_unknown_kind_is_rejected(client):
    headers = _mint(make_user())
    res = client.post("/api/ingest/event", json={"kind": "not-a-real-kind"}, headers=headers)
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_payload"


def test_event_ingest_writes_sync_run(client):
    headers = _mint(make_user())
    client.post("/api/ingest/event", json={"kind": "manual", "title": "x"}, headers=headers)

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import SyncRun

    with SessionLocal() as db:
        run = db.scalar(select(SyncRun).where(SyncRun.source == "ingest:event"))
        assert run is not None
        assert run.status == "ok"


def test_reading_event_falls_back_to_primary_user_when_token_unowned(client):
    """A household-bus-style token (user_id=None) can still log 'reading' --
    it resolves to the household's primary user (app.ingest.events)."""
    primary_id = make_user(email="mack@example.com", role="primary")
    headers = _mint(None)

    res = client.post("/api/ingest/event", json={"kind": "reading"}, headers=headers)
    assert res.status_code == 200

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Habit

    with SessionLocal() as db:
        habit = db.scalar(select(Habit).where(Habit.key == "reading"))
        assert habit.user_id == primary_id
