"""POST /api/notify -- the household bus entry point (token-auth, scope
'notify') -- docs/API.md §5, docs/phases/PHASE-5-notify.md acceptance:
"curl the bus with the notify token -> ... inbox row exists; ingest-scoped
token -> 403."."""
from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Nudge, SyncRun
from tests.conftest import ingest_headers, make_ingest_token, make_user


def _notify_headers(user_id: int | None = None) -> dict[str, str]:
    raw, _id = make_ingest_token(scope="notify", user_id=user_id)
    return ingest_headers(raw)


def test_notify_scope_token_creates_inbox_nudge(client):
    user_id = make_user(email="mack@example.com", role="primary")
    headers = _notify_headers(user_id)

    res = client.post(
        "/api/notify",
        json={"title": "Sukumo bus check", "body": "wired up end to end", "source": "test-script"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["deduped"] is False
    assert "nudge_id" in body

    with SessionLocal() as db:
        nudge = db.get(Nudge, body["nudge_id"])
        assert nudge is not None
        assert nudge.rule_key == "bus:test-script"
        assert nudge.user_id == user_id
        assert nudge.channel == "ntfy"


def test_ingest_scope_token_403s_on_notify(client):
    headers = _notify_headers(make_user())
    # swap for an ingest-only token deliberately
    raw, _id = make_ingest_token(scope="ingest", user_id=make_user(email="second@example.com"))
    from tests.conftest import ingest_headers as _h

    res = client.post(
        "/api/notify",
        json={"title": "t", "body": "b", "source": "s"},
        headers=_h(raw),
    )
    assert res.status_code == 403
    assert res.json()["code"] == "forbidden"


def test_notify_falls_back_to_primary_user_when_token_unowned(client):
    primary_id = make_user(email="mack@example.com", role="primary")
    headers = _notify_headers(None)  # household-bus-style token, no user_id

    res = client.post(
        "/api/notify", json={"title": "t", "body": "b", "source": "michi-bus"}, headers=headers
    )
    assert res.status_code == 200

    with SessionLocal() as db:
        nudge = db.get(Nudge, res.json()["nudge_id"])
        assert nudge.user_id == primary_id


def test_invalid_priority_rejected(client):
    headers = _notify_headers(make_user())
    res = client.post(
        "/api/notify",
        json={"title": "t", "body": "b", "source": "s", "priority": "urgent!!"},
        headers=headers,
    )
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_payload"


def test_repeated_bus_posts_are_not_deduped_against_each_other(client):
    """Unlike a recurring coach rule, every bus POST is its own event
    (routers/notify.py's dedupe_key is uuid-suffixed)."""
    headers = _notify_headers(make_user(email="mack@example.com", role="primary"))
    payload = {"title": "same title", "body": "same body", "source": "test-script"}
    first = client.post("/api/notify", json=payload, headers=headers)
    second = client.post("/api/notify", json=payload, headers=headers)
    assert first.json()["nudge_id"] != second.json()["nudge_id"]

    with SessionLocal() as db:
        rows = db.scalars(select(Nudge).where(Nudge.rule_key == "bus:test-script")).all()
        assert len(rows) == 2
