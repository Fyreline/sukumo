"""GET/PATCH /api/settings — quiet hours, daily cap, per-rule enable/disable
(docs/COACH.md §2, docs/phases/PHASE-6-coach.md build item 6). Primary-only."""
from __future__ import annotations

from tests.conftest import auth_headers, make_user


def _primary():
    uid = make_user(email="mack@example.com", role="primary")
    return uid, auth_headers(uid)


def test_settings_requires_primary(client):
    partner = make_user(role="partner")
    res = client.get("/api/settings", headers=auth_headers(partner))
    assert res.status_code == 403


def test_get_settings_defaults(client):
    _uid, headers = _primary()
    res = client.get("/api/settings", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["daily_cap"] == 5
    assert "-" in body["quiet_hours"]
    keys = {r["key"] for r in body["rules"]}
    assert "reading" in keys and "gym-day" in keys
    assert all(r["enabled"] for r in body["rules"])  # nothing disabled by default


def test_patch_quiet_hours_and_cap(client):
    _uid, headers = _primary()
    res = client.patch("/api/settings", json={"quiet_hours": "23:00-06:30", "daily_cap": 3}, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["quiet_hours"] == "23:00-06:30"
    assert body["daily_cap"] == 3


def test_patch_invalid_quiet_hours_422(client):
    _uid, headers = _primary()
    res = client.patch("/api/settings", json={"quiet_hours": "not-a-window"}, headers=headers)
    assert res.status_code == 422


def test_patch_disable_a_rule(client):
    _uid, headers = _primary()
    res = client.patch("/api/settings", json={"rules": {"low-movement": False}}, headers=headers)
    assert res.status_code == 200
    disabled = {r["key"] for r in res.json()["rules"] if not r["enabled"]}
    assert disabled == {"low-movement"}

    # re-enable
    res = client.patch("/api/settings", json={"rules": {"low-movement": True}}, headers=headers)
    assert all(r["enabled"] for r in res.json()["rules"])


def test_patch_unknown_rule_422(client):
    _uid, headers = _primary()
    res = client.patch("/api/settings", json={"rules": {"not-a-rule": False}}, headers=headers)
    assert res.status_code == 422
