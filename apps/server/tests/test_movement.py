"""app/memory/movement.py -- haversine/Douglas-Peucker units, the daily
movement aggregate (distance, away-from-home minutes, simplified trace),
90-day retention, and the assembly slot line + stats keys + determinism.

All coordinates are SYNTHETIC (the same invented anchor as
test_ingest_location.py) -- no real household location in the repo.
"""
from __future__ import annotations

import json

from app.memory import movement

LAT = 55.8600
LON = -4.2500
HOME = (LAT, LON)

# ~111,195 m per degree of latitude (mean Earth radius) -- the yardstick the
# unit tests below measure against.
M_PER_DEG_LAT = 111_195.0


def _insert_points(user_id: int, rows: list[tuple[str, float, float]]) -> None:
    from app.db import SessionLocal
    from app.models import LocationPoint

    with SessionLocal() as db:
        for ts, lat, lon in rows:
            db.add(LocationPoint(user_id=user_id, ts=ts, lat=lat, lon=lon, source="overland"))
        db.commit()


# ------------------------------------------------------------------ geometry --
def test_haversine_known_distances():
    # 0.01 deg of latitude is ~1112 m anywhere on Earth.
    d = movement.haversine_m(LAT, LON, LAT + 0.01, LON)
    assert abs(d - 0.01 * M_PER_DEG_LAT) < 5
    # 0.01 deg of longitude shrinks by cos(lat) (~0.5615 at 55.86 N).
    import math

    d_lon = movement.haversine_m(LAT, LON, LAT, LON + 0.01)
    assert abs(d_lon - 0.01 * M_PER_DEG_LAT * math.cos(math.radians(LAT))) < 5
    assert movement.haversine_m(LAT, LON, LAT, LON) == 0.0


def test_douglas_peucker_collapses_collinear_points():
    line = [(LAT + i * 0.001, LON) for i in range(10)]  # due north, dead straight
    assert movement.douglas_peucker(line, 10.0) == [line[0], line[-1]]


def test_douglas_peucker_keeps_a_real_detour():
    # Out-and-back corner ~1112 m off the straight line -- far beyond 10 m.
    pts = [(LAT, LON), (LAT + 0.005, LON + 0.01), (LAT + 0.01, LON)]
    assert movement.douglas_peucker(pts, 10.0) == pts
    # ...but a huge epsilon flattens it away.
    assert movement.douglas_peucker(pts, 5_000.0) == [pts[0], pts[-1]]


def test_simplify_trace_caps_at_200_points_deterministically():
    # A jagged 1,000-point zigzag that plain 10 m epsilon can't flatten.
    pts = [(LAT + i * 0.0005, LON + (0.002 if i % 2 else -0.002)) for i in range(1000)]
    out1 = movement.simplify_trace(pts)
    out2 = movement.simplify_trace(pts)
    assert len(out1) <= movement.MAX_TRACE_POINTS
    assert out1 == out2  # same points in, same trace out (determinism law)
    assert out1[0] == pts[0] and out1[-1] == pts[-1]  # endpoints survive


# ----------------------------------------------------------------- aggregate --
def test_day_movement_distance_and_trace(client):
    from app.db import SessionLocal
    from tests.conftest import make_user

    user_id = make_user()
    # A straight 10-point walk due north, one point per 5 min: 9 legs of
    # ~111 m each (0.001 deg lat).
    rows = [(f"2026-07-05 09:{5 * i:02d}:00", LAT + i * 0.001, LON) for i in range(10)]
    _insert_points(user_id, rows)

    with SessionLocal() as db:
        out = movement.day_movement(db, "2026-07-05", home=None)
    assert out is not None
    expected = 9 * 0.001 * M_PER_DEG_LAT
    assert abs(out["distance_m"] - expected) < 10
    assert out["away_min"] is None  # home not configured
    assert 2 <= len(out["trace"]) <= movement.MAX_TRACE_POINTS
    assert out["trace"][0] == [LAT, LON]  # collinear walk simplifies, ends kept
    assert out["trace"][-1] == [round(LAT + 0.009, 5), LON]


