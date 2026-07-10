"""Journal read API — JWT, primary-only 403, mood tap, digests.
docs/API.md §1, docs/phases/PHASE-7-memory.md item 6. SYNTHETIC data only."""
from __future__ import annotations

import json

from app.db import SessionLocal
from app.models import Digest, JournalDay, MemoryEvent

from .conftest import auth_headers, make_user


def _seed_day(local_date="2026-07-08", *, mood=None):
    with SessionLocal() as db:
        db.add(
            JournalDay(
                local_date=local_date,
                assembled_at=f"{local_date} 02:30:00",
                summary_md=f"## {local_date}\n\nA synthetic day.\n",
                stats_json=json.dumps({"steps": 8123, "films": 1}),
                event_count=1,
                mood=mood,
            )
        )
        db.add(
            MemoryEvent(
                user_id=None,
                ts=f"{local_date} 21:00:00",
                kind="film",
                title="A Synthetic Film",
                detail_json=json.dumps({"rating": 4}),
                source="mishka",
                provider_uid=f"f1:{local_date}",
            )
        )
        db.commit()


def _primary_headers():
    return auth_headers(make_user(email="mack@example.com", role="primary"))


def test_journal_requires_jwt(client):
    assert client.get("/api/journal/2026-07-08").status_code == 401
    assert client.get("/api/journal?from=2026-07-01&to=2026-07-08").status_code == 401


def test_partner_gets_403(client):
    partner = auth_headers(make_user(email="amy@example.com", role="partner"))
    _seed_day()
    assert client.get("/api/journal/2026-07-08", headers=partner).status_code == 403
    assert client.get("/api/digests", headers=partner).status_code == 403


def test_get_day_returns_events_and_anniversary(client):
    headers = _primary_headers()
    _seed_day()
    res = client.get("/api/journal/2026-07-08", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["local_date"] == "2026-07-08"
    assert body["stats"]["steps"] == 8123
    assert body["events"][0]["kind"] == "film"
    assert body["anniversary"] == []


def test_get_missing_day_404(client):
    headers = _primary_headers()
    assert client.get("/api/journal/2026-07-08", headers=headers).status_code == 404


def test_bad_date_422(client):
    headers = _primary_headers()
    assert client.get("/api/journal/2026-7-8", headers=headers).status_code == 422
    assert client.get("/api/journal/2026-13-40", headers=headers).status_code == 422


def test_list_range(client):
    headers = _primary_headers()
    _seed_day("2026-07-06")
    _seed_day("2026-07-08")
    res = client.get("/api/journal?from=2026-07-01&to=2026-07-08", headers=headers)
    assert res.status_code == 200
    days = res.json()["days"]
    assert [d["local_date"] for d in days] == ["2026-07-08", "2026-07-06"]  # desc


def test_range_from_after_to_422(client):
    headers = _primary_headers()
    assert client.get("/api/journal?from=2026-07-09&to=2026-07-01", headers=headers).status_code == 422


def test_patch_mood(client):
    headers = _primary_headers()
    _seed_day()
    res = client.patch("/api/journal/2026-07-08", json={"mood": "good"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["mood"] == "good"
    # clearable
    assert client.patch("/api/journal/2026-07-08", json={"mood": None}, headers=headers).json()["mood"] is None
    # invalid mood rejected
    assert client.patch("/api/journal/2026-07-08", json={"mood": "ecstatic"}, headers=headers).status_code == 422


def test_patch_mood_does_not_touch_summary(client):
    headers = _primary_headers()
    _seed_day()
    before = client.get("/api/journal/2026-07-08", headers=headers).json()["summary_md"]
    client.patch("/api/journal/2026-07-08", json={"mood": "low"}, headers=headers)
    after = client.get("/api/journal/2026-07-08", headers=headers).json()["summary_md"]
    assert before == after


def test_patch_missing_day_404(client):
    headers = _primary_headers()
    assert client.patch("/api/journal/2026-07-08", json={"mood": "good"}, headers=headers).status_code == 404


def test_digests_endpoint(client):
    headers = _primary_headers()
    with SessionLocal() as db:
        db.add(Digest(period_start="2026-07-05", period_end="2026-07-11", kind="weekly", content_md="# Week\n", sent_at=None))
        db.add(Digest(period_start="2026-09-10", period_end="2026-09-12", kind="trip", content_md="# Trip\n", sent_at=None))
        db.commit()
    all_res = client.get("/api/digests", headers=headers)
    assert all_res.status_code == 200
    assert len(all_res.json()["digests"]) == 2
    weekly = client.get("/api/digests?kind=weekly", headers=headers).json()["digests"]
    assert len(weekly) == 1 and weekly[0]["kind"] == "weekly"
    assert client.get("/api/digests?kind=nonsense", headers=headers).status_code == 422
