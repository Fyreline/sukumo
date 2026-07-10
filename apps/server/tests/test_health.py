"""routers/health.py — unauthenticated liveness only."""
from __future__ import annotations


def test_health_ok(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_health_does_not_require_auth(client):
    res = client.get("/api/health")
    assert res.status_code == 200