def test_day_movement_ignores_gps_teleport_noise(client):
    from app.db import SessionLocal
    from tests.conftest import make_user

    user_id = make_user()
    _insert_points(
        user_id,
        [
            ("2026-07-05 09:00:00", LAT, LON),
            ("2026-07-05 09:00:10", LAT + 0.01, LON),  # ~1112 m in 10 s: scatter
            ("2026-07-05 09:05:00", LAT + 0.011, LON),  # ~111 m in ~5 min: real
        ],
    )
    with SessionLocal() as db:
        out = movement.day_movement(db, "2026-07-05", home=None)
    # Only the second leg counts toward distance.
    assert abs(out["distance_m"] - 0.001 * M_PER_DEG_LAT) < 10


def test_day_movement_away_minutes_with_home_configured(client):
    from app.db import SessionLocal
    from tests.conftest import make_user

    user_id = make_user()
    away = (LAT + 0.01, LON)  # ~1112 m out: beyond the 150 m home radius
    _insert_points(
        user_id,
        [
            ("2026-07-05 10:00:00", LAT, LON),  # home
            ("2026-07-05 10:10:00", *away),  # away (home->away leg not counted)
            ("2026-07-05 10:40:00", away[0] + 0.001, away[1]),  # away: +30 min
            ("2026-07-05 10:50:00", LAT, LON),  # home again
            # A second away pair separated by a 2 h data hole: never counted.
            ("2026-07-05 14:00:00", *away),
            ("2026-07-05 16:00:00", *away),
        ],
    )
    with SessionLocal() as db:
        with_home = movement.day_movement(db, "2026-07-05", home=HOME)
        without = movement.day_movement(db, "2026-07-05", home=None)
    assert with_home["away_min"] == 30
    assert without["away_min"] is None
    # Same points -> same trace, regardless of the home setting.
    assert with_home["trace"] == without["trace"]


def test_day_movement_none_when_fewer_than_two_points(client):
    from app.db import SessionLocal
    from tests.conftest import make_user

    user_id = make_user()
    _insert_points(user_id, [("2026-07-05 09:00:00", LAT, LON)])
    with SessionLocal() as db:
        assert movement.day_movement(db, "2026-07-05", home=HOME) is None
        assert movement.day_movement(db, "2026-07-06", home=HOME) is None  # empty day


# ----------------------------------------------------------------- retention --
def test_prune_deletes_only_aggregated_days_older_than_90(client):
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import JournalDay, LocationPoint
    from tests.conftest import make_user

    user_id = make_user()
    now = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)
    _insert_points(
        user_id,
        [
            ("2026-03-01 10:00:00", LAT, LON),  # old, day aggregated -> pruned
            ("2026-03-02 10:00:00", LAT, LON),  # old, day NOT aggregated -> kept
            ("2026-07-05 10:00:00", LAT, LON),  # recent -> kept
        ],
    )
    with SessionLocal() as db:
        db.add(
            JournalDay(
                local_date="2026-03-01",
                assembled_at="2026-03-02 02:30:00",
                summary_md="x",
                stats_json="{}",
                event_count=0,
            )
        )
        db.commit()
        deleted = movement.prune_location_points(db, now=now)
        assert deleted == 1
        remaining = sorted(db.scalars(select(LocationPoint.ts)).all())
        assert remaining == ["2026-03-02 10:00:00", "2026-07-05 10:00:00"]


