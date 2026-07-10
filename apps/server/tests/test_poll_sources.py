"""scripts/poll_sources.py -- calendar full-window replace, weather
snapshot + not_configured path, sync_runs everywhere
(docs/phases/PHASE-2-ingestion.md build item 5, acceptance list)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.clients import calendar as calendar_client
from app.config import Settings
from app.db import SessionLocal
from scripts import poll_sources

FIXTURE = Path(__file__).parent / "fixtures" / "sample_calendar.ics"


def _settings(**overrides) -> Settings:
    base = dict(
        ics_urls="https://example.invalid/feed.ics",
        home_lat=None,
        home_lon=None,
        office_lat=None,
        office_lon=None,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(autouse=True)
def _stub_fetch_ics(monkeypatch):
    """Never hits the network -- returns the synthetic fixture every time."""

    async def _fake_fetch(url: str, timeout: float = 15.0) -> bytes:
        return FIXTURE.read_bytes()

    monkeypatch.setattr(calendar_client, "fetch_ics", _fake_fetch)
    yield


@pytest.mark.anyio
async def test_poll_calendar_not_configured_when_no_urls():
    with SessionLocal() as db:
        result = await poll_sources.poll_calendar(db, _settings(ics_urls=""))
    assert result["status"] == "not_configured"

    from sqlalchemy import select

    from app.models import SyncRun

    with SessionLocal() as db:
        run = db.scalar(select(SyncRun).where(SyncRun.source == "poll:calendar"))
        assert run.status == "not_configured"


@pytest.mark.anyio
async def test_poll_calendar_writes_events_and_sync_run():
    with SessionLocal() as db:
        result = await poll_sources.poll_calendar(db, _settings())
    assert result["status"] == "ok"
    assert result["feeds"][0]["count"] > 0

    from sqlalchemy import select

    from app.models import CalendarEvent, SyncRun

    with SessionLocal() as db:
        count = len(db.scalars(select(CalendarEvent)).all())
        assert count == result["feeds"][0]["count"]
        run = db.scalar(select(SyncRun).where(SyncRun.source == "poll:calendar"))
        assert run.status == "ok"
        assert run.items == count


@pytest.mark.anyio
async def test_poll_calendar_twice_is_a_stable_row_count():
    """Acceptance list: 'Calendar fixture poll twice -> stable row count.'"""
    with SessionLocal() as db:
        await poll_sources.poll_calendar(db, _settings())

    from sqlalchemy import select

    from app.models import CalendarEvent

    with SessionLocal() as db:
        first_count = len(db.scalars(select(CalendarEvent)).all())

    with SessionLocal() as db:
        await poll_sources.poll_calendar(db, _settings())

    with SessionLocal() as db:
        second_count = len(db.scalars(select(CalendarEvent)).all())

    assert first_count == second_count


@pytest.mark.anyio
async def test_poll_calendar_one_bad_feed_does_not_sink_the_others(monkeypatch):
    calls = {"n": 0}

    async def _flaky_fetch(url: str, timeout: float = 15.0) -> bytes:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("feed unreachable")
        return FIXTURE.read_bytes()

    monkeypatch.setattr(calendar_client, "fetch_ics", _flaky_fetch)

    settings = _settings(ics_urls="https://example.invalid/bad.ics,https://example.invalid/good.ics")
    with SessionLocal() as db:
        result = await poll_sources.poll_calendar(db, settings)

    assert result["status"] == "ok"  # the good feed's rows still count as success
    assert result["feeds"][0]["status"] == "error"
    assert result["feeds"][1]["status"] == "ok"


@pytest.mark.anyio
async def test_poll_weather_not_configured_when_no_coords():
    with SessionLocal() as db:
        result = await poll_sources.poll_weather(db, _settings())
    assert result["status"] == "not_configured"

    from sqlalchemy import select

    from app.models import SiblingSnapshot, SyncRun

    with SessionLocal() as db:
        run = db.scalar(select(SyncRun).where(SyncRun.source == "poll:weather"))
        assert run.status == "not_configured"
        assert db.scalar(select(SiblingSnapshot).where(SiblingSnapshot.app == "weather")) is None


@pytest.mark.anyio
async def test_poll_weather_writes_snapshot_and_sync_run(monkeypatch):
    async def _fake_forecast(settings, timeout: float = 10.0):
        return {"home": {"daily": {"temperature_2m_max": [21.0]}}, "_fetched_at": "2026-06-01 00:00:00"}

    from app.clients import weather as weather_client

    monkeypatch.setattr(weather_client, "fetch_home_and_office", _fake_forecast)

    with SessionLocal() as db:
        result = await poll_sources.poll_weather(db, _settings(home_lat=55.95, home_lon=-3.19))
    assert result["status"] == "ok"

    from sqlalchemy import select

    from app.models import SiblingSnapshot, SyncRun

    with SessionLocal() as db:
        snapshot = db.scalar(select(SiblingSnapshot).where(SiblingSnapshot.app == "weather"))
        assert snapshot is not None
        assert snapshot.ok == 1
        run = db.scalar(select(SyncRun).where(SyncRun.source == "poll:weather"))
        assert run.status == "ok"


def test_run_habit_auto_evidence_delegates_to_app_habits():
    with SessionLocal() as db:
        result = poll_sources.run_habit_auto_evidence(db)
    assert result == {"habits_processed": 0, "events_written": 0}
