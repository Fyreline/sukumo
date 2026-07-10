"""POST /api/ingest/health -- both payload shapes, the metric mapping dict,
unknown-metric passthrough, workout upsert, idempotency, sync_runs
(docs/API.md #2, docs/phases/PHASE-2-ingestion.md acceptance list).

All fixtures below are entirely synthetic -- invented dates/values, no
relation to any real device export.
"""
from __future__ import annotations

from tests.conftest import ingest_headers, make_ingest_token, make_user

# ---------------------------------------------------------------- fixtures --
PATH_A_PAYLOAD = {
    "metrics": [
        {"metric": "step_count", "date": "2026-06-01", "qty": 8123, "unit": "count"},
        {"metric": "active_energy", "date": "2026-06-01", "qty": 410.5, "unit": "kcal"},
        {"metric": "resting_heart_rate", "date": "2026-06-01", "qty": 58, "unit": "bpm"},
        {"metric": "stand_hours", "date": "2026-06-01", "qty": 11, "unit": "count"},
        {"metric": "sleep_analysis", "date": "2026-06-01", "qty": 420, "unit": "min"},
        # deliberately unknown, must be stored verbatim rather than rejected
        {"metric": "Body Fat Percentage", "date": "2026-06-01", "qty": 18.2, "unit": "%"},
    ],
    "workouts": [
        {
            "name": "Traditional Strength Training",
            "start": "2026-06-01T07:00:00+01:00",
            "end": "2026-06-01T07:52:00+01:00",
            "duration_s": 3120,
            "kcal": 310,
            "distance_m": 0,
        }
    ],
}

PATH_B_PAYLOAD = {
    "data": {
        "metrics": [
            {
                "name": "step_count",
                "units": "count",
                "data": [{"date": "2026-06-02 00:00:00 +0000", "qty": 9450}],
            },
            {
                "name": "heart_rate",
                "units": "bpm",
                "data": [{"date": "2026-06-02 12:00:00 +0000", "avg": 71, "min": 60, "max": 130}],
            },
            {
                "name": "sleep_analysis",
                "units": "min",
                "data": [
                    {
                        "date": "2026-06-02",
                        "asleep": 405,
                        "inBed": 452,
                        "sleepStart": "2026-06-01 23:10:00 +0000",
                        "sleepEnd": "2026-06-02 06:22:00 +0000",
                    }
                ],
            },
        ],
        "workouts": [
            {
                "id": "hae-workout-abc123",
                "name": "Running",
                "start": "2026-06-02 06:30:00 +0000",
                "end": "2026-06-02 07:00:00 +0000",
                "duration": 1800,
                "activeEnergyBurned": {"qty": 260, "units": "kcal"},
                "distance": {"qty": 5.1, "units": "km"},
            }
        ],
    }
}


def _mint(user_id: int) -> dict:
    raw, _id = make_ingest_token(scope="ingest", user_id=user_id)
    return ingest_headers(raw)


def test_path_a_ingest_accepts_and_upserts(client):
    headers = _mint(make_user())
    res = client.post("/api/ingest/health", json=PATH_A_PAYLOAD, headers=headers)
    assert res.status_code == 200
    body = res.json()
    # 6 metric points + 1 workout = 7 accepted; sleep_analysis fans out to
    # TWO rows (sleep_asleep only here, since Path A sent a flat qty with no
    # inBed) -- but qty-only sleep only ever produces 1 row, so accepted==7.
    assert body["accepted"] == 7
    assert body["upserted"] == 7
    assert "body_fat_percentage" in body["unknown_metrics"]


def test_path_a_repost_is_idempotent(client):
    from app.db import SessionLocal
    from app.models import HealthSample, Workout

    headers = _mint(make_user())
    client.post("/api/ingest/health", json=PATH_A_PAYLOAD, headers=headers)
    with SessionLocal() as db:
        samples_before = db.query(HealthSample).count()
        workouts_before = db.query(Workout).count()

    res = client.post("/api/ingest/health", json=PATH_A_PAYLOAD, headers=headers)
    assert res.status_code == 200
    assert res.json()["upserted"] == 0  # nothing changed -> zero new/changed rows

    with SessionLocal() as db:
        assert db.query(HealthSample).count() == samples_before
        assert db.query(Workout).count() == workouts_before


