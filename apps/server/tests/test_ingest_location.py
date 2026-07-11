"""POST /api/ingest/location -- the Overland door (docs/API.md #3b):
GeoJSON batches -> location_points, accuracy gate, idempotent re-delivery,
and the literal {"result": "ok"} body Overland requires on 200.

All coordinates in this file are SYNTHETIC (invented city-centre-ish values)
-- no real household location ever enters the repo (ARCHITECTURE #5.5).
"""
from __future__ import annotations

from sqlalchemy import select

from tests.conftest import ingest_headers, make_ingest_token, make_user

# Invented test-city anchor -- looks plausibly urban-Scotland, is nobody's home.
LAT = 55.8600
LON = -4.2500


def _mint(user_id: int | None, scope: str = "ingest") -> dict:
    raw, _id = make_ingest_token(scope=scope, user_id=user_id)
    return ingest_headers(raw)


def _feature(ts: str, lat: float, lon: float, accuracy: float | None = 10.0, speed: float = 1.2) -> dict:
    props: dict = {
        "timestamp": ts,
        "speed": speed,
        "motion": ["walking"],
        "battery_level": 0.83,
        "battery_state": "unplugged",
        "wifi": "",
    }
    if accuracy is not None:
        props["horizontal_accuracy"] = accuracy
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def _batch(*features: dict) -> dict:
    return {"locations": list(features)}


def _points(user_id: int) -> list:
    from app.db import SessionLocal
    from app.models import LocationPoint

    with SessionLocal() as db:
        return db.scalars(
            select(LocationPoint).where(LocationPoint.user_id == user_id).order_by(LocationPoint.ts)
        ).all()


def _latest_sync_run() -> object:
    from app.db import SessionLocal
    from app.models import SyncRun

    with SessionLocal() as db:
        return db.scalars(
            select(SyncRun).where(SyncRun.source == "ingest:location").order_by(SyncRun.id.desc())
        ).first()


def test_batch_ingests_and_returns_the_literal_ok_shape(client):
    user_id = make_user()
    res = client.post(
        "/api/ingest/location",
        json=_batch(
            _feature("2026-07-05T09:00:00Z", LAT, LON),
            _feature("2026-07-05T09:05:00Z", LAT + 0.002, LON),
            _feature("2026-07-05T09:10:00Z", LAT + 0.004, LON + 0.001),
        ),
        headers=_mint(user_id),
    )
    assert res.status_code == 200
    # EXACTLY {"result": "ok"} -- Overland retains + retries on anything else.
    assert res.json() == {"result": "ok"}

    pts = _points(user_id)
    assert len(pts) == 3
    assert pts[0].ts == "2026-07-05 09:00:00"
    assert pts[0].lat == LAT and pts[0].lon == LON
    assert pts[0].accuracy_m == 10.0
    assert pts[0].speed_ms == 1.2
    assert pts[0].source == "overland"

    run = _latest_sync_run()
    assert run is not None and run.status == "ok" and run.items == 3 and run.error is None


def test_accuracy_gate_drops_bad_fixes_but_still_acks(client):
    user_id = make_user()
    res = client.post(
        "/api/ingest/location",
        json=_batch(
            _feature("2026-07-05T09:00:00Z", LAT, LON, accuracy=10.0),
            _feature("2026-07-05T09:05:00Z", LAT, LON, accuracy=165.0),  # > 100 m: mush
            _feature("2026-07-05T09:10:00Z", LAT, LON, accuracy=-1.0),  # invalid fix
            _feature("2026-07-05T09:15:00Z", LAT, LON, accuracy=None),  # missing: kept
        ),
        headers=_mint(user_id),
    )
    assert res.status_code == 200
    assert res.json() == {"result": "ok"}
    assert len(_points(user_id)) == 2
    run = _latest_sync_run()
    assert run.items == 2
    assert run.error == "dropped=2"


def test_redelivery_is_idempotent(client):
    user_id = make_user()
    headers = _mint(user_id)
    batch = _batch(
        _feature("2026-07-05T09:00:00Z", LAT, LON),
        _feature("2026-07-05T09:05:00Z", LAT + 0.001, LON),
    )
    first = client.post("/api/ingest/location", json=batch, headers=headers)
    second = client.post("/api/ingest/location", json=batch, headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.json() == {"result": "ok"}
    assert len(_points(user_id)) == 2  # UNIQUE(user_id, ts, source) upsert
    assert _latest_sync_run().items == 0  # nothing new the second time


def test_negative_speed_is_stored_as_null(client):
    user_id = make_user()
    client.post(
        "/api/ingest/location",
        json=_batch(_feature("2026-07-05T09:00:00Z", LAT, LON, speed=-1.0)),
        headers=_mint(user_id),
    )
    (pt,) = _points(user_id)
    assert pt.speed_ms is None  # CoreLocation's "unknown" sentinel


def test_malformed_features_drop_without_wedging_the_batch(client):
    user_id = make_user()
    res = client.post(
        "/api/ingest/location",
        json=_batch(
            "not-a-feature",
            {"type": "Feature", "geometry": {"type": "LineString"}, "properties": {}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LON, 95.0]}, "properties": {"timestamp": "2026-07-05T09:00:00Z"}},  # lat out of range
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LON, LAT]}, "properties": {"timestamp": "yesterday-ish"}},  # unparseable ts
            _feature("2026-07-05T09:00:00Z", LAT, LON),
        ),
        headers=_mint(user_id),
    )
    # A poison point must never make Overland retry forever (API.md #3b).
    assert res.status_code == 200
    assert res.json() == {"result": "ok"}
    assert len(_points(user_id)) == 1
    assert _latest_sync_run().error == "dropped=4"


def test_payload_without_locations_list_is_a_400(client):
    res = client.post("/api/ingest/location", json={"nope": []}, headers=_mint(make_user()))
    assert res.status_code == 400
    run = _latest_sync_run()
    assert run.status == "error" and "locations" in run.error


def test_auth_header_required_and_scope_checked(client):
    user_id = make_user()
    batch = _batch(_feature("2026-07-05T09:00:00Z", LAT, LON))
    assert client.post("/api/ingest/location", json=batch).status_code == 401
    # notify-only scope must not open the ingest door (AUTH.md #3).
    assert (
        client.post("/api/ingest/location", json=batch, headers=_mint(user_id, scope="notify")).status_code
        == 403
    )
    # No ?token= query fallback exists -- by decision (API.md #3b: query
    # strings land in uvicorn's access log).
    raw, _ = make_ingest_token(scope="ingest", user_id=user_id)
    assert client.post(f"/api/ingest/location?token={raw}", json=batch).status_code == 401


def test_unowned_token_is_a_400(client):
    make_user()
    res = client.post(
        "/api/ingest/location",
        json=_batch(_feature("2026-07-05T09:00:00Z", LAT, LON)),
        headers=_mint(None),  # a household token with no user binding
    )
    assert res.status_code == 400
    assert res.json()["code"] == "token_unowned"
