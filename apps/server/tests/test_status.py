"""GET /api/status -- latest sync_runs per source + snapshot ages +
ingest-token last_seen (docs/DATA_MODEL.md #7, docs/phases/PHASE-2-ingestion.md
build item 7). Ingest-token-specific coverage lives in test_ingest_tokens.py.
The `siblings` section + consecutive-failure counting
(docs/phases/PHASE-3-siblings.md build item 5) is covered below."""
from __future__ import annotations


def test_status_requires_jwt_auth(client):
    res = client.get("/api/status")
    assert res.status_code == 401


def test_status_shape_when_empty(authed):
    client, user_id, headers = authed
    res = client.get("/api/status", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "sync_runs": [],
        "snapshots": [],
        "ingest_tokens": [],
        "siblings": [
            {"app": "michi", "ok": None, "age_seconds": None, "latency_ms": None, "consecutive_failures": 0},
            {"app": "kakeibo", "ok": None, "age_seconds": None, "latency_ms": None, "consecutive_failures": 0},
            {"app": "mishka", "ok": None, "age_seconds": None, "latency_ms": None, "consecutive_failures": 0},
        ],
    }


def test_status_shows_latest_sync_run_per_source(authed):
    client, user_id, headers = authed
    from app.db import SessionLocal
    from app.models import SyncRun

    with SessionLocal() as db:
        db.add(SyncRun(source="poll:calendar", started_at="2026-06-01 00:00:00", finished_at="2026-06-01 00:00:01", status="ok", items=5))
        db.add(SyncRun(source="poll:calendar", started_at="2026-06-02 00:00:00", finished_at="2026-06-02 00:00:01", status="error", items=0, error="boom"))
        db.commit()

    res = client.get("/api/status", headers=headers)
    runs = res.json()["sync_runs"]
    assert len(runs) == 1  # only the latest per source
    assert runs[0]["status"] == "error"
    assert runs[0]["started_at"] == "2026-06-02 00:00:00"


def _add_snapshot(app: str, fetched_at: str, ok: bool, latency_ms: int | None = 42, error: str | None = None):
    from app.db import SessionLocal
    from app.models import SiblingSnapshot

    with SessionLocal() as db:
        db.add(
            SiblingSnapshot(
                app=app, fetched_at=fetched_at, ok=1 if ok else 0, latency_ms=latency_ms, payload_json=None, error=error
            )
        )
        db.commit()


def test_status_siblings_shows_latest_ok_snapshot(authed):
    client, user_id, headers = authed
    _add_snapshot("michi", "2026-06-01 00:00:00", ok=True, latency_ms=120)

    res = client.get("/api/status", headers=headers)
    siblings = {s["app"]: s for s in res.json()["siblings"]}
    assert siblings["michi"]["ok"] is True
    assert siblings["michi"]["latency_ms"] == 120
    assert siblings["michi"]["age_seconds"] is not None
    assert siblings["michi"]["age_seconds"] >= 0
    assert siblings["michi"]["consecutive_failures"] == 0
    # untouched apps stay at the empty shape
    assert siblings["kakeibo"]["ok"] is None
    assert siblings["mishka"]["ok"] is None


def test_status_siblings_counts_consecutive_failures_from_most_recent(authed):
    """docs/phases/PHASE-3-siblings.md build item 5: stopping Michi ->
    snapshot error rows accumulate -> status shows it red with a growing
    consecutive_failures count; one earlier ok row must not reset it."""
    client, user_id, headers = authed
    _add_snapshot("michi", "2026-06-01 00:00:00", ok=True)
    _add_snapshot("michi", "2026-06-01 00:15:00", ok=False, error="connection refused")
    _add_snapshot("michi", "2026-06-01 00:30:00", ok=False, error="connection refused")
    _add_snapshot("michi", "2026-06-01 00:45:00", ok=False, error="connection refused")

    res = client.get("/api/status", headers=headers)
    michi = next(s for s in res.json()["siblings"] if s["app"] == "michi")
    assert michi["ok"] is False
    assert michi["consecutive_failures"] == 3


def test_status_siblings_consecutive_failures_resets_after_recovery(authed):
    client, user_id, headers = authed
    _add_snapshot("michi", "2026-06-01 00:00:00", ok=False, error="boom")
    _add_snapshot("michi", "2026-06-01 00:15:00", ok=False, error="boom")
    _add_snapshot("michi", "2026-06-01 00:30:00", ok=True)  # restart -> green again

    res = client.get("/api/status", headers=headers)
    michi = next(s for s in res.json()["siblings"] if s["app"] == "michi")
    assert michi["ok"] is True
    assert michi["consecutive_failures"] == 0


def test_status_siblings_excludes_weather_and_calendar():
    """Ambient sources (weather/calendar) are NOT siblings -- they have no
    'is this household app up' question to answer, so they never appear in
    the siblings section even though they share the same snapshots table."""
    from app.routers.status import SIBLING_APPS

    assert set(SIBLING_APPS) == {"michi", "kakeibo", "mishka"}
    assert "weather" not in SIBLING_APPS
    assert "calendar" not in SIBLING_APPS
