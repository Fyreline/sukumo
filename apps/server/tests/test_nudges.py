"""Nudge lifecycle -- docs/API.md §1, docs/AUTH.md §4, docs/COACH.md §2,
docs/phases/PHASE-5-notify.md acceptance: "action button tap -> nudge
actioned, second tap -> idempotent no-op; expired token -> 410."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import notify
from app.config import get_settings
from app.db import SessionLocal
from app.models import Nudge
from tests.conftest import auth_headers, make_user


def _make_nudge(user_id: int, **overrides) -> int:
    defaults = dict(
        rule_key="bus:test",
        user_id=user_id,
        dedupe_key=f"dk-{overrides.get('id_hint', 'x')}-{overrides.get('dedupe_suffix', '1')}",
        scheduled_for="2026-07-10 12:00:00",
        channel="ntfy",
        title="Gym gap: 4 days",
        body="a walk on the way home?",
        status="sent",
        context_json="{}",
    )
    defaults.update({k: v for k, v in overrides.items() if k not in ("id_hint", "dedupe_suffix")})
    with SessionLocal() as db:
        nudge = Nudge(**defaults)
        db.add(nudge)
        db.commit()
        return nudge.id


def _primary(email: str = "mack@example.com") -> tuple[int, dict]:
    user_id = make_user(email=email, role="primary")
    return user_id, auth_headers(user_id)


# ------------------------------------------------------------------ listing --
def test_list_nudges_requires_primary_role(client):
    partner_id = make_user(role="partner")
    _make_nudge(partner_id)
    res = client.get("/api/nudges", headers=auth_headers(partner_id))
    assert res.status_code == 403


def test_list_nudges_filters_by_status(client):
    user_id, headers = _primary()
    _make_nudge(user_id, dedupe_suffix="a", status="pending")
    _make_nudge(user_id, dedupe_suffix="b", status="sent")
    _make_nudge(user_id, dedupe_suffix="c", status="dismissed")

    res = client.get("/api/nudges?status=pending,sent", headers=headers)
    assert res.status_code == 200
    statuses = {n["status"] for n in res.json()}
    assert statuses == {"pending", "sent"}


def test_list_nudges_unknown_status_400s(client):
    user_id, headers = _primary()
    res = client.get("/api/nudges?status=not-a-status", headers=headers)
    assert res.status_code == 400


# ------------------------------------------------------------- snooze/dismiss
def test_snooze_3h(client):
    user_id, headers = _primary()
    nudge_id = _make_nudge(user_id)
    res = client.post(f"/api/nudges/{nudge_id}/snooze", json={"option": "3h"}, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "snoozed"
    assert body["snoozed_until"] is not None


def test_snooze_invalid_option_400s(client):
    user_id, headers = _primary()
    nudge_id = _make_nudge(user_id)
    res = client.post(f"/api/nudges/{nudge_id}/snooze", json={"option": "next-month"}, headers=headers)
    assert res.status_code == 400


def test_dismiss(client):
    user_id, headers = _primary()
    nudge_id = _make_nudge(user_id)
    res = client.post(f"/api/nudges/{nudge_id}/dismiss", headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "dismissed"


def test_cannot_touch_someone_elses_nudge(client):
    owner_id = make_user(email="owner@example.com", role="primary")
    _other_id, other_headers = _primary(email="other@example.com")
    nudge_id = _make_nudge(owner_id)
    res = client.post(f"/api/nudges/{nudge_id}/dismiss", headers=other_headers)
    assert res.status_code == 404


def test_action_route_marks_actioned_and_runs_registered_callback(client):
    user_id, headers = _primary()
    nudge_id = _make_nudge(user_id, rule_key="reading", dedupe_suffix="cb")
    calls: list[int] = []
    notify.register_action_callback("reading", lambda session, nudge: calls.append(nudge.id))
    try:
        res = client.post(f"/api/nudges/{nudge_id}/action", headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "actioned"
        assert calls == [nudge_id]
    finally:
        notify._action_callbacks.pop("reading", None)


# --------------------------------------------------------- act/{token} link --
def test_act_token_marks_nudge_actioned_then_second_hit_is_idempotent(client):
    user_id, _headers = _primary()
    nudge_id = _make_nudge(user_id, dedupe_suffix="act")
    settings = get_settings()
    token = notify.issue_action_token(nudge_id, settings)

    first = client.get(f"/api/nudges/act/{token}")
    assert first.status_code == 200
    assert "Done" in first.text

    with SessionLocal() as db:
        nudge = db.get(Nudge, nudge_id)
        assert nudge.status == "actioned"

    second = client.get(f"/api/nudges/act/{token}")
    assert second.status_code == 200
    assert "Already sorted" in second.text

    with SessionLocal() as db:
        nudge = db.get(Nudge, nudge_id)
        assert nudge.status == "actioned"  # unchanged by the second hit


def test_act_token_runs_registered_callback_on_first_hit_only(client):
    user_id, _headers = _primary()
    nudge_id = _make_nudge(user_id, rule_key="reading", dedupe_suffix="act-cb")
    settings = get_settings()
    token = notify.issue_action_token(nudge_id, settings)
    calls: list[int] = []
    notify.register_action_callback("reading", lambda session, nudge: calls.append(nudge.id))
    try:
        client.get(f"/api/nudges/act/{token}")
        client.get(f"/api/nudges/act/{token}")
        assert calls == [nudge_id]  # not called again on the idempotent second hit
    finally:
        notify._action_callbacks.pop("reading", None)


def test_tampered_token_401s(client):
    user_id, _headers = _primary()
    nudge_id = _make_nudge(user_id, dedupe_suffix="tamper")
    settings = get_settings()
    token = notify.issue_action_token(nudge_id, settings)
    tampered = token[:-4] + ("a" if token[-4] != "a" else "b") + token[-3:]

    res = client.get(f"/api/nudges/act/{tampered}")
    assert res.status_code == 401


def test_garbage_token_401s(client):
    res = client.get("/api/nudges/act/not-a-real-token")
    assert res.status_code == 401


def test_expired_token_returns_410(client):
    user_id, _headers = _primary()
    nudge_id = _make_nudge(user_id, dedupe_suffix="expired")
    settings = get_settings()
    # issue with an already-passed TTL by backdating via a negative ttl_hours
    token = notify.issue_action_token(nudge_id, settings, ttl_hours=-1)

    res = client.get(f"/api/nudges/act/{token}")
    assert res.status_code == 410

    with SessionLocal() as db:
        nudge = db.get(Nudge, nudge_id)
        assert nudge.status == "expired"


def test_act_on_unknown_nudge_id_returns_410(client):
    settings = get_settings()
    token = notify.issue_action_token(999999, settings)
    res = client.get(f"/api/nudges/act/{token}")
    assert res.status_code == 410


def test_act_token_signature_is_bound_to_jwt_secret():
    """A token minted with a different secret must not verify against this
    app's SUKUMO_JWT_SECRET -- proves the HMAC is doing real work."""
    settings = get_settings()
    other_settings = settings.model_copy(update={"jwt_secret": "a-different-secret-entirely"})
    token = notify.issue_action_token(1, other_settings)
    try:
        notify.verify_action_token(token, settings)
        raised = False
    except notify.ActionTokenError:
        raised = True
    assert raised
