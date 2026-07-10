"""GET /api/status -- latest sync_runs per source + snapshot ages +
ingest-token last_seen (docs/DATA_MODEL.md #7, docs/phases/PHASE-2-ingestion.md
build item 7). Ingest-token-specific coverage lives in test_ingest_tokens.py."""
from __future__ import annotations


def test_status_requires_jwt_auth(client):
    res = client.get("/api/status")
    assert res.status_code == 401


def test_status_shape_when_empty(authed):
    client, user_id, headers = authed
    res = client.get("/api/status", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body == {"sync_runs": [], "snapshots": [], "ingest_tokens": []}


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
