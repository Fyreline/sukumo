"""/api/books — the reading habit's companion (docs/DATA_MODEL.md §2,
HANDOFF Q1, docs/phases/PHASE-4-dashboard.md build item 2). Finishing a
book writes the memory_events milestone, idempotently."""
from __future__ import annotations


def test_books_require_jwt(client):
    assert client.get("/api/books").status_code == 401


def test_create_and_list_books(authed):
    client, user_id, headers = authed
    res = client.post("/api/books", json={"title": "A Synthetic Book", "author": "N. O. Body"}, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "reading"
    assert body["started_on"] is not None
    assert body["finished_on"] is None

    listed = client.get("/api/books", headers=headers).json()
    assert [b["title"] for b in listed] == ["A Synthetic Book"]


def test_create_book_requires_title(authed):
    client, user_id, headers = authed
    assert client.post("/api/books", json={"title": "  "}, headers=headers).status_code == 422


def test_finishing_a_book_stamps_date_and_writes_milestone_once(authed):
    from app.db import SessionLocal
    from app.models import MemoryEvent
    from sqlalchemy import select

    client, user_id, headers = authed
    book = client.post("/api/books", json={"title": "Done Soon"}, headers=headers).json()

    finished = client.patch(f"/api/books/{book['id']}", json={"status": "finished"}, headers=headers).json()
    assert finished["status"] == "finished"
    assert finished["finished_on"] is not None

    # re-patching to finished again must not duplicate the milestone
    client.patch(f"/api/books/{book['id']}", json={"status": "reading"}, headers=headers)
    client.patch(f"/api/books/{book['id']}", json={"status": "finished"}, headers=headers)

    with SessionLocal() as db:
        milestones = db.scalars(
            select(MemoryEvent).where(MemoryEvent.source == "books", MemoryEvent.kind == "milestone")
        ).all()
        assert len(milestones) == 1
        assert milestones[0].provider_uid == f"book:{book['id']}:finished"
        assert "Done Soon" in (milestones[0].title or "")


def test_abandoning_a_book_writes_no_milestone(authed):
    from app.db import SessionLocal
    from app.models import MemoryEvent
    from sqlalchemy import select

    client, user_id, headers = authed
    book = client.post("/api/books", json={"title": "Not For Me"}, headers=headers).json()
    res = client.patch(f"/api/books/{book['id']}", json={"status": "abandoned"}, headers=headers)
    assert res.status_code == 200

    with SessionLocal() as db:
        assert db.scalars(select(MemoryEvent).where(MemoryEvent.source == "books")).all() == []


def test_book_status_validation(authed):
    client, user_id, headers = authed
    book = client.post("/api/books", json={"title": "Valid"}, headers=headers).json()
    assert client.patch(f"/api/books/{book['id']}", json={"status": "burnt"}, headers=headers).status_code == 422