def test_path_b_hae_ingest_fans_out_sleep_and_maps_avg_heart_rate(client):
    headers = _mint(make_user())
    res = client.post("/api/ingest/health", json=PATH_B_PAYLOAD, headers=headers)
    assert res.status_code == 200
    body = res.json()
    # step_count(1) + heart_rate(1, via avg) + sleep_asleep+sleep_inbed(2) + workout(1) = 5
    assert body["accepted"] == 5
    assert body["upserted"] == 5
    assert body["unknown_metrics"] == []

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import HealthSample, Workout

    with SessionLocal() as db:
        sleep_rows = db.scalars(select(HealthSample).where(HealthSample.metric.in_(["sleep_asleep", "sleep_inbed"]))).all()
        assert {r.metric for r in sleep_rows} == {"sleep_asleep", "sleep_inbed"}
        asleep = next(r for r in sleep_rows if r.metric == "sleep_asleep")
        assert asleep.value == 405
        in_bed = next(r for r in sleep_rows if r.metric == "sleep_inbed")
        assert in_bed.value == 452

        hr = db.scalar(select(HealthSample).where(HealthSample.metric == "heart_rate"))
        assert hr.value == 71  # avg, since HAE's aggregated shape has no 'qty'

        workout = db.scalar(select(Workout).where(Workout.provider_uid == "hae-workout-abc123"))
        assert workout.wtype == "run"
        assert workout.duration_s == 1800
        assert workout.kcal == 260
        assert workout.distance_m == 5100  # km -> m conversion
        assert workout.source == "Running"


def test_path_b_repost_is_idempotent(client):
    from app.db import SessionLocal
    from app.models import HealthSample, Workout

    headers = _mint(make_user())
    client.post("/api/ingest/health", json=PATH_B_PAYLOAD, headers=headers)
    with SessionLocal() as db:
        samples_before = db.query(HealthSample).count()
        workouts_before = db.query(Workout).count()

    res = client.post("/api/ingest/health", json=PATH_B_PAYLOAD, headers=headers)
    assert res.json()["upserted"] == 0
    with SessionLocal() as db:
        assert db.query(HealthSample).count() == samples_before
        assert db.query(Workout).count() == workouts_before


def test_workout_repost_without_stable_id_is_idempotent_via_derived_uid(client):
    """Path A workouts have no 'id' -- the derived provider_uid (wtype +
    ts_start) must make repeated identical POSTs a no-op (PHASE-2 build item 3)."""
    from app.db import SessionLocal
    from app.models import Workout

    headers = _mint(make_user())
    payload = {"metrics": [], "workouts": [PATH_A_PAYLOAD["workouts"][0]]}
    client.post("/api/ingest/health", json=payload, headers=headers)
    client.post("/api/ingest/health", json=payload, headers=headers)

    with SessionLocal() as db:
        assert db.query(Workout).count() == 1


def test_health_ingest_writes_sync_run(client):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import SyncRun

    headers = _mint(make_user())
    client.post("/api/ingest/health", json=PATH_A_PAYLOAD, headers=headers)

    with SessionLocal() as db:
        run = db.scalar(select(SyncRun).where(SyncRun.source == "ingest:health"))
        assert run is not None
        assert run.status == "ok"
        assert run.items == 7


def test_health_ingest_requires_token_with_owning_user(client):
    raw, _id = make_ingest_token(scope="ingest", user_id=None)
    res = client.post("/api/ingest/health", json={"metrics": []}, headers=ingest_headers(raw))
    assert res.status_code == 400
    assert res.json()["code"] == "token_unowned"
