"""app/auth.py's ingest_token_auth -- scope check, revocation, last_seen_at
stamping, and the "two disjoint doors" rule (docs/AUTH.md #3,
docs/phases/PHASE-2-ingestion.md acceptance list)."""
from __future__ import annotations

from tests.conftest import auth_headers, ingest_headers, make_ingest_token, make_user


def test_ingest_scope_token_can_post_to_ingest_health(client):
    raw, _id = make_ingest_token(scope="ingest", user_id=make_user())
    res = client.post("/api/ingest/health", json={"metrics": []}, headers=ingest_headers(raw))
    assert res.status_code == 200


def test_notify_scope_token_403s_on_ingest_routes(client):
    raw, _id = make_ingest_token(scope="notify", user_id=make_user())
    res = client.post("/api/ingest/health", json={"metrics": []}, headers=ingest_headers(raw))
    assert res.status_code == 403
    assert res.json()["code"] == "forbidden"


def test_combined_scope_token_satisfies_ingest(client):
    raw, _id = make_ingest_token(scope="ingest+notify", user_id=make_user())
    res = client.post("/api/ingest/health", json={"metrics": []}, headers=ingest_headers(raw))
    assert res.status_code == 200


def test_revoked_token_401s(client):
    raw, _id = make_ingest_token(scope="ingest", user_id=make_user(), revoked=True)
    res = client.post("/api/ingest/health", json={"metrics": []}, headers=ingest_headers(raw))
    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"


def test_unknown_token_401s(client):
    res = client.post(
        "/api/ingest/health", json={"metrics": []}, headers=ingest_headers("not-a-real-token")
    )
    assert res.status_code == 401


def test_missing_auth_header_401s(client):
    res = client.post("/api/ingest/health", json={"metrics": []})
    assert res.status_code == 401


def test_last_seen_at_stamped_on_use(client):
    user_id = make_user()
    raw, token_id = make_ingest_token(scope="ingest", user_id=user_id)

    from app.db import SessionLocal
    from app.models import IngestToken

    with SessionLocal() as db:
        before = db.get(IngestToken, token_id)
        assert before.last_seen_at is None

    client.post("/api/ingest/health", json={"metrics": []}, headers=ingest_headers(raw))

    with SessionLocal() as db:
        after = db.get(IngestToken, token_id)
        assert after.last_seen_at is not None


def test_jwt_does_not_work_on_ingest_routes(client):
    """AUTH.md #3: 'JWTs never grant ingest routes' -- a valid user JWT
    presented as the bearer token on an ingest-token route must 401, not
    silently succeed."""
    user_id = make_user()
    jwt_headers = auth_headers(user_id)
    res = client.post("/api/ingest/health", json={"metrics": []}, headers=jwt_headers)
    assert res.status_code == 401


def test_ingest_token_does_not_work_on_jwt_routes(client):
    """AUTH.md #3: 'ingest tokens never grant any JWT-protected route' -- a
    raw ingest token presented as the bearer token on a JWT route must 401."""
    raw, _id = make_ingest_token(scope="ingest", user_id=make_user())
    res = client.get("/api/auth/me", headers=ingest_headers(raw))
    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"


def test_status_shows_ingest_token_last_seen(authed):
    client, user_id, jwt_headers = authed
    raw, _id = make_ingest_token(name="health-mack-iphone", scope="ingest", user_id=user_id)
    client.post("/api/ingest/health", json={"metrics": []}, headers=ingest_headers(raw))

    res = client.get("/api/status", headers=jwt_headers)
    assert res.status_code == 200
    tokens = res.json()["ingest_tokens"]
    mine = next(t for t in tokens if t["name"] == "health-mack-iphone")
    assert mine["last_seen_at"] is not None
    assert mine["revoked"] is False
    assert mine["scope"] == "ingest"
