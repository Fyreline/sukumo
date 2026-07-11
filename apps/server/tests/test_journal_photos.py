"""Journal photo strip endpoints — GET /api/journal/{date}/photos and
GET /api/photos/{uuid}/thumb (docs/MEMORY.md §5, docs/API.md §1). The real
Photos library is NEVER touched by the suite (the household discipline from
test_memory_photos.py): the configured paths are monkeypatched fakes.
SYNTHETIC only."""
from __future__ import annotations

from app.memory import photos as photos_mod
from app.routers import journal as journal_router

from .conftest import auth_headers, make_user

FAKE_UUID = "1EB2B765-0765-43BA-A90C-0D0580E6172C"


def _primary_headers():
    return auth_headers(make_user(email="mack@example.com", role="primary"))


def _configure_fake_library(monkeypatch):
    monkeypatch.setattr(photos_mod, "resolve_library_path", lambda session: "/fake/lib")
    monkeypatch.setattr(photos_mod, "library_exists", lambda path=None: True)


# ------------------------------------------------------------- the doors ----
def test_photos_require_jwt(client):
    assert client.get("/api/journal/2026-07-08/photos").status_code == 401
    assert client.get(f"/api/photos/{FAKE_UUID}/thumb").status_code == 401


def test_partner_gets_403(client):
    partner = auth_headers(make_user(email="amy@example.com", role="partner"))
    assert client.get("/api/journal/2026-07-08/photos", headers=partner).status_code == 403
    assert client.get(f"/api/photos/{FAKE_UUID}/thumb", headers=partner).status_code == 403


def test_bad_date_422(client):
    headers = _primary_headers()
    assert client.get("/api/journal/2026-7-8/photos", headers=headers).status_code == 422


# --------------------------------------------------------- graceful degrade --
def test_photos_unconfigured_is_honest_empty(client):
    """No library wired up -> empty groups + configured false, never an error
    (the HANDOFF Q4 degrade, same as the mapper)."""
    headers = _primary_headers()
    res = client.get("/api/journal/2026-07-08/photos", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"date": "2026-07-08", "groups": [], "configured": False}


def test_thumb_unconfigured_404(client):
    headers = _primary_headers()
    assert client.get(f"/api/photos/{FAKE_UUID}/thumb", headers=headers).status_code == 404


# ------------------------------------------------------------ happy paths ---
def test_photos_lists_day_groups(client, monkeypatch):
    """The route hands photos_for_date's moment groups through verbatim
    (SYNTHETIC label/place — the suite never touches a real library)."""
    headers = _primary_headers()
    _configure_fake_library(monkeypatch)
    groups = [
        {
            "label": "A Synthetic Outing",
            "start": "14:05",
            "end": "14:40",
            "photos": [{"uuid": FAKE_UUID, "taken_at": "14:05", "place": "Somewhere"}],
        }
    ]
    monkeypatch.setattr(photos_mod, "photos_for_date", lambda lib, day: [dict(g) for g in groups])

    res = client.get("/api/journal/2026-07-08/photos", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is True
    assert body["groups"] == groups
    assert "photos" not in body  # the flat list is gone — groups are the shape


def test_thumb_serves_cached_jpeg(client, monkeypatch, tmp_path):
    headers = _primary_headers()
    _configure_fake_library(monkeypatch)
    fake_jpeg = tmp_path / f"{FAKE_UUID}.jpg"
    fake_jpeg.write_bytes(b"\xff\xd8\xff\xe0 synthetic jpeg bytes")
    monkeypatch.setattr(photos_mod, "export_thumb", lambda lib, uuid, cache: fake_jpeg)

    res = client.get(f"/api/photos/{FAKE_UUID}/thumb", headers=headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert "private" in res.headers["cache-control"]
    assert res.content.startswith(b"\xff\xd8")


def test_thumb_unknown_uuid_404(client, monkeypatch):
    headers = _primary_headers()
    _configure_fake_library(monkeypatch)
    monkeypatch.setattr(photos_mod, "export_thumb", lambda lib, uuid, cache: None)
    assert client.get(f"/api/photos/{FAKE_UUID}/thumb", headers=headers).status_code == 404


def test_thumb_rejects_malformed_uuid(client, monkeypatch):
    """export_thumb's own uuid gate: a path-shaped 'uuid' can never become a
    cache filename. Exercised through the real function (no monkeypatched
    export), with the library configured so the gate is what says no."""
    headers = _primary_headers()
    _configure_fake_library(monkeypatch)
    res = client.get("/api/photos/not-a-uuid/thumb", headers=headers)
    assert res.status_code == 404


def test_export_thumb_refuses_bad_uuid(tmp_path):
    assert photos_mod.export_thumb("/fake/lib", "../../etc/passwd", tmp_path) is None
    assert photos_mod.export_thumb("/fake/lib", "AAAA", tmp_path) is None


def test_router_uses_gitignored_thumbs_dir():
    """data/ is gitignored (DEPLOYMENT §6) — the thumb cache must live there."""
    assert journal_router.THUMBS_DIR.name == "thumbs"
    assert journal_router.THUMBS_DIR.parent.name == "data"
