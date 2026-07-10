"""Day assembly — determinism, thin days, late-data re-run, anniversary.
docs/MEMORY.md §3-4, docs/phases/PHASE-7-memory.md item 2. SYNTHETIC data only."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import SessionLocal
from app.memory import assemble as A
from app.models import HealthSample, JournalDay, MemoryEvent, User

from .conftest import make_user


def _primary() -> int:
    return make_user(email="mack@example.com", role="primary")


def _mem(db, *, kind, ts, title, source, provider_uid, detail=None, user_id=None):
    db.add(
        MemoryEvent(
            user_id=user_id,
            ts=ts,
            kind=kind,
            title=title,
            detail_json=json.dumps(detail or {}),
            source=source,
            provider_uid=provider_uid,
        )
    )


def _steps(db, uid, local_date, qty):
    db.add(
        HealthSample(
            user_id=uid,
            metric="step_count",
            ts_start=f"{local_date} 10:00:00",
            ts_end=None,
            value=float(qty),
            unit="count",
            source="shortcut",
        )
    )


def test_assembly_is_byte_identical_on_rerun():
    uid = _primary()
    with SessionLocal() as db:
        _steps(db, uid, "2026-07-08", 8123)
        _mem(db, kind="workout", ts="2026-07-08 18:00:00", title="Strength, 52 min", source="workouts", provider_uid="w1")
        _mem(db, kind="film", ts="2026-07-08 21:00:00", title="A Synthetic Film", source="mishka", provider_uid="f1", detail={"rating": 4})
        db.commit()

        first = A.assemble_day(db, "2026-07-08", run_maps=False)
        snap1 = (first.summary_md, first.stats_json, first.event_count, first.assembled_at)

        second = A.assemble_day(db, "2026-07-08", run_maps=False)
        snap2 = (second.summary_md, second.stats_json, second.event_count, second.assembled_at)

        # Deterministic content AND an unmoved assembled_at (nothing changed).
        assert snap1 == snap2
        assert "8,123 steps" in first.summary_md
        assert "Strength, 52 min".lower() in first.summary_md.lower()


def test_thin_day_reads_short():
    uid = _primary()
    with SessionLocal() as db:
        _steps(db, uid, "2026-07-08", 4102)
        db.commit()
        jd = A.assemble_day(db, "2026-07-08", run_maps=False)
        assert jd.event_count == 0
        assert "quiet" in jd.summary_md.lower()
        assert "4,102 steps" in jd.summary_md
        # short: header + one line
        body_lines = [ln for ln in jd.summary_md.splitlines() if ln.strip() and not ln.startswith("#")]
        assert len(body_lines) == 1


def test_empty_day_is_honest_not_empty():
    _primary()
    with SessionLocal() as db:
        jd = A.assemble_day(db, "2026-07-08", run_maps=False)
        assert "quiet" in jd.summary_md.lower()
        assert jd.event_count == 0


def test_late_data_reassembly_updates_and_bumps_assembled_at():
    uid = _primary()
    with SessionLocal() as db:
        _steps(db, uid, "2026-07-08", 4000)
        db.commit()
        jd = A.assemble_day(db, "2026-07-08", run_maps=False)
        first_summary = jd.summary_md
        first_assembled = jd.assembled_at

        # a late HAE sync lands a workout for that same day
        _mem(db, kind="workout", ts="2026-07-08 19:00:00", title="Run, 30 min", source="workouts", provider_uid="late-w")
        db.commit()
        # force assembled_at to be observably different (whole-second clock)
        import time

        time.sleep(1.05)
        jd2 = A.assemble_day(db, "2026-07-08", run_maps=False)
        assert jd2.summary_md != first_summary
        assert "Run, 30 min".lower() in jd2.summary_md.lower()
        assert jd2.assembled_at != first_assembled


def test_assemble_yesterday_reruns_day_before():
    uid = _primary()
    now = datetime(2026, 7, 10, 3, 0, tzinfo=timezone.utc)  # 04:00 London, so "yesterday"=09th
    with SessionLocal() as db:
        _steps(db, uid, "2026-07-09", 5000)  # yesterday
        _steps(db, uid, "2026-07-08", 6000)  # day-before
        db.commit()
        out = A.assemble_yesterday(db, now=now)
        assert out["assembled"] == ["2026-07-08", "2026-07-09"]
        assert db.get(JournalDay, "2026-07-08") is not None
        assert db.get(JournalDay, "2026-07-09") is not None


def test_anniversary_lookback_hits_past_year():
    _primary()
    with SessionLocal() as db:
        # a journal day exactly one year before the queried date
        db.add(
            JournalDay(
                local_date="2025-07-08",
                assembled_at="2025-07-09 02:30:00",
                summary_md="## Tuesday 8 July 2025\n\nSomething happened.\n",
                stats_json="{}",
                event_count=2,
                mood=None,
            )
        )
        db.commit()
        hits = A.anniversary(db, "2026-07-08")
        assert len(hits) == 1
        assert hits[0]["years_ago"] == 1
        assert hits[0]["local_date"] == "2025-07-08"
        # a date with no past-year row returns nothing
        assert A.anniversary(db, "2026-03-03") == []
