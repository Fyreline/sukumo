"""scripts/poll_sources.py -- calendar full-window replace, weather
snapshot + not_configured path, sync_runs everywhere
(docs/phases/PHASE-2-ingestion.md build item 5, acceptance list). The
sibling clients (michi/kakeibo/mishka -- docs/phases/PHASE-3-siblings.md
build item 4) reuse the exact same not_configured/error/ok shape."""
from __future__ import annotations

import json
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


# ============ sibling clients (michi/kakeibo/mishka) -- PHASE-3 build item 4 ============


@pytest.mark.anyio
async def test_poll_michi_not_configured_when_no_token():
    with SessionLocal() as db:
        result = await poll_sources.poll_michi(db, _settings())
    assert result["status"] == "not_configured"

    from sqlalchemy import select

    from app.models import SiblingSnapshot, SyncRun

    with SessionLocal() as db:
        run = db.scalar(select(SyncRun).where(SyncRun.source == "poll:michi"))
        assert run.status == "not_configured"
        assert db.scalar(select(SiblingSnapshot).where(SiblingSnapshot.app == "michi")) is None


@pytest.mark.anyio
async def test_poll_michi_writes_ok_snapshot_and_sync_run(monkeypatch):
    from app.clients import michi as michi_client

    async def _fake_fetch(settings, timeout: float = 3.0):
        return {"streak_days": 5, "studied_today": True, "due_reviews": 2, "words_known": 90, "last_session_at": "2026-07-10 08:00:00"}

    monkeypatch.setattr(michi_client, "fetch", _fake_fetch)

    with SessionLocal() as db:
        result = await poll_sources.poll_michi(db, _settings(michi_service_token="secret"))
    assert result["status"] == "ok"

    from sqlalchemy import select

    from app.models import SiblingSnapshot, SyncRun

    with SessionLocal() as db:
        snapshot = db.scalar(select(SiblingSnapshot).where(SiblingSnapshot.app == "michi"))
        assert snapshot is not None
        assert snapshot.ok == 1
        assert snapshot.latency_ms is not None
        assert json.loads(snapshot.payload_json) == {
            "streak_days": 5, "studied_today": True, "due_reviews": 2, "words_known": 90, "last_session_at": "2026-07-10 08:00:00"
        }
        run = db.scalar(select(SyncRun).where(SyncRun.source == "poll:michi"))
        assert run.status == "ok"


@pytest.mark.anyio
async def test_poll_michi_writes_error_snapshot_on_fetch_failure(monkeypatch):
    from app.clients import michi as michi_client

    async def _fake_fetch(settings, timeout: float = 3.0):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(michi_client, "fetch", _fake_fetch)

    with SessionLocal() as db:
        result = await poll_sources.poll_michi(db, _settings(michi_service_token="secret"))
    assert result["status"] == "error"

    from sqlalchemy import select

    from app.models import SiblingSnapshot, SyncRun

    with SessionLocal() as db:
        snapshot = db.scalar(select(SiblingSnapshot).where(SiblingSnapshot.app == "michi"))
        assert snapshot.ok == 0
        assert snapshot.error == "connection refused"
        assert snapshot.payload_json is None
        run = db.scalar(select(SyncRun).where(SyncRun.source == "poll:michi"))
        assert run.status == "error"
        assert run.error == "connection refused"


@pytest.mark.anyio
async def test_poll_kakeibo_not_configured_when_no_token():
    """Scope note: Kakeibo's own endpoint doesn't exist yet this phase, so
    this always resolves not_configured with the default settings -- never
    an error, per docs/API.md §4's fallback wording."""
    with SessionLocal() as db:
        result = await poll_sources.poll_kakeibo(db, _settings())
    assert result["status"] == "not_configured"


@pytest.mark.anyio
async def test_poll_kakeibo_writes_ok_snapshot_when_mocked(monkeypatch):
    from app.clients import kakeibo as kakeibo_client

    async def _fake_fetch(settings, timeout: float = 3.0):
        return {"goal_pence": 2000000, "saved_pence": 500000, "pct": 25.0, "pace_status": "on_track", "as_of": "2026-07-10 00:00:00"}

    monkeypatch.setattr(kakeibo_client, "fetch", _fake_fetch)

    with SessionLocal() as db:
        result = await poll_sources.poll_kakeibo(db, _settings(kakeibo_service_token="secret"))
    assert result["status"] == "ok"

    from sqlalchemy import select

    from app.models import SiblingSnapshot

    with SessionLocal() as db:
        snapshot = db.scalar(select(SiblingSnapshot).where(SiblingSnapshot.app == "kakeibo"))
        assert snapshot.ok == 1


@pytest.mark.anyio
async def test_poll_mishka_not_configured_when_no_token():
    with SessionLocal() as db:
        result = await poll_sources.poll_mishka(db, _settings())
    assert result["status"] == "not_configured"


@pytest.mark.anyio
async def test_poll_mishka_writes_ok_snapshot_when_mocked(monkeypatch):
    from app.clients import mishka as mishka_client

    async def _fake_fetch(settings, timeout: float = 3.0):
        return {"recent": [{"title": "Paddington", "watched_at": "2026-07-09", "poster_url": None, "rating": 4.5}], "watchlist_count": 3}

    monkeypatch.setattr(mishka_client, "fetch", _fake_fetch)

    with SessionLocal() as db:
        result = await poll_sources.poll_mishka(db, _settings(mishka_service_token="secret"))
    assert result["status"] == "ok"

    from sqlalchemy import select

    from app.models import SiblingSnapshot

    with SessionLocal() as db:
        snapshot = db.scalar(select(SiblingSnapshot).where(SiblingSnapshot.app == "mishka"))
        assert snapshot.ok == 1
        assert json.loads(snapshot.payload_json)["watchlist_count"] == 3


@pytest.mark.anyio
async def test_sibling_snapshots_pruned_to_50_per_app(monkeypatch):
    """DATA_MODEL §6: 'keep last N=50 per app, prune on insert.'"""
    from app.clients import michi as michi_client
    from sqlalchemy import select

    from app.models import SiblingSnapshot

    async def _fake_fetch(settings, timeout: float = 3.0):
        return {"streak_days": 1, "studied_today": False, "due_reviews": 0, "words_known": 1, "last_session_at": None}

    monkeypatch.setattr(michi_client, "fetch", _fake_fetch)

    settings = _settings(michi_service_token="secret")
    for _ in range(55):
        with SessionLocal() as db:
            await poll_sources.poll_michi(db, settings)

    with SessionLocal() as db:
        count = len(db.scalars(select(SiblingSnapshot).where(SiblingSnapshot.app == "michi")).all())
        assert count == 50


@pytest.mark.anyio
async def test_run_includes_all_three_sibling_results():
    with SessionLocal() as db:
        result = await poll_sources.run(db)
    assert result["michi"]["status"] == "not_configured"
    assert result["kakeibo"]["status"] == "not_configured"
    assert result["mishka"]["status"] == "not_configured"