# ------------------------------------------------------------------ assembly --
def test_assembly_gains_movement_slot_and_stats(client, monkeypatch):
    from app.db import SessionLocal
    from app.memory import assemble
    from app.models import JournalDay
    from tests.conftest import make_user

    # Hermetic home coords -- never the machine's real .env values.
    monkeypatch.setattr(assemble, "_home_coords", lambda: HOME)

    user_id = make_user()
    away = (LAT + 0.01, LON)
    _insert_points(
        user_id,
        [
            ("2026-07-05 10:00:00", LAT, LON),
            ("2026-07-05 10:10:00", *away),
            ("2026-07-05 10:40:00", away[0] + 0.001, away[1]),
            ("2026-07-05 10:50:00", LAT, LON),
        ],
    )
    with SessionLocal() as db:
        row = assemble.assemble_day(db, "2026-07-05", run_maps=False)
        assert "Out and about — " in row.summary_md
        assert "km on foot." in row.summary_md
        stats = json.loads(row.stats_json)
        assert stats["distance_m"] > 0
        assert stats["away_min"] == 30
        assert isinstance(stats["trace"], list) and len(stats["trace"]) >= 2
        assert all(len(p) == 2 for p in stats["trace"])

        # Determinism: a re-run leaves the row byte-identical.
        first = (row.summary_md, row.stats_json, row.assembled_at)
        again = assemble.assemble_day(db, "2026-07-05", run_maps=False)
        assert (again.summary_md, again.stats_json, again.assembled_at) == first

    # And a day with no points carries none of the movement keys.
    with SessionLocal() as db:
        quiet = assemble.assemble_day(db, "2026-07-06", run_maps=False)
        qstats = json.loads(quiet.stats_json)
        assert "trace" not in qstats and "distance_m" not in qstats and "away_min" not in qstats
        db.delete(db.get(JournalDay, "2026-07-06"))
        db.commit()


def test_assembly_nightly_runs_the_prune(client):
    from datetime import datetime, timezone

    from app.db import SessionLocal
    from app.memory import assemble

    now = datetime(2026, 7, 11, 2, 30, 0, tzinfo=timezone.utc)
    with SessionLocal() as db:
        result = assemble.assemble_yesterday(db, now=now)
    assert result["pruned_location_points"] == 0  # nothing to prune, but wired


# ------------------------------------------------------- privacy hard lines --
def test_journal_day_with_trace_is_primary_only(client, monkeypatch):
    from app.db import SessionLocal
    from app.memory import assemble
    from tests.conftest import auth_headers, make_user

    monkeypatch.setattr(assemble, "_home_coords", lambda: HOME)
    primary_id = make_user(email="mack@example.com", display_name="Mack", role="primary")
    partner_id = make_user(email="amy@example.com", display_name="Amy", role="partner")
    _insert_points(
        primary_id,
        [("2026-07-05 10:00:00", LAT, LON), ("2026-07-05 10:10:00", LAT + 0.01, LON)],
    )
    with SessionLocal() as db:
        assemble.assemble_day(db, "2026-07-05", run_maps=False)

    ok = client.get("/api/journal/2026-07-05", headers=auth_headers(primary_id))
    assert ok.status_code == 200
    assert ok.json()["stats"]["trace"]  # the primary sees the route

    denied = client.get("/api/journal/2026-07-05", headers=auth_headers(partner_id))
    assert denied.status_code == 403  # the partner NEVER sees location


def test_dashboard_carries_no_location_data(client, monkeypatch):
    from app.db import SessionLocal
    from app.memory import assemble
    from tests.conftest import auth_headers, make_user

    monkeypatch.setattr(assemble, "_home_coords", lambda: HOME)
    primary_id = make_user(email="mack@example.com", display_name="Mack", role="primary")
    partner_id = make_user(email="amy@example.com", display_name="Amy", role="partner")
    _insert_points(
        primary_id,
        [("2026-07-05 10:00:00", LAT, LON), ("2026-07-05 10:10:00", LAT + 0.01, LON)],
    )
    with SessionLocal() as db:
        assemble.assemble_day(db, "2026-07-05", run_maps=False)

    for uid in (primary_id, partner_id):
        res = client.get("/api/dashboard", headers=auth_headers(uid))
        assert res.status_code == 200
        text = res.text
        assert "trace" not in text
        assert "location" not in text
        assert str(LAT) not in text
