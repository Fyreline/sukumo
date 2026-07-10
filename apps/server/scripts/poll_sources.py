#!/usr/bin/env python3
"""Calendar/weather/habit-evidence refresh entrypoint --
docs/ARCHITECTURE.md #2-3, docs/phases/PHASE-2-ingestion.md build item 5-6.

Sibling clients (Michi/Kakeibo/Mishka) land in Phase 3 and get wired in here
then; this phase wires calendar + weather + the habit auto-evidence pass
(per the explicit PHASE-2-ingestion.md build list).

Callable programmatically -- ``poll_calendar`` / ``poll_weather`` /
``run_habit_auto_evidence`` / ``run`` -- for tests and for
``coach_tick.py``'s "poll first" call (ARCHITECTURE.md #2: "one agent, not
two"); ``python scripts/poll_sources.py`` also runs standalone.

Every branch writes a sync_runs row, including 'not_configured' when
SUKUMO_ICS_URLS / SUKUMO_HOME_LAT&LON / SUKUMO_OFFICE_LAT&LON are unset
(ARCHITECTURE.md #5.6: "silence must be diagnosable from the Ops tile alone").
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.clients import calendar as calendar_client  # noqa: E402
from app.clients import weather as weather_client  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.habits import derive_auto_habit_events  # noqa: E402
from app.models import Base, CalendarEvent, SiblingSnapshot, SyncRun  # noqa: E402


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _window_bounds() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=calendar_client.WINDOW_PAST_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    end = (now + timedelta(days=calendar_client.WINDOW_FUTURE_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    return start, end


def _prune_snapshots(session: Session, app: str, keep: int = 50) -> None:
    rows = session.scalars(
        select(SiblingSnapshot).where(SiblingSnapshot.app == app).order_by(SiblingSnapshot.fetched_at.desc())
    ).all()
    for row in rows[keep:]:
        session.delete(row)


async def poll_calendar(session: Session, settings: Settings) -> dict:
    """Full-window replace per feed (DATA_MODEL #6 -- ICS has no deltas).
    Writes calendar_events + one sync_runs row ('poll:calendar'). One bad
    feed doesn't sink the others; returns per-feed counts for reporting."""
    started_at = _utcnow_str()
    urls = settings.ics_url_list
    if not urls:
        session.add(
            SyncRun(
                source="poll:calendar",
                started_at=started_at,
                finished_at=_utcnow_str(),
                status="not_configured",
                items=0,
                error=None,
            )
        )
        session.commit()
        return {"status": "not_configured", "feeds": []}

    window_start, window_end = _window_bounds()
    feed_results = []
    total_items = 0
    first_error: str | None = None

    for i, url in enumerate(urls):
        feed_label = f"feed-{i}"
        try:
            raw = await calendar_client.fetch_ics(url)
            events = calendar_client.parse_events(raw)
        except Exception as exc:  # noqa: BLE001 -- one feed's failure must not sink the poll
            first_error = first_error or str(exc)
            feed_results.append({"feed": feed_label, "status": "error", "error": str(exc), "count": 0})
            continue

        calendar_name = events[0]["calendar_name"] if events and events[0].get("calendar_name") else feed_label
        # normalise every row of THIS feed to one stable calendar_name --
        # the delete-then-replace below is keyed to exactly this feed's
        # rows, regardless of what X-WR-CALNAME says (can be blank/change).
        for e in events:
            e["calendar_name"] = calendar_name

        session.execute(
            delete(CalendarEvent).where(
                CalendarEvent.calendar_name == calendar_name,
                CalendarEvent.starts_at >= window_start,
                CalendarEvent.starts_at <= window_end,
            )
        )
        count = 0
        for e in events:
            existing = session.scalar(
                select(CalendarEvent).where(
                    CalendarEvent.ics_uid == e["ics_uid"], CalendarEvent.starts_at == e["starts_at"]
                )
            )
            if existing is not None:
                existing.ends_at = e["ends_at"]
                existing.all_day = e["all_day"]
                existing.title = e["title"]
                existing.location = e["location"]
                existing.calendar_name = e["calendar_name"]
            else:
                session.add(CalendarEvent(**e))
            count += 1
        session.commit()
        total_items += count
        feed_results.append({"feed": calendar_name, "status": "ok", "count": count})

    status = "error" if first_error and total_items == 0 else "ok"
    session.add(
        SyncRun(
            source="poll:calendar",
            started_at=started_at,
            finished_at=_utcnow_str(),
            status=status,
            items=total_items,
            error=first_error,
        )
    )
    session.commit()
    return {"status": status, "feeds": feed_results}


async def poll_weather(session: Session, settings: Settings) -> dict:
    """Fetches home+office Open-Meteo forecasts, writes one sibling_snapshots
    row (app='weather') + one sync_runs row ('poll:weather')."""
    started_at = _utcnow_str()
    t0 = datetime.now(timezone.utc)
    try:
        forecasts = await weather_client.fetch_home_and_office(settings)
    except weather_client.WeatherNotConfigured:
        session.add(
            SyncRun(
                source="poll:weather",
                started_at=started_at,
                finished_at=_utcnow_str(),
                status="not_configured",
                items=0,
                error=None,
            )
        )
        session.commit()
        return {"status": "not_configured"}
    except Exception as exc:  # noqa: BLE001
        session.add(
            SiblingSnapshot(
                app="weather", fetched_at=_utcnow_str(), ok=0, latency_ms=None, payload_json=None, error=str(exc)
            )
        )
        session.add(
            SyncRun(
                source="poll:weather",
                started_at=started_at,
                finished_at=_utcnow_str(),
                status="error",
                items=0,
                error=str(exc),
            )
        )
        session.commit()
        return {"status": "error", "error": str(exc)}

    latency_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    locations = [k for k in forecasts if not k.startswith("_")]
    session.add(
        SiblingSnapshot(
            app="weather",
            fetched_at=_utcnow_str(),
            ok=1,
            latency_ms=latency_ms,
            payload_json=json.dumps(forecasts),
            error=None,
        )
    )
    _prune_snapshots(session, "weather")
    session.add(
        SyncRun(
            source="poll:weather",
            started_at=started_at,
            finished_at=_utcnow_str(),
            status="ok",
            items=len(locations),
            error=None,
        )
    )
    session.commit()
    return {"status": "ok", "locations": locations}


def run_habit_auto_evidence(session: Session) -> dict:
    return derive_auto_habit_events(session)


async def run(session: Session | None = None) -> dict:
    settings = get_settings()
    owns_session = session is None
    session = session or SessionLocal()
    try:
        calendar_result = await poll_calendar(session, settings)
        weather_result = await poll_weather(session, settings)
        habit_result = run_habit_auto_evidence(session)
        return {"calendar": calendar_result, "weather": weather_result, "habits": habit_result}
    finally:
        if owns_session:
            session.close()


def main() -> None:
    Base.metadata.create_all(engine)  # no Alembic (ARCHITECTURE.md #4); mirrors app.main's lifespan
    result = asyncio.run(run())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
